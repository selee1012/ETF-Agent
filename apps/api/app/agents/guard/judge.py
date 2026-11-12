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


async def judge(
    llm: LLMClient, *, model: str, answer: str, evidence: list[str]
) -> tuple[list[str], dict[str, Any] | None]:
    """(실패 사유 목록, 판정 JSON). 판정이 불가능하면 사유에 judge_unparsed/judge_unavailable만 남기고 통과."""
    ev = "\n\n".join(evidence)[:6000]
    try:
        resp = await llm.complete(
            [
                ChatMessage("system", load_text("guard/judge.md")),
                ChatMessage("user", f"[근거]\n{ev}\n\n[답변]\n{answer}"),
            ],
            task="judge",
            model=model,
            json_mode=True,
            temperature=0,
            max_tokens=300,
        )
    except LLMError:
        return ["note:judge_unavailable"], None
    verdict = parse_judge(resp.text)
    if verdict is None:
        return ["note:judge_unparsed"], None
    reasons = []
    if not verdict["grounded"]:
        reasons.append("judge:ungrounded")
    if verdict["is_solicitation"]:
        reasons.append("judge:solicitation")
    return reasons, verdict
