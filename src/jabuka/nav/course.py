"""Mark library, Course A/B templates and the persisted active course (CRSE-01/03/05).

<data-dir>/course.json = {"version": int, "course": Course}. Every change is written with
atomic_write_json and bumps the version, so every tablet re-fetches it (Pitfall 10). A torn or
invalid file falls back to NAME.bak, then to Course A with an alert.

Index 0 of the sequence is the start and is never active; select() puts the first rounding mark
(index 1) active. The anchor of the active mark is the point at radius_nm on the rounding side:
A = M + R * u(leg_bearing + 90 deg) for a mark left to port, - 90 deg for starboard, M itself for
side "none" (RESEARCH Pattern 4, Pitfall 17). leg_bearing is previous mark -> active mark.

Plan 02-04 adds editing, the rounding state machine (inside on_tick), the banner and "Finir ici".
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jabuka.common.atomicio import atomic_write_json, load_json_with_bak
from jabuka.nav import geo
from jabuka.nav.settings import VersionConflict

COURSE_FILE = "course.json"
MAX_MARKS = 30
MAX_SEQ = 30

Side = Literal["port", "stbd", "none"]


class Mark(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=40)
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


class Course(BaseModel):
    model_config = ConfigDict(extra="ignore")

    template: Literal["A", "B", "custom"] = "A"
    marks: dict[str, Mark] = Field(default_factory=dict, max_length=MAX_MARKS)
    seq: list[Leg] = Field(default_factory=list, max_length=MAX_SEQ)
    active_idx: int = Field(1, ge=0)
    finish_idx: int | None = None
    finished: bool = False
    sides_confirmed: bool = False


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


def course_from_template(library: dict[str, Any], template: str) -> Course:
    marks = {m["id"]: Mark(**m, builtin=True) for m in library["marks"]}
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
    )


def _valid(course: Course) -> bool:
    if len(course.seq) < 2 or any(leg.mark_id not in course.marks for leg in course.seq):
        return False
    last = len(course.seq) - 1
    if course.finish_idx is not None and not 1 <= course.finish_idx <= last:
        return False
    return 1 <= course.active_idx <= last


class CourseStore:
    def __init__(self, data_dir: str | Path, library: dict[str, Any] | None = None) -> None:
        self.path = Path(data_dir) / COURSE_FILE
        self.library = library if library is not None else load_library()
        self.alerts: list[str] = []
        self.version = 0
        self.course = course_from_template(self.library, "A")
        self.boat: tuple[float, float, float] | None = None  # (lat, lon, t_mono)
        raw = load_json_with_bak(self.path, None)
        if raw is not None:
            try:
                if not isinstance(raw, dict):
                    raise ValueError("not an object")
                course = Course.model_validate(raw.get("course"))
                if not _valid(course):
                    raise ValueError("inconsistent course")
                self.course = course
                v = raw.get("version", 0)
                self.version = v if isinstance(v, int) and not isinstance(v, bool) else 0
            except (ValidationError, ValueError):
                self.alerts.append("Parcours illisible : Parcours A par défaut")

    # -- accessors ---------------------------------------------------------------------------
    @property
    def marks(self) -> dict[str, Mark]:
        return self.course.marks

    @property
    def last_idx(self) -> int:
        c = self.course
        return c.finish_idx if c.finish_idx is not None else len(c.seq) - 1

    # -- persistence -------------------------------------------------------------------------
    def _commit(self, course: Course, base_version: int | None = None) -> None:
        if base_version is not None and base_version != self.version:
            raise VersionConflict(self.version, self.to_api())
        version = self.version + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, {"version": version, "course": course.model_dump()})
        self.course = course
        self.version = version

    # -- commands ----------------------------------------------------------------------------
    def select(self, template: str, base_version: int | None = None) -> dict:
        if template not in self.library.get("templates", {}):
            raise ValueError(f"unknown course template {template!r}")
        self._commit(course_from_template(self.library, template), base_version)
        return self.to_api()

    def _step(self, delta: int) -> dict:
        c = self.course
        idx = min(max(1, c.active_idx + delta), self.last_idx)
        if idx != c.active_idx:
            self._commit(c.model_copy(update={"active_idx": idx, "finished": False}))
        return self.to_api()

    def next(self) -> dict:
        return self._step(+1)

    def prev(self) -> dict:
        return self._step(-1)

    # -- per tick ----------------------------------------------------------------------------
    def on_tick(self, lat: float | None, lon: float | None, t_mono: float) -> None:
        """Record the boat position (plan 02-04 adds the rounding state machine here)."""
        if lat is not None and lon is not None:
            self.boat = (lat, lon, t_mono)

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
        return {
            "template": c.template,
            "active_idx": c.active_idx,
            "finish_idx": c.finish_idx,
            "finished": c.finished,
            "sides_confirmed": c.sides_confirmed,
            "banner": None,
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
                }
                for k, m in c.marks.items()
            },
            "seq": [leg.model_dump() for leg in c.seq],
            "active_idx": c.active_idx,
            "finish_idx": c.finish_idx,
        }
