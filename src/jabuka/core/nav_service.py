"""Per-tick nav composition: wind -> polar targets (x efficiency) -> course -> laylines, and the
nav WebSocket message (contract consumed by plans 02-03/04/05 and Phase 3).

Display units in the message: degrees, knots, nm, seconds. Every heading/direction is TRUE
(suffix _t); the browser converts to magnetic for display with display.variation. Unknown values
are null, never NaN. A failure inside update() never crashes the tick: it is counted in
``errors`` and yields a message with null blocks and an alert.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from jabuka.common.clock import Clock
from jabuka.common.units import ms_to_kn, wrap_pi
from jabuka.core.state import StateStore
from jabuka.nav import laylines, wind
from jabuka.nav.course import CourseStore
from jabuka.nav.polar import Targets, load_racepack_polar
from jabuka.nav.settings import ManualWindStore, SettingsStore

log = logging.getLogger("jabuka.nav")

NAV_MSG_VERSION = 1


def _r(x: Any, nd: int) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _deg(rad: float | None, nd: int = 1) -> float | None:
    if rad is None or not math.isfinite(rad):
        return None
    d = round(math.degrees(rad) % 360.0, nd)
    return 0.0 if d >= 360.0 else d


def _signed_deg(rad: float | None, nd: int = 1) -> float | None:
    if rad is None or not math.isfinite(rad):
        return None
    return round(math.degrees(wrap_pi(rad)), nd)


class NavService:
    def __init__(
        self,
        state: StateStore,
        clock: Clock,
        data_dir: str | Path,
        racepack_dir: str | Path | None = None,
    ) -> None:
        self.state = state
        self.clock = clock
        self.data_dir = Path(data_dir)
        self.racepack_dir = Path(racepack_dir) if racepack_dir is not None else None
        self.settings_store = SettingsStore(self.data_dir)
        self.course = CourseStore(self.data_dir)
        self.manual = ManualWindStore(self.data_dir)
        self.polar = load_racepack_polar(self.racepack_dir)
        self.wind = wind.WindPipeline(self.settings_store.settings)
        self.last: dict | None = None
        self.errors = 0
        self._prev_leg: str | None = None
        self._prev_primary: str | None = None

    @property
    def settings(self):
        return self.settings_store.settings

    # -- inputs ------------------------------------------------------------------------------
    def _inputs(self) -> dict[str, dict | None]:
        return {p: self.state.latest(p) for p in wind.INPUT_PATHS}

    # -- message -----------------------------------------------------------------------------
    def _envelope(self, t_mono: float) -> dict:
        s = self.settings
        return {
            "type": "nav",
            "v": NAV_MSG_VERSION,
            "t_mono": round(t_mono, 3),
            "utc": self.clock.status().get("utc"),
            "course_version": self.course.version,
            "settings_version": self.settings_store.version,
            "boat": None,
            "wind": None,
            "polar": None,
            "mark": None,
            "leg": None,
            "helm": {"primary": None, "target": None, "deviation": None, "cts_t": None},
            "layline": None,
            "course": self.course.status(),
            "display": {"heading_ref": s.heading_display, "variation": s.variation_deg},
            "alerts": (
                list(self.settings_store.alerts)
                + list(self.course.alerts)
                + list(self.manual.alerts)
            ),
        }

    def update(self) -> dict:
        t_mono = self.clock.monotonic()
        try:
            msg = self._compute(t_mono)
        except Exception:
            self.errors += 1
            log.exception("nav update failed")
            msg = self._envelope(t_mono)
            msg["alerts"].append("Erreur de calcul nav")
        self.last = msg
        return msg

    def _compute(self, t_mono: float) -> dict:
        s = self.settings
        self.wind.settings = s
        msg = self._envelope(t_mono)
        inputs = self._inputs()

        # -- boat --------------------------------------------------------------------------
        pos = inputs.get(wind.POSITION)
        lat = lon = None
        if pos is not None and isinstance(pos.get("value"), dict):
            lat = _r(pos["value"].get("latitude"), 7)
            lon = _r(pos["value"].get("longitude"), 7)
        hdg_t = self.wind.heading(inputs)
        cog = wind.num(inputs.get(wind.COG))
        sog_ms = wind.num(inputs.get(wind.SOG))
        bsp_ms = wind.num(inputs.get(wind.BSP))
        sog_kn = ms_to_kn(sog_ms) if sog_ms is not None else None
        bsp_kn = ms_to_kn(bsp_ms) if bsp_ms is not None else None
        heading_src = "compass" if hdg_t is not None else ("cog" if cog is not None else None)
        msg["boat"] = {
            "lat": lat,
            "lon": lon,
            "hdg_t": _deg(hdg_t),
            "cog_t": _deg(cog),
            "sog_kn": _r(sog_kn, 2),
            "bsp_kn": _r(bsp_kn, 2),
            "heading_src": heading_src,
        }

        # -- wind --------------------------------------------------------------------------
        w = self.wind.update(inputs, t_mono, manual=self.manual.entry, t_wall=self.clock.wall())
        msg["alerts"].extend(w.alerts)
        tws_kn = ms_to_kn(w.tws) if w.tws is not None else None
        msg["wind"] = {
            "source": w.source,
            "stale": w.stale,
            "twd_t": _deg(w.twd),
            "twd_lay_t": _deg(w.twd_lay),
            "tws_kn": _r(tws_kn, 1),
            "twa": _signed_deg(w.twa),
            "heading_trusted": w.heading_trusted,
            "in_zone": w.in_zone,
            "manual_age_s": _r(w.manual_age_s, 0),
            "check": w.check,
        }

        # -- polar -------------------------------------------------------------------------
        eff_up, eff_down = s.eff_up(), s.eff_down()
        targets_eff: Targets | None = None
        twa_abs = abs(math.degrees(w.twa)) if w.twa is not None else None
        pct = None
        if w.ok and tws_kn is not None:
            raw = self.polar.targets(tws_kn)
            targets_eff = Targets(
                raw.up_twa, raw.up_bsp * eff_up, raw.down_twa, raw.down_bsp * eff_down
            )
            if twa_abs is not None and bsp_kn is not None:
                eff = eff_up if twa_abs < 90.0 else eff_down
                ref = eff * self.polar.speed(tws_kn, twa_abs)
                pct = bsp_kn / ref * 100.0 if ref > 0.05 else None
        msg["polar"] = {
            "name": self.polar.name,
            "eff": s.efficiency,
            "up": (
                {"twa": _r(targets_eff.up_twa, 1), "bsp_kn": _r(targets_eff.up_bsp, 2)}
                if targets_eff
                else None
            ),
            "down": (
                {"twa": _r(targets_eff.down_twa, 1), "bsp_kn": _r(targets_eff.down_bsp, 2)}
                if targets_eff
                else None
            ),
            "target_bsp_kn": None,
            "pct": _r(pct, 0),
        }

        # -- course + laylines -------------------------------------------------------------
        self.course.on_tick(lat, lon, t_mono)
        msg["course"] = self.course.status()
        target = self.course.active_target()
        if target is not None:
            m = target.mark
            msg["mark"] = {
                "id": m.id,
                "name": m.name,
                "idx": target.idx,
                "lat": m.lat,
                "lon": m.lon,
                "anchor_lat": round(target.anchor_lat, 6),
                "anchor_lon": round(target.anchor_lon, 6),
                "side": target.side,
                "radius_nm": target.radius_nm,
                "dtw_nm": None,
                "btw_t": None,
                "ttw_s": None,
            }
        if target is not None and lat is not None and lon is not None:
            boat = laylines.BoatState(
                lat=lat, lon=lon, hdg=hdg_t, cog=cog, sog_kn=sog_kn, bsp_kn=bsp_kn
            )
            reach_bsp = None
            if w.ok and tws_kn is not None and twa_abs is not None:
                eff = eff_up if twa_abs < 90.0 else eff_down
                reach_bsp = eff * self.polar.speed(tws_kn, twa_abs)
            res = laylines.solve(
                boat,
                w,
                targets_eff or Targets(45.0, 0.0, 150.0, 0.0),
                laylines.Anchor(target.anchor_lat, target.anchor_lon),
                prev_leg=self._prev_leg,
                prev_primary=self._prev_primary,
                reach_bsp_kn=reach_bsp,
                src="polar",  # sailed angles arrive with plan 02-03
            )
            self._prev_leg = res.leg
            self._prev_primary = res.helm.get("primary")
            msg["mark"]["dtw_nm"] = _r(res.dtw_nm, 2)
            msg["mark"]["btw_t"] = _deg(res.btw)
            msg["mark"]["ttw_s"] = _r(res.ttw_s, 0)
            msg["leg"] = res.leg
            msg["helm"] = res.helm
            msg["layline"] = res.layline
            msg["polar"]["target_bsp_kn"] = _r(res.target_bsp_kn, 2)
        if w.source == "NONE":
            msg["alerts"].append("PAS DE VENT")

        self._write_back(w, tws_kn, pct, msg, t_mono)
        return msg

    def _write_back(self, w, tws_kn, pct, msg: dict, t_mono: float) -> None:
        """Derived values into the StateStore (src "nav"): Diag page + 1 Hz derived log."""
        lay = msg.get("layline") or {}
        self.state.update_values(
            "nav",
            [
                {"path": "nav.wind.twd", "value": w.twd, "unit": "rad", "ref": "T"},
                {"path": "nav.wind.tws", "value": w.tws, "unit": "m/s"},
                {"path": "nav.wind.source", "value": w.source, "unit": None},
                {"path": "nav.polar.pct", "value": _r(pct, 1), "unit": "%"},
                {"path": "nav.layline.countdown", "value": lay.get("countdown_s"), "unit": "s"},
            ],
            t_mono,
        )
