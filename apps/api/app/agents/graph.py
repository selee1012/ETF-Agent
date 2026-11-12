"""에이전트 그래프(LangGraph).

질문 → preprocess → orchestrate ─┬→ etf_info ─┐
                                ├→ faq      ─┼→ compose → guard ─┬→ END (통과)
                                ├→ disclosure┘                   ├→ retry → (해당 에이전트 재실행) …
                                └→ template → END                └→ safe → END (재생성 후 실패)

- 복수 의도는 해당 에이전트 노드로 동시에 분기(LangGraph 병렬 superstep)해 compose에서 합친다. # P1-AG-02
- 고위험·추천·범위 밖은 생성하지 않고 템플릿으로 답한다. # P1-AG-06 ③
- 가드 실패 시 1회 재생성, 다시 실패하면 안전 답변 + 문의 채널. # P1-AG-06
"""

from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app import cache
from app.agents import compose as composer
from app.agents import disclosure, etf_info, faq
from app.agents.guard import run_guard
from app.agents.guard.templates import high_risk_answer, safe_answer, template_answer
from app.agents.orchestrator import classify
from app.agents.orchestrator.rules import is_followup_info
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
from app.logging import get_logger

log = get_logger(__name__)

MAX_RETRIES = 1
_AGENTS = {"etf_info": etf_info.run, "faq": faq.run, "disclosure": disclosure.run}


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
    intents, source = await classify(deps.llm, state["normalized"], has_entity=bool(entities))
    context = state.get("context_tickers") or []
    # 멀티턴: ETF 없이 정보 항목만 묻는 후속 질문('그럼 괴리율은?')은 직전 턴 ETF의 정보 질문으로 본다.
    if (
        not entities
        and context
        and intents == [Intent.FAQ]
        and is_followup_info(state["normalized"])
    ):
        intents = [Intent.ETF_INFO.value]
    update: dict[str, Any] = {"intents": intents, "intent_source": source}
    # 이번 질문에 ETF가 없으면 직전 턴의 ETF를 이어 쓴다(ETF 정보·공시 의도일 때만).
    if not entities and context and (Intent.ETF_INFO in intents or Intent.DISCLOSURE in intents):
        catalog = {c.ticker: c for c in await load_catalog(deps.maker)}
        update["entities"] = [
            EtfEntity(t, catalog[t].name, "", 0.0, "context") for t in context if t in catalog
        ]
    return update


def _agent_node(name: str):
    async def node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        deps = _deps(config)
        try:
            result = await _AGENTS[name](state, deps)
        except LLMError as e:  # LLM 실패(폴백 없음) → 이 에이전트만 실패 처리
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
    if intent == Intent.HIGH_RISK:
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
    await deps.emit("compose", "답변을 정리하는 중")
    intents = state["intents"]
    body, sources, evidence, all_failed = composer.compose(intents, state.get("results") or {})
    ids = composer.required_disclaimers(intents)
    return {
        "body": body,
        "sources": sources,
        "evidence": evidence,
        "disclaimer_ids": ids,
        "answer": "" if all_failed else composer.full_answer(body, ids),
        "verdict": Verdict.LLM_UNAVAILABLE if all_failed else "",
    }


async def guard_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """# P1-AG-06 ① 룰 → ② 검증 모델."""
    deps = _deps(config)
    if state.get("verdict") == Verdict.LLM_UNAVAILABLE:
        return {"guard_history": [["llm_unavailable"]]}
    await deps.emit("guard", "답변을 점검하는 중")
    results = state.get("results") or {}
    active = [r for r in results.values() if r.ok and r.agent in state["intents"]]
    if active and all(r.cached for r in active):
        res_reasons, passed = ["note:cache_hit"], True
    else:
        ids = state.get("disclaimer_ids") or []
        g = await run_guard(
            deps,
            body=state["body"],
            intents=state["intents"],
            included_disclaimers=ids,
            required_disclaimers=composer.required_disclaimers(state["intents"]),
            evidence=state.get("evidence") or [],
            generated=any(r.generated for r in active),
        )
        res_reasons, passed = g.reasons, g.passed
    if passed:
        verdict = Verdict.PASS if state.get("attempt", 0) == 0 else Verdict.PASS_AFTER_RETRY
        # 가드를 통과한 FAQ 답변만 캐시(키 faq:{level}:{hash})
        for r in active:
            if r.cache_key and not r.cached:
                cache.faq_cache()[r.cache_key] = r
        return {"verdict": verdict, "guard_history": [res_reasons]}
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
    return targets or ["template"]


def route_retry(state: GraphState) -> list[str]:
    """재생성 대상: 실패 사유와 무관하게 해당 의도의 에이전트를 다시 돌린다."""
    return route_intents(state)


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
    agent_targets = [*_AGENTS, "template"]
    g.add_conditional_edges("orchestrate", route_intents, agent_targets)
    for name in _AGENTS:
        g.add_edge(name, "compose")
    g.add_edge("template", END)
    g.add_edge("compose", "guard")
    g.add_conditional_edges("guard", route_guard, {"end": END, "retry": "retry", "safe": "safe"})
    g.add_conditional_edges("retry", route_retry, list(_AGENTS))
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
    return await build_graph().ainvoke(state, config={"configurable": {"deps": deps}})
