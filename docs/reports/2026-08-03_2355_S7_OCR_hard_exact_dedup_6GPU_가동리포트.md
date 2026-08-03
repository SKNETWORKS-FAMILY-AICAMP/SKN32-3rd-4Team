# S7 OCR-hard exact dedup·6GPU 가동 리포트

## 목표

짧아진 마감에 맞춰 OCR 없이 처리 가능한 표와 설명문을 제외하고, 실제 다축 자기부담금 표 후보만 처리한다.

## 범위 축소

- 최초 production 렌더: 3,000쪽
- strict hard filter: 1,361쪽
  - 자기부담 업무어
  - 원/% 금액 신호
  - 서비스·기관·급여·플랜 축 또는 표 헤더
  - native/verified line table 없음
- exact PNG SHA-256 dedup: 832 고유 이미지
- 절약: 529 inference. 동일 픽셀이 아닌 유사 레이아웃에는 결과를 전파하지 않음

## 최종 6GPU 배분

| 장비 | GPU | 고유 이미지 |
|---|---|---:|
| x600 | RTX 4070 SUPER | 120 |
| RunPod 1 | RTX 2000 Ada | 139 |
| RunPod 2 | RTX 2000 Ada | 123 |
| RunPod 3 | RTX 4000 Ada | 122 |
| RunPod 4 | RTX 4000 Ada | 157 |
| RunPod 5 | RTX 2000 Ada | 171 |

합계 832, manifest 간 sample ID 누락·중복 0. 6장비 모두 Python PID와 GPU VRAM을 확인했다.

## 변경 파일

- `scripts/eval/select_s7_ocr_hard.py`
- `scripts/eval/allocate_s7_ocr_hard.py`
- `scripts/eval/allocate_s7_ocr_dedup6.py`
- `scripts/ops/setup_s7_ocr_hard_x600.ps1`
- `scripts/ops/run_s7_ocr_hard_x600.ps1`

## 검증

- hard filter: 3배치 입력 3,000 → 827 + 534 + 0 = 1,361
- exact image: 1,361 occurrence → 832 SHA groups, 최대 group 27
- dedup6 packet: 120+139+123+122+157+171=832
- 시작 시 RunPod 결과 오류 0, x600/RunPod 5대 PID 확인
- 기존 OCR/binder 집중 회귀: 22 passed

## ETA·미완료

- 장비별 실측 처리시간이 약 1.7시간이 되도록 배분
- 추론 1.7~2.0시간, 회수·exact alias 확장·binder·S7 결합·검증 포함 2.5~3시간
- 아직 완료 아님: 결과 회수, 529 alias 확장, candidate fact 결합, manifest/export, D1/D4/D6, 최종 Claude 검토

## 참조

- `docs/plans/2026-08-03_2208_S7_실사용_데이터셋_생성계획.md`
- `docs/reports/2026-08-03_2330_S7_전량골격과_3GPU_OCR_가동중간리포트.md`
