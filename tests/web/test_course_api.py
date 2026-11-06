"""Course editing REST routes (CRSE-02/04/05): add/move/edit marks, legs, reorder, delete, "Finir
ici", activate, confirm sides; base_version 409; bounds 422; nav push; course_edit event lines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app

BUOY = {
    "name": "Bouée dégagement",
    "lat": 43.68,
    "lon": 15.79,
    "radius_nm": 0.05,
    "side": "port",
    "insert_at": 2,
}


@pytest.fixture
def make_client(tmp_data_dir: Path, free_udp_port: int):
    def _make():
        ctx = CoreContext.create(SimClock(), tmp_data_dir, udp_port=free_udp_port)
        return ctx, TestClient(create_app(ctx))

    return _make


def events(data_dir: Path) -> list[dict]:
    out: list[dict] = []
    for p in sorted((data_dir / "logs" / "events").glob("*.jsonl")):
        out += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return out


def add(client: TestClient, version: int, **kw) -> dict:
    r = client.post("/api/marks", json={**BUOY, **kw, "base_version": version})
    assert r.status_code == 200, r.text
    return r.json()


# -- Task 1: tap to add ---------------------------------------------------------------------------
def test_add_mark_inserts_bumps_version_and_pushes_nav(make_client, tmp_data_dir: Path) -> None:
    ctx, client = make_client()
    with client, client.websocket_connect("/ws") as ws:
        assert [ws.receive_json()["type"], ws.receive_json()["type"]] == ["diag", "nav"]
        v = client.get("/api/course").json()["version"]
        c = add(client, v)
        assert c["version"] == v + 1
        assert c["template"] == "custom"
        assert c["seq"][2] == {"mark_id": "m1", "side": "port", "radius_nm": 0.05}
        assert c["marks"]["m1"]["name"] == "Bouée dégagement"
        assert c["marks"]["m1"]["builtin"] is False
        assert c["active_idx"] == 1  # still Plić Sestre
        msg = ws.receive_json()
        assert msg["type"] == "nav" and msg["course_version"] == v + 1
        assert client.get("/api/nav").json()["course_version"] == v + 1
        # default position: right after the active mark
        c = client.post(
            "/api/marks", json={**BUOY, "insert_at": None, "base_version": v + 1}
        ).json()
        assert c["seq"][2]["mark_id"] == "m2" and c["seq"][3]["mark_id"] == "m1"
    lines = [e for e in events(tmp_data_dir) if e["type"] == "course_edit"]
    assert [e["action"] for e in lines] == ["add_mark", "add_mark"]
    assert lines[0]["mark_id"] == "m1" and lines[0]["version"] == v + 1
    assert isinstance(lines[0]["t_wall"], float)


def test_add_mark_stale_version_is_409_with_current_course(make_client) -> None:
    _, client = make_client()
    with client:
        add(client, 0)
        r = client.post("/api/marks", json={**BUOY, "base_version": 0})
        assert r.status_code == 409
        assert r.json()["version"] == 1 and r.json()["seq"][2]["mark_id"] == "m1"


@pytest.mark.parametrize(
    "patch",
    [
        {"lat": 41.9},
        {"lon": 17.1},
        {"radius_nm": 3.5},
        {"side": "left"},
        {"name": "x" * 41},
        {"name": ""},
        {"name": "\x07\x1b"},  # nothing left after stripping control characters
        {"color": "red"},  # extra fields are forbidden
        {"insert_at": 0},  # never before the start
        {"insert_at": 9},
    ],
)
def test_add_mark_rejects_bad_input(make_client, patch: dict) -> None:
    _, client = make_client()
    with client:
        r = client.post("/api/marks", json={**BUOY, **patch, "base_version": 0})
        assert r.status_code == 422, (patch, r.text)
        assert client.get("/api/course").json()["version"] == 0
        assert client.post("/api/marks", json=BUOY).status_code == 422  # base_version required


def test_control_characters_are_stripped(make_client) -> None:
    _, client = make_client()
    with client:
        c = add(client, 0, name="Bou\x07ée\x1b[31m\x7f")
        assert c["marks"]["m1"]["name"] == "Bouée[31m"


def test_thirty_marks_at_most(make_client) -> None:
    _, client = make_client()
    with client:
        c = client.get("/api/course").json()
        n0 = len(c["marks"])  # the five builtin marks
        v = c["version"]
        for i in range(30 - n0):
            v = add(client, v, name=f"M{i}", insert_at=None)["version"]
        r = client.post("/api/marks", json={**BUOY, "insert_at": None, "base_version": v})
        assert r.status_code == 422
        assert len(client.get("/api/course").json()["marks"]) == 30
