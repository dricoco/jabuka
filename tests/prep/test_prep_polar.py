"""jabuka-prep-polar (WIND-01): OpenCPN/qtVlm grid, Expedition, ORC certificate table and JSON
polars become the race-pack polar.json that the core loads."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jabuka.nav.polar import default_polar, load_racepack_polar, parse_expedition, polar_to_json
from jabuka.prep import polar as pp

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "polar"
ORC = FIX / "x35-orc-table.csv"
GRID = FIX / "grid-semicolon.pol"
EXP = FIX / "expedition.txt"

GRID_CELLS = {  # (tws, twa) -> bsp, empty and zero cells left out
    (6, 40): 4.8, (10, 40): 6.2, (16, 40): 6.6,
    (6, 52): 5.6, (10, 52): 7.0, (16, 52): 7.3,
    (6, 90): 6.1, (10, 90): 7.4, (16, 90): 8.3,
    (6, 120): 5.8, (10, 120): 7.4, (16, 120): 8.9,
    (6, 150): 4.4, (10, 150): 6.5, (16, 150): 8.0,
    (16, 170): 7.6,
}  # fmt: skip


# -- ORC certificate table ----------------------------------------------------------------------
def test_orc_table_matches_the_derived_expedition_polar() -> None:
    got = pp.parse_orc_table(ORC.read_text("utf-8"), "x35")
    ref = default_polar()
    assert [t for t, _ in got.curves] == [t for t, _ in ref.curves] == [6, 8, 10, 12, 14, 16, 20]
    for (tws, pts), (_, ref_pts) in zip(got.curves, ref.curves, strict=True):
        assert len(pts) == len(ref_pts), tws
        for (a, b), (ra, rb) in zip(pts, ref_pts, strict=True):
            assert a == pytest.approx(ra, abs=0.01), (tws, a)
            assert b == pytest.approx(rb, abs=0.01), (tws, a)
            assert got.speed(tws, ra) == pytest.approx(ref.speed(tws, ra), abs=0.01)
    assert got.targets(12.0).up_twa == pytest.approx(37.7, abs=0.05)
    assert got.targets(12.0).down_twa == pytest.approx(158.9, abs=0.05)


def test_orc_table_whitespace_and_semicolon_layouts() -> None:
    text = ORC.read_text("utf-8")
    ref = pp.parse_orc_table(text, "x35")
    spaced = pp.parse_orc_table(text.replace(",", "  "), "x35")  # pdftotext-like
    semi = pp.parse_orc_table(text.replace(",", ";").replace("°", ""), "x35")
    assert spaced.curves == ref.curves
    assert semi.curves == ref.curves


def test_orc_table_without_beat_vmg_is_rejected() -> None:
    text = "\n".join(
        line for line in ORC.read_text("utf-8").splitlines() if not line.startswith("Beat VMG")
    )
    with pytest.raises(ValueError, match="Beat VMG"):
        pp.parse_orc_table(text, "x")


# -- OpenCPN / qtVlm grid -----------------------------------------------------------------------
def test_grid_semicolon_with_decimal_commas() -> None:
    p = pp.parse_grid(GRID.read_text("utf-8"), "grid")
    assert [t for t, _ in p.curves] == [6, 10, 16]
    for (tws, twa), bsp in GRID_CELLS.items():
        assert p.speed(tws, twa) == pytest.approx(bsp, abs=1e-9), (tws, twa)
    # empty (6 kn) and zero (10 kn) cells at 170 are skipped, not read as 0 kn
    assert [a for a, _ in dict(p.curves)[6]] == [0, 40, 52, 90, 120, 150]  # + implicit origin
    assert [a for a, _ in dict(p.curves)[10]] == [0, 40, 52, 90, 120, 150]


def test_grid_tab_separated_lowercase_header_gives_the_same_polar() -> None:
    text = GRID.read_text("utf-8")
    tab = text.replace(";", "\t").replace(",", ".").replace("TWA\\TWS", "twa/tws")
    ref = pp.parse_grid(text, "grid")
    assert pp.parse_grid(tab, "grid").curves == ref.curves
    # runs of spaces cannot carry empty cells: compare without the sparse 170 row, and a short
    # row is an error rather than a silent column shift
    dense = "\n".join(text.splitlines()[:-1]) + "\n"
    spaced = dense.replace(";", "   ").replace(",", ".")
    assert pp.parse_grid(spaced, "grid").curves == pp.parse_grid(dense, "grid").curves
    with pytest.raises(ValueError, match="line 8"):
        pp.parse_grid(text.replace(";", "   ").replace(",", "."), "grid")


# -- parse_any dispatch + validation ------------------------------------------------------------
def test_parse_any_dispatches_by_content() -> None:
    assert pp.parse_any(ORC.read_text("utf-8"), "a").source == "orc-table"
    assert pp.parse_any(GRID.read_text("utf-8"), "b").source == "grid"
    exp = pp.parse_any(EXP.read_text("utf-8"), "c")
    assert exp.source == "expedition"
    assert exp.curves == parse_expedition(EXP.read_text("utf-8"), "c").curves
    js = pp.parse_any(json.dumps(polar_to_json(default_polar())), "d")
    assert js.source == "json"
    assert js.curves == default_polar().curves


@pytest.mark.parametrize(
    "text, needle",
    [
        ("8 40 5.9 90 nan\n12 40 6.5 90 7.7\n", "line 1"),
        ("8 40 5.9 90 7.0\n12 40 6.5 90 inf\n", "line 2"),
        ("8 40 5.9 90 31.0\n12 40 6.5 90 7.7\n", "BSP"),
        ("8 40 5.9 190 7.0\n12 40 6.5 90 7.7\n", "TWA"),
        ("8 0 5.9 90 7.0\n12 40 6.5 90 7.7\n", "TWA"),
        ("61 40 5.9 90 7.0\n12 40 6.5 90 7.7\n", "TWS"),
        ("0 40 5.9 90 7.0\n12 40 6.5 90 7.7\n", "TWS"),
        ("8 40 5.9 90 7.0\n", "2 TWS"),
        ("TWA\\TWS;6;10\n40;4.8;nan\n90;6.1;7.4\n", "line 2"),
        ("TWA\\TWS;6;70\n40;4.8;6.2\n90;6.1;7.4\n", "TWS"),
        ("TWA\\TWS;6;10\n40;4.8;6.2\n200;6.1;7.4\n", "line 3"),
        ("TWA\\TWS;6\n40;4.8\n90;6.1\n", "2 TWS"),
        ('{"curves": [[8, [[40, 5.9]]], [12, [[40, 45.0]]]]}', "BSP"),
        ("hello world\n", "line 1"),
        ("", "no data"),
    ],
)
def test_parse_any_rejects_invalid_values(text: str, needle: str) -> None:
    with pytest.raises(ValueError, match=re.escape(needle)):
        pp.parse_any(text, "x")


def test_parse_any_rejects_files_over_1_mb() -> None:
    big = "! padding\n" * 120_000 + "8 40 5.9 90 7.0\n12 40 6.5 90 7.7\n"
    with pytest.raises(ValueError, match="1 MB"):
        pp.parse_any(big, "x")


# -- CLI ----------------------------------------------------------------------------------------
def _row(out: str, tws: int) -> str:
    return next(line for line in out.splitlines() if re.match(rf"\s*{tws}\s*\|", line))


def test_cli_converts_the_orc_table_into_the_race_pack(tmp_path: Path, capsys) -> None:
    out = tmp_path / "polar.json"
    assert pp.main([str(ORC), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    row = _row(printed, 12)
    assert "37.7" in row and "158.9" in row
    loaded = load_racepack_polar(tmp_path)
    assert loaded.source == "racepack:polar.json"
    assert loaded.name == "x35-orc-table"
    assert loaded.curves == pp.parse_orc_table(ORC.read_text("utf-8"), "x").curves
    assert not (tmp_path / "polar.json.bak").exists()


def test_cli_name_option_and_latin1_input(tmp_path: Path, capsys) -> None:
    src = tmp_path / "x35-latin1.csv"
    src.write_bytes(ORC.read_text("utf-8").encode("latin-1"))  # '°' as 0xB0
    out = tmp_path / "pack" / "polar.json"
    assert pp.main([str(src), "--name", "X35 owner 2026", "--out", str(out)]) == 0
    assert load_racepack_polar(out.parent).name == "X35 owner 2026"


def test_cli_garbage_and_missing_input_exit_2(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "garbage.pol"
    bad.write_bytes(b"\x00\x01 this is not a polar \xff\n")
    assert pp.main([str(bad), "--out", str(tmp_path / "polar.json")]) == 2
    assert not (tmp_path / "polar.json").exists()
    assert pp.main([str(tmp_path / "missing.pol"), "--out", str(tmp_path / "p.json")]) == 2
    big = tmp_path / "big.pol"
    big.write_bytes(b"!" * (1024 * 1024 + 10))
    assert pp.main([str(big), "--out", str(tmp_path / "p.json")]) == 2
    assert "1 MB" in capsys.readouterr().err


def test_cli_help_and_usage() -> None:
    assert pp.main(["--help"]) == 0
    assert pp.main([]) == 2
