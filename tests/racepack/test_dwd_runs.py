"""DWD open data: listing parse, run selection (partial run, fallback), URLs, offline downloads."""

from __future__ import annotations

import bz2
import io
import os
import socket
import threading
import time
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
    import pygrib  # noqa: F401
else:
    pytest.importorskip("numpy")
    pytest.importorskip("pygrib")

from jabuka.prep import cli, dwd  # noqa: E402
from jabuka.route.racepack import RaceWindow, load_pack  # noqa: E402

DWD = Path(__file__).resolve().parents[1] / "fixtures" / "racepack" / "dwd"
REPO_MARKS = Path(__file__).resolve().parents[2] / "src" / "jabuka" / "nav" / "data" / "marks.json"


def _ts(*a: int) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp())


WINDOW = RaceWindow(_ts(2026, 11, 13, 17), _ts(2026, 11, 15, 9))
NOW = _ts(2026, 11, 13, 16)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network access attempted in a test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _html(name: str, *, to_date: str | None = None) -> str:
    text = (DWD / name).read_text(encoding="utf-8")
    return text.replace("20261105", to_date) if to_date else text


def _icon(html: str, var: str) -> dict:
    return dwd.parse_listing(html, dwd.icon_listing_pattern(var))


def _race_listings() -> dict:
    """The saved 5 Nov listings moved to 13 Nov: complete 12Z run + 15Z run still publishing."""
    u12 = _html("icon-eu_u_10m_12.html", to_date="20261113")
    v12 = _html("icon-eu_v_10m_12.html", to_date="20261113")
    u15 = _html("icon-eu_u_10m_15_partial.html", to_date="20261113")
    v15 = u15.replace("_U_10M", "_V_10M")
    return {
        "u_10m": dwd.merge_listings(_icon(u12, "u_10m"), _icon(u15, "u_10m")),
        "v_10m": dwd.merge_listings(_icon(v12, "v_10m"), _icon(v15, "v_10m")),
    }


def test_parse_listing_complete_12z_run() -> None:
    lst = _icon(_html("icon-eu_u_10m_12.html"), "u_10m")
    run = datetime(2026, 11, 5, 12, tzinfo=UTC)
    assert list(lst) == [run]
    assert sorted(lst[run]) == dwd.model_steps("ICON-EU", 12)
    assert len(lst[run]) == 93
    assert dwd.missing_steps("ICON-EU", run, lst[run]) == []
    # the v listing does not leak into the u pattern
    assert _icon(_html("icon-eu_v_10m_12.html"), "u_10m") == {}


def test_parse_listing_partial_15z_run_reports_missing_steps() -> None:
    lst = _icon(_html("icon-eu_u_10m_15_partial.html"), "u_10m")
    run = datetime(2026, 11, 5, 15, tzinfo=UTC)
    assert sorted(lst[run]) == list(range(0, 31))
    assert dwd.missing_steps("ICON-EU", run, lst[run]) == list(range(31, 52))


def test_parse_ewam_listing_keeps_two_runs() -> None:
    lst = dwd.parse_listing(_html("ewam_swh_12.html"), dwd.ewam_listing_pattern("swh"))
    assert sorted(lst) == [
        datetime(2026, 11, 4, 12, tzinfo=UTC),
        datetime(2026, 11, 5, 12, tzinfo=UTC),
    ]
    assert all(sorted(s) == list(range(79)) for s in lst.values())


def test_select_run_friday_picks_complete_12z_not_partial_15z() -> None:
    choice = dwd.select_run(_race_listings(), WINDOW, NOW, "ICON-EU")
    assert choice is not None and not choice.incomplete
    assert choice.run == datetime(2026, 11, 13, 12, tzinfo=UTC)
    assert choice.steps == list(range(5, 46))  # +5 .. +45 hourly
    assert any("15Z incomplet" in s for s in choice.skipped)


def test_select_run_falls_back_when_12z_has_a_hole() -> None:
    lst = _race_listings()
    run12 = datetime(2026, 11, 13, 12, tzinfo=UTC)
    run09 = datetime(2026, 11, 13, 9, tzinfo=UTC)
    lst["u_10m"][run12].discard(30)
    for var in lst:
        lst[var][run09] = set(range(52))
    choice = dwd.select_run(lst, WINDOW, NOW, "ICON-EU")
    assert choice is not None and not choice.incomplete
    assert choice.run == run09 and choice.steps == list(range(8, 49))


def test_select_run_far_ahead_returns_newest_complete_run_flagged_incomplete() -> None:
    lst = {
        "u_10m": dwd.merge_listings(
            _icon(_html("icon-eu_u_10m_12.html"), "u_10m"),
            _icon(_html("icon-eu_u_10m_15_partial.html"), "u_10m"),
        ),
        "v_10m": _icon(_html("icon-eu_v_10m_12.html"), "v_10m"),
    }
    choice = dwd.select_run(lst, WINDOW, _ts(2026, 11, 6, 4), "ICON-EU")
    assert choice is not None and choice.incomplete
    assert choice.run == datetime(2026, 11, 5, 12, tzinfo=UTC)  # 15Z is partial
    assert choice.steps == list(range(0, 49))
    assert dwd.select_run({"u_10m": {}, "v_10m": {}}, WINDOW, NOW, "ICON-EU") is None


def test_select_run_three_hourly_tail_brackets_the_window() -> None:
    run = datetime(2026, 11, 12, 0, tzinfo=UTC)
    lst = {v: {run: set(dwd.model_steps("ICON-EU", 0))} for v in dwd.ICON_VARS}
    choice = dwd.select_run(lst, WINDOW, NOW, "ICON-EU")
    assert choice is not None and not choice.incomplete
    # window +41 h .. +81 h: hourly to +78, then +81 (3-hourly part)
    assert choice.steps[0] == 41 and choice.steps[-3:] == [77, 78, 81]


def test_url_patterns_match_research() -> None:
    run = datetime(2026, 11, 13, 12, tzinfo=UTC)
    assert dwd.icon_eu_urls(run, [5, 45], "u_10m") == [
        "https://opendata.dwd.de/weather/nwp/icon-eu/grib/12/u_10m/"
        "icon-eu_europe_regular-lat-lon_single-level_2026111312_005_U_10M.grib2.bz2",
        "https://opendata.dwd.de/weather/nwp/icon-eu/grib/12/u_10m/"
        "icon-eu_europe_regular-lat-lon_single-level_2026111312_045_U_10M.grib2.bz2",
    ]
    assert dwd.icon_eu_urls(datetime(2026, 11, 13, 3, tzinfo=UTC), [0], "v_10m") == [
        "https://opendata.dwd.de/weather/nwp/icon-eu/grib/03/v_10m/"
        "icon-eu_europe_regular-lat-lon_single-level_2026111303_000_V_10M.grib2.bz2"
    ]
    assert dwd.ewam_urls(run, [7], "swh") == [
        "https://opendata.dwd.de/weather/maritime/wave_models/ewam/grib/12/swh/"
        "EWAM_SWH_2026111312_007.grib2.bz2"
    ]
    assert dwd.ewam_urls(run, [78], "mwd")[0].endswith("/12/mwd/EWAM_MWD_2026111312_078.grib2.bz2")
    with pytest.raises(ValueError):
        dwd.icon_eu_urls(run, [0], "t_2m")


# --------------------------------------------------------------------------- downloads

PAYLOAD = bz2.compress(b"GRIB" + b"x" * 1000 + b"7777")


class FakeOpener:
    def __init__(self, fail_first: int = 0, delay: float = 0.0, payload: bytes = PAYLOAD):
        self.calls: list[str] = []
        self.fail_first = fail_first
        self.delay = delay
        self.payload = payload
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, url, timeout=None):
        with self.lock:
            self.calls.append(url)
            n = len(self.calls)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if n <= self.fail_first:
                raise urllib.error.URLError("temporary failure")
            assert timeout == dwd.TIMEOUT_S
            return io.BytesIO(self.payload)
        finally:
            with self.lock:
                self.active -= 1


def _urls(n: int) -> list[str]:
    run = datetime(2026, 11, 13, 12, tzinfo=UTC)
    return dwd.icon_eu_urls(run, range(n), "u_10m")


def test_download_retries_a_transient_failure(tmp_path) -> None:
    op = FakeOpener(fail_first=1)
    sleeps: list[float] = []
    res = dwd.download_all(_urls(1), tmp_path, opener=op, sleep=sleeps.append)
    assert len(op.calls) == 2 and sleeps == [1.0]
    assert res.downloaded == 1 and res.paths[0].read_bytes() == PAYLOAD
    assert res.downloaded_bytes == len(PAYLOAD)


def test_download_gives_up_after_three_attempts(tmp_path) -> None:
    op = FakeOpener(fail_first=10)
    with pytest.raises(RuntimeError, match="en échec"):
        dwd.download_all(_urls(1), tmp_path, opener=op, sleep=lambda s: None)
    assert len(op.calls) == 3
    assert not any(tmp_path.iterdir())


def test_download_skips_verified_cache_and_refetches_truncated(tmp_path) -> None:
    urls = _urls(2)
    good, bad = (tmp_path / dwd.check_url(u) for u in urls)
    good.write_bytes(PAYLOAD)
    bad.write_bytes(PAYLOAD[: len(PAYLOAD) // 2])  # truncated by an interrupted run
    op = FakeOpener()
    res = dwd.download_all(urls, tmp_path, opener=op)
    assert op.calls == [urls[1]]
    assert res.cached == 1 and res.downloaded == 1
    assert bad.read_bytes() == PAYLOAD


def test_download_rejects_corrupt_payload(tmp_path) -> None:
    op = FakeOpener(payload=b"BZh9 not really bz2")
    with pytest.raises(RuntimeError):
        dwd.download_all(_urls(1), tmp_path, opener=op, sleep=lambda s: None)
    assert len(op.calls) == 3


def test_download_never_exceeds_six_concurrent_requests(tmp_path) -> None:
    op = FakeOpener(delay=0.03)
    res = dwd.download_all(_urls(20), tmp_path, opener=op, max_workers=32)
    assert res.downloaded == 20
    assert 1 < op.max_active <= 6


def test_download_refuses_non_https_url(tmp_path) -> None:
    op = FakeOpener()
    url = "http://opendata.dwd.de/weather/nwp/icon-eu/grib/12/u_10m/x.grib2.bz2"
    with pytest.raises(ValueError, match="https"):
        dwd.download_all([*_urls(1), url], tmp_path, opener=op)
    assert op.calls == []


def test_download_refuses_other_hosts_and_odd_names(tmp_path) -> None:
    op = FakeOpener()
    with pytest.raises(ValueError, match="hôte"):
        dwd.download_all(["https://evil.example/x.grib2.bz2"], tmp_path, opener=op)
    with pytest.raises(ValueError):
        dwd.download_all(["https://opendata.dwd.de/weather/.."], tmp_path, opener=op)
    assert op.calls == []


# --------------------------------------------------------------------------- CLI, offline


def _listing_html(names: list[str]) -> str:
    rows = "\n".join(
        f'<a href="{n}">{n[:40]}..&gt;</a> 13-Nov-2026 15:00:00 1200000' for n in names
    )
    return f"<html><body><pre>\n{rows}\n</pre></body></html>\n"


def test_cli_wind_from_saved_listings_and_cache(rp, tmp_path, capsys) -> None:
    run = rp.run_13_12z
    listing_dir = tmp_path / "listings"
    listing_dir.mkdir()
    cache = tmp_path / "cache"
    (cache / "icon-eu").mkdir(parents=True)
    for var in dwd.ICON_VARS:
        urls = dwd.icon_eu_urls(run, dwd.model_steps("ICON-EU", 12), var)
        names = [u.rsplit("/", 1)[1] for u in urls]
        (listing_dir / f"icon-eu_{var}_12.html").write_text(_listing_html(names), encoding="utf-8")
        short = "10u" if var == "u_10m" else "10v"
        for step in range(5, 46):  # what the selection needs: no download happens
            msg = rp.grib_message(short_name=short, run=run, forecast=step * 60, values=-3.0)
            name = dwd.icon_eu_urls(run, [step], var)[0].rsplit("/", 1)[1]
            (cache / "icon-eu" / name).write_bytes(bz2.compress(msg))

    def no_net(*a, **k):
        raise AssertionError("no download expected")

    cli.URL_OPENER = no_net
    try:
        rc = cli.main(
            ["wind", "--listing-dir", str(listing_dir), "--cache", str(cache),
             "--out", str(tmp_path / "pack"), "--marks", str(REPO_MARKS),
             "--now", "2026-11-13T16:00Z"]
        )  # fmt: skip
    finally:
        cli.URL_OPENER = None
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "run 2026-11-13 12Z, échéances +5..+45 (41)" in out
    assert "0 fichiers téléchargés" in out and "82 déjà en cache" in out
    pack = load_pack(tmp_path / "pack")
    assert pack.errors == [] and pack.wind is not None
    assert pack.wind.t[0] == _ts(2026, 11, 13, 17) and pack.wind.t[-1] == _ts(2026, 11, 15, 9)
    assert "Deutscher Wetterdienst" in pack.meta["wind"]["source"]


def test_cli_wind_incomplete_run_exits_3(rp, tmp_path, capsys) -> None:
    run = datetime(2026, 11, 5, 12, tzinfo=UTC)
    listing_dir = tmp_path / "listings"
    listing_dir.mkdir()
    for name in ("icon-eu_u_10m_12.html", "icon-eu_v_10m_12.html"):
        (listing_dir / name).write_text(_html(name), encoding="utf-8")
    cache = tmp_path / "cache" / "icon-eu"
    cache.mkdir(parents=True)
    for var, short in (("u_10m", "10u"), ("v_10m", "10v")):
        for step in range(0, 49):
            msg = rp.grib_message(short_name=short, run=run, forecast=step * 60)
            name = dwd.icon_eu_urls(run, [step], var)[0].rsplit("/", 1)[1]
            (cache / name).write_bytes(bz2.compress(msg))
    rc = cli.main(
        ["wind", "--listing-dir", str(listing_dir), "--cache", str(tmp_path / "cache"),
         "--out", str(tmp_path / "pack"), "--marks", str(REPO_MARKS),
         "--now", "2026-11-06T04:00Z"]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert rc == 3
    assert "MÉTÉO INCOMPLÈTE" in out
    assert (tmp_path / "pack" / "wind.npz").is_file()


def test_redirects_are_checked_against_the_allowed_hosts(monkeypatch) -> None:
    """03-REVIEW LO-07: urlopen followed a redirect to any host after check_host approved the
    first URL; the DWD opener re-checks every redirect target."""
    import urllib.request

    req = urllib.request.Request("https://opendata.dwd.de/weather/nwp/x.grib2.bz2")
    handler = dwd._CheckedRedirect()
    with pytest.raises(ValueError, match="hôte non autorisé"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x")
    with pytest.raises(ValueError, match="https obligatoire"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://opendata.dwd.de/x")
    ok = handler.redirect_request(req, None, 302, "Found", {}, "https://opendata.dwd.de/y")
    assert ok.full_url == "https://opendata.dwd.de/y"
    with pytest.raises(ValueError, match="hôte non autorisé"):
        dwd.safe_urlopen("https://evil.example/x")  # refused before any connection
    monkeypatch.setattr(cli, "URL_OPENER", None)
    assert cli._opener() is dwd.safe_urlopen
    import inspect

    for fn in (dwd.download_all, dwd.fetch_listings):
        assert inspect.signature(fn).parameters["opener"].default is dwd.safe_urlopen
