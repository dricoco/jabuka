# Mise en service à bord — Regata Jabuka 2026 (X35)

Le runbook unique pour mettre Jabuka en service sur le bateau, en une séance, les **jeudi 12
novembre** (premier jour à bord) et **vendredi 13 novembre** (jour de course, départ à partir de
**20:00 heure locale**). Heure locale = CET = **UTC + 1**. Toutes les heures de ce document sont
locales, sauf mention « UTC ». Les heures sont indicatives : les décaler en bloc selon l'accès au
bateau.

Ce document ne recopie pas les contrôles déjà écrits : il dit **quand** les faire et renvoie aux
sources ([PI-SETUP](../deploy/PI-SETUP.md), [TABLET-SETUP](TABLET-SETUP.md),
[WEATHER-PACK](WEATHER-PACK.md), [ROUTING](ROUTING.md), [RACE-PACK](RACE-PACK.md), les fichiers
UAT des phases 1 et 2, les « Human items » de 03-06). L'annexe B fait le lien entre chaque
élément en attente et le moment où on le traite à bord.

## Lire ce document

- Chaque ligne d'action : **heure approximative**, **action**, **repère**, **ce qu'on doit voir**.
- Repère **`[R2.swap]`** : l'étape est **répétée sur le portable** par
  `bash scripts/commissioning-rehearsal.sh` (même identifiant dans la sortie du script).
- Repère **HUMAN** : l'étape demande le bateau, le Pi ou la tablette ; le script l'affiche avec
  l'observation attendue, sans pouvoir la faire.
- Les commandes `sh` sont à taper sur le Pi (SSH par Ethernet ou par le Wi-Fi `jabuka`) ou sur le
  portable, comme indiqué. Les outils du Pi sont dans `/opt/jabuka/venv/bin/`, ceux du portable
  dans `.venv/bin/` (après `bash scripts/bootstrap-dev.sh`).

## Répéter sur le portable (avant de partir, et à quai)

```sh
bash scripts/commissioning-rehearsal.sh                  # rapide (~10 s) : §2–§4, §5, §7
bash scripts/commissioning-rehearsal.sh --steps all      # complète (~4 min) : + §1, §6, §8, §9
bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.replay,R3.logcheck \
    --capture <capture.log du bateau>                    # le 12 nov., sur la vraie capture
```

Chaque étape imprime une ligne `[PASS|FAIL|SKIP|HUMAN] <id> §<n> <titre> : <détail>`. Code de
sortie 0 : aucune étape en échec. Les résultats vont dans `var/rehearsal/<horodatage UTC>/`
(`results.json` avec `--json`, journaux des outils dans `logs/`). La répétition complète fait
tourner un bateau de synthèse (`jabuka-sim` en pty → `jabuka-ingest-fastnet` → `jabuka-core` sur un
pack de répétition) : vérifications d'instruments, route, exercices dégradés, coupure
d'alimentation. Les derniers résultats sont dans l'annexe A.

## Plan des deux journées

**Jeudi 12 novembre (premier jour à bord)**

| Heure | Bloc | Sections |
|---|---|---|
| 09:00 | Arrivée, déballage, sac contrôlé, Pi posé et alimenté (12 V → USB ≥ 3 A) | §1 (liste) |
| 09:30 | Câblage du bus en écoute seule, sonde | §2 |
| 10:00 | Capture brute **avant tout autre réglage**, pages B&G, archive, rejeu sur le portable | §3 |
| 10:30 | Contrôles des instruments au port | §4 (au port) |
| 11:30 | Tablette : réseau, drapeau Chrome, écran, nuit, verrou, support | §5 |
| 14:00 | Exercices en mode dégradé à quai (bus débranché, vent manuel, ON RESTE, coupure) | §8 |
| 15:00 | Si le bateau sort : contrôles au moteur puis sous voiles, `true_wind_source` | §4 (en mer) |
| 17:30 | Bilan du jour : noter ce qui reste, recharger tablette et portable | annexe B |
| 18:30 | Nuit tombée : contrôle du mode nuit et de la luminosité à la barre | §5 |

**Vendredi 13 novembre (jour de course, départ à partir de 20:00)**

| Heure | Bloc | Sections |
|---|---|---|
| 09:00 | Pi allumé, Diag vert (`routing: ok`), tablette chargée | §5, §9 |
| 12:00–18:00 | Inscription : IC, côtés de passage, ligne, restrictions électroniques | §7 |
| 13:00 | Parcours sur la tablette d'après les IC, exercice de changement < 30 s | §7 |
| 16:40 (15:40 UTC) | Pack météo final, copie au Pi, route visible | §6 |
| 18:30 | **Go / no-go** (avant 19:00), choix du mode de course | §9 |
| 19:00 | Tablette fixée, verrouillée, mode nuit prêt ; portable chargé à bord (Plan B) | §5, §9 |
| 20:00 | Départ | — |

## 1. Avant de partir (maison)

But : partir avec tout le matériel, un système gelé et éprouvé, et une carte SD de secours.

Liste de colisage (cocher) : HUMAN [R1.packing]

- [ ] Raspberry Pi 3B dans son boîtier, carte SD de course en place
- [ ] **SD de secours** clonée et vérifiée, étiquetée « JABUKA SECOURS + date »
- [ ] Adaptateur **DTECH** USB RS422/485 avec son faisceau de dérivation (Blanc, Vert, masse)
- [ ] GPS **VK-162** (USB) et sa rallonge
- [ ] Câbles USB (2 de rechange) et câble d'alimentation du Pi
- [ ] Convertisseur **12 V → USB** (≥ 3 A), cosses, domino, ruban isolant
- [ ] **Fusibles** de rechange (calibre du circuit utilisé), multimètre
- [ ] **Outils** : tournevis plats et cruciformes, pince à dénuder, colliers, adhésif
- [ ] Tablette, chargeur, câble long, **support 3D** et ses vis
- [ ] Portable, chargeur, adaptateur 12 V ou batterie externe
- [ ] Clé USB : pack de course, archive du dépôt, wheelhouse, cette documentation
- [ ] Carte du parcours imprimée (marques, côtés, ligne) et ce runbook imprimé

| Quand | Action | Repère | On doit voir |
|---|---|---|---|
| J−3 | Wheelhouse construite depuis la version gelée | [R1.wheelhouse] | une roue par paquet du verrou + `jabuka-*.whl` |
| J−3 | Essai d'endurance race-36h PASS, portable puis Pi ([SOAK](SOAK.md), `bash scripts/soak.sh`) | [R1.soak] | `report.json` `verdict: PASS` |
| 9 nov. | Banc du Pi fait et noté : ROUTING.md « Banc d'essai Pi », `route_level` réglé | HUMAN | `NIVEAU RECOMMANDÉ : Lx` |
| 11 nov. | Gel fait : [FREEZE](FREEZE.md), `bash scripts/freeze-check.sh` | HUMAN | F1–F7 PASS |
| 11 nov. | SD de secours clonée et démarrée : [SPARE-SD](SPARE-SD.md) | HUMAN | mêmes services, même empreinte |
| 11 nov. | Pack de répétition construit et contrôlé (`bash scripts/racepack-dryrun.sh`) | [R6.dryrun] | résumé, code 0 |
| 11 nov. | Contrôles du Pi à la maison : PI-SETUP §4 e–f (GPS, heure hors ligne), §4 h–k (kill -9, débranchement, 5 coupures, chien de garde), §4 l (sonde sans bus) | HUMAN | 01-UAT #6, #7, #5 cochés |
| 11 nov. | Polaire du X35 du propriétaire convertie (02-UAT #5) | HUMAN | `polar.json` dans le pack |
| 11 nov. | Répétition complète : `bash scripts/commissioning-rehearsal.sh --steps all` | [R9.summary] | aucun `FAIL` |

Pack de répétition, du portable (voir aussi §6) :

```sh
.venv/bin/jabuka-prep check --out var/racepack
```

## 2. Câblage du bus Fastnet

But : se brancher sur le bus B&G **en écoute seule**, sans jamais rien y émettre ni le charger,
et savoir en une minute si le câblage est bon grâce aux codes de sortie de `fastnet-probe`.

Règles (PITFALLS Pitfall 1 et 2) :

- **Écoute seule.** Le Pi ne doit jamais émettre sur le bus : le port est ouvert en lecture seule
  (PI-SETUP §4 b et d le vérifient). Ne pas utiliser fastnet2ip directement sur `/dev/fastnet`
  (Plan B : PI-SETUP §5, par le relais).
- **Pas de terminaison ajoutée** sur l'adaptateur DTECH (pas de résistance 120 Ω, cavalier
  ouvert). Le bus B&G a déjà les siennes.
- **Blanc = Data+** (A, borne T/R+ du DTECH), **Vert = Data−** (B, borne T/R−), **masse (GND)**
  reliée au 0 V du bus (fil noir / blindage côté B&G, selon le faisceau). Jamais les bornes RXD.
- Adaptateur DTECH en **mode RS485** (pas RS422).

| Heure (12 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 09:30 | Pi et instruments **éteints**. Poser le faisceau de dérivation sur le bus Fastnet : Blanc → T/R+, Vert → T/R−, masse → GND. Aucune terminaison. **Photos** du câblage (bornier B&G et DTECH). | HUMAN [R2.wiring] | Photos prises, rien de dénudé qui traîne |
| 09:40 | Allumer les instruments B&G, puis le Pi. Vérifier le port en réception seule. | HUMAN [R2.wiring] | PI-SETUP §4 b (`crw-r----- root dialout`), §4 c (`28800 parenb parodd cs8 cstopb`), §4 d (seul l'ingest tient le port) |
| 09:45 | Arrêter l'ingest et lancer la sonde (commande ci-dessous). | [R2.ok] | Verdict `OK`, code 0 |
| 09:50 | Si le code n'est pas 0 : suivre le tableau des codes, refaire la sonde après chaque correction. | [R2.silent] [R2.swap] [R2.noisy] | Code 0 au bout de la procédure |
| 10:00 | Relancer l'ingest. | HUMAN | `systemctl is-active jabuka-ingest-fastnet` = `active` |

Sonde sur le bateau (environ 15 s, le port doit être libre : l'ingest est arrêté avant) :

```sh
sudo systemctl stop jabuka-ingest-fastnet
sudo -u jabuka /opt/jabuka/venv/bin/fastnet-probe --device /dev/fastnet --seconds 10 --out /var/lib/jabuka/commissioning/probe-cablage
echo "code $?"
sudo systemctl start jabuka-ingest-fastnet
```

Codes de sortie de `fastnet-probe` (ce tableau est vérifié contre le code par les tests) :

| Code | Verdict | Action |
|---|---|---|
| 0 | `OK` (ok) | Câblage bon. Relancer l'ingest et passer au §3. |
| 1 | `DEVICE MISSING` / `PORT BUSY` (erreur) | Adaptateur absent ou port pris. `PORT BUSY` : l'ingest tourne encore, l'arrêter. `DEVICE MISSING` : `lsusb`, règle udev, `ls -l /dev/fastnet` (PI-SETUP §6). |
| 2 | `NO BYTES` (silent) | Rien ne parle : instruments allumés ? fils sur T/R+ et T/R− (pas RXD) ? masse reliée ? adaptateur en mode RS485 ? |
| 3 | `BYTES BUT NO VALID FRAMES` (no_frames) | Polarité inversée : **croiser Blanc et Vert** (A/B), puis refaire la sonde. |
| 4 | `NOISY` (noisy) | Bruit : vérifier la masse (GND) et le blindage, **retirer toute terminaison** ajoutée. |
| 5 | `FEW BYTES, NO FRAMES` (few_bytes) | Trop peu d'octets pour juger : attendre que le bus soit actif (afficheurs allumés) et refaire la sonde plus longue (`--seconds 30`). |

Ordre de dépannage quand rien ne marche (PITFALLS « Recovery Strategies », Pitfall 1) :
**croiser Blanc/Vert → vérifier la masse → retirer la terminaison → vérifier le mode RS485**.
Toujours une seule correction à la fois, sonde après chaque correction. Si le bus reste muet :
pas de panique, on court en mode **GPS + GRIB + vent manuel** (§8), et le Plan B reste possible
(§9).

Renvois : 01-UAT #4 (contrôles du port série sur le Pi), 01-UAT #5 (sonde sur le matériel :
`NO BYTES` sans bus, puis `OK` au bateau), PI-SETUP §4 l (sonde sur un bus débranché, à faire à
la maison), PI-SETUP §6 (dépannage).

## 3. Capture et inventaire

But : enregistrer les **octets bruts du bus avant tout autre réglage**, avec tous les canaux que
ce bateau peut émettre, pour pouvoir tout rejouer au portable si quelque chose cloche ensuite
(PITFALLS Pitfall 3 : les canaux attendus ne sont peut-être pas sur ce bus ; le Hercules de ce
bateau n'a jamais été capturé).

| Heure (12 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 10:00 | Lancer la capture longue (commande ci-dessous), **avant tout autre réglage**. | [R3.capture] | `fastnet-probe: reading /dev/fastnet for 600 s ...` |
| 10:00–10:10 | Pendant la capture : faire défiler **toutes les pages** de tous les afficheurs B&G (cap magnétique et vrai, TWD, set/drift, VMG, TWA cible, cap sur l'autre bord, profondeur, loch). | HUMAN [R3.pages] | Chaque page affichée au moins 10 s |
| 10:10 | Lire l'inventaire imprimé : canaux vus, noms, dernières valeurs. Noter ce qui manque (TWD 0x6D ? cap 0x49 ? set/drift 0x83/0x84 ?). | [R3.inventory] | Au minimum : BSP 0x41, AWA 0x51, AWS 0x4F, cap 0x49 |
| 10:15 | Copier la capture sur le portable et en faire une archive (commande ci-dessous). | [R3.archive] | `capture.log`, `inventory.json` sur le portable |
| 10:20 | Sur le portable : rejouer la vraie capture dans toute la chaîne. | [R3.replay] [R3.logcheck] | 5 lignes `PASS` |
| 10:25 | Relancer l'ingest sur le Pi. | HUMAN | `active` |

Capture sur le Pi (10 min, ingest arrêté) :

```sh
sudo systemctl stop jabuka-ingest-fastnet
sudo -u jabuka /opt/jabuka/venv/bin/fastnet-probe --device /dev/fastnet --seconds 600 --out /var/lib/jabuka/commissioning/capture-12nov
sudo systemctl start jabuka-ingest-fastnet
```

Archive et rejeu sur le portable (Wi-Fi `jabuka`, `<user>` = le compte SSH du Pi) :

```sh
mkdir -p var/commissioning
scp -r <user>@10.42.0.1:/var/lib/jabuka/commissioning/capture-12nov var/commissioning/
bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log
```

`R3.archive` écrit `var/rehearsal/<horodatage>/archive/capture-<horodatage>.tar.gz` et son
`.sha256`. Copier aussi l'archive sur la clé USB. Le rejeu (`R3.replay`) prouve que la vraie
capture traverse proprement `jabuka-replay` → `jabuka-ingest-fastnet` → `jabuka-core` : chaque
chemin décodé de l'inventaire est servi par `/api/state`. Pour la regarder à la main :

```sh
.venv/bin/jabuka-replay var/commissioning/capture-12nov/capture.log --link var/commissioning/fastnet-pty --loop
```

Renvois : 01-UAT #5 (garder `inventory.json` et `capture.log`), PI-SETUP §4 l.

## 4. Contrôles des instruments

But : que tout ce qui sort du Pi soit **vrai** (et non magnétique par erreur), que le cap et le
COG s'accordent, que le signe de l'AWA suive la convention, et choisir la source du vent réel.
PITFALLS Pitfall 4 (vrai/magnétique), Pitfall 5 (anomalie de Jabuka : près de Jabuka le cap
compas n'est pas fiable, le Pi bascule sur le COG, badge `CAP NON FIABLE`), Pitfall 6 (TWD qui
saute à chaque virement), Pitfall 7 (polaire optimiste).

Réglages concernés (onglet **Réglages** de la tablette) : `variation_deg` (Déclinaison, 4,7° E
par défaut), `heading_offset_deg` (Décalage compas), `true_wind_source` (`computed` par défaut :
vent réel calculé par le Pi depuis AWA/AWS/BSP/cap ; `instrument` : TWD/TWS du Hercules),
`efficiency` (polaire), `heavy_wind_start_kn`, `heavy_wind_full_kn` et `heavy_wind_reduction`
(réduction de polaire en vent fort : par défaut de 18 à 25 nds jusqu'à 5 %, 0 = désactivée ;
appliquée sur la polaire avant l'efficacité, pour les cibles, le % polaire, les lay-lines et le
routage).

| Heure (12 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 10:30 | Au port, Diag : cap magnétique du bus + `variation_deg` = cap vrai affiché | [R4.variation] | écart ≤ 1° |
| 10:35 | Au port : cap affiché contre l'orientation du ponton sur la carte | HUMAN [R4.dock] | écart ≤ 5° (sinon `heading_offset_deg`) |
| 10:40 | Signe de l'AWA : vent venant de **tribord** = AWA **positif** sur Diag (convention du projet) | [R4.awa_sign] | `+` vent sur tribord, `−` sur bâbord |
| 10:45 | Si le signe est inversé : drop-in `--awa-sign -1` sur l'ingest (ci-dessous), redémarrer, revérifier | HUMAN [R4.dock] | signe correct |
| 15:00 | **Au moteur**, eau calme, cap stable 2 min : cap vrai contre COG GPS | [R4.cog_hdg] HUMAN [R4.dock] | écart < 3° (Pitfall 4) ; sinon `heading_offset_deg` |
| 15:10 | Au moteur à l'étale : BSP contre SOG | HUMAN [R4.dock] | BSP ≈ SOG (± 0,3 nd) ; sinon calibrer le loch sur le B&G |
| 15:30 | Sous voiles, sur chaque bord 5 min : TWD calculé contre TWD Hercules (Diag) | [R4.twd] HUMAN [R4.underway] | écart < 10° sur les deux bords |
| 15:50 | Symétrie du TWD bâbord/tribord (pas de saut de plus de 10° à chaque virement) | HUMAN [R4.underway] | TWD stable d'un bord à l'autre |
| 16:00 | Choisir `true_wind_source` : `computed` par défaut ; `instrument` si le TWD Hercules est plus stable d'un bord à l'autre | HUMAN [R4.underway] | réglage noté sur la carte du parcours |
| 16:10 | Au près : le gros chiffre montre `TWA CIBLE ↑`, jamais ↓ (02-UAT #7) | HUMAN [R4.underway] | conforme |

Drop-in du signe de l'AWA (seulement si le bateau l'exige ; c'est un changement de
configuration autorisé après le gel, voir [FREEZE](FREEZE.md)) :

```sh
sudo systemctl edit jabuka-ingest-fastnet
```

```ini
[Service]
ExecStart=
ExecStart=/opt/jabuka/venv/bin/jabuka-ingest-fastnet --device /dev/fastnet --data-dir /var/lib/jabuka --udp 127.0.0.1:47100 --awa-sign -1
```

Renvois : 02-UAT #8 (vent LIVE, écart calculé/B&G < 10°, vent manuel), 02-UAT #7 (chiffre
principal au près). Garder set/drift désactivé tant que compas et loch ne sont pas vérifiés.

## 5. Tablette

But : la tablette à la barre reste connectée au Pi, allumée toute la nuit, lisible de nuit et
insensible aux embruns. PITFALLS Pitfall 16 (Android quitte le Wi-Fi « sans internet »),
Pitfall 17 (pas de Wake Lock sur une origine HTTP sans le drapeau Chrome).

| Heure (12 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 11:30 | Rejoindre le réseau `jabuka`, oublier les autres réseaux, données mobiles coupées, puis **mode avion** avec le Wi-Fi rallumé (TABLET-SETUP §1) | HUMAN [R5.setup] | `http://10.42.0.1` ouvre l'onglet Barre |
| 11:35 | La page ne charge rien hors du Pi (répété sur le portable) | [R5.offline] | aucune requête externe (chrome://inspect si doute) |
| 11:40 | Drapeau Chrome `unsafely-treat-insecure-origin-as-secure` = `http://10.42.0.1` (TABLET-SETUP §2) | HUMAN [R5.setup] | badge `ÉCRAN: verrou` après un toucher |
| 11:45 | **Stay awake** en charge, délai d'écran maximal, optimisation batterie coupée pour Chrome (TABLET-SETUP §3) | HUMAN [R5.setup] | l'écran ne s'éteint pas en 30 min |
| 11:50 | Plein écran, carte (WebGL), orientation (TABLET-SETUP §4–§7) | HUMAN [R5.setup] | carte dessinée, pas de `CARTE INDISPONIBLE` |
| 11:55 | Mode nuit `☾ Nuit` et **luminosité** minimale lisible (TABLET-SETUP §6) | HUMAN [R5.setup] | rouge sur noir, aucune lumière blanche |
| 12:00 | Test du **verrou** : eau sur l'écran, doigts mouillés, paume ; appui 2 s sur le cadenas puis relâcher (avant 4 s) (TABLET-SETUP §8) | HUMAN [R5.setup] | rien ne bouge verrouillé ; 2 s puis relâcher déverrouille ; un appui sans relâcher ne déverrouille jamais |
| 12:10 | Montage dans le **support 3D** à la barre, câble de charge passé, angle lisible du barreur | HUMAN [R5.setup] | lisible debout et assis |
| 18:30 | De nuit à la barre : relire le gros chiffre à bout de bras, vision de nuit préservée après 5 min (02-UAT #3) | HUMAN [R5.setup] | conforme |

Renvois : 02-UAT #1–#4 (vue Barre hors ligne, écran allumé, nuit, verrou), 01-UAT #2–#3 (AP et
page Diag), TABLET-SETUP « Night-before checklist » (à refaire le 13 à 19:00), PI-SETUP §4 g.

## 6. Pack de course (vendredi 13 après ~15:40 UTC)

But : partir avec la prévision la plus fraîche (run 12Z d'ICON-EU complet vers 15:40 UTC, soit
16:40 locale), contrôlée, copiée sur le Pi, et une route visible sur la tablette.

Le déroulé détaillé, minute par minute, est la **Checklist vendredi 13 novembre** de
[WEATHER-PACK](WEATHER-PACK.md#checklist-vendredi-13-novembre-pack-final) : ne pas le recopier,
le suivre. Points de passage :

| Heure | Action | Repère | On doit voir |
|---|---|---|---|
| avant 16:00 | Répétition rapide du pack réel avec internet (`bash scripts/racepack-dryrun.sh`) | [R6.dryrun] | résumé, code 0 |
| 16:40 (15:40 UTC) | Vent ICON-EU et vagues EWAM du run 12Z | HUMAN [R6.friday] | `run 2026-11-13T12:00:00Z` |
| 16:50 | Masque terre : construit en direct depuis **Overpass** (OSM) ; sinon celui de la veille dans `var/racepack` | HUMAN [R6.friday] | `landmask.npz` présent |
| 16:50 | Option : GRIB de l'**organisateur** (`jabuka-prep grib`), courant Copernicus | HUMAN [R6.friday] | champs trouvés listés |
| 17:00 | Contrôle du pack : `COUVERTURE MÉTÉO : OK` (lire `coverage.txt`) | HUMAN [R6.friday] | code 0 |
| 17:05 | Copie au Pi, redémarrage de `jabuka-core` (WEATHER-PACK « Copying the pack to the Pi », RACE-PACK « Copy to the Pi ») | HUMAN [R6.friday] | service `active` |
| 17:15 | Tablette : Diag `pack_ok true`, run 12Z ; Barre : une route apparaît | [R6.pack] | en moins de 1 min |
| 17:20 | Lisibilité de la route et du prochain virement sur la carte, de jour et de nuit (03-06) | HUMAN [R6.friday] | lisible |

Commandes du portable (la liste complète et les cas « DWD en retard » sont dans WEATHER-PACK) :

```sh
.venv/bin/jabuka-prep wind --out var/racepack
.venv/bin/jabuka-prep waves --out var/racepack
.venv/bin/jabuka-prep land build --out var/racepack
.venv/bin/jabuka-prep grib <fichier GRIB de l'organisateur> --out var/racepack --name wind_organiser
.venv/bin/jabuka-prep check --out var/racepack
```

Si le pack n'est pas bon à 18:00 : garder celui de la veille (§9 « GO laylines » si aucun pack ne
couvre la course). La route n'est jamais bloquante : sans route valide, l'onglet Barre affiche
les laylines (ROUTING.md « Repli : les laylines »).

## 7. Parcours

But : le parcours sur la tablette est exactement celui des IC (côtés de passage, ligne de départ
et d'arrivée), et on sait le changer en moins de 30 s en course.

| Heure (13 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 12:00–18:00 | À l'**inscription** : récupérer les IC ; demander s'il existe une restriction sur l'électronique ou la réception de données (Pitfall 19, RRS 41) ; noter la réponse | HUMAN [R7.si] | réponse écrite sur la carte du parcours |
| 13:00 | Onglet Carte : parcours A ou B, côtés de passage et rayons contre les IC ; déplacer la ligne de Vodice du point provisoire 43.7500N 15.7800E vers la vraie ligne | HUMAN [R7.si] | conforme aux IC |
| 13:10 | **« Côtés confirmés »** : l'alerte « Côtés à confirmer (IC) » disparaît | HUMAN [R7.si] | plus d'alerte |
| 13:15 | Exercice : passer à l'autre parcours, « Finir ici », l'annuler, revenir, en moins de **30 s** (répété par le script) | [R7.drill] HUMAN [R7.si] | < 30 s, aucun `409` |
| 13:20 | Imprimer ou écrire la carte du parcours (marques, côtés, ligne, réglages notés au §4) | HUMAN | carte dans le sac |
| 13:30 | Exercice **mode départ** à quai (TABLET-SETUP §11) : `DÉPART`, `Ping comité`, saisie de la bouée, `5:00`, `SYNC`, recharger la page, `Fermer le départ` | HUMAN | chrono conservé au rechargement, ligne affichée sur la carte, panneau fermé |

La vraie ligne de départ se « pingue » en mer, avant le signal d'avertissement (comité puis
bouée, antenne GPS au plus près de chacun).

Renvois : 02-UAT #6 (marques, côtés, ligne contre les IC), 02-04 human item 1 (exercice sur la
tablette). Le script fait le même enchaînement que la tablette, chaque changement portant
`base_version`.

## 8. Exercices en mode dégradé

But : avoir vu une fois, à quai, chaque panne probable et ce que l'écran montre alors. Ces
exercices se font le 12 à quai (bateau amarré, bus allumé).

| Heure (12 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 14:00 | **Débrancher le DTECH** : le bus disparaît | [R8.gribonly] HUMAN [R8.boat] | badge vent `GRIB`, alerte `VENT GRIB (pas d'instruments)`, laylines et route continuent |
| 14:05 | Bus toujours débranché : saisir le **vent manuel** lu sur le B&G (TWD en °M, TWS) dans Réglages | [R8.manual] HUMAN [R8.boat] | badge `MANUEL`, laylines mises à jour |
| 14:10 | Effacer le vent manuel, rebrancher le DTECH | [R8.gribonly] HUMAN [R8.boat] | retour `GRIB` puis `LIVE` sans rien faire |
| 14:15 | **ON RESTE** puis **ANNULER ON RESTE** ; écran verrouillé : le bouton ne fait rien | [R8.stay] HUMAN [R8.boat] | le bouton change, le compte à rebours suit |
| 14:20 | **Coupure d'alimentation** du Pi (débrancher 10 s), rallumer | [R8.powerpull] HUMAN [R8.boat] | en ~2 min : même parcours, marque active, réglages, vent manuel ; `jabuka-logcheck` OK |
| 14:30 | Lire « Échange de carte en mer » dans [SPARE-SD](SPARE-SD.md) ; le faire une fois si le temps le permet | HUMAN [R8.sdswap] | carte de secours démarrée, tablette reconnectée |

Après la coupure, sur le Pi :

```sh
systemctl is-active jabuka-ingest-fastnet jabuka-core
sudo -u jabuka /opt/jabuka/venv/bin/jabuka-logcheck /var/lib/jabuka/logs
```

Renvois : 01-UAT #7 (REL-01 sur le Pi : kill -9, débranchement, 5 coupures), 02-UAT #8 (vent
manuel), 02-UAT #9 (parcours et réglages après une coupure), PI-SETUP §4 i–j, ROUTING.md « ON
RESTE » et « Badge GRIB (bus B&G muet) ».

## 9. Go / no-go et plans B

Décision le **13 à 18:30** (avant 19:00), notée sur la carte du parcours. La répétition du
portable donne le bilan technique ([R9.summary]) ; le reste se lit sur la tablette.

| Décision | Critères (tous) | En course |
|---|---|---|
| **GO avec routage** | sonde `OK` au §2 ; badge `LIVE` ; écart TWD calculé/B&G < 10° (§4) ; route adoptée au §6 (`pack_ok true`) ; `route_level` réglé d'après le banc | suivre `TWA ROUTE` / `CAP ROUTE`, `Virement dans`, `VIREZ` |
| **GO laylines seulement** | bus et tablette OK, mais pas de route valide (pack mauvais, routeur en échec) ou pas de niveau de banc | `TWA CIBLE` / `CAP À SUIVRE` et laylines (Phase 2) |
| **GO GRIB / manuel** | bus mort (§2 sans `OK`), GPS et tablette OK | badge `GRIB` ou `MANUEL` ; recopier TWD/TWS du B&G toutes les 30 min |
| **Plan B** | Pi ou appli Jabuka inutilisable, bus OK | OpenCPN sur le portable via le relais fastnet2ip (PI-SETUP §5), UDP 2002 |
| **Plan C** | plus rien d'électronique fiable | afficheurs B&G et **carte papier** ; route au compas |

Plan B en pratique (PI-SETUP §5) : `sudo systemctl start fastnet2ip` sur le Pi (l'ingest Jabuka
s'arrête tout seul), OpenCPN sur le portable en UDP entrée port 2002 sur le Wi-Fi `jabuka`.
Retour à Jabuka : `sudo systemctl start jabuka-ingest-fastnet`.

Avant de larguer (19:00) : TABLET-SETUP « Night-before checklist » refaite, tablette en charge,
verrouillée ; portable chargé à bord ; SD de secours et ce runbook dans le sac étanche.

## Annexe A — Répétition sur le portable

Commande : `bash scripts/commissioning-rehearsal.sh --steps all` (complète, hors ligne : la
répétition du pack réel `R6.dryrun` est `SKIP « hors ligne »` ; avec internet ajouter
`--online`). Le 12 novembre, refaire `R3.*` avec `--capture` sur la vraie capture (§3). La
version rapide (`bash scripts/commissioning-rehearsal.sh`, ~10 s) tourne dans la porte
(`tests/commissioning`).

Dernière répétition complète : **2026-11-06 20:15 UTC**, commit de la tâche 3 du plan 04-02 (sur
`9ed8631`), portable i7, Python 3.14, capture de test `example2_fastnet_data.txt`, **202 s**,
code 0. Lignes résumées (le détail complet est dans `var/rehearsal/<horodatage>/results.json`) :

```text
[HUMAN] R1.packing §1 Sac de bord
[PASS] R1.wheelhouse §1 Wheelhouse complète : 19 paquets verrouillés, une roue chacun + jabuka
[HUMAN] R1.soak §1 Endurance race-36h : aucun rapport race-36h dans var/soak : bash scripts/soak.sh
[HUMAN] R2.wiring §2 Prise sur le bus
[PASS] R2.silent §2 Bus muet → NO BYTES : attendu NO BYTES (code 2), obtenu code 2 (pty en direct)
[PASS] R2.swap §2 Fils inversés → croiser Blanc/Vert : attendu BYTES BUT NO VALID FRAMES (code 3), obtenu code 3 (pty en direct)
[PASS] R2.noisy §2 Bus bruité → NOISY : attendu NOISY (code 4), obtenu code 4 (pty en direct)
[PASS] R2.ok §2 Bon câblage → OK : attendu OK (code 0), obtenu code 0 (pty en direct) : OK: 102.6 frames/s, 54 channels
[HUMAN] R3.pages §3 Pages B&G pendant la capture
[PASS] R3.capture §3 Capture brute (fastnet-probe) : probe code 0 : OK: 102.6 frames/s, 54 channels ; fichiers ['capture.log', 'inventory.json']
[PASS] R3.inventory §3 Inventaire des canaux : 42 canaux décodés sur 54 vus
[PASS] R3.archive §3 Archive de la capture : archive/capture-20261106T201554Z.tar.gz (sha256 326f78d706fb…)
[PASS] R3.replay §3 Rejeu propre dans la chaîne : 42 chemins de l'inventaire servis par /api/state en 0.6 s
[PASS] R3.logcheck §3 Journaux du rejeu intacts : jabuka-logcheck code 0 : logcheck: OK (1 files, 0 torn tails)
[PASS] R4.variation §4 Cap magnétique + variation = cap vrai : cap bus 111.0°M + variation 4.7° = 115.7°T, nav 115.7°T, bateau 116.0°T
[PASS] R4.cog_hdg §4 COG contre cap vrai : COG 116.0°T, cap vrai 115.7°T : écart 0.3° (≤ 3°, sans courant)
[PASS] R4.awa_sign §4 Signe de l'AWA : tribord amures (TWA +45) → AWA +33°, TWA nav +45°
[PASS] R4.twd §4 TWD calculé contre scripté : écart 0.4° (≤ 5°) ; moitié instrument SKIP (pas de canal TWD 0x6D)
[HUMAN] R4.dock §4 Contrôles au port / au moteur
[HUMAN] R4.underway §4 Contrôles sous voiles
[PASS] R5.offline §5 Page de barre sans internet : 8 ressources de la page, toutes servies par le Pi
[HUMAN] R5.setup §5 Réglage de la tablette
[PASS] R6.pack §6 Route adoptée sur le pack : route version 1 adoptée (état ok, pack uniform ok)
[SKIP] R6.dryrun §6 Répétition du pack réel : hors ligne (--online lance scripts/racepack-dryrun.sh)
[HUMAN] R6.friday §6 Pack final du vendredi
[PASS] R7.drill §7 Changement de parcours : parcours B → Finir ici à Mulo → Finir ici annulé → Côtés confirmés → parcours A en 0.07 s (< 30 s)
[HUMAN] R7.si §7 Parcours d'après les IC
[PASS] R8.gribonly §8 Bus muet → GRIB : GRIB (TWD 160.6°T, 12.0 nd, alerte VENT GRIB (pas d'instruments)) → LIVE au retour du bus
[PASS] R8.manual §8 Vent manuel : GRIB → saisie 150°M 14 nd → MANUEL 154.7°T → effacé → GRIB
[PASS] R8.stay §8 ON RESTE : ON RESTE actif (bord stbd) → ANNULER ON RESTE : inactif
[PASS] R8.powerpull §8 Coupure d'alimentation : kill -9 ingest + cœur, redémarrage en 0.9 s : parcours, réglages et vent manuel identiques, bus de retour, jabuka-logcheck OK
[HUMAN] R8.boat §8 Exercices à bord
[HUMAN] R8.sdswap §8 Échange de carte SD
[PASS] R9.summary §9 Bilan go / no-go : 21 PASS, 0 FAIL, 1 SKIP, 11 HUMAN
jabuka-rehearsal: 22 PASS, 0 FAIL, 1 SKIP, 11 HUMAN en 202 s -> OK
```

À refaire après le gel (11 nov.) : `R1.soak` doit alors être `PASS` (rapport race-36h du
portable) et la wheelhouse reconstruite depuis le tag.

## Annexe B — Renvois

Chaque élément encore en attente a sa place les 11–13 novembre. « Maison » = avant de partir
(§1, [FREEZE](FREEZE.md), [SPARE-SD](SPARE-SD.md)).

| Élément en attente | Où / quand | Étape |
|---|---|---|
| 01-UAT #1 Pi provisionné, services actifs | maison (11 nov., après le gel) | §1, FREEZE |
| 01-UAT #2 Tablette sur l'AP | 12 nov. 11:30 | §5 [R5.setup] |
| 01-UAT #3 Page Diag dans un vrai navigateur | 12 nov. 11:30 | §5 [R5.setup] |
| 01-UAT #4 Port série sur le Pi (PI-SETUP §4 b–d) | 12 nov. 09:40 | §2 [R2.wiring] |
| 01-UAT #5 Sonde sur le matériel | maison (sans bus, PI-SETUP §4 l) puis 12 nov. 09:45 | §1, §2 [R2.ok], §3 [R3.capture] |
| 01-UAT #6 Heure GPS sans internet (PI-SETUP §4 e–f) | maison, recontrôle le 13 | §1, §9 |
| 01-UAT #7 REL-01 sur le Pi (PI-SETUP §4 h–k) | maison, puis 12 nov. 14:20 | §1, §8 [R8.boat] |
| 01-UAT #8 Revue du verrou | 11 nov. | FREEZE |
| 02-UAT #1 Vue Barre hors ligne sur la tablette | 12 nov. 11:50 | §5 [R5.setup] |
| 02-UAT #2 Écran toujours allumé | 12 nov. 11:40 | §5 [R5.setup] |
| 02-UAT #3 Lisibilité de nuit | 12 nov. 18:30 | §5 |
| 02-UAT #4 Verrou sous les embruns | 12 nov. 12:00 | §5 [R5.setup] |
| 02-UAT #5 Polaire réelle du X35 | maison | §1 |
| 02-UAT #6 Marques, côtés, ligne contre les IC | 13 nov. 13:00 | §7 [R7.si] |
| 02-UAT #7 Chiffre principal au près | 12 nov. sous voiles | §4 [R4.underway] |
| 02-UAT #8 Vent LIVE et repli manuel | 12 nov. | §4 [R4.underway], §8 [R8.manual] |
| 02-UAT #9 Parcours et réglages après une coupure | 12 nov. 14:20 | §8 [R8.powerpull] |
| 02-UAT #10 Revue du verrou | 11 nov. | FREEZE |
| 03-06 Tablette : route et virement lisibles, ON RESTE au pouce mouillé | 12 nov. (§5), 13 nov. 17:20 | §5, §6, §8 |
| 03-06 `racepack-dryrun.sh` avec Overpass joignable | maison et 13 nov. avant 16:00 | §1, §6 [R6.dryrun] |
| 03-06 Banc du Pi, `route_level` | 9 nov. | §1 |
| 03-06 Courant Copernicus (compte du propriétaire) | 13 nov. 16:50 (option) | §6 |
| 03-06 Prévision de l'organisateur | dès publication, 13 nov. 16:50 | §6 |
| 03-06 Revue des paquets (numpy, prep) | 11 nov. | FREEZE |
| 03-06 Pack final du vendredi | 13 nov. 16:40 | §6 [R6.friday] |
| PI-SETUP §4 a Services actifs | maison, puis chaque matin | §1, §9 |
| PI-SETUP §4 g Tablette sur l'AP | 12 nov. 11:30 | §5 |
| PI-SETUP §4 m Revue du verrou | 11 nov. | FREEZE |
