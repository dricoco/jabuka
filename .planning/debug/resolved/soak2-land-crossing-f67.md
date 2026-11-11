---
status: resolved
resolution_state: resolved (vérification humaine : soak Pi race-36h n°3 20261111T005058Z PASS)
fix_commit: 0c582d6
trigger: "Soak race-36h Pi n°2 (20261110T220521Z, code aee344df7b52, alim OK throttled 0x0) : FAIL — route adoptée v121 traverse la terre (segment 4) ; f67 course-change : course finished during the fault, no new route (version > 129) within 60 s"
created: 2026-11-11
updated: 2026-11-11
---

## Symptoms

DATA_START
- **Expected:** every adopted route avoids land (check `land`: 0 crossings); after a course-change fault a new route is published within 60 s.
- **Actual (report /home/drico/git/jabuka/var/soak/20261110T220521Z-race-36h/report.md + report.json, timeline.jsonl, samples.csv, proc/*.log, console.log):**
  1. **TOP PRIORITY — possible real race defect:** check `land`: "291 adopted routes re-validated; crossing land: versions [121] at segments [4]". One adopted route (version 121) crosses land at segment index 4. Determine: which course/legs/marks, where (lat/lon), when (sim/real time, which fault window), whether the router's own land check (landmask / segment validation in src/jabuka/route/) let it through or the soak re-validation is stricter/different (resolution, raw vs buffered mask, segment sampling), and whether this can happen on the real boat. Fix the root cause if it is in the app (with regression test); if it is a check-mismatch in the harness, prove it with numbers.
  2. f67 course-change (sim 66144 s, real 3317 s): "course finished during the fault: next course selected; no new route (version > 129) within 60 s"; route_after_recovery missing after f67. All other faults passed (recovery bus/gps/process/power/watchdog all within budget, persistence OK, 0 unexpected tracebacks). Previous debug session (.planning/debug/resolved/soak-route-not-refreshed.md, commit 35a61a7) changed baselines to last_route_version(); here the course finished during the fault and the next course was selected — check whether route versions renumber on course switch (RouterService.restore / course finished A->B) so "version > 129" is again unreachable (harness), or whether routing really stalled.
- **Timeline:** second system-scope soak after harness fixes 35a61a7; first one with stable power.
- **Reproduction:** Pi soak `sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M` (~1 h 50). Harness: src/jabuka/soak/, src/jabuka/tools/soak.py. Router: src/jabuka/core/router_service.py, src/jabuka/route/ (isochrone, landmask, rounding, stay).
DATA_END

## Constraints

- Race is 13 Nov 2026. Symptom 1 first and fully.
- Do NOT touch the Pi (192.168.64.169) — analysis from the copied report only; no deploy, no soak rerun. Local tests only.
- Never touch cad/, stl/, hardware/, docs/SOAK.md, nor the quick-tasks table in .planning/STATE.md. Stage by explicit path only; no git add -A/stash/reset/clean; no push. Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". Do not stage docs/I18N-SL-REVIEW.md.bak, uv.lock, orc/, cad/ changes in the working tree.
- pytest is .venv313/bin/pytest; full gate `bash scripts/check.sh` (UI test test_switch_to_slovenian_then_english_persists_and_fits known flaky).
- The user is AFK and authorized fixing directly; if a decision is truly needed, record it in the session file and return a checkpoint (do not block on AskUserQuestion).

## Current Focus

bug_class: Bohrbug (déterministe pour une géométrie donnée). S1 et S2 sont tous deux des défauts du harnais ; aucun défaut de l'app n'a été trouvé. RÉSOLU : vérifié par le soak Pi n°3 (20261111T005058Z), PASS.

S1 CONFIRMÉ : v121 = faux positif du harnais. Le routeur valide sa polyligne exacte (nm, non arrondie) ; le cœur publie [round(lon, 6), round(lat, 6)] ; le harnais re-valide ces coordonnées arrondies avec le contrôle raster exact à tolérance nulle. L'arrondi déplace chaque point d'au plus 4,0 cm (x) / 5,6 cm (y), soit 6,9 cm ; un segment livré qui frôle la marge dilatée (100 m) à quelques mm/cm bascule « bloqué ». Distance à la terre réelle >= 92 m dans les cas reproduits : pas de risque à bord.

S2 CONFIRMÉ : trois défauts du harnais combinés (voir Evidence) : (a) base « version > 129 » = dernière route vue d'un processus mort (le cœur redémarré à 3293,7 s affichait version 0, no_course) ; (b) course_upkeep agit sur un nav périmé « finished » 0,2 s après la sélection de B par f67 et rebascule B -> A (faux constat « course B finished ») ; (c) wait_sim n'appelle course_upkeep que si le planning est en avance : f66/f67 en retard, le parcours terminé à sim 64215 s n'a jamais été relancé avant f67 (f66 stay-toggle a passé à vide, 0 route). Le routage n'a pas calé : v1 adoptée 36,3 s après la sélection (budget 60 s).

reasoning_checkpoint:
  hypothesis: "Le contrôle land du soak échoue sur v121 parce que le harnais re-valide les coordonnées publiées arrondies à 1e-6° avec un contrôle raster exact à tolérance nulle, alors que le routeur a validé la géométrie non arrondie ; un frôlement de la marge dilatée de quelques cm suffit."
  confirming_evidence:
    - "Balayage de 3200 requêtes (2400 routes acceptées par le routeur) sur le pack soak reconstruit, même jambe/zone/heure que v121 : 3 échecs du contrôle harnais, tous avec la géométrie non arrondie valide (clairance 1,2 mm / 5,2 mm / 35,4 mm au masque dilaté) et la géométrie publiée bloquée ; terre brute à >= 92,8 m (ou aucune terre brute à proximité : marge de danger)."
    - "Déplacements d'arrondi mesurés : <= 3,8 cm en x, <= 5,5 cm en y (borne théorique 4,04 / 5,56 cm, 6,87 cm en norme)."
    - "Forme identique à v121 : start_in_margin True, 11-12 points (v121 : 9), segment fautif au milieu/fin de route (v121 : 4)."
    - "Aucune autre différence de géométrie : même cadre (env.frame = mask.frame), même landmask.npz, display_points sans effet (< 300 pts), shown = opt pour kind optimal, pas de redémarrage du cœur autour de v121."
  falsification_test: "Une route publiée dont un point s'enfonce de plus de 6,87 cm dans une case bloquée (profondeur échantillonnée) ne peut pas venir d'une route valide du routeur ; si v121 avait été dans ce cas, l'hypothèse tomberait — la géométrie exacte de v121 n'étant pas dans le rapport, la preuve est statistique (même mécanisme reproduit 3 fois, 0 faux négatif de l'autre côté)."
  fix_rationale: "Le harnais re-valide désormais à la précision de publication : un segment signalé par le contrôle exact n'est accepté que si sa profondeur maximale dans les cases bloquées (distance à la case libre la plus proche, échantillonnée au cm) est <= la borne d'arrondi 6,87 cm. C'est une condition nécessaire satisfaite par toute route valide du routeur (sans faux positif), et toute vraie traversée (des mètres) reste rejetée. Aucune modification de l'app (pas de risque la veille de la course)."
  blind_spots: "La géométrie exacte de v121 n'a pas été conservée par le harnais (seuls version/n_points/bad_index) : impossible de mesurer sa profondeur réelle a posteriori ; le correctif enregistre désormais la profondeur (graze_m) pour que le prochain soak la chiffre."
  candidate_causes:
    - "code (harnais) : re-validation sur coordonnées arrondies sans tolérance — CONFIRMÉ"
    - "code (app) : route non validée publiée (composition stay, restore, display_points) — ÉLIMINÉ"
    - "data : masque différent entre routeur et harnais — ÉLIMINÉ (même fichier, même cadre)"
    - "environment : bateau simulé dans la terre (simulateur sans terre) — contexte, rend le départ en marge fréquent mais n'explique pas le segment 4"
  and_gate: "non pour S1 (l'arrondi seul suffit, reproduit en eau libre avec start_in_margin False aussi : 58680 s). Oui pour S2 : (a) seul suffit à l'échec ; (b) et (c) sont des contributeurs (faux constat, course relancée trop tard)."

next_action: aucune — session résolue. Vérification humaine faite sur le soak Pi race-36h n°3 (20261111T005058Z, code 0c582d6) : PASS, voir Resolution.verification.human_verify.

## Evidence

- timestamp: 2026-11-11
  checked: report.json routes[146] et timeline.jsonl
  found: v121 adoptée à wall 2939,7 s (sim ≈ 58590 s), kind "optimal", 9 points, start_in_margin True, bad_index 4 ; c'est la première route optimale après la fin du stay-toggle f59 (cleared_wall 2938,2) ; v120 = stay (11 pts), v122 (7 pts, 8 s plus tard) land_ok True. Aucun redémarrage du cœur entre 2920 et 2978 (f60 watchdog-hang démarre à 2950).
  implication: la route vient directement de route() (shown = opt), pas d'une composition stay ni d'un restore.

- timestamp: 2026-11-11
  checked: tablet.route_states autour de 2900-2995 s
  found: 2910 'outdated 118 virement manqué : nouvelle route impossible' ; 2931 'outdated 119 le routeur échoue : départ dans la terre : aucune eau libre à 1 nm' ; 2934 v120 ; 2939,7 v121.
  implication: le bateau simulé était dans la terre juste avant v121.

- timestamp: 2026-11-11
  checked: synth.log (progress) classé contre tests/fixtures/route/landmask_race_25m.npz (cellule 25 m, marge 100 m)
  found: t sim 58020 MARGIN, 58080-58380 RAWLAND (le bateau simulé traverse une île à 43,664-43,670 N / 15,628-15,639 E), 58440-58500 clear, 58560 MARGIN, 58620+ clear.
  implication: v121 calculée avec un départ dans la marge côtière (cohérent avec start_in_margin True) ; le simulateur ne respecte pas la terre (artefact du harnais, pas un scénario réel), mais le routeur doit quand même ne jamais adopter de route traversant la terre.

- timestamp: 2026-11-11
  checked: src/jabuka/route/isochrone.py _route(), src/jabuka/core/router_service.py route_message(), src/jabuka/soak/tablet.py _validate()
  found: le routeur valide les points livrés (xs, ys en nm, non arrondis) : validate_polyline(xs[v0:]) sur le masque dilaté + raw_segments_clear sur le segment de sortie si start_in_margin. Le cœur publie [round(lon, 6), round(lat, 6)] (display_points sans effet sous 300 points). Le harnais recalcule frame.to_xy(lat, lon) des coordonnées arrondies et applique la même règle (v0 = 1 si start_in_margin). Même cadre (env.frame = mask.frame), même fichier landmask.npz.
  implication: seule différence de géométrie entre les deux contrôles : l'arrondi à 1e-6° (0,111 m en lat, 0,080 m en lon) ; bad_index 4 = segment 4->5 sur le masque dilaté.

- timestamp: 2026-11-11
  checked: balayage routeur (scratchpad/repro.py) sur le pack soak reconstruit, t sim 58440-58650 pas 10 s, tack0 ±1, sans biais, polaire par défaut, L0
  found: 44/44 routes OK, 8 à 11 points (v121 : 9), start_in_margin True entre 58520 et 58600 ; 0 échec du contrôle harnais après arrondi.
  implication: reconstruction fidèle de la forme des routes ; le cas exact n'est pas reproduit avec ces entrées (vent mesuré, biais, position exacte inconnus) : il faut mesurer les clairances.

- timestamp: 2026-11-11
  checked: scratchpad/repro2.py — clairance exacte (distance segment / carré de case bloquée) de chaque segment livré, 56 routes 58500-58620 s, biais k ∈ {aucun, 1,11} × dTWD ∈ {0, ±5°}
  found: clairance minimale par route : 3/56 < 0,5 m, 6/56 < 1 m, 24/56 < 5 m (ex. 0,106 m au segment 4 pour t=58600, tack -1, k 1,11, +5°). Le routeur longe la marge au plus près (optimalité + décimation gloutonne).
  implication: des frôlements de l'ordre du cm sont attendus à quelques ‰ des routes : compatible avec 1/291 au soak.

- timestamp: 2026-11-11
  checked: scratchpad/repro3.py — 3200 requêtes (58300-58700 s pas 4 s, tack ±1, k ∈ {aucun, 1,05, 1,11, 1,2} × dTWD ∈ {0, ±3°, ±6°}), contrôle harnais identique à tablet._validate sur coordonnées arrondies à 6 décimales ; scratchpad/analyse.py pour les chiffres
  found: 2400 routes acceptées (800 refus : départ dans la terre, 58300-58380 s) ; 3 échecs harnais, tous valides non arrondis :
    (58532 s, tack -1, k 1,11, -6°) 11 pts, start_in_margin, seg 8 (2071 m) : clairance 0,0052 m au masque dilaté, 105,2 m à la terre brute ; décalages d'arrondi (0,032 ; -0,017) et (-0,006 ; -0,039) m ; publié : bloqué sur le masque dilaté, libre sur la terre brute.
    (58544 s, tack -1, k 1,2) 12 pts, start_in_margin, seg 7 (1701 m) : clairance 0,0012 m, pas de terre brute à < 75 m (marge de danger) ; décalages jusqu'à 0,055 m.
    (58680 s, tack +1, k 1,05) 8 pts, départ hors marge, seg 6 (3214 m, vers Vodice) : clairance 0,0354 m, terre brute à 92,8 m.
  implication: S1 confirmé : faux positif de précision du harnais, la route du routeur ne touche ni la marge ni la terre ; la ligne publiée frôle la marge de 100 m de quelques cm (sans conséquence à bord : le suiveur de route utilise le chemin non arrondi, route.json aussi).

- timestamp: 2026-11-11
  checked: report.json routes / tablet.route_states / process_events autour de f67, timeline (at vs t_sim), synth.log (sim vs wall), src/jabuka/soak/faults.py _route_after/course_change, tablet.last_route_version, tools/soak.py course_upkeep/wait_sim/run_faults
  found: v129 adoptée 3218,9 ; 3220,9 'no_course' 129 (parcours A terminé, sim 64215) ; redémarrage du cœur 3292-3293,7 (f65) puis 'no_course' version 0 ; aucune route publiée jusqu'à v1 à 3353,5 (32 pts, 36,3 s après f67), v2..v4 ensuite. f66 (at 64888,6) démarre à sim 65795 et f67 (at 66000) à sim 66144 : planning en retard, wait_sim ne boucle pas, course_upkeep jamais appelé entre 3220,9 et 3317,2. f67 : GET /api/course -> A (terminé) -> sélection B à 3317,2 ; _route_after voit le nav périmé 'no_course' -> course_upkeep lit last_nav.course.finished périmé -> GET -> B -> sélectionne A à 3317,4 (constat « course B finished at sim 66151 s: A selected » faux). Base v_before = last_route_version() = 129 (dernier message route de l'ancien processus) : v1 jamais > 129.
  implication: S2 = défauts du harnais uniquement ; le routage a produit une route dans le budget (36,3 s : parcours complet depuis Vodice au niveau L0 + une requête B rendue caduque).

- timestamp: 2026-11-11
  checked: scratchpad/repro4.py — balayage tenu à l'écart (58402-58702 s pas 4 s, mêmes variantes), chaque route acceptée publiée à 6 décimales puis re-validée par le TabletClient corrigé
  found: 2400 routes ; ancien contrôle : 1 faux échec (58618 s, tack +1, k 1,05, -3° : à 30 s de v121) ; nouveau contrôle : 0 échec, 1 frôlement toléré de 1,88 cm. Cumul des deux balayages : 4 faux positifs / 4800 routes (0,08 %) avec l'ancien contrôle, 0 avec le nouveau. Profondeurs publiées mesurées : 0,27 à 1,88 cm (borne 6,87 cm). Les vraies traversées restent rejetées (test : 7,5 cm, 0,5 m, 100 m ; segment Vodice -> Jabuka : profondeur inf en 62 ms).
  implication: le correctif supprime le faux positif sans masquer de vraie traversée.

## Eliminated

- hypothesis: v121 est une route non validée publiée par le cœur (composition stay, route restaurée, display_points tronquée)
  evidence: kind optimal (shown = opt, validé par _route), adoptée hors redémarrage (aucun restart entre 2920 et 2978), 9 points < MAX_ROUTE_POINTS 300.
  timestamp: 2026-11-11

- hypothesis: le harnais et le routeur utilisent un masque ou un cadre différents
  evidence: TabletClient charge <pack>/landmask.npz, le worker build_env le même fichier ; env.frame est mask.frame.
  timestamp: 2026-11-11

- hypothesis: f67 = routage réellement bloqué après le changement de parcours
  evidence: route_states 'computing' dès 3317,2 puis v1 'ok' à 3353,5 (36,3 s < 60 s), v2-v4 ensuite.
  timestamp: 2026-11-11

## Resolution

root_cause: "S1 (check land, v121 segment 4) : faux positif du harnais — tablet._validate re-valide les coordonnées publiées par le cœur (route_message : round(lon/lat, 6), jusqu'à 6,87 cm de la polyligne validée par le routeur) avec le contrôle raster exact à tolérance nulle ; un segment livré qui frôle la marge dilatée de 100 m à quelques mm/cm devient « bloqué » une fois arrondi (reproduit 3 fois sur 2400 routes du même secteur, terre brute >= 92 m). Aucun défaut du routeur : il valide exactement ce qu'il livre ; à bord, le suiveur et route.json utilisent le chemin non arrondi. S2 (f67) : défauts du harnais — (a) base de version = dernier message route vu (v129 d'un processus remplacé) au lieu de la version affichée par le cœur (0, no_course) ; (b) course_upkeep agit sur un nav périmé « finished » et rebascule le parcours que la panne vient de choisir (faux constat « course B finished ») ; (c) wait_sim n'appelle course_upkeep que si le planning est en avance, le parcours terminé reste terminé ~1930 s simulées. Le routage a produit v1 en 36,3 s (< 60 s)."
fix: "Harnais uniquement (aucune modification de l'app) : tablet.py — COORD_DECIMALS = 6, publication_precision_nm(frame), graze_depth_nm() (profondeur échantillonnée au cm d'un segment dans les cases bloquées, distance à la case libre voisine la plus proche), _published_ok() : un segment signalé par le contrôle exact n'échoue que s'il s'enfonce de plus que la précision de publication ; graze_m + detail enregistrés ; last_route_version() = nav.route.version du dernier nav (repli : dernière route adoptée). tools/soak.py — course_upkeep() exige finished dans GET /api/course et renvoie True s'il a sélectionné ; wait_sim() l'appelle une fois même en retard. faults._route_after — note « next course selected » seulement si une sélection a eu lieu."
verification:
  target_test: { result: pass, tests: "tests/soak/test_soak_tablet.py (5 nouveaux dont 7 cas paramétrés), tests/soak/test_soak_faults.py (5 nouveaux) ; rouges avant correctif : (1, False, 7) / (2, False, 6) reproduisent la classe v121, 129 au lieu de 0, faux constat « course B finished » reproduit" }
  mutation_check: { result: pass, reason_if_skipped: "pas de Stryker (Python) : 6 mutants manuels aux sites du correctif (scratchpad/mutate.py)", mutant_killed: "6/6 (tolérance x10, tolérance nulle, base sans nav, upkeep sans finished API, wait_sim sans upkeep initial, note sans sélection)" }
  no_op_deletion: { result: pass, deletion_justified_by_rca: true, note: "ajouts uniquement, sauf le renvoi booléen de course_upkeep et la note conditionnelle de _route_after (justifiés : défaut (b))" }
  adjacent_tests: { result: pass, suites_run: ["tests/soak (128 passés)", "bash scripts/check.sh : ruff check + format OK, pytest 3.14 2094 passés / 4 ignorés, pytest 3.13 2094 passés / 4 ignorés"] }
  held_out: { result: pass, detail: "scratchpad/repro4.py : 2400 routes tenues à l'écart, ancien contrôle 1 faux échec, nouveau 0" }
  revert_and_reconfirm: { result: pass, bug_returned_on_revert: true, fixed_on_reapply: true, detail: "src revenus à HEAD : 10 échecs ; réappliqués : 37 passés (tablet + faults + tracer)" }
  guardrail_verdict: accepted
  human_verify: { result: pass, confirmed_by: utilisateur (2026-11-11), run: "soak Pi race-36h n°3 20261111T005058Z, portée system, code 0c582d6 (empreinte 13e282453207, 152 fichiers), throttling 0x0, temp. max 73,1 °C, 129870 s simulées en 6511 s (19,9×)", verdict: "PASS (exit 0), 131 lignes « oui », 0 « non »", land: "0 des 315 routes adoptées traversent la terre ; 2 frôlements dans la précision de publication (le plus profond 0,0163 m, borne 0,0687 m)", f67: "course-change PASS en 13,5 s (budget 60 s), sans note (aucun faux constat « course X finished »)", route_after_fault: "pire 15,19 s, p95 14,14 s (23 pannes) ; route_after_recovery oui (16,1 s)", report: var/soak/20261111T005058Z-race-36h/report.md }
commit: 0c582d6 (correctif du harnais + tests) ; archivage de la session : commit docs(debug) qui suit
files_changed: [src/jabuka/soak/tablet.py, src/jabuka/tools/soak.py, src/jabuka/soak/faults.py, tests/soak/test_soak_tablet.py, tests/soak/test_soak_faults.py, tests/soak/test_soak_tracer.py]

## Specialist Review

specialist_hint: python. La compétence python-expert-best-practices-code-review n'est pas installée, la relecture a donc été faite par le gestionnaire de session sur le diff de 0c582d6.

LOOKS_GOOD.
- La tolérance de graze_depth_nm est bornée par publication_precision_nm, soit environ 6,9 cm.
- Tout échantillon sans case libre parmi ses 8 voisines renvoie inf et échoue. Une vraie traversée de la marge de 100 m reste donc rejetée.
- last_route_version() lit nav.route.version. Ce n'est sûr que parce que _route_after filtre par routes_after(t_from) : une route adoptée avant la panne ne peut pas compter comme nouvelle, même si le nav est en retard.
- Relancé localement par le gestionnaire : tests/soak, 128 passés.
