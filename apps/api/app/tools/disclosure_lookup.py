"""ETF·구성종목 최근 공시 조회 도구. # P1-AG-05"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import disclosures as disclosure_repo
from app.repositories.models import Disclosure


async def recent(
    session: AsyncSession,
    *,
    tickers: Sequence[str] = (),
    constituents: Sequence[str] = (),
    limit: int = 5,
) -> list[Disclosure]:
    return await disclosure_repo.recent_disclosures(
        session, tickers=tickers, constituents=constituents, limit=limit
    )


def format_list(rows: Sequence[Disclosure]) -> str:
    lines = []
    for d in rows:
        who = f" · 구성종목 {d.constituent_name}" if d.constituent_name else ""
        link = f" — [원문]({d.url})" if d.url else ""
        lines.append(f"- **{d.disclosed_at.isoformat()}** {d.title}{who}{link}")
        if d.summary:
            lines.append(f"  - {d.summary}")
    return "\n".join(lines)
