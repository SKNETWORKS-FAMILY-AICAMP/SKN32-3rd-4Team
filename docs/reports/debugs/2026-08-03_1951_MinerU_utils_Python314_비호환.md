# MinerU 공식 utils의 Python 3.14 비호환

- 시각: 2026-08-03 19:51 KST
- 명령: `python -m pip install "mineru-vl-utils[transformers]"`
- 환경: x600 Python 3.14.2
- 결과: 모든 공개 버전이 Python `<3.14` 또는 `<=3.13`을 요구해 `No matching distribution found`
- 영향: 공식 `MinerUClient.two_step_extract` 경로를 현재 가상환경에 설치할 수 없다. 모델 가중치 추론은 아직 시작하지 않았다.
- 다음 확인: x600에 Python 3.10~3.13이 별도로 있으면 격리 venv를 만들고, 없으면 Hugging Face가 제공하는 일반 transformers image-text 경로로 제한 smoke를 하되 공식 2단계 결과와 구분한다.

## Python 3.12 발견 및 launcher 표기 문제

- `py -0p`에서 Astral 관리 Python 3.12.13 경로를 발견했다.
- 일반 선택자 `py -3.12`는 이 Astral tag를 선택하지 못해 `No suitable Python runtime found`로 종료됐다.
- `py -0p`가 출력한 절대 실행 파일 경로를 직접 사용해 격리 venv를 생성한다.

## 해결

- 절대 경로의 Astral CPython 3.12.13으로 `F:\ocr_sota5_20260803\.venv312` 생성 성공.
- 공식 의존성 `mineru-vl-utils[transformers]` 1.0.5 설치 성공.
- 격리 환경 버전: torch 2.13.0, torchvision 0.28.0, transformers 4.57.6.
- 원격 실행 스크립트는 MinerU slug에만 이 환경을 사용하도록 분기했다.
