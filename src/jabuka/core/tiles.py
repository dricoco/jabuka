"""Offline race pack: vector tiles from <racepack>/race.pmtiles plus the seamark/coastline overlays
(HELM-01, RESEARCH Pattern 13, Pitfall 15, Security Domain V12).

TileIndex mmaps the archive once, validates the header (MVT + gzip) and walks the root and leaf
directories into a dict tile_id -> (offset, length), so a tile lookup is a dict hit and a slice
(microseconds) instead of pmtiles.Reader.get re-parsing the root directory on every request
(~30 ms on a Pi 3B, holding the GIL). The browser gets plain XYZ tiles: no HTTP Range requests.

Routes (racepack_router):
  GET /tiles/{z}/{x}/{y}.mvt        200 gzip MVT | 204 (missing, out of range, no pack)
  GET /racepack/info                {tiles, seamarks, coastline, bounds, minzoom, maxzoom, count,
                                     error}
  GET /racepack/seamarks.geojson    fixed file name (404 when absent)
  GET /racepack/coastline.geojson   fixed file name (404 when absent)
No path is ever built from request input; the race-pack directory comes from the CLI only.
"""

from __future__ import annotations

import logging
import mmap
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, JSONResponse
from pmtiles.tile import (
    Compression,
    TileType,
    deserialize_directory,
    deserialize_header,
    zxy_to_tileid,
)

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

log = logging.getLogger("jabuka.tiles")

TILES_FILE = "race.pmtiles"
SEAMARKS_FILE = "seamarks.geojson"
COASTLINE_FILE = "coastline.geojson"
HEADER_LEN = 127
MAX_DEPTH = 4  # root + leaves (the spec allows nesting; real archives use at most 2 levels)
MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
GEOJSON_MEDIA_TYPE = "application/geo+json"


class TileIndex:
    """In-memory index of a PMTiles v3 archive (read-only mmap). Raises ValueError with the reason
    when the file is not a gzip-compressed MVT archive."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._f = open(self.path, "rb")  # noqa: SIM115 - kept open for the mmap's lifetime
        self._mm: mmap.mmap | None = None
        try:
            size = self.path.stat().st_size
            if size < HEADER_LEN:
                raise ValueError("file too short for a PMTiles header")
            self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                h = deserialize_header(self._mm[0:HEADER_LEN])
            except ValueError:
                raise
            except Exception as e:  # MagicNumberNotFound, SpecVersionUnsupported
                raise ValueError(f"not a PMTiles v3 archive ({type(e).__name__})") from None
            if h["tile_type"] != TileType.MVT:
                raise ValueError(f"tile type {h['tile_type'].name}, expected MVT")
            if h["tile_compression"] != Compression.GZIP:
                raise ValueError(f"tile compression {h['tile_compression'].name}, expected GZIP")
            if h["internal_compression"] != Compression.GZIP:
                raise ValueError("directory compression is not gzip")
            self.header = h
            self.idx: dict[int, tuple[int, int]] = {}
            self._walk(size)
        except Exception:
            self.close()
            raise

    def _walk(self, size: int) -> None:
        h = self.header
        assert self._mm is not None
        stack = [(h["root_offset"], h["root_length"], 0)]
        while stack:
            off, length, depth = stack.pop()
            if depth >= MAX_DEPTH:
                raise ValueError("directory nesting too deep")
            if off < 0 or length <= 0 or off + length > size:
                raise ValueError("directory outside the file")
            try:
                entries = deserialize_directory(self._mm[off : off + length])
            except Exception as e:
                raise ValueError(f"corrupt directory ({type(e).__name__})") from None
            for e in entries:
                if e.run_length == 0:
                    stack.append((h["leaf_directory_offset"] + e.offset, e.length, depth + 1))
                    continue
                start = h["tile_data_offset"] + e.offset
                if start + e.length > size:
                    raise ValueError("tile data outside the file")
                for i in range(e.run_length):
                    self.idx[e.tile_id + i] = (start, e.length)

    # -- queries -----------------------------------------------------------------------------
    @property
    def count(self) -> int:
        return len(self.idx)

    @property
    def minzoom(self) -> int:
        return int(self.header["min_zoom"])

    @property
    def maxzoom(self) -> int:
        return int(self.header["max_zoom"])

    @property
    def bounds(self) -> list[float]:
        h = self.header
        return [
            h["min_lon_e7"] / 1e7,
            h["min_lat_e7"] / 1e7,
            h["max_lon_e7"] / 1e7,
            h["max_lat_e7"] / 1e7,
        ]

    def get(self, z: int, x: int, y: int) -> bytes | None:
        """The stored (gzip) tile bytes, or None."""
        mm = self._mm
        if mm is None or not (0 <= z <= 31 and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
            return None
        hit = self.idx.get(zxy_to_tileid(z, x, y))
        if hit is None:
            return None
        return mm[hit[0] : hit[0] + hit[1]]

    def close(self) -> None:
        if self._mm is not None:
            try:
                self._mm.close()
            except BufferError:  # a slice still exported; the mapping goes with the process
                pass
            self._mm = None
        try:
            self._f.close()
        except OSError:
            pass


class Racepack:
    """The race-pack directory as served: tile index (or the reason it is missing) + overlays."""

    def __init__(self, directory: Path | None) -> None:
        self.dir = directory
        self.index: TileIndex | None = None
        self.error: str | None = None
        if directory is None:
            self.error = "no race-pack directory"
            return
        path = directory / TILES_FILE
        if not path.exists():
            self.error = f"{TILES_FILE} absent"
            return
        try:
            self.index = TileIndex(path)
        except (OSError, ValueError) as e:
            self.error = f"{TILES_FILE}: {e}"
            log.warning("race pack tiles disabled: %s", self.error)

    def file(self, name: str) -> Path | None:
        if self.dir is None:
            return None
        p = self.dir / name
        return p if p.is_file() else None

    def info(self) -> dict:
        idx = self.index
        return {
            "tiles": idx is not None,
            "seamarks": self.file(SEAMARKS_FILE) is not None,
            "coastline": self.file(COASTLINE_FILE) is not None,
            "bounds": idx.bounds if idx is not None else None,
            "minzoom": idx.minzoom if idx is not None else None,
            "maxzoom": idx.maxzoom if idx is not None else None,
            "count": idx.count if idx is not None else 0,
            "error": self.error,
        }

    def close(self) -> None:
        if self.index is not None:
            self.index.close()
            self.index = None


def racepack_router(ctx: CoreContext) -> APIRouter:
    """Builds the tile index once (at app creation) and serves the race pack."""
    if ctx.racepack is None:
        ctx.racepack = Racepack(ctx.racepack_dir)
    pack = ctx.racepack
    ctx.record_racepack_health()
    r = APIRouter()

    def no_tile() -> Response:
        return Response(status_code=204)

    @r.get("/tiles/{z}/{x}/{y}.mvt")
    def tile(z: int, x: int, y: int) -> Response:  # plain def: a dict lookup + slice
        idx = pack.index
        if idx is None or not (0 <= z <= idx.maxzoom and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
            return no_tile()
        data = idx.get(z, x, y)
        if data is None:
            return no_tile()
        return Response(
            data,
            media_type=MVT_MEDIA_TYPE,
            headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=3600"},
        )

    @r.get("/racepack/info")
    def racepack_info() -> dict:
        return pack.info()

    def overlay(name: str) -> Response:
        p = pack.file(name)
        if p is None:
            return JSONResponse({"error": f"{name} absent"}, status_code=404)
        return FileResponse(p, media_type=GEOJSON_MEDIA_TYPE)

    @r.get("/racepack/seamarks.geojson")
    def seamarks() -> Response:
        return overlay(SEAMARKS_FILE)

    @r.get("/racepack/coastline.geojson")
    def coastline() -> Response:
        return overlay(COASTLINE_FILE)

    return r
