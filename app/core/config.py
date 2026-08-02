"""애플리케이션 설정 (단일 소스).

RULE.md 3.1(하드코딩 금지)에 따라 모델명·경로·키·DB 접속정보를 모두 여기로 모은다.
값은 .env 또는 환경변수에서 로드한다. 기본 프로바이더는 로컬 Gemma(llama-cpp-python
OpenAI 호환 서버)로, 빌드 중 외부 토큰을 소모하지 않는다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트: 이 파일은 app/core/config.py 이므로 parents[2] = 프로젝트 루트
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """전 계층이 공유하는 설정값."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 브랜드 ---
    # 몰 이름 단일 소스(RULE 3.1 하드코딩 금지). 프롬프트·API 타이틀이 전부 이 값을 참조한다.
    # 프론트엔드(정적 HTML)는 app/static/common.js의 BRAND_NAME 상수가 대응하는 단일 소스다.
    BRAND_NAME: str = "바로봄"

    # --- LLM 프로바이더 선택 ---
    LLM_PROVIDER: Literal["local", "openai", "gemini"] = "local"

    # --- 모델 레지스트리(Phase 1) ---
    # 활성 모델 '프로필 선택자'(모델 ID 자체가 아니라 model_registry.yaml의 profile_id).
    # 실제 모델 ID·revision·checksum은 model_registry.yaml에서 해석한다(RULE 3.1: 소스 모델ID 금지).
    ACTIVE_MODEL_PROFILE: str = "local_gemma4_e4b"

    # --- 로컬(Gemma GGUF, OpenAI 호환 서버) ---
    LOCAL_BASE_URL: str = "http://127.0.0.1:8000/v1"
    LOCAL_MODEL: str = "gemma-4-e4b"
    LOCAL_API_KEY: str = "not-needed"

    # --- OpenAI ---
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # --- Gemini ---
    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # --- pgvector (Phase 3, 학습 트랙) ---
    # 접속 정보(모델ID 아님) — userspace PG(conda pgv env). 미기동이면 접속 실패→명시 오류(무폴백).
    PGVECTOR_DSN: str = "host=127.0.0.1 port=5433 user=postgres dbname=mall_vec"

    # --- RAG / 임베딩 ---
    EMBEDDING_PROVIDER: Literal["local_st"] = "local_st"
    ST_EMBEDDING_MODEL: str = "jhgan/ko-sroberta-multitask"
    CHUNK_SIZE: int = 400
    CHUNK_OVERLAP: int = 50
    RAG_TOP_K: int = 3
    # 임베딩 정규화 시 거리는 [0,2] 범위 → 이 값 초과는 무관으로 간주(방어)
    RAG_MAX_DISTANCE: float = 1.5

    # --- ML (감성분석) ---
    SENTIMENT_MODEL: str = "monologg/koelectra-base-finetuned-nsmc"
    SENTIMENT_DEVICE: int = -1  # -1=CPU

    # --- 음성 (Phase 11, STT/TTS) ---
    # GPU 미검출 환경(Codex 검토) — CPU + int8로 검증한 크기만 기본값으로 둔다.
    STT_MODEL: str = "small"
    STT_DEVICE: str = "cpu"
    STT_COMPUTE_TYPE: str = "int8"
    STT_LANGUAGE: str = "ko"
    # SAPI5 보이스 ID 부분 문자열로 찾는다(전체 ID는 OS마다 다름) — 없으면 ConfigError.
    TTS_VOICE_MATCH: str = "KO-KR"

    # --- PDF 한글 폰트 (정책 문서·관리자 보고서 공용) ---
    # 없으면 조용히 깨진 글자로 만들지 않고 ConfigError(무폴백). 비Windows는 이 경로만 바꾸면 됨
    # (예: /usr/share/fonts/truetype/nanum/NanumGothic.ttf).
    PDF_FONT_REGULAR: Path = Path("C:/Windows/Fonts/malgun.ttf")
    PDF_FONT_BOLD: Path = Path("C:/Windows/Fonts/malgunbd.ttf")

    # --- 얼굴 로그인 2차 인증 (Phase 13) ---
    # 검출·정렬: insightface RetinaFace(buffalo_l, 우수). 인식 임베딩: AdaFace IR-101(기본) —
    # 저품질 벤치마크(TinyFace/IJB-S) SOTA이고 이 프로젝트에서도 열화 이미지 매칭이 ArcFace(r50)보다
    # 전 항목 우위임을 실측(블러 k21 0.578→0.665, 저해상 0.15배 0.299→0.389). 라이브니스: Silent-Face.
    FACE_EMBED_MODEL: str = "buffalo_l"  # insightface 모델팩(검출·정렬·자세, 최초 사용시 자동 다운로드)
    # 인식 백엔드 선택(실측 근거로 기본=adaface):
    #   "adaface"   — AdaFace IR-101. 저품질(흐림·저조도·저해상) 최강. CPU 느림(~550ms/장).
    #   "lvface"    — LVFace-S(ViT). 일반/고품질 벤치마크 SOTA·빠름(~96ms)이나 저품질은 오히려 약함.
    #   "insightface" — buffalo_l r50. 중간·빠름(~100ms).
    # 웹캠 로그인은 저품질이 실제 조건이라 adaface가 이 용도에 최선(LVFace의 SOTA는 고품질 한정).
    FACE_RECOGNITION: str = "adaface"
    FACE_ADAFACE_ONNX: Path = ROOT_DIR / "data" / "models" / "adaface_ir101_webface12m.onnx"
    FACE_LVFACE_ONNX: Path = ROOT_DIR / "data" / "models" / "LVFace-S_Glint360K.onnx"
    FACE_ANTISPOOF_ONNX: Path = ROOT_DIR / "data" / "models" / "minifasnet_v2.onnx"
    FACE_ANTISPOOF_SCALE: float = 2.7  # Silent-Face 2.7 모델의 크롭 스케일(원본 파이프라인 기준)
    # onnxruntime 실행 프로바이더(EP). 인식 모델(AdaFace/LVFace)은 DirectML(Windows iGPU/GPU)이
    # 훨씬 빠름(실측 AdaFace 531ms→74ms, 7배). 설치가 CPU 전용(plain onnxruntime)이면 Dml은
    # 자동으로 제외되고 CPU로 돈다(_resolve_providers가 가용한 것만 남김). 라이브니스는 초소형
    # 모델이라 DirectML 오버헤드가 더 커서 CPU 고정.
    FACE_RECOG_PROVIDERS: list[str] = ["DmlExecutionProvider", "CPUExecutionProvider"]
    FACE_LIVENESS_PROVIDERS: list[str] = ["CPUExecutionProvider"]
    # 코사인 유사도 임계(정규화 임베딩). AdaFace 기준값(타인 유사도 ~0이라 여유 큼) — 실데이터
    # 튜닝 아님(문서화). insightface 백엔드로 바꾸면 이 값도 재튜닝 필요(관례상 ~0.35~0.40).
    FACE_MATCH_THRESHOLD: float = 0.30
    # 라이브니스 live 클래스 확률 임계(0~1). 라이브러리 기본 근사 — 실환경 검증 아님(문서화).
    FACE_LIVENESS_THRESHOLD: float = 0.50
    FACE_MAX_ATTEMPTS: int = 5  # 얼굴 2차인증 연속 실패 허용 횟수(초과 시 잠금, 데모: 인메모리)
    # 지식 바운티 L1 기계 검증 임계값(docs/plans/2026-07-22_2100_지식바운티_검증모델_재설계.md).
    # 인용 대조: 인용문이 색인 원문과 **문자 수준**으로 이만큼 일치해야 통과(의미 유사도 아님).
    #   → 실제 문서명 + 원문과 의미만 비슷한 허위 문장이 통과하던 결함을 막기 위함(Codex 지적).
    # 중복성: 기존 지식과 이 유사도 이상이면 중복으로 반려.
    # ★ 두 값 모두 실 제출 데이터로 튜닝되지 않은 **시작값**이다(정직 기록).
    BOUNTY_CITATION_MATCH_THRESHOLD: float = 0.85
    BOUNTY_DUPLICATE_THRESHOLD: float = 0.95

    # 업로드 크기 상한(모델 연산 DoS 표면 축소, Codex 지적). 초과분은 무폴백으로 ValidationErr.
    FACE_MAX_UPLOAD_BYTES: int = 8 * 1024 * 1024    # 얼굴 이미지 1장 상한(8MB)
    VOICE_MAX_UPLOAD_BYTES: int = 16 * 1024 * 1024  # STT 오디오 상한(16MB)
    # 등록 다중 샷 개수 상한(파일별 상한만으로는 개수를 늘린 합산 DoS를 못 막음 — Codex 지적).
    FACE_MAX_ENROLL_IMAGES: int = 10                # 등록 요청당 이미지 최대 장수(기본 샷 3의 여유배)

    # 품질 게이팅(Codex 권고): 저품질 입력을 조용히 통과시키지 않고 명시적 재촬영 요구(무폴백).
    # 등록(strict)이 검증(loose)보다 엄격 — 나쁜 기준 임베딩이 이후 매칭을 오염시키는 걸 막는다.
    # 임계는 112×112 정렬 얼굴 기준 시작값이며 실 genuine/impostor 분포로 튜닝 필요(문서화).
    FACE_QUALITY_REGISTER: dict[str, float] = {
        "min_blur": 100.0,   # 라플라시안 분산(낮으면 흐림)
        "min_bright": 45.0, "max_bright": 210.0,  # 정렬 crop 평균 밝기
        "min_face_px": 100.0,  # 원본 얼굴 폭(px)
        "max_yaw": 15.0, "max_pitch": 15.0,  # 정면 이탈 각(roll은 정렬로 보정되어 제외)
        "min_det": 0.60,  # 검출 신뢰도
    }
    FACE_QUALITY_VERIFY: dict[str, float] = {
        "min_blur": 60.0,
        "min_bright": 35.0, "max_bright": 220.0,
        "min_face_px": 80.0,
        "max_yaw": 25.0, "max_pitch": 20.0,
        "min_det": 0.50,
    }
    # CLAHE(대비 보정)는 정상광엔 오히려 임베딩을 흔들 수 있어(실측), 정렬 crop 평균 밝기가
    # 이 값 미만일 때만 luminance 채널에 약하게 적용(등록·검증 동일 파이프라인).
    FACE_CLAHE_BRIGHTNESS: float = 80.0
    FACE_CLAHE_CLIP: float = 2.0
    FACE_ENROLL_SHOTS: int = 3  # 등록 시 촬영 장수(품질통과분 임베딩 평균 — 견고성↑)

    # --- Lab (비용 추정) ---
    # 1M 토큰당 USD [input, output]. 로컬(local)은 과금 없음이라 미등록 → 비용추정 불가.
    PRICE_TABLE: dict[str, list[float]] = {
        "gpt-4o-mini": [0.15, 0.60],
        "gemini-2.5-flash": [0.075, 0.30],
    }

    # --- 경로 / DB ---
    DATA_DIR: Path = ROOT_DIR / "data"
    DOCS_DIR: Path = ROOT_DIR / "data" / "docs"
    VECTOR_DIR: Path = ROOT_DIR / "data" / "vector_store"
    # CWD 의존을 피하기 위해 절대 경로 기반 (Codex 합의)
    DATABASE_URL: str = f"sqlite:///{(ROOT_DIR / 'data' / 'mall.db').as_posix()}"

    # --- 인증 (JWT) ---
    # SECRET_KEY는 하드코딩 금지: 미설정이면 auth 사용 시 ConfigError (RULE 3.1/3.2)
    SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    def require_secret_key(self) -> str:
        if not (self.SECRET_KEY and self.SECRET_KEY.strip()):
            from app.core.errors import ConfigError

            raise ConfigError("SECRET_KEY가 설정되지 않았습니다. .env에 SECRET_KEY를 넣으세요.")
        return self.SECRET_KEY

    def has_openai_key(self) -> bool:
        return bool(self.OPENAI_API_KEY and self.OPENAI_API_KEY.strip())

    def has_google_key(self) -> bool:
        return bool(self.GOOGLE_API_KEY and self.GOOGLE_API_KEY.strip())

    def readiness(self) -> dict[str, bool]:
        """LLM 실호출 없이 '설정/키/경로 존재 여부'만 보고한다 (Codex 합의)."""
        return {
            "local": self.LLM_PROVIDER == "local" and bool(self.LOCAL_BASE_URL),
            "openai": self.has_openai_key(),
            "gemini": self.has_google_key(),
            "db": bool(self.DATABASE_URL),
            "vector": self.VECTOR_DIR.exists(),
        }


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. 테스트에서 환경 변경 시 get_settings.cache_clear() 사용."""
    return Settings()
