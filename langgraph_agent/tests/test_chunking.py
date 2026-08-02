

"""
tests/test_chunking.py

역할:
    rag/chunking.py의 조문 분리 로직이 정확히 동작하는지 검증.
    특히 "제N조의M" 같은 예외 패턴이 안 깨지는지 확인.

실행:
    pytest tests/test_chunking.py -v
"""

from rag.chunking import chunk_by_article, extract_generation


def test_extract_generation():
    assert extract_generation("gen3_standard_2018.txt") == "3세대"
    assert extract_generation("random_file.txt") == "unknown"


def test_chunk_by_article_basic():
    text = "머리말\n제1조(목적) 이것은 목적입니다.\n제2조(정의) 이것은 정의입니다."
    chunks = chunk_by_article(text, "gen1_standard.txt")

    # 메타정보(머리말) + 제1조 + 제2조 = 3개
    assert len(chunks) == 3
    assert chunks[1].metadata["article_no"] == "제1조"
    assert chunks[2].metadata["article_no"] == "제2조"
    assert all(c.metadata["generation"] == "1세대" for c in chunks)


def test_chunk_by_article_handles_sub_articles():
    """'제4조의2'처럼 '조의N' 패턴이 별도 조문으로 안전하게 분리되는지 확인."""
    text = "제4조(보상하지 않는 사항) 본문1\n제4조의2(특별약관) 본문2"
    chunks = chunk_by_article(text, "gen3_standard_2018.txt")

    article_nos = [c.metadata["article_no"] for c in chunks]
    assert "제4조" in article_nos
    assert "제4조의2" in article_nos
