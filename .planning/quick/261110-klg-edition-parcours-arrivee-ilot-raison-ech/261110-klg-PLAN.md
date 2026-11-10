---
phase: quick-261110-klg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/jabuka/route/rounding.py
  - tests/route/test_rounding.py
  - tests/route/test_course_routes.py
  - docs/ROUTING.md
  - src/jabuka/core/router_service.py
  - tests/routing/test_route_expiry.py
  - src/jabuka/web/static/i18n.js
  - tests/test_i18n.py
  - docs/I18N-SL-REVIEW.md
  - src/jabuka/web/static/carte.js
  - tests/test_carte_logic.py
  - tests/ui/test_carte.py
autonomous: true
requirements: [ROUT-01, ROUT-11, ROUT-02, CRSE-02, CRSE-04]

estimate:
  tokens: 130000
  raw_tokens: 130000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Routing a course whose LAST mark has its centre on an islet (Blitvenica, side stbd or none) returns ok with a last leg for that mark: the target is a point of its radius circle on the approach side (bearing mark -> previous mark; the boat only when the first remaining mark has no previous mark), pushed outward to clear water like _push; the reason 'cible dans la terre, aucune eau libre à 1 nm : Blitvenica' no longer occurs"
    - "A last mark with side stbd/port also targets its radius circle on the approach side even when its centre is clear water; a last mark with side 'none' whose centre is clear water (Vodice start-finish) still targets the exact centre (regression), so Course A/B routes are unchanged"
    - "Intermediate marks, rounding waypoints and the rounding FSM in src/jabuka/nav/course.py are unchanged (no edit to course.py, existing test_rounding / test_course_routes cases pass untouched)"
    - "After a course edit the withdrawn route reads 'parcours modifié : recalcul en cours' while no cycle for the CURRENT course version has failed (first cycle still computing, or only older-version failures); once a cycle for the current course version failed it reads 'parcours modifié : <that failure>' (e.g. 'parcours modifié : cible dans la terre, aucune eau libre à 1 nm : Blitvenica')"
    - "EN and SL tablets translate 'parcours modifié : <reason>' prefix AND inner reason (EN 'course changed: target on land, no open water within 1 nm: Blitvenica', SL 'proga spremenjena: cilj na kopnem, ni proste vode v 1 nm: Blitvenica') and the rounding failure 'impossible de contourner …'; FR text is untouched; docs/I18N-SL-REVIEW.md is regenerated and in sync"
    - "'À la fin' in the add-mark sheet inserts before the last mark only when it is a real finish (course.finish_idx set, or the last leg's mark kind is 'start-finish' at index >= 1); otherwise it appends after the last mark (insert_at = seq.length)"
    - "bash scripts/check.sh is green (ruff check, ruff format --check, pytest on .venv and .venv313)"
  artifacts:
    - path: src/jabuka/route/rounding.py
      provides: "expand(): last-mark finish waypoint on the radius circle (approach side, pushed to clear water) for stbd/port or non-clear centres; centre kept for side none + clear centre"
      contains: "def expand"
    - path: src/jabuka/core/router_service.py
      provides: "course version of the last failed cycle (_fail_course_version) and _withdrawal returning the real failure for the current course version"
      contains: "parcours modifié : {self._last_fail}"
    - path: src/jabuka/web/static/i18n.js
      provides: "srv.rOutCourseWhy and srv.rCannotRound in FR/EN/SL + SRV_RULES regexes"
      contains: "rOutCourseWhy"
    - path: src/jabuka/web/static/carte.js
      provides: "exported pure endInsertAt(course) used by openAddSheet for 'À la fin'"
      contains: "export function endInsertAt"
    - path: tests/route/test_rounding.py
      provides: "unit regressions: islet last mark (stbd / none / radius 0 push), buoy last mark with side, Vodice centre kept with the mask, previous-mark vs boat bearing"
      contains: "def test_last_islet_mark"
    - path: tests/route/test_course_routes.py
      provides: "real-router routes ending on Blitvenica (short course and Course A without its finish)"
      contains: "def test_course_ending_on_an_islet"
    - path: tests/routing/test_route_expiry.py
      provides: "course-change reason: recalcul en cours while computing / older failure, real failure for the current version"
      contains: "def test_course_change_reason"
    - path: tests/test_carte_logic.py
      provides: "node tests of carte.js endInsertAt"
      contains: "endInsertAt"
    - path: tests/ui/test_carte.py
      provides: "Playwright: 'À la fin' before the Vodice finish, then after the last mark once the finish is deleted"
      contains: "def test_add_at_end"
  key_links:
    - from: src/jabuka/route/isochrone.py
      to: src/jabuka/route/rounding.py
      via: "_waypoints -> expand(req.prev_mark, req.marks, ...); _route snaps each waypoint with _snap_target (mask.snap_clear) — a clear finish point is returned unmoved"
      pattern: "expand\\(req.prev_mark"
    - from: src/jabuka/core/router_service.py
      to: src/jabuka/core/router_service.py
      via: "_on_outcome passes course_version to _failed/_invalid; _withdrawal compares _fail_course_version with self.nav.course.version"
      pattern: "_fail_course_version"
    - from: src/jabuka/web/static/i18n.js
      to: src/jabuka/core/router_service.py
      via: "SRV_RULES /^parcours modifié : (.+)$/s -> srv.rOutCourseWhy with the inner reason translated recursively (*r); SRV_EXACT still maps the exact 'parcours modifié : recalcul en cours'"
      pattern: "parcours modifié : \\(\\.\\+\\)"
    - from: src/jabuka/web/static/carte.js
      to: src/jabuka/nav/course.py
      via: "openAddSheet POST /api/marks insert_at = endInsertAt(course); add_mark accepts 1 <= insert_at <= len(seq) (len(seq) = append)"
      pattern: "endInsertAt\\(course\\)"
---

<objective>
Fix three course-editing bugs reproduced on the local demo (course vodice, plic-sestre, m1, jabuka,
m2, blitvenica after the user deleted the Vodice finish and added M2 "à la fin"):

1. Routing: the LAST mark becomes a "finish" waypoint at the mark CENTRE; Blitvenica's centre is on
   the islet, so isochrone._snap_target fails ("cible dans la terre, aucune eau libre à 1 nm :
   Blitvenica") and no route is ever produced. Target a clear point of the mark's radius circle on
   the approach side instead (rounding last marks and non-clear centres); keep the Vodice
   start-finish centre exactly as today.
2. Router reason: after the course change the helm reads "parcours modifié : recalcul en cours"
   forever although every cycle fails. Show the real failure once a cycle for the current course
   version has failed (FR/EN/SL).
3. Carte: "À la fin" always inserted before the last mark (assumed to be the finish), so M2 landed
   before Blitvenica. Insert before the last mark only when it is a real finish, else append.

Purpose: the helm must get a route again after a mid-race course edit, and see why when it cannot.
Output: rounding.py, router_service.py, i18n.js, carte.js fixes + regression tests for each bug.
</objective>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@src/jabuka/route/rounding.py
@tests/route/test_rounding.py
@tests/routing/test_route_expiry.py

<interfaces>
Facts observed in the code at planning time (use them; do not re-derive):

Repo rules for this task: stage by explicit paths only (never git add -A / stash / reset / clean /
branch switch); never stage docs/I18N-SL-REVIEW.md.bak (untracked, leave it alone); never touch
cad/, stl/, hardware/, docs/SOAK.md, nor the quick-task table in .planning/STATE.md; do not push;
no deploy; do not touch the demo on port 8080 nor the Pi (a soak runs on it). One commit per task,
messages in the repo style (e.g. "fix(quick-261110-klg): …", French description), each ending with
the line "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". Targeted runs:
.venv313/bin/pytest. Full gate: bash scripts/check.sh (ruff check + ruff format --check on src and
tests, pytest on .venv and .venv313). tests/ui/test_i18n_ui.py::test_switch_to_slovenian_then_english_persists_and_fits
is a known flaky race: if it alone fails, rerun it alone and record the rerun in the SUMMARY.

src/jabuka/route/rounding.py (158 lines):
- expand(prev, marks, boat_lat, boat_lon, mask=None, notes=None) -> list[Waypoint]. frame =
  mask.frame if mask else DEFAULT_FRAME. In the loop: prev_pos = previous mark (prev for i == 0
  when given, else the boat), next_pos = None for the last mark. _arc(...) returns None when
  side is not port/stbd OR next_pos is None, so the LAST mark always takes the branch at line
  ~130-132 that appends Waypoint(m.lat, m.lon, m.mark_id, "finish" if i == n - 1 else "mark", i)
  — the centre.
- Helpers: _bearing(frame, a, b) -> degrees or None when a == b; _at(frame, mark, bearing, r);
  _clear(mask, frame, lat, lon) (True when mask is None; else mask.points_clear = DILATED mask);
  _push(mask, frame, mark, bearing, notes): point at mark.radius_nm on that bearing, if not clear
  pushed outward in 0.02 nm steps up to radius + 0.5 nm with the note "point de contournement de
  {name} repoussé à {r} nm (relèvement {b}°)", else ValueError "impossible de contourner {name} :
  aucun point en eau libre à moins de {r} nm au relèvement {b}°".
- Waypoint kind "finish" is consumed NOWHERE in src (grep): only
  tests/route/test_rounding.py::test_finish_and_side_none_are_the_mark_itself asserts it.
- isochrone._waypoints wraps expand's ValueError into RouteFailure(str(exc)); isochrone._route
  calls _snap_target(ctx, tx, ty, mark.name) on EVERY waypoint: mask.snap_clear(x, y, 1.0)
  returns (x, y, False) for a clear point, None when no clear cell is reachable by a segment that
  does not cross RAW land — always None from a centre on an islet -> RouteFailure "cible dans la
  terre, aucune eau libre à 1 nm : {name}".
- Mask facts (tests/fixtures/route/landmask_race_25m.npz, checked at planning time): Vodice
  (43.75, 15.78) clear (dilated and raw) -> snap unmoved; Blitvenica (43.62508, 15.57476, radius
  0.55) raw land, snap None; Jabuka and Mulo centres raw land; Plić Sestre centre blocked in the
  dilated mask but raw water. Blitvenica approach points at 0.55 nm are clear without push from
  Plić Sestre (bearing ~70.9°) and from Jabuka (~188.8°); with radius 0 the push lands at 0.12 nm
  with a note naming Blitvenica. The real packs var/demo/racepack and var/racepack (read-only
  check) agree: Vodice clear, Blitvenica raw land.
- tests/route/conftest.py fixtures: mask (LandMask of the fixture), course(key) -> (start
  CourseMark, remaining marks tuple); course("A") = vodice(none) then (plic-sestre stbd 0.3,
  jabuka stbd 0.6, blitvenica stbd 0.55, vodice none 0.15); env_factory(wind, geofields=...),
  uniform_wind(twd_deg, tws_kn), course_geofields (keyed by (lat, lon, radius): radius changes
  fall back to an on-demand field), make_request(lat, lon, marks, **overrides).
  test_course_routes.py: route(req, env) never raises; r.ok, r.reason, r.legs (LegResult mark_id,
  eta, lat, lon), r.path (PathPoint t, lat, lon, …), r.start_in_margin; mask.validate_polyline.

src/jabuka/core/router_service.py:
- REASON_OUT_COURSE = "parcours modifié : recalcul en cours" (line 104).
- __init__: self._last_fail: str | None = None (line 246); self._fail_streak in __init__ ~280.
- _maybe_request sets self.last_request = req (~line 603) before self._submit(req, ...).
  _submit spawns self._run(req, forced, reasons, self.nav.course.version); _run -> _on_outcome(req,
  out, forced, reasons, course_version).
- _on_outcome failure calls: self._failed(req, f"{out.status}: {out.error}" if out.error else
  out.status) (pool status not ok); not opt.ok -> self._invalid(reason, req) for FAIL_LAND else
  self._failed(req, reason); not opt.valid / no path -> self._invalid(opt.reason or "route non
  validée", req). Stale-version SUCCESS is dropped ("superseded") but stale-version FAILURES are
  recorded like current ones (this is why _last_fail alone cannot tell them apart). Success sets
  self._last_fail = None.
- _failed(req, reason) sets _last_fail and _fail_streak; _invalid(reason, req=None) calls _failed
  when req is given, else sets _last_fail. _recycle_pool calls self._failed(self.last_request,
  self._last_fail) for the cancelled in-flight cycle. _pool_alarm sets _last_fail directly.
- _withdrawal(now, f): ... if self._course_changed(r, f): return REASON_OUT_COURSE (line ~1057).
- tests/test_i18n.py core_texts() collects every module-level REASON_* constant and every return
  value of functions whose name contains "withdraw" as tablet UI texts (attribute f-string parts
  render as "7"), and asserts EN/SL translations differ from FR with no leftover {placeholder}.
  So: do NOT add a REASON_* constant holding a bare prefix like "parcours modifié" (it would need
  its own exact translation) nor a "{r}" template constant (placeholder check). Use an inline
  f-string in _withdrawal, like the existing f"{REASON_OUT_FAIL} : {self._last_fail}".

tests/routing (conftest FakePool / RoutingCore): fake_pool.script = lambda creq: PoolOutcome(...);
fake_pool.hold = True keeps a job running (release with False); core.call(fn) runs fn on the
loop thread; core.router is the RouterService (core.call(lambda: core.router.force("test"))
forces a cycle at the next tick); core.settle() raises when the router stays busy (use
_step(core, pos, settle=False) while hold is True). Existing test_course_change_withdraws_the_route
scripts a crashing pool BEFORE POST /api/course/next and asserts reason == "parcours modifié :
recalcul en cours" after 120 steps — every failing cycle there runs for the NEW course version, so
that assertion encodes bug 2 and must become "parcours modifié : crashed: BrokenProcessPool".

src/jabuka/web/static/i18n.js: FR dict "srv.rOutCourse" line 457, "srv.rTargetOnLand" line 492;
EN 806 / 841; SL 1158 / 1193. SRV_EXACT (built from FR values of a key list, ~1265-1297) is
checked BEFORE SRV_RULES, so the exact "parcours modifié : recalcul en cours" keeps mapping to
rOutCourse. SRV_RULES (~1300-1327): [regex, key, names], a name starting with "*" is translated
recursively (trRec). Existing style: EN "course changed: recomputing", SL "proga spremenjena:
ponovni izračun", SL "cilj na kopnem, ni proste vode v {n} nm: {name}". The review sheet:
.venv313/bin/python -m jabuka.tools.i18n_review (rewrite) / --check;
tests/test_i18n.py::test_the_slovenian_review_sheet_is_up_to_date compares it.

src/jabuka/web/static/carte.js: export function lastIdx(course) { return course.finish_idx ??
course.seq.length - 1; } (line 99, also used for list tags / legFor — leave it). openAddSheet
(line ~597) post(): comment "à la fin = before the finish" then insertAt = st.pos === "end" ?
lastIdx(course) : null, sent as insert_at. course JSON (CourseService.to_api): marks{id: {kind:
"start-finish" | "mark", builtin, …}}, seq[{mark_id, side, radius_nm}], active_idx, finish_idx,
finished. Node imports carte.js cleanly (checked: exports lastIdx, circle, courseGeo, bannerView…).
src/jabuka/nav/course.py add_mark: at = active_idx + 1 if insert_at is None else insert_at;
CourseError unless 1 <= at <= len(seq) (len(seq) appends); course_api insert_at Field(ge=1,
le=MAX_SEQ). DELETE /api/course/legs/{idx}?base_version=N deletes a leg. tests/test_route_logic.py
shows the node-import test pattern (js(expr) through node --input-type=module). tests/ui/test_carte.py:
open_carte(page) (5 legs, template A), xy(pg, lat, lon), EARTH_JS land probe, WATER = (43.680,
15.800), course(env) -> /api/course JSON, segmented buttons "#carte-sheet [data-name=pos]
button[data-value=end]", add button "#mark-add", page.bad_responses.
</interfaces>
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1 (tracer): a course ending on an islet mark routes end-to-end to a clear point of its circle</name>
  <files>src/jabuka/route/rounding.py, tests/route/test_rounding.py, tests/route/test_course_routes.py, docs/ROUTING.md</files>
  <behavior>
    - expand(start, (plic stbd, blitvenica stbd 0.55), boat at start, mask): last waypoint kind "finish", mark_id "blitvenica", mark_index 1, clear in mask.points_clear, mask.snap_clear(x, y, 1.0) returns it unmoved, distance from the centre within [0.55, 0.55 + 0.5] nm, bearing from Blitvenica within 1.5° of the bearing Blitvenica -> Plić Sestre (~70.9°).
    - Same with blitvenica side "none" radius 0.55 (centre on land) -> same circle point; side "none" radius 0.0 -> pushed point (clear, distance > 0) and a note containing "Blitvenica".
    - A clear-water buoy last mark with a side (CourseMark("m2", "M2", 43.751111, 15.778849, "stbd", 0.1)) after Plić Sestre, no mask: finish at 0.1 nm (abs 1e-6) on the bearing M2 -> Plić Sestre.
    - Regression: expand(start, course A marks, …, mask, notes) -> last waypoint == (Vodice lat, lon) exactly, kind "finish", no note mentions Vodice; the existing test_finish_and_side_none_are_the_mark_itself and all other test_rounding cases pass untouched.
    - Single remaining last mark: expand(prev=plic, (blitvenica,), boat elsewhere) uses the bearing to Plić Sestre; expand(None, (blitvenica,), boat) uses the bearing to the boat.
    - Real router (test_course_routes.py), uniform SW 12 kn, prev_mark = Vodice start, tack0 1, course_geofields, parametrized: (Plić Sestre stbd, Blitvenica stbd), (Plić Sestre stbd, Blitvenica none), and Course A without its finish (Plić Sestre, Jabuka, Blitvenica stbd = the reported shape): r.ok (message r.reason), legs mark ids match the marks, shipped polyline valid against the mask (skip segment 0 when start_in_margin), r.path[-1] and r.legs[-1] within 0.05 nm of expand(start, marks, start.lat, start.lon, mask)[-1], no "cible dans la terre" in r.reason or r.notes.
  </behavior>
  <action>
    RED first: add the tests above (test_last_islet_mark_targets_its_circle_on_the_approach_side parametrized over (side, radius) in tests/route/test_rounding.py, plus the buoy, Vodice-with-mask, and previous-mark-vs-boat tests; test_course_ending_on_an_islet_routes_to_its_circle in tests/route/test_course_routes.py, importing expand from jabuka.route.rounding with the same noqa E402 guard as the other imports). Compute bearings/distances in the frame expand uses (mask.frame when a mask is passed; the module's DEFAULT_FRAME helpers are fine without a mask). Run them and confirm they fail (unit: centre instead of circle point; real router: ok False with "cible dans la terre … Blitvenica").

    GREEN (fix 1 of the task): in expand(), in the branch where _arc returns None, when the mark is the last one (i == n - 1) AND (m.side is "port" or "stbd" OR not _clear(mask, frame, m.lat, m.lon)): bearing = _bearing(frame, (m.lat, m.lon), prev_pos); if that is None (previous position on the mark) fall back to the bearing to (boat_lat, boat_lon), then to 0.0 (use explicit None checks: 0.0 is a valid bearing). Place the waypoint with the existing _push(mask, frame, m, bearing, notes) — same outward push, same note, same ValueError naming the mark (isochrone turns it into a RouteFailure) — and append Waypoint(lat, lon, m.mark_id, "finish", i). Every other case keeps the current append byte-for-byte (side "none" + clear centre -> centre "finish"; non-last side "none" -> centre "mark"). prev_pos is the variable the loop already computes: the previous MARK (stable between reruns, as the module docstring requires), the boat only when the first remaining mark has no previous mark — this is how "bearing mark -> previous mark, or boat for the first remaining mark" is implemented. Do not touch _arc, rounding waypoints of intermediate marks, _not_passed, isochrone.py, or src/jabuka/nav/course.py (the rounding FSM is separate). Update the module docstring bullet "Side 'none' or the last mark of the course: one waypoint at the mark itself" to describe: side none -> the mark itself; the last mark -> the mark itself when side none and its centre is clear water, else one "finish" waypoint on its radius circle on the approach side (towards the previous mark, the boat when there is none), pushed outward like rounding waypoints.

    docs/ROUTING.md: after the sentence ending "…plus an entry waypoint, no loop)." in the routing paragraph (~line 127-131), add one English sentence: the last mark is targeted at its centre when it is a plain finish point in open water (Vodice), otherwise (rounding side, or centre on land such as Blitvenica) at the point of its radius circle facing the previous mark, pushed into open water.

    Commit (explicit paths): src/jabuka/route/rounding.py tests/route/test_rounding.py tests/route/test_course_routes.py docs/ROUTING.md.
  </action>
  <verify>
    <automated>.venv313/bin/pytest -q tests/route/test_rounding.py tests/route/test_course_routes.py tests/route/test_stay_route.py tests/route/test_forced_cost.py</automated>
  </verify>
  <done>The new unit and real-router tests pass (they failed before the fix with the centre target / "cible dans la terre … Blitvenica"); every pre-existing test in those files passes unchanged; Vodice-finish courses produce the same last waypoint as before; commit made with explicit paths.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: withdrawn-route reason shows the real failure for the current course version (FR/EN/SL)</name>
  <files>src/jabuka/core/router_service.py, tests/routing/test_route_expiry.py, src/jabuka/web/static/i18n.js, tests/test_i18n.py, docs/I18N-SL-REVIEW.md</files>
  <behavior>
    - test_course_change_withdraws_the_route (existing, crashing pool for every cycle after POST /api/course/next): reason == "parcours modifié : crashed: BrokenProcessPool" (assertion updated: the old value encoded the bug).
    - New test_course_change_reason_while_computing_then_failed: after _start, script a timeout and force one cycle (core.call(lambda: core.router.force("test")); _step) so _last_fail holds an OLD-version failure; then fake_pool.hold = True, script a crash, POST /api/course/next, a few _step(..., settle=False): route withdrawn with reason exactly "parcours modifié : recalcul en cours" (the older failure is not shown); then hold = False, settle, step: reason "parcours modifié : crashed: BrokenProcessPool". Release hold in a finally block.
    - i18n: "parcours modifié : cible dans la terre, aucune eau libre à 1 nm : Blitvenica" -> EN "course changed: target on land, no open water within 1 nm: Blitvenica", SL "proga spremenjena: cilj na kopnem, ni proste vode v 1 nm: Blitvenica", FR unchanged; "impossible de contourner Blitvenica : aucun point en eau libre à moins de 1.05 nm au relèvement 189°" translated in EN and SL; the exact "parcours modifié : recalcul en cours" still maps to the existing rOutCourse text.
  </behavior>
  <action>
    RED first: update the existing assertion and add the new routing test in tests/routing/test_route_expiry.py; in tests/test_i18n.py add the two French messages above to COMPOSITES (rounding.py is not in CORE_FILES: its ValueError text reaches the tablet through RouteFailure(str(exc))) and add explicit EN/SL equality asserts for the "parcours modifié : cible dans la terre …" composite inside test_every_core_text_is_translated_in_en_and_sl_and_untouched_in_fr. Run them: they fail.

    router_service.py (fix 2): add self._fail_course_version: int | None = None next to self._last_fail in __init__, and self._last_req_course_version: int | None = None. In _maybe_request, where self.last_request = req is set, also record self._last_req_course_version = self.nav.course.version. Give _failed an optional course_version: int | None = None parameter that it stores in self._fail_course_version; give _invalid the same optional parameter, passed to _failed (or stored directly in the no-req branch). In _on_outcome pass the course_version argument to all three failure calls (pool status not ok, opt not ok -> _invalid or _failed, not valid -> _invalid). In _recycle_pool pass self._last_req_course_version to _failed. Leave _pool_alarm and the success path (self._last_fail = None) as they are. In _withdrawal, in the _course_changed branch: when self._last_fail is not None and self._fail_course_version == self.nav.course.version return the inline f-string f"parcours modifié : {self._last_fail}"; otherwise return REASON_OUT_COURSE (unchanged constant). Do not add a module-level REASON_* constant for the prefix (see interfaces: the i18n collector would demand a translation of the bare prefix). Nothing else in the withdrawal order changes.

    i18n.js: add "srv.rOutCourseWhy" next to "srv.rOutCourse" in all three dictionaries — FR "parcours modifié : {r}", EN "course changed: {r}", SL "proga spremenjena: {r}" — and "srv.rCannotRound" next to "srv.rTargetOnLand" — FR "impossible de contourner {name} : aucun point en eau libre à moins de {n} nm au relèvement {b}°", EN "cannot round {name}: no open-water point within {n} nm at bearing {b}°", SL "obplutje {name} ni mogoče: ni točke v prosti vodi v {n} nm pri smeri {b}°". In SRV_RULES add, next to the rOutMissedWhy rule, [/^parcours modifié : (.+)$/s, "rOutCourseWhy", ["*r"]] (the inner reason is translated recursively; SRV_EXACT is checked first so the exact "recalcul en cours" text keeps rOutCourse), and next to the rTargetOnLand rule [/^impossible de contourner (.+) : aucun point en eau libre à moins de (.+) nm au relèvement (.+)°$/s, "rCannotRound", ["name", "n", "b"]]. Same placeholders in every language (test_every_key_in_every_language_with_the_same_placeholders).

    Regenerate the Slovenian review sheet with .venv313/bin/python -m jabuka.tools.i18n_review, check it with --check. Commit (explicit paths): src/jabuka/core/router_service.py tests/routing/test_route_expiry.py src/jabuka/web/static/i18n.js tests/test_i18n.py docs/I18N-SL-REVIEW.md — never docs/I18N-SL-REVIEW.md.bak.
  </action>
  <verify>
    <automated>.venv313/bin/pytest -q tests/routing/test_route_expiry.py tests/test_i18n.py tests/test_route_logic.py tests/routing/test_supervisor.py && .venv313/bin/python -m jabuka.tools.i18n_review --check</automated>
  </verify>
  <done>Course-change reason is "recalcul en cours" while the current-version cycle computes (older failures ignored) and "parcours modifié : <failure>" once a current-version cycle failed; EN/SL translate both the prefix and the inner reason plus the rounding failure; the review sheet is in sync; the .bak file is untouched and unstaged; commit made with explicit paths.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: "À la fin" appends after the last mark unless that mark is a real finish</name>
  <files>src/jabuka/web/static/carte.js, tests/test_carte_logic.py, tests/ui/test_carte.py</files>
  <behavior>
    - endInsertAt(course): Course A shape (seq vodice, plic-sestre, jabuka, blitvenica, vodice; vodice kind "start-finish"; finish_idx null) -> 4 (before the Vodice finish, as today).
    - finish_idx 2 (explicit "Finir ici") -> 2.
    - Finish deleted (seq vodice, plic-sestre, m1, jabuka, blitvenica; blitvenica kind "mark") -> 5 = seq.length (append).
    - Last mark a custom mark (kind "mark") -> seq.length; only the start left (seq [vodice]) -> 1 (append; index 0 is never a finish).
    - UI (Playwright): tap open water, choose "À la fin", add -> the POST body has insert_at 4 and the course ends …, blitvenica, m1, vodice; delete the Vodice finish (DELETE /api/course/legs/5?base_version=v, wait for 5 list rows); tap a second open-water point, "À la fin", add -> insert_at 5 and the course ends …, blitvenica, m1, m2; no bad responses.
  </behavior>
  <action>
    RED first: create tests/test_carte_logic.py on the node-import pattern of tests/test_route_logic.py (module carte.js, skip when node is missing) with the endInsertAt cases above, and add test_add_at_end_before_a_finish_else_after_the_last_mark to tests/ui/test_carte.py (reuse open_carte, xy, course, EARTH_JS; read the posted insert_at from the response's request JSON; pick a second water point a few hundred metres from WATER so the tap does not hit the new m1 mark, and assert EARTH_JS == 0 for it like the existing fixture checks — adjust the point if it reports land). Run: they fail (endInsertAt missing; the second add lands before m1).

    carte.js (fix 3): add, next to lastIdx, an exported pure function endInsertAt(course) returning course.finish_idx when it is set (not null/undefined); else, when the last leg index is >= 1 and the mark of the last leg has kind "start-finish", that index (insert before the finish, the finish stays the finish); else course.seq.length (append after the last mark — accepted by add_mark since 1 <= len(seq) <= len(seq)). In openAddSheet's post(), use endInsertAt(course) instead of lastIdx(course) for st.pos === "end" and rewrite the comment above it in English to state the rule. Keep lastIdx unchanged (list tags, legFor, activate). No French string literal in carte.js (texts go through t()); no server change.

    Commit (explicit paths): src/jabuka/web/static/carte.js tests/test_carte_logic.py tests/ui/test_carte.py. Then run the full gate bash scripts/check.sh (ruff format fixes, if any, are committed with explicit paths too).
  </action>
  <verify>
    <automated>.venv313/bin/pytest -q tests/test_carte_logic.py tests/ui/test_carte.py tests/ui/test_carte_coords.py && bash scripts/check.sh</automated>
  </verify>
  <done>"À la fin" inserts before Vodice (start-finish) or an explicit finish, and appends after any other last mark; node and Playwright tests pass; bash scripts/check.sh prints "check: ok" (a lone failure of the known flaky test_switch_to_slovenian_then_english_persists_and_fits is rerun alone and recorded); commit made with explicit paths.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| tablet -> core API (POST /api/marks) | insert_at chosen by carte.js crosses into course.add_mark |
| core -> tablet (route reason) | router failure text (contains user-typed mark names) shown on the helm/diag |
| course data -> router worker | user-placed mark positions/sides drive rounding.expand |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-klg-01 | Tampering | POST /api/marks insert_at | low | mitigate | Existing validation kept: course_api Field(ge=1, le=MAX_SEQ) and add_mark CourseError unless 1 <= insert_at <= len(seq); endInsertAt only returns finish_idx, seq.length - 1 (>= 1) or seq.length |
| T-klg-02 | Information disclosure / injection | route reason "parcours modifié : <failure>" with mark names | low | mitigate | Rendered through trServer/t into textContent only (no innerHTML in web/static, checked at planning); regex captures are inserted as plain text params |
| T-klg-03 | Denial of service | rounding.expand last-mark push | low | accept | Bounded loop (0.5 nm / 0.02 nm = 25 lookups); failure is a ValueError -> RouteFailure, route() never raises, the core keeps the laylines |
| T-klg-04 | Repudiation (misleading state) | _withdrawal reason | low | mitigate | Failure tied to its course version: older-version failures never shown as current, current-version failures always shown (tests in test_route_expiry.py) |
</threat_model>

<verification>
- .venv313/bin/pytest -q tests/route/test_rounding.py tests/route/test_course_routes.py tests/routing/test_route_expiry.py tests/test_i18n.py tests/test_carte_logic.py tests/ui/test_carte.py
- .venv313/bin/python -m jabuka.tools.i18n_review --check
- bash scripts/check.sh -> "check: ok"
- git status: docs/I18N-SL-REVIEW.md.bak still untracked and unstaged; no change under cad/, stl/, hardware/, docs/SOAK.md, src/jabuka/nav/course.py, src/jabuka/route/isochrone.py
</verification>

<success_criteria>
- A course ending on Blitvenica (or any islet mark) routes again: last-mark target on its circle, approach side, clear water; Vodice finish unchanged.
- After a course edit the helm says "recalcul en cours" only while really computing, and the real failure (translated in EN/SL) once a current-version cycle failed.
- "À la fin" appends after a non-finish last mark and still inserts before a real finish.
- Full gate green; three commits with explicit paths and the Co-Authored-By trailer; nothing pushed or deployed.
</success_criteria>

<output>
Create `.planning/quick/261110-klg-edition-parcours-arrivee-ilot-raison-ech/261110-klg-SUMMARY.md` when done
</output>
