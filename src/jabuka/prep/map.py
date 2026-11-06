"""jabuka-prep-map: build and check the offline race pack on the laptop (HELM-01; CONTEXT "Map
(offline)"; RESEARCH "Offline map prep (laptop) - exact steps").

    jabuka-prep-map [--out DIR] [--bbox W,S,E,N] [--maxzoom N] [--date YYYYMMDD]
                    [--extractor auto|go|python] [--pmtiles-bin PATH] [--pbf PATH]
                    [--skip-seamarks] [--check DIR]
    exit 0 ok, 1 build failed, 2 usage, 3 check failed

Basemap: the newest Protomaps daily build of the last 7 days (builds are kept one week) is probed
with HTTP HEAD and the race box is extracted into race.pmtiles (gzip MVT, maxzoom 14 by default).
Two extractors produce the same archive:
  go      `pmtiles extract URL OUT --bbox=W,S,E,N --maxzoom=N` with go-pmtiles 1.31.2. Without
          --pmtiles-bin or a `pmtiles` on PATH the release tarball is downloaded into
          var/cache/go-pmtiles/ and its sha256 is checked against the value pinned below BEFORE the
          binary is unpacked; a mismatch deletes the tarball and nothing is executed.
  python  the same algorithm in-process with the pinned `pmtiles` package: header + root directory,
          the leaf directories and tile byte ranges the box needs, fetched with merged HTTP Range
          requests, rewritten with pmtiles.writer (tile bytes copied unchanged). No executable is
          downloaded. `auto` (default) uses go when --pmtiles-bin or a `pmtiles` on PATH exists,
          else python.
The extract is renamed into place only after jabuka.core.tiles.TileIndex accepts its header.

racepack.json (manifest) records the bbox, maxzoom, build date, sources, sha256 + size of every
pack file this tool wrote, and the ODbL attribution. --check DIR re-validates a pack before it is
copied to the Pi (see docs/RACE-PACK.md).

Laptop-only dev tool: it reads the wall clock and uses the network; it never runs on the Pi.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from pmtiles.tile import (
    Compression,
    TileType,
    deserialize_directory,
    deserialize_header,
    zxy_to_tileid,
)
from pmtiles.writer import write as pmtiles_write

from jabuka.common.atomicio import atomic_write_json
from jabuka.core.tiles import COASTLINE_FILE, SEAMARKS_FILE, TILES_FILE, TileIndex

EXIT_OK, EXIT_BUILD, EXIT_USAGE, EXIT_CHECK = 0, 1, 2, 3

Bbox = tuple[float, float, float, float]  # W, S, E, N (degrees)

DEFAULT_BBOX: Bbox = (15.0, 42.8, 16.3, 44.0)
DEFAULT_MAXZOOM = 14
DEFAULT_OUT = Path("var/racepack")
DEFAULT_CACHE = Path("var/cache")
MANIFEST_FILE = "racepack.json"
MAP_FILES = (TILES_FILE, SEAMARKS_FILE, COASTLINE_FILE)  # the files this tool writes + hashes
ATTRIBUTION = "© OpenStreetMap contributors (ODbL), Protomaps"
USER_AGENT = "jabuka-prep-map/0.1 (offline race-pack builder)"

PROTOMAPS_URL = "https://build.protomaps.com/{day}.pmtiles"
PROTOMAPS_KEEP_DAYS = 7
PROBE_TIMEOUT_S = 15.0
EXTRACT_TIMEOUT_S = 600.0

GO_PMTILES_VERSION = "1.31.2"
GO_PMTILES_ASSET = f"go-pmtiles_{GO_PMTILES_VERSION}_Linux_x86_64.tar.gz"
GO_PMTILES_URL = (
    "https://github.com/protomaps/go-pmtiles/releases/download/"
    f"v{GO_PMTILES_VERSION}/{GO_PMTILES_ASSET}"
)
# GitHub release asset digest (the release publishes no checksums.txt); re-verified 2026-11-06
GO_PMTILES_SHA256 = "3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f"
GO_PMTILES_MAX_BYTES = 64 * 1024 * 1024

HEADER_LEN = 127
ROOT_FETCH = 16384  # the spec keeps header + root directory inside the first 16 KiB
MAX_DIR_DEPTH = 4
MERGE_GAP = 256 * 1024  # merge byte ranges closer than this into one HTTP request
MAX_CHUNK = 32 * 1024 * 1024
HTTP_WORKERS = 8
HTTP_TIMEOUT_S = 60.0
HTTP_RETRIES = 3

Extractor = Callable[[str, Path, Bbox, int], None]
Logger = Callable[[str], None]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fmt_bbox(bbox: Sequence[float]) -> str:
    return ",".join(f"{v:g}" for v in bbox)


def parse_bbox(text: str) -> Bbox:
    try:
        w, s, e, n = (float(v) for v in text.split(","))
    except ValueError:
        raise ValueError(f"bbox {text!r}: expected W,S,E,N in degrees") from None
    if not all(math.isfinite(v) for v in (w, s, e, n)):
        raise ValueError(f"bbox {text!r}: non-finite value")
    if not (-180.0 <= w < e <= 180.0 and -85.0 <= s < n <= 85.0):
        raise ValueError(f"bbox {text!r}: need W < E within ±180 and S < N within ±85")
    return (w, s, e, n)


# -- Protomaps daily builds ---------------------------------------------------------------------
def protomaps_candidates(today: dt.date, days: int = PROTOMAPS_KEEP_DAYS) -> list[str]:
    """Daily build URLs from `today` back `days` days, newest first (days + 1 URLs)."""
    return [
        PROTOMAPS_URL.format(day=(today - dt.timedelta(days=k)).strftime("%Y%m%d"))
        for k in range(days + 1)
    ]


def build_day(url: str) -> str:
    """'https://build.protomaps.com/20261105.pmtiles' -> '20261105'."""
    return url.rsplit("/", 1)[-1].split(".", 1)[0]


def probe_url(url: str) -> bool:
    """HTTP HEAD answers 200."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as r:
            return getattr(r, "status", 0) == 200
    except (OSError, ValueError):
        return False


def find_build(
    today: dt.date, probe: Callable[[str], bool] = probe_url, log: Logger = _log
) -> str | None:
    for url in protomaps_candidates(today):
        if probe(url):
            log(f"prep-map: Protomaps build {build_day(url)} available")
            return url
        log(f"prep-map: {url} not available")
    return None


# -- downloads + go-pmtiles ---------------------------------------------------------------------
def download_file(url: str, dest: Path, max_bytes: int, timeout: float = HTTP_TIMEOUT_S) -> Path:
    """Stream url to dest (via dest.part), refusing more than max_bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    raise OSError(f"{url}: larger than the {max_bytes // (1 << 20)} MB cap")
                f.write(block)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Raise ValueError (and delete the file) when its sha256 is not `expected`."""
    got = sha256_file(path)
    if got != expected.lower():
        path.unlink(missing_ok=True)
        raise ValueError(f"{path.name}: sha256 {got} does not match the pinned {expected}")


def ensure_go_pmtiles(
    cache_dir: Path,
    download: Callable[[str, Path, int], Any] = download_file,
    log: Logger = _log,
) -> Path:
    """The checksum-verified go-pmtiles binary under cache_dir (downloaded once). The tarball hash
    is checked on every call before the binary is (re)unpacked, so a tampered cache never runs."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    tarball = cache_dir / GO_PMTILES_ASSET
    binary = cache_dir / "pmtiles"
    binary.unlink(missing_ok=True)
    if not tarball.exists():
        log(f"prep-map: downloading {GO_PMTILES_URL}")
        download(GO_PMTILES_URL, tarball, GO_PMTILES_MAX_BYTES)
    verify_sha256(tarball, GO_PMTILES_SHA256)
    with tarfile.open(tarball, "r:gz") as tf:
        member = tf.getmember("pmtiles")
        if not member.isfile() or member.size > GO_PMTILES_MAX_BYTES:
            raise ValueError(f"{GO_PMTILES_ASSET}: unexpected 'pmtiles' member")
        src = tf.extractfile(member)
        if src is None:
            raise ValueError(f"{GO_PMTILES_ASSET}: cannot read 'pmtiles'")
        data = src.read()
    tmp = binary.with_name("pmtiles.tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    os.replace(tmp, binary)
    return binary


def go_extractor(
    binary: str | Path, run: Callable[..., Any] = subprocess.run, log: Logger = _log
) -> Extractor:
    def extract(url: str, out: Path, bbox: Bbox, maxzoom: int) -> None:
        cmd = [
            str(binary),
            "extract",
            url,
            str(out),
            f"--bbox={fmt_bbox(bbox)}",
            f"--maxzoom={maxzoom}",
        ]
        log("prep-map: " + " ".join(cmd))
        run(cmd, check=True, timeout=EXTRACT_TIMEOUT_S)

    return extract


# -- pure-Python extract (pmtiles package + HTTP Range) -----------------------------------------
class RangeSource(Protocol):
    def read(self, offset: int, length: int) -> bytes: ...


class FileRanges:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self, offset: int, length: int) -> bytes:
        with open(self.path, "rb") as f:
            f.seek(offset)
            return f.read(length)


class HttpRanges:
    """Byte ranges of a remote archive. Refuses a server that ignores Range (a 200 would stream
    the whole 100+ GB planet build)."""

    def __init__(
        self, url: str, timeout: float = HTTP_TIMEOUT_S, retries: int = HTTP_RETRIES
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.requests = 0

    def read(self, offset: int, length: int) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries):
            req = urllib.request.Request(
                self.url,
                headers={
                    "Range": f"bytes={offset}-{offset + length - 1}",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                self.requests += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    status = getattr(r, "status", 0)
                    if status != 206:
                        raise OSError(f"HTTP {status} to a Range request (expected 206)")
                    data = r.read(length + 1)
                if len(data) > length:
                    raise OSError("server sent more bytes than requested")
                return data
            except OSError as e:  # URLError, timeouts and the checks above
                last = e
                time.sleep(1.0 + attempt)
        raise OSError(f"{self.url} bytes {offset}+{length}: {last}")


def tile_range(z: int, bbox: Bbox) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) inclusive XYZ tile range covering bbox at zoom z."""
    w, s, e, n = bbox
    n_tiles = 1 << z

    def tx(lon: float) -> int:
        return min(n_tiles - 1, max(0, int((lon + 180.0) / 360.0 * n_tiles)))

    def ty(lat: float) -> int:
        r = math.radians(lat)
        y = (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n_tiles
        return min(n_tiles - 1, max(0, int(y)))

    return tx(w), ty(n), tx(e), ty(s)


def bbox_tile_ids(bbox: Bbox, minzoom: int, maxzoom: int) -> list[int]:
    ids = []
    for z in range(minzoom, maxzoom + 1):
        x0, y0, x1, y1 = tile_range(z, bbox)
        ids.extend(zxy_to_tileid(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
    return sorted(set(ids))


def fetch_ranges(
    source: RangeSource,
    ranges: Sequence[tuple[int, int]],
    gap: int = MERGE_GAP,
    workers: int = HTTP_WORKERS,
) -> list[bytes]:
    """The bytes of every (offset, length), fetched as few merged reads (in parallel)."""
    chunks: list[list[int]] = []
    for off, ln in sorted(set(ranges)):
        end = off + ln
        if (
            chunks
            and off - chunks[-1][1] <= gap
            and max(chunks[-1][1], end) - chunks[-1][0] <= MAX_CHUNK
        ):
            chunks[-1][1] = max(chunks[-1][1], end)
        else:
            chunks.append([off, end])
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        datas = list(ex.map(lambda c: source.read(c[0], c[1] - c[0]), chunks))
    for (start, end), data in zip(chunks, datas, strict=True):
        if len(data) != end - start:
            raise OSError(f"short read at {start}: {len(data)} of {end - start} bytes")
    starts = [c[0] for c in chunks]
    out = []
    for off, ln in ranges:
        i = bisect.bisect_right(starts, off) - 1
        rel = off - chunks[i][0]
        out.append(bytes(datas[i][rel : rel + ln]))
    return out


def pmtiles_python_extract(
    source: RangeSource,
    out: Path,
    bbox: Bbox,
    maxzoom: int,
    workers: int = HTTP_WORKERS,
    log: Logger = _log,
) -> int:
    """Write the tiles of `source` (a PMTiles v3 gzip-MVT archive) intersecting bbox up to maxzoom
    into `out`. Returns the number of tiles."""
    head = source.read(0, ROOT_FETCH)
    if len(head) < HEADER_LEN:
        raise ValueError("source too short for a PMTiles header")
    try:
        h = deserialize_header(head[:HEADER_LEN])
    except Exception as e:
        raise ValueError(f"source is not a PMTiles v3 archive ({type(e).__name__})") from None
    if h["tile_type"] != TileType.MVT or h["tile_compression"] != Compression.GZIP:
        raise ValueError("source must be a gzip MVT archive")
    if h["internal_compression"] != Compression.GZIP:
        raise ValueError("source directories are not gzip")
    top = min(maxzoom, h["max_zoom"])
    if top < h["min_zoom"]:
        raise ValueError(f"maxzoom {maxzoom} below the source minzoom {h['min_zoom']}")
    needed = bbox_tile_ids(bbox, h["min_zoom"], top)
    ro, rl = h["root_offset"], h["root_length"]
    level = [head[ro : ro + rl] if ro + rl <= len(head) else source.read(ro, rl)]
    found: dict[int, tuple[int, int]] = {}
    n_leaves = 0
    for _depth in range(MAX_DIR_DEPTH):
        leaf_ranges: list[tuple[int, int]] = []
        for buf in level:
            entries = deserialize_directory(buf)
            for i, e in enumerate(entries):
                lo = bisect.bisect_left(needed, e.tile_id)
                if e.run_length == 0:  # leaf directory covering [tile_id, next tile_id)
                    nxt = entries[i + 1].tile_id if i + 1 < len(entries) else None
                    if lo < len(needed) and (nxt is None or needed[lo] < nxt):
                        leaf_ranges.append((h["leaf_directory_offset"] + e.offset, e.length))
                else:
                    hi = bisect.bisect_left(needed, e.tile_id + e.run_length)
                    for t in needed[lo:hi]:
                        found[t] = (h["tile_data_offset"] + e.offset, e.length)
        if not leaf_ranges:
            break
        n_leaves += len(leaf_ranges)
        level = fetch_ranges(source, leaf_ranges, workers=workers)
    else:
        raise ValueError("directory nesting too deep")
    if not found:
        raise ValueError(f"no tile of the source intersects the bbox {fmt_bbox(bbox)}")
    ids = sorted(found)
    log(f"prep-map: {len(ids)} tiles in {n_leaves} leaf directories, fetching tile data")
    datas = fetch_ranges(source, [found[t] for t in ids], workers=workers)
    try:
        raw = source.read(h["metadata_offset"], h["metadata_length"])
        metadata = json.loads(gzip.decompress(raw)) if h["metadata_length"] else {}
        if not isinstance(metadata, dict):
            metadata = {}
    except (OSError, ValueError, EOFError):
        metadata = {}
    w, s, e, n = bbox
    header = {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.GZIP,
        "min_lon_e7": round(w * 1e7),
        "min_lat_e7": round(s * 1e7),
        "max_lon_e7": round(e * 1e7),
        "max_lat_e7": round(n * 1e7),
        "center_zoom": min(top, 10),
        "center_lon_e7": round((w + e) / 2 * 1e7),
        "center_lat_e7": round((s + n) / 2 * 1e7),
    }
    with pmtiles_write(out) as writer:
        for tile_id, data in zip(ids, datas, strict=True):
            writer.write_tile(tile_id, data)
        writer.finalize(header, metadata)
    return len(ids)


def python_extractor(workers: int = HTTP_WORKERS, log: Logger = _log) -> Extractor:
    def extract(url: str, out: Path, bbox: Bbox, maxzoom: int) -> None:
        source: RangeSource = (
            HttpRanges(url) if url.startswith(("http://", "https://")) else FileRanges(url)
        )
        log(f"prep-map: extracting {url} bbox {fmt_bbox(bbox)} maxzoom {maxzoom} (python)")
        n = pmtiles_python_extract(source, out, bbox, maxzoom, workers=workers, log=log)
        reqs = getattr(source, "requests", None)
        log(f"prep-map: {n} tiles written" + (f" in {reqs} HTTP requests" if reqs else ""))

    return extract


def make_extractor(
    kind: str, pmtiles_bin: str | None, cache_dir: Path, log: Logger = _log
) -> Extractor:
    if kind == "auto":
        on_path = shutil.which("pmtiles")
        if pmtiles_bin or on_path:
            return go_extractor(pmtiles_bin or on_path, log=log)  # type: ignore[arg-type]
        return python_extractor(log=log)
    if kind == "go":
        binary = pmtiles_bin or ensure_go_pmtiles(cache_dir / "go-pmtiles", log=log)
        return go_extractor(binary, log=log)
    return python_extractor(log=log)


# -- basemap ------------------------------------------------------------------------------------
def extract_basemap(url: str, out_dir: Path, bbox: Bbox, maxzoom: int, extract: Extractor) -> int:
    """Extract into race.pmtiles.tmp, validate with TileIndex, then rename into place.
    Returns the tile count. Raises on any failure (nothing left behind)."""
    tmp = out_dir / (TILES_FILE + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        extract(url, tmp, bbox, maxzoom)
        if not tmp.is_file():
            raise ValueError("the extractor wrote no file")
        idx = TileIndex(tmp)
        try:
            count = idx.count
            if count == 0:
                raise ValueError("the extract holds no tile")
        finally:
            idx.close()
        os.replace(tmp, out_dir / TILES_FILE)
        return count
    finally:
        tmp.unlink(missing_ok=True)


# -- manifest + check ---------------------------------------------------------------------------
def write_manifest(directory: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """racepack.json (atomic) with sha256 + size of every pack file present."""
    files = {}
    for name in MAP_FILES:
        p = directory / name
        if p.is_file():
            files[name] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
    built = meta.get("built_utc") or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "v": 1,
        "built_utc": built,
        "bbox": [float(v) for v in meta["bbox"]],
        "maxzoom": meta.get("maxzoom"),
        "protomaps_build": meta.get("protomaps_build"),
        "sources": meta.get("sources", {}),
        "files": files,
        "counts": meta.get("counts", {}),
        "fallback": meta.get("fallback"),
        "warnings": list(meta.get("warnings", [])),
        "attribution": ATTRIBUTION,
    }
    atomic_write_json(directory / MANIFEST_FILE, manifest)
    (directory / (MANIFEST_FILE + ".bak")).unlink(missing_ok=True)
    return manifest


def _check_tiles(path: Path, manifest: dict[str, Any], bbox: Bbox | None) -> list[str]:
    problems = []
    try:
        idx = TileIndex(path)
    except (OSError, ValueError) as e:
        return [f"{TILES_FILE}: {e}"]
    try:
        if idx.count == 0:
            problems.append(f"{TILES_FILE}: no tile")
        if bbox is not None:
            bw, bs, be, bn = idx.bounds
            w, s, e, n = bbox
            tol = 1e-4
            if bw > w + tol or bs > s + tol or be < e - tol or bn < n - tol:
                problems.append(
                    f"{TILES_FILE}: bounds {fmt_bbox(idx.bounds)} do not cover the bbox "
                    f"{fmt_bbox(bbox)}"
                )
        mz = manifest.get("maxzoom")
        if isinstance(mz, int) and idx.maxzoom != mz:
            problems.append(f"{TILES_FILE}: maxzoom {idx.maxzoom}, manifest says {mz}")
    finally:
        idx.close()
    return problems


def check_pack(directory: str | Path) -> list[str]:
    """Problems found in a race pack (empty list = ok)."""
    d = Path(directory)
    if not d.is_dir():
        return [f"{d}: not a directory"]
    try:
        manifest = json.loads((d / MANIFEST_FILE).read_text("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as e:
        return [f"{MANIFEST_FILE}: unreadable ({e})"]
    problems: list[str] = []
    if manifest.get("v") != 1:
        problems.append(f"{MANIFEST_FILE}: unsupported version {manifest.get('v')!r}")
    bbox: Bbox | None = None
    try:
        bbox = parse_bbox(fmt_bbox(manifest["bbox"]))
    except (KeyError, TypeError, ValueError):
        problems.append(f"{MANIFEST_FILE}: invalid bbox {manifest.get('bbox')!r}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        problems.append(f"{MANIFEST_FILE}: no files table")
        files = {}
    for name, info in files.items():
        p = d / name
        if name not in MAP_FILES:
            problems.append(f"{MANIFEST_FILE}: unexpected file {name!r}")
        elif not p.is_file():
            problems.append(f"{name}: listed in the manifest but missing")
        elif not isinstance(info, dict) or sha256_file(p) != info.get("sha256"):
            problems.append(f"{name}: sha256 mismatch with the manifest")
        elif p.stat().st_size != info.get("bytes"):
            problems.append(f"{name}: size mismatch with the manifest")
    for name in MAP_FILES:
        if (d / name).is_file() and name not in files:
            problems.append(f"{name}: present but not in the manifest")
    tiles = d / TILES_FILE
    if tiles.is_file():
        problems += _check_tiles(tiles, manifest, bbox)
    else:
        problems.append(f"{TILES_FILE}: missing")
    return problems


# -- build --------------------------------------------------------------------------------------
def build_pack(
    out: Path,
    *,
    today: dt.date,
    extract: Extractor,
    bbox: Bbox = DEFAULT_BBOX,
    maxzoom: int = DEFAULT_MAXZOOM,
    probe: Callable[[str], bool] = probe_url,
    log: Logger = _log,
) -> int:
    """Build the race pack in `out`. Returns the CLI exit code."""
    out.mkdir(parents=True, exist_ok=True)
    url = find_build(today, probe, log)
    if url is None:
        log("prep-map: ERROR no Protomaps daily build reachable in the last 7 days")
        return EXIT_BUILD
    try:
        count = extract_basemap(url, out, bbox, maxzoom, extract)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log(f"prep-map: ERROR extract at maxzoom {maxzoom} failed: {e}")
        return EXIT_BUILD
    log(f"prep-map: {TILES_FILE}: {count} tiles, maxzoom {maxzoom}")
    write_manifest(
        out,
        {
            "bbox": bbox,
            "maxzoom": maxzoom,
            "protomaps_build": build_day(url),
            "sources": {"basemap": url},
            "fallback": None,
        },
    )
    return EXIT_OK


def summary(directory: Path) -> str:
    lines = [f"race pack {directory}:"]
    try:
        m = json.loads((directory / MANIFEST_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        m = {}
    for name, info in sorted(m.get("files", {}).items()):
        lines.append(f"  {name:20s} {info.get('bytes', 0) / 1e6:8.2f} MB")
    tiles = directory / TILES_FILE
    if tiles.is_file():
        try:
            idx = TileIndex(tiles)
            lines.append(f"  tiles {idx.count}, zoom {idx.minzoom}-{idx.maxzoom}")
            idx.close()
        except (OSError, ValueError) as e:
            lines.append(f"  tiles unreadable: {e}")
    lines.append(
        f"  Protomaps build {m.get('protomaps_build')}, built {m.get('built_utc')}, "
        f"fallback {m.get('fallback')}"
    )
    for k, v in sorted(m.get("counts", {}).items()):
        lines.append(f"  {k}: {v}")
    lines += [
        "copy to the Pi (docs/RACE-PACK.md):",
        f"  scp -r {directory} jabuka@10.42.0.1:/tmp/racepack",
        "  ssh jabuka@10.42.0.1 'sudo rsync -a --delete /tmp/racepack/ /var/lib/jabuka/racepack/ "
        "&& sudo chown -R jabuka:jabuka /var/lib/jabuka/racepack "
        "&& sudo systemctl restart jabuka-core'",
    ]
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-prep-map",
        description="Build (or --check) the offline race pack: Protomaps basemap extract, "
        "OSM seamarks and coastline, racepack.json manifest.",
    )
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="pack directory (var/racepack)")
    p.add_argument("--bbox", default=fmt_bbox(DEFAULT_BBOX), help="W,S,E,N degrees")
    p.add_argument("--maxzoom", type=int, default=DEFAULT_MAXZOOM)
    p.add_argument("--date", help="newest Protomaps build date to try, YYYYMMDD (default today)")
    p.add_argument("--extractor", choices=("auto", "go", "python"), default="auto")
    p.add_argument("--pmtiles-bin", help="go-pmtiles binary to use (implies the go extractor)")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="download cache (var/cache)")
    p.add_argument("--pbf", type=Path, help="local OSM .pbf instead of the Geofabrik download")
    p.add_argument("--skip-seamarks", action="store_true", help="basemap only (no OSM step)")
    p.add_argument("--check", type=Path, metavar="DIR", help="validate a built pack and exit")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    try:
        a = build_arg_parser().parse_args(argv)
    except SystemExit as e:  # argparse: --help -> 0, usage error -> 2
        return int(e.code or 0)
    if a.check is not None:
        problems = check_pack(a.check)
        if problems:
            for msg in problems:
                print(f"prep-map: CHECK FAILED: {msg}", file=sys.stderr)
            return EXIT_CHECK
        print(summary(a.check))
        print("prep-map: check ok")
        return EXIT_OK
    try:
        bbox = parse_bbox(a.bbox)
        if not 0 <= a.maxzoom <= 15:
            raise ValueError("--maxzoom must be within 0..15")
        today = (
            dt.datetime.strptime(a.date, "%Y%m%d").date()
            if a.date
            else dt.datetime.now(dt.UTC).date()
        )
    except ValueError as e:
        print(f"prep-map: {e}", file=sys.stderr)
        return EXIT_USAGE
    try:
        extract = make_extractor(a.extractor, a.pmtiles_bin, a.cache)
    except (OSError, ValueError, KeyError, tarfile.TarError) as e:
        print(f"prep-map: ERROR go-pmtiles unavailable: {e}", file=sys.stderr)
        return EXIT_BUILD
    t0 = time.monotonic()
    code = build_pack(a.out, today=today, extract=extract, bbox=bbox, maxzoom=a.maxzoom)
    if code == EXIT_OK:
        print(summary(a.out))
        print(f"prep-map: built in {time.monotonic() - t0:.1f} s")
    return code


if __name__ == "__main__":
    sys.exit(main())
