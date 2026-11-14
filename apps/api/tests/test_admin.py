"""운영 화면 API: 권한, 트레이스·피드백 조회, 문서 업로드 → 검색 반영 (P1-API-04)."""

import asyncio

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.llm.fake import FakeEmbedder
from app.storage.azure_blob import AzureBlobStorage
from tests.sse import parse_sse


async def test_admin_requires_admin_role(client: AsyncClient, user_headers: dict) -> None:
    assert (await client.get("/admin/traces")).status_code == 401
    assert (await client.get("/admin/traces", headers=user_headers)).status_code == 403


async def test_admin_traces_filters(
    client: AsyncClient, user_headers: dict, admin_headers: dict
) -> None:
    await client.post("/chat", json={"message": "ETF 추천해줘"}, headers=user_headers)
    resp = await client.post(
        "/chat", json={"message": "샘플 반도체 비교하고 뉴스도"}, headers=user_headers
    )
    rid = parse_sse(resp.text)[-1][1]["request_id"]

    page = (await client.get("/admin/traces?intent=disclosure", headers=admin_headers)).json()
    assert rid in [t["request_id"] for t in page["items"]]
    assert all("disclosure" in t["intent"].split("+") for t in page["items"])
    page = (await client.get("/admin/traces?verdict=template", headers=admin_headers)).json()
    assert page["total"] >= 1
    assert all(t["guard_verdict"] == "template" for t in page["items"])


async def test_admin_feedback_list(
    client: AsyncClient, user_headers: dict, admin_headers: dict
) -> None:
    resp = await client.post("/chat", json={"message": "괴리율이 뭐야?"}, headers=user_headers)
    mid = parse_sse(resp.text)[-1][1]["message_id"]
    await client.post(
        "/feedback", json={"kind": "dislike", "message_id": mid}, headers=user_headers
    )
    items = (await client.get("/admin/feedback", headers=admin_headers)).json()
    assert any(f["message_id"] == mid and f["kind"] == "dislike" for f in items)


DOC = """# [샘플] 퀀텀 리밸런싱 안내

## 퀀텀 리밸런싱이란
퀀텀 리밸런싱은 이 테스트를 위해 만든 가상의 용어로, 샘플 ETF가 분기마다 비중을 다시 맞추는 절차를 말합니다.
"""


async def test_upload_ingest_and_search(client: AsyncClient, admin_headers: dict) -> None:
    files = {"file": ("quantum.md", DOC.encode(), "text/markdown")}
    resp = await client.post("/admin/documents", files=files, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "created" and body["chunks"] >= 1
    assert body["source_uri"] == "local://uploads/quantum.md"

    again = await client.post("/admin/documents", files=files, headers=admin_headers)
    assert again.json()["status"] == "unchanged"

    hits = (await client.get("/admin/search?q=퀀텀 리밸런싱", headers=admin_headers)).json()
    assert hits[0]["title"] == "[샘플] 퀀텀 리밸런싱 안내"

    docs = (await client.get("/admin/documents", headers=admin_headers)).json()
    assert any(d["source_uri"] == "local://uploads/quantum.md" for d in docs)


async def test_upload_rejects_unsupported(client: AsyncClient, admin_headers: dict) -> None:
    files = {"file": ("x.exe", b"MZ", "application/octet-stream")}
    resp = await client.post("/admin/documents", files=files, headers=admin_headers)
    assert resp.status_code == 415


async def test_broken_pdf_is_rejected_and_not_stored(
    client: AsyncClient, app: FastAPI, admin_headers: dict
) -> None:
    files = {"file": ("broken.pdf", b"not a pdf", "application/pdf")}
    resp = await client.post("/admin/documents", files=files, headers=admin_headers)
    assert resp.status_code == 422, resp.text
    assert not await app.state.container.storage.exists("uploads/broken.pdf")


async def test_failed_reupload_keeps_previous_original(
    client: AsyncClient, app: FastAPI, admin_headers: dict
) -> None:
    good = b"# [\xec\x83\x98\xed\x94\x8c] keep\n\n## a\n\nfirst version body"
    ok = await client.post(
        "/admin/documents",
        files={"file": ("keep.md", good, "text/markdown")},
        headers=admin_headers,
    )
    assert ok.status_code == 201
    empty = await client.post(
        "/admin/documents",
        files={"file": ("keep.md", b"   \n", "text/markdown")},
        headers=admin_headers,
    )
    assert empty.status_code == 422  # 본문이 비어 적재 실패
    assert await app.state.container.storage.get("uploads/keep.md") == good


async def test_upload_with_stub_storage_returns_501(
    client: AsyncClient, app: FastAPI, admin_headers: dict
) -> None:
    app.state.container.storage = AzureBlobStorage()
    files = {"file": ("stub.md", DOC.encode(), "text/markdown")}
    resp = await client.post("/admin/documents", files=files, headers=admin_headers)
    assert resp.status_code == 501, resp.text
    assert "구현하지 않았다" in resp.json()["detail"]


class _SlowEmbedder(FakeEmbedder):
    """임베딩 구간의 시작·끝을 기록한다. 두 업로드가 겹치면 start가 연달아 찍힌다."""

    def __init__(self, dim: int, events: list[str]) -> None:
        super().__init__(dim=dim)
        self.events = events

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.events.append("start")
        await asyncio.sleep(0.05)
        self.events.append("end")
        return await super().embed(texts)


async def _upload_pair(client: AsyncClient, headers: dict, names: tuple[str, str]) -> None:
    bodies = [f"# [샘플] 동시 업로드 {i}\n\n## a\n\n본문 {i}".encode() for i in (1, 2)]
    responses = await asyncio.gather(
        *(
            client.post(
                "/admin/documents", files={"file": (n, b, "text/markdown")}, headers=headers
            )
            for n, b in zip(names, bodies, strict=True)
        )
    )
    assert [r.status_code for r in responses] == [201, 201]


async def test_same_name_uploads_run_one_at_a_time(
    client: AsyncClient, app: FastAPI, admin_headers: dict
) -> None:
    """같은 이름의 업로드가 겹치면 원본과 색인이 어긋난다. 하나가 끝난 뒤 다음이 시작한다."""
    events: list[str] = []
    c = app.state.container
    c.embedder = _SlowEmbedder(c.settings.embedding_dim, events)
    await _upload_pair(client, admin_headers, ("race.md", "race.md"))
    assert events == ["start", "end", "start", "end"]


async def test_different_name_uploads_do_not_wait(
    client: AsyncClient, app: FastAPI, admin_headers: dict
) -> None:
    events: list[str] = []
    c = app.state.container
    c.embedder = _SlowEmbedder(c.settings.embedding_dim, events)
    await _upload_pair(client, admin_headers, ("race-a.md", "race-b.md"))
    assert events == ["start", "start", "end", "end"]


async def test_many_concurrent_uploads_do_not_exhaust_pool(
    client: AsyncClient, admin_headers: dict
) -> None:
    """업로드 하나가 DB 연결을 둘씩 잡으면 풀(10개)보다 많은 동시 업로드가 서로를 기다리다 모두 실패한다."""
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                client.post(
                    "/admin/documents",
                    files={
                        "file": (
                            f"pool-{i}.md",
                            f"# t{i}\n\n## a\n\n본문 {i}".encode(),
                            "text/markdown",
                        )
                    },
                    headers=admin_headers,
                )
                for i in range(12)
            )
        ),
        timeout=20,
    )
    assert [r.status_code for r in responses] == [201] * 12


class _BlockingEmbedder(FakeEmbedder):
    def __init__(self, dim: int) -> None:
        super().__init__(dim=dim)
        self.started = asyncio.Event()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.started.set()
        await asyncio.Event().wait()  # 취소될 때까지 멈춘다
        return []


async def test_cancelled_upload_restores_previous_original(
    client: AsyncClient, app: FastAPI, admin_headers: dict
) -> None:
    """원본을 덮어쓴 뒤 적재 중에 요청이 취소돼도 이전 원본으로 되돌리고 잠금을 푼다."""
    c = app.state.container
    good = "# [샘플] 취소\n\n## a\n\n처음 본문".encode()
    files = {"file": ("cancel.md", good, "text/markdown")}
    assert (
        await client.post("/admin/documents", files=files, headers=admin_headers)
    ).status_code == 201

    original, blocking = c.embedder, _BlockingEmbedder(c.settings.embedding_dim)
    c.embedder = blocking
    newer = {"file": ("cancel.md", "# [샘플] 취소\n\n## a\n\n바뀐 본문".encode(), "text/markdown")}
    task = asyncio.create_task(client.post("/admin/documents", files=newer, headers=admin_headers))
    await asyncio.wait_for(blocking.started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await c.storage.get("uploads/cancel.md") == good

    c.embedder = original  # 잠금이 풀렸으므로 같은 이름을 다시 올릴 수 있다
    again = await asyncio.wait_for(
        client.post("/admin/documents", files=newer, headers=admin_headers), timeout=5
    )
    assert again.status_code == 201 and again.json()["status"] == "updated"
