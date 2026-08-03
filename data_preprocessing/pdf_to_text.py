r"""
[보관용] 데이터 전처리는 이제 다른 담당자가 이어서 맡는다. 이 파일은 참고용으로만
남겨뒀고, 여기(data_preprocessing/)로 옮기면서 file_config.py를 import하는 경로가
깨졌다 - 실행하려면 file_config.py를 이 폴더로 복사하거나 import 경로를 조정할 것.

목적: PDF 파일에서 텍스트를 뽑고, 목차/점선 줄만 걸러내서
     실제 필요한 내용(약관 본문, 요약서, 가이드북 등)만 텍스트 파일로 저장한다.

핵심 아이디어:
  - 목차 줄은 "점(·)이 여러 개 반복되다가 페이지번호로 끝난다"는 특징이 있다.
  - 페이지마다 텍스트를 뽑은 뒤, 한 줄씩 검사해서
    이 패턴에 맞는 줄은 버리고 나머지만 남긴다.

결과물: data\<파일명>_filtered.txt (다음 단계인 text_to_chunks.py가 이 파일을 읽는다)
"""

import pdfplumber
import re
from file_config import FILES, get_file_paths


def extract_all_text(pdf_path: str) -> str:
    """PDF의 모든 페이지에서 텍스트를 뽑아 하나의 문자열로 합친다."""
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        print(f"총 페이지 수: {len(pdf.pages)}")
        for page in pdf.pages:
            page_text = page.extract_text()  # 이 페이지의 텍스트 (없으면 None)
            if page_text:  # 텍스트가 없는 페이지(예: 표지 이미지)는 건너뜀
                full_text += page_text + "\n"

    # 한글(HWP)->PDF 변환 시 글자 사이에 널 바이트(\x00)가 잡음처럼 섞여
    # 들어가는 경우가 있다. 에디터에 따라 이 문자가 "NUL"이라는 글자로
    # 표시되기도 하지만, 실제로는 "N","U","L" 세 글자가 아니라
    # 화면에 안 보이는 특수문자 하나(\x00)다. 다음 단계(제N조 정규식 찾기)에서
    # 이게 남아있으면 패턴 매칭이 깨지므로 여기서 미리 지운다.
    full_text = full_text.replace("\x00", "")

    return full_text


# 지금까지 발견한 '노이즈 줄' 패턴들. 새로운 잡음 형태를 발견하면
# 여기에 정규식만 하나 추가하면 된다.
NOISE_LINE_PATTERNS = [
    # 목차: 점(·)이 여러 개 반복되다가 페이지번호가 나오는 줄.
    # (점 개수를 세는 대신, "점들+숫자가 있는가"를 본다 - 제목 길이에 따라
    #  점 개수가 들쭉날쭉해서 개수 기준은 파일마다 기준이 흔들렸음)
    # 줄 끝(\s*$)까지는 요구하지 않는다 - 2단 편집 PDF에서는 목차 항목
    # 두 개가 한 줄에 옆으로 붙어서 나오는 경우가 있어서
    # (예: "제14조(...)····69 제30조(...)"), 점+숫자 뒤에 다음 항목
    # 텍스트가 더 붙어있어도 그 줄 전체가 목차 줄인 건 똑같다.
    re.compile(r"·{3,}\s*\d+"),

    # '쉽게찾기' 색인: 목차랑 다르게 점 없이 "제목 바로 뒤에 페이지번호만" 있는 줄.
    # 예) "제16조(상해보험계약후알릴의무) 79"
    # 이 줄을 걸러내지 않으면 진짜 조항 시작으로 오인식되어, 본문이 "79"처럼
    # 페이지번호 하나만 남는 가짜 청크가 생긴다.
    re.compile(r"^제\d+조\s*\([^)]*\)\s*\d{1,3}\s*$"),

    # 페이지 머리말/꼬리말: "보통약관 41"처럼 페이지마다 반복되는 줄.
    # 주의: "보통약관"/"특별약관"은 현대해상 PDF에 실제로 쓰인 문구라서,
    # 다른 보험사 PDF는 문구 자체가 다를 수 있다 (그때는 이 목록에 추가해야 함).
    re.compile(r"^(보통약관|특별약관)\s*\d{1,3}\s*$"),

    # 목차 섹션 제목 줄: "특별약관 목차", "별표 목차"처럼 짧게 끝나는 줄.
    # 20자 이하로 짧은 줄만 대상으로 해서, 본문 중에 우연히 '목차'라는
    # 단어가 들어간 긴 문장까지 잘못 지우지 않게 한다.
    re.compile(r"^.{0,20}목차\s*$"),
]


def filter_noise_lines(text: str) -> tuple[list[str], int]:
    """줄 단위로 검사해서, 알려진 노이즈 패턴에 맞는 줄만 걸러낸다."""
    kept_lines = []
    removed_count = 0

    for line in text.split("\n"):  # 한 줄씩 순서대로 꺼낸다
        if any(pattern.search(line) for pattern in NOISE_LINE_PATTERNS):
            # 노이즈 줄로 판단 -> 버리고 다음 줄로 넘어간다
            removed_count += 1
            continue

        kept_lines.append(line)

    return kept_lines, removed_count


if __name__ == "__main__":
    for file_info in FILES:
        print(f"\n========== {file_info['insurer']} / {file_info['product_type']} 처리 시작 ==========")

        pdf_path, filtered_path, _ = get_file_paths(file_info)

        raw_text = extract_all_text(pdf_path)
        kept_lines, removed_count = filter_noise_lines(raw_text)
        filtered_text = "\n".join(kept_lines)

        with open(filtered_path, "w", encoding="utf-8") as f:
            f.write(filtered_text)

        print(f"버려진 줄 수: {removed_count}")
        print(f"남은 줄 수: {len(kept_lines)}")
        print(f"저장 위치: {filtered_path}")
