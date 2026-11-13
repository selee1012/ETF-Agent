"""가드 ① 룰: 금칙 표현, 필수 고지 누락, 개인정보 노출, 근거 없는 수치. # P1-AG-06"""

import re
from dataclasses import dataclass
from functools import lru_cache

from app.agents.prompts import load_yaml
from app.privacy import find_pii

_CITATION = re.compile(r"\[\d{1,2}\]")
_DATE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}")
_TICKER = re.compile(r"(?<!\d)\d{6}(?!\d)")


@dataclass(frozen=True, slots=True)
class BannedRule:
    id: str
    reason: str
    pattern: re.Pattern[str]


@lru_cache(maxsize=1)
def _config() -> dict:
    return load_yaml("guard/rules.yaml")


def banned_rules() -> list[BannedRule]:
    return [BannedRule(r["id"], r["reason"], re.compile(r["pattern"])) for r in _config()["banned"]]


def find_banned(text: str) -> list[str]:
    return [f"banned:{r.id}" for r in banned_rules() if r.pattern.search(text)]


def _norm_num(int_part: str, frac: str | None, unit: str | None) -> str:
    n = int_part.replace(",", "")
    if frac:
        n = f"{n}.{frac}"
    return f"{n}{unit or ''}"


def _canon(int_part: str, frac: str | None) -> str:
    """표기만 다른 같은 값을 하나로: 쉼표·앞자리 0·소수 끝자리 0을 뗀다(0.0500 → 0.05, 36,180.00 → 36180)."""
    n = int_part.replace(",", "").lstrip("0") or "0"
    f = (frac or "").rstrip("0")
    return f"{n}.{f}" if f else n


def extract_numbers(text: str) -> list[str]:
    cfg = _config()["numbers"]
    pat = re.compile(cfg["pattern"])
    text = _CITATION.sub(" ", text)
    text = _DATE.sub(" ", text)
    text = _TICKER.sub(" ", text)
    out = []
    for m in pat.finditer(text):
        int_part, frac, unit = m.group(1), m.group(2), m.group(3)
        if cfg.get("require_unit_or_decimal", True) and not (unit or frac):
            continue
        out.append(_norm_num(int_part, frac, unit))
    return out


def ungrounded_numbers(answer: str, evidence: list[str]) -> list[str]:
    """답변 수치 중 근거 텍스트에 없는 것. 단위 없이 숫자만 일치해도 근거로 인정한다.

    값으로 비교한다: 근거가 '0.0500%'·'36,180.00원'이면 답변의 '0.05%'·'36,180원'도 근거가 있다.
    """
    cfg = _config()["numbers"]
    if not cfg.get("enabled", True):
        return []
    allow = {a.replace(" ", "") for a in cfg.get("allow", [])}
    ev_text = " ".join(evidence)
    ev_nums = set()
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?", ev_text):
        ev_nums.add(_canon(m.group(1), m.group(2)))
    missing = []
    for n in extract_numbers(answer):
        int_part, _, frac = re.sub(r"[^\d.]", "", n).partition(".")
        if n in allow or _canon(int_part, frac) in ev_nums:
            continue
        missing.append(n)
    return list(dict.fromkeys(missing))


def check_rules(
    body: str,
    *,
    included_disclaimers: list[str],
    required_disclaimers: list[str],
    evidence: list[str],
    check_numbers: bool = True,
) -> list[str]:
    reasons = find_banned(body)
    reasons += [
        f"missing_disclaimer:{d}" for d in required_disclaimers if d not in included_disclaimers
    ]
    if _config().get("pii", {}).get("enabled", True):
        reasons += [f"pii:{k}" for k in find_pii(body)]
    if check_numbers:
        reasons += [f"ungrounded_number:{n}" for n in ungrounded_numbers(body, evidence)]
    return reasons


def clear_cache() -> None:
    _config.cache_clear()
