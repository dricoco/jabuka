"""REST seams for the course (CRSE-01..05): GET, one-tap Course A/B select, next/prev, and the
editing routes of plan 02-04 (marks, legs, reorder, "Finir ici", activate, confirm sides, Annuler).

Every mutating body carries base_version: a stale one gets 409 with the current course JSON (the
tablet refetches). Bad indices / values get 422, an unknown mark 404, an expired or unknown
Annuler token 410, a disk failure 503 (nothing changed). Each change returns the course JSON
(version bumped) and publishes a fresh nav message so every tablet sees it within one round trip.
Handlers are ``async def``: they run on the event loop, serialized with the tick that drives the
rounding state machine (no threadpool race on CourseStore).

Event lines (events log, fsync'd): course_edit for every edit, course_advance / course_undo from the
state machine, written through CourseStore.on_event which this router installs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jabuka.nav.course import MAX_SEQ, NAME_MAX, BannerGone, UnknownMark, clean_name
from jabuka.nav.settings import VersionConflict

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

log = logging.getLogger("jabuka.core.course")

Side = Literal["port", "stbd", "none"]


class SelectIn(BaseModel):
    template: Literal["A", "B"]
    base_version: int | None = None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarkIn(_Strict):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    lat: float = Field(ge=42.0, le=45.0)
    lon: float = Field(ge=14.0, le=17.0)
    radius_nm: float = Field(0.05, ge=0.0, le=3.0)
    side: Side = "none"
    insert_at: int | None = Field(None, ge=1, le=MAX_SEQ)
    base_version: int


class MarkPatch(_Strict):
    name: str | None = Field(None, min_length=1, max_length=NAME_MAX)
    lat: float | None = Field(None, ge=42.0, le=45.0)
    lon: float | None = Field(None, ge=14.0, le=17.0)
    base_version: int


class LegPatch(_Strict):
    side: Side | None = None
    radius_nm: float | None = Field(None, ge=0.0, le=3.0)
    base_version: int


class ReorderIn(_Strict):
    from_idx: int = Field(ge=0, le=MAX_SEQ)
    to_idx: int = Field(ge=0, le=MAX_SEQ)
    base_version: int


class FinishIn(_Strict):
    idx: int | None = Field(ge=0, le=MAX_SEQ)
    base_version: int


class ActivateIn(_Strict):
    idx: int = Field(ge=0, le=MAX_SEQ)
    base_version: int


class VersionIn(_Strict):
    base_version: int


class UndoIn(_Strict):
    token: str = Field(min_length=1, max_length=64)


def _clean(name: str | None) -> str | None:
    """Same rule as jabuka.core.web.strip_control (not imported: web imports this module)."""
    return None if name is None else clean_name(name)


def router(ctx: CoreContext) -> APIRouter:
    r = APIRouter()
    course = ctx.nav.course

    def write_event(rec: dict) -> None:
        if ctx.events_log is None:
            return
        line = {
            **rec,
            "t_mono": ctx.clock.monotonic(),
            "t_wall": ctx.clock.wall(),
            "utc": ctx.clock.status().get("utc"),
        }
        try:
            ctx.events_log.write_json(line, fsync_now=True)
        except (OSError, ValueError):
            ctx.stats["events_errors"] = ctx.stats.get("events_errors", 0) + 1
            log.exception("course event write failed")

    course.on_event = write_event
    course.wall = ctx.clock.wall

    def mutate(fn: Callable[[], dict]) -> dict | JSONResponse:
        try:
            out = fn()
        except VersionConflict as e:
            return JSONResponse(e.current, status_code=409)
        except UnknownMark as e:
            return JSONResponse({"detail": f"unknown mark {e}"}, status_code=404)
        except BannerGone:
            return JSONResponse({"detail": "Annuler expiré"}, status_code=410)
        except OSError:  # disk full / read-only: nothing changed
            return JSONResponse({"ok": False, "error": "course write failed"}, status_code=503)
        except ValueError as e:  # CourseError, pydantic ValidationError
            return JSONResponse({"detail": str(e)[:300]}, status_code=422)
        ctx.publish_nav()
        return out

    @r.get("/api/course")
    async def api_course() -> dict:
        return course.to_api()

    @r.post("/api/course/select", response_model=None)
    async def api_course_select(body: SelectIn) -> dict | JSONResponse:
        return mutate(lambda: course.select(body.template, body.base_version))

    @r.post("/api/course/next", response_model=None)
    async def api_course_next() -> dict | JSONResponse:
        return mutate(course.next)

    @r.post("/api/course/prev", response_model=None)
    async def api_course_prev() -> dict | JSONResponse:
        return mutate(course.prev)

    # -- editing (plan 02-04) ----------------------------------------------------------------
    @r.post("/api/marks", response_model=None)
    async def api_mark_add(body: MarkIn) -> dict | JSONResponse:
        return mutate(
            lambda: course.add_mark(
                _clean(body.name) or "",
                body.lat,
                body.lon,
                body.radius_nm,
                body.side,
                body.insert_at,
                body.base_version,
            )
        )

    @r.patch("/api/marks/{mark_id}", response_model=None)
    async def api_mark_patch(mark_id: str, body: MarkPatch) -> dict | JSONResponse:
        if len(mark_id) > 40:
            return JSONResponse({"detail": "unknown mark"}, status_code=404)
        return mutate(
            lambda: course.edit_mark(
                mark_id,
                name=_clean(body.name),
                lat=body.lat,
                lon=body.lon,
                base_version=body.base_version,
            )
        )

    @r.patch("/api/course/legs/{idx}", response_model=None)
    async def api_leg_patch(idx: int, body: LegPatch) -> dict | JSONResponse:
        return mutate(
            lambda: course.set_leg(
                idx, side=body.side, radius_nm=body.radius_nm, base_version=body.base_version
            )
        )

    @r.delete("/api/course/legs/{idx}", response_model=None)
    async def api_leg_delete(idx: int, base_version: int = Query(...)) -> dict | JSONResponse:
        return mutate(lambda: course.delete_leg(idx, base_version))

    @r.post("/api/course/reorder", response_model=None)
    async def api_reorder(body: ReorderIn) -> dict | JSONResponse:
        return mutate(lambda: course.reorder(body.from_idx, body.to_idx, body.base_version))

    @r.post("/api/course/finish", response_model=None)
    async def api_finish(body: FinishIn) -> dict | JSONResponse:
        return mutate(lambda: course.set_finish(body.idx, body.base_version))

    @r.post("/api/course/activate", response_model=None)
    async def api_activate(body: ActivateIn) -> dict | JSONResponse:
        return mutate(lambda: course.activate(body.idx, body.base_version))

    @r.post("/api/course/confirm-sides", response_model=None)
    async def api_confirm_sides(body: VersionIn) -> dict | JSONResponse:
        return mutate(lambda: course.confirm_sides(body.base_version))

    @r.post("/api/course/undo", response_model=None)
    async def api_undo(body: UndoIn) -> dict | JSONResponse:
        return mutate(lambda: course.undo(body.token, ctx.clock.monotonic()))

    return r
