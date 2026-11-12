"""수집기: 키가 없으면 안내만, 응답 파싱 (P1-DA-02)."""

from datetime import date
from decimal import Decimal

from app.db import get_sessionmaker
from jobs.collector import (
    collect_dart,
    collect_etf_prices,
    match_dart_rows,
    parse_data_go_kr_items,
    to_price_row,
)


async def test_no_keys_only_prints_notice() -> None:
    async with get_sessionmaker()() as s:
        r1 = await collect_etf_prices(s, None, bas_dt=date(2026, 11, 11), http_timeout=1)
        r2 = await collect_dart(
            s,
            None,
            begin=date(2026, 11, 1),
            end=date(2026, 11, 11),
            constituents=[],
            http_timeout=1,
        )
    assert "DATA_GO_KR_API_KEY" in r1.message and r1.stored == 0
    assert "DART_API_KEY" in r2.message and r2.stored == 0


def test_parse_data_go_kr_payload() -> None:
    payload = {
        "response": {
            "body": {
                "totalCount": 1,
                "items": {
                    "item": {
                        "basDt": "20261111",
                        "srtnCd": "900010",
                        "itmsNm": "샘플",
                        "clpr": "10100",
                        "nav": "10000",
                        "trqu": "123",
                        "nPptTotAmt": "5000000000",
                    }
                },
            }
        }
    }
    items = parse_data_go_kr_items(payload)
    row = to_price_row(items[0])
    assert row["trade_date"] == date(2026, 11, 11)
    assert row["premium_discount"] == Decimal("1.00")
    assert row["volume"] == 123


def test_match_dart_rows() -> None:
    rows = [
        {
            "report_nm": "샘플 반도체 분배금 지급",
            "corp_name": "샘플자산운용",
            "rcept_dt": "20261110",
            "rcept_no": "1",
        },
        {
            "report_nm": "주요사항보고서",
            "corp_name": "샘플전자",
            "rcept_dt": "20261110",
            "rcept_no": "2",
        },
        {"report_nm": "무관", "corp_name": "기타", "rcept_dt": "20261110", "rcept_no": "3"},
    ]
    out = match_dart_rows(rows, {"샘플 반도체": "900050"}, ["샘플전자"])
    assert [(r["ticker"], r["constituent_name"]) for r in out] == [
        ("900050", None),
        (None, "샘플전자"),
    ]
    assert out[0]["url"].endswith("rcpNo=1")
