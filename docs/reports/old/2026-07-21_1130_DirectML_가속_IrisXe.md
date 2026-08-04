# 얼굴 인식 DirectML 가속 (Windows 11 · Intel Iris Xe)

- 작성일시: 2026-07-21 11:30
- 계기: 사용자 질문 "insightface는 따로 속도 개선(빌더) 필요하지 않냐? 다른 애들은? AdaFace도?
  Windows 11 기준." → 벤치마크 ms의 정체 규명 + 가속 실측 후 적용.

## 1. 오해 교정 2가지
- **벤치마크 ms는 부풀려진 값**: facebench가 찍은 지연은 최초 호출(모델 로딩 포함)이라 정상
  속도보다 큼. 워밍업 후 CPU 실측: insightface 123ms, AdaFace 512ms, LVFace 108ms.
- **"빌더"는 모델별로 따로가 아님**: 셋 다 onnxruntime 위에서 돎 → 가속은 **실행 프로바이더(EP)
  교체** 한 가지 방법으로 세 모델에 동일 적용. insightface만 별도 빌더가 필요한 구조 아님.

## 2. 환경 확인
- GPU: **Intel Iris Xe(내장), NVIDIA 없음** → CUDA/TensorRT("빌더" 있는 그것) 불가.
- 설치 EP: `['Azure','CPU']`뿐이었음(가속 미사용).
- Windows 11 + Iris Xe에 맞는 가속 = **DirectML**(DX12 iGPU에서 동작, CUDA 불필요).

## 3. DirectML 설치·실측 (사용자 선택: "설치해서 실측")
`onnxruntime` → `onnxruntime-directml==1.24.4` 교체(공존 불가). Iris Xe에서 워밍업 후:
| 모델 | CPU | DirectML | 배속 |
|---|---|---|---|
| AdaFace(112) | 530.8ms | **74.3ms** | **7.1×** |
| LVFace-S(112) | 90.6ms | 64.3ms | 1.4× |
| MiniFASNet(80, 라이브니스) | 3.4ms | 6.4ms | 오히려 느림 |

→ **AdaFace 7배 가속**이 핵심(유일 단점이던 느림이 사실상 해소 — 저품질 최강 + 속도 확보).
라이브니스는 초소형 모델이라 DirectML 오버헤드가 커서 CPU가 나음.

## 4. 적용
- config: `FACE_RECOG_PROVIDERS=["DmlExecutionProvider","CPUExecutionProvider"]`(인식),
  `FACE_LIVENESS_PROVIDERS=["CPUExecutionProvider"]`(라이브니스 CPU 고정).
- `app/ml/face.py`: `_resolve_providers()`가 **실제 가용한 EP만 남김**(plain onnxruntime·GPU
  없음이면 Dml 자동 제외→CPU). 인식 세션은 DirectML, 라이브니스는 CPU. 존재하지 않는 EP로
  세션이 깨지는 것 방지(가용성 기반, 조용한 성능저하 아님).
- requirements: `onnxruntime-directml==1.24.4`(Windows). 비Windows/GPU 없음이면 plain
  onnxruntime로 교체해도 코드가 가용 EP만 자동 사용.
- 실 앱 경로 확인: `_get_onnx_recognizer(AdaFace)` EP=DmlExecutionProvider, `_embed(adaface)`
  워밍업 후 **77.5ms**(530→77). 라이브니스 세션 EP=CPU.

## 5. 검증
- 전체 회귀 **324 passed**, 얼굴 **8 passed**(DirectML로), 음성 **3 passed**(onnxruntime 버전
  교체가 faster-whisper에 무영향). onnxruntime 1.20.1→1.24.4 API 호환.

## 6. 정직한 한계
- Iris Xe 기준 실측이며 다른 GPU/드라이버에선 배속이 다를 수 있음. DirectML은 Windows 전용.
- 합성 얼굴(t1)·워밍업 후 단일 이미지 기준. 실 웹캠 연속 로그인 부하는 별도.
- onnxruntime-directml은 Windows 전용이라 CI/타 OS에선 plain onnxruntime 필요(코드는 대응됨).

## 참조
- `app/core/config.py`(FACE_RECOG/LIVENESS_PROVIDERS), `app/ml/face.py`(_resolve_providers),
  `requirements.txt`
