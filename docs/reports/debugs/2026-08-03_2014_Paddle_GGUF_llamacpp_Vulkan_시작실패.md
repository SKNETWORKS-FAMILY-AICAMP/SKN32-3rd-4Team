# PaddleOCR-VL 1.6 GGUF llama.cpp Vulkan 시작 실패

- 시각: 2026-08-03 20:14 KST
- 설치: 공식 안내대로 `winget install ggml.llamacpp`, b10223 Vulkan x64 빌드
- 입력: 기존 KCD p109 PNG, `Table Recognition:`, 2,048토큰
- 결과: 0.398초 후 Windows exit code `-1058471934`, stdout/stderr 없음
- 영향: 모델 다운로드·로드·추론 전 실패. GGUF 품질 결과 없음.
- 원인 범위: winget이 설치한 Vulkan 빌드의 런타임/백엔드 시작 실패. GGUF 가중치 자체의 실패로 보지 않는다.
- 조치: 같은 공식 llama.cpp 릴리스의 Windows CUDA 빌드로 재시도한다.

## CUDA 재시도

- llama.cpp b10223의 공식 Windows CUDA 12.4 실행 파일과 CUDA runtime DLL을 벤치 전용 폴더에 설치했다.
- CUDA 빌드도 0.516초 후 동일한 `0xC0E90002` Bad Image 코드로 종료됐다.
- 모델 다운로드 전이며 Vulkan/CUDA 공통으로 Windows 코드 무결성 또는 바이너리 로드 정책에 막힌 것으로 좁혀졌다.
- 호스트 보안 정책은 변경하지 않았다. GGUF 품질은 미측정으로 남긴다.
