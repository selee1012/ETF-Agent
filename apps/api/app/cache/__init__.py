"""인메모리 TTL 캐시(cachetools). # P1-API-05

키 규칙(README 참고):
- ETF 마스터 전체: ``etf_master:all`` (1일)
- ETF 단건/목록 조회: ``etf:{ticker}`` (1일)
- 최신 시세: ``price:latest:{ticker}`` (1시간)
- FAQ 답변: ``faq:{level}:{sha256(정규화 질문)[:16]}`` (1시간, 가드 통과 답변만)

프로세스 단위 캐시라 api 인스턴스가 여러 개면 각자 갖는다. 나중에 Redis 등으로 바꿀 때는
이 모듈의 함수 시그니처만 유지하면 된다.
"""

from typing import Any

from cachetools import TTLCache

from app.privacy import stable_hash

ETF_MASTER_TTL = 24 * 60 * 60
PRICE_TTL = 60 * 60
FAQ_TTL = 60 * 60

_etf_cache: TTLCache[str, Any] = TTLCache(maxsize=2048, ttl=ETF_MASTER_TTL)
_price_cache: TTLCache[str, Any] = TTLCache(maxsize=4096, ttl=PRICE_TTL)
_faq_cache: TTLCache[str, Any] = TTLCache(maxsize=1024, ttl=FAQ_TTL)

ETF_MASTER_ALL = "etf_master:all"


def etf_key(ticker: str) -> str:
    return f"etf:{ticker}"


def price_key(ticker: str) -> str:
    return f"price:latest:{ticker}"


def faq_key(level: str, normalized_query: str) -> str:
    return f"faq:{level}:{stable_hash(normalized_query)}"


def etf_cache() -> TTLCache[str, Any]:
    return _etf_cache


def price_cache() -> TTLCache[str, Any]:
    return _price_cache


def faq_cache() -> TTLCache[str, Any]:
    return _faq_cache


def clear_all() -> None:
    """시드·수집·ingest 후 또는 테스트에서 호출한다."""
    _etf_cache.clear()
    _price_cache.clear()
    _faq_cache.clear()
