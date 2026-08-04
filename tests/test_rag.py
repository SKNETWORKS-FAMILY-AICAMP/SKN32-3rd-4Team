"""RAG 테스트 (실제 로컬 ko-sroberta 임베딩, 토큰 0).

임시 코퍼스/인덱스로 격리한다 (실 data/vector_store 오염 방지, Codex 지적).
임베딩 모델 로드로 다소 느릴 수 있으나 외부 토큰은 쓰지 않는다.
"""

import pytest

from app.core.config import get_settings
from app.rag import service
from app.rag.build_index import build_index
from app.rag.embeddings import get_embeddings

# 실제 임베딩 모델 로드가 필요 → CI 기본 경로에서 제외 (Codex 합의)
pytestmark = pytest.mark.ml


@pytest.fixture(scope="module", autouse=True)
def _rag_env(tmp_path_factory):
    s = get_settings()
    orig_vec, orig_docs = s.VECTOR_DIR, s.DOCS_DIR
    tmp = tmp_path_factory.mktemp("rag")
    docs = tmp / "docs"
    docs.mkdir()
    (docs / "loop_safety.txt").write_text(
        "에이전트 무한루프를 막으려면 최대 단계 수를 제한하고 같은 도구를 같은 인자로 "
        "반복 호출하면 중단한다.",
        encoding="utf-8",
    )
    (docs / "tool_rules.txt").write_text(
        "좋은 도구는 한 가지 일만 하고 명확한 인자와 구체적인 독스트링을 가진다.",
        encoding="utf-8",
    )
    (docs / "refund.txt").write_text(
        "환불은 구매 후 7일 이내에 가능하며 전액 환불된다.", encoding="utf-8"
    )
    # 실제 정책 PDF도 코퍼스에 포함(TXT+PDF 혼합 인덱싱·page 메타데이터 검증)
    import shutil

    src_pdf = get_settings().DATA_DIR / "docs" / "환불교환정책.pdf"
    assert src_pdf.exists(), f"테스트 전제 PDF가 없습니다: {src_pdf}"
    shutil.copy(src_pdf, docs / "환불교환정책.pdf")
    s.VECTOR_DIR = tmp / "vec"
    s.DOCS_DIR = docs
    service.reset_store()
    build_index()
    yield
    s.VECTOR_DIR, s.DOCS_DIR = orig_vec, orig_docs
    service.reset_store()


def test_embeddings_object():
    assert get_embeddings() is not None


def test_index_is_current_detects_model_change():
    from app.rag.build_index import index_is_current

    s = get_settings()
    assert index_is_current() is True  # 방금 빌드됨
    orig = s.ST_EMBEDDING_MODEL
    try:
        s.ST_EMBEDDING_MODEL = "some/other-model"
        assert index_is_current() is False  # 모델 바뀌면 stale 감지
    finally:
        s.ST_EMBEDDING_MODEL = orig


def test_index_is_current_detects_doc_change():
    """문서를 추가하면 인덱스가 stale로 판정돼 재빌드 대상이 된다."""
    from app.rag.build_index import index_is_current

    s = get_settings()
    assert index_is_current() is True
    new_doc = s.DOCS_DIR / "extra_temp.txt"
    new_doc.write_text("새로 추가한 문서", encoding="utf-8")
    try:
        assert index_is_current() is False  # 문서 추가 → stale
    finally:
        new_doc.unlink()
    assert index_is_current() is True  # 원복 → 다시 current


def test_search_returns_relevant_with_source_and_distance():
    results = service.search("에이전트 무한루프를 어떻게 막나요?", k=3)
    assert len(results) >= 1
    assert all("source" in r and "distance" in r for r in results)
    assert results[0]["source"] == "loop_safety.txt"


def test_distance_ascending_order():
    results = service.search("도구 설계 규칙", k=3)
    distances = [r["distance"] for r in results]
    assert distances == sorted(distances)


def test_source_metadata_filter():
    # ko-sroberta는 단어 하나보다 완전한 문장 질의에서 관련 문서를 잘 찾는다
    results = service.search("환불 정책이 며칠 이내인지 알려주세요", k=5, source="refund.txt")
    assert len(results) >= 1
    assert all(r["source"] == "refund.txt" for r in results)


def test_irrelevant_query_filtered_by_distance():
    # 코퍼스와 완전히 무관한 질의 → 임계값(RAG_MAX_DISTANCE) 초과로 결과 제외.
    # 주의: 거리 임계값은 coarse 필터라 ko-sroberta가 격식체 한국어(정책 PDF 등)에는
    # 무관 질의도 중간 거리를 줄 수 있다. 확실히 먼 도메인의 질의로 검증한다.
    results = service.search("아프리카 사바나 코끼리의 계절별 이동 경로", k=3)
    assert results == []


def test_save_load_roundtrip_same_results():
    r1 = service.search("좋은 도구의 조건은 무엇인가요?", k=2)
    service.reset_store()
    r2 = service.search("좋은 도구의 조건은 무엇인가요?", k=2)
    assert [x["text"] for x in r1] == [x["text"] for x in r2]


def test_add_documents_incremental_chunked():
    res = service.add_documents(
        ["교환은 미개봉 상품에 한해 배송 후 14일 이내에 가능합니다."], ["exchange.txt"]
    )
    assert res["added"] >= 1
    service.reset_store()
    results = service.search("교환은 며칠 이내에 가능한가요?", k=3)
    assert any(r["source"] == "exchange.txt" for r in results)


# ★`test_search_knowledge_base_tool` 삭제(2026-08-04).
#   대상이던 `app/tools/commerce_tools.py` 는 v4.0 §2-3 에서 **폐기 확정**된 커머스 도구이고
#   `legacy/v3_commerce.zip` 에 들어갔다. 마커로 빼면 "인프라만 갖추면 도는 테스트"처럼
#   보이지만 사실은 **영구히 안 도는 테스트**다. 그래서 마커가 아니라 삭제한다.
#   검색 자체는 위 `test_add_documents_incremental_chunked` 가 계속 지킨다.


def test_summarize_single_chunk_mock():
    from app.rag.summarize import summarize_text

    out = summarize_text("짧은 텍스트", chat_complete=lambda p: "요약 결과")
    assert out == "요약 결과"


def test_summarize_map_reduce_mock():
    from app.rag.summarize import summarize_text

    long_text = "문장. " * 800

    def fake(prompt):
        return "부분요약" if "간단히" in prompt else "통합요약"

    assert summarize_text(long_text, chat_complete=fake) == "통합요약"


def test_pdf_indexed_with_page_metadata():
    """PDF가 인덱싱되고 검색 결과에 page(정수)가 포함되는지 (혼합 코퍼스)."""
    results = service.search("제주 지역 반품 배송비는 얼마인가요?", k=5)
    pdf_hits = [r for r in results if r["source"].endswith(".pdf")]
    assert pdf_hits, f"PDF 청크가 검색돼야 함: {[r['source'] for r in results]}"
    assert isinstance(pdf_hits[0]["page"], int), "PDF 결과는 page(정수)를 가져야 함"


def test_qa_over_pdf_with_mock_llm():
    """QA가 PDF 근거로 답변하고 출처(파일·1-based page)를 반환하는지 (mock LLM).

    Phase 8: 레거시 `rag.qa` 삭제에 따라 **AnswerQuestion 유스케이스 + rag_view 변환**
    (REST·MCP 공용 경로)으로 이관. 검증 대상(실 인덱스 근거·1-based page)은 동일.
    """
    from app.adapters.faiss_retriever import FaissRetriever
    from app.adapters.rag_view import answer_to_dict
    from app.application.answer_question import AnswerQuestion

    class _Model:
        def complete(self, prompt, *, max_tokens=None, temperature=0.0):
            return "제주 지역 왕복 반품 배송비는 10,000원입니다."

    result = AnswerQuestion(retriever=FaissRetriever(), model=_Model(), top_k=5)(
        "제주 지역 반품 배송비는 얼마인가요?"
    )
    res = answer_to_dict(result)
    assert "10,000" in res["answer"]
    assert res["sources"], "출처가 있어야 함"
    pdf_src = [s for s in res["sources"] if s["source"].endswith(".pdf")]
    assert pdf_src and isinstance(pdf_src[0]["page"], int) and pdf_src[0]["page"] >= 1
