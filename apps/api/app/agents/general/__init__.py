"""일반 대화 에이전트(개인용 로컬 전용, GENERAL_CHAT_ENABLED).

- ETF 범위 밖 질문(out_of_scope)에 LLM이 이전 대화 맥락을 이어 자유롭게 답한다.
- FAQ에서 근거 문서를 못 찾았을 때도 이 함수로 일반 지식 답변을 만든다(근거 없음 표시).
- 근거 없는 답변이므로 가드는 금칙 표현·개인정보 룰만 보고 수치 대조·검증 모델은 건너뛴다.
- 고위험·ETF 추천 질문은 여기로 오지 않는다(계속 템플릿).
"""

from app.agents.common import history_turns
from app.agents.prompts import load_text
from app.agents.state import AgentDeps, AgentResult, GraphState
from app.llm.base import ChatMessage

NAME = "general"
UNGROUNDED_NOTE = (
    "_등록된 자료에서 근거를 찾지 못해 모델의 일반 지식으로 답했습니다. 정확하지 않을 수 있습니다._"
)


def _retry_instruction(state: GraphState) -> str:
    fb = state.get("retry_feedback") or []
    if not fb:
        return ""
    return (
        "\n\n[재작성 요청] 이전 답변이 준법 점검에서 반려되었습니다. 사유: "
        + "; ".join(fb)
        + "\n투자 권유·수익 보장·단정 표현과 개인정보 없이 다시 작성하세요."
    )


async def answer(state: GraphState, deps: AgentDeps, *, intent: str = NAME) -> str:
    """이전 대화(마스킹된 저장본) + 이번 질문으로 자유 답변을 만든다. 실패하면 LLMError."""
    messages = [ChatMessage("system", load_text("system/general.md") + _retry_instruction(state))]
    messages += [ChatMessage(role, content) for role, content in history_turns(state)]
    # 정규화본은 기호·줄바꿈을 지우므로(코드·서식 손상) 원문을 쓴다. 원문은 메모리에서만 쓴다.
    messages.append(ChatMessage("user", state["query"]))
    resp = await deps.llm.complete(
        messages,
        task="general_answer",
        intent=intent,
        temperature=deps.settings.general_chat_temperature,
    )
    return resp.text.strip()


async def run(state: GraphState, deps: AgentDeps) -> AgentResult:
    await deps.emit(NAME, "답변을 생각하는 중")
    text = await answer(state, deps)
    if not text:
        return AgentResult(agent=NAME, content="", ok=False, error="empty_answer")
    return AgentResult(agent=NAME, content=text, generated=True, grounded=False)
