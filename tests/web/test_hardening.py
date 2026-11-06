"""REST hardening (review IN-01): next/prev carry base_version, mutations are JSON-only (no
cross-site form), request bodies are capped at 64 KiB, the Host header is checked (DNS
rebinding) and every response carries the security headers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jabuka.common.clock import SimClock
from jabuka.core.hardening import MAX_BODY_BYTES, HardeningMiddleware, host_allowed
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app


@pytest.fixture
def client(tmp_data_dir: Path, free_udp_port: int):
    ctx = CoreContext.create(SimClock(), tmp_data_dir, udp_port=free_udp_port)
    with TestClient(create_app(ctx)) as c:
        yield c


def test_next_prev_need_the_current_version(client) -> None:
    """Two tablets tap "Suiv." for the same rounding: the second gets 409, no mark skipped."""
    v = client.get("/api/course").json()["version"]
    first = client.post("/api/course/next", json={"base_version": v})
    assert first.status_code == 200 and first.json()["active_idx"] == 2
    second = client.post("/api/course/next", json={"base_version": v})
    assert second.status_code == 409 and second.json()["active_idx"] == 2
    assert client.post("/api/course/next").status_code == 415  # no JSON body: refused
    assert client.post("/api/course/prev", json={}).status_code == 422
    back = client.post("/api/course/prev", json={"base_version": v + 1})
    assert back.status_code == 200 and back.json()["active_idx"] == 1


@pytest.mark.parametrize(
    "ctype", ["application/x-www-form-urlencoded", "text/plain", "multipart/form-data", None]
)
def test_cross_site_form_posts_are_refused(client, ctype) -> None:
    headers = {"content-type": ctype} if ctype else {}
    for url in ("/api/course/next", "/api/course/undo", "/api/wind/manual", "/api/event"):
        r = client.post(url, content=b"base_version=0", headers=headers)
        assert r.status_code == 415, (url, ctype, r.status_code)
    r = client.put("/api/settings", content=b"x", headers=headers)
    assert r.status_code == 415
    assert client.get("/api/course").json()["active_idx"] == 1  # nothing changed
    ok = client.post("/api/course/next", json={"base_version": 0})
    assert ok.status_code == 200  # application/json (with charset too) still works
    r = client.post(
        "/api/course/prev",
        content=b'{"base_version": 1}',
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert r.status_code == 200


def test_oversized_body_is_refused(client) -> None:
    big = b'{"base_version": 0, "patch": {"x": "' + b"a" * MAX_BODY_BYTES + b'"}}'
    r = client.put("/api/settings", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert client.get("/api/settings").json()["version"] == 0


def test_chunked_oversized_body_is_refused_without_buffering_it_all() -> None:
    """No Content-Length (chunked): the middleware stops reading past the cap."""
    reached: list[bool] = []

    async def app(scope, receive, send) -> None:  # never reached
        reached.append(True)

    chunks = [b"x" * 16384] * 10
    sent: list[dict] = []
    pulled = 0

    async def receive() -> dict:
        nonlocal pulled
        pulled += 1
        return {"type": "http.request", "body": chunks[pulled - 1], "more_body": pulled < 10}

    async def send(msg: dict) -> None:
        sent.append(msg)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/event",
        "headers": [(b"host", b"10.42.0.1:8000"), (b"content-type", b"application/json")],
    }
    asyncio.run(HardeningMiddleware(app)(scope, receive, send))
    assert reached == [] and sent[0]["status"] == 413
    assert pulled == MAX_BODY_BYTES // 16384 + 1  # stopped right after the cap


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("10.42.0.1:8000", True),
        ("10.42.0.1", True),
        ("127.0.0.1:8123", True),
        ("[::1]:8000", True),
        ("localhost:8000", True),
        ("jabuka", True),
        ("jabuka.local:8000", True),
        ("evil.example.com", False),
        ("evil.example.com:8000", False),
        ("10.42.0.1:80;x", False),
        ("", False),
        (None, False),
    ],
)
def test_host_check(host, ok) -> None:
    assert host_allowed(host) is ok


def test_rebinding_host_is_refused(client) -> None:
    assert client.get("/api/state", headers={"host": "evil.example.com"}).status_code == 421
    assert client.get("/api/state", headers={"host": "10.42.0.1:8000"}).status_code == 200
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"host": "evil.example.com"}) as ws:
            ws.receive_text()


def test_security_headers(client) -> None:
    for url in ("/", "/api/state", "/diag.html", "/app.js"):
        r = client.get(url, headers={"host": "10.42.0.1:8000"})
        assert r.status_code == 200, url
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "connect-src 'self' ws://10.42.0.1:8000" in csp
        assert "frame-ancestors 'self'" in csp
        assert r.headers["x-frame-options"] == "SAMEORIGIN"  # the app frames its own diag page
        assert r.headers["x-content-type-options"] == "nosniff"
