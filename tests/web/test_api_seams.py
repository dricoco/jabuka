"""Settings and course REST seams: optimistic concurrency, bounds, persistence across a restart,
nav push on every change, and the app shell / diagnostics page routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app


@pytest.fixture
def make_client(tmp_data_dir: Path, free_udp_port: int):
    def _make():
        ctx = CoreContext.create(SimClock(), tmp_data_dir, udp_port=free_udp_port)
        return ctx, TestClient(create_app(ctx))

    return _make


def test_settings_put_409_422_and_persistence(make_client) -> None:
    ctx, client = make_client()
    with client:
        got = client.get("/api/settings").json()
        assert got["version"] == 0 and got["settings"]["efficiency"] == 0.92
        r = client.put("/api/settings", json={"base_version": 0, "patch": {"efficiency": 0.85}})
        assert r.status_code == 200
        assert r.json()["version"] == 1 and r.json()["settings"]["efficiency"] == 0.85
        stale = client.put("/api/settings", json={"base_version": 0, "patch": {"efficiency": 0.8}})
        assert stale.status_code == 409
        assert stale.json()["version"] == 1
        assert stale.json()["settings"]["efficiency"] == 0.85
        for patch in ({"efficiency": 2.0}, {"variation_deg": 45}, {"unknown": 1}):
            r = client.put("/api/settings", json={"base_version": 1, "patch": patch})
            assert r.status_code == 422, patch
        assert client.put("/api/settings", json={"patch": {}}).status_code == 422
        assert client.get("/api/nav").json()["settings_version"] == 1
    ctx2, client2 = make_client()
    with client2:
        got = client2.get("/api/settings").json()
        assert got == {"version": 1, "settings": got["settings"]}
        assert got["settings"]["efficiency"] == 0.85


def test_settings_schema_has_labels_and_bounds(make_client) -> None:
    _, client = make_client()
    with client:
        props = client.get("/api/settings/schema").json()["properties"]
    assert props["efficiency"]["label"] == "Efficacité polaire"
    assert props["efficiency"]["minimum"] == 0.5 and props["efficiency"]["maximum"] == 1.2
    assert props["heading_display"]["enum"] == ["M", "T"]


def test_course_select_next_prev_and_persistence(make_client) -> None:
    ctx, client = make_client()
    with client:
        c = client.get("/api/course").json()
        assert c["template"] == "A" and c["active_idx"] == 1 and c["version"] == 0
        assert c["marks"]["plic-sestre"]["name"] == "Plić Sestre"
        assert c["sides_confirmed"] is False
        b = client.post("/api/course/select", json={"template": "B", "base_version": 0}).json()
        assert b["template"] == "B" and b["version"] == 1
        r = client.post("/api/course/select", json={"template": "A", "base_version": 0})
        assert r.status_code == 409 and r.json()["version"] == 1
        assert client.post("/api/course/select", json={"template": "Z"}).status_code == 422
        n = client.post("/api/course/next", json={"base_version": 1}).json()
        assert n["active_idx"] == 2 and n["version"] == 2
        p = client.post("/api/course/prev", json={"base_version": 2}).json()
        assert p["active_idx"] == 1
        nav = client.get("/api/nav").json()
        assert nav["course_version"] == 3 and nav["course"]["template"] == "B"
        client.post("/api/course/next", json={"base_version": 3})
    _, client2 = make_client()
    with client2:
        c = client2.get("/api/course").json()
    assert (c["template"], c["active_idx"], c["version"]) == ("B", 2, 4)


def test_mutation_pushes_a_nav_message(make_client) -> None:
    ctx, client = make_client()
    with client, client.websocket_connect("/ws") as ws:
        first = [ws.receive_json(), ws.receive_json()]
        assert [m["type"] for m in first] == ["diag", "nav"]  # snapshot on connect
        client.post("/api/course/select", json={"template": "B"})
        msg = ws.receive_json()
        assert msg["type"] == "nav"
        assert msg["course_version"] == 1 and msg["course"]["template"] == "B"


def test_write_failure_is_503(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, client = make_client()

    def full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("jabuka.nav.course.atomic_write_json", full)
    monkeypatch.setattr("jabuka.nav.settings.atomic_write_json", full)
    with client:
        assert client.post("/api/course/next", json={"base_version": 0}).status_code == 503
        r = client.put("/api/settings", json={"base_version": 0, "patch": {"efficiency": 0.9}})
        assert r.status_code == 503
        assert client.get("/api/course").json()["active_idx"] == 1
        assert client.get("/api/settings").json()["version"] == 0


def test_app_shell_and_diag_page(make_client) -> None:
    _, client = make_client()
    with client:
        shell = client.get("/")
        assert shell.status_code == 200
        for dom_id in ('id="tab-barre"', 'id="primary"', 'id="map"', 'id="topbar"'):
            assert dom_id in shell.text
        diag = client.get("/diag.html")
        assert diag.status_code == 200 and "Jabuka diagnostics" in diag.text
        assert 'id="event-btn"' in diag.text
        for asset in ("/app.js", "/helm.js", "/helm_logic.js", "/carte.js", "/reglages.js"):
            assert client.get(asset).status_code == 200, asset
