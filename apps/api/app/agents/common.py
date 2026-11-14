"""에이전트 공용 유틸."""

from app.agents.state import GraphState

LEVEL_LABEL = {"beginner": "입문", "intermediate": "중급", "expert": "숙련"}
DISCLAIMER_SPLIT = "\n---\n**고지**"  # compose.DISCLAIMER_HEADER 앞 구분


def history_text(state: GraphState, max_chars: int = 1200) -> str:
    """최근 N턴(마스킹된 저장본)을 프롬프트용 텍스트로."""
    lines = []
    for h in state.get("history") or []:
        who = "사용자" if h.get("role") == "user" else "도우미"
        lines.append(f"{who}: {str(h.get('content', ''))[:300]}")
    text = "\n".join(lines)
    return text[-max_chars:]


def prior_answer_evidence(state: GraphState) -> list[str]:
    """프롬프트의 [이전 대화]에 들어간 앞선 답변. 가드가 근거로 함께 본다.

    앞선 답변은 이미 가드를 통과한 내용이다. 후속 질문에서 그 수치를 다시 짚으면('아까 그 괴리율')
    이번 근거에는 없어 '근거 없는 수치'로 반려되고, 재작성해도 같아 안전 답변으로 끝난다.
    근거 없이 쓴 일반 대화 답변과 사용자 발화는 넣지 않는다.
    """
    return [
        str(h.get("content", ""))[:300]
        for h in state.get("history") or []
        if h.get("role") == "assistant" and h.get("intent") != "general" and h.get("content")
    ]


def history_turns(state: GraphState, max_chars: int = 2000) -> list[tuple[str, str]]:
    """최근 N턴(마스킹된 저장본)을 대화 메시지로. 답변 끝 고지 영역은 빼서 토큰을 아낀다."""
    turns: list[tuple[str, str]] = []
    for h in state.get("history") or []:
        role = "user" if h.get("role") == "user" else "assistant"
        content = str(h.get("content", "")).split(DISCLAIMER_SPLIT, 1)[0].strip()
        if content:
            turns.append((role, content[:max_chars]))
    return turns


def retry_note(state: GraphState) -> str:
    fb = state.get("retry_feedback") or []
    if not fb:
        return ""
    return (
        "\n\n[재작성 요청] 이전 답변이 준법 점검에서 반려되었습니다. 사유: "
        + "; ".join(fb)
        + "\n근거에 있는 내용만, 권유·보장·단정 표현 없이 다시 작성하세요."
    )
