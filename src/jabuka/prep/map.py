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
from collections.abc import Callable, Mapping, Sequence
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
from jabuka.core.web import strip_control

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

GEOFABRIK_URL = "https://download.geofabrik.de/europe/croatia-latest.osm.pbf"
GEOFABRIK_FILE = "croatia-latest.osm.pbf"
PBF_MAX_BYTES = 600 * 1024 * 1024
PBF_MAX_AGE_S = 2 * 86400.0

# night-relevant seamark types (RESEARCH "Offline map prep" item 2); everything else is dropped
SEAMARK_TYPES = frozenset({"rock", "wreck", "obstruction", "landmark", "marine_farm"})
SEAMARK_PREFIXES = ("light_", "beacon_", "buoy_")
NAME_MAX = 60
LIGHT_TEXT_MAX = 24
COLOUR_ABBR = {"white": "W", "red": "R", "green": "G", "yellow": "Y", "blue": "Bu", "orange": "Or"}
COORD_DECIMALS = 5  # ~1 m
COAST_MARGIN_DEG = 0.3  # coastline kept up to this far outside the bbox (map edge, islands)
COAST_MAX_BYTES = 4 * 1024 * 1024
COAST_TOL_M = 5.0
GEOJSON_MAX_BYTES = 64 * 1024 * 1024  # --check refuses to parse anything bigger
FALLBACK_ZOOMS = (12, 10)

Extractor = Callable[[str, Path, Bbox, int], None]
Logger = Callable[[str], None]
# overlays(bbox) -> (seamarks FeatureCollection, coastline FeatureCollection, manifest sources)
Overlays = Callable[[Bbox], tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]


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


# -- seamarks + coastline from OpenStreetMap ----------------------------------------------------
def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = strip_control(str(value)).strip()[:limit]
    return text or None


def seamark_kept(kind: str) -> bool:
    return kind in SEAMARK_TYPES or kind.startswith(SEAMARK_PREFIXES)


def _light_tag(tags: Mapping[str, str], key: str) -> str | None:
    # single light: seamark:light:KEY; sectored lights: seamark:light:1:KEY
    return _clean_text(
        tags.get(f"seamark:light:{key}") or tags.get(f"seamark:light:1:{key}"), LIGHT_TEXT_MAX
    )


def _light_summary(
    char: str | None, group: str | None, colour: str | None, period: str | None, rng: str | None
) -> str | None:
    """'Fl', '2', 'white', '10', '4' -> 'Fl(2)W 10s 4M' (chart abbreviation, for labels)."""
    if not char:
        return None
    parts = (colour or "").replace(",", ";").split(";")
    col = "".join(COLOUR_ABBR.get(c.strip(), "") for c in parts)
    # 'Fl(2)W' with a group, 'Fl W' without (as on the chart)
    text = char + (f"({group}){col}" if group else (f" {col}" if col else ""))
    if period:
        text += f" {period}s"
    if rng:
        text += f" {rng}M"
    return text[:LIGHT_TEXT_MAX]


def seamark_feature(
    osm_id: str, tags: Mapping[str, str], lon: float, lat: float, bbox: Bbox
) -> dict[str, Any] | None:
    """GeoJSON Point feature for a night-relevant seamark inside bbox, else None.
    properties: id, type, name (control chars stripped, <= 60 chars), light_character,
    light_colour, light_period, light_range, light (chart-style summary or None)."""
    kind = str(tags.get("seamark:type", ""))
    if not seamark_kept(kind):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return None
    w, s, e, n = bbox
    if not (w <= lon <= e and s <= lat <= n):
        return None
    char = _light_tag(tags, "character")
    colour = _light_tag(tags, "colour")
    period = _light_tag(tags, "period")
    rng = _light_tag(tags, "range")
    group = _light_tag(tags, "group")
    props = {
        "id": osm_id,
        "type": kind,
        "seamark:type": kind,  # same value, as in tests/fixtures/map/seamarks-mini.geojson
        "name": _clean_text(tags.get("seamark:name") or tags.get("name"), NAME_MAX),
        "light_character": char,
        "light_colour": colour,
        "light_period": period,
        "light_range": rng,
        "light": _light_summary(char, group, colour, period, rng),
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": props,
    }


Point = tuple[float, float]
Way = tuple[list[int], list[Point]]  # node refs, positions (same length)


def _chain_ways(ways: Sequence[Way]) -> list[tuple[bool, list[Point]]]:
    """Join coastline ways that share end nodes (OSM splits long coastlines into ways of at most
    2000 nodes). Returns (closed, positions) per chain."""
    out: list[tuple[bool, list[Point]]] = []
    opened: list[Way] = []
    for refs, pts in ways:
        if len(refs) != len(pts) or len(refs) < 2:
            continue
        if refs[0] == refs[-1]:
            out.append((len(refs) >= 4, list(pts)))
        else:
            opened.append((list(refs), list(pts)))
    by_first: dict[int, list[int]] = {}
    by_last: dict[int, list[int]] = {}
    for i, (refs, _) in enumerate(opened):
        by_first.setdefault(refs[0], []).append(i)
        by_last.setdefault(refs[-1], []).append(i)
    used = [False] * len(opened)

    def take(index: dict[int, list[int]], ref: int) -> int | None:
        for j in index.get(ref, []):
            if not used[j]:
                used[j] = True
                return j
        return None

    for i, (refs0, pts0) in enumerate(opened):
        if used[i]:
            continue
        used[i] = True
        refs, pts = list(refs0), list(pts0)
        while refs[0] != refs[-1]:
            j = take(by_first, refs[-1])
            if j is None:
                break
            refs += opened[j][0][1:]
            pts += opened[j][1][1:]
        while refs[0] != refs[-1]:
            j = take(by_last, refs[0])
            if j is None:
                break
            refs = opened[j][0][:-1] + refs
            pts = opened[j][1][:-1] + pts
        out.append((refs[0] == refs[-1] and len(refs) >= 4, pts))
    return out


def _round_dedup(pts: Sequence[Sequence[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for lon, lat in pts:
        if not (math.isfinite(lon) and math.isfinite(lat)):
            continue
        p = [round(lon, COORD_DECIMALS), round(lat, COORD_DECIMALS)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def _inside(p: Sequence[float], box: Bbox) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def _touches(pts: Sequence[Sequence[float]], box: Bbox) -> bool:
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return (
        min(lons) <= box[2] and max(lons) >= box[0] and min(lats) <= box[3] and max(lats) >= box[1]
    )


def _line(coords: list[Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {},
    }


def _polygon(ring: list[Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {},
    }


def coastline_features(ways: Sequence[Way], bbox: Bbox) -> list[dict[str, Any]]:
    """natural=coastline ways -> GeoJSON features for the land/water fallback map: chained ways that
    close become Polygons, the others LineStrings; positions rounded to 5 decimals with consecutive
    duplicates dropped; chains that do not reach bbox are dropped, the rest is cut to bbox plus
    COAST_MARGIN_DEG (a polygon that sticks out degrades to its inside LineStrings)."""
    w, s, e, n = bbox
    m = COAST_MARGIN_DEG
    outer = (w - m, s - m, e + m, n + m)
    feats: list[dict[str, Any]] = []
    for closed, pts in _chain_ways(ways):
        coords = _round_dedup(pts)
        if len(coords) < 2 or not _touches(coords, bbox):
            continue
        if all(_inside(p, outer) for p in coords):
            if closed and len(coords) >= 4 and coords[0] == coords[-1]:
                feats.append(_polygon(coords))
            else:
                feats.append(_line(coords))
            continue
        run: list[list[float]] = []
        for p in [*coords, None]:
            if p is not None and _inside(p, outer):
                run.append(p)
                continue
            if len(run) >= 2 and _touches(run, bbox):
                feats.append(_line(run))
            run = []
    return feats


def rdp_simplify(pts: Sequence[Any], tol_m: float) -> list[Any]:
    """Ramer-Douglas-Peucker on lon/lat with a local metric projection (iterative). Endpoints are
    always kept, so a closed ring stays closed."""
    k = len(pts)
    if k < 3:
        return list(pts)
    lat0 = math.radians(sum(p[1] for p in pts) / k)
    kx, ky = 111_320.0 * math.cos(lat0), 110_574.0
    xy = [(p[0] * kx, p[1] * ky) for p in pts]
    keep = [False] * k
    keep[0] = keep[-1] = True
    stack = [(0, k - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if seg2 == 0.0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best:
                best, idx = d2, i
        if best > tol_m * tol_m:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, kept in zip(pts, keep, strict=True) if kept]


def _json_size(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def coastline_collection(
    features: list[dict[str, Any]], max_bytes: int = COAST_MAX_BYTES, tol_m: float = COAST_TOL_M
) -> dict[str, Any]:
    """FeatureCollection; above max_bytes every geometry is simplified at tol_m (RDP)."""
    fc = {"type": "FeatureCollection", "features": features}
    if _json_size(fc) <= max_bytes:
        return fc
    simplified = []
    for f in features:
        g = f["geometry"]
        if g["type"] == "Polygon":
            ring = rdp_simplify(g["coordinates"][0], tol_m)
            simplified.append(_polygon(ring if len(ring) >= 4 else g["coordinates"][0]))
        else:
            simplified.append(_line(rdp_simplify(g["coordinates"], tol_m)))
    return {"type": "FeatureCollection", "features": simplified}


def extract_overlays(
    pbf: Path, bbox: Bbox, log: Logger = _log
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One osmium pass over an OSM file (.pbf or .osm): seamark nodes/ways (a way at the mean of
    its distinct node positions) and natural=coastline ways. Returns (seamarks FC, coastline FC)."""
    import osmium  # laptop-only prep extra
    from osmium.filter import KeyFilter

    t0 = time.monotonic()
    seamarks: list[dict[str, Any]] = []
    ways: list[Way] = []
    fp = (
        osmium.FileProcessor(str(pbf))
        .with_locations()
        .with_filter(KeyFilter("seamark:type", "natural"))
    )
    for o in fp:
        tags = {t.k: t.v for t in o.tags}
        if o.is_node():
            if "seamark:type" in tags and o.location.valid():
                f = seamark_feature(f"node/{o.id}", tags, o.location.lon, o.location.lat, bbox)
                if f is not None:
                    seamarks.append(f)
        elif o.is_way():
            refs: list[int] = []
            pts: list[Point] = []
            for nd in o.nodes:
                if nd.location.valid():
                    refs.append(nd.ref)
                    pts.append((nd.location.lon, nd.location.lat))
            if tags.get("natural") == "coastline" and len(pts) >= 2:
                ways.append((refs, pts))
            if "seamark:type" in tags and pts:
                distinct = list(dict(zip(refs, pts, strict=True)).values())
                lon = sum(p[0] for p in distinct) / len(distinct)
                lat = sum(p[1] for p in distinct) / len(distinct)
                f = seamark_feature(f"way/{o.id}", tags, lon, lat, bbox)
                if f is not None:
                    seamarks.append(f)
    seamarks.sort(key=lambda f: f["properties"]["id"])
    coast = coastline_collection(coastline_features(ways, bbox))
    log(
        f"prep-map: {len(seamarks)} seamarks, {len(coast['features'])} coastline features "
        f"from {len(ways)} coastline ways in {time.monotonic() - t0:.1f} s"
    )
    return {"type": "FeatureCollection", "features": seamarks}, coast


def ensure_pbf(
    cache_dir: Path,
    download: Callable[[str, Path, int], Any] = download_file,
    log: Logger = _log,
) -> Path:
    """The Geofabrik Croatia extract in cache_dir, re-downloaded when older than 2 days."""
    path = cache_dir / GEOFABRIK_FILE
    if path.is_file() and time.time() - path.stat().st_mtime < PBF_MAX_AGE_S:
        log(f"prep-map: reusing {path}")
        return path
    log(f"prep-map: downloading {GEOFABRIK_URL} (about 200 MB)")
    download(GEOFABRIK_URL, path, PBF_MAX_BYTES)
    return path


def _write_geojson(path: Path, fc: dict[str, Any]) -> None:
    atomic_write_json(path, fc)
    path.with_name(path.name + ".bak").unlink(missing_ok=True)


def _geojson_count(path: Path) -> int | None:
    try:
        return len(json.loads(path.read_text("utf-8"))["features"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


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
    elif manifest.get("fallback") != "coastline-only":
        problems.append(f"{TILES_FILE}: missing (and the manifest is not coastline-only)")
    coast_count = None
    if bbox is not None:
        for name, kinds, box in (
            (SEAMARKS_FILE, ("Point",), bbox),
            (COASTLINE_FILE, ("LineString", "Polygon"), _expand(bbox, COAST_MARGIN_DEG)),
        ):
            p = d / name
            if p.is_file():
                found, count = _check_geojson(p, kinds, box)
                problems += found
                if name == COASTLINE_FILE:
                    coast_count = count
    if not tiles.is_file() and not coast_count:
        problems.append(f"{COASTLINE_FILE}: no coastline feature and no {TILES_FILE}: empty map")
    return problems


def _expand(bbox: Bbox, margin: float) -> Bbox:
    return (bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin)


def _positions(geom: dict[str, Any]) -> list[Any] | None:
    """Every position of a Point/LineString/Polygon, None when the shape is malformed."""
    c = geom.get("coordinates")
    kind = geom.get("type")
    if kind == "Point":
        return [c]
    if kind == "LineString":
        return c if isinstance(c, list) and len(c) >= 2 else None
    if kind == "Polygon":
        if not isinstance(c, list) or not c:
            return None
        out = []
        for ring in c:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                return None
            out += ring
        return out
    return None


def _check_geojson(path: Path, kinds: tuple[str, ...], box: Bbox) -> tuple[list[str], int]:
    """(problems, feature count) for a FeatureCollection whose geometries must be one of kinds with
    finite positions inside box. At most 5 feature problems are reported."""
    name = path.name
    if path.stat().st_size > GEOJSON_MAX_BYTES:
        return [f"{name}: larger than {GEOJSON_MAX_BYTES // (1 << 20)} MB"], 0
    try:
        fc = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as e:
        return [f"{name}: unreadable ({e})"], 0
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        return [f"{name}: not a GeoJSON FeatureCollection"], 0
    feats = fc.get("features")
    if not isinstance(feats, list):
        return [f"{name}: FeatureCollection without a features list"], 0
    problems: list[str] = []
    for i, f in enumerate(feats):
        if len(problems) >= 5:
            problems.append(f"{name}: more problems not shown")
            break
        geom = f.get("geometry") if isinstance(f, dict) else None
        if not isinstance(geom, dict) or geom.get("type") not in kinds:
            got = geom.get("type") if isinstance(geom, dict) else None
            problems.append(f"{name}: feature {i} is {got!r}, expected {'/'.join(kinds)}")
            continue
        pts = _positions(geom)
        ok = pts is not None and all(
            isinstance(p, list)
            and len(p) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) for v in p)
            and all(math.isfinite(v) for v in p)
            for p in pts
        )
        if not ok:
            problems.append(f"{name}: feature {i} has malformed coordinates")
        elif not all(_inside(p, box) for p in pts or []):
            problems.append(f"{name}: feature {i} lies outside the bbox {fmt_bbox(box)}")
    return problems, len(feats)


# -- build --------------------------------------------------------------------------------------
def build_pack(
    out: Path,
    *,
    today: dt.date,
    extract: Extractor,
    bbox: Bbox = DEFAULT_BBOX,
    maxzoom: int = DEFAULT_MAXZOOM,
    probe: Callable[[str], bool] = probe_url,
    overlays: Overlays | None = None,
    log: Logger = _log,
) -> int:
    """Build the race pack in `out`. Returns the CLI exit code.

    Basemap fallback chain (CONTEXT: never leave the tablet without a map): extract at maxzoom,
    then 12, then 10 (manifest fallback "maxzoom-12"/"maxzoom-10"); when every extract fails or no
    build is reachable the pack is "coastline-only" (02-01's map.js draws land from
    coastline.geojson). overlays(bbox) -> (seamarks FC, coastline FC, sources) is the OSM step,
    None to skip it (--skip-seamarks keeps any overlay files already in `out`).
    Exit 0 when the pack is usable and complete, 1 when the OSM step failed or the pack would
    show no map at all."""
    out.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    sources: dict[str, Any] = {}

    def warn(msg: str) -> None:
        warnings.append(msg)
        log(f"prep-map: WARNING {msg}")

    url = find_build(today, probe, log)
    used_zoom: int | None = None
    if url is None:
        warn("no Protomaps daily build reachable in the last 7 days")
    else:
        sources["basemap"] = url
        for z in [maxzoom, *(z for z in FALLBACK_ZOOMS if z < maxzoom)]:
            try:
                count = extract_basemap(url, out, bbox, z, extract)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                warn(f"basemap extract at maxzoom {z} failed: {e}")
                continue
            used_zoom = z
            log(f"prep-map: {TILES_FILE}: {count} tiles, maxzoom {z}")
            break
    if used_zoom is None:
        fallback: str | None = "coastline-only"
        stale = out / TILES_FILE
        if stale.exists():
            os.replace(stale, out / (TILES_FILE + ".old"))
            warn(f"previous {TILES_FILE} moved to {TILES_FILE}.old (not served)")
        banner = "!" * 72
        log(
            f"{banner}\nprep-map: COASTLINE-ONLY PACK: no basemap tiles; the tablets will show "
            "land and water from coastline.geojson only. Rebuild with internet before departure.\n"
            f"{banner}"
        )
    else:
        fallback = None if used_zoom == maxzoom else f"maxzoom-{used_zoom}"
        if fallback:
            log(f"prep-map: WARNING basemap built at maxzoom {used_zoom} instead of {maxzoom}")

    overlays_failed = False
    if overlays is not None:
        try:
            seamarks, coast, osm_sources = overlays(bbox)
            _write_geojson(out / SEAMARKS_FILE, seamarks)
            _write_geojson(out / COASTLINE_FILE, coast)
            sources.update(osm_sources)
        except (OSError, ValueError, RuntimeError, ImportError) as e:
            overlays_failed = True
            warn(f"seamarks/coastline step failed: {e}")
    counts = {
        "seamarks": _geojson_count(out / SEAMARKS_FILE),
        "coastline_features": _geojson_count(out / COASTLINE_FILE),
    }
    write_manifest(
        out,
        {
            "bbox": bbox,
            "maxzoom": used_zoom,
            "protomaps_build": build_day(url) if url and used_zoom is not None else None,
            "sources": sources,
            "counts": counts,
            "fallback": fallback,
            "warnings": warnings,
        },
    )
    if used_zoom is None and not counts["coastline_features"]:
        log("prep-map: ERROR no basemap and no coastline: the pack would show an empty map")
        return EXIT_BUILD
    return EXIT_BUILD if overlays_failed else EXIT_OK


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
    lines += [f"  WARNING: {w}" for w in m.get("warnings", [])]
    lines += [
        "copy to the Pi (docs/RACE-PACK.md):",
        f"  rsync -a --delete {directory}/ <user>@10.42.0.1:/tmp/racepack/",
        "  ssh <user>@10.42.0.1 'sudo rsync -a --delete /tmp/racepack/ /var/lib/jabuka/racepack/ "
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
    overlays: Overlays | None = None
    if not a.skip_seamarks:

        def osm_overlays(box: Bbox) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            pbf = a.pbf or ensure_pbf(a.cache)
            seamarks, coast = extract_overlays(pbf, box)
            stamp = dt.datetime.fromtimestamp(pbf.stat().st_mtime, dt.UTC)
            return (
                seamarks,
                coast,
                {
                    "osm": str(a.pbf) if a.pbf else GEOFABRIK_URL,
                    "osm_file_utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )

        overlays = osm_overlays
    t0 = time.monotonic()
    code = build_pack(
        a.out, today=today, extract=extract, bbox=bbox, maxzoom=a.maxzoom, overlays=overlays
    )
    print(summary(a.out))
    print(f"prep-map: {'built' if code == EXIT_OK else 'FAILED'} in {time.monotonic() - t0:.1f} s")
    return code


if __name__ == "__main__":
    sys.exit(main())
