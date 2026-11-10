---
phase: quick-261110-iil
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/jabuka/route/stay.py
  - src/jabuka/core/router_service.py
  - tests/routing/test_tack_advice_core.py
  - tests/route/test_stay_route.py
  - docs/ROUTING.md
autonomous: true
requirements: [ROUT-07, ROUT-10, ROUT-05, ROUT-06]

estimate:
  tokens: 125000
  raw_tokens: 125000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "With On reste active on a course with marks after the active one, GET /api/route answers kind 'stay' with EVERY remaining leg: leg 1 = the forced leg to the active mark (forced ETA), later legs = the same cycle's optimal legs shifted by delta = forced ETA at the active mark - optimal ETA at the active mark; the map LineString ends at the finish (D-01)"
    - "The stay route's eta_utc (route message and nav block) is the finish ETA = optimal ETA + delta; leg_eta_utc stays the forced arrival at the active mark (D-02)"
    - "The forced route itself, res.forced (one leg), and the cost of not tacking are unchanged: tests/route/test_forced_cost.py passes untouched (D-03)"
    - "should_replace receives the composed finish ETA, the same span as the displayed route the worker re-evaluates (eta_old_now), so a non-forced cycle whose re-evaluated stay route equals the new one is kept and a gain > 3 min replaces it (D-04)"
    - "On the current leg the helm advice from the composed route equals the advice from the forced leg alone: target TWA/tack, XTE, course deviation, next tack and countdown (the forced leg's first tack stays the next tack) (D-05)"
    - "Edge cases return the forced route unchanged and never raise: optimal with a single leg (last mark), active-mark id mismatch, no optimal path point at the optimal active-mark ETA, junction farther than 0.1 nm, forced or optimal not usable; a composition exception in the core falls back to the forced route instead of dropping the cycle (D-06)"
    - "bash scripts/check.sh is green (ruff check, ruff format --check, pytest on both venvs)"
  artifacts:
    - path: src/jabuka/route/stay.py
      provides: "stay_route(forced, optimal) -> RouteResult: forced current leg + optimal continuation shifted by delta (pure: stdlib + jabuka.route.types)"
      contains: "def stay_route"
    - path: src/jabuka/core/router_service.py
      provides: "_on_outcome shows stay_route(f, opt) as the 'stay' route (try/except fallback to f); _whole_eta docstring updated"
      contains: "stay_route("
    - path: tests/routing/test_tack_advice_core.py
      provides: "core regression (all legs + finish ETA through /api/route and the nav block) and hysteresis-span tests"
      contains: "def test_stay_route_keeps_the_later_legs"
    - path: tests/route/test_stay_route.py
      provides: "stay_route unit tests (composition, tacks, edge cases), follower invariance on the current leg, one real-router two-mark round"
      contains: "def test_"
    - path: docs/ROUTING.md
      provides: "router paragraph + French ON RESTE section describe the complete stay route and its finish ETA"
      contains: "stay.py"
  key_links:
    - from: src/jabuka/core/router_service.py
      to: src/jabuka/route/stay.py
      via: "_on_outcome: shown, kind = stay_route(f, opt), 'stay'"
      pattern: "stay_route\\(f, opt\\)"
    - from: src/jabuka/core/router_service.py
      to: src/jabuka/route/advice.py
      via: "should_replace(shown.eta, ...) with shown = composed route; _on_new_route builds RouteFollower(path, tacks, legs=composed leg ETAs)"
      pattern: "should_replace\\("
    - from: src/jabuka/route/stay.py
      to: src/jabuka/route/isochrone.py
      via: "tack points of the appended part follow the same rule as isochrone._tack_points (prev/tk non-zero, gybe when |twa| >= 90 of the leaving segment)"
      pattern: "gybe"
---

<objective>
Fix the "On reste" (stay on tack) display bug: with stay active, the shown route is the forced
route of the CURRENT leg only, so every later leg vanishes from the map and eta_utc becomes the
active-mark ETA instead of the finish ETA.

User-locked decisions (from the orchestrator brief, cited below as D-NN):
- D-01: the displayed stay route = forced route for the current leg + the continuation of the SAME
  cycle's optimal route from the active mark onward (path points, tack points, leg ETAs), shifted
  in time by delta = forced ETA at the active mark - optimal ETA at the active mark. Legs complete.
- D-02: global ETA = optimal ETA + delta.
- D-03: do NOT change how the forced route is computed (route/cycle.py, route/isochrone.py stay
  untouched) nor the cost of not tacking.
- D-04: do not change hysteresis semantics (decision and justification in Task 1).
- D-05: the helm follower, next-tack countdown and off-route detection must still follow the
  forced current leg; next_tack stays the forced leg's first tack.
- D-06: edge cases (optimal single leg, forced invalid/None, optimal path without the leg
  boundary) fall back to the current behaviour and never crash.
- O-01 (optional marking of the appended part): NOT implemented, by discretion. The route line is
  one LineString built from Adopted.path; marking the appended part needs a new persisted Adopted
  field (route.json save/restore/_parse_saved) plus a front-end paint change in
  src/jabuka/web/static/route_logic.js to be visible at all — not trivial, and touching the helm
  front end two days before the freeze is not "safe". Nothing in the front end assumes a stay
  route has one leg (routeData() takes every LineString/tack/next_tack feature as for optimal).

Purpose: during the race the helm keeps the full picture (later legs, finish ETA) while holding
the tack, which is the core value ("trustworthy, continuously updated steer this / tack here").
Output: a pure composition function, its wiring in the core, regression + edge-case tests, docs.
</objective>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@src/jabuka/route/types.py
@src/jabuka/route/cycle.py
@tests/routing/test_tack_advice_core.py

<interfaces>
Facts observed in the code at planning time (use them; do not re-derive):

src/jabuka/route/types.py (NamedTuples, so ._replace works; RouteResult is a frozen dataclass,
use dataclasses.replace):
- PathPoint(t, lat, lon, twa_deg, tack, bsp_kn, twd_deg, tws_kn). Point i carries the segment
  sailed from point i to point i + 1. There is NO leg index on PathPoint.
- TackPoint(t, lat, lon, from_tack, to_tack, kind)  kind "tack" | "gybe".
- LegResult(mark_id, eta, lat, lon)  one per MARK (not per rounding waypoint).
- RouteResult fields: ok, reason, request_id, t0, path, tacks, legs, eta, valid, horizon_hold,
  start_in_margin, force_released_at, level, compute_ms, steps, notes, fail_kind.
- CycleResult(optimal, forced, cost_s, eta_old_now, old_valid, old_reason, worker).

How the real router lays out legs (src/jabuka/route/isochrone.py _route, lines ~760-815):
- each mark's arrival point is _Pt(t_arr, target, seg, protect=True); it becomes the first point
  of the next leg, so it appears exactly once in the path and survives decimation (protected);
- LegResult(mark_id, arrival.t, ...) uses the SAME float t, so the optimal path contains a point
  whose t equals optimal.legs[0].eta exactly; that point carries the segment LEAVING the mark
  (first segment of the next leg);
- route eta = t of the last path point; a leg_only (forced) route ends with the arrival point
  at the mark, whose segment is a COPY of the last sailed segment; forced.legs has 1 entry,
  forced.eta == forced.legs[0].eta == forced.path[-1].t;
- forced and optimal are built from the same request (same position, prev_mark, marks), so the
  rounding waypoints and the snapped target of the active mark are identical;
- _tack_points(pts, tack0): for p in pts[:-1]: tk = p.seg.tack; if prev != 0 and tk != 0 and
  tk != prev -> TackPoint(p.t, lat, lon, prev, tk, "gybe" if abs(p.seg.twa) >= 90 else "tack");
  if tk != 0: prev = tk. The arrival (last) point never yields a tack, so forced.tacks never
  contains a tack at the active mark.

src/jabuka/core/router_service.py (current):
- _on_outcome (~line 969): shown, kind = opt, "optimal"; if req.stay_active and self.stay.active
  and f ok/valid/path: shown, kind = f, "stay". Then should_replace(float(shown.eta), now,
  res.eta_old_now, res.old_valid is not False, age, forced_eff) and self._adopt(req, shown, ...).
- _build_request passes old_path = self.route.path (the DISPLAYED route) to the worker, which
  re-evaluates it under the new wind into eta_old_now (route/evaluate.py evaluate_path).
- _adopt stores eta=_whole_eta(...) (returns shown.eta; docstring says the stay route covers
  the current leg only), legs=((mark_id, eta), ...), path, tacks, horizon_hold, start_in_margin,
  force_released_at. _on_new_route builds RouteFollower(path, tacks, legs=[leg ETAs]).
- _fill_advice: eta_utc = follower eta_now (t_now + path[-1].t - t_here); leg_eta_utc =
  legs[0] eta + shift. route_message: LineString from display_points(path, 300) (keeps ends and
  tack vertices), one 'tack' feature per tack, 'next_tack' = first tack with t >= t0 - 1,
  "eta_utc": iso_utc(r.eta), "legs": [{mark_id, eta_utc}]. iso_utc rounds to whole seconds.
- The module already imports dataclasses, math, logging (log) and from jabuka.route.types.

src/jabuka/route/advice.py RouteFollower: leg arrivals = nearest path index to each leg ETA;
the projection never passes the next arrival unless the boat is within MARK_ZONE_NM (0.5 nm);
upcoming tack = first tack with t >= t_here - DUE_S; when the boat is already on the due tack's
new side, the following tack is advised.

tests/route/test_route_purity.py scans every module in src/jabuka/route/: no clock reads, no
jabuka.core / jabuka.nav / jabuka.prep imports, no network/shapely/GRIB libs.

Test harness (tests/routing/conftest.py, reachable through the rh fixture): rh.straight_route(t0,
lat, lon, *, eta_s, twa, tack_at_s, to_mark, request_id, mark_id) builds a 2-3 point one-leg
RouteResult; rh.PLIC_SESTRE; rh.boat_near_plic(nm); FakePool.default(creq) returns optimal
(eta_s 7200, tack at 1800 s) + forced (eta_s + cost_s, tack at tack_at_s + 600), both one leg;
fake_pool.script = fn(creq) -> CycleResult overrides it. test_tack_advice_core.py already has
_start(routing_core, fake_pool, rh), _run(core, pos, seconds, hdg) and _kept(fake_pool) helpers
and PORT_HDG. Tests use TestClient and free UDP ports (never port 8080).

tests/route/conftest.py fixtures: env_factory(wind), uniform_wind(twd_deg, tws_kn),
make_request(lat, lon, marks, **overrides incl. tack0, settings), mark_point(lat, lon, name)
(mark_id = name.lower()). tests/route/test_forced_cost.py shows the numpy guard header
(JABUKA_REQUIRE_ROUTE == "1" -> import numpy, else pytest.importorskip("numpy")) and the 'beat'
scenario: OPEN = (43.25, 15.20), wind 000 / 12 kn, target 8 nm at 030, tack0 = +1,
RouterSettings(use_waves=False).
</interfaces>
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer - stay route composed end-to-end (route/stay.py -> core _on_outcome -> /api/route and the nav block)</name>
  <files>src/jabuka/route/stay.py, src/jabuka/core/router_service.py, tests/routing/test_tack_advice_core.py</files>
  <read_first>src/jabuka/route/types.py, src/jabuka/route/isochrone.py (lines 659-670 _tack_points, 752-832 _route), src/jabuka/core/router_service.py (lines 933-1000 _on_outcome, 1061-1120 _adopt/_on_new_route/_whole_eta, 1523-1580 route_message), tests/routing/test_tack_advice_core.py, tests/routing/conftest.py (lines 100-206)</read_first>
  <behavior>
    - RED first: add test_stay_route_keeps_the_later_legs to tests/routing/test_tack_advice_core.py and run it against the unfixed code; it must fail (today: 1 leg and eta_utc = forced leg ETA).
    - Fake script (set fake_pool.script before activating stay, after _start): optimal = two legs. Leg 1 = rh.straight_route(t0, b.lat, b.lon, eta_s=3600, tack_at_s=900, request_id=b.request_id) to PLIC_SESTRE; leg 2 = from PLIC_SESTRE to a point 3 nm from it (jabuka.nav.geo.offset, bearing 250 deg), 1800 s, one tack at +600 s from the mark (port then starboard), mark id = creq.base.marks[1].mark_id when the request carries 2+ marks, else "m2". Concatenate: path = leg-1 path without its last point + mark point carrying leg-2's first segment + leg-2 points; tacks = leg-1 tacks + leg-2 tack; legs = (LegResult plic-sestre at t0+3600, LegResult m2 at t0+5400); eta = t0 + 5400. Forced = rh.straight_route(t0, b.lat, b.lon, eta_s=3600 + 420, tack_at_s=900 + 600) (one leg to PLIC, delta = 420 s). cost_s = 420. eta_old_now = None unless creq.old_path.
    - Activate stay (POST /api/route/stay {"active": true}), _run(core, pos, 1). Assert: nav route kind == "stay"; GET /api/route: len(legs) == 2, legs[0] == {"mark_id": "plic-sestre", "eta_utc": iso_utc(t0 + 4020)}, legs[1]["eta_utc"] == iso_utc(t0 + 5400 + 420), msg["eta_utc"] == iso_utc(t0 + 5820); the LineString's last coordinate equals the leg-2 end rounded to 6 decimals; the 'tack' features include the forced tack (t_utc iso(t0+1500)) and the leg-2 tack shifted (iso(t0+3600+600+420)); the 'next_tack' feature t_utc == iso_utc(t0 + 1500) (forced first tack, D-05).
    - Nav block: parse eta_utc and leg_eta_utc (datetime.fromisoformat with Z replaced) and assert eta_utc within 5 s of t0 + 5820 and leg_eta_utc within 5 s of t0 + 4020 (D-02); countdown_s == approx(1500, abs=3) (forced first tack).
  </behavior>
  <action>
Create src/jabuka/route/stay.py (module docstring in English like its siblings: the core's "On reste" display route, D-01/D-02; pure stdlib + jabuka.route.types so test_route_purity passes; no numpy, no clock). Constants JOIN_TOL_S = 1.0 (seconds) and JOIN_TOL_NM = 0.1. One public function stay_route(forced: RouteResult, optimal: RouteResult) -> RouteResult that returns `forced` itself (the same object, unchanged) whenever composition is not possible (D-06): forced or optimal not ok, empty path or legs, eta None or non-finite; len(optimal.legs) < 2 (last leg: nothing to append, forced.eta already is the finish); forced.legs[0].mark_id != optimal.legs[0].mark_id; no optimal path index j with abs(optimal.path[j].t - optimal.legs[0].eta) <= JOIN_TOL_S (take the closest such index); j is the last optimal path index; or the equirectangular distance (dlat*60, dlon*60*cos(mean lat), inline math, no jabuka.nav import) between optimal.path[j] and forced.path[-1] exceeds JOIN_TOL_NM.

Composition (D-01, D-02): delta = forced.legs[0].eta - optimal.legs[0].eta, NOT clamped (the cost clamps with max(0, .) but the shift must keep the path continuous at the forced arrival). Junction = forced.path[-1] with twa_deg, tack, bsp_kn, twd_deg, tws_kn taken from optimal.path[j] (keep the forced t/lat/lon: it is the forced arrival at the mark, and its segment must be the next leg's first one). Path = forced.path[:-1] + (junction,) + every optimal.path[k] for k > j with t + delta. Tacks = forced.tacks + tack points of the appended part recomputed with the isochrone._tack_points rule on PathPoints: prev = the ORIGINAL forced.path[-1].tack (the arriving tack), walk the composed path from the junction index to the second-to-last point; this yields the junction tack when the forced boat arrives on another tack than the next leg leaves on, and the optimal's later tacks shifted by delta. Legs = (forced.legs[0],) + optimal.legs[1:] each with eta + delta. eta = optimal.eta + delta. horizon_hold = forced.horizon_hold or optimal.horizon_hold (the core has no wind field to re-check the later ETA; conservative). valid = forced.valid and optimal.valid. Everything else (request_id, t0, start_in_margin, force_released_at, level, notes incl. "on_reste", compute_ms, steps, fail_kind) comes from forced via dataclasses.replace.

Wire it in src/jabuka/core/router_service.py _on_outcome: where the stay branch currently sets shown, kind = f, "stay", compose instead: shown = stay_route(f, opt) inside try/except Exception (noqa: BLE001 like the module's other best-effort spots) that logs with log.exception and falls back to shown = f, then kind = "stay" (D-06: a composition bug must never drop a routing cycle on a 36 h unattended run). Import stay_route from jabuka.route.stay. Leave should_replace(float(shown.eta ...)) as is so it receives the COMPOSED finish ETA — this is the D-04 decision: _build_request sends old_path = self.route.path (the displayed route) and the worker re-evaluates it into eta_old_now; once a stay route is displayed whole, eta_old_now is a finish ETA, so new_eta must be the composed finish ETA to compare the same span (before the fix both sides were leg-1 ETAs; for optimal routes both are finish ETAs). Feeding the forced leg ETA would make gain = finish - leg (an hour or more) and replace on every timer cycle, changing ROUT-05. Kind switches (optimal <-> stay) stay forced as today. Rewrite the _whole_eta docstring to say the stay route is now composed (forced current leg + optimal continuation shifted by the forced delay, route/stay.py), so its eta is the finish ETA; keep the method returning shown.eta. Add a short comment at the should_replace call recording the D-04 reason in one line. Do not touch route/cycle.py, route/isochrone.py, route/advice.py, the cost (res.cost_s) or _adopt's cost logic (D-03).

Then make the RED test from the behavior block pass (GREEN). Keep the existing tests in the file unchanged.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q tests/routing/test_tack_advice_core.py tests/route/test_forced_cost.py tests/route/test_route_purity.py</automated>
  </verify>
  <done>test_stay_route_keeps_the_later_legs failed before the fix and passes after; every other test in tests/routing/test_tack_advice_core.py, tests/route/test_forced_cost.py and tests/route/test_route_purity.py passes unchanged; /api/route for a stay route lists all legs with the finish ETA = optimal ETA + delta and the next_tack is the forced first tack.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Edge cases, current-leg advice invariance, real-router round and hysteresis span</name>
  <files>tests/route/test_stay_route.py, tests/routing/test_tack_advice_core.py</files>
  <read_first>src/jabuka/route/stay.py (from Task 1), src/jabuka/route/advice.py (lines 155-388 RouteFollower, 517-541 should_replace), tests/route/test_forced_cost.py, tests/route/conftest.py (lines 128-160)</read_first>
  <behavior>
    - Synthetic composition (tests/route/test_stay_route.py, no numpy needed): hand-built forced (1 leg, ends at mark M with a held-tack segment then one tack) and optimal (2-3 legs, path point exactly at legs[0].eta at M, tacks on later legs). Assert path = forced.path[:-1] + junction + shifted tail; junction t/lat/lon = forced.path[-1], twa/tack/bsp = optimal point at the mark; times non-decreasing; legs[0] is forced.legs[0]; later leg ETAs = optimal + delta; eta = optimal.eta + delta == path[-1].t; tacks start with forced.tacks; later tacks equal optimal tacks after the mark shifted by delta.
    - Junction tack: forced arrives on starboard, next leg leaves on port -> one TackPoint at the junction (from +1 to -1, kind "tack" when |twa| < 90, "gybe" when >= 90); forced arrives on the same tack as the next leg -> no junction tack.
    - Negative delta (forced reaches the mark before the optimal): composition still continuous, eta = optimal.eta + delta.
    - Fallbacks (result `is forced`, no exception): optimal with one leg; mark id mismatch; optimal path with the point at legs[0].eta removed (or shifted by 5 s); that point is the last one; junction 0.5 nm away from forced.path[-1]; optimal ok False; forced eta None; empty optimal path.
    - Advice invariance (D-05): RouteFollower(composed.path, composed.tacks, legs=[lg.eta for lg in composed.legs]) and RouteFollower(forced.path, forced.tacks, legs=[forced.legs[0].eta]) fed the same sequence of (t, lat, lon, cog = segment course, twd) at the midpoint of every forced segment except the last arrival give identical idx, xte_nm, course_dev_deg, target_twa, target_tack, next_tack and countdown_s.
    - Real router (guarded by the test_forced_cost numpy header logic inside the test): beat scenario with TWO marks, A = 8 nm at 030 from OPEN, B = 5 nm at 100 from A (open water), tack0 +1, use_waves False; res = cycle_with_env(env, CycleRequest(req, stay_active=True)); res.forced has 1 leg (D-03); s = stay_route(res.forced, res.optimal) has 2 legs, mark ids [a, b], eta == approx(res.optimal.eta + delta), eta - optimal.eta == approx(res.cost_s) when delta >= 0, path times non-decreasing, s.path[-1] lat/lon == optimal.path[-1] lat/lon, and the advice-invariance check above holds on the real forced leg.
    - Hysteresis span (D-04, tests/routing/test_tack_advice_core.py, same two-leg fake script as Task 1, extracted to a module-level helper both tests use): after the stay route is adopted (version 2), a script returning the same cycle with eta_old_now = composed finish ETA and old_valid True + core.call(core.router.request, "timer", False) + _run -> version stays 2 (kept); with eta_old_now = composed ETA + 600 -> version 3 (gain). Feeding the forced leg ETA to should_replace would fail the first case.
  </behavior>
  <action>
Write tests/route/test_stay_route.py covering every bullet of the behavior block except the hysteresis one (module docstring: "On reste" display route, D-01..D-06). Build synthetic RouteResults with small local helpers (PathPoint/TackPoint/LegResult from jabuka.route.types, positions with plain degree offsets, t0 = 1793923200.0); keep the module importable without numpy: only the real-router test imports numpy-dependent modules (jabuka.route.cycle.cycle_with_env) inside its body after the same JABUKA_REQUIRE_ROUTE / importorskip guard test_forced_cost.py uses at module level. Parametrize the fallback cases. In the advice-invariance helper, derive the COG of each forced segment from its two end points (math.atan2 of dlon*cos(lat) over dlat, in degrees, wrapped to 0-360) and pass twd = the segment start point's twd_deg.

In tests/routing/test_tack_advice_core.py, move the Task 1 two-leg fake script into a module-level helper (e.g. _two_legs(rh, delta_s) returning a script) shared by test_stay_route_keeps_the_later_legs and the new test_stay_hysteresis_compares_whole_routes; wrap it like _kept() to set eta_old_now / old_valid only when creq.old_path is not None.

If any assertion exposes a stay_route defect, fix it in src/jabuka/route/stay.py (allowed, same task) without changing the D-04 decision or anything in route/cycle.py, route/isochrone.py, route/advice.py. Document in a test docstring the one intended advice change: once the forced leg has no tack left, the countdown points at the first tack after the mark (exactly what an optimal multi-leg route does) instead of none.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q tests/route/test_stay_route.py tests/routing/test_tack_advice_core.py tests/route/test_forced_cost.py tests/route/test_advice.py tests/route/test_decisions.py</automated>
  </verify>
  <done>tests/route/test_stay_route.py exists with composition, junction-tack, negative-delta, parametrized fallback, advice-invariance and real-router tests, all passing; test_stay_hysteresis_compares_whole_routes passes (kept at equal ETA, replaced at +600 s); existing advice/decisions/forced-cost tests unchanged and green.</done>
</task>

<task type="auto">
  <name>Task 3: Docs and full gate</name>
  <files>docs/ROUTING.md</files>
  <read_first>docs/ROUTING.md (lines 128-140 router paragraph, 240-262 French "ON RESTE" section)</read_first>
  <action>
docs/ROUTING.md, router paragraph (English, after the sentence ending "re-sailed under the new wind for the hysteresis rule."): add 2-3 sentences: with "On reste" active the core displays the forced current leg followed by the same cycle's optimal route from the active mark onward, shifted by delta = forced arrival - optimal arrival at that mark (src/jabuka/route/stay.py); the route ETA is the finish (optimal ETA + delta) and that is what the hysteresis compares with the displayed route re-evaluated, both spanning the whole course; the worker's forced route and the cost of not tacking are unchanged (still the current leg only). French operator section "### ON RESTE": add one bullet in the same style as its neighbours, e.g. « La route affichée va jusqu'à l'arrivée : la branche en cours tenue sur le bord actuel, puis les branches suivantes de la route optimale, décalées du temps perdu à la marque. L'ETA affichée est celle de l'arrivée. » Do not edit any other doc (docs/SOAK.md is off-limits; no other doc claims the stay route covers one leg).

Then run the full gate: bash scripts/check.sh. If bootstrap-dev.sh fails offline, run its four steps directly: .venv/bin/ruff check src tests; .venv/bin/ruff format --check src tests; .venv/bin/python -m pytest -q; .venv313/bin/python -m pytest -q. Apply ruff format to the touched Python files if the format check fails (only those files). Never stop or kill the demo on port 8080.

Commit per task as the executor workflow does, staging explicit paths only (src/jabuka/route/stay.py, src/jabuka/core/router_service.py, tests/routing/test_tack_advice_core.py, tests/route/test_stay_route.py, docs/ROUTING.md, then the plan/summary docs); never git add -A, stash, reset, clean or switch branch; do not push; do not deploy to the Pi; never touch cad/, stl/, hardware/, docs/SOAK.md or the quick-task table in .planning/STATE.md. Commit subjects like fix(quick-261110-iil): ... / test(quick-261110-iil): ... / docs(quick-261110-iil): ..., each message ending with the line "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". In the SUMMARY, note that src/jabuka changed, so the src fingerprint changes (wheelhouse rebuild / Pi re-provision is the orchestrator's call, not part of this task).
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && grep -c "stay.py" docs/ROUTING.md && bash scripts/check.sh</automated>
  </verify>
  <done>docs/ROUTING.md describes the complete stay route (English paragraph + French ON RESTE bullet); bash scripts/check.sh prints "check: ok" (or the four direct steps all pass); commits made with explicit paths and the Co-Authored-By trailer; nothing pushed or deployed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| routing worker -> core | CycleResult (optimal + forced RouteResult) crosses a process boundary; internal, but its geometry is now combined by the core |
| core -> tablet | /api/route and the nav block drive the helm advice; a wrong composition = wrong steering advice |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-iil-01 | Denial of service | router_service._on_outcome stay branch | high | mitigate | stay_route call wrapped in try/except with log.exception and fallback to the forced route, so a composition bug never drops a routing cycle (D-06); stay_route itself returns forced for every malformed input (parametrized fallback tests) |
| T-iil-02 | Tampering (integrity of advice) | route/stay.py junction cut | high | mitigate | cut only at an optimal path point within 1 s of optimal.legs[0].eta AND within 0.1 nm of the forced arrival, matching mark ids; advice-invariance tests prove the current-leg advice (target, XTE, next tack, countdown) is identical to the forced leg alone |
| T-iil-03 | Tampering (integrity of advice) | hysteresis (should_replace) | medium | mitigate | composed finish ETA vs re-evaluated displayed route (same span); test_stay_hysteresis_compares_whole_routes pins kept/replaced behaviour |
| T-iil-04 | Information disclosure | route message | low | accept | no new data beyond existing route geometry on the boat's local Wi-Fi |
</threat_model>

<verification>
- .venv313/bin/python -m pytest -q tests/route/test_stay_route.py tests/routing/test_tack_advice_core.py tests/route/test_forced_cost.py tests/route/test_route_purity.py tests/route/test_advice.py tests/route/test_decisions.py
- bash scripts/check.sh (or its four steps when bootstrap fails offline) -> "check: ok"
- git diff --stat HEAD~N shows no change under src/jabuka/route/cycle.py, src/jabuka/route/isochrone.py, src/jabuka/route/advice.py, src/jabuka/web/, cad/, stl/, hardware/, docs/SOAK.md
- Optional manual look (no restart of the demo required by this plan): the demo on port 8080 runs the old code until the orchestrator restarts it; do not kill it.
</verification>

<success_criteria>
- With On reste active, the displayed route has all remaining legs, its later legs shifted by delta, and eta_utc = optimal finish ETA + delta (regression test red before, green after).
- Current-leg advice identical to the forced leg alone; next tack = forced first tack.
- Forced route, cost of not tacking and hysteresis semantics unchanged (composed ETA vs whole re-evaluated displayed route, justified and tested).
- Edge cases fall back to the forced route; nothing raises.
- Full gate green on both venvs.
</success_criteria>

<output>
Create `.planning/quick/261110-iil-on-reste-route-stay-complete-legs-suivan/261110-iil-SUMMARY.md` when done
</output>
