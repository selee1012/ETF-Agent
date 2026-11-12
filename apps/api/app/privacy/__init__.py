"""개인정보 마스킹. 로그·트레이스·DB 저장 전에 반드시 mask_pii()를 거친다(공통 규칙 4). # P1-AG-06"""

import hashlib
import re

# 순서가 중요하다: 긴 패턴(주민번호·카드) → 짧은 패턴(전화·계좌)
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("RRN", re.compile(r"(?<!\d)\d{6}\s?-\s?[1-8]\d{6}(?!\d)")),  # 주민·외국인등록번호
    ("CARD", re.compile(r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:01[016789]|0[2-6]\d?)[- .]?\d{3,4}[- .]?\d{4}(?!\d)")),
    # 계좌번호(날짜 YYYY-MM-DD는 제외)
    (
        "ACCOUNT",
        re.compile(
            r"(?<!\d)(?!(?:19|20)\d{2}-[01]\d-[0-3]\d(?!\d))\d{3,6}-\d{2,6}-\d{2,8}(?:-\d{1,3})?(?!\d)"
        ),
    ),
    ("RRN", re.compile(r"(?<!\d)\d{2}[01]\d[0-3]\d[1-8]\d{6}(?!\d)")),  # 하이픈 없는 13자리
]


def find_pii(text: str) -> list[str]:
    """발견된 개인정보 종류 목록(중복 제거, 값은 반환하지 않는다)."""
    kinds: list[str] = []
    for kind, pat in _PATTERNS:
        if pat.search(text) and kind not in kinds:
            kinds.append(kind)
    return kinds


def mask_pii(text: str) -> str:
    """이메일·주민번호·카드·전화·계좌번호를 [EMAIL] 같은 자리표시로 바꾼다."""
    if not text:
        return text
    for kind, pat in _PATTERNS:
        text = pat.sub(f"[{kind}]", text)
    return text


def stable_hash(value: str) -> str:
    """캐시 키 등에 쓰는 SHA-256 앞 16자리(원문을 키에 남기지 않는다)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
