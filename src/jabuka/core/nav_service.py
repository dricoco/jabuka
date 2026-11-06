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

from jabuka.common.clock import Clock, utc_epoch
from jabuka.common.conventions import current_towards_uv
from jabuka.common.units import ms_to_kn, wrap_pi
from jabuka.core.state import StateStore
from jabuka.nav import laylines, wind
from jabuka.nav.course import CourseStore
from jabuka.nav.polar import Targets, apply_efficiency, efficiency_for, load_racepack_polar
from jabuka.nav.settings import ManualWindStore, SettingsStore
from jabuka.nav.tacks import TackTracker

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
        self.tacks = TackTracker(self.settings_store.settings)
        self.polar = load_racepack_polar(self.racepack_dir)
        self.wind = wind.WindPipeline(self.settings_store.settings)
        self.last: dict | None = None
        self.errors = 0
        self._prev_leg: str | None = None
        self._prev_primary: str | None = None
        self._prev_target: tuple[int, str] | None = None  # hysteresis is per mark (IN-07)

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
        # wind first: it owns the TRUE heading (compass, or COG inside the Jabuka zone)
        w = self.wind.update(inputs, t_mono, manual=self.manual.entry, t_wall=utc_epoch(self.clock))
        hdg_t = w.hdg
        cog = wind.num(inputs.get(wind.COG))
        sog_ms = wind.num(inputs.get(wind.SOG))
        bsp_ms = wind.num(inputs.get(wind.BSP))
        sog_kn = ms_to_kn(sog_ms) if sog_ms is not None else None
        bsp_kn = ms_to_kn(bsp_ms) if bsp_ms is not None else None
        msg["boat"] = {
            "lat": lat,
            "lon": lon,
            "hdg_t": _deg(hdg_t),
            "cog_t": _deg(cog),
            "sog_kn": _r(sog_kn, 2),
            "bsp_kn": _r(bsp_kn, 2),
            "heading_src": w.heading_src,
        }

        # -- wind --------------------------------------------------------------------------
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
        targets_eff: Targets | None = None
        twa_abs = abs(math.degrees(w.twa)) if w.twa is not None else None
        # factor of the current point of sail (up / down / general), speeds only (Pitfall 9)
        eff_now = efficiency_for(twa_abs, s.efficiency, s.efficiency_up, s.efficiency_down)
        pct = None
        if w.ok and tws_kn is not None:
            targets_eff = apply_efficiency(
                self.polar.targets(tws_kn), s.efficiency, s.efficiency_up, s.efficiency_down
            )
            if twa_abs is not None and bsp_kn is not None:
                ref = eff_now * self.polar.speed(tws_kn, twa_abs)
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

        # -- sailed angles + current -------------------------------------------------------
        self.tacks.update(t_mono, w.twa, cog, w.twd_lay, sog_kn, w.in_zone)
        current_kn = self._current_kn(inputs, w)

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
        if target is not None and (target.idx, target.mark.id) != self._prev_target:
            self._prev_target = (target.idx, target.mark.id)
            self._prev_leg = self._prev_primary = None  # a new leg starts without hysteresis
        if target is not None and lat is not None and lon is not None:
            boat = laylines.BoatState(
                lat=lat, lon=lon, hdg=hdg_t, cog=cog, sog_kn=sog_kn, bsp_kn=bsp_kn
            )
            reach_bsp = None
            if w.ok and tws_kn is not None and twa_abs is not None:
                reach_bsp = eff_now * self.polar.speed(tws_kn, twa_abs)
            res = laylines.solve(
                boat,
                w,
                targets_eff or Targets(45.0, 0.0, 150.0, 0.0),
                laylines.Anchor(target.anchor_lat, target.anchor_lon),
                prev_leg=self._prev_leg,
                prev_primary=self._prev_primary,
                reach_bsp_kn=reach_bsp,
                current_kn=current_kn,
                src=s.layline_source,
                sailed=self.tacks.angles() if s.layline_source == "sailed" else None,
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

    def _current_kn(self, inputs: dict, w: wind.WindSolution) -> tuple[float, float] | None:
        """Hercules set/drift as (east, north) kn when NAV-03 is on, both are fresh and the boat
        is outside the Jabuka zone (the set is compass-derived, Pitfall 7); else None."""
        if not self.settings.use_current or w.in_zone:
            return None
        cur = wind.current_true(inputs, self.settings)
        if cur is None:
            return None
        u, v = current_towards_uv(cur[0], ms_to_kn(cur[1]))
        return u, v

    def _write_back(self, w, tws_kn, pct, msg: dict, t_mono: float) -> None:
        """Derived values into the StateStore (src "nav"): Diag page + 1 Hz derived log."""
        lay = msg.get("layline") or {}
        check = w.check or {}
        self.state.update_values(
            "nav",
            [
                {"path": "nav.wind.twd", "value": w.twd, "unit": "rad", "ref": "T"},
                {"path": "nav.wind.twdLay", "value": w.twd_lay, "unit": "rad", "ref": "T"},
                {"path": "nav.wind.tws", "value": w.tws, "unit": "m/s"},
                {"path": "nav.wind.source", "value": w.source, "unit": None},
                {"path": "nav.wind.dtwa", "value": check.get("dtwa"), "unit": "deg"},
                {"path": "nav.wind.dtws", "value": check.get("dtws_kn"), "unit": "kn"},
                {"path": "nav.wind.inZone", "value": w.in_zone, "unit": None},
                {"path": "nav.heading.true", "value": w.hdg, "unit": "rad", "ref": "T"},
                {"path": "nav.heading.src", "value": w.heading_src, "unit": None},
                {"path": "nav.polar.pct", "value": _r(pct, 1), "unit": "%"},
                {"path": "nav.layline.countdown", "value": lay.get("countdown_s"), "unit": "s"},
                {"path": "nav.tacks.stbd", "value": self.tacks.diag("stbd"), "unit": "deg"},
                {"path": "nav.tacks.port", "value": self.tacks.diag("port"), "unit": "deg"},
            ],
            t_mono,
        )
