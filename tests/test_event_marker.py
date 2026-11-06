"""POST /api/event: 201 + fsync'd JSONL line, 1/s rate limit (429), validation (422), page ids."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
from jabuka.ingest import rawlog as rawlog_mod
from jabuka.ingest.rawlog import iter_log_lines

T0 = datetime(2026, 11, 12, 9, 30, tzinfo=UTC).timestamp()


@pytest.fixture
def core(tmp_data_dir: Path, free_udp_port: int):
    clock = SimClock(start_utc=T0)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port)
    with TestClient(create_app(ctx)) as client:
        yield client, clock, ctx, tmp_data_dir


def _event_lines(data_dir: Path) -> list[dict]:
    files = sorted((data_dir / "logs" / "events").glob("events-*.jsonl"))
    return [json.loads(x) for f in files for x in iter_log_lines(f)]


def test_event_201_and_stored(core) -> None:
    client, clock, ctx, data_dir = core
    r = client.post("/api/event", json={"label": "Mark rounded"})
    assert r.status_code == 201
    body = r.json()
    assert body["ok"] is True
    assert body["n"] == 1
    for key in ("t_mono", "t_wall", "utc"):
        assert key in body
    assert body["utc"].startswith("2026-11-12T09:30")
    lines = _event_lines(data_dir)
    assert len(lines) == 1
    ev = lines[0]
    assert ev["type"] == "event"
    assert ev["label"] == "Mark rounded"
    assert ev["n"] == 1
    assert ev["clock"]["kind"] == "sim"
    assert "state_ref" in ev
    assert client.get("/api/state").json()["log"]["events_written"] == 1


def test_event_fsynced_immediately(core, monkeypatch: pytest.MonkeyPatch) -> None:
    client, *_ = core
    calls: list[int] = []
    real = os.fsync
    monkeypatch.setattr(rawlog_mod.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    r = client.post("/api/event", json={"label": "fsync me"})
    assert r.status_code == 201
    assert len(calls) >= 1


def test_event_rate_limited_429(core) -> None:
    client, clock, ctx, data_dir = core
    assert client.post("/api/event", json={"label": "one"}).status_code == 201
    clock.advance(0.5)
    assert client.post("/api/event", json={"label": "two"}).status_code == 429
    clock.advance(0.6)
    r = client.post("/api/event", json={"label": "three"})
    assert r.status_code == 201
    assert r.json()["n"] == 2
    assert [e["label"] for e in _event_lines(data_dir)] == ["one", "three"]


def test_event_label_too_long_422(core) -> None:
    client, clock, ctx, data_dir = core
    r = client.post("/api/event", json={"label": "x" * 201})
    assert r.status_code == 422
    assert _event_lines(data_dir) == []
    assert client.post("/api/event", json={"label": "x" * 200}).status_code == 201


def test_event_control_chars_stripped(core) -> None:
    client, clock, ctx, data_dir = core
    r = client.post("/api/event", json={"label": "a\x00b\x07c\x7fd\ne\tf"})
    assert r.status_code == 201
    assert _event_lines(data_dir)[0]["label"] == "abcdef"


def test_event_empty_body_defaults_label(core) -> None:
    client, clock, ctx, data_dir = core
    r = client.post("/api/event", json={})
    assert r.status_code == 201
    assert _event_lines(data_dir)[0]["label"] == ""


def test_page_has_event_controls(core) -> None:
    client, *_ = core
    html = client.get("/").text
    assert 'id="event-btn"' in html
    assert 'id="event-label"' in html
    assert 'maxlength="200"' in html
    js = client.get("/diag.js").text
    assert "/api/event" in js
    assert "event-ack" in js
