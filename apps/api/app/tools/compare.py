"""ETF 정보 표·2~3개 상품 비교표(마크다운). 숫자는 DB 값만 쓴다. # P1-AG-03"""

from collections.abc import Sequence
from datetime import date

from app.repositories.models import EtfMaster, PriceDaily
from app.tools import fmt

_ROWS = [
    ("종목코드", lambda e, p: e.ticker),
    ("운용사", lambda e, p: e.issuer or "-"),
    ("기초지수", lambda e, p: e.underlying_index or "-"),
    ("분류", lambda e, p: e.category or "-"),
    ("총보수", lambda e, p: fmt.fee(e.total_expense_ratio)),
    ("종가", lambda e, p: fmt.won(p.close_price) if p else "-"),
    ("NAV", lambda e, p: fmt.won(p.nav, 2) if p else "-"),
    ("괴리율", lambda e, p: fmt.pct(p.premium_discount) if p else "-"),
    ("거래량", lambda e, p: fmt.shares(p.volume) if p else "-"),
    ("순자산", lambda e, p: fmt.eok(p.net_assets) if p else "-"),
    ("상장일", lambda e, p: e.listed_date.isoformat() if e.listed_date else "-"),
    # 시세 기준일은 상품마다 다를 수 있다(거래 정지·수집 누락). 열마다 자기 날짜를 적는다.
    ("시세 기준일", lambda e, p: p.trade_date.isoformat() if p else "-"),
]


def as_of_dates(prices: Sequence[PriceDaily | None]) -> list[date]:
    """시세 기준일(중복 없이 오름차순). 상품마다 다르면 둘 이상이 나온다."""
    return sorted({p.trade_date for p in prices if p is not None})


def as_of_text(dates: Sequence[date]) -> str | None:
    """기준일 표기. 날짜가 여럿이면 가장 최근 날짜 하나로 뭉뚱그리지 않고 범위로 적는다."""
    if not dates:
        return None
    if len(dates) == 1:
        return dates[0].isoformat()
    return f"{dates[0].isoformat()} ~ {dates[-1].isoformat()}"


def _cell(s: str) -> str:
    return s.replace("|", "/")


def detail_table(etf: EtfMaster, price: PriceDaily | None) -> str:
    lines = [f"| 항목 | {_cell(etf.name)} |", "| --- | --- |"]
    lines += [f"| {label} | {_cell(fn(etf, price))} |" for label, fn in _ROWS]
    return "\n".join(lines)


def compare_table(etfs: Sequence[EtfMaster], prices: dict[str, PriceDaily]) -> str:
    head = "| 항목 | " + " | ".join(_cell(e.name) for e in etfs) + " |"
    sep = "| --- |" + " --- |" * len(etfs)
    body = [
        f"| {label} | " + " | ".join(_cell(fn(e, prices.get(e.ticker))) for e in etfs) + " |"
        for label, fn in _ROWS
    ]
    return "\n".join([head, sep, *body])


def list_table(etfs: Sequence[EtfMaster]) -> str:
    lines = ["| 이름 | 종목코드 | 분류 | 기초지수 | 총보수 |", "| --- | --- | --- | --- | --- |"]
    lines += [
        f"| {_cell(e.name)} | {e.ticker} | {_cell(e.category or '-')} | "
        f"{_cell(e.underlying_index or '-')} | {fmt.fee(e.total_expense_ratio)} |"
        for e in etfs
    ]
    return "\n".join(lines)
