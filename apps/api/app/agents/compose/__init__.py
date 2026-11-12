"""답변 합성: 에이전트 결과를 섹션으로 결합하고 의도별 필수 고지를 붙인다. # P1-AG-06

LLM으로 다시 쓰지 않는다(DB 수치·출처가 바뀌지 않도록 결정적으로 결합).
"""

from app.agents.prompts import load_yaml
from app.agents.state import AGENT_INTENTS, AgentResult, Source

SECTION_TITLE = {"etf_info": "ETF 정보", "faq": "설명", "disclosure": "공시"}
DISCLAIMER_HEADER = "---\n**고지**"


def disclaimer_texts() -> dict[str, str]:
    return {k: v["text"] for k, v in load_yaml("guard/disclaimers.yaml")["disclaimers"].items()}


def required_disclaimers(intents: list[str]) -> list[str]:
    req = load_yaml("guard/disclaimers.yaml").get("required", {})
    ids: list[str] = []
    for intent in intents:
        for d in req.get(intent, []) or []:
            if d not in ids:
                ids.append(d)
    return ids


def compose(
    intents: list[str], results: dict[str, AgentResult]
) -> tuple[str, list[Source], list[str], bool]:
    """(본문, 출처, 근거 텍스트, 전부 실패 여부)."""
    ordered = [results[i] for i in (x.value for x in AGENT_INTENTS) if i in results]
    ok = [r for r in ordered if r.ok]
    if not ok:
        return "", [], [], True
    if len(ok) == 1:
        body = ok[0].content
    else:
        body = "\n\n".join(f"### {SECTION_TITLE.get(r.agent, r.agent)}\n\n{r.content}" for r in ok)
    if len(ok) < len(ordered):
        body += "\n\n_일부 정보는 지금 가져오지 못했습니다. 잠시 후 다시 시도해 주세요._"
    sources: list[Source] = []
    seen = set()
    for r in ok:
        for s in r.sources:
            key = (s.title, s.location, s.url)
            if key not in seen:
                seen.add(key)
                sources.append(s)
    evidence = [e for r in ok for e in r.evidence]
    return body, sources, evidence, False


def render_disclaimers(ids: list[str]) -> str:
    texts = disclaimer_texts()
    lines = [f"- {texts[i]}" for i in ids if i in texts]
    return f"{DISCLAIMER_HEADER}\n" + "\n".join(lines) if lines else ""


def full_answer(body: str, disclaimer_ids: list[str]) -> str:
    block = render_disclaimers(disclaimer_ids)
    return f"{body}\n\n{block}" if block else body
