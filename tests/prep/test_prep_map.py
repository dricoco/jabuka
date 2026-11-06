"""jabuka-prep-map basemap half (HELM-01): Protomaps build search, checksum-pinned go-pmtiles,
pure-Python extract, manifest and --check. Offline: downloads and extracts are injected."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import shutil
import stat
import tarfile
from pathlib import Path

import pytest

from jabuka.core.tiles import TileIndex
from jabuka.prep import map as pm

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "map" / "sibenik.pmtiles"
FIXTURE_BBOX = (15.70, 43.62, 15.95, 43.80)


def _pack(tmp_path: Path) -> Path:
    d = tmp_path / "pack"
    d.mkdir()
    shutil.copy(FIXTURE, d / "race.pmtiles")
    pm.write_manifest(d, {"bbox": FIXTURE_BBOX, "maxzoom": 11, "protomaps_build": "20261105"})
    return d


# -- Protomaps builds ---------------------------------------------------------------------------
def test_protomaps_candidates_newest_first_over_a_week() -> None:
    urls = pm.protomaps_candidates(dt.date(2026, 11, 10))
    assert len(urls) == 8
    assert urls[0] == "https://build.protomaps.com/20261110.pmtiles"
    assert urls[-1] == "https://build.protomaps.com/20261103.pmtiles"
    assert pm.build_day(urls[2]) == "20261108"


def test_find_build_takes_the_first_answering_url() -> None:
    probed: list[str] = []

    def probe(url: str) -> bool:
        probed.append(url)
        return url.endswith("20261105.pmtiles")

    url = pm.find_build(dt.date(2026, 11, 6), probe, log=lambda _m: None)
    assert url == "https://build.protomaps.com/20261105.pmtiles"
    assert len(probed) == 2
    assert pm.find_build(dt.date(2026, 11, 6), lambda _u: False, log=lambda _m: None) is None


# -- go-pmtiles download ------------------------------------------------------------------------
def _fake_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"#!/bin/sh\necho fake\n"
        info = tarfile.TarInfo("pmtiles")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_tarball_with_wrong_hash_is_deleted_and_never_unpacked(tmp_path: Path) -> None:
    blob = _fake_tarball()

    def download(url: str, dest: Path, max_bytes: int) -> Path:
        assert url == pm.GO_PMTILES_URL
        dest.write_bytes(blob)
        return dest

    cache = tmp_path / "go-pmtiles"
    with pytest.raises(ValueError, match="sha256"):
        pm.ensure_go_pmtiles(cache, download=download, log=lambda _m: None)
    assert not (cache / "pmtiles").exists()
    assert not (cache / pm.GO_PMTILES_ASSET).exists()


def test_tarball_with_pinned_hash_is_unpacked(tmp_path: Path, monkeypatch) -> None:
    blob = _fake_tarball()
    monkeypatch.setattr(pm, "GO_PMTILES_SHA256", hashlib.sha256(blob).hexdigest())

    def download(url: str, dest: Path, max_bytes: int) -> Path:
        dest.write_bytes(blob)
        return dest

    binary = pm.ensure_go_pmtiles(tmp_path, download=download, log=lambda _m: None)
    assert binary == tmp_path / "pmtiles"
    assert binary.stat().st_mode & stat.S_IXUSR
    # a tampered cached tarball is re-checked on the next call
    (tmp_path / pm.GO_PMTILES_ASSET).write_bytes(blob + b"x")
    with pytest.raises(ValueError, match="sha256"):
        pm.ensure_go_pmtiles(tmp_path, download=download, log=lambda _m: None)
    assert not binary.exists()


def test_pinned_hash_is_the_release_digest() -> None:
    assert pm.GO_PMTILES_SHA256.startswith("3ed7dbf4") and pm.GO_PMTILES_SHA256.endswith("312f")
    assert len(pm.GO_PMTILES_SHA256) == 64


def test_go_extractor_command_line(tmp_path: Path) -> None:
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))

    ex = pm.go_extractor("/opt/pmtiles", run=run, log=lambda _m: None)
    ex("https://build.protomaps.com/20261105.pmtiles", tmp_path / "o.pmtiles", pm.DEFAULT_BBOX, 14)
    cmd, kw = calls[0]
    assert cmd == [
        "/opt/pmtiles",
        "extract",
        "https://build.protomaps.com/20261105.pmtiles",
        str(tmp_path / "o.pmtiles"),
        "--bbox=15,42.8,16.3,44",
        "--maxzoom=14",
    ]
    assert kw["check"] is True and kw["timeout"] == pm.EXTRACT_TIMEOUT_S


# -- pure-Python extract ------------------------------------------------------------------------
class CountingFile(pm.FileRanges):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.reads = 0

    def read(self, offset: int, length: int) -> bytes:
        self.reads += 1
        return super().read(offset, length)


def test_python_extract_copies_the_bbox_tiles_byte_for_byte(tmp_path: Path) -> None:
    src = TileIndex(FIXTURE)
    out = tmp_path / "sub.pmtiles"
    bbox = (15.80, 43.65, 15.85, 43.70)  # Plić Sestre
    try:
        source = CountingFile(FIXTURE)
        n = pm.pmtiles_python_extract(source, out, bbox, 10, workers=1, log=lambda _m: None)
        sub = TileIndex(out)
        try:
            assert sub.maxzoom == 10 and sub.minzoom == 8
            assert sub.bounds == pytest.approx(list(bbox))
            assert n == sub.count > 0
            for z in range(8, 11):
                x0, y0, x1, y1 = pm.tile_range(z, bbox)
                for x in range(x0, x1 + 1):
                    for y in range(y0, y1 + 1):
                        assert sub.get(z, x, y) == src.get(z, x, y)
            assert sub.get(11, *pm.tile_range(11, bbox)[:2]) is None  # above maxzoom
        finally:
            sub.close()
        assert source.reads <= 4  # header+root, tiles (merged), metadata
    finally:
        src.close()


def test_python_extract_rejects_a_bbox_without_tiles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no tile"):
        pm.pmtiles_python_extract(
            pm.FileRanges(FIXTURE), tmp_path / "x.pmtiles", (1.0, 1.0, 1.1, 1.1), 11, log=print
        )


def test_fetch_ranges_merges_close_ranges() -> None:
    class Mem:
        def __init__(self) -> None:
            self.blob = bytes(range(256)) * 64
            self.calls: list[tuple[int, int]] = []

        def read(self, offset: int, length: int) -> bytes:
            self.calls.append((offset, length))
            return self.blob[offset : offset + length]

    m = Mem()
    ranges = [(100, 10), (0, 5), (120, 4), (9000, 3), (100, 10)]
    got = pm.fetch_ranges(m, ranges, gap=100, workers=2)
    assert got == [m.blob[o : o + n] for o, n in ranges]
    assert sorted(m.calls) == [(0, 124), (9000, 3)]


def test_extract_basemap_validates_before_renaming(tmp_path: Path) -> None:
    def bad(url, out, bbox, maxzoom):
        out.write_bytes(b"not a pmtiles archive at all, padding" * 10)

    with pytest.raises(ValueError):
        pm.extract_basemap("u", tmp_path, pm.DEFAULT_BBOX, 14, bad)
    assert not (tmp_path / "race.pmtiles").exists()
    assert not (tmp_path / "race.pmtiles.tmp").exists()


def test_build_pack_writes_tiles_and_manifest(tmp_path: Path) -> None:
    def extract(url, out, bbox, maxzoom):
        assert url == "https://build.protomaps.com/20261104.pmtiles"
        assert (bbox, maxzoom) == (FIXTURE_BBOX, 11)
        shutil.copy(FIXTURE, out)

    out = tmp_path / "racepack"
    code = pm.build_pack(
        out,
        today=dt.date(2026, 11, 6),
        extract=extract,
        bbox=FIXTURE_BBOX,
        maxzoom=11,
        probe=lambda u: u.endswith("20261104.pmtiles"),
        log=lambda _m: None,
    )
    assert code == pm.EXIT_OK
    m = json.loads((out / "racepack.json").read_text())
    assert m["protomaps_build"] == "20261104" and m["maxzoom"] == 11
    assert m["files"]["race.pmtiles"]["bytes"] == FIXTURE.stat().st_size
    assert m["attribution"] == "© OpenStreetMap contributors (ODbL), Protomaps"
    assert m["fallback"] is None
    assert pm.check_pack(out) == []


# -- manifest + check ---------------------------------------------------------------------------
def test_check_pack_accepts_a_valid_pack(tmp_path: Path) -> None:
    d = _pack(tmp_path)
    m = json.loads((d / "racepack.json").read_text())
    assert m["files"]["race.pmtiles"]["sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert pm.check_pack(d) == []


def test_check_pack_detects_a_flipped_byte(tmp_path: Path) -> None:
    d = _pack(tmp_path)
    p = d / "race.pmtiles"
    data = bytearray(p.read_bytes())
    data[-10] ^= 0xFF  # inside the last tile: the header still parses
    p.write_bytes(bytes(data))
    problems = pm.check_pack(d)
    assert any("sha256 mismatch" in msg for msg in problems), problems


def test_check_pack_rejects_uncompressed_tiles(tmp_path: Path) -> None:
    d = _pack(tmp_path)
    p = d / "race.pmtiles"
    data = bytearray(p.read_bytes())
    data[98] = 1  # tile_compression NONE
    p.write_bytes(bytes(data))
    problems = pm.check_pack(d)
    assert any("compression" in msg for msg in problems), problems


def test_check_pack_rejects_bounds_short_of_the_bbox(tmp_path: Path) -> None:
    d = _pack(tmp_path)
    m = json.loads((d / "racepack.json").read_text())
    m["bbox"] = [15.0, 42.8, 16.3, 44.0]
    (d / "racepack.json").write_text(json.dumps(m))
    assert any("do not cover" in msg for msg in pm.check_pack(d))


def test_check_pack_wrong_maxzoom_and_missing_manifest(tmp_path: Path) -> None:
    d = _pack(tmp_path)
    m = json.loads((d / "racepack.json").read_text())
    m["maxzoom"] = 14
    (d / "racepack.json").write_text(json.dumps(m))
    assert any("maxzoom 11" in msg for msg in pm.check_pack(d))
    (d / "racepack.json").unlink()
    assert any("racepack.json" in msg for msg in pm.check_pack(d))


# -- CLI ----------------------------------------------------------------------------------------
def test_cli_check_missing_dir_exits_3(tmp_path: Path, capsys) -> None:
    assert pm.main(["--check", str(tmp_path / "nope")]) == pm.EXIT_CHECK
    assert "not a directory" in capsys.readouterr().err


def test_cli_check_valid_pack_exits_0(tmp_path: Path, capsys) -> None:
    d = _pack(tmp_path)
    assert pm.main(["--check", str(d)]) == pm.EXIT_OK
    out = capsys.readouterr().out
    assert "check ok" in out and "rsync -a --delete" in out


def test_cli_usage_errors_exit_2(capsys) -> None:
    assert pm.main(["--bogus"]) == pm.EXIT_USAGE
    assert pm.main(["--bbox", "16,42,15,44"]) == pm.EXIT_USAGE
    assert pm.main(["--date", "2026-11-06"]) == pm.EXIT_USAGE
    assert pm.main(["--help"]) == pm.EXIT_OK
