# x600 OvisOCR2 smoke: torchvision 누락

- 시각: 2026-08-03 19:22 KST
- 재현: Pillow 설치 후 OvisOCR2 동일 smoke 재실행
- 결과: 모델 processor 로드 14.691초 후 `Qwen3VLVideoProcessor requires the Torchvision library`
- 환경: Python 3.14.2, torch 2.13.0+cu126, transformers 5.14.1, RTX 4070 SUPER
- 영향: processor 로드 단계 실패. 모델 추론 및 OCR 출력 없음.
- 조치: 현재 torch와 pip resolver가 호환되는 torchvision wheel을 설치하고 버전을 기록한 뒤 재실행한다.
