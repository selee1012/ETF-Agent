"""일반 대화 모드(GENERAL_CHAT_ENABLED, 로컬 전용): 라우팅·근거 없는 FAQ 대체·가드 적용 범위."""

import pytest
from pydantic import ValidationError

from app.agents.general import UNGROUNDED_NOTE
from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm.base import ChatMessage
from app.llm.fake import FakeLLM
from app.settings import Settings


@pytest.fixture
def gdeps(deps: AgentDeps) -> AgentDeps:
    deps.settings = deps.settings.model_copy(update={"general_chat_enabled": True})
    return deps


def capture(llm: FakeLLM, *answers: str) -> list[list[ChatMessage]]:
    """general_answer 호출 메시지를 모으고 answers를 순서대로 돌려준다."""
    seen: list[list[ChatMessage]] = []

    def make(text: str):
        def reply(messages: list[ChatMessage]) -> str:
            seen.append(messages)
            return text

        return reply

    llm.push("general_answer", *(make(a) for a in answers))
    return seen


async def ask(deps: AgentDeps, q: str, **kw):
    return await run_graph(deps, request_id="test", query=q, **kw)


async def test_out_of_scope_goes_to_general_with_raw_query(
    gdeps: AgentDeps, fake_llm: FakeLLM
) -> None:
    seen = capture(fake_llm, "```python\ndef fib(n): ...\n```")
    q = "파이썬으로 피보나치 함수 짜줘 (def fib(n): -> int)"
    st = await ask(gdeps, q)
    assert st["intents"] == ["general"]
    assert st["verdict"] == "pass"
    assert st["answer"].startswith("```python")
    assert "**고지**" not in st["answer"]  # 일반 대화는 ETF 고지를 붙이지 않는다
    # 정규화본이 아니라 원문(기호 포함)이 모델에 간다
    assert seen[0][-1] == ChatMessage("user", q)
    assert seen[0][0].role == "system"


async def test_general_uses_history_turns_without_disclaimers(
    gdeps: AgentDeps, fake_llm: FakeLLM
) -> None:
    seen = capture(fake_llm, "네, 기억해요.")
    history = [
        {"role": "user", "content": "내 이름은 철수야"},
        {"role": "assistant", "content": "반가워요!\n\n---\n**고지**\n- 본 답변은 정보 제공 목적"},
    ]
    st = await ask(gdeps, "내 이름 기억해?", history=history)
    assert st["intents"] == ["general"]
    msgs = seen[0]
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2].content == "반가워요!"


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("오늘 저녁 메뉴 추천해줘", ["general"]),
        ("아이폰 언제 사야 돼?", ["general"]),
        ("ETF 하나 추천해줘", ["recommendation"]),
        ("샘플 코스피200 지금 사야 해?", ["high_risk"]),
        ("주식 언제 팔아야 해?", ["high_risk"]),
    ],
)
async def test_non_domain_recommendation_and_timing_go_general(
    gdeps: AgentDeps, q: str, expected: list[str]
) -> None:
    st = await ask(gdeps, q)
    assert st["intents"] == expected


async def test_faq_without_evidence_falls_back_to_general(
    gdeps: AgentDeps, fake_llm: FakeLLM
) -> None:
    capture(fake_llm, "직원 연봉은 회사마다 다르며 약 3.5% 인상이 일반적이라는 말도 있습니다.")
    st = await ask(gdeps, "ETF 회사 직원의 연봉 협상 절차는?")
    assert st["intents"] == ["faq"]
    assert st["verdict"] == "pass"  # 근거 없는 수치(3.5%)도 일반 대화에서는 막지 않는다
    assert UNGROUNDED_NOTE in st["answer"]
    assert "투자 권유가 아닙니다" in st["answer"]  # FAQ 필수 고지는 유지
    assert st["sources"] == []
    assert fake_llm.count("judge") == 0  # 근거 대비 검증 모델은 건너뛴다


async def test_faq_with_evidence_is_unchanged(gdeps: AgentDeps, fake_llm: FakeLLM) -> None:
    st = await ask(gdeps, "괴리율이 뭐야?")
    assert st["intents"] == ["faq"] and st["sources"]
    assert UNGROUNDED_NOTE not in st["answer"]
    assert fake_llm.count("general_answer") == 0


async def test_banned_phrase_in_general_answer_is_blocked(
    gdeps: AgentDeps, fake_llm: FakeLLM
) -> None:
    seen = capture(fake_llm, "이건 무조건 오릅니다.", "그래도 무조건 오릅니다.")
    st = await ask(gdeps, "오늘 날씨 어때?")
    assert st["intents"] == ["general"]
    assert st["verdict"] == "blocked"
    assert len(seen) == 2  # 1회 재생성
    assert "[재작성 요청]" in seen[1][0].content


async def test_default_off_keeps_out_of_scope_template(deps: AgentDeps) -> None:
    st = await ask(deps, "오늘 저녁 메뉴 추천해줘")
    assert st["intents"] == ["recommendation"]
    st = await ask(deps, "파이썬 코드 짜줘")
    assert st["intents"] == ["out_of_scope"] and st["verdict"] == "template"


def test_general_chat_only_allowed_in_local(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    clean_env.setenv("APP_ENV", "prod")
    clean_env.setenv("LOCAL_JWT_SECRET", "x" * 32)
    clean_env.setenv("GENERAL_CHAT_ENABLED", "true")
    with pytest.raises(ValidationError, match="APP_ENV=local"):
        Settings(_env_file=None)  # type: ignore[call-arg]
