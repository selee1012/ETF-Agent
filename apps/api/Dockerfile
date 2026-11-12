# syntax=docker/dockerfile:1.7
# 빌드 컨텍스트는 레포 루트다(prompts·jobs·data·ml·scripts를 함께 담는다).
#   docker build -f apps/api/Dockerfile .

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.13.7

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------- builder: uv로 의존성만 먼저 설치(레이어 캐시) ----------
FROM python:${PYTHON_VERSION}-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=apps/api/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=apps/api/uv.lock,target=uv.lock \
    uv sync --locked --no-dev --no-install-project

# ---------- runtime: 레포와 같은 디렉터리 구조(/workspace), non-root ----------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/apps/api:/workspace
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /workspace --shell /usr/sbin/nologin app \
    && mkdir -p /data/storage && chown app:app /data/storage
COPY --from=builder /opt/venv /opt/venv
WORKDIR /workspace
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app data ./data
COPY --chown=app:app jobs ./jobs
COPY --chown=app:app ml ./ml
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app apps/api/alembic.ini apps/api/alembic.ini
COPY --chown=app:app apps/api/migrations apps/api/migrations
COPY --chown=app:app apps/api/app apps/api/app
WORKDIR /workspace/apps/api
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
