"""TEST-ARCH-001 — Application 계층 프레임워크 무-import 검사(정적 스캔).

v3.2 §2 의존성 규칙: app/application/*는 FastAPI/LangChain/SQLAlchemy/openai를 import하지 않는다.
"""

from __future__ import annotations

import pathlib
import re

_APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "application"
_FORBIDDEN = ("fastapi", "langchain", "sqlalchemy", "openai")


def _import_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("import ") or s.startswith("from "):
            lines.append(s)
    return lines


def test_arch_001_application_has_no_framework_imports():
    offenders: list[str] = []
    for py in _APP_DIR.rglob("*.py"):
        for line in _import_lines(py.read_text(encoding="utf-8")):
            for fb in _FORBIDDEN:
                if re.search(rf"\b{fb}\b", line):
                    offenders.append(f"{py.name}: {line}")
    assert offenders == [], f"Application 계층 금지 import 발견: {offenders}"


def test_application_package_exists():
    assert (_APP_DIR / "ports.py").exists()
    assert (_APP_DIR / "answer_question.py").exists()


# ── TEST-ARCH-002 — 클린아키텍처 2단계 경계 ────────────────────────────────
# 안쪽(app/core/{domain,ports,usecases})은 프레임워크도, 바깥 계층도 모른다.
# 경계를 하나만 두는 대신 그 하나는 절대 넘지 않는다.

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_INNER_DIRS = (
    _ROOT / "app" / "core" / "domain",
    _ROOT / "app" / "core" / "ports",
    _ROOT / "app" / "core" / "usecases",
)
#: 안쪽에서 import 하면 안 되는 바깥 패키지. 의존 방향은 항상 안쪽으로만.
_OUTER_PACKAGES = (
    "app.outer",
    "app.adapters",
    "app.routers",
    "app.db",
    "app.rag",
    "app.services",
    "app.mcp",
    "app.a2a",
)


def _scan_inner() -> list[tuple[pathlib.Path, str]]:
    found: list[tuple[pathlib.Path, str]] = []
    for d in _INNER_DIRS:
        if not d.exists():
            continue
        for py in d.rglob("*.py"):
            for line in _import_lines(py.read_text(encoding="utf-8")):
                found.append((py, line))
    return found


def test_arch_002_inner_layer_exists():
    missing = [str(d.relative_to(_ROOT)) for d in _INNER_DIRS if not d.exists()]
    assert missing == [], f"안쪽 계층 디렉터리 누락: {missing}"


def test_arch_002_inner_layer_has_no_framework_imports():
    offenders = [
        f"{py.relative_to(_ROOT)}: {line}"
        for py, line in _scan_inner()
        for fb in _FORBIDDEN
        if re.search(rf"\b{fb}\b", line)
    ]
    assert offenders == [], f"안쪽 계층 금지 import 발견: {offenders}"


def test_arch_002_inner_layer_does_not_import_outer():
    offenders = [
        f"{py.relative_to(_ROOT)}: {line}"
        for py, line in _scan_inner()
        for pkg in _OUTER_PACKAGES
        if re.search(rf"\b{re.escape(pkg)}\b", line)
    ]
    assert offenders == [], f"안쪽 계층이 바깥을 참조합니다(의존 방향 역전): {offenders}"


# ── ARCH-003 ─────────────────────────────────────────────────────────────
# 도메인 코드가 계층 밖에 새로 생기는 것을 막는다.
#
# ★왜 필요한가 — 실제로 그랬다.
#   `app/core/domain/insurance.py` 에 `Verdict`·`PolicyVersion` 이 이미 있는데,
#   `app/insurance/` 라는 패키지를 새로 만들어 같은 것을 또 정의했다.
#   `app/core/domain/generation.py` 가 있는데 세대 로직도 다시 짰다.
#   같은 사실이 두 곳에 있으면 반드시 갈라진다. 갈라지면 어느 쪽이 맞는지
#   아무도 모르게 된다.

#: 도메인 로직이 있어서는 안 되는 자리(패키지 이름).
_FORBIDDEN_DOMAIN_PKGS = ("app/insurance", "app/domain", "app/models")

#: 도메인 타입은 한 곳에서만 정의한다.
_SINGLE_DEFINITION = ("class Verdict", "class PolicyVersion", "class GenerationProfile")


def test_arch_003_no_domain_package_outside_core():
    """`app/insurance` 같은 경계 밖 도메인 패키지를 만들지 않는다."""
    offenders = [
        pkg for pkg in _FORBIDDEN_DOMAIN_PKGS if (_ROOT / pkg).is_dir()
    ]
    assert offenders == [], (
        f"도메인 코드는 app/core/{{domain,ports,usecases}} 에 둔다. "
        f"경계 밖 패키지 발견: {offenders}"
    )


def test_arch_003_domain_types_defined_once():
    """핵심 도메인 타입이 두 곳에서 정의되지 않는다."""
    dupes: dict[str, list[str]] = {}
    for py in (_ROOT / "app").rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for token in _SINGLE_DEFINITION:
            if re.search(rf"^{re.escape(token)}\b", text, re.M):
                dupes.setdefault(token, []).append(str(py.relative_to(_ROOT)))
    offenders = {k: v for k, v in dupes.items() if len(v) > 1}
    assert offenders == {}, f"도메인 타입이 여러 곳에 정의됨: {offenders}"


def test_arch_003_usecases_do_not_import_adapters():
    """유스케이스는 어댑터를 직접 부르지 않는다 — 포트로 주입받는다."""
    usecases = _ROOT / "app" / "core" / "usecases"
    offenders = [
        f"{py.relative_to(_ROOT)}: {line}"
        for py in usecases.rglob("*.py")
        for line in _import_lines(py.read_text(encoding="utf-8"))
        if re.search(r"\bapp\.adapters\b", line)
    ]
    assert offenders == [], f"유스케이스가 어댑터를 직접 import: {offenders}"


# ── ARCH-004 ─────────────────────────────────────────────────────────────
# 현행 코드가 레거시를 참조하지 않는다.
#
# ★왜 필요한가 — 실제로 그럴 뻔했다.
#   커머스 시딩 CSV 를 `legacy/` 로 옮기고 `settings.LEGACY_DATA_DIR` 을 만들어
#   현행 코드가 그걸 읽게 했다. 그러면 "레거시"가 아니라 **그냥 다른 폴더에 있는
#   현행 코드**다. 레거시는 통째로 지워도 되는 것이어야 한다.
#
#   그래서 압축본으로만 둔다. 이 테스트는 그 규칙이 다시 무너지지 않게 막는다.


#: 레거시를 코드로 참조하는 흔적.
_LEGACY_REF = re.compile(
    r"legacy[/\\]v\d|LEGACY_DATA_DIR|import\s+legacy|from\s+legacy"
)


def test_arch_004_current_code_does_not_reference_legacy():
    """`app/` · `tests/` · `scripts/` 가 `legacy/` 를 코드로 참조하지 않는다."""
    targets = [_ROOT / d for d in ("app", "tests", "scripts")]
    offenders: list[str] = []
    for base in targets:
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if "__pycache__" in str(py) or py.name == "test_arch.py":
                continue
            for i, line in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                stripped = line.strip()
                #: 주석·문서화 문자열의 언급은 참조가 아니다.
                if stripped.startswith("#") or stripped.startswith("*"):
                    continue
                if re.search(_LEGACY_REF, line):
                    offenders.append(f"{py.relative_to(_ROOT)}:{i}: {stripped[:70]}")
    assert offenders == [], (
        "현행 코드가 legacy/ 를 참조합니다. 레거시는 지워도 되는 것이어야 합니다:\n"
        + "\n".join(offenders)
    )


def test_arch_004_legacy_is_archived_not_importable():
    """레거시는 **압축본**으로만 둔다 — 풀린 상태로 두면 import 될 수 있다."""
    legacy = _ROOT / "legacy"
    if not legacy.exists():
        return  # 레거시가 없는 것은 정상이다
    loose = [
        str(p.relative_to(_ROOT))
        for p in legacy.rglob("*.py")
        if "__pycache__" not in str(p)
    ]
    assert loose == [], (
        f"레거시에 풀린 .py 가 있습니다. 압축해서 보관하세요: {loose[:5]}"
    )
