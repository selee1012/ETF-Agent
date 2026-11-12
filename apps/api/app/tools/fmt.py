"""수치 표기. 답변과 가드 근거가 같은 문자열을 쓰도록 여기서만 포맷한다."""

from decimal import Decimal


def won(v: Decimal | int | None, digits: int = 0) -> str:
    if v is None:
        return "-"
    return f"{Decimal(v):,.{digits}f}원"


def pct(v: Decimal | None, digits: int = 2) -> str:
    return "-" if v is None else f"{Decimal(v):.{digits}f}%"


def fee(v: Decimal | None) -> str:
    """총보수는 연 %, 소수 넷째 자리까지(뒤 0 제거 안 함: 공시 표기와 맞춤)."""
    return "-" if v is None else f"연 {Decimal(v):.4f}%"


def shares(v: int | None) -> str:
    return "-" if v is None else f"{v:,}주"


def eok(v: int | None) -> str:
    """원 → 억 원(소수 없이)."""
    return "-" if v is None else f"{round(v / 100_000_000):,}억 원"
