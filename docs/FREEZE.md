# Gel des fonctionnalités — mercredi 11 novembre 2026

Le **mercredi 11 novembre 2026**, le code est gelé. Ce qui part sur le bateau est exactement le
tag `race-2026` : même code que les essais d'endurance, même verrou de paquets revu, même
wheelhouse, même carte SD (et son clone de secours). Après le gel, **seule la configuration
change**.

`bash scripts/freeze-check.sh` vérifie tout ce qui peut l'être (éléments F1 à F9, une ligne
chacun, code 0 quand aucun élément n'est en `FAIL`). `--pre` avant de poser le tag, `--skip-gate`
pour ne pas relancer la porte (déjà lancée à l'étape 3).

## Ce qui est gelé

- **Le code** : `src/jabuka/` (cœur, ingest, navigation, routeur, interface web), `pyproject.toml`.
- **Le verrou** : `deploy/requirements.lock` (et `deploy/fastnet2ip.lock` du Plan B), revu et
  haché ci-dessous.
- **Les unités systemd** et les fichiers d'installation : `deploy/systemd/`, `deploy/udev/`,
  `deploy/provision.sh`, `deploy/gpsd.default`, `deploy/chrony-gps.conf`.
- **La wheelhouse** construite depuis le tag, et la carte SD installée depuis elle.

## Ce qui reste permis après le gel (configuration seulement)

- Les **réglages** par l'interface (onglet Réglages), enregistrés sur le Pi.
- Le **parcours et les marques** (parcours A/B, côtés, ligne, marques ajoutées, « Finir ici »).
- Les **données du pack de course** : vent, vagues, courant, masque terre, carte (`race.pmtiles`,
  amers) et la polaire `polar.json` (`jabuka-prep`, `jabuka-prep-polar`).
- La **variation**, le **décalage compas** et le **signe de l'AWA** : `variation_deg` et
  `heading_offset_deg` dans Réglages ; `--awa-sign -1` de l'ingest seulement par un drop-in
  systemd (`sudo systemctl edit jabuka-ingest-fastnet`, COMMISSIONING.md §4), et seulement si le
  bateau l'exige.
- `true_wind_source`, `route_level`, `efficiency`, la réduction en vent fort
  (`heavy_wind_start_kn`, `heavy_wind_full_kn`, `heavy_wind_reduction`) et les autres réglages de
  l'onglet Réglages.

Tout le reste (une ligne de code, une version de paquet, une unité) est un **correctif
d'urgence** (dernière section), jamais une retouche sur le bateau.

## Liste du 11 novembre (dans l'ordre)

1. **Endurance sur le portable** : `bash scripts/soak.sh` (scénario race-36h, [SOAK](SOAK.md)),
   verdict PASS, complet (sans `--duration`), sur un arbre propre.
2. **Endurance sur le Pi** : `sudo bash scripts/soak.sh --systemd system --python
   /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M` lancé dans
   `tmux` ([SOAK](SOAK.md) « Soak sur le Pi 3B »), verdict PASS, complet (sans `--duration`) ;
   recopier le dossier du rapport du Pi dans `var/soak/` du portable. Le rapport du Pi porte
   l'empreinte du paquet installé (`code.sha256`) et celle des unités installées ; F4 les compare
   avec `src/jabuka` et `deploy/systemd` à HEAD, la copie du dépôt sans `.git` (PI-SETUP §3)
   suffit donc. F4 n'accepte que ce rapport-là (`mode` systemd, `code.source` = `units`) : un
   soak du Pi en mode shim ou en `--systemd user`, ou un rapport sans bloc `code`, donne F4 FAIL.
3. **Porte verte** : `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh`.
4. **Revue du verrou** : 01-UAT #8, 02-UAT #10, PI-SETUP §4 m et la revue des paquets de 03-05
   (numpy 2.5.4, outils de préparation). Puis calculer `sha256sum deploy/requirements.lock` et
   remplacer `À REMPLIR` sur la ligne ci-dessous par ce hash ; commit.
5. **Pré-contrôle** : `bash scripts/freeze-check.sh --pre --skip-gate` : F1, F3, F4, F5 PASS
   (F6 vient à l'étape 7).
6. **Tag** : `git tag -a race-2026 -m "Regata Jabuka 2026 : version gelée"`.
7. **Wheelhouse depuis le tag** : `bash scripts/build-wheelhouse.sh` (roue jabuka reconstruite
   depuis `src/` du tag).
8. **Réinstaller le Pi** : copier le dépôt et la wheelhouse, puis `sudo deploy/provision.sh`
   (PI-SETUP §3).
9. **Redémarrer le Pi** et vérifier qu'il ne reste aucun drop-in de l'endurance (mode
   `--systemd` de 04-01) : `systemctl cat jabuka-core jabuka-ingest-fastnet` ne montre que les
   unités installées.
10. **Contrôle final** : `bash scripts/freeze-check.sh` : tout PASS sauf F8 (WARN, éléments UAT
    à traiter à bord) et F9 (HUMAN).
11. **Cloner la SD de secours** depuis la carte gelée : [SPARE-SD](SPARE-SD.md).
12. **Étiqueter et ranger** : carte de course dans le Pi, carte de secours étiquetée
    « JABUKA SECOURS race-2026 », clé USB (pack, wheelhouse, archive du dépôt).

Lock revu : sha256 À REMPLIR

## Empreinte du code

L'empreinte d'un paquet `jabuka` se calcule dans son dossier (sur le Pi
`/opt/jabuka/venv/lib/python3.13/site-packages/jabuka`, sur le portable `src/jabuka`) :

```bash
find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum
```

C'est la même valeur que `code.sha256` dans `report.json` du soak, celle que `freeze-check` F3/F4
compare avec `src/jabuka` à HEAD, et celle que l'étape 5 de [SPARE-SD](SPARE-SD.md) compare entre
les deux cartes.

Règle par élément :

- **F3 (portable)** : la règle git est obligatoire (`git.head` présent, arbre propre, aucun
  changement sous `src/`, `deploy/` hors `*.md` ni `pyproject.toml` depuis `git.head`), plus
  l'empreinte quand le rapport en porte une. Un rapport du portable sans `git.head` donne F3 FAIL
  « git.head inconnu », même avec la bonne empreinte.
- **F4 (Pi)** : l'empreinte (`code.sha256`) et les unités (`code.units`) sont obligatoires, et le
  rapport doit venir d'un soak `--systemd system` (`mode` systemd, `code.source` = `units`). Un
  soak en mode shim ou en `--systemd user` donne « n'est pas un soak --systemd system », un rapport
  sans bloc `code` donne « sans empreinte du code ». La règle git seule ne suffit jamais pour F4 ;
  quand `git.head` est présent, elle s'applique en plus.
- **F3 et F4 (soak complet)** : seul un soak race-36h complet compte : `scenario_sha256` = sha256
  de `src/jabuka/soak/scenarios/race-36h.json` à HEAD, la même `seed`, `duration_s` ≥ sa durée
  (129 600 s), `sim_s` ≥ 99 % de celle-ci, et aucune panne SKIPPED « after the end of the run ».
  Sinon « essai raccourci » ou « ne prouve pas le scénario race-36h de HEAD ». `freeze-check`
  juge le rapport race-36h le plus récent de chaque machine : garder les essais rapides hors de
  `var/soak/` (`--out var/soak-essais`).
- **F3 et F4 (soak terminé sans signal)** : un rapport dont `end_signal` n'est pas null (Ctrl-C,
  SIGTERM ou SIGHUP reçu à la fin du soak : sortie 128 + signal), ou absent (banc antérieur au
  plan 04-08), donne « soak interrompu » ; un rapport en mode systemd dont
  `systemd.journal.complete` n'est pas true donne « copie du journal des unités incomplète ». Il
  faut alors refaire le soak, en attendant `jabuka-soak: verdict` sans Ctrl-C.

## Correctif d'urgence après le gel

Seulement pour un défaut qui empêche de courir (plantage, donnée fausse à l'écran), jamais pour
une amélioration :

1. Branche depuis le tag : `git switch -c hotfix/race-2026.1 race-2026`.
2. Correctif minimal **avec son test** qui échoue avant et passe après.
3. Porte complète : `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh`.
4. Tag `race-2026.1` sur le commit du correctif.
5. Reconstruire la wheelhouse (`bash scripts/build-wheelhouse.sh`).
6. Réinstaller le Pi (`sudo deploy/provision.sh`, PI-SETUP §3), redémarrer.
7. Recloner la SD de secours ([SPARE-SD](SPARE-SD.md)).

Le soak n'est pas refait pour un correctif d'urgence (pas le temps) : `freeze-check.sh` dira F3/F4
`code modifié depuis le soak` (règle git) ou `code soaké … différent de src/jabuka à HEAD` (règle
de l'empreinte), et F7 sur `race-2026` ; c'est attendu, le noter dans le carnet.
