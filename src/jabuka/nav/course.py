"""Mark library, Course A/B templates, course editing, the rounding state machine and the persisted
active course (CRSE-01..05).

<data-dir>/course.json = {"version": int, "course": Course}. Every change is written with
atomic_write_json and bumps the version, so every tablet re-fetches it (Pitfall 10). A torn or
invalid file falls back to NAME.bak with a "restauré" alert (it may hold an older active mark,
04-REVIEW WR-04), then to Course A with an "illisible" alert.

Index 0 of the sequence is the start and is never active; select() puts the first rounding mark
(index 1) active. The anchor of the active mark is the point at radius_nm on the rounding side:
A = M + R * u(leg_bearing + 90 deg) for a mark left to port, - 90 deg for starboard, M itself for
side "none" (RESEARCH Pattern 4, Pitfall 17). leg_bearing is previous mark -> active mark.

Editing (CRSE-02/04): add a custom mark ("m<N>"), move/rename any mark (a builtin mark gets an
override stored in course.json, marks.json stays the reference and the override survives a
template switch), change a leg's side/radius, delete, reorder, "Finir ici" (finish_idx), activate,
confirm the sides. Every edit keeps the active mark on the same leg object.

Rounding state machine (CRSE-03, RESEARCH Pattern 6, Pitfall 11), active mark only:
APPROACH -> IN_ZONE when d(P, M) <= radius + 0.25 nm; then a rounding candidate when the boat has
passed abeam of M relative to the incoming leg (dot(P - M, u_in) > 0) or has left the zone past
the mark. A zone exit counts only past the mark: along the incoming leg; at a hairpin, after
having been past it along the incoming leg since entering the zone and now past it along the
outgoing leg. A zone exit on the approach side never advances (G-4-R02). Gate d <= 2 nm.
The candidate must hold DEBOUNCE_S consecutive seconds of t_mono; then the next
mark becomes active, a banner "Marque suivante : <nom> — Annuler" is shown for 60 s and the
advance is persisted together with the banner (a restart within the window still offers
Annuler). undo() restores the previous mark and suppresses that mark until the boat has left its
zone; leaving that zone then counts as the rounding (10 s debounce), so the real rounding after
an early advance + Annuler still advances. The finish leg finishes on entering its radius
("ARRIVÉE — <nom>"), no further advance.
Hairpin marks (course change > 90 deg, Jabuka in both courses: in 203 deg, out 009/038 deg) need
more than abeam of the incoming leg, which comes half a lap before the island is rounded (WR-01):
the boat must also be past the mark along the outgoing leg (the far side of the island), or have
left the zone past the mark (above). Debounce state lives in memory.
"""

from __future__ import annotations

import hmac
import json
import logging
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jabuka.common.atomicio import atomic_write_json, load_json_status
from jabuka.nav import geo
from jabuka.nav.settings import VersionConflict

log = logging.getLogger("jabuka.nav.course")

COURSE_FILE = "course.json"
MAX_MARKS = 30
MAX_SEQ = 30
NAME_MAX = 40

ZONE_MARGIN_NM = 0.25  # arrival zone = leg radius + this (RESEARCH A10)
GATE_NM = 2.0  # nothing fires further than this from the active mark...
GATE_OVER_ZONE_NM = 0.5  # ...or than this beyond a large zone (radius up to 3 nm, IN-07)
WRITE_ALERT = "Écriture du parcours impossible"
DEBOUNCE_S = 10.0  # rounding evidence must hold this long
FSM_GAP_S = 3.0  # a longer gap between position samples restarts the debounce (IN-05)
BANNER_S = 60.0  # Annuler window
FINISH_MIN_NM = 0.05  # finish radius floor (a radius-0 custom finish is still reachable)
HAIRPIN_DEG = 90.0  # course change above which abeam also needs "past the mark" on the way out

Side = Literal["port", "stbd", "none"]


class CourseError(ValueError):
    """An edit that cannot apply (bad index, too many marks...). HTTP 422."""


class UnknownMark(LookupError):
    """No mark with that id. HTTP 404."""


class BannerGone(Exception):
    """Annuler after the window, with a wrong token or nothing to undo. HTTP 410."""


def clean_name(text: str) -> str:
    """Control characters (code < 32 or 127) dropped, surrounding spaces stripped."""
    return "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127).strip()


class Mark(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=NAME_MAX)
    lat: float = Field(ge=42.0, le=45.0)
    lon: float = Field(ge=14.0, le=17.0)
    radius_nm: float = Field(0.0, ge=0.0, le=3.0)
    kind: str = Field("mark", max_length=20)
    builtin: bool = True
    provisional: bool = False


class Leg(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mark_id: str = Field(min_length=1, max_length=40)
    side: Side = "none"
    radius_nm: float = Field(0.0, ge=0.0, le=3.0)


class MarkOverride(BaseModel):
    """Navigator's correction of a builtin mark (e.g. Vodice moved to the SI start line)."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(None, min_length=1, max_length=NAME_MAX)
    lat: float | None = Field(None, ge=42.0, le=45.0)
    lon: float | None = Field(None, ge=14.0, le=17.0)


class Banner(BaseModel):
    """Pending advance (Annuler offered) or the finish notice. Times are trusted UTC epochs (GPS,
    never the unsynced system clock, WR-03; None when not synced) so a restart can tell how much
    of the window is left; the live window runs on t_mono."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["advance", "finish"]
    text: str = Field(max_length=160)
    token: str | None = Field(None, max_length=64)
    prev_idx: int | None = None
    at_wall: float | None = None
    until_wall: float | None = None


class Course(BaseModel):
    model_config = ConfigDict(extra="ignore")

    template: Literal["A", "B", "custom"] = "A"
    marks: dict[str, Mark] = Field(default_factory=dict, max_length=MAX_MARKS)
    seq: list[Leg] = Field(default_factory=list, max_length=MAX_SEQ)
    active_idx: int = Field(1, ge=0)
    finish_idx: int | None = None
    finished: bool = False
    sides_confirmed: bool = False
    overrides: dict[str, MarkOverride] = Field(default_factory=dict, max_length=MAX_MARKS)
    next_mark_n: int = Field(1, ge=1)
    banner: Banner | None = None
    suppress_idx: int | None = None


@dataclass
class ActiveTarget:
    mark: Mark
    idx: int
    side: str
    radius_nm: float
    anchor_lat: float
    anchor_lon: float
    leg_bearing: float  # rad TRUE, previous mark -> active mark


def load_library() -> dict[str, Any]:
    """The packaged marks.json (marks + templates A/B)."""
    text = resources.files("jabuka.nav").joinpath("data", "marks.json").read_text("utf-8")
    return json.loads(text)


def _apply_override(mark: Mark, ov: MarkOverride | None) -> Mark:
    if ov is None:
        return mark
    upd = {k: v for k, v in ov.model_dump().items() if v is not None}
    return mark.model_copy(update=upd)


def course_from_template(
    library: dict[str, Any], template: str, overrides: dict[str, MarkOverride] | None = None
) -> Course:
    overrides = overrides or {}
    marks = {
        m["id"]: _apply_override(Mark(**m, builtin=True), overrides.get(m["id"]))
        for m in library["marks"]
    }
    seq = [
        Leg(mark_id=e["mark_id"], side=e["side"], radius_nm=marks[e["mark_id"]].radius_nm)
        for e in library["templates"][template]
    ]
    return Course(
        template=template,
        marks=marks,
        seq=seq,
        active_idx=1 if len(seq) > 1 else 0,
        finish_idx=None,
        sides_confirmed=bool(library.get("sides_confirmed", False)),
        overrides={k: v for k, v in overrides.items() if k in marks},
    )


def _valid(course: Course) -> bool:
    if len(course.seq) < 2 or any(leg.mark_id not in course.marks for leg in course.seq):
        return False
    last = len(course.seq) - 1
    if course.finish_idx is not None and not 1 <= course.finish_idx <= last:
        return False
    return 1 <= course.active_idx <= last


def _parse_course_file(raw: Any) -> tuple[Course, int]:
    """course.json content -> (course, version). Raises ValueError (pydantic ValidationError
    included) when it is not a whole, consistent course: load_json_status then tries NAME.bak."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    course = Course.model_validate(raw.get("course"))
    if not _valid(course):
        raise ValueError("inconsistent course")
    v = raw.get("version", 0)
    return course, (v if isinstance(v, int) and not isinstance(v, bool) else 0)


class CourseStore:
    def __init__(
        self,
        data_dir: str | Path,
        library: dict[str, Any] | None = None,
        *,
        on_event: Callable[[dict], None] | None = None,
        wall: Callable[[], float] | None = None,
    ) -> None:
        self.path = Path(data_dir) / COURSE_FILE
        self.library = library if library is not None else load_library()
        self.alerts: list[str] = []
        self.version = 0
        self.course = course_from_template(self.library, "A")
        self.boat: tuple[float, float, float] | None = None  # (lat, lon, t_mono)
        # set by the course API router: event lines and the trusted UTC (epoch | None) for the
        # banner window
        self.on_event = on_event
        self.wall = wall
        # rounding state machine (memory only)
        self._fsm_key: tuple[int, str] | None = None
        self._entered = False
        self._cand_since: float | None = None
        self._suppressed_in_zone = False  # seen inside the zone of the mark Annuler restored
        # the boat has been past the active mark along the incoming leg since entering its zone;
        # a hairpin's zone exit needs it (G-4-R02)
        self._beyond = False
        self._last_fsm_t: float | None = None  # t_mono of the previous position sample
        self._banner_until: float | None = None  # t_mono end of the banner window
        parsed, source = load_json_status(self.path, None, validate=_parse_course_file)
        if parsed is not None:  # "main" or "bak"
            self.course, self.version = parsed
        if source == "bak":  # an older course may come back: never silent (04-REVIEW WR-04)
            self.alerts.append("Parcours restauré depuis la sauvegarde : vérifier la marque active")
        elif source == "unreadable":  # present but neither NAME nor NAME.bak valid (04-01 soak)
            self.alerts.append("Parcours illisible : Parcours A par défaut")

    # -- accessors ---------------------------------------------------------------------------
    @property
    def marks(self) -> dict[str, Mark]:
        return self.course.marks

    @property
    def last_idx(self) -> int:
        c = self.course
        return c.finish_idx if c.finish_idx is not None else len(c.seq) - 1

    # -- events ------------------------------------------------------------------------------
    def _emit(self, rec: dict) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(rec)
        except Exception:  # an event line must never break an edit or the tick
            log.exception("course event failed")

    # -- persistence -------------------------------------------------------------------------
    def _check_version(self, base_version: int | None) -> None:
        if base_version is not None and base_version != self.version:
            raise VersionConflict(self.version, self.to_api())

    def _write(self, course: Course, version: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, {"version": version, "course": course.model_dump()})

    def _commit(
        self, course: Course, base_version: int | None = None, event: dict | None = None
    ) -> None:
        """Version check, atomic write, then (and only then) the new state in memory."""
        self._check_version(base_version)
        version = self.version + 1
        self._write(course, version)
        self._clear_write_alert()
        self._set(course, version)
        if event is not None:
            self._emit({**event, "version": version})

    def _set(self, course: Course, version: int) -> None:
        old_active = (self.course.active_idx, self.course.seq[self.course.active_idx].mark_id)
        self.course = course
        self.version = version
        if course.banner is None:
            self._banner_until = None
        new_active = (course.active_idx, course.seq[course.active_idx].mark_id)
        if new_active != old_active:
            self._reset_fsm()

    def _commit_tick(self, course: Course, event: dict) -> None:
        """A state-machine change: written like an edit, applied in memory even when the disk
        fails (steering to the right mark matters more than the file)."""
        try:
            self._commit(course, None, event)
        except OSError:
            log.exception("course write failed during the tick")
            if WRITE_ALERT not in self.alerts:
                self.alerts.append(WRITE_ALERT)
            self._set(course, self.version + 1)
            self._emit({**event, "version": self.version, "persisted": False})

    def _save_quiet(self, course: Course) -> None:
        """Banner expiry / suppression cleared: persisted without a version bump."""
        try:
            self._write(course, self.version)
            self._clear_write_alert()
        except OSError:
            log.exception("course write failed")
        self.course = course
        if course.banner is None:
            self._banner_until = None

    def _clear_write_alert(self) -> None:
        """A successful write ends a transient disk failure's alert (IN-07)."""
        if WRITE_ALERT in self.alerts:
            self.alerts.remove(WRITE_ALERT)

    def _copy(self, **update: Any) -> Course:
        return self.course.model_copy(deep=True, update=update)

    # -- index helpers ----------------------------------------------------------------------
    def _check_idx(self, idx: int, *, allow_start: bool = False) -> None:
        lo = 0 if allow_start else 1
        if not isinstance(idx, int) or not lo <= idx < len(self.course.seq):
            raise CourseError(f"index {idx} out of range")

    @staticmethod
    def _unused_marks_dropped(c: Course) -> None:
        used = {leg.mark_id for leg in c.seq}
        for mid in [k for k, m in c.marks.items() if not m.builtin and k not in used]:
            del c.marks[mid]

    # -- commands: template / navigation ----------------------------------------------------
    def select(self, template: str, base_version: int | None = None) -> dict:
        if template not in self.library.get("templates", {}):
            raise ValueError(f"unknown course template {template!r}")
        old = self.course
        if template == old.template:  # WR-05: re-selecting the template in use changes nothing
            self._check_version(base_version)
            return self.to_api()
        new = course_from_template(self.library, template, old.overrides)
        new.next_mark_n = old.next_mark_n
        # the same mark at the same place in the new sequence stays active (A <-> B share
        # Vodice, Plić Sestre and Jabuka): race progress survives a template correction
        i = old.active_idx
        if 1 <= i < len(new.seq) and new.seq[i].mark_id == old.seq[i].mark_id and not old.finished:
            new.active_idx = i
        self._commit(
            new, base_version, {"type": "course_edit", "action": "select", "template": template}
        )
        return self.to_api()

    def _step(self, delta: int, base_version: int | None = None) -> dict:
        c = self.course
        idx = min(max(1, c.active_idx + delta), self.last_idx)
        if idx != c.active_idx:
            new = self._copy(active_idx=idx, finished=False, banner=None, suppress_idx=None)
            action = "next" if delta > 0 else "prev"
            self._commit(new, base_version, {"type": "course_edit", "action": action, "idx": idx})
        else:
            self._check_version(base_version)
        return self.to_api()

    def next(self, base_version: int | None = None) -> dict:
        return self._step(+1, base_version)

    def prev(self, base_version: int | None = None) -> dict:
        return self._step(-1, base_version)

    def activate(self, idx: int, base_version: int | None = None) -> dict:
        self._check_version(base_version)
        if not isinstance(idx, int) or not 1 <= idx <= self.last_idx:
            raise CourseError(f"index {idx} out of range")
        new = self._copy(active_idx=idx, finished=False, banner=None, suppress_idx=None)
        self._commit(new, base_version, {"type": "course_edit", "action": "activate", "idx": idx})
        return self.to_api()

    def confirm_sides(self, base_version: int | None = None) -> dict:
        self._commit(
            self._copy(sides_confirmed=True),
            base_version,
            {"type": "course_edit", "action": "confirm_sides"},
        )
        return self.to_api()

    # -- commands: editing ------------------------------------------------------------------
    def add_mark(
        self,
        name: str,
        lat: float,
        lon: float,
        radius_nm: float = 0.05,
        side: str = "none",
        insert_at: int | None = None,
        base_version: int | None = None,
    ) -> dict:
        """A custom mark ("m<N>") and its leg; default position right after the active mark."""
        self._check_version(base_version)
        c = self.course
        if len(c.marks) >= MAX_MARKS or len(c.seq) >= MAX_SEQ:
            raise CourseError(f"at most {MAX_MARKS} marks")
        name = clean_name(name)
        n = c.next_mark_n
        while f"m{n}" in c.marks:
            n += 1
        mark_id = f"m{n}"
        mark = Mark(
            id=mark_id, name=name, lat=lat, lon=lon, radius_nm=radius_nm, kind="mark", builtin=False
        )
        leg = Leg(mark_id=mark_id, side=side, radius_nm=radius_nm)
        at = c.active_idx + 1 if insert_at is None else insert_at
        if not isinstance(at, int) or not 1 <= at <= len(c.seq):
            raise CourseError(f"insert_at {insert_at} out of range")
        new = self._copy(template="custom", next_mark_n=n + 1, banner=None, suppress_idx=None)
        new.marks[mark_id] = mark
        new.seq.insert(at, leg)
        # IN-03: inserted right before the active FINISH ("À la fin" on the last leg): the new
        # mark is the next one to round, so it becomes active (not listed as already done).
        # Anywhere else the active mark stays the same mark.
        before_active_finish = at == c.active_idx == self.last_idx and not c.finished
        if at <= new.active_idx and not before_active_finish:
            new.active_idx += 1
        if new.finish_idx is not None and at <= new.finish_idx:
            new.finish_idx += 1
        self._commit(
            new,
            None,
            {"type": "course_edit", "action": "add_mark", "mark_id": mark_id, "idx": at},
        )
        return self.to_api()

    def edit_mark(
        self,
        mark_id: str,
        *,
        name: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        base_version: int | None = None,
    ) -> dict:
        """Move and/or rename a mark. A builtin mark keeps its library entry; the change is an
        override in course.json that survives a template switch."""
        self._check_version(base_version)
        c = self.course
        if mark_id not in c.marks:
            raise UnknownMark(mark_id)
        if (lat is None) != (lon is None):
            raise CourseError("lat and lon go together")
        upd: dict[str, Any] = {}
        if name is not None:
            upd["name"] = clean_name(name)
        if lat is not None:
            upd["lat"], upd["lon"] = lat, lon
        if not upd:
            raise CourseError("nothing to change")
        new = self._copy()
        mark = Mark.model_validate({**new.marks[mark_id].model_dump(), **upd})
        new.marks[mark_id] = mark
        if mark.builtin:
            ov = new.overrides.get(mark_id) or MarkOverride()
            new.overrides[mark_id] = ov.model_copy(update=upd)
        self._commit(
            new,
            None,
            {
                "type": "course_edit",
                "action": "edit_mark",
                "mark_id": mark_id,
                "fields": sorted(upd),
            },
        )
        return self.to_api()

    def set_leg(
        self,
        idx: int,
        *,
        side: str | None = None,
        radius_nm: float | None = None,
        base_version: int | None = None,
    ) -> dict:
        self._check_version(base_version)
        self._check_idx(idx)
        upd: dict[str, Any] = {}
        if side is not None:
            upd["side"] = side
        if radius_nm is not None:
            upd["radius_nm"] = radius_nm
        if not upd:
            raise CourseError("nothing to change")
        new = self._copy()
        new.seq[idx] = Leg.model_validate({**new.seq[idx].model_dump(), **upd})
        self._commit(
            new,
            None,
            {"type": "course_edit", "action": "set_leg", "idx": idx, **upd},
        )
        return self.to_api()

    def delete_leg(self, idx: int, base_version: int | None = None) -> dict:
        """Never the start; deleting the active leg makes the following mark active."""
        self._check_version(base_version)
        self._check_idx(idx)
        c = self.course
        if len(c.seq) <= 2:
            raise CourseError("a course needs a start and one mark")
        removed = c.seq[idx].mark_id
        new = self._copy(template="custom", banner=None, suppress_idx=None)
        del new.seq[idx]
        last = len(new.seq) - 1
        if idx < new.active_idx:
            new.active_idx -= 1
        if new.finish_idx is not None:
            if idx < new.finish_idx:
                new.finish_idx -= 1
            elif idx == new.finish_idx:
                new.finish_idx = None
        new.active_idx = max(1, min(new.active_idx, last))
        if new.finish_idx is not None:
            new.finish_idx = min(new.finish_idx, last)
            new.active_idx = min(new.active_idx, new.finish_idx)
        if new.active_idx != c.active_idx or idx == c.active_idx:
            new.finished = False
        self._unused_marks_dropped(new)
        self._commit(
            new,
            None,
            {"type": "course_edit", "action": "delete_leg", "idx": idx, "mark_id": removed},
        )
        return self.to_api()

    def reorder(self, from_idx: int, to_idx: int, base_version: int | None = None) -> dict:
        """Move one leg; the start (0) never moves and nothing moves before it. The active mark
        and the finish stay on the same legs."""
        self._check_version(base_version)
        self._check_idx(from_idx)
        self._check_idx(to_idx)
        if from_idx == to_idx:
            raise CourseError("nothing to move")
        c = self.course
        new = self._copy(template="custom", banner=None, suppress_idx=None)
        order = list(range(len(c.seq)))
        order.insert(to_idx, order.pop(from_idx))
        new.seq = [new.seq[i] for i in order]
        new.active_idx = order.index(c.active_idx)
        if c.finish_idx is not None:
            new.finish_idx = order.index(c.finish_idx)
            if new.active_idx > new.finish_idx:
                new.active_idx = new.finish_idx
        self._commit(
            new,
            None,
            {"type": "course_edit", "action": "reorder", "from_idx": from_idx, "to_idx": to_idx},
        )
        return self.to_api()

    def set_finish(self, idx: int | None, base_version: int | None = None) -> dict:
        """ "Finir ici" (CRSE-04): the course ends at leg idx (None restores the full course)."""
        self._check_version(base_version)
        new = self._copy(banner=None, suppress_idx=None, finished=False)
        if idx is not None:
            self._check_idx(idx)
            new.finish_idx = idx
            new.active_idx = min(new.active_idx, idx)
        else:
            new.finish_idx = None
        self._commit(new, None, {"type": "course_edit", "action": "finish", "idx": idx})
        return self.to_api()

    # -- rounding state machine --------------------------------------------------------------
    def _reset_fsm(self) -> None:
        self._fsm_key = None
        self._entered = False
        self._cand_since = None
        self._suppressed_in_zone = False
        self._beyond = False

    def _tick_banner(self, t: float) -> None:
        b = self.course.banner
        if b is None:
            self._banner_until = None
            return
        if self._banner_until is None:  # loaded from disk: how much of the window is left?
            remaining = BANNER_S
            if self.wall is not None and b.at_wall is not None and b.until_wall is not None:
                now = self.wall()  # trusted UTC; None while unsynced -> the full window
                if now is not None and now >= b.at_wall - 1.0:  # a clock behind it: not trusted
                    remaining = b.until_wall - now
            remaining = min(BANNER_S, remaining)
            if remaining > 0:
                self._banner_until = t + remaining
                return
        elif t < self._banner_until:
            return
        self._save_quiet(self.course.model_copy(update={"banner": None}))

    def _abeam(self, lat: float, lon: float, idx: int, mark: Mark) -> bool:
        """Passed abeam of the mark relative to the incoming leg. At a turn sharper than
        HAIRPIN_DEG (Jabuka: in 203 deg, out 009/038 deg) abeam of the incoming leg is reached
        half a lap before the rounding is done (WR-01): the boat must ALSO be past the mark
        along the outgoing leg, i.e. round on the far side; otherwise the zone exit decides."""
        c = self.course
        prev = c.marks.get(c.seq[idx - 1].mark_id)
        if prev is None:
            return False
        bearing, dist = geo.bearing_distance(prev.lat, prev.lon, mark.lat, mark.lon)
        if dist < 1e-6:  # previous mark on the same spot: only the zone exit counts
            return False
        px, py = geo.to_local(lat, lon, mark.lat, mark.lon)
        ux, uy = geo.unit(bearing)
        if px * ux + py * uy <= 0.0:
            return False
        nxt = c.marks.get(c.seq[idx + 1].mark_id) if idx + 1 < len(c.seq) else None
        if nxt is None:
            return True
        out, out_dist = geo.bearing_distance(mark.lat, mark.lon, nxt.lat, nxt.lon)
        if out_dist < 1e-6:
            return True
        turn = math.degrees(math.remainder(out - bearing, 2 * math.pi))  # + right, - left
        if abs(turn) <= HAIRPIN_DEG:
            return True
        side = c.seq[idx].side
        if (side == "stbd" and turn < 0) or (side == "port" and turn > 0):
            return False  # rounded the long way (> 180 deg): only the zone exit counts
        vx, vy = geo.unit(out)
        return px * vx + py * vy > 0.0

    def _leg_dots(
        self, lat: float, lon: float, idx: int, mark: Mark
    ) -> tuple[float, float | None, float | None] | None:
        """(dot_in, dot_out, turn_deg) of P - M in local nm: along the incoming leg, along the
        outgoing leg and the course change (+ right, - left). None without an incoming leg (no
        previous mark, or on the same spot); dot_out and turn_deg None without an outgoing leg."""
        c = self.course
        prev = c.marks.get(c.seq[idx - 1].mark_id)
        if prev is None:
            return None
        bearing, dist = geo.bearing_distance(prev.lat, prev.lon, mark.lat, mark.lon)
        if dist < 1e-6:
            return None
        px, py = geo.to_local(lat, lon, mark.lat, mark.lon)
        ux, uy = geo.unit(bearing)
        dot_in = px * ux + py * uy
        nxt = c.marks.get(c.seq[idx + 1].mark_id) if idx + 1 < len(c.seq) else None
        if nxt is None:
            return dot_in, None, None
        out, out_dist = geo.bearing_distance(mark.lat, mark.lon, nxt.lat, nxt.lon)
        if out_dist < 1e-6:
            return dot_in, None, None
        turn = math.degrees(math.remainder(out - bearing, 2 * math.pi))
        vx, vy = geo.unit(out)
        return dot_in, px * vx + py * vy, turn

    def _past_mark(self, dots: tuple[float, float | None, float | None] | None) -> bool:
        """A zone exit counts only past the mark (G-4-R02, review repro on Plić Sestre: a tack
        away on the approach side used to advance the course). Past along the incoming leg; at
        a hairpin (turn > HAIRPIN_DEG, Jabuka) the approach side is also "past along the
        outgoing leg", so the boat must first have been past the mark along the incoming leg
        since entering the zone (the latch), the far-side evidence _abeam uses, and be past it
        along the outgoing leg now. No incoming leg to judge against: the zone exit alone, as
        before."""
        if dots is None:
            return True
        dot_in, dot_out, turn = dots
        if turn is None or dot_out is None or abs(turn) <= HAIRPIN_DEG:
            return dot_in > 0.0
        return self._beyond and dot_out > 0.0

    def on_tick(self, lat: float | None, lon: float | None, t_mono: float) -> None:
        """Record the boat position and run the rounding state machine (never raises)."""
        if lat is not None and lon is not None:
            self.boat = (lat, lon, t_mono)
        try:
            self._tick_banner(t_mono)
            if lat is not None and lon is not None:
                self._fsm(lat, lon, t_mono)
        except Exception:
            log.exception("course state machine failed")

    def _fsm(self, lat: float, lon: float, t: float) -> None:
        # IN-05: the debounce needs DEBOUNCE_S of continuous evidence; after a GPS gap the first
        # fix starts a fresh candidate instead of advancing on a single sample
        last, self._last_fsm_t = self._last_fsm_t, t
        if last is not None and not 0.0 <= t - last <= FSM_GAP_S:
            self._cand_since = None
        c = self.course
        idx = c.active_idx
        if c.finished or not 1 <= idx < len(c.seq):
            self._reset_fsm()
            return
        leg = c.seq[idx]
        mark = c.marks.get(leg.mark_id)
        if mark is None:
            return
        key = (idx, leg.mark_id)
        if key != self._fsm_key:
            self._reset_fsm()
            self._fsm_key = key
        _, d = geo.bearing_distance(lat, lon, mark.lat, mark.lon)
        zone = leg.radius_nm + ZONE_MARGIN_NM
        if c.suppress_idx is not None:
            if c.suppress_idx == idx and d <= zone:
                self._suppressed_in_zone = True
                return  # Annuler: not again until the boat has left this zone
            left_this_zone = c.suppress_idx == idx and self._suppressed_in_zone
            self._save_quiet(c.model_copy(update={"suppress_idx": None}))
            self._reset_fsm()
            self._fsm_key = key
            if d <= zone:
                return
            # CR-02: leaving the zone the boat was suppressed in (seen inside it after Annuler)
            # IS the rounding evidence: keep it, the usual 10 s "left the zone" debounce then
            # advances. Discarding it would leave the course stuck on the mark just rounded,
            # since the boat never re-enters that zone. Annuler tapped already outside the zone
            # still needs a fresh entry.
            if left_this_zone:
                self._entered = True
                # the stay inside the suppressed zone after Annuler is the rounding evidence: it
                # stands in for the incoming-leg latch, which the suppressed ticks never update
                self._beyond = True
        if idx >= self.last_idx:  # the finish
            if d <= max(leg.radius_nm, FINISH_MIN_NM):
                self._finish(t, idx, mark)
            return
        if d > max(GATE_NM, zone + GATE_OVER_ZONE_NM):  # a zone past 2 nm can still be left
            self._entered = False
            self._cand_since = None
            self._beyond = False
            return
        if d <= zone:
            self._entered = True
        if not self._entered:
            return
        dots = self._leg_dots(lat, lon, idx, mark)
        if dots is not None and dots[0] > 0.0:
            self._beyond = True
        if self._abeam(lat, lon, idx, mark) or (d > zone and self._past_mark(dots)):
            if self._cand_since is None:
                self._cand_since = t
            elif t - self._cand_since >= DEBOUNCE_S:
                self._advance(t, idx, mark)
        else:
            self._cand_since = None

    def _banner_wall(self) -> tuple[float | None, float | None]:
        if self.wall is None:
            return None, None
        try:
            now = self.wall()
            at = None if now is None else float(now)
        except Exception:
            return None, None
        if at is None:  # trusted UTC unknown: a restart offers the full window
            return None, None
        return at, at + BANNER_S

    def _advance(self, t: float, idx: int, mark: Mark) -> None:
        c = self.course
        new_idx = idx + 1
        nxt = c.marks[c.seq[new_idx].mark_id]
        at_wall, until_wall = self._banner_wall()
        banner = Banner(
            kind="advance",
            text=f"Marque suivante : {nxt.name} — Annuler",
            token=secrets.token_hex(8),
            prev_idx=idx,
            at_wall=at_wall,
            until_wall=until_wall,
        )
        new = self._copy(active_idx=new_idx, banner=banner, suppress_idx=None)
        self._commit_tick(
            new,
            {
                "type": "course_advance",
                "action": "advance",
                "from_idx": idx,
                "to_idx": new_idx,
                "mark_id": mark.id,
                "next_mark_id": nxt.id,
                "token": banner.token,
                "boat": [self.boat[0], self.boat[1]] if self.boat else None,
            },
        )
        self._banner_until = t + BANNER_S
        self._reset_fsm()

    def _finish(self, t: float, idx: int, mark: Mark) -> None:
        at_wall, until_wall = self._banner_wall()
        banner = Banner(
            kind="finish", text=f"ARRIVÉE — {mark.name}", at_wall=at_wall, until_wall=until_wall
        )
        new = self._copy(finished=True, banner=banner, suppress_idx=None)
        self._commit_tick(
            new, {"type": "course_advance", "action": "finish", "idx": idx, "mark_id": mark.id}
        )
        self._banner_until = t + BANNER_S
        self._reset_fsm()

    def undo(self, token: str, t_mono: float) -> dict:
        """Annuler: back to the previous mark, which then cannot re-fire until the boat has left
        its zone. Raises BannerGone after the window or with a wrong token."""
        self._tick_banner(t_mono)
        b = self.course.banner
        if (
            b is None
            or b.kind != "advance"
            or b.token is None
            or not isinstance(token, str)
            or not hmac.compare_digest(token.encode(), b.token.encode())
            or self._banner_until is None
            or t_mono >= self._banner_until
            or b.prev_idx is None
            or not 1 <= b.prev_idx < len(self.course.seq)
        ):
            raise BannerGone("nothing to undo")
        prev = b.prev_idx
        new = self._copy(active_idx=prev, finished=False, banner=None, suppress_idx=prev)
        self._commit(
            new,
            None,
            {"type": "course_undo", "action": "undo", "to_idx": prev, "token": b.token},
        )
        self._reset_fsm()
        return self.to_api()

    # -- targets -----------------------------------------------------------------------------
    def active_target(self) -> ActiveTarget | None:
        c = self.course
        if not 1 <= c.active_idx < len(c.seq) or c.finished:
            return None
        leg = c.seq[c.active_idx]
        mark = c.marks.get(leg.mark_id)
        if mark is None:
            return None
        prev = c.marks.get(c.seq[c.active_idx - 1].mark_id)
        bearing, dist = (0.0, 0.0)
        if prev is not None:
            bearing, dist = geo.bearing_distance(prev.lat, prev.lon, mark.lat, mark.lon)
        if dist < 1e-6 and self.boat is not None:  # start on the mark: use boat -> mark
            bearing, dist = geo.bearing_distance(self.boat[0], self.boat[1], mark.lat, mark.lon)
        if leg.side == "port":
            a_lat, a_lon = geo.offset(mark.lat, mark.lon, bearing + math.pi / 2, leg.radius_nm)
        elif leg.side == "stbd":
            a_lat, a_lon = geo.offset(mark.lat, mark.lon, bearing - math.pi / 2, leg.radius_nm)
        else:
            a_lat, a_lon = mark.lat, mark.lon
        return ActiveTarget(
            mark=mark,
            idx=c.active_idx,
            side=leg.side,
            radius_nm=leg.radius_nm,
            anchor_lat=a_lat,
            anchor_lon=a_lon,
            leg_bearing=bearing,
        )

    # -- views -------------------------------------------------------------------------------
    def status(self) -> dict:
        """The "course" block of the nav message."""
        c = self.course
        banner = None
        if c.banner is not None:
            until = self._banner_until if c.banner.kind == "advance" else None
            banner = {
                "text": c.banner.text,
                "token": c.banner.token,
                "undo_until_s": round(until, 3) if until is not None else None,
                "kind": c.banner.kind,
            }
        return {
            "template": c.template,
            "active_idx": c.active_idx,
            "finish_idx": c.finish_idx,
            "finished": c.finished,
            "sides_confirmed": c.sides_confirmed,
            "banner": banner,
        }

    def to_api(self) -> dict:
        """GET /api/course JSON."""
        c = self.course
        return {
            "version": self.version,
            "template": c.template,
            "sides_confirmed": c.sides_confirmed,
            "marks": {
                k: {
                    "id": m.id,
                    "name": m.name,
                    "lat": m.lat,
                    "lon": m.lon,
                    "radius_nm": m.radius_nm,
                    "kind": m.kind,
                    "builtin": m.builtin,
                    "moved": k in c.overrides,
                }
                for k, m in c.marks.items()
            },
            "seq": [leg.model_dump() for leg in c.seq],
            "active_idx": c.active_idx,
            "finish_idx": c.finish_idx,
            "finished": c.finished,
        }
