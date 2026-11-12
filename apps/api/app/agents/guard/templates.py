"""가드 ③ 고위험 의도 고정 답변. 첫 줄에 '준법감시 승인 전 초안' 표기. # P1-AG-06"""

import re

from app.agents.prompts import render_template

HIGH_RISK_KINDS = ("buy_sell_timing", "return_forecast", "personal_tax", "loss_compensation")

_KIND_RULES = [
    ("loss_compensation", re.compile(r"(손실|손해).{0,12}(보상|보전|물어|책임|배상|돌려)")),
    ("personal_tax", re.compile(r"세금|양도세|배당소득세|종합과세|건보료")),
    ("return_forecast", re.compile(r"오를|내릴|떨어질|전망|예측|예상|얼마나|목표|폭락|급등")),
]


def high_risk_kind(text: str) -> str:
    for kind, pat in _KIND_RULES:
        if pat.search(text):
            return kind
    return "buy_sell_timing"


def high_risk_answer(text: str, inquiry_channel: str) -> tuple[str, str]:
    kind = high_risk_kind(text)
    return kind, render_template(f"templates/high_risk/{kind}.md", inquiry_channel=inquiry_channel)


def template_answer(name: str, inquiry_channel: str) -> str:
    return render_template(f"templates/{name}.md", inquiry_channel=inquiry_channel)


def safe_answer(inquiry_channel: str) -> str:
    return template_answer("safe_answer", inquiry_channel)
