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
    """답변 수치 중 근거 텍스트에 없는 것. 단위 없이 숫자만 일치해도 근거로 인정한다."""
    cfg = _config()["numbers"]
    if not cfg.get("enabled", True):
        return []
    allow = {a.replace(" ", "") for a in cfg.get("allow", [])}
    ev_text = " ".join(evidence)
    ev_nums = set()
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?", ev_text):
        ev_nums.add(_norm_num(m.group(1), m.group(2), None))
    missing = []
    for n in extract_numbers(answer):
        bare = re.sub(r"[^\d.]", "", n)
        if n in allow or bare in ev_nums:
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
