"""가드 ② 검증 모델: JUDGE_MODEL이 JSON으로 근거 일치·투자권유 여부를 판정한다. # P1-AG-06"""

import json
import re
from typing import Any

from app.agents.prompts import load_text
from app.llm.base import ChatMessage, LLMClient, LLMError

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_TRUE = frozenset({"true", "yes", "y", "1", "예", "네", "참"})
_FALSE = frozenset({"false", "no", "n", "0", "아니오", "아니요", "거짓"})


def _as_bool(value: Any) -> bool | None:
    """JSON 불리언과 그 문자열 표기("false" 등)만 받아들인다. 해석할 수 없으면 None.

    bool("false")는 True라서 bool()로 바꾸면 '근거 없음' 판정이 통과로 뒤집힌다.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    return None


def parse_judge(text: str) -> dict[str, Any] | None:
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "grounded" not in data:
        return None
    grounded = _as_bool(data["grounded"])
    solicitation = _as_bool(data.get("is_solicitation", False))
    if grounded is None or solicitation is None:
        return None  # 값을 해석하지 못하면 판정 실패로 본다(통과시키지 않는다)
    issues = data.get("issues") or []
    return {
        "grounded": grounded,
        "is_solicitation": solicitation,
        "issues": [str(i)[:120] for i in issues][:5] if isinstance(issues, list) else [],
    }


# 판정을 받지 못했다는 사유. 답변을 다시 써도 해결되지 않으므로 그래프가 재생성 없이 안전 답변으로 보낸다.
UNAVAILABLE = "judge:unavailable"
UNPARSED = "judge:unparsed"
UNVERIFIED = frozenset({UNAVAILABLE, UNPARSED})


async def judge(
    llm: LLMClient, *, model: str, answer: str, evidence: list[str], intent: str | None = None
) -> tuple[list[str], dict[str, Any] | None]:
    """(실패 사유 목록, 판정 JSON).

    판정을 받지 못하면 통과시키지 않는다(검증되지 않은 답변을 내보내지 않는다).
    - 호출 실패: judge:unavailable (재시도는 LLM 어댑터가 이미 했다)
    - 응답 해석 실패: 한 번 더 물어보고, 그래도 안 되면 judge:unparsed
    intent는 폴백 허용 여부 판단용이다(근거·답변이 허용된 의도일 때만 폴백 엔드포인트로 간다).
    """
    ev = "\n\n".join(evidence)[:6000]
    messages = [
        ChatMessage("system", load_text("guard/judge.md")),
        ChatMessage("user", f"[근거]\n{ev}\n\n[답변]\n{answer}"),
    ]
    verdict = None
    for _ in range(2):
        try:
            resp = await llm.complete(
                messages,
                task="judge",
                intent=intent,
                model=model,
                json_mode=True,
                temperature=0,
                max_tokens=300,
            )
        except LLMError:
            return [UNAVAILABLE], None
        verdict = parse_judge(resp.text)
        if verdict is not None:
            break
    if verdict is None:
        return [UNPARSED], None
    reasons = []
    if not verdict["grounded"]:
        reasons.append("judge:ungrounded")
    if verdict["is_solicitation"]:
        reasons.append("judge:solicitation")
    return reasons, verdict
