"""Typed mark coordinates (quick 003, web/static/coord_logic.js), run through node: the tolerant
degrees + decimal minutes parser a race committee's VHF position is typed into, the display format,
the race-area check and parse(format(x)) round trips."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
LOGIC = STATIC / "coord_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

LAT_4345_2 = 43 + 45.2 / 60  # 43°45,2' N
LON_1540_1 = 15 + 40.1 / 60  # 15°40,1' E


def js(expr: str) -> object:
    code = (
        f"import * as L from {json.dumps(LOGIC.as_uri())};\n"
        f"const f = new Function(...Object.keys(L), {json.dumps('return (' + expr + ');')});\n"
        "process.stdout.write(JSON.stringify(f(...Object.values(L))));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def parse_all(texts: list[str], axis: str) -> list[dict]:
    return js(f"{json.dumps(texts)}.map((s) => parseCoord(s, {json.dumps(axis)}))")


@pytest.mark.parametrize(
    "text",
    [
        "43 45.2",
        "43 45,2",
        "43°45,2'",
        "43°45.2'",
        "43°45.2N",
        "43°45,2' N",
        "43° 45,2′ N",
        "N 43 45.2",
        "N43°45.2",
        "n 43 45,2",
        "  43   45,2  ",
        "43:45.2",
        "43*45,2",
        "43 45.20000",
        "+43 45,2",
        "43.45.2",  # numeric keypad without a space key
        "43,45,2",
        "43,45.2",
        "43 45 12",  # degrees minutes seconds
        "43°45'12\"",
        "43°45′12″N",
    ],
)
def test_latitude_formats(text: str) -> None:
    (r,) = parse_all([text], "lat")
    assert r["ok"] is True, (text, r)
    assert r["value"] == pytest.approx(LAT_4345_2, abs=1e-9)


def test_decimal_degrees_with_point_or_comma() -> None:
    rs = parse_all(["43.7533", "43,7533", "43.7533N", "43", "43 N", "0"], "lat")
    assert [r["value"] for r in rs] == pytest.approx([43.7533, 43.7533, 43.7533, 43.0, 43.0, 0.0])


def test_longitude_formats_and_hemispheres() -> None:
    rs = parse_all(
        ["15 40,1", "15°40.1'E", "E 15 40,1", "15 40,1 W", "15 40,1 O", "-15 40,1", "W15°40,1"],
        "lon",
    )
    values = [r["value"] for r in rs]
    assert values == pytest.approx([LON_1540_1] * 3 + [-LON_1540_1] * 4, abs=1e-9)
    south = parse_all(["43 45,2 S", "S43 45,2", "-43 45,2", "-43.7533"], "lat")
    assert [r["value"] for r in south] == pytest.approx([-LAT_4345_2] * 3 + [-43.7533], abs=1e-9)


@pytest.mark.parametrize(
    ("text", "axis", "error"),
    [
        ("", "lat", "empty"),
        ("   ", "lat", "empty"),
        ("abc", "lat", "format"),
        ("43 45,2 x", "lat", "format"),
        ("43.5 30", "lat", "format"),  # fractional degrees with minutes
        ("43 45.5 10", "lat", "format"),  # fractional minutes with seconds
        ("43 45 2 1", "lat", "format"),  # four fields
        ("43 45.2.1", "lat", "format"),
        ("43..2", "lat", "format"),
        ("N", "lat", "format"),
        ("-", "lat", "format"),
        ("N 43 45,2 S", "lat", "format"),  # two letters
        ("N -43", "lat", "format"),
        ("43 60", "lat", "minutes"),
        ("43 60,0", "lat", "minutes"),
        ("43 75", "lat", "minutes"),
        ("43 59 60", "lat", "seconds"),
        ("91", "lat", "range"),
        ("4345.2", "lat", "range"),  # NMEA ddmm.mm is not guessed
        ("181 00", "lon", "range"),
        ("43 45,2 E", "lat", "hemisphere"),
        ("15 40,1 N", "lon", "hemisphere"),
        ("S 15 40,1", "lon", "hemisphere"),
        ("43 45,2 O", "lat", "hemisphere"),
    ],
)
def test_invalid_input(text: str, axis: str, error: str) -> None:
    (r,) = parse_all([text], axis)
    assert r == {"ok": False, "error": error}, (text, r)


def test_minutes_just_below_sixty_are_accepted() -> None:
    (r,) = parse_all(["43 59,999"], "lat")
    assert r["ok"] and r["value"] == pytest.approx(43 + 59.999 / 60)


def test_format_degrees_decimal_minutes() -> None:
    assert js(f"formatDM({LAT_4345_2}, 'lat')") == "43°45.200' N"
    assert js(f"formatDM({LAT_4345_2}, 'lat', {{sep: ','}})") == "43°45,200' N"
    assert js(f"formatDM({LON_1540_1}, 'lon', {{sep: ','}})") == "15°40,100' E"
    assert js("formatDM(15.0011, 'lon')") == "15°00.066' E"  # minutes padded to two digits
    assert js("formatDM(-0.5, 'lat')") == "0°30.000' S"
    assert js("formatDM(-15.5, 'lon', {digits: 1})") == "15°30.0' W"
    assert js("formatDM(42.7, 'lat', {digits: 0})") == "42°42' N"
    assert js("[formatDM(null, 'lat'), formatDM(NaN, 'lon'), formatDM(Infinity, 'lat')]") == [
        "",
        "",
        "",
    ]


def test_rounding_at_59_99_minutes_carries_to_the_next_degree() -> None:
    # 43°59,9996' with 3 decimals is 44°00,000', never 43°60,000'
    assert js(f"formatDM({43 + 59.9996 / 60}, 'lat', {{sep: ','}})") == "44°00,000' N"
    assert js(f"dmParts({43 + 59.9996 / 60}, 3)") == {"deg": 44, "min": 0, "neg": False}
    assert js(f"formatDM({15 + 59.96 / 60}, 'lon', {{digits: 1}})") == "16°00.0' E"
    assert js(f"formatDM({43 + 59.994 / 60}, 'lat')") == "43°59.994' N"  # no carry
    assert js(f"formatDM({-(43 + 59.9996 / 60)}, 'lat')") == "44°00.000' S"


def test_round_trips() -> None:
    """parse(format(x)) within half a thousandth of a minute, over the race area and beyond."""
    worst = js(
        """(() => {
          let worst = 0;
          for (let i = 0; i <= 2000; i++) {
            const lat = 42 + (3 * i) / 2000 + 1e-7 * (i % 7);
            const lon = -16.4 + (33 * i) / 2000 - 1e-7 * (i % 5);
            for (const [v, axis] of [[lat, "lat"], [lon, "lon"], [-lat, "lat"]]) {
              for (const sep of [".", ","]) {
                const r = parseCoord(formatDM(v, axis, {sep}), axis);
                if (!r.ok) return {fail: formatDM(v, axis, {sep})};
                worst = Math.max(worst, Math.abs(r.value - v));
              }
            }
          }
          return {worst};
        })()"""
    )
    assert "fail" not in worst, worst
    assert worst["worst"] <= 0.0005 / 60 + 1e-12  # 0.0005' (< 1 m)
    # a VHF position typed back from its own display is the same position
    assert js(f"parseCoord(formatDM({LAT_4345_2}, 'lat', {{sep: ','}}), 'lat').value") == (
        pytest.approx(LAT_4345_2, abs=1e-12)
    )


def test_race_area_and_check_position() -> None:
    area = js("RACE_AREA")
    assert area == {"south": 42.7, "north": 44.1, "west": 14.9, "east": 16.4}
    assert js("SERVER_LIMITS") == {"south": 42.0, "north": 45.0, "west": 14.0, "east": 17.0}
    # the map's maxBounds, clipped to what the core accepts; garbage -> RACE_AREA
    assert js("areaFrom([[14.9, 42.7], [16.4, 44.1]])") == area
    assert js("areaFrom([[13.0, 41.0], [18.0, 46.0]])") == js("SERVER_LIMITS")
    assert js("[areaFrom(null), areaFrom([]), areaFrom([[16, 44], [15, 43]])]") == [area] * 3
    assert js("areaFrom([[20, 50], [21, 51]])") == area  # no overlap with the server limits
    assert js("[inArea(43.75, 15.67), inArea(42.5, 15.67), inArea(43.75, 16.5)]") == [
        True,
        False,
        False,
    ]

    ok = js("checkPosition('43 45,2', '15 40,1', RACE_AREA)")
    assert ok["ok"] is True and ok["areaError"] is False
    assert ok["lat"] == pytest.approx(LAT_4345_2) and ok["lon"] == pytest.approx(LON_1540_1)
    assert ok["latError"] is None and ok["lonError"] is None

    out = js("checkPosition('42 30', '15 40,1', RACE_AREA)")  # 42°30' N: south of the area
    assert out["ok"] is False and out["areaError"] is True
    assert out["latError"] is None and out["lat"] == pytest.approx(42.5)

    bad = js("checkPosition('43 61', '', RACE_AREA)")
    assert bad == {
        "lat": None,
        "lon": None,
        "ok": False,
        "latError": "minutes",
        "lonError": "empty",
        "areaError": False,
    }


def test_unknown_axis_throws() -> None:
    assert js(
        "(() => { try { parseCoord('43', 'x'); return 'no'; } catch { return 'threw'; } })()"
    ) == ("threw")
