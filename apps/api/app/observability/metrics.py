"""Prometheus 형식 메트릭(/metrics). Grafana Cloud가 나중에 수집한다. # P1-OP-02"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "etf_http_requests_total", "HTTP 요청 수", ["method", "route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "etf_http_request_duration_seconds",
    "HTTP 요청 지연 시간",
    ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
    registry=REGISTRY,
)
CHAT_LATENCY = Histogram(
    "etf_chat_duration_seconds",
    "채팅 1건 전체 처리 시간(그래프 + 가드)",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 40, 80),
    registry=REGISTRY,
)
INTENTS = Counter("etf_chat_intent_total", "의도별 채팅 건수", ["intent"], registry=REGISTRY)
GUARD_VERDICTS = Counter(
    "etf_guard_verdict_total", "가드 판정별 건수", ["verdict"], registry=REGISTRY
)
GUARD_BLOCK_RATE = Gauge(
    "etf_guard_block_rate", "가드 차단율(차단 ÷ 전체 판정, 프로세스 시작 이후)", registry=REGISTRY
)
LLM_CALLS = Counter("etf_llm_calls_total", "LLM 호출 수", ["task", "outcome"], registry=REGISTRY)

# 차단으로 집계하는 판정(안전 답변으로 대체된 경우)
BLOCKED_VERDICTS = {"blocked", "llm_unavailable"}
_totals = {"all": 0, "blocked": 0}


def observe_http(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_LATENCY.labels(method, route).observe(seconds)


def observe_chat(intents: list[str], verdict: str, seconds: float) -> None:
    for intent in intents or ["unknown"]:
        INTENTS.labels(intent).inc()
    GUARD_VERDICTS.labels(verdict).inc()
    CHAT_LATENCY.observe(seconds)
    _totals["all"] += 1
    if verdict in BLOCKED_VERDICTS:
        _totals["blocked"] += 1
    GUARD_BLOCK_RATE.set(_totals["blocked"] / _totals["all"])


def render() -> bytes:
    return generate_latest(REGISTRY)
