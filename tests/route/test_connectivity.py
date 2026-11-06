"""Every channel the course needs stays open at the chosen margins (CONTEXT: margins must not
close a required channel), and the router gets geodesic distance fields."""

from __future__ import annotations

import math
import os
import time
from collections import deque
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
    import shapely
else:  # Phase 2 worktrees without numpy/shapely skip instead of failing
    np = pytest.importorskip("numpy")
    shapely = pytest.importorskip("shapely")

from jabuka.prep import land  # noqa: E402
from jabuka.route.frame import DEFAULT_FRAME, NM_M  # noqa: E402
from jabuka.route.landmask import (  # noqa: E402
    GeoField,
    LandMask,
    compute_geofield,
    flood_reachable,
    load_geofields,
    save_geofields,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "route" / "landmask_race_25m.npz"
F = DEFAULT_FRAME
VODICE = (43.75, 15.78)
PINCH = (43.7229, 15.7828)  # Prvić–Tijat passage, narrowest point Vodice -> open sea


@pytest.fixture(scope="module")
def lm() -> LandMask:
    return LandMask.load(FIXTURE)


def _rc(m: LandMask, p: tuple[float, float]) -> tuple[int, int]:
    r, c = m.rc(*m.frame.to_xy(*p))
    return int(r[0]), int(c[0])


def _bfs(blocked: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """Reference 4-connected flood (slow, pure Python)."""
    ny, nx = blocked.shape
    seen = np.zeros_like(blocked)
    if blocked[seed]:
        return seen
    seen[seed] = True
    q = deque([seed])
    while q:
        r, c = q.popleft()
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < ny and 0 <= cc < nx and not blocked[rr, cc] and not seen[rr, cc]:
                seen[rr, cc] = True
                q.append((rr, cc))
    return seen


# ------------------------------------------------------------------ flood fill (synthetic)
def test_flood_through_an_l_shaped_channel() -> None:
    g = np.ones((40, 40), dtype=bool)
    g[2:12, 2:12] = False  # basin A
    g[28:38, 28:38] = False  # basin B
    g[6, 12:33] = False  # channel east along row 6 (1 cell wide) ...
    g[6:28, 32] = False  # ... then south into basin B
    reach = flood_reachable(g, [(5, 5)])
    assert reach[33, 33] and reach[6, 20] and not reach[0, 0]
    assert np.array_equal(reach, _bfs(g, (5, 5)))
    g[15, 32] = True  # cut the channel
    assert not flood_reachable(g, [(5, 5)])[33, 33]


def test_flood_matches_bfs_on_random_grids() -> None:
    rng = np.random.default_rng(3)
    for _ in range(20):
        g = rng.random((37, 53)) < 0.42
        seed = (int(rng.integers(0, 37)), int(rng.integers(0, 53)))
        assert np.array_equal(flood_reachable(g, [seed]), _bfs(g, seed))


def test_flood_cost_does_not_follow_path_length() -> None:
    # serpentine: one corridor folded 500 times, a 1-million-cell path
    n = 2001
    g = np.zeros((n, n), dtype=bool)
    g[1::2, :] = True
    g[1::4, -1] = False  # openings alternate right ...
    g[3::4, 0] = False  # ... and left
    t0 = time.perf_counter()
    reach = flood_reachable(g, [(0, 0)])
    assert time.perf_counter() - t0 < 5.0
    assert reach[n - 1, n - 1] and reach[n - 1, 0]
    assert not flood_reachable(g, [(1, 5)]).any()  # blocked seed
    assert not flood_reachable(g, [(-1, 5), (5, n + 3)]).any()  # seeds outside the grid


@pytest.mark.parametrize("gap_m,open_", [(200, False), (600, True)])
def test_gap_rule(gap_m: float, open_: bool) -> None:
    """g > 2 x margin + 2 x cell stays open (25 m cells, 100 m margin)."""
    cell, margin, w, h = 25.0, 100.0, 3000.0, 2000.0
    left = shapely.box(-10.0, 800.0, (w - gap_m) / 2, 1200.0)
    right = shapely.box((w + gap_m) / 2, 800.0, w + 10.0, 1200.0)
    obst = shapely.union(left, right).buffer(margin)
    g = land.rasterize(obst, 0.0, 0.0, cell, int(w / cell), int(h / cell))
    reach = flood_reachable(g, [(2, 60)])  # south of the islands
    assert bool(reach[-3, 60]) is open_  # north of the islands


# ------------------------------------------------------------------ real mask
def test_required_points_reachable_on_fixture(lm: LandMask) -> None:
    reach = flood_reachable(lm.mask, [_rc(lm, VODICE)])
    for name, p in land.REQUIRED_SEA_POINTS.items():
        assert lm.points_clear(*F.to_xy(*p))[0], f"{name} inside the mask"
        assert reach[_rc(lm, p)], f"{name} unreachable from Vodice"


def test_prvic_tijat_pinch_is_open(lm: LandMask) -> None:
    assert land.disc_clear(lm, PINCH, 0.1)
    x, y = F.to_xy(*PINCH)
    r, c = _rc(lm, PINCH)
    k = int(0.1 / lm.cell_nm) + 1
    cy, cx = np.mgrid[r - k : r + k + 1, c - k : c + k + 1]
    d = np.hypot(lm.x0_nm + (cx + 0.5) * lm.cell_nm - x, lm.y0_nm + (cy + 0.5) * lm.cell_nm - y)
    assert not lm.mask[cy[d <= 0.1], cx[d <= 0.1]].any()


def _dilate_disc(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    out = mask.copy()
    rad = radius_cells
    ny, nx = mask.shape
    for dr in range(-rad, rad + 1):
        for dc in range(-rad, rad + 1):
            if (dr, dc) == (0, 0) or dr * dr + dc * dc > rad * rad:
                continue
            out[max(dr, 0) : ny + min(dr, 0), max(dc, 0) : nx + min(dc, 0)] |= mask[
                max(-dr, 0) : ny + min(-dr, 0), max(-dc, 0) : nx + min(-dc, 0)
            ]
    return out


def test_stricter_margins_keep_every_required_point_reachable(lm: LandMask) -> None:
    """RESEARCH check (c): another 100 m of margin everywhere still leaves the course open."""
    strict = _dilate_disc(lm.mask, int(round(100 / lm.cell_m)))
    assert strict.sum() > lm.mask.sum()
    reach = flood_reachable(strict, [_rc(lm, VODICE)])
    for name, p in land.REQUIRED_SEA_POINTS.items():
        assert reach[_rc(lm, p)], f"{name} unreachable with +100 m margins"


# ------------------------------------------------------------------ geodesic fields
def _open_water(size_nm: float = 30.0, cell_m: float = 50.0) -> LandMask:
    n = int(size_nm * NM_M / cell_m)
    return LandMask(
        np.zeros((n, n), dtype=bool), None, x0_nm=0.0, y0_nm=0.0, cell_nm=cell_m / NM_M, frame=F
    )


def test_geofield_open_water_close_to_straight_line() -> None:
    m = _open_water()
    seed = (15.0, 15.0)
    gf = compute_geofield(m, [seed])
    for brg in (0, 13, 30, 45, 60, 90, 120, 135, 200, 290):
        b = math.radians(brg)
        x, y = seed[0] + 12 * math.sin(b), seed[1] + 12 * math.cos(b)
        geo = float(gf.distance(x, y)[0])
        assert abs(geo - 12.0) / 12.0 < 0.03, (brg, geo)


def test_geofield_detour_around_the_islands(lm: LandMask) -> None:
    gf = compute_geofield(lm, [F.to_xy(*VODICE)])
    ox, oy = F.to_xy(43.60, 15.60)
    vx, vy = F.to_xy(*VODICE)
    geo = float(gf.distance(ox, oy)[0])
    straight = math.hypot(ox - vx, oy - vy)
    assert math.isfinite(geo) and geo > straight * 1.05
    assert math.isinf(gf.distance(*F.to_xy(43.80, 15.95))[0])  # inland
    assert math.isinf(gf.distance(-500.0, 0.0)[0])  # outside the grid


def test_enclosed_seed_reaches_nothing_outside() -> None:
    m = _open_water(10.0, 50.0)
    mask = m.mask.copy()
    n = mask.shape[0]
    c = n // 2
    yy, xx = np.mgrid[0:n, 0:n]
    rr = np.hypot(yy - c, xx - c)
    mask[(rr > 40) & (rr < 60)] = True  # a 1 km-thick ring of land (50 m cells)
    enclosed = LandMask(mask, None, x0_nm=0.0, y0_nm=0.0, cell_nm=m.cell_nm, frame=F)
    centre = (c + 0.5) * m.cell_nm
    gf = compute_geofield(enclosed, [(centre, centre)])
    assert math.isfinite(gf.distance(centre + 0.5, centre)[0])
    assert math.isinf(gf.distance(0.3, 0.3)[0])
    assert np.isinf(gf.dist).mean() > 0.5


def test_geofields_round_trip_without_pickle(tmp_path: Path) -> None:
    m = _open_water(8.0, 50.0)
    fields = {
        (43.6845, 15.8116, 0.3): compute_geofield(m, [(2.0, 2.0)], seed_radius_nm=0.3),
        (43.0915, 15.4605, 0.6): compute_geofield(m, [(6.0, 5.0)], 400 / NM_M, "any"),
    }
    with pytest.raises(ValueError):  # different grids in one file
        save_geofields(tmp_path / "g.npz", fields)
    fields[(43.0915, 15.4605, 0.6)] = compute_geofield(m, [(6.0, 5.0)])
    path = tmp_path / "geofields.npz"
    save_geofields(path, fields)
    back = load_geofields(path)
    assert set(back) == set(fields)
    for k, f in fields.items():
        g = back[k]
        assert isinstance(g, GeoField) and g.gcell_nm == f.gcell_nm
        xs = np.array([0.5, 3.0, 7.5])
        assert np.allclose(g.distance(xs, xs), f.distance(xs, xs), rtol=1e-6)
    with np.load(path) as z:
        a = {k: z[k] for k in z.files}
    a["keys"] = np.array([{"evil": 1}], dtype=object)
    np.savez(tmp_path / "evil.npz", **a)
    with pytest.raises(ValueError):
        load_geofields(tmp_path / "evil.npz")


# ------------------------------------------------------------------ check CLI
def test_check_cli_on_fixture(tmp_path: Path, capsys) -> None:
    d = tmp_path / "pack"
    d.mkdir()
    (d / "landmask.npz").write_bytes(FIXTURE.read_bytes())
    (d / "landmask.json").write_bytes(FIXTURE.with_suffix(".json").read_bytes())
    assert land.main(["check", str(d)]) == 0
    out = capsys.readouterr().out
    for name in land.REQUIRED_SEA_POINTS:
        assert name in out
    assert "Prvić–Tijat" in out and "ouvert" in out


def test_check_cli_names_an_unreachable_point(tmp_path: Path, capsys) -> None:
    with np.load(FIXTURE) as z:
        a = {k: z[k] for k in z.files}
    ny, nx = (int(v) for v in a["shape"])
    mask = np.unpackbits(a["mask"], axis=1, count=nx).astype(bool)
    m = LandMask.load(FIXTURE)
    r, c = _rc(m, land.REQUIRED_SEA_POINTS["jabuka_A"])
    yy, xx = np.mgrid[r - 30 : r + 31, c - 30 : c + 31]
    ring = (np.hypot(yy - r, xx - c) > 12) & (np.hypot(yy - r, xx - c) < 20)
    mask[yy[ring], xx[ring]] = True  # a ring of "land" 300-500 m around the rounding point
    a["mask"] = np.packbits(mask, axis=1)
    d = tmp_path / "cut"
    d.mkdir()
    np.savez_compressed(d / "landmask.npz", **a)
    assert land.main(["check", str(d)]) == 1
    out = capsys.readouterr().out
    assert "jabuka_A" in out and "ÉCHEC" in out
