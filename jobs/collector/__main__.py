"""CLI: python -m jobs.collector [--date YYYY-MM-DD] [--days 7] [--constituent 회사명 ...]"""

import argparse
import asyncio
from datetime import date, timedelta

from app.db import dispose_engine, get_sessionmaker
from app.settings import get_settings
from jobs.collector import CollectorError, collect_dart, collect_etf_prices


async def main() -> int:
    parser = argparse.ArgumentParser(description="공공데이터포털·DART 수집")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--days", type=int, default=7, help="DART 조회 기간(일)")
    parser.add_argument("--constituent", action="append", default=[], help="구성종목 회사명")
    args = parser.parse_args()

    s = get_settings()
    price_key = s.data_go_kr_api_key.get_secret_value() if s.data_go_kr_api_key else None
    dart_key = s.dart_api_key.get_secret_value() if s.dart_api_key else None
    code = 0
    try:
        async with get_sessionmaker()() as session:
            for job in (
                collect_etf_prices(
                    session, price_key, bas_dt=args.date, http_timeout=s.external_timeout_seconds
                ),
                collect_dart(
                    session,
                    dart_key,
                    begin=args.date - timedelta(days=args.days),
                    end=args.date,
                    constituents=args.constituent,
                    http_timeout=s.external_timeout_seconds,
                ),
            ):
                try:
                    r = await job
                except CollectorError as e:
                    await session.rollback()
                    print(f"수집 실패: {e}")
                    code = 1
                    continue
                print(r.message or f"[{r.source}] 받은 건수={r.fetched}, 적재={r.stored}")
    finally:
        await dispose_engine()
    return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
