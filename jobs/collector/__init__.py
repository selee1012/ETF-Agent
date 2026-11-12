"""외부 데이터 수집: 공공데이터포털 증권상품시세(일별 ETF), DART 공시. # P1-DA-02

키(DATA_GO_KR_API_KEY, DART_API_KEY)가 없으면 호출하지 않고 안내만 한다.
모든 외부 호출에는 타임아웃과 오류 처리를 넣는다(공통 규칙 5).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import cache
from app.logging import get_logger
from app.repositories import disclosures as disclosure_repo
from app.repositories import etf as etf_repo

log = get_logger(__name__)

DATA_GO_KR_ETF_URL = (
    "https://apis.data.go.kr/1160100/service/GetSecuritiesProductInfoService/getETFPriceInfo"
)
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


class CollectorError(Exception):
    pass


@dataclass(slots=True)
class CollectResult:
    source: str
    fetched: int
    stored: int
    message: str = ""


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "")) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _int(value: Any) -> int | None:
    d = _dec(value)
    return int(d) if d is not None else None


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict:
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException as e:
        raise CollectorError(f"타임아웃: {url}") from e
    except httpx.HTTPStatusError as e:
        raise CollectorError(f"HTTP {e.response.status_code}: {url}") from e
    except (httpx.HTTPError, ValueError) as e:
        raise CollectorError(f"요청 실패({type(e).__name__}): {url}") from e


def parse_data_go_kr_items(payload: dict) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {}) or {}
    rows = items.get("item", []) if isinstance(items, dict) else []
    return [rows] if isinstance(rows, dict) else list(rows)


def to_price_row(item: dict[str, Any]) -> dict[str, Any] | None:
    ticker = (item.get("srtnCd") or "").strip()
    bas = item.get("basDt")
    if not ticker or not bas:
        return None
    close, nav = _dec(item.get("clpr")), _dec(item.get("nav"))
    prem = None
    if close is not None and nav:
        prem = ((close - nav) / nav * 100).quantize(Decimal("0.01"))
    return {
        "ticker": ticker,
        "trade_date": datetime.strptime(str(bas), "%Y%m%d").date(),
        "close_price": close,
        "nav": nav,
        "premium_discount": prem,
        "volume": _int(item.get("trqu")),
        "net_assets": _int(item.get("nPptTotAmt")),
        "source": "data_go_kr",
    }


def to_master_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": item["srtnCd"].strip(),
        "isin": (item.get("isinCd") or None),
        "name": item.get("itmsNm") or item["srtnCd"],
        "aliases": [],
        "underlying_index": item.get("bssIdxIdxNm"),
        "source": "data_go_kr",
    }


async def collect_etf_prices(
    session: AsyncSession, api_key: str | None, *, bas_dt: date, http_timeout: float, page_size=1000
) -> CollectResult:
    if not api_key:
        return CollectResult(
            "data_go_kr", 0, 0, "DATA_GO_KR_API_KEY가 없어 증권상품시세 수집을 건너뜁니다."
        )
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        page = 1
        while True:
            payload = await _get_json(
                client,
                DATA_GO_KR_ETF_URL,
                {
                    "serviceKey": api_key,
                    "resultType": "json",
                    "numOfRows": page_size,
                    "pageNo": page,
                    "basDt": bas_dt.strftime("%Y%m%d"),
                },
            )
            batch = parse_data_go_kr_items(payload)
            items.extend(batch)
            total = int(payload.get("response", {}).get("body", {}).get("totalCount", 0) or 0)
            if not batch or len(items) >= total:
                break
            page += 1
    masters = {i["srtnCd"].strip(): to_master_row(i) for i in items if i.get("srtnCd")}
    existing = {e.ticker for e in await etf_repo.get_etfs(session, list(masters))}
    # 새 종목만 마스터에 추가한다(샘플 별칭·보수 정보를 덮어쓰지 않는다).
    await etf_repo.upsert_etfs(session, [m for t, m in masters.items() if t not in existing])
    prices = [r for r in (to_price_row(i) for i in items) if r]
    stored = await etf_repo.upsert_prices(session, prices)
    await session.commit()
    cache.clear_all()
    return CollectResult("data_go_kr", len(items), stored)


def match_dart_rows(
    rows: Sequence[dict[str, Any]], etf_names: dict[str, str], constituents: Sequence[str]
) -> list[dict[str, Any]]:
    """보고서명에 ETF 이름이 있으면 해당 ETF 공시, 회사명이 구성종목 목록에 있으면 구성종목 공시."""
    out = []
    for r in rows:
        title, corp = r.get("report_nm", ""), r.get("corp_name", "")
        ticker = next((t for name, t in etf_names.items() if name and name in title), None)
        if ticker is None and corp not in constituents:
            continue
        out.append(
            {
                "ticker": ticker,
                "constituent_name": None if ticker else corp,
                "title": f"{corp} {title}".strip(),
                "disclosed_at": datetime.strptime(r["rcept_dt"], "%Y%m%d").date(),
                "url": DART_VIEW_URL.format(rcept_no=r["rcept_no"]),
                "summary": None,
                "source": "dart",
                "external_id": r["rcept_no"],
            }
        )
    return out


async def collect_dart(
    session: AsyncSession,
    api_key: str | None,
    *,
    begin: date,
    end: date,
    constituents: Sequence[str],
    http_timeout: float,
) -> CollectResult:
    if not api_key:
        return CollectResult("dart", 0, 0, "DART_API_KEY가 없어 공시 수집을 건너뜁니다.")
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        page = 1
        while True:
            payload = await _get_json(
                client,
                DART_LIST_URL,
                {
                    "crtfc_key": api_key,
                    "bgn_de": begin.strftime("%Y%m%d"),
                    "end_de": end.strftime("%Y%m%d"),
                    "page_no": page,
                    "page_count": 100,
                },
            )
            status = payload.get("status")
            if status == "013":  # 조회된 데이터 없음
                break
            if status != "000":
                raise CollectorError(f"DART 오류 status={status} {payload.get('message', '')}")
            rows.extend(payload.get("list", []))
            if page >= int(payload.get("total_page", 1)):
                break
            page += 1
    etf_names = {e.name: e.ticker for e in await etf_repo.list_etfs(session)}
    matched = match_dart_rows(rows, etf_names, constituents)
    stored = await disclosure_repo.upsert_disclosures(session, matched)
    await session.commit()
    return CollectResult("dart", len(rows), stored)
