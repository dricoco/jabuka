---
phase: quick-261110-cuk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/jabuka/nav/start.py
  - src/jabuka/core/start_api.py
  - src/jabuka/core/nav_service.py
  - src/jabuka/core/web.py
  - src/jabuka/nav/settings.py
  - src/jabuka/web/static/start_logic.js
  - src/jabuka/web/static/start.js
  - src/jabuka/web/static/app.js
  - src/jabuka/web/static/app.css
  - src/jabuka/web/static/i18n.js
  - src/jabuka/tools/i18n_review.py
  - docs/I18N-SL-REVIEW.md
  - docs/TABLET-SETUP.md
  - docs/COMMISSIONING.md
  - docs/COMMISSIONING-SL.md
  - tests/nav/test_start.py
  - tests/web/test_start_api.py
  - tests/test_start_logic.py
  - tests/ui/test_start_ui.py
autonomous: true
requirements: [HELM-01, HELM-02, HELM-03, CRSE-05, DATA-07]

estimate:
  tokens: 180000
  raw_tokens: 180000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "On the Barre tab a DÉPART button opens start mode on every tablet (state on the Pi, in the nav message); « Ping comité » / « Ping bouée » store the boat's current GPS position as the line ends, typed degrees + decimal minutes (coord_logic.js) are the fallback, and both ends survive a core restart (start.json, .bak fallback)"
    - "5:00 starts a countdown on the Pi that keeps running through a page reload (the reloaded page shows the same remaining time within 2 s); SYNC rounds the remaining time to the nearest full minute (4:40 -> 5:00, 4:20 -> 4:00, under 0:30 -> the gun); STOP cancels it; « Fermer le départ » closes start mode"
    - "With the line, a GPS position, a heading and a non-stale wind, the panel shows the time to the line on the current heading and on the other tack (heading mirrored about TWD, same TWA, beat-angle clamp, + start_tack_s) and each margin = remaining - time to line; without wind, position, heading or line the times read — and no zone is drawn, never an error"
    - "While the timer runs the map shows the start zone: the reverse isochrone from the line (measured TWD/TWS, derated polar x efficiency, VMG with one tack costing start_tack_s, crossing towards the course side) that shrinks as the remaining time drops"
    - "Réglages shows a new field « Départ : durée d'un virement (s) » (start_tack_s, default 10 s, 0-60 accepted, -1 and 61 refused with 422) with fr/en/sl labels; changing it changes only the other-tack time and the zone; tack_penalty_s and every routing setting keep their values and consumers"
    - "When the margin on the other tack reaches zero (in (-10 s, 0], crossing inside the segment) the start panel turns into an inverted TACK alert and the tablet beeps once (no repeat within 10 s)"
    - "At the gun the timer stops and start mode closes on every tablet with an events-log line (type start, action gun); every start change (open, close, ping, typed, timer_start, sync, stop, gun) is an events-log line"
    - "Routing, laylines, the rounding FSM and every existing nav field are unchanged: with start mode closed the nav message has no 'start' key (tests/nav/test_nav_tracer.py shape fixture unchanged); a start failure yields start = {open: true, error: true}, never touches the other blocks, never stops the tick, and start.js renders in try/catch"
    - "Every new UI string exists in fr, en and sl (tests/test_i18n.py green, docs/I18N-SL-REVIEW.md regenerated); the start panel is red-only at night; TABLET-SETUP §11 explains ping, timer, SYNC and the numbers; bash scripts/check.sh is green on both venvs"
  artifacts:
    - path: src/jabuka/nav/start.py
      provides: "LineEnd/StartState models, StartStore (start.json, timer gun_mono + gun_utc, sync, gun, events through on_event), pure geometry (tack_headings, ray_to_line, course_normal, convex_hull, zone_ring) and start_block(store, msg, polar, settings, t_mono, utc_now)"
      contains: "def start_block"
    - path: src/jabuka/core/start_api.py
      provides: "GET /api/start, POST /api/start/open, POST /api/start/ping, PUT /api/start/line/{end}, POST /api/start/timer; events-log writer installed on StartStore.on_event"
      contains: "def router"
    - path: src/jabuka/core/nav_service.py
      provides: "self.start = StartStore(...); _add_start(msg, t_mono) called by update() after the nav computation, in its own try/except"
      contains: "_add_start"
    - path: src/jabuka/nav/settings.py
      provides: "start_tack_s field (default 10.0, ge 0, le 60, label « Départ : durée d'un virement (s) ») in a start-mode block; nothing else changes"
      contains: "start_tack_s"
    - path: src/jabuka/web/static/start_logic.js
      provides: "pure formatting: fmtTimer, fmtSigned, remainingAt, startView, beepDue, startData, startLayers, coordErrorKey"
      contains: "export function startView"
    - path: src/jabuka/web/static/start.js
      provides: "DÉPART button, #start-panel, typed-coordinate form, beep, 'start' map overlay; every render in try/catch"
      contains: "export function mount"
    - path: tests/nav/test_start.py
      provides: "store, timer, sync, gun, restart, geometry, zone and start_block unit tests"
    - path: tests/web/test_start_api.py
      provides: "REST endpoints, events log, persistence across a core restart, isolation of the nav message"
    - path: tests/test_start_logic.py
      provides: "node tests of start_logic.js (fr/en/sl texts, interpolation, beep edge, GeoJSON, night colours)"
    - path: tests/ui/test_start_ui.py
      provides: "Playwright: open, ping, typed end, 5:00, reload survival, zone polygon, layout, night colours, close"
    - path: docs/TABLET-SETUP.md
      provides: "## 11. Start mode — Mode départ"
      contains: "Mode départ"
  key_links:
    - from: src/jabuka/core/nav_service.py
      to: src/jabuka/nav/start.py
      via: "NavService.update() -> _add_start(msg, t_mono) -> start_block(self.start, msg, self.polar, self.settings, t_mono, utc_epoch(self.clock))"
      pattern: "start_block\\(self\\.start"
    - from: src/jabuka/nav/start.py
      to: src/jabuka/nav/settings.py
      via: "start_block reads settings.start_tack_s for other.t_s and the zone's effective time; never settings.tack_penalty_s"
      pattern: "settings\\.start_tack_s"
    - from: src/jabuka/nav/settings.py
      to: src/jabuka/web/static/i18n.js
      via: "tests/test_i18n.py binds every Settings field label to settings.<field> (SETTINGS_FR/EN/SL)"
      pattern: "start_tack_s"
    - from: src/jabuka/core/web.py
      to: src/jabuka/core/start_api.py
      via: "app.include_router(start_api.router(ctx)) before the static mount"
      pattern: "start_api\\.router\\(ctx\\)"
    - from: src/jabuka/core/start_api.py
      to: src/jabuka/nav/start.py
      via: "router installs store.on_event = write_event (events log) and every mutation ends with ctx.publish_nav()"
      pattern: "on_event = write_event"
    - from: src/jabuka/web/static/app.js
      to: src/jabuka/web/static/start.js
      via: "MODULES entry [\"start\", \"./start.js\", \"tab-barre\"] loaded with its own try/catch after the helm"
      pattern: "\\./start\\.js"
    - from: src/jabuka/web/static/start.js
      to: src/jabuka/web/static/coord_logic.js
      via: "typed line ends parsed with checkPosition and shown with formatDM (same helpers as the Carte tab)"
      pattern: "checkPosition"
---

<objective>
"Mode départ" (start sequence) for the helm tablet: a start line pinged on the water (or typed),
a 5:00 timer with SYNC and STOP that lives on the Pi, the time to the line on the current heading
and on the other tack with the margin against the gun, a TACK alert with a beep when the
other-tack margin reaches zero, and the start zone (reverse isochrone from the line) on the map.
At the gun the timer stops and start mode closes; routing is untouched.

The owner asked for the full version in chat (decision D-05) after the 11 Nov freeze and for a
race starting 13 Nov 20:00 local, i.e. a NIGHT start: night colours and the beep matter.
REQUIREMENTS.md lists "AIS, start-line tools" as out of scope; the owner's chat request overrides
it for this quick task (do not edit REQUIREMENTS.md).

Purpose: a trustworthy start without a separate watch, from the same tablet, without any risk to
the helm numbers, routing or laylines (H-01).
Output: nav/start.py + core/start_api.py + a start block in the nav message; start_logic.js +
start.js on the Barre tab with a map overlay; fr/en/sl strings; TABLET-SETUP §11 and runbook
rows; unit, API, node and Playwright tests; gate green on 3.14 and 3.13.
</objective>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@src/jabuka/core/nav_service.py
@src/jabuka/core/course_api.py
@src/jabuka/core/nav_api.py
@src/jabuka/core/web.py
@src/jabuka/nav/settings.py
@src/jabuka/nav/geo.py
@src/jabuka/web/static/route.js
@src/jabuka/web/static/route_logic.js
@src/jabuka/web/static/coord_logic.js
@src/jabuka/web/static/app.js

Read on demand (by line range, not whole): src/jabuka/nav/course.py lines 1-110 (docstring style,
CourseStore load/alert pattern, on_event at 295-310), src/jabuka/nav/polar.py lines 149-237
(Polar.speed, targets, efficiency_for), src/jabuka/core/main.py lines 267-336 (update_nav,
publish_nav, tick_once), src/jabuka/web/static/helm_logic.js lines 1-46 (fmtHeading, fmtDuration),
src/jabuka/web/static/i18n.js lines 1-30 and 145-175 (conventions, where FR keys live) and
1140-1260 (trServer: NOT needed, start texts are client keys), src/jabuka/web/static/app.css
lines 97-160 and 245-282 (.tab, #helm-col, .map-ctrls, theme vars), tests/test_route_logic.py
lines 1-40 and 356-370 (node harness, no-innerHTML and parse tests), tests/test_i18n.py lines
30-50 (node(body, *modules) helper importing i18n.js as I), tests/web/test_manual_wind.py lines
1-60 (in-process CoreContext + TestClient + _feed_gps/_feed_wind + _events helpers),
tests/ui/conftest.py (page/feeder fixtures; feeder.boat lat/lon/twd/tws_kn/twa/bsp_kn),
tests/ui/test_helm_column.py lines 115-160 (night red-only colour check JS to reuse),
src/jabuka/tools/i18n_review.py lines 27-55 (SECTIONS).

## Source items (traceability; cite these IDs in commits and the summary)

Owner decisions (LOCKED, from chat):
- D-01 Start line by GPS ping: two buttons « Ping comité » and « Ping bouée » store the current
  boat GPS position as each line end; typed coordinates as fallback reusing coord_logic.js;
  persisted on the Pi like the course (survives a power cut); an events-log entry per change.
- D-02 Timer: a 5:00 button started at the 5-minute signal; SYNC rounds the remaining time to the
  nearest full minute (classic sync); a way to cancel/stop.
- D-03a Zone on the map: the positions from which the boat reaches the line exactly at the gun
  (reverse isochrone from the line with measured TWD/TWS and the current polar incl. efficiency),
  shrinking as time runs; at least its boundary for the remaining time.
- D-03b Time to line on the current heading and on the other tack (after a tack), and the margin =
  time remaining - time to line.
- D-03c Visual alert + beep when the margin on the other tack reaches zero (= tack now).
- D-04 At the gun the timer stops and start mode closes; routing unchanged (it already routes from
  the live GPS position to the active mark).
- D-05 Full version (all of D-01..D-04) even past the planned 11 Nov code freeze.

Hard requirements from the owner:
- H-01 Isolation: no change to routing, laylines, the rounding FSM or the semantics of existing
  nav message fields. A start-mode error never breaks the helm or map page (UI renders in
  try/catch like the other optional modules; backend never raises into the nav tick).
- H-02 Computation on the Pi in a pure module (nav/start.py), pushed as an optional nav block; the
  timer survives a page reload (state on the Pi: monotonic gun time in memory, UTC gun time from
  the trusted GPS clock persisted).
- H-03 Measured true wind from the nav wind block; without wind or polar speed the times show "—"
  and there is no zone, no crash. Beat angle from the polar for upwind headings; time to line =
  distance to the line along the chosen heading / (polar speed at that TWA x efficiency); other
  tack = heading mirrored about the wind with the same TWA. Simple documented model: no current,
  no acceleration, a fixed tack cost (see O-01).
- O-01 (orchestrator decision, supersedes the earlier reuse of the router's tack_penalty_s): a
  dedicated Réglages setting start_tack_s ("Départ : durée d'un virement (s)", default 10.0, range
  0-60, fr/en/sl labels) is the tack cost of start mode, used ONLY by the other-tack time to line
  and by the zone. Routing settings stay untouched: tack_penalty_s keeps its value, its label and
  its only consumers (router_service, route/); start mode never reads it.
- H-04 fr/en/sl for every new string (i18n.js conventions, tests/test_i18n.py, review sheet).
- H-05 Docs: a short section in docs/TABLET-SETUP.md plus docs/COMMISSIONING.md (and the
  Slovenian course card docs/COMMISSIONING-SL.md).
- H-06 Tests: unit tests for geometry / time to line / zone, the API endpoints, UI logic tests
  (node harness), full gate bash scripts/check.sh green (pytest for direct runs: .venv313).
- H-07 Repo rules: stage by explicit paths only (never git add -A / stash / reset / clean /
  branch switch); never touch cad/, stl/, hardware/, docs/SOAK.md, the quick-task table in
  .planning/STATE.md; never stage the untracked docs/I18N-SL-REVIEW.md.bak (the review tool's
  atomic write refreshes it as a side effect); no push; no deploy; every
  commit ends with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".

Claude's discretion (decided here, documented in the module docstring and TABLET-SETUP §11):
- Below the polar beat angle (luffing, head to wind) the current-heading time assumes bearing away
  to the beat angle on the same tack (head to wind exactly = starboard).
- Course side (the side the boat crosses towards) = the side of the active mark (nav mark block),
  else the windward side. The zone only uses headings that cross towards the course side.
- The zone uses the convex hull of the polar velocities (VMG, tacks and gybes allowed) over the
  effective time T' = max(0, remaining - start_tack_s) (O-01: one tack or gybe assumed, so a boat
  that lays the line on one straight course has at most start_tack_s of sailing more than the zone
  shows; start_tack_s = 0 gives the no-cost zone); no zone when T' <= 0. It is drawn only while the
  timer runs; the times need a position and a heading, the zone does not.
- SYNC that rounds to 0:00 fires the gun (classic sync: pressed at the start signal).
- With the GPS clock not yet trusted the timer still runs in memory (survives a page reload, not
  a core restart); once trusted UTC is known the gun UTC is recorded so a later restart keeps it.

## Interface contract (binding between the three tasks and between Python and JS)

Persisted file <data-dir>/start.json (atomic_write_json, load_json_status with .bak):
{"open": bool, "gun_utc": float|null, "committee": End|null, "pin": End|null},
End = {"lat": 42..45, "lon": 14..17, "src": "ping"|"typed", "utc": float|null}.

Nav message key "start": ABSENT while start mode is closed. While open, Task 1 emits:
open (true), error (false), restored (null | "bak" | "unreadable"),
timer {state "off"|"running"|"clock", remaining_s float|null (0.1 s), gun_utc ISO "...Z"|null},
line {committee End-like {lat, lon, src}|null, pin {...}|null}.
Task 2 adds (additive, no renamed keys): line.length_nm, line.bearing_t (committee -> pin, deg
TRUE), reason (null | "no_line" | "no_position" | "no_heading" | "no_wind" | "calc_error"),
now {hdg_t, twa (signed deg, + = starboard), t_s|null, on_line bool, margin_s|null}|null,
other {same keys, t_s includes start_tack_s}|null, start_tack_s (echo of the setting), tack_now bool,
zone [[lon, lat], ...] closed ring (first == last) | null.
On an exception building the block: {"open": true, "error": true} only.

REST (all mutations return the fresh nav message, like nav_api fresh_nav):
GET /api/start -> store.to_api(); POST /api/start/open {open: bool}; POST /api/start/ping
{end: "committee"|"pin"} (409 {"detail": "no_position"} without a fresh GPS position, 422 outside
42-45 N / 14-17 E); PUT /api/start/line/{end} {lat, lon} (typed); POST /api/start/timer
{action: "start"|"sync"|"stop"} (409 {"detail": "no_timer"} for sync without a running timer);
OSError -> 503 {"ok": false, "error": "start write failed"}, nothing changed; bodies extra=forbid,
allow_inf_nan=False.

Events log lines: {"type": "start", "action": open|close|ping|typed|timer_start|sync|stop|gun,
...details (end, lat, lon, src, remaining_s, gun_utc, via, boat)} + t_mono/t_wall/utc added by the
API writer (same as course_api write_event).

DOM ids (tests rely on them): #start-ctrls, #start-open, #start-panel, #start-timer,
#start-status, #start-go, #start-sync, #start-stop, #start-close, #start-ping-committee,
#start-ping-pin, #start-type-committee, #start-type-pin, #start-end-committee, #start-end-pin,
#start-line-info, #start-now, #start-other, #start-alert, #start-msg, #start-form, #start-lat,
#start-lon, #start-form-ok, #start-form-cancel, #start-form-err. Map overlay id "start", sources
"start-zone", "start-line", "start-ends".
</context>

<tasks>

<task type="tracer">
  <name>Task 1 (tracer): start mode, line ends and the 5:00 timer end to end — start.json -> REST -> nav "start" block -> DÉPART panel, surviving a page reload</name>
  <files>src/jabuka/nav/start.py, src/jabuka/core/start_api.py, src/jabuka/core/nav_service.py, src/jabuka/core/web.py, src/jabuka/web/static/start_logic.js, src/jabuka/web/static/start.js, src/jabuka/web/static/app.js, src/jabuka/web/static/app.css, src/jabuka/web/static/i18n.js, src/jabuka/tools/i18n_review.py, docs/I18N-SL-REVIEW.md, tests/nav/test_start.py, tests/web/test_start_api.py, tests/test_start_logic.py, tests/ui/test_start_ui.py</files>
  <behavior>
    - StartStore round trip: open + both ends + gun_utc written to start.json and reloaded by a new store on the same dir; a torn start.json with a valid .bak gives restored "bak"; garbage in both gives defaults and restored "unreadable"
    - A write failure (atomic_write_json in jabuka.nav.start patched to raise OSError) raises and leaves the in-memory state unchanged
    - start_timer at t_mono 100 -> remaining(130) == ("running", 270); sync at remaining 280 -> 300, 260 -> 240, 270 -> 300 (half up), 20 -> gun (mode closed, event action gun via sync); stop -> ("off", None) and mode stays open; set_open(False) clears the timer
    - tick past the gun closes start mode, persists open false, emits one gun event carrying the boat position; a second tick emits nothing
    - restart: timer started with utc_now 1000 -> a new store with utc_now 1100 reads ("running", 200); a new store with utc_now None reads ("clock", None) then running once utc_now is given, and fires the gun at once if the gun UTC already passed; a timer started without UTC records gun_utc the first time utc_now is known
    - API: closed -> GET /api/nav has no "start" key; open -> start block; ping without GPS -> 409 no_position; ping with GPS -> committee src "ping"; PUT typed pin -> src "typed"; unknown end, lat 50, NaN, extra key -> 422; timer start -> remaining about 300; sync without timer -> 409 no_timer; close -> key gone; one events-log line of type start per action
    - Isolation: start_block patched to raise -> every other block of the nav message equals the unpatched one, start == {"open": true, "error": true}, nav.errors unchanged, ctx.tick_once() runs
    - Node: fmtTimer(300) "5:00", fmtTimer(4.2) "0:05", fmtTimer(null) "—:—"; remainingAt interpolates from the receive time and clamps at 0; startView status/end texts in fr and en
    - Browser: DÉPART -> panel; Ping comité and a typed pin show on the panel; 5:00 runs; after page.reload() the timer still runs within 2 s of the server's remaining time; STOP; Fermer hides the panel
  </behavior>
  <action>
Build the thinnest complete path for D-01, D-02, D-04 under H-01/H-02, with the contract in the
context section. Ruff line length 100; both venvs must pass.

1. src/jabuka/nav/start.py (new). Module docstring in the style of course.py: the start.json schema,
the timer model (gun_mono in memory, gun_utc persisted from the trusted GPS UTC, "clock" state
after a restart without trusted UTC), SYNC rounding (floor(remaining / 60 + 0.5) * 60, 0 = the
gun), the gun closing start mode (D-04), events through on_event, the decisions listed under
"Claude's discretion". Constants START_FILE = "start.json", START_S = 300.0, END_NAMES =
("committee", "pin"). Pydantic LineEnd (lat 42..45, lon 14..17, src Literal["ping", "typed"], utc
float|None) and StartState (open False, gun_utc None, committee None, pin None), both
extra="forbid", allow_inf_nan=False. Exception NoTimer. StartStore(data_dir) loads with
load_json_status(path, None, validate=...) like ManualWindStore, keeping self.restored = None |
"bak" | "unreadable" (shown inside the start block, never appended to the envelope alerts: H-01).
Every mutation builds the new StartState, writes it with atomic_write_json, and only then updates
memory (OSError propagates, nothing changes). Methods (names binding): open (property),
set_open(flag) (closing clears the timer), set_end(end, lat, lon, src, utc) -> LineEnd,
start_timer(t_mono, utc_now, seconds=START_S) (also opens start mode), sync(t_mono, utc_now) ->
new remaining (raises NoTimer when the timer is not running with a known remaining; 0 fires the
gun with via "sync"), stop(), remaining(t_mono, utc_now) -> (state, seconds|None) (re-anchors
gun_mono = t_mono + gun_utc - utc_now after a restart; records gun_utc = utc_now + remaining once
when it was None, persisting quietly with OSError logged), tick(t_mono, utc_now, boat) (gun when
remaining <= 0: open False, timer cleared, persisted with OSError logged and memory still closed,
one event {"type": "start", "action": "gun", "via": "timer"|"sync", "gun_utc", "boat": [lat, lon]
| None}), to_api(). Every mutation emits its event through self.on_event (None = no-op; an
exception inside on_event is logged, never raised). No direct clock reads anywhere (t_mono and
utc_now are parameters; tests/test_no_wallclock.py). Module function start_block(store, msg,
polar, settings, t_mono, utc_now) -> dict | None: calls store.tick(t_mono, utc_now, boat lat/lon
from msg["boat"] when numeric), returns None when closed, else the Task 1 keys of the contract
(gun_utc as ISO "Z" like clock._iso; remaining_s rounded to 0.1). polar and settings are unused
in this task and used by Task 2 (keep the signature).

2. src/jabuka/core/start_api.py (new), pattern course_api.py + nav_api.py: router(ctx) installs
store.on_event = write_event (adds t_mono, t_wall, utc from ctx.clock like course_api write_event,
fsync_now=True, counts events_errors on failure); routes and status codes exactly as the REST
contract; async def handlers (serialized with the tick); a mutate helper mapping NoTimer -> 409
{"detail": "no_timer"}, pydantic ValidationError -> 422 (nav_api.validation_response), OSError ->
503; success -> ctx.publish_nav() then return ctx.nav.last (or ctx.nav.update() when None). Ping
reads the position through ctx.nav.state.latest(wind.POSITION) (the same freshness rule as the
helm's boat block); no entry or non-finite lat/lon -> 409 {"detail": "no_position"}; LineEnd
bounds -> 422. utc_now everywhere = utc_epoch(ctx.clock), t_mono = ctx.clock.monotonic().

3. src/jabuka/core/nav_service.py (H-01, smallest possible diff): import StartStore and
start_block; in __init__ self.start = StartStore(self.data_dir) and self.start_errors = 0; in
update(), after the existing try/except has produced msg and before self.last = msg, call
self._add_start(msg, t_mono). _add_start wraps start_block(self.start, msg, self.polar,
self.settings, t_mono, utc_epoch(self.clock)) in its own try/except Exception: log.exception,
self.start_errors += 1 (never self.errors), block = {"open": True, "error": True} when
self.start.open else None. Set msg["start"] only when the block is not None, so the closed-mode
message keeps exactly today's keys (tests/nav/test_nav_tracer.py shape fixture unchanged). Do not
touch _envelope, _compute or _write_back.

4. src/jabuka/core/web.py: import start_api and app.include_router(start_api.router(ctx)) next to
the other routers, before the static mount.

5. src/jabuka/web/static/start_logic.js (new, pure, DOM-free; header comment listing the exports
like route_logic.js): fmtTimer(s) ("m:ss", ceil so 0:00 only at the gun, "—:—" for null),
fmtSigned(s) ("+0:35" / "−0:05" with U+2212), remainingAt(block, rxMs, nowMs) (running only:
max(0, remaining_s - (nowMs - rxMs) / 1000), else null), coordErrorKey(code) (the existing
carte.errEmpty/errFormat/errMinutes/errSeconds/errRange keys; hemisphere handled by the caller with
carte.errHemi), startView(block, remaining) -> {visible, timer {text, state}, status (restored /
error / timer off / waiting for GPS time), ends {committee, pin: {label, text, ok}} (position with
coord_logic formatDM, decimal separator from fmtDec like carte.js decSep, "(ping)" / "(saisie)"
words via t), buttons {syncDisabled, stopDisabled}}. Every string through t("start.*") or existing
keys; never a French literal (tests/test_i18n.py scans every static JS).

6. src/jabuka/web/static/start.js (new; header comment like route.js): mount(ctx) per the app.js
module contract. Builds #start-ctrls (button #start-open, class "ctrl", t("start.open")) and
#start-panel (hidden) as children of ctx.section (#tab-barre), never inside #helm-col or
#map-ctrls (H-01: the helm layout and its tests stay untouched). Panel rows: timer (#start-timer
big, #start-status), buttons #start-go (5:00) #start-sync #start-stop #start-close, line rows
#start-end-committee / #start-end-pin with #start-ping-committee, #start-ping-pin,
#start-type-committee, #start-type-pin, a typed form #start-form (#start-lat, #start-lon,
#start-form-ok, #start-form-cancel, #start-form-err) validated live with coord_logic checkPosition
against RACE_AREA (errors via coordErrorKey / carte.errHemi / carte.errArea), #start-msg for
refused actions (6 s; 409 no_position -> start.noGps, 409 no_timer -> start.noTimer, 503 ->
start.writeFailed, 422 -> carte.refused, else common.failed). Visibility follows nav.start: panel
shown and DÉPART hidden while open, the reverse when the key is absent. Render on every bus "nav"
and every 250 ms for the timer text (remainingAt from the last nav receive time), each in
try/catch with console.error. Actions through ctx.api (post/put with a JSON body), one request in
flight, ignored while body.locked or after a bus "lock" true (route.js stay-button pattern); the
answer (fresh nav) is rendered at once. textContent only.

7. src/jabuka/web/static/app.js: append ["start", "./start.js", "tab-barre"] to MODULES; nothing else.

8. src/jabuka/web/static/app.css: a "start mode" section. Colours only from the theme vars (--bg,
--bg-band, --fg, --dim, --line, --good, --warn, --bad) so night stays red-only (HELM-03).
Landscape (min-aspect-ratio: 1/1): #start-panel absolute, top 8px, left calc(var(--col-w) + 8px),
right 8px, max-height calc(100% - 220px) (clear of .map-ctrls at bottom right), overflow-y auto,
content laid out in compact wrapping rows so it stays a strip near the top of the map area.
Portrait: left 8px, right 136px (the .map-ctrls column stays free), bottom 8px, max-height 34%.
#start-ctrls: bottom 36px, left 8px (portrait) / left calc(var(--col-w) + 8px) (landscape).
Buttons at least 48 px high; #start-timer large with tabular-nums; user-select none like #helm-col.

9. src/jabuka/web/static/i18n.js: a "start mode (start.js, start_logic.js)" block of start.* keys in
FR, EN and SL (same keys, same {name} parameters) for every text above: open "DÉPART", title, the 5:00 /
SYNC / STOP labels, close "Fermer le départ", ping comité / ping bouée, committee / pin names,
typed-entry button and form title, end states (ping / saisie / non défini), timer off, waiting
for GPS time, restored / unreadable line, start unavailable (error), noGps, noTimer, writeFailed.
SL is a proposal marked for proofreading like the rest (docs/I18N-SL-REVIEW.md). Reuse existing
keys where one exists (carte.lat, carte.lon, carte.err*, common.cancel, common.failed,
carte.refused).
src/jabuka/tools/i18n_review.py: add ("start.", "Start mode (Départ)") to SECTIONS before the
"srv." entry; regenerate docs/I18N-SL-REVIEW.md with .venv313/bin/python -m jabuka.tools.i18n_review
(the untracked docs/I18N-SL-REVIEW.md.bak it refreshes is never staged, H-07).

10. Tests (the behavior block above is the list):
tests/nav/test_start.py — store and timer tests on a tmp dir, events captured with a list as
on_event, plus start_block on literal msg dicts (closed -> None; open -> Task 1 keys).
tests/web/test_start_api.py — in-process CoreContext.create(SimClock(start_utc=START_UTC), dir,
udp_port=free_udp_port) + TestClient(create_app(ctx)) like tests/web/test_manual_wind.py (copy its
_feed_gps and _events helpers); advance time with ctx.clock.advance; a restart = a new CoreContext
on the same data dir; the isolation test patches jabuka.core.nav_service.start_block.
tests/test_start_logic.py — node harness importing i18n.js as I and start_logic.js (pattern
tests/test_i18n.py node()), with I.setLang(lang, {persist: false}) for fr/en; plus node --check
of .mjs copies of start.js and start_logic.js and a check that no non-comment line of either file
assigns HTML strings (same as tests/test_route_logic.py test_no_inner_html).
tests/ui/test_start_ui.py — page + feeder fixtures of tests/ui/conftest.py (system clock: the
timer lives in memory, which is exactly the reload case): wait for #start-open, click it, wait for
#start-panel visible; click #start-ping-committee and wait for GET /api/nav start.line.committee;
open #start-type-pin, type a position a few hundred metres east of the boat (feeder.boat lat/lon
moved with jabuka.nav.geo.offset, written in Python as degrees + decimal minutes with a decimal
comma, e.g. "43 42,966"), OK, wait for line.pin src typed; click #start-go, wait for #start-timer to match ^[45]:\d\d$; read
start.timer.remaining_s, page.reload(), wait for the panel, parse #start-timer and assert it is
within 2 s of the server's remaining time read right after the reload and still running; click
#start-stop then #start-close, wait for the panel hidden and for GET /api/nav without "start";
assert page.console_errors == [] and page.external_requests == [].

Commit (explicit paths only): "feat(quick-261110-cuk): mode départ — ligne (ping/saisie) et chrono 5:00 sur le Pi (D-01, D-02, D-04)" with the Co-Authored-By trailer (H-07).
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv313/bin/python -m pytest -q tests/nav/test_start.py tests/web/test_start_api.py tests/test_start_logic.py tests/ui/test_start_ui.py tests/test_i18n.py tests/nav/test_nav_tracer.py tests/web/test_manual_wind.py tests/web/test_course_api.py tests/test_no_wallclock.py && .venv/bin/python -m pytest -q tests/nav/test_start.py tests/web/test_start_api.py tests/test_start_logic.py tests/test_i18n.py</automated>
  </verify>
  <done>From a fresh data dir: DÉPART opens the panel on the tablet, Ping comité stores the GPS position, a typed pin is accepted with the Carte tab's coordinate rules, 5:00 counts down on the Pi and the reloaded page shows the same countdown; SYNC/STOP/Fermer work; at the gun start mode closes with an events-log line; with start mode closed the nav message is byte-for-byte the old shape; a forced start_block exception leaves the helm message intact. All listed tests green on .venv313 and the non-UI ones on .venv; committed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: time to line, other tack, margins, TACK alert + beep, the start zone on the map and the start_tack_s setting (D-03a, D-03b, D-03c, O-01)</name>
  <files>src/jabuka/nav/start.py, src/jabuka/nav/settings.py, src/jabuka/web/static/start_logic.js, src/jabuka/web/static/start.js, src/jabuka/web/static/app.css, src/jabuka/web/static/i18n.js, docs/I18N-SL-REVIEW.md, tests/nav/test_start.py, tests/web/test_start_api.py, tests/test_start_logic.py, tests/ui/test_start_ui.py</files>
  <behavior>
    - tack_headings: TWD 0, hdg 45 (twa -45, port), up_twa 40 -> now (45, -45), other (315, +45); hdg 20 -> clamped to (40, -40), other (320, +40); hdg 0 (head to wind) -> starboard (320, +40), other (40, -40)
    - ray_to_line: line east-west of 0.1 nm through the origin, boat 0.2 nm south heading 000 -> 0.2 nm, on_line true; heading 090 (parallel) -> None; heading 180 (away) -> None; heading 045 from 0.2 nm south crossing beyond an end -> distance with on_line false
    - start_block, uniform TWD 000 / 12 kn, boat 0.2 nm south of the line centre on starboard close-hauled, timer 120 s: now.t_s == distance along the heading / (efficiency_for x polar.speed) x 3600 (independent recomputation in the test), other.t_s includes settings.start_tack_s (default 10 s; changing tack_penalty_s to 90 changes nothing in the start block, changing start_tack_s to 0 / 30 shifts other.t_s by exactly that), margin_s == remaining - t_s for both
    - Settings: start_tack_s defaults to 10.0; PUT /api/settings with 0 and 60 accepted, -1 and 61 refused with 422 and nothing written; an existing settings.json without the key loads with the default; GET /api/settings/schema carries the label « Départ : durée d'un virement (s) »
    - tack_now true exactly when -10 < other.margin_s <= 0 with other.on_line; false at +1 s, at -11 s and when other crosses outside the segment
    - reason precedence: no_line > no_position > no_heading > no_wind (source NONE, stale, twd/tws null) > calc_error (geometry raising), with now/other null and tack_now false; the timer part stays correct in every case
    - zone_ring with start_tack_s = 0 at T = 300 s: closed ring, convex, every point on the pre-start side (y <= 1e-9 when the course side is north), southernmost point within 3 % of T x upwind VMG x efficiency; area at T = 150 s between 0.2 and 0.35 of the area at T = 300 s (about T squared plus the line sweep, 0.1 nm line); with start_tack_s = 10 at T = 300 s the ring equals the start_tack_s = 0 ring at T = 290 s; None when remaining <= start_tack_s, without wind, without a running timer or with polar speed 0
    - course side: the side of the nav mark block when present, else windward
    - Node: startView now/other rows (time, margin, class good within 5 s, bad later than 5 s, neutral early), off-line suffix, reason texts fr/en; beepDue true only on the rising edge and not again within 10 s; startData returns Polygon/LineString/Point features; startLayers night colours have g = b = 0
    - Browser: with the line set and the timer running the "start-zone" source holds a Polygon and #start-now shows a time or —
  </behavior>
  <action>
Fill the displays of D-03a/b/c on the Task 1 path, model per H-03, contract additions exactly as
listed in the context section (additive keys only).

1. src/jabuka/nav/start.py — pure geometry (radians, nm, kn; local frame centred on the line
midpoint with geo.to_local / geo.from_local; TWA = wrap_pi(TWD - heading), positive = starboard,
heading = TWD - TWA as in nav/laylines.py):
tack_headings(hdg, twd, up_twa_deg) -> ((h_now, twa_now_deg), (h_other, twa_other_deg)) with the
beat-angle clamp (|twa| < up_twa -> sign(twa or +1) x up_twa) and the other tack mirrored about TWD
with the same |TWA|; ray_to_line(px, py, hdg, ax, ay, bx, by) -> (dist_nm | None, on_line) forward
intersection with the infinite line through the ends (None when parallel within 1e-9 or behind);
course_normal(a, b, mark_xy | None, twd) -> unit normal towards the course side (the mark's side,
else windward u(TWD)); convex_hull(points) (Andrew monotone chain); zone_ring(a, b, n, twd, tws_kn,
polar, settings, remaining_s, lat0, lon0) -> [[lon, lat], ...] closed ring rounded to 5 decimals:
for every heading h in steps of ZONE_STEP_DEG = 5, v = efficiency_for(|twa|, efficiency,
efficiency_up, efficiency_down) x polar.speed(tws, |twa|) x u(h), kept when v . n > 1e-6; hull of
the line ends and of A - T' v, B - T' v with the effective time T' = max(0, remaining_s -
settings.start_tack_s) / 3600 h (O-01: one tack or gybe assumed); None when nothing is kept, no
wind or T' <= 0. Speed for a time: efficiency_for(...) x polar.speed(...); below 0.05 kn the
time is None. Constants TACK_NOW_WINDOW_S = 10.0, ZONE_STEP_DEG = 5.
start_block additions: line.length_nm and line.bearing_t (geo.bearing_distance committee -> pin)
when both ends exist; wind from msg["wind"] (twd_t, tws_kn; unusable when the block is None, source
"NONE", stale true or values non-numeric), heading and position from msg["boat"] (hdg_t, lat, lon),
up TWA from polar.targets(tws_kn).up_twa, course side from msg["mark"] lat/lon; reason precedence
as in the behavior block; now/other dicts per the contract (t_s and margin_s rounded to 0.1,
other.t_s + settings.start_tack_s, margins only while the timer runs); tack_now per the behavior;
zone only while the timer runs (needs line + wind, not the position); start_tack_s echoed. Start
mode never reads settings.tack_penalty_s (O-01). The
geometry part runs in its own try/except inside start_block: on an exception reason "calc_error",
now/other/zone null, tack_now false, logged once per distinct error message (the timer part is
built before it and always survives). Extend the module docstring with the model (H-03: measured
wind, derated polar x efficiency, beat-angle clamp, mirrored other tack, start_tack_s as the one
tack cost on the other tack and in the zone, no current, no acceleration, zone = VMG with tacks
over T', crossing towards the course side).

1b. src/jabuka/nav/settings.py (O-01, the only change in this file): a new "# -- start mode
(quick 261110-cuk)" block right after the routing block (after route_current) with
start_tack_s: float = _f(10.0, "Départ : durée d'un virement (s)", ge=0.0, le=60.0). Réglages
renders it from the schema with no reglages.js change. Do not touch tack_penalty_s or any other
field; router_service.py and route/ are not edited (routing triggers do not depend on the settings
version, so a change of start_tack_s never reroutes).

2. src/jabuka/web/static/start_logic.js: extend startView with lineInfo (t("start.lineInfo") with
fmtDistance and fmtHeading from helm_logic.js, display from nav.display), now/other rows {label,
time (fmtTimer of t_s or "—"), margin (fmtSigned), cls ("good" when |margin| <= 5, "bad" when
margin < -5, "" otherwise), offLine suffix}, reason text, tackNow; add beepDue(prev, tackNow,
nowMs) -> {beep, state} (rising edge, BEEP_GAP_MS = 10000), startData(block) -> {zone, line, ends}
FeatureCollections, startLayers(theme) -> fill + outline of "start-zone", line "start-line", circles
"start-ends"; day colours readable on the basemap, night pure red only (g = b = 0, fill opacity
<= 0.2).

3. src/jabuka/web/static/start.js: render the new rows (#start-line-info, #start-now, #start-other,
#start-alert) and on tackNow add class "tack-now" to #start-panel with t("start.tackNow"); beep:
a lazily created AudioContext unlocked/resumed by a capture-phase pointerdown on window while the
panel is visible (Android needs a gesture; insecure origin is fine for Web Audio), three short
tones (about 150 ms, 1 kHz) when beepDue says so, everything in try/catch (no audio = visual alert
only); map overlay "start" exactly like route.js (ensureMap -> registerOverlay("start", {sources,
layers: startLayers}), setOverlayData on change, setOverlayVisible(false) when the block is
absent), the map staying optional.

4. src/jabuka/web/static/app.css: rows for the times (tabular-nums, the good/bad classes) and
#start-panel.tack-now inverted like .primary-box.cue (background var(--bad), text var(--bg)),
colours from theme vars only.

5. src/jabuka/web/static/i18n.js: start.* keys fr/en/sl for: line info ("Ligne {d} · {h}"), "Ligne
au cap", "Autre bord", the time/margin line ("{t} · marge {m}"), "hors ligne", the tack alert
("VIREZ POUR LA LIGNE"), the reasons (line incomplete, no GPS position, heading unknown, no wind,
start computation error); the settings label start_tack_s in SETTINGS_FR ("Départ : durée d'un
virement (s)", exactly the schema label: tests/test_i18n.py checks it), SETTINGS_EN ("Start: tack
duration (s)") and SETTINGS_SL (proposal, to proofread); regenerate docs/I18N-SL-REVIEW.md.

6. Tests: write the behavior cases first in tests/nav/test_start.py (RED), then implement (GREEN).
tests/web/test_start_api.py: feed GPS (_feed_gps with a heading via COG, or the fastnet wind
helper which carries heading) and wind, set the line by ping + typed, start the timer, assert the
nav start block numbers against an independent recomputation and a closed zone ring; a no-wind
core gives reason "no_wind" and zone null with the timer still counting; the settings cases of the
behavior block through PUT /api/settings {base_version, patch: {"start_tack_s": ...}} (0/60 ok,
-1/61 -> 422, other.t_s follows start_tack_s and ignores a tack_penalty_s change). tests/test_start_logic.py:
the node cases of the behavior block. tests/ui/test_start_ui.py: after the line and 5:00, wait for
window.jabuka.map.getSource("start-zone") data with a Polygon feature and #start-now non-empty.

Commit (explicit paths only): "feat(quick-261110-cuk): mode départ — temps à la ligne, marges, alerte virement + bip, zone de départ, réglage start_tack_s (D-03, O-01)" with the Co-Authored-By trailer.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv313/bin/python -m pytest -q tests/nav/test_start.py tests/web/test_start_api.py tests/test_start_logic.py tests/ui/test_start_ui.py tests/test_i18n.py tests/nav/test_nav_tracer.py tests/test_helm_logic.py tests/test_route_logic.py tests/nav/test_settings_core.py tests/web/test_api_seams.py tests/ui/test_reglages.py tests/nav/test_heavy_wind.py && .venv/bin/python -m pytest -q tests/nav/test_start.py tests/web/test_start_api.py tests/test_start_logic.py tests/nav/test_settings_core.py</automated>
  </verify>
  <done>With a pinged/typed line, live wind and the timer running: the panel shows the time to the line on the current heading and on the other tack with signed margins, the map shows a closed zone that shrinks as the timer runs, and the TACK alert + one beep fire when the other-tack margin reaches zero; without wind/position/heading/line the times read — and no zone, never an error. Réglages shows « Départ : durée d'un virement (s) » (10 s, 0-60) which drives only the other-tack time and the zone; tack_penalty_s and routing are untouched. Unit, API, node and browser tests green; committed.</done>
</task>

<task type="auto">
  <name>Task 3: docs (TABLET-SETUP §11, runbook, Slovenian card), night + layout checks of the start panel, full gate</name>
  <files>docs/TABLET-SETUP.md, docs/COMMISSIONING.md, docs/COMMISSIONING-SL.md, tests/ui/test_start_ui.py, src/jabuka/web/static/app.css</files>
  <action>
H-05, H-06, HELM-03 (night start at 20:00).

1. docs/TABLET-SETUP.md: new "## 11. Start mode — Mode départ" after §10 and before the
night-before checklist (do not renumber §1-§10; tests/commissioning/test_runbook_docs.py checks
"TABLET-SETUP §N" references). Same bilingual style as the other sections, short: open with
DÉPART; ping each end with the GPS antenna next to the committee boat's flag / the pin buoy
(« Ping comité », « Ping bouée »), or type the ends in degrees + decimal minutes like a mark; press
5:00 at the 5-minute signal (19:55 for the 20:00 start), SYNC at each later signal (rounds to the
nearest minute; under 0:30 it means "the gun is now"), STOP if the start is postponed, « Fermer le
départ » to leave; what the numbers mean (Ligne au cap / Autre bord, marge = temps restant - temps
à la ligne, positive = time to burn) and the model (measured wind, polar x efficiency, beat angle
when pinching, other tack mirrored about the wind, + « Départ : durée d'un virement (s) » from
Réglages (start_tack_s, 10 s by default, 0-60, start mode only: the router's « Pénalité de
virement » is a different setting and is not used here); no current, no acceleration); the zone
(its edge = reach the line exactly at the gun at full VMG after one tack of start_tack_s; inside =
time to burn; outside = late; it disappears in the last start_tack_s seconds);
the TACK alert + beep (tap the panel once after loading the page so the tablet may play sound);
at the gun start mode closes and routing goes on to the first mark unchanged; survives a page
reload; after a power cut the line is kept and the timer too once GPS time is valid. Add one line
to the night-before checklist ("Mode départ : ping, 5:00, SYNC, rechargement, Fermer").

2. docs/COMMISSIONING.md §7 Parcours: one table row after 13:20 for the dock drill (DÉPART, Ping
comité, saisie de la bouée, 5:00, SYNC, recharger la page, Fermer; on doit voir: chrono conservé,
ligne affichée) referencing "TABLET-SETUP §11", plus one sentence that the real line is pinged at
sea before the warning signal. Keep every §7 keyword the runbook test requires (IC, Côtés
confirmés, 30 s, inscription, Pitfall 19).

3. docs/COMMISSIONING-SL.md: a "## Start (DÉPART)" section of at most 5 lines in Slovenian (draft
like the rest of the card), naming the on-screen French words (DÉPART, Ping comité, Ping bouée,
SYNC, VIREZ POUR LA LIGNE); the card stays <= 80 lines with its glossary words.

4. tests/ui/test_start_ui.py: add (a) layout at 1280x800 and 1024x600 landscape with start mode
open: #start-panel does not intersect #helm-col nor #map-ctrls, its bottom stays above the middle
of the map area (the boat at the map centre stays visible), no horizontal page scroll; portrait
600x1024: panel visible, no intersection with #map-ctrls nor #helm-col; (b) night: click
#night-toggle, wait for body.theme-night, then every visible element of #start-panel and
#start-ctrls has colour / background / border colours with g = b = 0 (reuse the colour-check JS
of tests/ui/test_helm_column.py lines 115-142, selector changed). Adjust only the start-mode
section of app.css if an assertion fails; never the existing helm rules.

5. Full gate: bash scripts/check.sh (ruff + pytest on .venv 3.14 and .venv313; the UI tests run on
.venv313). Record pass/skip counts per venv in the summary next to the baseline (STATE.md: 1915
passed on each venv). Note in the summary that the src/jabuka fingerprint changed, so the soak and
freeze evidence predates this code (docs/SOAK.md is not touched, H-07).

Commit (explicit paths only): "docs(quick-261110-cuk): mode départ — TABLET-SETUP §11, runbook §7, carte SL; tests nuit et mise en page" with the Co-Authored-By trailer. Do not push, do not deploy.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q tests/commissioning/test_runbook_docs.py tests/ui/test_start_ui.py && bash scripts/check.sh</automated>
    <human-check>On the real tablet at the dock (end of phase): after one tap on the start panel, the TACK alert beep is audible; in night mode the panel, zone and line are red on black with no white or green; the panel leaves the boat visible on the map in landscape.</human-check>
  </verify>
  <done>TABLET-SETUP §11, the runbook row and the Slovenian card describe ping, timer, SYNC, numbers, zone and alert; the start panel passes the layout and night checks in a real browser; bash scripts/check.sh prints "check: ok"; committed, not pushed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| tablet/laptop on the boat Wi-Fi -> core REST | untrusted JSON bodies (line ends, timer actions) cross here; any AP client can call them (no auth, same as the course API) |
| start.json on the SD card -> StartStore | a torn or corrupted file after a power cut must not break the core |
| start block -> nav tick | a start-mode bug must never stop the 1 Hz nav tick that drives the helm |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-cuk-01 | Denial of service | NavService._add_start / start_block | high | mitigate | Own try/except around start_block (block {"open": true, "error": true}, start_errors counter, never nav.errors); geometry in a nested try (reason calc_error); isolation test patches start_block to raise and compares every other nav block |
| T-cuk-02 | Tampering | start_api bodies | medium | mitigate | Pydantic extra="forbid", allow_inf_nan=False, Literal end/action, lat 42-45 / lon 14-17; harden() JSON-only + 64 KiB cap already applies; 422 tests for NaN, extra key, unknown end, out-of-area |
| T-cuk-03 | Tampering | start.json | medium | mitigate | atomic_write_json + load_json_status .bak fallback; restored "bak"/"unreadable" shown on the panel; write-then-commit so a failed write changes nothing (503) |
| T-cuk-04 | Denial of service | start.js on the helm page | high | mitigate | Separate module in app.js MODULES (own try/catch), every render and the 250 ms timer in try/catch, DOM outside #helm-col; Playwright test asserts no console errors |
| T-cuk-05 | Spoofing | any AP client can ping/close/sync | low | accept | Closed WPA2 boat network, same trust model as the course and settings APIs; every action is an events-log line |
| T-cuk-06 | Repudiation | start actions | low | mitigate | One fsync'd events-log line per open/close/ping/typed/timer_start/sync/stop/gun with t_mono, t_wall, utc |
| T-cuk-07 | Tampering (XSS) | panel rendering | low | mitigate | textContent only; node test checks the start files never assign HTML strings |
</threat_model>

<verification>
- Source audit (all COVERED): GOAL "mode départ" -> Tasks 1-3; D-01 -> Task 1 (ping, typed, start.json, events) ; D-02 -> Task 1 (5:00, SYNC, STOP, Fermer); D-03a -> Task 2 (zone_ring + overlay); D-03b -> Task 2 (now/other times, margins); D-03c -> Task 2 (tack_now, alert, beep); D-04 -> Task 1 (gun closes, routing untouched); D-05 -> all three tasks; H-01 -> Task 1 (_add_start isolation, key absent when closed) + Task 3 layout; H-02 -> Task 1 (nav/start.py, gun_mono/gun_utc, reload test); H-03 -> Task 2; H-04 -> Tasks 1-2 (i18n keys, review sheet); H-05 -> Task 3; H-06 -> Tasks 1-3; H-07 -> every commit; O-01 -> Task 2 (start_tack_s setting, labels, other-tack time, zone T') + Task 3 (doc); REQ HELM-01/02/03, CRSE-05, DATA-07 -> Tasks 1-3. No deferred ideas exist for this task.
- Closed start mode: GET /api/nav keys identical to tests/fixtures/nav/tracer_nav.json shape (tests/nav/test_nav_tracer.py green).
- git diff of src/jabuka/core/nav_service.py touches only the import, __init__ (two attributes), update() (one call) and the new _add_start; no file under src/jabuka/route/, src/jabuka/nav/laylines.py, src/jabuka/nav/course.py or src/jabuka/core/router_service.py changes; git diff of src/jabuka/nav/settings.py adds only the start_tack_s block (tack_penalty_s line unchanged).
- bash scripts/check.sh prints "check: ok".
</verification>

<success_criteria>
- The owner can, on the tablet: open start mode, ping both ends (or type them), start 5:00 at the 5-minute signal, SYNC at later signals, reload the page without losing the countdown, read time to the line + margin on both tacks, see the shrinking start zone, get a TACK alert + beep, and see start mode close at the gun.
- No change in behaviour of the helm, laylines, routing, rounding FSM or the existing nav fields; start-mode failures are contained.
- fr/en/sl complete, docs updated, full gate green on both venvs, three commits with the trailer, nothing pushed or deployed.
</success_criteria>

<output>
Create `.planning/quick/261110-cuk-mode-depart-start-timer-ligne-ping-zone/261110-cuk-SUMMARY.md` when done (pass/skip counts per venv vs the 1915 baseline, the decisions taken under "Claude's discretion", the fingerprint note).
</output>
