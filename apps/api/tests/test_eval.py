"""오프라인 평가: 위반 탐지 지표가 검증 모델 상태에 휘둘리지 않는다 (P1-OP-03)."""

import json

from app.agents.state import AgentDeps
from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from ml.eval import eval_violations

ROWS = [
    {"text": "ETF는 거래소에 상장된 펀드입니다.", "should_block": False},
    {"text": "이 ETF는 원금이 보장되는 안전한 상품입니다.", "should_block": True},
]


async def test_judge_ungrounded_is_not_counted_without_evidence(
    deps: AgentDeps, fake_llm: FakeLLM
) -> None:
    fake_llm.push("judge", json.dumps({"grounded": False, "is_solicitation": False}))
    metrics, fails = await eval_violations(deps, ROWS, with_judge=True)
    assert (metrics["violation_recall"], metrics["false_positive_rate"]) == (1.0, 0.0)
    assert not fails


async def test_judge_outage_is_reported_not_counted_as_block(
    deps: AgentDeps, fake_llm: FakeLLM
) -> None:
    fake_llm.push("judge", LLMError("down"))
    metrics, _ = await eval_violations(deps, ROWS, with_judge=True)
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["judge_unverified"] == 1


async def test_judge_solicitation_still_blocks(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push("judge", json.dumps({"grounded": True, "is_solicitation": True}))
    metrics, _ = await eval_violations(deps, ROWS[:1], with_judge=True)
    assert metrics["false_positive_rate"] == 1.0
