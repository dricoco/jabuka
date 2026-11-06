# Mise en service à bord — Regata Jabuka 2026 (X35)

Le runbook unique pour mettre Jabuka en service sur le bateau, en une séance, les **jeudi 12
novembre** (premier jour à bord) et **vendredi 13 novembre** (jour de course, départ à partir de
**20:00 heure locale**). Heure locale = CET = **UTC + 1**. Toutes les heures de ce document sont
locales, sauf mention « UTC ».

Ce document ne recopie pas les contrôles déjà écrits : il dit **quand** les faire et renvoie aux
sources (`deploy/PI-SETUP.md`, `docs/TABLET-SETUP.md`, `docs/WEATHER-PACK.md`, `docs/ROUTING.md`,
les fichiers UAT des phases 1 et 2, les « Human items » de 03-06). L'annexe B fait le lien entre
chaque élément en attente et le moment où on le traite à bord.

## Lire ce document

- Chaque ligne d'action : **heure approximative**, **action**, **repère**, **ce qu'on doit voir**.
- Repère **`[R2.swap]`** : l'étape est **répétée sur le portable** par
  `bash scripts/commissioning-rehearsal.sh` (même identifiant dans la sortie du script).
- Repère **HUMAN** : l'étape demande le bateau, le Pi ou la tablette ; le script l'affiche avec
  l'observation attendue, sans pouvoir la faire.
- Les commandes `sh` sont à taper sur le Pi (SSH par Ethernet ou par le Wi-Fi `jabuka`) ou sur le
  portable, comme indiqué. Les outils du Pi sont dans `/opt/jabuka/venv/bin/`.

## Répéter sur le portable (avant de partir, et à quai)

```sh
bash scripts/commissioning-rehearsal.sh                  # rapide (~30 s) : §2–§4, §5, §7
bash scripts/commissioning-rehearsal.sh --steps all      # complète (~4 min) : + §1, §6, §8, §9
bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.replay,R3.logcheck \
    --capture <capture.log du bateau>                    # le 12 nov., sur la vraie capture
```

Chaque étape imprime une ligne `[PASS|FAIL|SKIP|HUMAN] <id> §<n> <titre> : <détail>`. Code de
sortie 0 : aucune étape en échec. Les résultats vont dans `var/rehearsal/<horodatage UTC>/`.

## Plan des deux journées

À compléter (tâche 2).

## 1. Avant de partir (maison)

À compléter : liste de colisage, pack de course, banc Pi, endurance, gel, carte SD de secours.

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
| 09:30 | Pi et instruments **éteints**. Poser le faisceau de dérivation sur le bus Fastnet : Blanc → T/R+, Vert → T/R−, masse → GND. Aucune terminaison. Photos du câblage (bornier B&G et DTECH). | HUMAN [R2.wiring] | Photos prises, rien de dénudé qui traîne |
| 09:40 | Allumer les instruments B&G, puis le Pi. Vérifier le port en réception seule. | HUMAN [R2.wiring] | PI-SETUP §4 b (`crw-r----- root dialout`) et §4 d (seul l'ingest tient le port) |
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

Renvois : 01-UAT #5 (sonde sur le matériel : `NO BYTES` sans bus, puis `OK` au bateau),
PI-SETUP §4 l (sonde sur un bus débranché, à faire à la maison), PI-SETUP §6 (dépannage).

## 3. Capture et inventaire

But : enregistrer les **octets bruts du bus avant toute autre manipulation**, avec tous les
canaux que ce bateau peut émettre, pour pouvoir tout rejouer au portable si quelque chose
cloche ensuite (PITFALLS Pitfall 3 : les canaux attendus ne sont peut-être pas sur ce bus).

| Heure (12 nov.) | Action | Repère | On doit voir |
|---|---|---|---|
| 10:00 | Lancer la capture longue (commande ci-dessous), **avant tout autre réglage**. | [R3.capture] | `fastnet-probe: reading /dev/fastnet for 600 s ...` |
| 10:00–10:10 | Pendant la capture : faire défiler **toutes les pages de tous les afficheurs B&G** (cap magnétique et vrai, TWD, set/drift, VMG, TWA cible, cap sur l'autre bord, profondeur, loch). | HUMAN [R3.pages] | Chaque page affichée au moins 10 s |
| 10:10 | Lire l'inventaire imprimé : canaux vus, noms, dernières valeurs. Noter ce qui manque (TWD 0x6D ? cap 0x49 ? set/drift 0x83/0x84 ?). | [R3.inventory] | Au minimum : BSP 0x41, AWA 0x51, AWS 0x4F, cap 0x49 |
| 10:15 | Copier la capture sur le portable et l'archiver (commande ci-dessous). | [R3.archive] | `capture.log`, `inventory.json` sur le portable |
| 10:20 | Sur le portable : rejouer la vraie capture dans toute la chaîne. | [R3.replay] [R3.logcheck] | 4 lignes `PASS` |
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
chemin décodé de l'inventaire est servi par `/api/state`.

Renvois : 01-UAT #5 (garder `inventory.json` et `capture.log`), PI-SETUP §4 l.

## 4. Contrôles des instruments

À compléter : vrai/magnétique, COG/cap, signe de l'AWA, BSP, TWD Hercules contre calculé,
choix de `true_wind_source`.

## 5. Tablette

À compléter : AP, mode avion, drapeau Chrome, écran allumé, luminosité de nuit, verrou, support.

## 6. Pack de course (vendredi 13 après ~15:40 UTC)

À compléter : ICON-EU/EWAM final, masque terre, GRIB de l'organisateur, contrôle, copie au Pi.

## 7. Parcours

À compléter : côtés et ligne d'après les IC, exercice de changement de parcours en moins de 30 s.

## 8. Exercices en mode dégradé

À compléter : bus débranché (GRIB), vent manuel, ON RESTE, coupure d'alimentation, carte SD.

## 9. Go / no-go et plans B

À compléter : critères, Plan B (OpenCPN via le relais), Plan C (afficheurs B&G et carte papier).
