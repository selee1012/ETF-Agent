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
    grounded: bool = True,
) -> GuardResult:
    reasons = check_rules(
        body,
        included_disclaimers=included_disclaimers,
        required_disclaimers=required_disclaimers,
        evidence=evidence,
        # 근거 없는 일반 대화 답변은 대조할 근거가 없어 수치 검사를 하지 않는다.
        check_numbers=grounded,
    )
    if reasons:  # 룰에서 걸리면 검증 모델을 부르지 않는다(지연·비용 절감)
        return GuardResult(passed=False, reasons=reasons)
    if not grounded:  # 검증 모델은 '근거 대비' 판정이라 일반 대화에는 쓰지 않는다
        return GuardResult(passed=True, reasons=["note:judge_skipped_ungrounded"])
    if not generated:  # DB 표·목록만으로 된 답변은 검증 모델 대상이 아니다
        return GuardResult(passed=True, reasons=["note:judge_skipped_deterministic"])
    judge_reasons, verdict = await judge(
        deps.llm,
        model=deps.settings.judge_model_name,
        answer=body,
        evidence=evidence,
        intent="+".join(str(i) for i in intents) or None,
    )
    failed = [r for r in judge_reasons if not r.startswith("note:")]
    return GuardResult(passed=not failed, reasons=judge_reasons, judge=verdict)


__all__ = ["run_guard"]
