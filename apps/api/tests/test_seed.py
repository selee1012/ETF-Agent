"""샘플 시드: 다시 돌려도 행이 늘지 않는다 (P1-DA-02)."""

import json
import shutil
from pathlib import Path

from sqlalchemy import delete, func, select

from app.db import get_sessionmaker
from app.repositories.models import Disclosure
from jobs.seed import SAMPLES_DIR, disclosure_external_id, run


def test_external_id_from_url_or_content() -> None:
    row = {"ticker": "900010", "title": "[샘플] 분배금 공시", "disclosed_at": "2026-11-01"}
    assert disclosure_external_id({**row, "url": "https://example.com/d/sample-0001"}) == (
        "sample-0001"
    )
    no_url = disclosure_external_id({**row, "url": None})
    assert no_url.startswith("sample-") and no_url == disclosure_external_id({**row, "url": ""})
    assert no_url != disclosure_external_id({**row, "title": "[샘플] 다른 공시", "url": None})


async def test_reseed_does_not_duplicate_disclosures_without_url(tmp_path: Path) -> None:
    for name in ("etf_master.json", "prices_daily.csv"):
        shutil.copy(SAMPLES_DIR / name, tmp_path / name)
    rows = json.loads((SAMPLES_DIR / "disclosures.json").read_text(encoding="utf-8"))
    extra = {**rows[0], "title": "[샘플] url 없는 공시", "url": None}
    (tmp_path / "disclosures.json").write_text(
        json.dumps([*rows, extra], ensure_ascii=False), encoding="utf-8"
    )
    maker = get_sessionmaker()
    await run(maker, tmp_path)
    await run(maker, tmp_path)
    async with maker() as s:
        n = await s.scalar(
            select(func.count()).select_from(Disclosure).where(Disclosure.title == extra["title"])
        )
        await s.execute(delete(Disclosure).where(Disclosure.title == extra["title"]))
        await s.commit()
    assert n == 1
