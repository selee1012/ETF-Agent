"""컴플라이언스 가드 v1: ① 룰 → ② 검증 모델 → ③ 고위험 템플릿(그래프에서 분기). # P1-AG-06"""

from app.agents.guard.judge import judge
from app.agents.guard.rules import check_rules
from app.agents.state import AgentDeps, GuardResult


async def run_guard(
    deps: AgentDeps,
    *,
    body: str,
    intents: list[str],
    included_disclaimers: list[str],
    required_disclaimers: list[str],
    evidence: list[str],
    generated: bool,
) -> GuardResult:
    reasons = check_rules(
        body,
        included_disclaimers=included_disclaimers,
        required_disclaimers=required_disclaimers,
        evidence=evidence,
    )
    if reasons:  # 룰에서 걸리면 검증 모델을 부르지 않는다(지연·비용 절감)
        return GuardResult(passed=False, reasons=reasons)
    if not generated:  # DB 표·목록만으로 된 답변은 검증 모델 대상이 아니다
        return GuardResult(passed=True, reasons=["note:judge_skipped_deterministic"])
    judge_reasons, verdict = await judge(
        deps.llm, model=deps.settings.judge_model_name, answer=body, evidence=evidence
    )
    failed = [r for r in judge_reasons if not r.startswith("note:")]
    return GuardResult(passed=not failed, reasons=judge_reasons, judge=verdict)


__all__ = ["run_guard"]
