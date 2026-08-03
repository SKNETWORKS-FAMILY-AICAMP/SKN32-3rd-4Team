# S7 OCR 상대 출력 경로에서 `relative_to(ROOT)` 실패

- 발견: 2026-08-03 23:04 KST
- 위치: `scripts/eval/prepare_s7_ocr_batch.py`의 image manifest 경로 생성
- 재현: `python -m scripts.eval.prepare_s7_ocr_batch --limit 3 --out data/work/s7/ocr_batch_smoke`
- 실측: 첫 PNG 정상 생성 뒤 `ValueError: ... is not in the subpath of ROOT`
- 위험도: 중간 — 대량 렌더가 첫 페이지에서 중단되며 GPU 입력 생성이 지연됨
- 원인: CLI의 상대 `Path`를 `resolve()`하지 않고 절대 `ROOT`에 대해 `relative_to()` 호출
- 수정: build 진입 시 출력 경로를 절대 경로로 정규화
