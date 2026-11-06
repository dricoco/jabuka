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
- `true_wind_source`, `route_level`, `efficiency` (et les autres réglages de l'onglet Réglages).

Tout le reste (une ligne de code, une version de paquet, une unité) est un **correctif
d'urgence** (dernière section), jamais une retouche sur le bateau.

## Liste du 11 novembre (dans l'ordre)

1. **Endurance sur le portable** : `bash scripts/soak.sh` (scénario race-36h, [SOAK](SOAK.md)),
   verdict PASS, sur un arbre propre.
2. **Endurance sur le Pi** : le même essai sur le Pi (mode `--systemd`), verdict PASS ; recopier
   le dossier du rapport du Pi dans `var/soak/` du portable.
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
`code modifié depuis le soak` et F7 sur `race-2026` ; c'est attendu, le noter dans le carnet.
