# Routing

Weather routing for Regata Jabuka (Phase 3). This document grows section by section: the land
mask first (plan 03-01), then the router and the race-day procedure (plans 03-03, 03-06).

## Land mask (never cross land, ROUT-11)

The router may only produce routes whose every segment stays in clear water. "Clear" is decided
on a raster built on the laptop and copied to the Pi in the race pack:

- `landmask.npz`: two boolean grids, packed with `np.packbits` along the rows.
  - `mask` (what the router uses): land + shore margin, charted hazards + hazard margin, and
    submerged rocks as small discs.
  - `raw`: land only. Used to get out of the margin when the boat starts inside it (marina,
    close to shore): the exit segment only has to avoid real land.
- `landmask.json`: sidecar with the sha256 of the npz, the OSM timestamps, the cell size,
  the margins and the hazard counts.

The Pi loads the npz with numpy only (`np.load(..., allow_pickle=False)`, every key, dtype and
shape checked). Shapely and the network are only used on the laptop.

### Data sources

| Layer | Source | Notes |
|---|---|---|
| Land | OSM `natural=coastline` via Overpass, bbox 42.7–44.1 N, 14.9–16.4 E | Ways merged and polygonized; each face classified with the OSM rule "land on the left of the coastline direction". Zero unclassified faces is required. |
| Hazards | OSM seamarks via Overpass: rocks, `beacon_isolated_danger`, `buoy_isolated_danger`, wrecks, obstructions, `natural=reef/shoal` | Same bbox. |
| Hand hazards | Built in: Plić Sestre beacon (node 498394251) and rock (node 8883790953) | Always added, even if OSM loses them. |
| Extra hazards | `--hazards FILE.geojson` | Dangers seen on the paper chart or in the sailing instructions. |

OSM data © OpenStreetMap contributors, ODbL 1.0. The committed test fixture
(`tests/fixtures/route/landmask_race_25m.npz`) carries its attribution in
`tests/fixtures/route/ATTRIBUTION.md`.

### Defaults

| Setting | Default | Flag |
|---|---|---|
| Cell size | 25 m (5334 x 4199 cells over 15.0–16.3 E, 42.8–44.0 N) | `--cell-m` |
| Shore margin | 100 m around all land | `--shore-margin-m` |
| Hazard margin | 200 m around awash/covering rocks, isolated-danger marks, wrecks, obstructions, reefs, shoals and the hand hazards (points are 50 m discs, ways a 25 m buffer, before the margin) | `--hazard-margin-m` |
| Submerged rocks | 50 m discs, no extra margin (depth unknown in OSM; 757 in the race area) | `--submerged-rocks` / `--no-submerged-rocks` |

Segment checks are exact on the raster: every cell a segment passes through is looked up, never
just the endpoints. A coarse 200 m grid first skips segments far from anything blocked; the
answer is the same as the exact pass (tested on 5000 random segments).

### Gap rule and the channels of the course

A gap of width `g` between two obstacles stays open when `g > 2 x margin + 2 x cell` (hazard
discs inside the gap count too). With the defaults that is 250 m. The guaranteed clearance from
real land is about `margin - 0.71 x cell`, i.e. 82 m.

Channel widths measured in research (exact polygon distance, OSM 2026-11-06):

| Gap | Width | Default mask | Course |
|---|---|---|---|
| Prvić–Tijat | 1065 m | open (narrowest point of Vodice → open sea, 43.7229 N 15.7828 E) | required |
| Prvić–mainland (Vodice side) | 824 m | open | alternative exit |
| Galijola–Prvić | 549 m | open by the gap rule (hazard discs inside not checked) | — |
| Obonjan–Zmajan | 419 m | open by the gap rule (hazard discs inside not checked) | — |
| Logorun–Tijat | 412 m | open by the gap rule (hazard discs inside not checked) | — |
| Obonjan–Sestrica Vela | 288 m | closed on purpose (too tight at night) | — |
| Kamenica–Tijat | 260 m | closed on purpose | — |
| Prvić–Lupac | 255 m | closed on purpose | — |

Raising the shore margin to about 400 m still leaves the course feasible but closes
Prvić–mainland. At 450 m the Prvić–Tijat check fails.

### Rebuild

On the laptop, with internet (Overpass answers are cached in `var/cache/prep/` and reused):

```bash
.venv/bin/python -m jabuka.prep.land build --out var/racepack
# offline rerun from the cache (e.g. on the boat):
.venv/bin/python -m jabuka.prep.land build --out var/racepack --offline
# force a fresh download:
.venv/bin/python -m jabuka.prep.land build --out var/racepack --refresh
# extra dangers from the chart (GeoJSON in lon/lat; Points, LineStrings, Polygons; max 5 MB):
.venv/bin/python -m jabuka.prep.land build --out var/racepack --hazards dangers.geojson
```

`build` always ends with `check` and exits 1 when a required channel is closed: do not copy
that mask to the Pi; lower the margins or fix the extra hazards instead.

If overpass-api.de refuses connections (it did on 2026-11-06 from the build laptop), use a
cached answer: the cache file name is `osm-<first 16 hex of sha256(query)>.json`, holding an
Overpass `out geom` JSON. The committed fixture was built that way (see its ATTRIBUTION.md).

### Reading the check report

```bash
.venv/bin/python -m jabuka.prep.land check var/racepack
```

It prints the cell size, margins, OSM timestamp and blocked fraction, verifies the sidecar
sha256, then one line per required sea point: the Vodice start, the open sea to the south-west
and the rounding anchors of Plić Sestre (0.3 nm), Jabuka (0.6 nm), Blitvenica (0.55 nm) and
Mulo (0.5 nm), each with its geodesic distance by water from Vodice (200 m grid; `-` when that
coarse grid closes a narrow channel the fine raster keeps open) and `ok` or the reason it fails
(`dans le masque`, `inaccessible`, `hors de la grille`). The last line is the Prvić–Tijat
passage: every cell within 0.1 nm of its narrowest point must be clear (`ouvert`). Exit code 0
means every required point is reachable by water from Vodice.

### What the mask does not know

Absence of a hazard in OSM is not proof that the water is clear. Check the paper chart around
Jabuka and Blitvenica in particular (OSM shows no hazard within 1.5 nm of either) and add what
you find with `--hazards`. Submerged rocks have no depth in OSM; they are all kept as 50 m discs
by default, which closes no required channel.

## Router (isochrones, ROUT-01/03/04/07/08)

`jabuka.route.isochrone.route(RouteRequest, RouterEnv) -> RouteResult` is a pure numpy function
run in the routing worker (`jabuka.route.cycle`). Per step it samples the GRIB wind once per
front point (bias applied, current subtracted: the polar sees the wind over the water), expands
|TWA| 30-180 deg every 5 deg plus the VMG targets on both tacks (heading = TWD - TWA), slows the
boat by the wave factor `max(0.70, 1 - k Hs)` (k = 0.05 / 0.03 / 0.015 per m below 60 / 60-120 /
above 120 deg TWA; Hs from `waves.npz`, else estimated from TWS) and adds the current to the
displacement. Pruning keeps, per 1.5 deg bearing sector from the leg origin, the candidate
closest to the mark by water (precomputed `geofields.npz`, else a 400 m field computed on
demand), land-checking only the best 4. Steps are 10 min near land, near the mark and in the
first hour, 15 min to 3 h, 30 min beyond. Arrivals are exact: a direct shot, or two boards on the
VMG targets inside the upwind/downwind cone (the layline tack is not rounded to a step).

The course is routed mark by mark through rounding waypoints on a circle of the mark's radius,
on the required side (starboard clockwise, port counter-clockwise, one waypoint per 90 deg of
turn; a mark passed while the course bends away from it gets an abeam waypoint plus an entry
waypoint, no loop). Every shipped polyline (at most 300 points after mask-aware decimation) is
re-validated against the mask; an invalid one is never returned.

One worker cycle (`run_cycle`) answers both questions from the same snapshot: the optimal route
for the whole remaining course, and the forced route for the current leg held on the boat's tack
until the advised tack + 5 min ("On reste"; released with "virement imposé (terre)" when the held
tack runs into land). Cost of not tacking = max(0, forced leg ETA - optimal leg ETA). When the core
passes the current route, it is re-sailed under the new wind for the hysteresis rule.

Race-pack step on the laptop, after `land build`:

```bash
.venv/bin/python -m jabuka.prep.cli geofields --marks src/jabuka/nav/data/marks.json --out var/racepack
```

## Banc d'essai Pi (porte du 2026-11-09)

The gate decides whether the Raspberry Pi 3B runs the router at full settings (L0) or degraded
(L1-L5), or not at all (the boat then races on the Phase 2 laylines; routing never blocks
Phase 4).

### Prepare (laptop, same day)

1. Build the pack: `jabuka-prep wind`, `jabuka-prep waves`, `jabuka-prep land build`, then the
   `geofields` step above (`python -m jabuka.prep.cli ...` until plan 03-05 adds the console
   script). The committed fixture pack also works (`--fixture`, 24 h of real ICON-EU wind).
2. Copy to the Pi: the repository `src/` and `tests/fixtures/` (rsync of the checkout is
   fine) and `var/racepack/`.
3. On the Pi, a scratch venv with numpy only (the Pi lock gets numpy in plan 03-05):

```bash
python3 -m venv /tmp/bench-venv
/tmp/bench-venv/bin/pip install numpy==2.5.4      # from the wheelhouse if offline
```

### Run

```bash
cd ~/jabuka
PYTHONPATH=src /tmp/bench-venv/bin/python -m jabuka.route.bench --pack var/racepack \
    --runs 3 --json var/bench-pi.json
# or, without a pack: --fixture   (smoke run: --quick = L0 and L1, 1 run)
```

Each cycle is the real worker job (optimal Course A or B from Vodice + forced current leg)
through the forkserver worker pool at nice +10, while a 100 ms asyncio ticker in the bench
process measures how late the event loop gets (the core's 1 Hz tick proxy).

### Read the table

| Column | Meaning |
|---|---|
| p50 / p95 / max s | cycle time (optimal + forced routing) over runs x courses |
| optimal ms / forcé ms | median time of each routing inside the worker |
| RSS Mo | worker resident memory after routing |
| étapes | isochrone steps of the slowest cycle |
| ETA h | mean whole-course ETA (sanity: the levels should agree within a few %) |
| gigue ms | worst lateness of the 100 ms ticker while routing |
| charge | L4/L5 only: average worker busy fraction per cadence |
| OK | the gate rule below |

**Rule: the first level with p95 <= 30 s and jitter <= 200 ms passes.** The bench prints
`NIVEAU RECOMMANDÉ : Lx` (exit 0) or `AUCUN` (exit 1).

### Degraded ladder (CONTEXT order)

| Level | Settings (cumulative) |
|---|---|
| L0 | 5 deg headings + VMG targets, 10/15/30-min steps, 1.5 deg sectors, whole course, 5-min cadence, cost every cycle |
| L1 | 10 deg headings |
| L2 | + 15-min steps for the first hour then 30 min, 2 deg sectors |
| L3 | + route the next mark and one more only |
| L4 | + 10-min cadence |
| L5 | + cost of not tacking every other cycle |

Laptop reference (i7-7700K, Python 3.14, numpy 2.5.4, fixture pack, 3 runs): L0 p95 0.62 s,
L1 0.47 s, L2 0.38 s, L3-L5 0.23 s, worker RSS 111 MB, jitter <= 2 ms. The research
extrapolation for the Pi 3B is x15-x25 (L0 about 9-15 s), so L0 is expected to pass.

### Record

Write in the phase summary (or STATE.md): p50/p95/max per level, jitter, RSS, the CPU
temperature and `vcgencmd get_throttled` at start and end (both in the JSON), and the
recommended level. That level becomes the `route_level` setting in Réglages (plan 03-05).

## À la barre : utiliser la route (opérateur)

Phrases courtes, à lire de nuit. Tout est calculé par le Pi ; la tablette ne fait qu'afficher.

### Lire l'onglet Barre

| Ce qu'on voit | Ce que ça veut dire |
|---|---|
| `TWA ROUTE ↑ 42° tribord` | Barrer cet angle au vent, sur ce bord. ↑ au près, ↓ au portant. |
| `CAP ROUTE 114°M` | Au travers : barrer ce cap (magnétique par défaut). |
| `TWA CIBLE` / `CAP À SUIVRE` | Pas de route valide : ce sont les laylines (Phase 2). |
| `LOFER` / `ABATTRE` / `◄ BÂBORD` | L'écart à la cible de la route. |
| `Virement dans 08:30` | Temps avant le virement de la route. `Empannage dans …` au portant. |
| `VIREZ` (inversé) | C'est maintenant. Reste affiché 2 min. |
| `Route mise à jour…` | Virement conseillé manqué depuis 2 min : le Pi recalcule. Ne pas virer sur l'ancien conseil. |
| `Layline à 1,5 nm` | Distance à la layline (seulement quand le compte à rebours vient des laylines). |
| `Ne pas virer : +4 min` | Ce que coûte de rester sur ce bord (`< 1 min` : sans importance). |
| `Route : il y a 3 min` | Âge de la route. Normal : moins de 5 min (recalcul toutes les 5 min). |
| `Cap route 114°M` / `TWA route 95° bâbord` | L'autre forme de la même cible, pour vérifier. |
| `Biais GRIB +12° ×1.15` | Le GRIB est corrigé par le vent mesuré : +12° de direction, vent ×1,15. |
| `(s'estompe)` | Plus de mesure fiable : la correction diminue avec le temps (τ 2,5 h). |
| `(gelé, Jabuka)` | Zone magnétique de Jabuka : la correction est figée, pas apprise. |
| `Biais GRIB : apprentissage` | Les 10 premières minutes de mesures stables. |
| `Route : niveau L2` | Le Pi tourne en mode allégé (banc). La route reste bonne, moins fine. |
| `Hors route` | Plus de 0,5 nm ou 20° de la route : un recalcul part après 2 min. |

Sur la carte : la route en trait violet (rouge pointillé la nuit), les virements en points, le
prochain virement en gros point.

### ON RESTE

Quand l'appuyer :

- On ne veut pas virer maintenant (risée attendue, trafic, manœuvre pas prête, équipage).
- Le Pi recalcule avec le bord actuel tenu au moins 5 min de plus (Réglages « On reste : marge
  (min) »).
- Le bouton devient `ANNULER ON RESTE`. Le compte à rebours montre le **premier virement
  possible**.
- Fin automatique : au prochain virement détecté (TWA qui change de signe pendant 30 s), ou
  `ANNULER ON RESTE`.

`Virement imposé (terre) dans 01:35` : le bord tenu va vers la terre ou un danger. Il faut virer
avant la fin du décompte, ON RESTE ou pas.

Écran verrouillé (cadenas) : le bouton ne fait rien. Déverrouiller : appui 2 s sur le cadenas.

`On reste impossible : amure inconnue …` : le Pi ne sait pas sur quel bord on est (pas de vent).
Attendre le vent, ou saisir un vent manuel.

### Badge GRIB (bus B&G muet)

- Le badge vent passe à `GRIB` et l'alerte `VENT GRIB (pas d'instruments)` s'affiche.
- Le vent vient du GRIB (corrigé du biais) à la position GPS.
- Cap = COG du GPS, vitesse = SOG. Sous 1 nd : pas de TWA, pas de laylines.
- La route et les laylines continuent. Vérifier le vent à l'œil et sur les répétiteurs B&G.
- Pour l'interdire : Réglages « Vent GRIB sans instruments » sur non.

### Couper la correction du GRIB

Si le biais affiché paraît faux (capteur de vent déréglé, bateau mal calibré) :
Réglages « Correction du GRIB (biais) » sur non. La bande affiche `Biais GRIB désactivé`. La
route suivante utilise le GRIB brut.

### Niveau de routage (banc Pi)

Après le banc du 2026-11-09 (section « Banc d'essai Pi ») : Réglages « Niveau de routage (banc
Pi) » = le `NIVEAU RECOMMANDÉ` du banc. En course, si `Route : il y a` dépasse souvent 10 min ou
si Diag montre des `timeouts` au routeur : monter d'un niveau (L0 → L1 → …).

### Alertes et que faire

| Alerte / ligne d'état | Action |
|---|---|
| `ROUTE INVALIDE : …` | Le Pi a jeté une route qui touchait la terre. Il garde l'ancienne et recalcule. Rien à faire ; si ça se répète, barrer aux laylines et regarder la carte. |
| `MÉTÉO INCOMPLÈTE : …` | Le pack ne couvre pas toute la course (heure, marque). Au-delà, le routeur tient le dernier champ. À quai : refaire le pack (WEATHER-PACK.md). En mer : se méfier de la route en fin de période. |
| `Routage bloqué : heure GPS non valide` | Pas d'heure GPS (antenne, gpsd). Vérifier le GPS sur Diag (`routing: ok`). Barrer aux laylines en attendant. |
| `Pas de pack météo : …` | Pas de `wind.npz` lisible sur le Pi. Recopier le pack, redémarrer le cœur. |
| `Routage en échec : …` | Le calcul a échoué (délai, plantage). Nouvel essai automatique après 1 min. Si ça dure : monter le niveau de routage. |
| `Calcul de la route…` | Premier calcul en cours (quelques secondes, jusqu'à 1 min au Pi). |
| `Routage désactivé (Réglages)` | Réglages « Routage actif » sur oui. |

### Repli : les laylines

Tant qu'il n'y a pas de route valide, l'onglet Barre affiche **les laylines de la Phase 2**
(`TWA CIBLE`, `Virement dans 12 min`, `Layline à 1,5 nm`, `Autre bord`). Rien à faire : la route
reprend la main dès qu'elle revient. La ligne d'état dit pourquoi il n'y a pas de route.

### Diag

La page Diag a une ligne `router` : `pack_ok`, `pool` (jobs, ok, timeouts, crashes, `last_ms`
= durée du dernier calcul), couverture, état ON RESTE, coût. À regarder avant le départ : `pack_ok
true`, `ok` qui augmente, `timeouts 0`.

### Répétition sur le portable (avec internet)

```bash
bash scripts/racepack-dryrun.sh          # pack réel -> var/racepack-dryrun, banc, routage A
```

Le script télécharge ICON-EU et EWAM (fenêtre maintenant + 3 h → + 27 h), construit le masque
terre (OSM), les champs géo, contrôle le pack, lance le banc rapide et route le parcours A depuis
Vodice dans un vrai cœur. Il s'arrête à la première étape en échec. Si Overpass est injoignable
et le cache OSM vide, il s'arrête ; pour une répétition seulement,
`JABUKA_DRYRUN_LANDMASK=tests/fixtures/route/landmask_race_25m` reprend le masque OSM du
2026-11-06 (jamais pour le pack du vendredi).
