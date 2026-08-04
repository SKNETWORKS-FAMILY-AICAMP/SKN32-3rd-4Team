# LVFace vs AdaFace 실측 — 왜 AdaFace를 유지하는가 (저품질 로그인 기준)

- 작성일시: 2026-07-21 09:00
- 계기: 사용자 재질문 "LVFace가 가장 좋다며? 오늘(2026) 기준도 그래? 더 좋은 거 있어? 더 좋은
  모델 있는데 왜 AdaFace 적용?" — 정당한 지적. LVFace를 배포 확인 없이 성급히 배제했던 걸 시인하고
  실제로 받아서 실측.

## 1. 정직한 시인
직전에 AdaFace를 고른 실제 이유는 "정확도 1위"가 아니라 **저품질 특화 + CPU/ONNX 배포 편의**였다.
LVFace를 "ViT라 무겁다"며 배포 검증 없이 배제한 것은 성급했다 — LVFace는 ONNX(MIT)로 공개돼 있고
T/S/B/L 여러 크기가 있어 CPU 배포도 가능하다.

## 2. 오늘(2026-07-21) 기준 SOTA 확인
- **LVFace(ICCV 2025 Highlight, ByteDance)**: MFR-Ongoing 학술트랙 1위, MR-All 98.49%(ViT-L/
  WebFace42M). ONNX+PyTorch 공개(HF `bytedance-research/LVFace`, MIT).
- 경쟁: TopoFR, KP-RPE, PFC 등이 IJB-C ~98%(0.01% FAR)로 근소차. LVFace를 명확히 앞서는 신모델은
  현재 확인 안 됨. **단, 이 1위는 "일반/고품질" 벤치마크 기준**이다.

## 3. 실측(동일 셋업·동일 정렬 crop, 동일인 열화 매칭 코사인 — 높을수록 좋음)
| 열화 | buffalo_l(r50) | AdaFace(IR-101) | LVFace-S(ViT) | LVFace-B(ViT) |
|---|---|---|---|---|
| 블러 k21 | 0.578 | **0.665** | 0.379 | 0.279 |
| 저조도 ×0.12 | 0.869 | **0.923** | 0.881 | 0.880 |
| 저해상 0.25배 | 0.711 | **0.772** | 0.579 | 0.456 |
| 저해상 0.15배 | 0.299 | **0.389** | 0.120 | 0.057 |
| 타인 분리(낮을수록↑) | -0.030 | -0.032 | -0.020 | 0.056 |
| CPU 임베딩(ms/장) | 103 | 553 | **96** | 171 |

## 4. 결론: 이 용도(웹캠 얼굴 로그인)엔 AdaFace가 실측상 최선
- **LVFace는 저품질(흐림·저해상)에서 buffalo_l보다도 약하다.** ViT가 이런 합성 열화(블러·다운스케일)
  에 CNN보다 민감한 것과, LVFace의 강점이 "고품질 일반 인식"에 있는 것이 겹친 결과.
- **AdaFace는 저품질 특화(quality-adaptive margin)** 설계대로 열화 전 항목 최강 — 웹캠 로그인은
  흐림·저조도·저해상이 실제 조건이라 이 강점이 정확히 필요. 사용자가 예전에 겪은 "insightface
  인식률 구렸다"의 근본 해결책.
- 트레이드오프: AdaFace는 CPU가 느리다(553ms vs LVFace-S 96ms). 로그인 1회당 1초 이내라 수용 가능.
- 그래서 **기본 = AdaFace 유지**가 데이터로 정당화됨. "LVFace가 최고"는 고품질 한정이며 이 용도엔
  틀린 선택이 됨을 실측으로 확인.

## 5. 구현(선택권 제공 + 문서화)
- `FACE_RECOGNITION`을 `adaface`(기본)/`lvface`/`insightface` 3택으로 확장. adaface·lvface는 동일
  전처리(RGB 112 [-1,1])라 `_embed`에서 ONNX만 스위치(`_get_onnx_recognizer` 공용 로더).
- `scripts/fetch_face_model.py`: lvface 선택 시 HF에서 LVFace-S ONNX 받음(gdown 아닌 hf_hub, 더 깔끔).
  LVFace-B는 저품질에 더 나빠 삭제, LVFace-S만 옵션 유지.
- 모델 파일은 gitignore(data/models). face.py 모듈 docstring에 실측 표 기록.

## 6. 검증
- `pytest -m ml tests/test_face.py` 8 passed(AdaFace 기본), LVFace 백엔드 로딩·임베딩 스모크 통과,
  전체 회귀 323 passed.

## 7. 한계(유지)
- 열화는 합성(가우시안 블러·다운스케일·밝기)이라 실 웹캠 열화와 완전 일치는 아님. 다만 AdaFace의
  저품질 우위는 문헌(TinyFace/IJB-S)과도 일치. 실 웹캠 라이브 매칭은 헤드리스 환경 미검증(유지).
- 임계 튜닝·라이브니스 정확도 미검증 한계 유지.

## 참조
- `app/ml/face.py`(_embed 3백엔드), `app/core/config.py`(FACE_RECOGNITION), `scripts/fetch_face_model.py`
