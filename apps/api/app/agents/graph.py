"""에이전트 그래프(LangGraph).

질문 → preprocess → orchestrate ─┬→ etf_info ─┐  (자료 수집, LLM 없음, 동시에)
      (의도 분류 ∥ 문서 검색 선행)  ├→ faq      ─┼→ compose → guard ─┬→ END (통과)
                                ├→ disclosure┘  (LLM 1회)        ├→ retry → compose (합성만 다시)
                                ├→ compose (일반 대화, 로컬 전용)   └→ safe → END (재생성 후 실패)
                                └→ template → END

- 의도 분류(LLM)와 문서 검색(임베딩)을 동시에 보낸다. FAQ 수집은 미리 검색한 결과를 쓴다. # P1-AG-02
- 복수 의도는 수집 노드로 동시에 분기(LangGraph 병렬 superstep)하고, compose가 모은 자료로
  LLM을 한 번만 불러 하나의 답을 쓴다.
- 차단(해킹·불법·지침 무력화)·고위험·추천·범위 밖은 생성하지 않고 템플릿으로 답한다. # P1-AG-06 ③
  차단은 규칙에 걸리면 LLM 분류도 건너뛰고, 직전 답변이 차단이면 범위 밖 후속 질문도 차단한다.
- 가드 실패 시 합성만 1회 재생성, 다시 실패하면 안전 답변 + 문의 채널. # P1-AG-06
- GENERAL_CHAT_ENABLED(APP_ENV=local 전용)면 범위 밖 질문은 템플릿 대신 compose가 일반 대화로 답한다.
  ETF·투자와 무관한 추천·시점 질문('저녁 메뉴 추천해줘')도 general로 보낸다.
"""

import asyncio
from dataclasses import replace
from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app import cache
from app.agents import compose as composer
from app.agents import disclosure, etf_info, faq
from app.agents.guard import run_guard
from app.agents.guard.judge import UNVERIFIED
from app.agents.guard.templates import high_risk_answer, safe_answer, template_answer
from app.agents.orchestrator import classify
from app.agents.orchestrator.rules import is_blocked, is_domain, is_followup_info, is_search
from app.agents.preprocess import load_catalog, normalize, recognize_entities
from app.agents.state import (
    AgentDeps,
    AgentResult,
    EtfEntity,
    GraphState,
    Intent,
    Level,
    Verdict,
)
from app.llm.base import LLMError
from app.llm.tracking import LLMUsage, TrackedLLM
from app.logging import get_logger
from app.tools import etf_search

log = get_logger(__name__)

MAX_RETRIES = 1
# 자료 수집 노드(LLM 없음)
_AGENTS = {
    "etf_info": etf_info.run,
    "faq": faq.run,
    "disclosure": disclosure.run,
}


def _deps(config: RunnableConfig) -> AgentDeps:
    return config["configurable"]["deps"]


# ---------- 노드 ----------
async def preprocess_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """# P1-AG-01 정규화 + ETF명·티커 인식(오타·별칭 허용). 엔티티를 상태에 저장."""
    deps = _deps(config)
    # 첫 status("질문을 이해하는 중")는 채팅 서비스가 요청 즉시 보낸다.
    normalized = normalize(state["query"])
    catalog = await load_catalog(deps.maker)
    entities = recognize_entities(
        normalized, catalog, fuzzy_threshold=deps.settings.entity_fuzzy_threshold
    )
    return {
        "normalized": normalized,
        "entities": entities,
        "level": state.get("level") or Level.BEGINNER,
        "attempt": 0,
        "retry_feedback": [],
    }


async def orchestrate_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """# P1-AG-02 의도 분류(LLM JSON → 실패 시 키워드 규칙)."""
    deps = _deps(config)
    await deps.emit("orchestrate", "질문 유형을 파악하는 중")
    entities = state.get("entities") or []
    # 의도 분류(LLM)와 문서 검색(임베딩·DB)을 동시에 보낸다. 캐시 적중이 예상되면 검색은 생략.
    (intents, source), prefetched = await asyncio.gather(
        classify(deps.llm, state["normalized"], has_entity=bool(entities)),
        _prefetch(state, deps),
    )
    context = state.get("context_tickers") or []
    # 멀티턴: ETF 없이 정보 항목만 묻는 후속 질문('그럼 괴리율은?')은 직전 턴 ETF의 정보 질문으로 본다.
    if (
        not entities
        and context
        and intents == [Intent.FAQ]
        and is_followup_info(state["normalized"])
    ):
        intents = [Intent.ETF_INFO.value]
    # 직전 답변이 차단이었는데 ETF 질문으로 돌아오지 않았다면('허가받았어', '교육 목적이야') 계속 차단한다.
    if intents == [Intent.OUT_OF_SCOPE] and _last_blocked(state):
        intents = [Intent.BLOCKED.value]
    if deps.settings.general_chat_enabled:
        intents = _general_override(intents, state["normalized"], bool(entities or context))
    update: dict[str, Any] = {
        "intents": intents,
        "intent_source": source,
        "prefetched_chunks": prefetched,
    }
    # 이번 질문에 ETF가 없으면 직전 턴의 ETF를 이어 쓴다(ETF 정보·공시 의도일 때만).
    if not entities and context and (Intent.ETF_INFO in intents or Intent.DISCLOSURE in intents):
        catalog = {c.ticker: c for c in await load_catalog(deps.maker)}
        # 조건 검색('총보수 0.1% 이하 해외 주식 ETF 찾아줘')은 직전 ETF의 후속 질문이 아니다.
        # 직전 ETF를 넣으면 검색 대신 그 ETF의 정보표가 다시 나온다.
        if not _is_condition_search(state["normalized"], intents, catalog.values()):
            update["entities"] = [
                EtfEntity(t, catalog[t].name, "", 0.0, "context") for t in context if t in catalog
            ]
    return update


def _is_condition_search(text: str, intents: list[str], catalog: Any) -> bool:
    """ETF 이름 없이 조건(분류·지역·기초지수·보수)으로 상품을 찾는 ETF 정보 질문인지."""
    if Intent.DISCLOSURE in intents or not is_search(text):
        return False
    indexes = sorted({c.underlying_index for c in catalog if c.underlying_index})
    return not etf_search.parse_filters(text, indexes).is_empty()


async def _prefetch(state: GraphState, deps: AgentDeps) -> list[Any] | None:
    """FAQ 근거 검색을 미리 해 둔다. 실패하면 None(FAQ 수집 노드가 다시 시도한다)."""
    if faq.cached_answer(state) is not None or is_blocked(state["normalized"]):
        return None
    try:
        return await faq.retrieve(state, deps)
    except LLMError as e:
        log.info("prefetch_failed", error=type(e).__name__)
        return None


def _last_blocked(state: GraphState) -> bool:
    last = next(
        (h for h in reversed(state.get("history") or []) if h.get("role") == "assistant"), None
    )
    return bool(last) and last.get("intent") == Intent.BLOCKED


def _general_override(intents: list[str], text: str, has_etf_context: bool) -> list[str]:
    """일반 대화 모드: 범위 밖 → general. ETF·투자와 무관한 추천·고위험 패턴도 general."""
    if intents == [Intent.OUT_OF_SCOPE]:
        return [Intent.GENERAL.value]
    if (
        intents in ([Intent.RECOMMENDATION], [Intent.HIGH_RISK])
        and not has_etf_context
        and not is_domain(text)
    ):
        return [Intent.GENERAL.value]
    return intents


def _agent_node(name: str):
    async def node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        deps = _deps(config)
        try:
            result = await _AGENTS[name](state, deps)
        except LLMError as e:  # 임베딩 등 외부 호출 실패 → 이 수집만 실패 처리
            log.warning("agent_llm_failed", agent=name, error=type(e).__name__)
            result = AgentResult(agent=name, content="", ok=False, error="llm_unavailable")
        return {"results": {name: result}, "agents_called": [name]}

    node.__name__ = f"{name}_node"
    return node


async def template_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """# P1-AG-06 ③ 고위험·추천·범위 밖: 생성 없이 템플릿."""
    deps = _deps(config)
    channel = deps.settings.inquiry_channel
    intent = state["intents"][0]
    if intent == Intent.BLOCKED:
        answer, agent = template_answer("blocked", channel), "template:blocked"
    elif intent == Intent.HIGH_RISK:
        kind, answer = high_risk_answer(state["normalized"], channel)
        agent = f"template:high_risk/{kind}"
    elif intent == Intent.RECOMMENDATION:
        answer, agent = template_answer("recommendation", channel), "template:recommendation"
    else:
        answer, agent = template_answer("out_of_scope", channel), "template:out_of_scope"
    return {
        "answer": answer,
        "body": answer,
        "sources": [],
        "verdict": Verdict.TEMPLATE,
        "guard_history": [["template"]],
        "agents_called": [agent],
        "model": "template",
    }


async def compose_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    deps = _deps(config)
    await deps.emit("compose", "답변을 작성하는 중")
    intents = state["intents"]
    c = await composer.synthesize(state, deps)
    ids = composer.required_disclaimers(intents)
    return {
        "body": c.body,
        "sources": c.sources,
        "evidence": c.evidence,
        "generated": c.generated,
        "grounded": c.grounded,
        "cached": c.cached,
        "cache_key": c.cache_key,
        "disclaimer_ids": ids,
        "answer": "" if c.failed else composer.full_answer(c.body, ids),
        "verdict": Verdict.LLM_UNAVAILABLE if c.failed else "",
        "agents_called": c.agents,
    }


async def guard_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """# P1-AG-06 ① 룰 → ② 검증 모델."""
    deps = _deps(config)
    if state.get("verdict") == Verdict.LLM_UNAVAILABLE:
        return {"guard_history": [["llm_unavailable"]]}
    await deps.emit("guard", "답변을 점검하는 중")
    # 필수 고지는 '붙이기로 한 id'가 아니라 완성된 답변에 실제로 들어간 문구로 검사한다.
    required = composer.required_disclaimers(state["intents"])
    included = composer.included_disclaimers(state.get("answer") or "")
    if state.get("cached"):
        # 캐시 답변은 본문 검증을 이미 통과했다. 고지는 지금 설정으로 다시 붙였으므로 다시 본다.
        missing = [f"missing_disclaimer:{d}" for d in required if d not in included]
        res_reasons, passed = (missing, False) if missing else (["note:cache_hit"], True)
    else:
        g = await run_guard(
            deps,
            body=state["body"],
            intents=state["intents"],
            included_disclaimers=included,
            required_disclaimers=required,
            evidence=state.get("evidence") or [],
            generated=bool(state.get("generated")),
            grounded=state.get("grounded", True),
        )
        res_reasons, passed = g.reasons, g.passed
    if passed:
        verdict = Verdict.PASS if state.get("attempt", 0) == 0 else Verdict.PASS_AFTER_RETRY
        # 가드를 통과한 FAQ 단독 답변만 캐시(키 faq:{level}:{hash})
        key = state.get("cache_key")
        if key and not state.get("cached"):
            cache.faq_cache()[key] = AgentResult(
                agent=faq.NAME,
                content=state["body"],
                sources=list(state.get("sources") or []),
                evidence=list(state.get("evidence") or []),
                generated=True,
            )
        return {"verdict": verdict, "guard_history": [res_reasons]}
    if UNVERIFIED.intersection(res_reasons):
        # 검증 모델이 판정하지 못했다. 답변을 다시 써도 같으므로 재생성 없이 안전 답변으로 보낸다.
        return {"verdict": Verdict.LLM_UNAVAILABLE, "guard_history": [res_reasons]}
    return {"verdict": "", "retry_feedback": res_reasons, "guard_history": [res_reasons]}


async def retry_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    deps = _deps(config)
    await deps.emit("retry", "답변을 다시 다듬는 중")
    return {"attempt": state.get("attempt", 0) + 1}


async def safe_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    deps = _deps(config)
    verdict = (
        Verdict.LLM_UNAVAILABLE
        if state.get("verdict") == Verdict.LLM_UNAVAILABLE
        else Verdict.BLOCKED
    )
    answer = safe_answer(deps.settings.inquiry_channel)
    return {"answer": answer, "body": answer, "sources": [], "verdict": verdict}


# ---------- 라우팅 ----------
def route_intents(state: GraphState) -> list[str]:
    intents = state.get("intents") or [Intent.OUT_OF_SCOPE]
    targets = [i for i in intents if i in _AGENTS]
    if targets:
        return targets
    return ["compose"] if Intent.GENERAL in intents else ["template"]


def route_guard(state: GraphState) -> str:
    verdict = state.get("verdict")
    if verdict in (Verdict.PASS, Verdict.PASS_AFTER_RETRY):
        return "end"
    if verdict == Verdict.LLM_UNAVAILABLE:
        return "safe"
    return "retry" if state.get("attempt", 0) < MAX_RETRIES else "safe"


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(GraphState)
    g.add_node("preprocess", preprocess_node)
    g.add_node("orchestrate", orchestrate_node)
    for name in _AGENTS:
        g.add_node(name, _agent_node(name))
    g.add_node("template", template_node)
    g.add_node("compose", compose_node)
    g.add_node("guard", guard_node)
    g.add_node("retry", retry_node)
    g.add_node("safe", safe_node)

    g.add_edge(START, "preprocess")
    g.add_edge("preprocess", "orchestrate")
    agent_targets = [*_AGENTS, "compose", "template"]
    g.add_conditional_edges("orchestrate", route_intents, agent_targets)
    for name in _AGENTS:
        g.add_edge(name, "compose")
    g.add_edge("template", END)
    g.add_edge("compose", "guard")
    g.add_conditional_edges("guard", route_guard, {"end": END, "retry": "retry", "safe": "safe"})
    g.add_edge("retry", "compose")  # 재생성은 합성만 다시(자료는 이미 모았다)
    g.add_edge("safe", END)
    return g.compile()


async def run_graph(
    deps: AgentDeps,
    *,
    request_id: str,
    query: str,
    level: str | None = None,
    history: list[dict[str, Any]] | None = None,
    context_tickers: list[str] | None = None,
) -> GraphState:
    state: GraphState = {
        "request_id": request_id,
        "query": query,
        "level": level or Level.BEGINNER,
        "history": history or [],
        "context_tickers": context_tickers or [],
        "results": {},
        "agents_called": [],
        "guard_history": [],
        "model": deps.llm.model,
        "fallback_used": False,
    }
    # 에이전트는 응답 본문만 쓰므로, 폴백 사용 여부와 실제 답변 모델은 호출을 감싸서 모은다.
    usage = LLMUsage()
    deps = replace(deps, llm=TrackedLLM(deps.llm, usage))
    final: GraphState = await build_graph().ainvoke(state, config={"configurable": {"deps": deps}})
    final["fallback_used"] = usage.fallback_used
    if usage.answer_model and final.get("model") != "template":
        final["model"] = usage.answer_model
    return final
