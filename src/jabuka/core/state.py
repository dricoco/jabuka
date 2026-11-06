"""In-memory state store: latest value per (path, src) with server-side age from the injected clock.

Every source of a path is its own row (e.g. navigation.position from Fastnet LatLon AND gpsd).
latest(path) is the source-arbitration seam: freshest non-stale entry wins (Phase 2 WIND-04
replaces the policy).
"""

from __future__ import annotations

from typing import Any

from jabuka.common.clock import Clock

# Longest-prefix match on path. Entries ending in "." are prefixes; others match the path itself
# or anything below it ("navigation.position" also covers "navigation.position.x").
DEFAULT_STALE_S: dict[str, float] = {
    "environment.wind.": 5.0,
    "navigation.speedThroughWater": 5.0,
    "navigation.heading": 5.0,
    "navigation.position": 3.0,
    "navigation.courseOverGroundTrue": 3.0,
    "navigation.speedOverGround": 3.0,
    "navigation.datetime": 3.0,
    "environment.depth.": 10.0,
    "environment.current.": 60.0,
}

ALIVE_S = 3.0


def _matches(path: str, key: str) -> bool:
    if key.endswith("."):
        return path.startswith(key)
    return path == key or path.startswith(key + ".")


class StateStore:
    def __init__(
        self,
        clock: Clock,
        stale_after: dict[str, float] | None = None,
        default_stale_s: float = 10.0,
    ) -> None:
        self.clock = clock
        self.stale_after = dict(DEFAULT_STALE_S if stale_after is None else stale_after)
        self.default_stale_s = default_stale_s
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}
        self._health: dict[str, dict[str, Any]] = {}
        self._health_rx: dict[str, float] = {}
        self._threshold_cache: dict[str, float] = {}

    # -- thresholds --------------------------------------------------------------------------
    def threshold(self, path: str) -> float:
        cached = self._threshold_cache.get(path)
        if cached is not None:
            return cached
        best_len = -1
        best = self.default_stale_s
        for key, secs in self.stale_after.items():
            if _matches(path, key) and len(key) > best_len:
                best_len, best = len(key), secs
        self._threshold_cache[path] = best
        return best

    # -- updates -----------------------------------------------------------------------------
    def update_values(self, src: str, values: list[dict], t_rx: float) -> None:
        for v in values:
            path = v.get("path")
            if not isinstance(path, str):
                continue
            self._entries[(path, src)] = {
                "value": v.get("value"),
                "unit": v.get("unit"),
                "src": src,
                "ref": v.get("ref"),
                "ch": v.get("ch"),
                "disp": v.get("disp"),
                "t_rx": t_rx,
            }

    def update_health(self, src: str, health: dict, t_rx: float) -> None:
        """Merge keys into the source's health dict (per-frame bus counters and 1 Hz heartbeats
        combine instead of replacing each other)."""
        self._health.setdefault(src, {}).update(health)
        self._health_rx[src] = t_rx

    # -- queries -----------------------------------------------------------------------------
    def _age(self, t_rx: float, now: float) -> float:
        return max(0.0, now - t_rx)

    def latest(self, path: str) -> dict | None:
        """Freshest non-stale entry for path across all sources that has a value, or None.

        A None value (an instrument showing "OFF") is no data: it never hides a valid value from
        another source. Those entries stay in rows() for the diagnostics page."""
        now = self.clock.monotonic()
        thr = self.threshold(path)
        best: dict | None = None
        for (p, _src), e in self._entries.items():
            if p != path or e["value"] is None:
                continue
            age = self._age(e["t_rx"], now)
            if age > thr:
                continue
            if best is None or e["t_rx"] > best["t_rx"]:
                best = e
        if best is None:
            return None
        out = {k: v for k, v in best.items()}
        out["path"] = path
        out["age_s"] = self._age(best["t_rx"], now)
        out["stale"] = False
        return out

    def rows(self) -> list[dict]:
        now = self.clock.monotonic()
        out = []
        for (path, src), e in sorted(self._entries.items()):
            age = self._age(e["t_rx"], now)
            thr = self.threshold(path)
            out.append(
                {
                    "path": path,
                    "value": e["value"],
                    "unit": e["unit"],
                    "src": src,
                    "ref": e["ref"],
                    "ch": e["ch"],
                    "disp": e["disp"],
                    "age_s": round(age, 3),
                    "stale": age > thr,
                    "stale_after_s": thr,
                }
            )
        return out

    def health(self) -> dict:
        now = self.clock.monotonic()
        out = {}
        for src, h in sorted(self._health.items()):
            age = self._age(self._health_rx.get(src, now), now)
            d = dict(h)
            d["age_s"] = round(age, 3)
            d["alive"] = age <= ALIVE_S
            out[src] = d
        return out

    def snapshot(self) -> dict:
        return {"values": self.rows(), "health": self.health()}
