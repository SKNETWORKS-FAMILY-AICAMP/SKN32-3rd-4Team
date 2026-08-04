# MinerU 격리 환경 PyPI torch CPU 빌드

- 시각: 2026-08-03 19:55 KST
- 환경: Python 3.12.13 venv, torch 2.13.0(PyPI 기본 채널)
- 결과: 모델/processor 로드 후 메모리 초기화에서 `torch._C`에 `_cuda_resetPeakMemoryStats`가 없어 실패
- 원인: 기본 PyPI에서 설치한 Windows torch가 이 환경에서 CUDA 빌드가 아니었다. 기존 3.14 환경은 별도 `2.13.0+cu126` 빌드다.
- 영향: MinerU 추론 전 실패. OCR 출력 없음.
- 조치: 공식 PyTorch CUDA 12.6 wheel index에서 `+cu126` 빌드를 설치한다. 실행기 메모리 계측도 `torch.cuda.is_available()`로 보호하되, CPU 결과를 GPU 결과로 오인하지 않도록 run metadata의 `cuda_available`을 유지한다.
