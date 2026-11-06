# Soak : 36 h sans surveillance, en accéléré

Ce document décrit le banc d'endurance de Jabuka (plan 04-01, exigence REL-02). Le soak fait
tourner les **vrais processus** (ingest Fastnet en réception seule sur un pty, jabuka-core avec son
routeur forkserver, un faux gpsd) autour d'un X35 synthétique qui barre sur les cibles du core,
sous horloge simulée à environ 60×. Il injecte un calendrier de pannes graine fixe, vérifie en
continu ce que verrait la tablette, et écrit un rapport JSON + Markdown. Code de sortie : 0 PASS,
1 FAIL, 2 erreur d'usage.

## Ce que le soak prouve

- Après chaque panne, la tablette (un client WebSocket sur `/ws`, qui lit les mêmes messages
  `diag`, `nav` et `route` que l'appli) revoit le vent et la position en direct dans le budget :
  10 s pour une panne bus ou GPS, 30 s pour le redémarrage d'un processus, 60 s pour une coupure
  d'alimentation (secondes réelles).
- Une nouvelle route est adoptée après chaque redémarrage, et **aucune route adoptée ne coupe la
  terre** : chaque polyligne est revalidée par le banc sur le masque du pack
  (`LandMask.validate_polyline`, premier segment ignoré si la route part dans la marge côtière).
- Parcours, réglages et vent manuel survivent à chaque coupure propre (CRSE-05, REL-01). Un fichier
  d'état tronqué ou corrompu n'arrête jamais le core : il sert une version entière (fichier ou
  `.bak`), ou la valeur par défaut **avec son alerte « illisible »**.
- RSS du core et du worker de routage ≤ 250 Mo (portable), pas de pente de croissance sur le plus
  long segment sans redémarrage, nombre de fd et de threads stable, disque des journaux conforme au
  budget de rétention, partition de journaux pleine sans perte des données en direct.
- Aucune trace d'exception inattendue dans les journaux des processus, aucun compteur d'erreur du
  core (`handler_errors`, `nav_errors`, `router_errors`, …) qui monte hors d'une fenêtre de panne.
- L'horloge GPS de production (`--clock gps`) : heure GPS en retard au démarrage (routage bloqué,
  puis débloqué) et saut de ±1 h (maintien, ré-ancrage, route toujours ok).

## Lancer

| Quoi | Commande | Durée (portable) |
|---|---|---|
| Soak CI (dans la porte) | `bash scripts/check.sh` (tests `tests/soak/`, `ci` et `gpsclock-ci` en parallèle) | ~2,5 min par Python |
| Soak CI seul | `.venv/bin/python -m jabuka.tools.soak --scenario ci` | ~100 s |
| Horloge GPS | `.venv313/bin/python -m jabuka.tools.soak --scenario gpsclock-ci` | ~55 s |
| Traceur (1 panne) | `.venv/bin/python -m jabuka.tools.soak --scenario tracer` | ~25 s |
| Course complète 36 h | `bash scripts/soak.sh` (scénario `race-36h`) | ~40 min à 60× |

`scripts/soak.sh` accepte `--scenario`, `--speed`, `--python` (défaut `.venv313/bin/python`,
l'interpréteur du Pi) et passe le reste à `jabuka-soak` (`--seed`, `--keep`, `--duration`, …).
`--duration` raccourcit une exécution (essai rapide) : les pannes prévues après la fin sont
listées SKIPPED avec leur heure, jamais comptées comme passées. Le
dossier de sortie doit être sous `var/` ; le banc refuse aussi tout `--out` sous
`/var/lib/jabuka` (données réelles) et ne réutilise jamais un dossier existant.

Chaque exécution crée `var/soak/<horodatage UTC>-<scénario>/` :

| Fichier | Contenu |
|---|---|
| `report.md` | verdict, chronologie des pannes, tableau des contrôles |
| `report.json` | la même chose, schéma 1 (lu par `scripts/freeze-check.sh`, plan 04-02) |
| `samples.csv` | une ligne par seconde réelle et par rôle : RSS, fd, threads, CPU |
| `timeline.jsonl` | événements : démarrages, READY, sorties, pannes, corruption |
| `proc/<rôle>-<n>.log` | sortie horodatée de chaque processus (n = numéro de démarrage) |
| `data/` | le dossier de données du core et de l'ingest |

### Pi 3B (plan 04-03)

Sur le Pi, le soak tourne plus lentement : prévoir **20×** (36 h en ~1 h 50) ou **10×** (~3 h 40)
au lieu de 60×, avec `--speed 20`. Le mode `--systemd` (pannes appliquées aux vraies unités
systemd au lieu du superviseur du portable) est ajouté par le plan 04-03.

## Différences portable / Pi

- Sur le portable, un **superviseur de substitution** (`jabuka/soak/supervisor.py`) imite systemd :
  `Restart=always`, `RestartSec=`, `WatchdogSec=` sont lus dans `deploy/systemd/*.service` (des
  valeurs intégrées servent sans dépôt ; un test vérifie qu'elles restent égales), `Type=notify`
  avec une socket de notification par service, et `KillMode=control-group` (le forkserver et le
  worker meurent avec le core).
- Le scénario `ci` raccourcit **WatchdogSec à 5 s** (au lieu de 30) pour tenir le budget de temps
  de la porte ; le rapport l'affiche (« Shim : … raison : … »). `race-36h` garde la valeur réelle.
- La partition de journaux pleine se simule avec un tmpfs de taille limitée monté sur
  `data/logs` dans un espace de noms utilisateur (`unshare --user --map-root-user --mount`). Sans
  espace de noms, la panne `disk-full` est **SKIPPED** avec la raison, jamais jouée sur le vrai
  disque. Les journaux du tmpfs disparaissent à la fin de l'exécution ; `logcheck` est passé avant.

## Format des scénarios

Fichiers JSON dans `src/jabuka/soak/scenarios/` (chargés par nom) ou un chemin :

```json
{"name": "ci", "seed": 4, "clock": "sim", "speed": 60, "duration_s": 5400,
 "start": [43.708265, 15.800369], "start_utc": "2026-11-13T19:00:00Z",
 "wind": {"twd": 161, "tws_kn": 12, "shift_deg_h": 0, "gust_kn": 0},
 "grib": {"tws_factor": 1.0, "hours_before": 2, "hours_after": 48},
 "course": "A", "settings": {}, "logs_fs": "auto", "budgets": {},
 "shim": {"watchdog_sec": 5, "why": "…"},
 "faults": [{"kind": "kill-core", "at": 300}, {"kind": "bus-silent", "at": 900, "dur": 300}],
 "random": null, "quiet_tail_s": 0, "expected_tracebacks": {}}
```

- `at` et `dur` sont en secondes **simulées**. Les pannes s'enchaînent : la suivante part au plus
  tôt à son heure, et jamais avant que la précédente soit rétablie (+ `settle_s`), pour que chaque
  effet soit attribué sans ambiguïté. Les heures réelles sont enregistrées.
- `random` : `{"count", "kinds", "min_gap_s", "until_s", "dur_s", "off_s"}` tire des pannes
  supplémentaires avec la graine ; jamais de redémarrage dans la `quiet_tail_s` finale (le
  contrôle de fuite mémoire a besoin d'un long segment sans redémarrage).
- `logs_fs` : `auto` (tmpfs seulement s'il y a une panne `disk-full`), `none`, ou `tmpfs:TAILLE`
  (512M au plus).
- `shim` : surcharge de `watchdog_sec` / `restart_sec`, **toujours avec une raison** (`why`).
- `start_utc` : une date ISO, ou `now` (scénario horloge GPS).

## Catalogue des pannes

| Panne | Ce qui est fait | Critère de rétablissement | Budget |
|---|---|---|---|
| `kill-ingest` | SIGKILL de l'ingest | vent en direct ; l'ingest relancé rouvre le **même** pty | 30 s |
| `kill-core` | SIGKILL du core | vent + position ; la route sauvegardée est restaurée (« périmée » jusqu'au premier calcul) puis une route plus récente est adoptée | 30 s / route 60 s |
| `kill-worker` | worker de routage figé (SIGSTOP), recalcul forcé, puis SIGKILL | le core garde son pid, le pool compte le crash, nouvelle route | route 60 s |
| `sigterm-storm` | 5 SIGTERM à 100 ms d'écart au core, puis à l'ingest | codes de sortie 0 ou -15 uniquement, retour par le superviseur | 30 s |
| `power-pull` | SIGKILL de tous les groupes, « courant coupé » `off_s`, corruption graine optionnelle (`truncate_half`, `garbage`, `drop_main`, `stray_tmp`), redémarrage | données en direct, persistance (voir plus haut), `logcheck` après chaque coupure | 60 s |
| `watchdog-hang` | SIGSTOP du core plus longtemps que WatchdogSec | le superviseur envoie SIGABRT puis SIGKILL et relance (comme systemd) | WatchdogSec + 30 s |
| `bus-silent` | le bus se tait | vent GRIB affiché en ≤ 15 s (WIND-05), vent en direct ≤ 10 s après | 10 s |
| `garbage` | octets aléatoires sur le bus | trames valides toujours décodées, rien ne redémarre | 10 s |
| `noise` | bits inversés dans les trames (équivalent des erreurs de parité : un pty ignore PARENB) | le décodeur rejette, continue | 10 s |
| `unplug` | le pty se ferme (EIO), puis un pty neuf | ingest « absent » puis vent en direct ≤ 10 s après rebranchement | 10 s |
| `gps-loss` | le faux gpsd se tait | position en direct ≤ 10 s après | 10 s |
| `clock-jump` | l'heure GPS saute de +1 h puis revient | horloge simulée : la boucle continue, pas de trace, nouvelle route ; horloge GPS : sauts comptés, heure valide (maintien puis ré-ancrage), route ok | route 60 s |
| `disk-full` | fichier de lest dans `data/logs` jusqu'à ENOSPC | données en direct pendant la fenêtre, le journal dérivé reprend ≤ 30 s après libération | 30 s |
| `grib-gap` | vent qui s'arrête 1 h après « maintenant », core relancé | alerte de couverture, routage ok, lay-lines sur chaque message nav ; vent complet remis et alerte levée | 30 s |
| `course-change` | parcours A ↔ B en cours de bord | route pour le nouveau parcours | 60 s |
| `stay-toggle` | « On reste » activé juste après un recalcul forcé, désactivé quelques minutes plus tard | `route.stay.active` suit, route optimale de nouveau | 60 s |
| `ws-stall` | une deuxième tablette ouvre la socket et ne lit plus jamais | RSS du core +20 Mo au plus (la file du hub jette les plus anciens), la vraie tablette reste en direct | 20 Mo |
| `ws-churn` | 50 connexions/fermetures (Wi-Fi qui décroche) | nombre de fd du core revenu à la normale | — |

## Lire le rapport

- **Chronologie** : une ligne par panne, heures en secondes depuis le début, « rétabli » en
  secondes réelles après la fin de la panne, budget, ok, notes (par exemple « idle worker killed »
  ou la corruption appliquée).
- **Contrôles** (noms stables, lus par le plan 04-03) : `recovery_bus`, `recovery_gps`,
  `recovery_process`, `recovery_power`, `route_after_recovery`, `land`, `persistence`,
  `logcheck`, `rss_core`, `rss_worker`, `leak_slope`, `fd_growth`, `thread_growth`,
  `cpu_per_sim_s`, `tick_ratio`, `log_disk`, `tracebacks`, `error_counters`. « — » dans ok veut
  dire « pas jugé » : `insufficient data` (par exemple `leak_slope` sur un soak court : il faut au
  moins 3 h simulées sans redémarrage après 30 min de chauffe) ou `skipped: raison`.
- **samples.csv** : tracer `rss_kb` en fonction de `t_sim` par `role` (`core`, `worker`,
  `ingest`, `forkserver`) ; chaque changement de `pid` est un redémarrage.
- **Budgets** : dans le scénario, recopiés dans `report.json`. Ils ne se modifient qu'à
  l'intérieur des plages du CONTEXT et avec une mesure à l'appui, notée dans le journal des
  constats ci-dessous.

## Traces attendues

Une trace « Traceback (most recent call last) » dans un journal de processus fait échouer le soak,
sauf si elle tombe dans la fenêtre d'une panne (5 s de marge après le rétablissement) **et**
correspond à un motif autorisé pour ce type de panne. La table intégrée ne contient qu'une entrée :
`disk-full` → « No space left on device » / ENOSPC. Toute autre entrée se déclare dans le scénario
(`expected_tracebacks`) avec une justification d'une ligne (`why`), recopiée dans le rapport.

## Journal des constats

| Date | Panne | Symptôme | Cause | Correction | Test |
|---|---|---|---|---|---|
| 2026-11-06 | `power-pull` + `garbage` sur `settings.json` | réglages revenus aux valeurs par défaut **sans alerte** | la première écriture n'a pas de `.bak` ; `load_json_with_bak` ne distinguait pas « absent » de « illisible » | `atomicio.load_json_status` ; réglages, parcours et vent manuel lèvent leur alerte « illisible » | `tests/nav/test_state_corruption.py` |
| 2026-11-06 | `kill-core` | le bateau synthétique s'arrête (`http.client.IncompleteRead`), fin du soak | le core tué au milieu d'une réponse ; seules OSError/ValueError étaient attrapées | `FollowHelm.fetch` attrape aussi `HTTPException` | `tests/sim/test_follow_helm_faults.py` |
| 2026-11-06 | arrêt du core (porte : `tests/sim/test_synth_e2e.py` bloqué) | l'arrêt propre du core ne se termine jamais | le nettoyage de session du client gpsd avalait `CancelledError` pendant l'attente de fermeture de la socket : le client se reconnectait sans fin | `CancelledError` n'est plus attrapée dans ce nettoyage | `tests/gps/test_gpsd_client_cancel.py` |
| 2026-11-06 | `disk-full` (Python 3.13 seulement, celui du Pi) | `logcheck` : ligne JSON invalide **au milieu** du journal dérivé | le `BufferedWriter` de Python 3.13 écrit directement une ligne longue (un diag fait plusieurs Kio) ; si le disque se remplit au milieu, la moitié reste sur disque et le reste est perdu, la ligne suivante se colle au fragment | `RotatingAppendLog` tamponne lui-même des lignes entières, écrit par un fichier non tamponné et, en cas d'échec, tronque le fichier à la dernière ligne entière et garde le lot pour réessayer | `tests/test_rawlog_full_disk.py` |
| 2026-11-06 | `clock-jump` (+1 h puis retour) | plus aucun recalcul de route pendant ~1 h | le minuteur de recalcul et l'âge de la route partaient d'une heure « future » | déclencheur forcé « clock » quand l'heure recule de plus de 30 s ; une route calculée pour une heure future est retirée (« heure GPS revenue en arrière ») jusqu'au recalcul | `tests/routing/test_clock_step_back.py` |

Observations sans correction (pas des défauts) :

- `disk-full` : tant que la partition est pleine, le core écrit une trace « log flush failed …
  ENOSPC » par tick (environ une par seconde en course). Attendu par la règle des traces ; le
  journal système est volatil et limité en débit. La rétention a supprimé 21 fichiers de
  catégories pour tenir la réserve, le journal dérivé reprend 0,1 s après libération.
- Une route restaurée au démarrage est affichée « périmée » sans le drapeau `start_in_margin`
  (rempli seulement à l'état ok) ; le banc applique donc la règle du routeur lui-même (segment de
  sortie de la marge côtière vérifié sur la terre réelle) au lieu de se fier au drapeau. Aucune
  traversée de terre n'a été trouvée ; aucune fausse alerte ne venait de l'arrondi à 1e-6° des
  coordonnées du message route.
- Après un redémarrage, une route sauvegardée calculée pour une version antérieure du parcours
  (marque arrondie depuis) n'est pas restaurée, à raison, et la numérotation des routes repart à
  1 ; l'appli redessine sur tout changement de version (`v !== drawn`), donc sans effet visible.
- Le job de routage L0 dure environ 50 ms : `kill-worker` fige d'abord le worker (SIGSTOP) pour que
  le SIGKILL tombe bien pendant un calcul (crash compté par le pool).
- `kill-ingest` relance l'ingest sur le **même** pty sans réinitialiser ses termios : le report
  01-04 (EINVAL à la réouverture) est confirmé corrigé par `serial_ro._quiesce_and_reset_speed`.
