"""오케스트레이터: 의도 분류(LLM JSON → 실패 시 키워드 규칙)와 라우팅. # P1-AG-02"""

import json
import re

from app.agents.orchestrator.rules import classify_rules, is_high_risk
from app.agents.prompts import load_text
from app.agents.state import AGENT_INTENTS, Intent
from app.llm.base import ChatMessage, LLMClient, LLMError
from app.logging import get_logger

log = get_logger(__name__)

_VALID = {i.value for i in Intent if i is not Intent.GENERAL}  # general은 분류 대상이 아니다
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_intents(text: str) -> list[str] | None:
    """LLM 출력에서 {"intents": [...]}를 꺼낸다. 형식이 틀리면 None."""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    raw = data.get("intents") if isinstance(data, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    intents = [str(x).strip().lower() for x in raw if str(x).strip().lower() in _VALID]
    return list(dict.fromkeys(intents)) or None


def finalize_intents(intents: list[str]) -> list[str]:
    """배타 의도 정리: 고위험 > 추천 > 범위 밖. 전문 에이전트 의도는 순서 고정."""
    if Intent.HIGH_RISK in intents:
        return [Intent.HIGH_RISK.value]
    if Intent.RECOMMENDATION in intents:
        return [Intent.RECOMMENDATION.value]
    agents = [i.value for i in AGENT_INTENTS if i in intents]
    return agents or [Intent.OUT_OF_SCOPE.value]


async def classify(
    llm: LLMClient, text: str, *, has_entity: bool, history_hint: str = ""
) -> tuple[list[str], str]:
    """(의도 목록, 출처 'llm'|'rules')."""
    intents: list[str] | None = None
    try:
        user = f"{history_hint}\n질문: {text}" if history_hint else f"질문: {text}"
        resp = await llm.complete(
            [ChatMessage("system", load_text("system/classifier.md")), ChatMessage("user", user)],
            task="classify",
            json_mode=True,
            temperature=0,
            max_tokens=60,
        )
        intents = parse_intents(resp.text)
    except LLMError as e:
        log.info("classify_llm_failed", error=type(e).__name__)
    source = "llm"
    if intents is None:
        intents, source = classify_rules(text, has_entity=has_entity), "rules"
    # 안전장치: 규칙이 고위험을 잡으면 LLM 결과와 상관없이 고위험으로 본다.
    if is_high_risk(text):
        intents = [Intent.HIGH_RISK]
    return finalize_intents(intents), source
