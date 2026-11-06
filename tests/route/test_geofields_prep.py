"""`jabuka-prep geofields`: precomputed 200 m pruning fields per mark; the router uses them when
the mark key matches and computes a 400 m field on demand otherwise."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.prep import cli  # noqa: E402
from jabuka.route.isochrone import mark_key  # noqa: E402
from jabuka.route.landmask import load_geofields  # noqa: E402
from jabuka.route.types import CourseMark  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "route"
MASK_FILE = FIXTURES / "landmask_race_25m.npz"
MARKS_FILE = FIXTURES / "marks.json"


@pytest.fixture(scope="module")
def prepped(tmp_path_factory):
    d = tmp_path_factory.mktemp("pack")
    shutil.copy(MASK_FILE, d / "landmask.npz")
    shutil.copy(MASK_FILE.with_suffix(".json"), d / "landmask.json")
    rc = cli.main(["geofields", "--marks", str(MARKS_FILE), "--out", str(d)])
    assert rc == 0
    return d


def test_writes_one_200m_field_per_mark(prepped, marks_doc, capsys) -> None:
    fields = load_geofields(prepped / "geofields.npz")
    assert len(fields) == len(marks_doc.marks) == 5
    for m in marks_doc.marks.values():
        key = (round(m.lat, 4), round(m.lon, 4), round(m.radius_nm, 3))
        assert key in fields
        assert fields[key].gcell_nm == pytest.approx(200.0 / 1852.0, rel=0.02)
    side = json.loads((prepped / "geofields.json").read_text(encoding="utf-8"))
    data = (prepped / "geofields.npz").read_bytes()
    assert side["sha256"] == hashlib.sha256(data).hexdigest()
    assert side["gcell_m"] == pytest.approx(200.0)
    assert len(side["marks"]) == 5


def test_router_env_uses_precomputed_or_on_demand(prepped, env_factory, uniform_wind) -> None:
    fields = load_geofields(prepped / "geofields.npz")
    env = env_factory(uniform_wind(225.0, 12.0), geofields=fields)
    jab = CourseMark("jabuka", "Jabuka", 43.09153, 15.46054, "stbd", 0.6)
    assert env.geofield_for(jab) is fields[mark_key(jab)]
    moved = jab._replace(lat=43.10)
    g = env.geofield_for(moved)
    assert g is not fields.get(mark_key(moved))
    assert g.gcell_nm == pytest.approx(400.0 / 1852.0, rel=0.02)
    assert env.geofield_for(moved) is g  # cached


def test_missing_mask_fails_in_french(tmp_path, capsys) -> None:
    rc = cli.main(["geofields", "--marks", str(MARKS_FILE), "--out", str(tmp_path)])
    assert rc == 2
    assert "landmask.npz" in capsys.readouterr().err


def test_help_and_land_dispatch(capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["geofields", "--help"])
    assert e.value.code == 0
    assert "--gcell-m" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["land", "--help"])
    assert e.value.code == 0
    assert "build" in capsys.readouterr().out
