"""답변 합성: 동시에 모은 자료(ETF 데이터·공시·근거 문서)로 LLM을 **한 번만** 불러 하나의 답을 쓴다. # P1-AG-06

- 수집 에이전트는 LLM을 부르지 않고 병렬로 자료만 모은다(LangGraph 병렬 superstep).
- 설명 문장은 LLM이 쓰고, DB 표·공시 목록은 그 아래에 결정적으로 붙인다(수치가 바뀌지 않게).
- LLM이 실패해도 DB 표·목록이 있으면 그것만으로 답한다. 근거 문서만 있는데 실패하면 '모델 응답 불가'.
- 재생성(가드 반려) 때는 이 단계만 다시 돈다(자료 수집은 반복하지 않는다).
  표·목록만 있는 답변은 재생성 때 설명 문장 없이 표·목록만 낸다(수치 왜곡 가능성 제거).
- 일반 대화(로컬 전용)와 근거 없는 FAQ의 일반 지식 답변도 여기서 만든다.
"""

from dataclasses import dataclass, field

from app.agents import faq, general
from app.agents.common import history_text, retry_note
from app.agents.prompts import load_text, load_yaml
from app.agents.state import (
    AGENT_INTENTS,
    AgentDeps,
    AgentResult,
    GraphState,
    Intent,
    Level,
    Source,
)
from app.llm.base import ChatMessage, LLMError
from app.logging import get_logger

log = get_logger(__name__)

SECTION_TITLE = {"etf_info": "ETF 정보", "faq": "설명", "disclosure": "공시", "general": "답변"}
ORDER = tuple(i.value for i in AGENT_INTENTS)
DISCLAIMER_HEADER = "---\n**고지**"
PARTIAL_NOTE = "_일부 정보는 지금 가져오지 못했습니다. 잠시 후 다시 시도해 주세요._"
# 근거 문서 없이 표·목록만 요약할 때의 출력 상한
DATA_ONLY_MAX_TOKENS = 300


@dataclass(slots=True)
class Composed:
    body: str = ""
    sources: list[Source] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    generated: bool = False
    grounded: bool = True
    cached: bool = False
    cache_key: str | None = None
    failed: bool = False  # 답할 수 없음(LLM 실패 등) → 안전 답변
    agents: list[str] = field(default_factory=list)


# ---------- 고지 ----------
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


def render_disclaimers(ids: list[str]) -> str:
    texts = disclaimer_texts()
    lines = [f"- {texts[i]}" for i in ids if i in texts]
    return f"{DISCLAIMER_HEADER}\n" + "\n".join(lines) if lines else ""


def full_answer(body: str, disclaimer_ids: list[str]) -> str:
    block = render_disclaimers(disclaimer_ids)
    return f"{body}\n\n{block}" if block else body


# ---------- 합성 ----------
def _dedupe(sources: list[Source]) -> list[Source]:
    return list({(s.title, s.location, s.url): s for s in sources}.values())


def system_prompt(level: str) -> str:
    """수준별 설명 방식 + 공통 규칙."""
    return load_text(f"system/answer_{level}.md") + "\n\n" + load_text("system/answer_rules.md")


async def _write(
    state: GraphState, deps: AgentDeps, found: list[AgentResult], *, docs: bool
) -> str:
    level = state.get("level") or Level.BEGINNER
    hist = history_text(state)
    user = (
        (f"[이전 대화]\n{hist}\n\n" if hist else "")
        + f"[질문]\n{state['normalized']}\n\n"
        + "\n\n".join(r.context for r in found if r.context)
        + retry_note(state)
    )
    resp = await deps.llm.complete(
        [ChatMessage("system", system_prompt(level)), ChatMessage("user", user)],
        task="answer",
        # 폴백 허용 의도(FALLBACK_ALLOWED_INTENTS) 판단용: 근거 문서 설명이 있으면 faq
        intent=Intent.FAQ.value if docs else found[0].agent,
        max_tokens=None if docs else DATA_ONLY_MAX_TOKENS,
    )
    return resp.text.strip()


async def _general(state: GraphState, deps: AgentDeps, *, intent: str) -> Composed:
    """근거 없이 모델 일반 지식으로 답한다(일반 대화 모드 전용)."""
    try:
        text = await general.answer(state, deps, intent=intent)
    except LLMError as e:
        log.info("general_answer_failed", error=type(e).__name__)
        return Composed(failed=True, agents=[general.NAME])
    if not text:
        return Composed(failed=True, agents=[general.NAME])
    if intent == faq.NAME:
        text = f"{text}\n\n{general.UNGROUNDED_NOTE}"
    return Composed(body=text, generated=True, grounded=False, agents=[general.NAME])


async def _no_evidence(state: GraphState, deps: AgentDeps, *, generated: bool = False) -> Composed:
    """FAQ 단독 질문에 근거 문서가 없다. 일반 대화 모드면 일반 지식으로, 아니면 '답하기 어렵다'."""
    if deps.settings.general_chat_enabled:
        return await _general(state, deps, intent=faq.NAME)
    return Composed(body=faq.NO_ANSWER, generated=generated)


async def synthesize(state: GraphState, deps: AgentDeps) -> Composed:
    intents = state.get("intents") or []
    if intents == [Intent.GENERAL]:
        return await _general(state, deps, intent=general.NAME)

    results = state.get("results") or {}
    ordered = [results[i] for i in ORDER if i in results and i in intents]
    ok = [r for r in ordered if r.ok]
    if not ok:
        return Composed(failed=True)
    faq_result = results.get(faq.NAME) if faq.NAME in intents else None

    # FAQ 단독 + 캐시 적중: 가드를 통과했던 답을 그대로 쓴다
    if intents == [Intent.FAQ] and faq_result is not None and faq_result.cached:
        return Composed(
            body=faq_result.content,
            sources=faq_result.sources,
            evidence=faq_result.evidence,
            generated=True,
            cached=True,
        )

    found = [r for r in ok if r.found]
    docs = faq_result is not None and faq_result.ok and faq_result.found
    if not found:
        if intents == [Intent.FAQ]:
            return await _no_evidence(state, deps)
        body = "\n\n".join(r.content for r in ok if r.content) or faq.NO_ANSWER
        return Composed(body=body)

    # 재생성 때 표·목록만 있는 답변은 설명 문장 없이 낸다
    prose = ""
    if docs or not state.get("retry_feedback"):
        try:
            prose = await _write(state, deps, found, docs=docs)
        except LLMError as e:
            log.info("answer_llm_failed", error=type(e).__name__)
            if all(r.agent == faq.NAME for r in found):
                return Composed(failed=True)
    if intents == [Intent.FAQ] and faq.NO_ANSWER in prose and len(prose) < len(faq.NO_ANSWER) + 20:
        return await _no_evidence(state, deps, generated=True)

    sources: list[Source] = []
    if docs and prose and faq_result is not None:
        sources += [faq_result.sources[i - 1] for i in faq.cited(prose, len(faq_result.sources))]
    blocks = [r for r in ok if r.agent != faq.NAME and r.content]
    sections = len([r for r in ok if r.found or r.content])
    parts = [faq.strip_citations(prose)] if prose else []
    for r in blocks:
        parts.append(f"### {SECTION_TITLE[r.agent]}\n\n{r.content}" if sections > 1 else r.content)
        sources += r.sources
    if (docs and not prose) or len(ok) < len(ordered):  # 근거 문서 설명을 쓰지 못했다(LLM 실패)
        parts.append(PARTIAL_NOTE)
    single_faq = intents == [Intent.FAQ]
    return Composed(
        body="\n\n".join(parts),
        sources=_dedupe(sources),
        evidence=[e for r in found for e in r.evidence],
        generated=bool(prose),
        cache_key=faq_result.cache_key if single_faq and faq_result is not None and prose else None,
    )
