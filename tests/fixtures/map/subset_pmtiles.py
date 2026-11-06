"""Rebuild sibenik.pmtiles: the tiles of a source PMTiles archive that intersect a bbox, up to a
maxzoom, rewritten with the pinned pmtiles Python writer (same bytes per tile, no re-encoding).

    python tests/fixtures/map/subset_pmtiles.py SRC.pmtiles OUT.pmtiles \\
        --bbox 15.70,43.62,15.95,43.80 --minzoom 8 --maxzoom 11

SRC is a Protomaps extract (go-pmtiles extract of https://build.protomaps.com/YYYYMMDD.pmtiles);
see SOURCES.md for the exact provenance of the committed file.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from pmtiles.reader import MmapSource, Reader
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write


def tile_range(z: int, bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    w, s, e, n = bbox
    n_tiles = 1 << z

    def tx(lon: float) -> int:
        return min(n_tiles - 1, max(0, int((lon + 180.0) / 360.0 * n_tiles)))

    def ty(lat: float) -> int:
        r = math.radians(lat)
        y = (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n_tiles
        return min(n_tiles - 1, max(0, int(y)))

    return tx(w), ty(n), tx(e), ty(s)


def subset(
    src: Path, out: Path, bbox: tuple[float, float, float, float], minzoom: int, maxzoom: int
) -> int:
    with open(src, "rb") as f:
        reader = Reader(MmapSource(f))
        h = reader.header()
        meta = reader.metadata()
        if h["tile_type"] != TileType.MVT or h["tile_compression"] != Compression.GZIP:
            raise SystemExit("source must be a gzip MVT archive")
        tiles: list[tuple[int, bytes]] = []
        for z in range(max(minzoom, h["min_zoom"]), min(maxzoom, h["max_zoom"]) + 1):
            x0, y0, x1, y1 = tile_range(z, bbox)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    data = reader.get(z, x, y)
                    if data is not None:
                        tiles.append((zxy_to_tileid(z, x, y), bytes(data)))
    tiles.sort()
    w, s, e, n = bbox
    header = {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.GZIP,
        "min_lon_e7": int(w * 1e7),
        "min_lat_e7": int(s * 1e7),
        "max_lon_e7": int(e * 1e7),
        "max_lat_e7": int(n * 1e7),
        "center_zoom": min(maxzoom, 10),
        "center_lon_e7": int((w + e) / 2 * 1e7),
        "center_lat_e7": int((s + n) / 2 * 1e7),
    }
    with write(out) as writer:
        for tile_id, data in tiles:
            writer.write_tile(tile_id, data)
        writer.finalize(header, meta)
    return len(tiles)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("src", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--bbox", default="15.70,43.62,15.95,43.80", help="W,S,E,N")
    p.add_argument("--minzoom", type=int, default=8)
    p.add_argument("--maxzoom", type=int, default=11)
    a = p.parse_args()
    bbox = tuple(float(v) for v in a.bbox.split(","))
    n = subset(a.src, a.out, bbox, a.minzoom, a.maxzoom)  # type: ignore[arg-type]
    print(f"{a.out}: {n} tiles, {a.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
