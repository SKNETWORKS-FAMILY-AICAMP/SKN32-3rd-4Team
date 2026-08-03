r"""
[보관용] 데이터 전처리는 이제 다른 담당자가 이어서 맡는다. 이 파일은 참고용으로만
남겨뒀고, 여기(data_preprocessing/)로 옮기면서 file_config.py를 import하는 경로가
깨졌다 - 실행하려면 file_config.py를 이 폴더로 복사하거나 import 경로를 조정할 것.

목적: pdf_to_text.py가 만들어둔 '_filtered.txt'를 읽어서,
     '제N조 (제목)' 단위로 잘라 청크로 만들고 메타데이터를 붙여 json으로 저장한다.

입력: data\<파일명>_filtered.txt (pdf_to_text.py 결과물)
결과물: data\<파일명>_chunks.json
"""

import re
import json
from file_config import FILES, get_file_paths


def split_by_article(text: str) -> list[dict]:
    """정리된 텍스트를 '제N조 (제목)' 단위로 자른다.

    정규식 설명:
      ^         -> 줄의 맨 앞 (re.MULTILINE과 함께 써야 "각 줄마다" 적용됨)
      제\\d+조   -> "제1조", "제23조"처럼 '제' + 숫자 + '조'
      \\s*\\([^)\\n]+\\) -> 그 뒤에, 같은 줄 안에서 끝나는 괄호 안 제목

    ^를 쓰는 이유:
    본문 중에는 "...제5조(보험가입금액 한도 등)에서 정한..."처럼 다른 조항을
    인용만 하는 문장이 많다. 진짜 조항 제목은 항상 줄 맨 앞에서 시작하므로,
    ^를 붙이면 문장 중간에 나오는 인용문은 대부분 걸러진다.

    괄호 안에 \\n(줄바꿈)을 못 들어오게 막은 이유:
    "요약서/가이드북" 페이지에는 "제35조(보험료의납입이연체되는경우" 처럼
    조항번호로 시작하지만 같은 줄에 닫는 괄호가 없는 가짜 제목이 있다.
    괄호 안에 줄바꿈까지 허용하면, 정규식이 몇 줄이나 떨어진 곳의 엉뚱한
    ')'까지 찾아가서 그 사이 텍스트(요약서 전체)를 통째로 본문으로
    삼켜버린다. 괄호가 "같은 줄 안에서" 끝나야만 진짜 제목으로 인정하면
    이런 가짜 매칭이 아예 발생하지 않는다 (보험사와 무관하게 적용 가능).
    """
    pattern = re.compile(r"^(제\d+조\s*\([^)\n]+\))", flags=re.MULTILINE)
    parts = pattern.split(text)

    # split 결과: [조항 시작 전 잡다한 텍스트, 제목1, 본문1, 제목2, 본문2, ...]
    chunks = []
    for i in range(1, len(parts) - 1, 2):
        title = parts[i].strip()
        body = parts[i + 1].strip()
        if not body:  # 본문이 비어있으면(제목만 있고 내용 없음) 건너뜀
            continue
        chunks.append({"title": title, "body": body})
    return chunks


def attach_metadata(chunks: list[dict], file_info: dict) -> list[dict]:
    """각 청크에 '어느 보험사/상품인지' 꼬리표를 붙인다."""
    tagged = []
    for idx, chunk in enumerate(chunks):
        tagged.append({
            "chunk_id": f"{file_info['insurer']}_{file_info['product_code']}_{file_info['product_type']}_{idx:03d}",
            "title": chunk["title"],
            "body": chunk["body"],
            **file_info,
        })
    return tagged


if __name__ == "__main__":
    for file_info in FILES:
        print(f"\n========== {file_info['insurer']} / {file_info['product_type']} 청킹 시작 ==========")

        _, filtered_path, chunks_path = get_file_paths(file_info)

        with open(filtered_path, "r", encoding="utf-8") as f:
            filtered_text = f.read()

        chunks = split_by_article(filtered_text)
        tagged_chunks = attach_metadata(chunks, file_info)

        print(f"조항 청크 개수: {len(tagged_chunks)}")
        print("앞 3개 미리보기:")
        for c in tagged_chunks[:3]:
            print(f"[{c['chunk_id']}] {c['title']}")
            print(c["body"][:100], "...")

        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(tagged_chunks, f, ensure_ascii=False, indent=2)
        print(f"청크 결과 저장 위치: {chunks_path}")
