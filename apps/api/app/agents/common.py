"""에이전트 공용 유틸."""

from app.agents.state import GraphState

LEVEL_LABEL = {"beginner": "입문", "intermediate": "중급", "expert": "숙련"}


def history_text(state: GraphState, max_chars: int = 1200) -> str:
    """최근 N턴(마스킹된 저장본)을 프롬프트용 텍스트로."""
    lines = []
    for h in state.get("history") or []:
        who = "사용자" if h.get("role") == "user" else "도우미"
        lines.append(f"{who}: {str(h.get('content', ''))[:300]}")
    text = "\n".join(lines)
    return text[-max_chars:]


def retry_note(state: GraphState) -> str:
    fb = state.get("retry_feedback") or []
    if not fb:
        return ""
    return (
        "\n\n[재작성 요청] 이전 답변이 준법 점검에서 반려되었습니다. 사유: "
        + "; ".join(fb)
        + "\n근거에 있는 내용만, 권유·보장·단정 표현 없이 다시 작성하세요."
    )
