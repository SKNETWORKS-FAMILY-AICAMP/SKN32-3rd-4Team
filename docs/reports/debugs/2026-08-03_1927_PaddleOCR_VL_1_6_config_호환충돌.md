# PaddleOCR-VL 1.6 config 호환 충돌

- 시각: 2026-08-03 19:27 KST
- 환경: Python 3.14.2, torch 2.13.0+cu126, transformers 5.14.1
- 재현: `AutoModelForImageTextToText.from_pretrained(..., trust_remote_code=True)`
- 결과: load 49.188초 후 `AttributeError: 'PaddleOCRVLConfig' object has no attribute 'text_config'`
- 원인: transformers 내장 `PaddleOCRVLModel`과 저장소에서 받은 remote config가 혼용됐다. 로그에도 remote `configuration_paddleocr_vl.py` 다운로드가 확인된다.
- 영향: 추론 전 load failure. OCR 출력 없음.
- 조치: 공식 모델 카드 예제와 동일하게 Paddle adapter에서 `trust_remote_code`를 제거하고 재실행한다.

## 재실행 결과

- 모델 608개 weight 항목 로드는 성공했다.
- 추론 직전 공식 예제가 참조하는 `processor.image_processor.min_pixels` 속성이 transformers 5.14.1 내장 processor에는 없어 `AttributeError`가 발생했다.
- 다운로드된 `preprocessor_config.json`에는 `min_pixels: 112896`, `max_pixels: 1003520`이 명시돼 있다.
- 실행기는 속성이 없을 때 모델 설정값 112896을 사용하도록 호환 처리했다. 값 자체를 임의 조정하지 않았다.
