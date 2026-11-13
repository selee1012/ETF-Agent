"""가드 ② 검증 모델: JUDGE_MODEL이 JSON으로 근거 일치·투자권유 여부를 판정한다. # P1-AG-06"""

import json
import re
from typing import Any

from app.agents.prompts import load_text
from app.llm.base import ChatMessage, LLMClient, LLMError

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


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
    issues = data.get("issues") or []
    return {
        "grounded": bool(data.get("grounded")),
        "is_solicitation": bool(data.get("is_solicitation", False)),
        "issues": [str(i)[:120] for i in issues][:5] if isinstance(issues, list) else [],
    }


# 판정을 받지 못했다는 사유. 답변을 다시 써도 해결되지 않으므로 그래프가 재생성 없이 안전 답변으로 보낸다.
UNAVAILABLE = "judge:unavailable"
UNPARSED = "judge:unparsed"
UNVERIFIED = frozenset({UNAVAILABLE, UNPARSED})


async def judge(
    llm: LLMClient, *, model: str, answer: str, evidence: list[str]
) -> tuple[list[str], dict[str, Any] | None]:
    """(실패 사유 목록, 판정 JSON).

    판정을 받지 못하면 통과시키지 않는다(검증되지 않은 답변을 내보내지 않는다).
    - 호출 실패: judge:unavailable (재시도는 LLM 어댑터가 이미 했다)
    - 응답 해석 실패: 한 번 더 물어보고, 그래도 안 되면 judge:unparsed
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
                messages, task="judge", model=model, json_mode=True, temperature=0, max_tokens=300
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
