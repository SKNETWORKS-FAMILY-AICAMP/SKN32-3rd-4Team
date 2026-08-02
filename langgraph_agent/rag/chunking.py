"""
rag/chunking.py

역할:
    세대별 약관 원문(.txt)을 "제N조(제목)" 단위로 청킹한다.
    각 청크에는 generation, article_no, article_title 메타데이터가 붙는다.

    이 메타데이터가 build_vectorstore.py에서 벡터DB 저장 시 그대로 쓰이고,
    search_policy.py에서 세대 필터링의 기준이 된다.

파일명 규칙:
    data/policy_docs/gen{N}_standard_{연도}.txt
    예: gen3_standard_2018.txt -> "3세대"로 자동 인식
"""

import re
from pathlib import Path
from langchain_core.documents import Document


def extract_generation(filename: str) -> str:
    match = re.match(r"gen(\d)_", filename)
    return f"{match.group(1)}세대" if match else "unknown"


def chunk_by_article(text: str, source_file: str) -> list[Document]:
    """'제N조(제목)' 패턴 기준으로 텍스트를 조문 단위 Document 리스트로 분할."""
    generation = extract_generation(source_file)
    pattern = r"(제\d+조(?:의\d+)?\([^)]+\))"
    parts = re.split(pattern, text)

    documents = []

    if parts[0].strip():
        documents.append(
            Document(
                page_content=parts[0].strip(),
                metadata={
                    "source_file": source_file,
                    "generation": generation,
                    "article_no": "메타정보",
                    "article_title": "문서 메타정보 및 목차",
                },
            )
        )

    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        title = parts[i].strip()
        body = parts[i + 1].strip()
        article_no_match = re.match(r"(제\d+조(?:의\d+)?)", title)
        article_no = article_no_match.group(1) if article_no_match else title

        documents.append(
            Document(
                page_content=f"{title}\n{body}",
                metadata={
                    "source_file": source_file,
                    "generation": generation,
                    "article_no": article_no,
                    "article_title": title,
                },
            )
        )

    return documents


def chunk_all_policy_docs(policy_docs_dir: Path) -> list[Document]:
    """policy_docs 디렉토리 안의 모든 .txt 파일을 청킹해서 하나의 리스트로 합침."""
    all_documents = []
    for txt_file in policy_docs_dir.glob("*.txt"):
        text = txt_file.read_text(encoding="utf-8")
        all_documents.extend(chunk_by_article(text, txt_file.name))
    return all_documents
