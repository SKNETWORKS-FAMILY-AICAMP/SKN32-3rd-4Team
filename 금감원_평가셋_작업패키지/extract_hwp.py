# -*- coding: utf-8 -*-
"""HWP 14건 -> 텍스트 일괄 추출.

두 포맷이 섞여 있다:
- 구 바이너리 HWP(OLE2): hwp5html로 변환 후 태그를 벗겨 순수 텍스트만 남긴다.
  (hwp5txt는 표 안 텍스트를 못 읽는데, 이 판단문들은 본문이 대부분 표 안에 있어서 사용 불가)
- 신형식 HWPX(zip, mimetype이 application/hwp+zip): hwp5html이 못 읽는다.
  zip 안 Preview/PrvText.txt에 전체 본문이 UTF-8 텍스트로 들어있어 그걸 대신 쓴다.
  (미리보기용 텍스트라 서식은 없지만, 이 판단문들처럼 표가 거의 본문 그 자체인
  문서는 오히려 hwp5html 결과와 내용 차이가 없었다 — 14건 검수 시 원본과 대조 확인할 것)
"""
import html
import re
import subprocess
import sys
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).parent
SRC_DIR = BASE_DIR / "원자료_HWP"
OUT_DIR = BASE_DIR / "원자료_HWP" / "추출_텍스트"
HWP5HTML = BASE_DIR / ".venv" / "Scripts" / "hwp5html.exe"

STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t ]+")
BLANKLINES_RE = re.compile(r"\n\s*\n+")


def html_to_text(xhtml_path: Path) -> str:
    raw = xhtml_path.read_text(encoding="utf-8")
    raw = STYLE_RE.sub(" ", raw)
    raw = raw.replace("&#13;", "\n")
    raw = TAG_RE.sub(" ", raw)
    raw = html.unescape(raw)
    return normalize_text(raw)


def normalize_text(raw: str) -> str:
    raw = WS_RE.sub(" ", raw)
    lines = [line.strip() for line in raw.split("\n")]
    text = "\n".join(line for line in lines if line)
    text = BLANKLINES_RE.sub("\n", text)
    return text.strip()


def is_hwpx(hwp_path: Path) -> bool:
    with hwp_path.open("rb") as f:
        head = f.read(4)
    return head == b"PK\x03\x04"


def hwpx_to_text(hwp_path: Path) -> str:
    with zipfile.ZipFile(hwp_path) as z:
        data = z.read("Preview/PrvText.txt")
    return normalize_text(data.decode("utf-8"))


def main():
    OUT_DIR.mkdir(exist_ok=True)
    hwp_files = sorted(SRC_DIR.glob("*.hwp"))
    print(f"대상 {len(hwp_files)}건")

    results = []
    for i, hwp_path in enumerate(hwp_files, 1):
        stem = hwp_path.stem
        txt_out_path = OUT_DIR / f"{i:02d}_{stem}.txt"

        if is_hwpx(hwp_path):
            text = hwpx_to_text(hwp_path)
            txt_out_path.write_text(text, encoding="utf-8")
            results.append((i, stem, "OK(hwpx)", len(text)))
            print(f"[OK/hwpx] {i:02d} {stem} -> {len(text)}자")
            continue

        html_out_dir = OUT_DIR / f"_html_{i:02d}"
        proc = subprocess.run(
            [str(HWP5HTML), str(hwp_path), "--output", str(html_out_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            print(f"[FAIL] {i:02d} {stem}\n{proc.stderr}")
            results.append((i, stem, "FAIL", 0))
            continue

        index_xhtml = html_out_dir / "index.xhtml"
        text = html_to_text(index_xhtml)
        txt_out_path.write_text(text, encoding="utf-8")
        results.append((i, stem, "OK", len(text)))
        print(f"[OK]   {i:02d} {stem} -> {len(text)}자")

    print("\n--- 요약 ---")
    for i, stem, status, length in results:
        flag = " ⚠짧음" if status == "OK" and length < 300 else ""
        print(f"{i:02d} [{status}] {length:>5}자{flag}  {stem}")


if __name__ == "__main__":
    main()
