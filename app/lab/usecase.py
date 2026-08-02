"""기능별 유즈케이스 프롬프트 팩토리 (PDF3, fastapi_llm_usage 흡수).

요약/번역/이메일/코드/문제생성 등 기능별 프롬프트를 만들고 실행한다.
빌더는 순수 함수(결정론), 실행은 chat 주입 가능.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.errors import ValidationErr

TASK_TYPES = ["summary", "translation", "email", "code", "problem"]

Complete = Callable[[str], str]


def build_usecase_prompt(task_type: str, text: str, target_lang: str = "영어") -> str:
    if task_type not in TASK_TYPES:
        raise ValidationErr(f"지원하지 않는 task_type: {task_type} (가능: {TASK_TYPES})")
    if not text.strip():
        raise ValidationErr("text가 비어 있습니다.")

    if task_type == "summary":
        return f"다음 내용을 한국어로 3문장 이내로 요약하라:\n\n{text}"
    if task_type == "translation":
        return f"다음 문장을 {target_lang}로 번역하라(번역문만 출력):\n\n{text}"
    if task_type == "email":
        return f"다음 요구사항으로 정중한 한국어 고객 응대 이메일을 작성하라:\n\n{text}"
    if task_type == "code":
        return f"다음 요구사항을 만족하는 파이썬 코드를 작성하라(코드만):\n\n{text}"
    # problem
    return f"다음 주제로 객관식 학습 문제 1개와 정답을 만들어라:\n\n{text}"


def run_usecase(task_type: str, text: str, target_lang: str = "영어",
                complete: Complete | None = None) -> str:
    prompt = build_usecase_prompt(task_type, text, target_lang)
    if complete is None:
        from app.lab.experiments import _default_complete

        return _default_complete(prompt, 0.5, 256, None)
    return complete(prompt)
