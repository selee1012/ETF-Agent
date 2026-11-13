"""샘플 ETF 마스터·시세·공시 적재. # P1-DA-02

모든 샘플은 이름이나 설명에 '샘플'이 들어 있다(data/samples).
"""

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cache
from app.repositories import disclosures as disclosure_repo
from app.repositories import etf as etf_repo
from app.settings import REPO_ROOT

SAMPLES_DIR = REPO_ROOT / "data" / "samples"


def load_master(samples_dir: Path) -> list[dict[str, Any]]:
    rows = json.loads((samples_dir / "etf_master.json").read_text(encoding="utf-8"))
    for row in rows:
        if "샘플" not in row["name"] and "샘플" not in (row.get("description") or ""):
            raise ValueError(f"샘플 표기가 없는 행: {row['ticker']}")
        row["total_expense_ratio"] = Decimal(str(row["total_expense_ratio"]))
        row["listed_date"] = date.fromisoformat(row["listed_date"])
        row["source"] = "sample"
    return rows


def load_prices(samples_dir: Path) -> list[dict[str, Any]]:
    with (samples_dir / "prices_daily.csv").open(encoding="utf-8") as f:
        return [
            {
                "ticker": r["ticker"],
                "trade_date": date.fromisoformat(r["trade_date"]),
                "close_price": Decimal(r["close_price"]),
                "nav": Decimal(r["nav"]),
                "premium_discount": Decimal(r["premium_discount"]),
                "volume": int(r["volume"]),
                "net_assets": int(r["net_assets"]),
                "source": "sample",
            }
            for r in csv.DictReader(f)
        ]


def disclosure_external_id(row: dict[str, Any]) -> str:
    """재적재 때 같은 행을 가리키는 식별자. url 끝 조각을 쓰고, url이 없으면 내용으로 만든다.

    external_id가 NULL이면 UNIQUE 충돌이 나지 않아 시드를 돌릴 때마다 같은 공시가 또 들어간다.
    """
    tail = (row.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
    if tail:
        return tail[:64]
    key = "|".join(
        str(row.get(k) or "") for k in ("ticker", "constituent_name", "title", "disclosed_at")
    )
    return "sample-" + hashlib.sha256(key.encode()).hexdigest()[:24]


def load_disclosures(samples_dir: Path) -> list[dict[str, Any]]:
    rows = json.loads((samples_dir / "disclosures.json").read_text(encoding="utf-8"))
    return [
        {
            **row,
            "external_id": disclosure_external_id(row),
            "disclosed_at": date.fromisoformat(row["disclosed_at"]),
            "source": "sample",
        }
        for row in rows
    ]


async def seed(session: AsyncSession, samples_dir: Path = SAMPLES_DIR) -> dict[str, int]:
    master = load_master(samples_dir)
    prices = load_prices(samples_dir)
    disclosures = load_disclosures(samples_dir)
    result = {
        "etf_master": await etf_repo.upsert_etfs(session, master),
        "prices_daily": await etf_repo.upsert_prices(session, prices),
        "disclosures": await disclosure_repo.upsert_disclosures(session, disclosures),
    }
    await session.commit()
    cache.clear_all()
    return result


async def run(maker: async_sessionmaker[AsyncSession], samples_dir: Path = SAMPLES_DIR) -> dict:
    async with maker() as session:
        return await seed(session, samples_dir)
