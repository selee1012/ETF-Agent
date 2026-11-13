"""오프라인 평가: data/eval-sets를 읽어 그래프를 직접 실행하고 지표를 낸다. # P1-OP-03

지표
- answer_accuracy: 골든셋 기대 키워드·수치가 모두 답변에 포함된 비율
- intent_accuracy: 의도 집합 일치 비율
- entity_f1: ETF명 인식 마이크로 P/R/F1
- violation_recall: 위반 문장 탐지 재현율(가드 룰, 선택적으로 검증 모델), 오탐률 함께
"""

import json
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.graph import run_graph
from app.agents.guard.judge import UNVERIFIED, judge
from app.agents.guard.rules import find_banned
from app.agents.preprocess import load_catalog, normalize, recognize_entities
from app.agents.state import AgentDeps
from app.privacy import find_pii
from app.settings import REPO_ROOT

DEFAULT_SETS = REPO_ROOT / "data" / "eval-sets"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@dataclass
class Report:
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def add(self, name: str, value: Any, failures: list[dict[str, Any]]) -> None:
        self.metrics[name] = value
        self.failures[name] = failures


async def eval_golden(deps: AgentDeps, rows: list[dict]) -> tuple[dict, list[dict]]:
    ok, fails, latencies = 0, [], []
    for r in rows:
        t0 = time.perf_counter()
        st = await run_graph(
            deps,
            request_id=f"eval-{uuid.uuid4().hex[:8]}",
            query=r["question"],
            level=r.get("level"),
        )
        latencies.append(time.perf_counter() - t0)
        ans = st.get("answer", "")
        missing = [
            k
            for k in r.get("expected_keywords", []) + r.get("expected_numbers", [])
            if k not in ans
        ]
        intent_ok = sorted(st.get("intents", [])) == sorted(r.get("expected_intents", []))
        if not missing and intent_ok:
            ok += 1
        else:
            fails.append(
                {
                    "id": r.get("id"),
                    "missing": missing,
                    "intents": st.get("intents"),
                    "verdict": st.get("verdict"),
                }
            )
    n = len(rows) or 1
    return {
        "answer_accuracy": round(ok / n, 4),
        "n": len(rows),
        "avg_latency_s": round(sum(latencies) / n, 3),
    }, fails


async def eval_intents(deps: AgentDeps, rows: list[dict]) -> tuple[dict, list[dict]]:
    ok, fails = 0, []
    for r in rows:
        st = await run_graph(deps, request_id=f"eval-{uuid.uuid4().hex[:8]}", query=r["question"])
        got = sorted(st.get("intents", []))
        if got == sorted(r["intents"]):
            ok += 1
        else:
            fails.append({"question": r["question"], "expected": r["intents"], "got": got})
    return {"intent_accuracy": round(ok / (len(rows) or 1), 4), "n": len(rows)}, fails


async def eval_aliases(deps: AgentDeps, rows: list[dict]) -> tuple[dict, list[dict]]:
    catalog = await load_catalog(deps.maker)
    tp = fp = fn = 0
    fails = []
    for r in rows:
        got = {e.ticker for e in recognize_entities(normalize(r["question"]), catalog)}
        exp = set(r["tickers"])
        tp += len(got & exp)
        fp += len(got - exp)
        fn += len(exp - got)
        if got != exp:
            fails.append({"question": r["question"], "expected": sorted(exp), "got": sorted(got)})
    p = tp / (tp + fp) if tp + fp else 1.0
    rc = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    return {
        "entity_precision": round(p, 4),
        "entity_recall": round(rc, 4),
        "entity_f1": round(f1, 4),
    }, fails


async def eval_violations(
    deps: AgentDeps, rows: list[dict], *, with_judge: bool
) -> tuple[dict, list[dict]]:
    """위반 문장 탐지. 검증 모델은 '투자 권유' 판정만 쓴다.

    평가셋에는 문장만 있고 근거가 없어 근거 일치(grounded)는 판정할 수 없다. 근거 없이 물으면
    정상 문장도 '근거 없음'이 되어 오탐률이 부풀려진다. 판정을 받지 못한 행(호출·해석 실패)은
    차단으로 세지 않고 judge_unverified로 따로 센다.
    """
    tp = fn = fp = tn = unverified = 0
    fails = []
    for r in rows:
        reasons = find_banned(r["text"]) + [f"pii:{k}" for k in find_pii(r["text"])]
        if with_judge and not reasons:
            jr, _ = await judge(
                deps.llm, model=deps.settings.judge_model_name, answer=r["text"], evidence=[]
            )
            if UNVERIFIED.intersection(jr):
                unverified += 1
            reasons += [x for x in jr if x == "judge:solicitation"]
        blocked = bool(reasons)
        if r["should_block"]:
            tp, fn = (tp + 1, fn) if blocked else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if blocked else (fp, tn + 1)
        if blocked != r["should_block"]:
            fails.append({"text": r["text"], "should_block": r["should_block"], "reasons": reasons})
    return {
        "violation_recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "with_judge": with_judge,
        "judge_unverified": unverified,
    }, fails


async def run_all(
    deps: AgentDeps, sets_dir: Path = DEFAULT_SETS, *, with_judge: bool = False
) -> Report:
    rep = Report()
    for name, fn, file in (
        ("golden", eval_golden, "golden.jsonl"),
        ("intents", eval_intents, "intents.jsonl"),
        ("aliases", eval_aliases, "aliases.jsonl"),
    ):
        metrics, fails = await fn(deps, read_jsonl(sets_dir / file))
        rep.add(name, metrics, fails)
    metrics, fails = await eval_violations(
        deps, read_jsonl(sets_dir / "violations.jsonl"), with_judge=with_judge
    )
    rep.add("violations", metrics, fails)
    return rep


def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s: str, w: int) -> str:
    return s + " " * (w - _width(s))


def render_table(rep: Report) -> str:
    rows = [("평가셋", "지표", "값")]
    for name, metrics in rep.metrics.items():
        for k, v in metrics.items():
            rows.append((name, k, str(v)))
    w = [max(_width(r[i]) for r in rows) for i in range(3)]
    line = "+".join("-" * (x + 2) for x in w)
    out = [line]
    for i, r in enumerate(rows):
        out.append("|".join(f" {_pad(c, w[j])} " for j, c in enumerate(r)))
        if i == 0:
            out.append(line)
    out.append(line)
    return "\n".join(out)
