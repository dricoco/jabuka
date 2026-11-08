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
| Traceur sous systemd (utilisateur) | `.venv313/bin/python -m jabuka.tools.soak --systemd user --scenario tracer` | ~25 s |
| Course complète sur le Pi | voir « Soak sur le Pi 3B » ci-dessous | ~2 h à 20× |

`scripts/soak.sh` accepte `--scenario`, `--speed`, `--python` (défaut `.venv313/bin/python`,
l'interpréteur du Pi), `--systemd user|system`, `--systemd-cleanup`, et passe le reste à
`jabuka-soak` (`--logs-fs`, `--seed`, `--keep`, `--duration`, …). `--systemd system` sans root
est refusé (code 2, une ligne avec la commande sudo).
`--duration` raccourcit une exécution (essai rapide) : les pannes prévues après la fin sont
listées SKIPPED avec leur heure, jamais comptées comme passées. Le banc l'annonce dès le départ
(`jabuka-soak: WARNING: shortened run …`) et `report.md` le marque **Essai raccourci**.
`freeze-check` F3/F4 refusent un tel rapport (« essai raccourci ») et jugent le rapport race-36h
**le plus récent** de chaque machine dans `var/soak/` : un essai rapide rangé là masquerait le
vrai soak. Les essais rapides vont donc ailleurs :
`bash scripts/soak.sh --scenario race-36h --duration 900 --out var/soak-essais`. Le
dossier de sortie doit être sous `var/` ; le banc refuse aussi tout `--out` sous
`/var/lib/jabuka` (données réelles) et ne réutilise jamais un dossier existant.

Chaque exécution crée `var/soak/<horodatage UTC>-<scénario>/` :

| Fichier | Contenu |
|---|---|
| `report.md` | verdict, **mesures et budgets** (valeur mesurée à côté de chaque budget du CONTEXT), chronologie des pannes, tableau des contrôles |
| `report.json` | la même chose, schéma 1 (lu par `scripts/freeze-check.sh`, plan 04-02) ; bloc `code` (plan 04-04 : empreinte `sha256` du paquet exécuté, nombre de `files`, `package_dir`, `source` `units` ou `children`, `units` = sha256 des unités installées en portée system) ; clés du plan 04-07 : `duration_s` (durée simulée visée), `scenario_duration_s`, `scenario_source` et `scenario_sha256` (sha256 du fichier de scénario exécuté), que `freeze-check` compare avec `src/jabuka/soak/scenarios/race-36h.json` à HEAD, avec `seed`, `sim_s` et les pannes SKIPPED ; en mode systemd, bloc `systemd` (portée, unités, `n_restarts`, nettoyage, `harness_oom_score_adj`), sur un Pi, bloc `pi` ; clés du plan 04-08 : `end_signal` (numéro du signal reçu à la fin du soak, sinon null) et, en mode systemd, `systemd.journal` (`complete`, `error`, `entries` par rôle) |
| `samples.csv` | une ligne par seconde réelle et par rôle : RSS, fd, threads, CPU ; sur un Pi, une ligne `pi` toutes les 10 s (`temp_c`, `throttled`) |
| `timeline.jsonl` | événements : démarrages, READY, sorties, pannes, corruption |
| `proc/<rôle>-<n>.log` | sortie horodatée de chaque processus (n = numéro de démarrage) ; en mode systemd, `proc/<rôle>-journal.log` (journal de l'unité) |
| `data/` | le dossier de données du core et de l'ingest (portée system : `/var/lib/jabuka/soak-<ts>/data`) |

### Mode systemd (`--systemd`, plan 04-03)

Avec `--systemd`, le core et l'ingest tournent comme **unités systemd** au lieu du superviseur
de substitution : ce sont `Restart=`, `RestartSec=`, `WatchdogSec=`, `Type=notify` et
`KillMode=` de systemd lui-même qui relancent tout. Les pannes passent par
`systemctl kill --signal=… --kill-whom=main|all`, `stop`, `start` ; le rapport compte les
redémarrages faits par systemd (`NRestarts`, bloc `systemd` de `report.json`).

| Portée | Où | Ce qui tourne | Sudo |
|---|---|---|---|
| `--systemd user` | portable | deux unités **transitoires** `systemd-run --user` (`jabuka-soak-<ts>-core`, `-ingest`), avec `Type=notify`, `Restart=`, `RestartSec=`, `WatchdogSec=` recopiés des unités livrées (+ `StartLimitIntervalSec=0`) | non |
| `--systemd system` | Pi | les **unités installées** `jabuka-core` et `jabuka-ingest-fastnet`, redirigées par des drop-ins **volatils** `/run/systemd/system/<unité>.d/50-jabuka-soak.conf` | oui |

- **Portée user** : le durcissement (`User=`, `ProtectSystem=`, `PrivateDevices=`, …) n'est
  **pas** appliqué (un gestionnaire utilisateur ne sait pas l'appliquer ; on prouve ici la
  logique de relance, de notification et de chien de garde). `disk-full` est SKIPPED : les
  services tournent hors de l'espace de noms du banc, le vrai disque n'est jamais rempli.
- **Portée system** : le drop-in vide `ExecStart=` puis pose l'`ExecStart` du soak (même binaire,
  mêmes options que l'unité livrée, sauf `--data-dir`, `--device`, `--racepack`, `--clock sim` et
  `--gpsd 127.0.0.1:<port du faux gpsd>`, jamais 2947). Tout le reste (utilisateur `jabuka`,
  durcissement, relance, chien de garde) est celui de production. Le core garde
  `--http-host 0.0.0.0 --http-port 80` : **la tablette suit le soak en direct** sur
  http://10.42.0.1. Les données du soak vont dans `/var/lib/jabuka/soak-<ts>/` (jamais les
  fichiers d'état de la course) ; le pty du bateau synthétique est `/run/jabuka-soak/fastnet-pty`,
  rendu à l'utilisateur `jabuka` à chaque rebranchement simulé. `--logs-fs loop:512M` monte une
  image ext4 de 512 Mo (1G au plus) sur `data/logs` pour la panne `disk-full`.
- **Nettoyage, toujours** (fin normale, échec, Ctrl-C, SIGTERM, SIGHUP, `atexit`), dans cet
  ordre : drop-ins retirés, `daemon-reload`, les deux unités **relancées sur leur configuration
  de production**, puis démontage du système de fichiers des journaux du soak ; le banc affiche
  enfin le résultat de `systemctl cat jabuka-core | grep -c 50-jabuka-soak` (attendu 0). Le
  nettoyage n'est marqué fait qu'une fois tout cela exécuté : un nettoyage interrompu est refait
  par `atexit` ou par `--systemd-cleanup`. Après la relance, le banc vérifie que les deux unités
  sont actives (jusqu'à 20 s). Si la relance a échoué ou qu'une unité n'est pas active :
  `restarted: false` dans `report.json` (avec les états des unités), verdict FAIL, nettoyage
  refait à la sortie, et `--systemd-cleanup` rend le code 1. Un Ctrl-C, SIGTERM ou SIGHUP reçu
  pendant toute la **fin du soak** (arrêt des unités, copie du journal, contrôles finaux,
  nettoyage, écriture et remise du rapport) ne fait plus perdre le rapport : le banc le retient
  et l'annonce par une ligne `jabuka-soak: signal … held`, termine, écrit `report.json`, puis
  sort avec le code 128 + signal. `journalctl`, `umount` et `vcgencmd` tournent dans leur
  **propre session** : le Ctrl-C du terminal ne les tue pas et la copie du journal reste
  complète. Mais l'exécution compte alors comme un **soak interrompu** : `report.json` →
  `end_signal`, et freeze-check F3/F4 la refusent. Si la copie du journal échoue (code de retour
  de `journalctl` non nul, plus de 300 s, erreur, ou aucune ligne pour une unité en portée
  system), le contrôle `tracebacks` est FAIL (« journal dump incomplete ») et le verdict aussi,
  avec le détail dans `report.json` → `systemd.journal` (plan 04-08). Un drop-in resté d'une
  exécution interrompue bloque
  toute nouvelle exécution ; `sudo bash scripts/soak.sh --systemd system --systemd-cleanup`
  répare. `/run` est de toute façon vidé au redémarrage du Pi. En portée system, le banc (root)
  abaisse aussi son propre `oom_score_adj` à -900 : un OOM-kill du banc sauterait le nettoyage.
- **Chien de garde** : `watchdog-hang` fige le core (SIGSTOP). systemd le voit (`Watchdog
  timeout`, état `stop-watchdog`) et envoie SIGABRT ; le banc fait alors SIGCONT pour que ce
  signal arrive tout de suite, comme sur un processus bloqué mais vivant. Sans ce SIGCONT,
  systemd attendrait `TimeoutAbortSec` (90 s par défaut) avant son SIGKILL : un artefact du
  SIGSTOP, pas un défaut de l'unité.
- Les traces sont lues dans le journal des unités (`journalctl -u … -o json`), recopiées dans
  `proc/<rôle>-journal.log` au même format que les journaux du superviseur, avec les lignes de
  systemd (« Main process exited », « Watchdog timeout », « Scheduled restart job »). La copie
  tourne dans sa propre session, en 300 s au plus, et un échec n'est jamais silencieux
  (« journal dump incomplete », voir le nettoyage ci-dessus).

Validation sur le portable (systemd 260, gestionnaire utilisateur), 2026-11-07, commit 38c275a :

| Scénario | Commande | Verdict | Détail |
|---|---|---|---|
| `tracer` | `.venv313/bin/python -m jabuka.tools.soak --systemd user --scenario tracer` | PASS | core tué, relancé par systemd (`NRestarts` 1, « Scheduled restart job, restart counter is at 1 »), retour en 3,0 s, 22 s réelles |
| `ci` | `.venv313/bin/python -m jabuka.tools.soak --systemd user --scenario ci` | PASS | 18 pannes (disk-full SKIPPED, portée user), `NRestarts` core 5 / ingest 2, chien de garde de systemd déclenché (`Watchdog timeout (limit 5s)!`, retour en 6,5 s), 23 routes sans terre, 0 trace inattendue, 92 s réelles |

Aucune unité `jabuka-soak-*` ne reste chargée après ces exécutions
(`systemctl --user list-units --all 'jabuka-soak-*'` vide).

La portée system ne peut pas tourner sur le portable sans root : ses drop-ins sont testés par
`tests/soak/test_soak_systemd.py` (analysés par les vrais parseurs du core et de l'ingest, passés
à `systemd-analyze verify` avec les unités livrées, nettoyage prouvé sur une erreur avec un faux
`systemctl`). Le premier vrai passage est celui du Pi ci-dessous.

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
- Sur le Pi (`--systemd system`), ce sont les vraies unités qui sont relancées, avec leur
  durcissement ; le Pi 3B tient **20×** (36 h en ~1 h 50) ou **10×** (~3 h 40), pas 60×.

## Résultats portable (race-36h, 2026-11-07)

Portable x86_64, 8 cœurs, 32 Go, Python 3.13 (`.venv313`, l'interpréteur du Pi), mode shim,
`bash scripts/soak.sh --scenario race-36h` lancé sous `nice -n 5 ionice -c2 -n7` (la porte et
d'autres travaux tournaient en même temps). 129 600 s simulées (36 h) en ~36 min réelles, 94
pannes par exécution.

| Exécution | Dossier (`var/soak/`) | Code | Vitesse | Verdict |
|---|---|---|---|---|
| 1 (découverte) | `20261107T113002Z-race-36h` | lancée sur b04dae8 (code produit inchangé depuis), rapport daté 0832f7f | 59,96× | **PASS** |
| 2 | `20261107T120650Z-race-36h` | 0832f7f, arbre propre | 59,96× | FAIL : f92 `clock-jump` (défaut du **banc**, corrigé en 394aa31, voir constats) |
| 3 | `20261107T124725Z-race-36h` | 394aa31, arbre propre | 60× | **interrompue** à 78 040 s simulées (f80, 79 pannes, aucune en échec) : processus arrêté par Claude Code, mémoire du portable saturée par d'autres tâches (swap plein, charge 23) ; pas de rapport |
| 4 (finale) | `20261107T133350Z-race-36h` | 0fff60c (merge 04-03 sur main), arbre propre | 59,97× | **PASS** : 94 pannes, 129 641 s simulées en 2 162 s réelles |

Le code **produit** (`src/jabuka/{core,ingest,nav,route,sim,common}`) n'a pas changé pendant ce
plan : seuls le banc (`src/jabuka/soak/`, `src/jabuka/tools/soak.py`) et `scripts/soak.sh` ont
changé. Le PASS de l'exécution 1 vaut donc pour le produit. L'exécution 4, relancée sur le HEAD
final (0fff60c, après le merge de 04-03), donne le **PASS** exigé par freeze-check F3 : tous les
budgets tenus (bus 0,54 s, redémarrage 3,09 s, watchdog 25,9 s, coupure 0,55 s, route 1,26 s,
RSS core 77 Mo / worker 148,7 Mo, pente de fuite core 15,2 Mo/36 h pour 20, 0 croisement de terre
sur 303 routes, 0 traceback). La pente de fuite du core (9,8 / 16,6 / 15,2 Mo/36 h selon les
exécutions) reste sous le budget mais à surveiller sur le Pi.

Mesures et budgets de l'exécution 1 (PASS ; l'exécution 2 donne les mêmes ordres de grandeur, sa
seule ligne en échec est la route après f92) :

| mesure | mesuré | budget | ok |
|---|---|---|---|
| recovery bus (s) | worst 0.55, p95 0.54 (20 faults) | 10 | oui |
| recovery GPS (s) | worst 0.03, p95 0.03 (4 faults) | 10 | oui |
| recovery process restart (s) | worst 3.1, p95 3.1 (12 faults) | 30 | oui |
| recovery watchdog hang (s) | worst 25.93, p95 25.93 (2 faults) | 60 | oui |
| recovery power pull (s) | worst 3.4, p95 3.4 (8 faults) | 60 | oui |
| route after fault (s) | worst 1.74, p95 1.06 (23 faults) | 60 | oui |
| restart with a short GRIB (s) | worst 4.36, p95 4.36 (8 faults) | 30 | oui |
| log writes resume after disk full (s) | worst 0, p95 0 (2 faults) | 30 | oui |
| max RSS core (MB) | 79.3 | 250 | oui |
| max RSS worker (MB) | 150.4 | 250 | oui |
| leak slope core (MB/36 h) | 9.76 (exécution 2 : 16.55) | 20 | oui |
| leak slope worker (MB/36 h) | 4.71 (exécution 2 : 0.84) | 20 | oui |
| fd growth | 1 | 8 | oui |
| thread growth | 0 | 4 | oui |
| CPU per sim s (CPU s) | 0.0046 | 0.1 | oui |
| tick ratio | 1 | ≥ 0.95 | oui |
| log usage (MB) | 44 (tmpfs 128 Mo, 31 suppressions de rétention) | 128 | oui |
| land crossings | 0 of 320 routes | 0 | oui |
| unexpected tracebacks | 0 (221 attendues, ENOSPC dans les fenêtres disk-full) | 0 | oui |

Pannes par type (94) : bus-silent 6, clock-jump 6, course-change 3, disk-full 2, garbage 3,
gps-loss 4, grib-gap 8, kill-core 3, kill-ingest 2, kill-worker 5, noise 6, power-pull 8 (dont
corruptions garbage, truncate_half, drop_main, stray_tmp), sigterm-storm 7, stay-toggle 9,
unplug 5, watchdog-hang 2, ws-churn 7, ws-stall 8. Persistance vérifiée après les 8 coupures,
`logcheck` ok 9 fois.

**Pente de fuite** : appliquée (segment de 12 h simulées sans redémarrage, la queue calme). La
courbe RSS du core n'est pas une rampe : 65 Mo au démarrage, palier ~73-75 Mo après 1 à 2 h, une
marche de +4 Mo vers 97 000 s simulées (exécution 2), puis plat (±1 Mo) sur les 8 à 10 dernières
heures. L'ajustement linéaire sur tout le segment surestime donc la pente ; il reste sous le
budget sans retouche de la chauffe ni du budget.

## Soak sur le Pi 3B (à faire avant le 2026-11-10)

Une seule commande, sur le Pi lui-même, en SSH par Ethernet (le Wi-Fi reste le point d'accès de la
tablette). Prévoir ~2 h à 20× (~4 h si l'on doit repasser à 10×).

1. **Pi installé depuis une wheelhouse construite après ce plan** (04-03, 04-04) : le paquet du
   soak doit être dans `/opt/jabuka/venv` (`/opt/jabuka/venv/bin/python -c "import
   jabuka.soak.systemd"` ne doit rien afficher). Le rapport enregistre le bloc `code` :
   l'**empreinte du paquet jabuka que les unités installées exécutent vraiment** (dans
   `/opt/jabuka/venv`, `code.sha256`) et le sha256 des deux fichiers d'unité installés
   (`code.units`). `~/jabuka` peut donc rester la copie rsync **sans .git** de PI-SETUP §3.
   Au départ, le banc affiche `jabuka-soak: code <12 hex>` ; il refuse de partir (code 2) s'il
   ne peut pas calculer cette empreinte. `freeze-check` F4 compare `code.sha256` avec
   `src/jabuka` à HEAD, et les unités installées avec `deploy/systemd` à HEAD. F4 ne compte que
   ce soak-là (`mode` systemd et `code.source` = `units`) : un soak lancé sur le Pi sans
   `sudo … --systemd system` (mode shim) ou avec `--systemd user` donne F4 FAIL « n'est pas un
   soak --systemd system », même avec la bonne empreinte ; un rapport sans bloc `code` donne
   aussi F4 FAIL. Le banc annonce un tel essai dès le départ par une ligne `WARNING`. F3/F4 ne
   comptent aussi qu'un soak race-36h **complet** : le lancer sans `--duration`, avec le scénario
   packagé et sa graine (`scenario_sha256`, `seed`). Un essai rapide sur le Pi va dans
   `--out var/soak-essais`, sinon `freeze-check` le lit en premier et donne F4 FAIL « essai
   raccourci ». Pour vérifier à la main sur le Pi :

   ```bash
   cd /opt/jabuka/venv/lib/python3.13/site-packages/jabuka && find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum
   ```

   Il faut ~600 Mo libres dans `/var/lib/jabuka` (`df -h /var/lib/jabuka`) pour l'image de 512 Mo.
2. Lancer, **dans tmux** : une coupure SSH pendant les 2 à 4 h envoie SIGHUP et arrête le banc
   (il intercepte SIGHUP lui-même, `nohup` n'y change donc rien). Ouvrir d'abord une session
   `tmux new -s soak` (si tmux manque : `sudo apt install -y tmux`, avec internet par Ethernet),
   lancer la commande ci-dessous dedans ; après une coupure, se reconnecter en SSH puis
   `tmux attach -t soak`.

   ```bash
   cd ~/jabuka && sudo bash scripts/soak.sh --systemd system \
       --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M
   ```

   Le banc refuse de partir sans root (code 2, avec la commande sudo), si les unités ne sont pas
   installées, ou s'il reste un drop-in d'une exécution interrompue (voir l'étape 8).
   `--logs-fs loop:512M` est **obligatoire** en portée system : un tmpfs (le défaut de race-36h
   sur le portable) est refusé avec le code 2, car il bloque de la RAM sur le Pi de 1 Go ;
   `--logs-fs none` est accepté mais la panne `disk-full` est alors SKIPPED.
3. **Suivre sur la tablette** : http://10.42.0.1 (le core du soak garde le port 80). Le bateau
   synthétique navigue au large de Vodice en temps accéléré ; les pannes font clignoter les
   sources et redémarrer l'appli, c'est voulu.
4. **Lire le ratio de ticks** (`tick ratio` dans « Mesures et budgets » de `report.md`). En
   dessous de 0,95, le Pi ne suit pas 20× : relancer avec `--speed 10` et noter les deux résultats.
5. **Température et throttling** : la ligne « Raspberry Pi » du rapport (et `report.json` → `pi`)
   donne la température max et les bits `get_throttled` vus (relevés toutes les 10 s). Si des bits
   « throttled » ou « under-voltage » apparaissent : aérer le boîtier / vérifier l'alimentation
   12 V→USB, puis refaire le soak.
6. **Rapatrier le rapport** sur le portable (freeze-check F4 le lit dans `var/soak/`) :

   ```bash
   scp -r pi@10.42.0.1:jabuka/var/soak/<ts>-race-36h var/soak/   # depuis le portable
   ```

   (ou l'adresse Ethernet du Pi). Le dossier appartient à l'utilisateur qui a lancé sudo. Ne
   rapatrier qu'une exécution dont le banc est sorti avec le code 0, au verdict PASS, et dont
   `proc/core-journal.log` et `proc/ingest-journal.log` ne sont pas vides (`end_signal` null et
   `systemd.journal.complete` true dans `report.json`).
7. **Redémarrer le Pi**, puis vérifier qu'il n'y a plus aucun drop-in du soak :

   ```bash
   sudo reboot
   systemctl cat jabuka-core | grep -c 50-jabuka-soak    # doit afficher 0
   systemctl is-active jabuka-core jabuka-ingest-fastnet # active active
   ```

   Puis libérer la carte SD : `sudo rm -rf /var/lib/jabuka/soak-<ts>` (après l'étape 6 ; l'image
   `logs.img` y est laissée pour inspection).
8. **Si le soak a été interrompu** (coupure, SSH perdu, Ctrl-C pendant le soak) :
   `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python
   /opt/jabuka/venv/bin/python --systemd-cleanup`. La fin du soak ne s'arrête plus sur un Ctrl-C
   (il est retenu jusqu'à l'écriture de `report.json`) ; si elle semble bloquée (plus de ~15 min
   sans nouvelle ligne), `sudo kill -9 <pid du banc>`, puis la commande ci-dessus. **Ne pas
   appuyer sur Ctrl-C à la fin du soak** : attendre la ligne `jabuka-soak: verdict …`. Un Ctrl-C
   à la fin donne un « soak interrompu » (sortie 128 + signal) que F4 refuse, et le soak est à
   refaire. Depuis le plan 04-08, le terminal garde les dernières lignes du banc après un Ctrl-C
   (`tee -i`). Code 0 quand
   `systemctl cat jabuka-core` ne contient plus `50-jabuka-soak` **et** que les deux unités sont
   actives ; code 1 sinon :
   `systemctl status jabuka-core jabuka-ingest-fastnet`, puis redémarrer le Pi (étape 7).
   Ensuite l'étape 7.
9. Le vrai test de **coupure d'alimentation** reste celui de PI-SETUP §4 j : 5 coupures réelles,
   suivies chacune de `jabuka-logcheck`. Le soak simule les coupures, il ne les remplace pas.

## Budgets Pi à confirmer

Les budgets mémoire du CONTEXT (core ≤ 250 Mo, worker ≤ 250 Mo) ont été mesurés sur le portable,
où le soak complet tient très en dessous (voir « Résultats portable »). Sur le Pi 3B (1 Go de RAM),
ils sont **à confirmer** par le soak ci-dessus ; ce relevé ferme aussi l'élément humain 03-05
« Pi memory ».

| Mesure | Budget | Portable (race-36h) | Pi 3B (à remplir) |
|---|---|---|---|
| RSS max core (Mo) | 250 | 79,3 | |
| RSS max worker (Mo) | 250 | 150,4 | |
| Pente de fuite core (Mo/36 h) | 20 | 9,8 / 16,6 | |
| CPU par seconde simulée (CPU s) | 0,10 | 0,005 | |
| Ratio de ticks | ≥ 0,95 | 1,0 | |
| Vitesse tenue | — | 60× | 20× ou 10× |
| Température max (°C) | (relevé) | — | |
| Bits throttling vus | aucun | — | |

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
- `logs_fs` : `auto` (tmpfs seulement s'il y a une panne `disk-full`), `none`, `tmpfs:TAILLE`
  (512M au plus) ou `loop:TAILLE` (image ext4 dans le dossier du soak, `--systemd system`
  seulement, 1G au plus).
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
| `watchdog-hang` | SIGSTOP du core plus longtemps que WatchdogSec | le superviseur envoie SIGABRT puis SIGKILL et relance (comme systemd) ; en mode `--systemd`, c'est le chien de garde de systemd (SIGCONT du banc ensuite, voir plus haut) | WatchdogSec + 30 s |
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
| 2026-11-07 | `clock-jump` (soak complet 2, f92) | « pas de nouvelle route en 60 s » après le retour de l'heure | **défaut du banc** : le bateau a fini le parcours B pendant la fenêtre de la panne (état route `no_course`, à raison) ; le banc ne choisissait le parcours suivant qu'entre deux pannes | `_route_after` relance la sélection du parcours suivant pendant l'attente (394aa31) ; aucun défaut produit | `tests/soak/test_soak_tracer.py::test_route_wait_selects_the_next_course_when_the_boat_finished_during_a_fault` |

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
