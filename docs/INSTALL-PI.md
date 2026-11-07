# Guide d'installation — Raspberry Pi 3B, de la carte SD vierge à la tablette en course

## 1. Introduction

Ce guide suit, dans l'ordre, tout le chemin d'installation de Jabuka : une carte microSD vierge
au départ, et à l'arrivée la tablette qui affiche la carte et la route à la barre, en course, sans
internet.

Le résultat :

- un point d'accès Wi-Fi WPA2 **`jabuka`** ;
- l'application à l'adresse **http://10.42.0.1/** ;
- l'ingest Fastnet et le cœur qui démarrent au boot et redémarrent seuls après un plantage.

Ce guide est une synthèse. Il ne recopie pas les vérifications détaillées, le Plan B ni le
dépannage : il renvoie aux documents qui les contiennent. Les commandes, noms de fichiers,
options et sorties de programme sont laissés tels quels (en anglais quand ils le sont dans le
dépôt).

Où trouver le détail :

- [deploy/PI-SETUP.md](../deploy/PI-SETUP.md) : le runbook de référence du Pi. Section 4 :
  la liste complète des vérifications ; section 5 : le Plan B fastnet2ip + OpenCPN ; section 6 :
  le dépannage.
- [RACE-PACK.md](RACE-PACK.md) : la carte hors ligne et la polaire.
- [WEATHER-PACK.md](WEATHER-PACK.md) : le vent, les vagues, le courant, et la check-list du
  vendredi 13 novembre.
- [TABLET-SETUP.md](TABLET-SETUP.md) : le réglage complet de la tablette.
- [SPARE-SD.md](SPARE-SD.md) : la carte SD de secours.
- [COMMISSIONING.md](COMMISSIONING.md) : la mise en service à bord, 12 et 13 novembre.
- [FREEZE.md](FREEZE.md) : le gel du code du 11 novembre.
- [SOAK.md](SOAK.md) : l'essai d'endurance de 36 h.

Convention : `<user>` est le nom d'utilisateur choisi à l'étape 4, `<passphrase>` le mot de
passe du Wi-Fi `jabuka`. Les outils du portable sont dans `.venv/bin/`, ceux du Pi dans
`/opt/jabuka/venv/bin/`.

## 2. Matériel

D'après [PI-SETUP](../deploy/PI-SETUP.md) section 0 et [TABLET-SETUP](TABLET-SETUP.md) :

- un **Raspberry Pi 3B** ;
- une **bonne alimentation 5 V 3 A** : une sous-tension corrompt la carte SD et provoque des
  redémarrages au hasard ;
- une **carte microSD**, plus une **carte de secours** pour le clone (section 10) ;
- l'adaptateur **DTECH USB RS422/485** (FTDI FT232R) sur le bus Fastnet, **en réception seule** ;
- le **GPS USB VK-162** (u-blox 7) ;
- un **câble Ethernet** vers la box de la maison. L'installation se fait par Ethernet, **jamais
  par le Wi-Fi** ;
- la **tablette Android** avec **Chrome**, pour la barre.

## 3. Sur le portable (avec internet)

Tout se fait dans le dépôt, sur le portable.

### 3.1 Environnement de développement

Créer les environnements Python du portable :

```bash
bash scripts/bootstrap-dev.sh
```

Attendu : la dernière ligne est `bootstrap: ok`. Le script installe aussi l'extra `prep`
(osmium, pygrib, shapely, netCDF4), nécessaire aux outils du pack de course (section 8). Ces
outils ne tournent que sur le portable, jamais sur le Pi.

### 3.2 Wheelhouse hors ligne

Le Pi installe l'application depuis une réserve de paquets construite ici (il faut internet) :

```bash
bash scripts/build-wheelhouse.sh
```

Attendu : la dernière ligne est `build-wheelhouse: ok`, et `ls deploy/wheelhouse` liste 18
roues, dont `jabuka-0.1.0-py3-none-any.whl`.

### 3.3 Secret Wi-Fi

Le mot de passe du Wi-Fi `jabuka` fait 8 à 63 caractères. Il n'est jamais commité :
`deploy/secrets.env` est ignoré par git.

```bash
cp deploy/secrets.env.example deploy/secrets.env
chmod 600 deploy/secrets.env
$EDITOR deploy/secrets.env        # set JABUKA_PSK=<your passphrase>
```

Remplacer la valeur d'exemple : `provision.sh` la refuse.

### 3.4 Répétition à blanc de l'installation

Vérifier le plan d'installation sans rien toucher :

```bash
bash deploy/provision.sh --dry-run --psk-file deploy/secrets.env
```

Attendu : chaque étape de a à k s'affiche sous forme de lignes `+ ...`, le mot de passe apparaît
en `***`, et le code de sortie vaut 0.

## 4. Flasher la carte SD

1. Installer Raspberry Pi Imager 2.x sur le portable.
2. Choisir **Raspberry Pi 3**, **Raspberry Pi OS Lite (64-bit)** (Debian 13 « Trixie »), puis la
   carte SD.
3. Dans les réglages de personnalisation, mettre :
   - nom d'hôte `jabuka` ;
   - un nom d'utilisateur et un mot de passe (c'est l'utilisateur `<user>` pour SSH) ;
   - SSH : activé, **par clé publique uniquement**, coller la clé `~/.ssh/id_ed25519.pub` du
     portable ;
   - Wi-Fi : ne configurer **aucun réseau**, régler seulement le **pays Wi-Fi HR** ;
   - fuseau horaire `Europe/Zagreb`, clavier au choix.
4. Écrire la carte.

Variante sans Imager (sans personnalisation : il faut alors ajouter soi-même l'utilisateur et la
clé SSH) :

```bash
xz -dc 2026-xx-xx-raspios-trixie-arm64-lite.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync
```

Attention : `/dev/sdX` doit être la carte SD, pas le disque du portable.

À savoir : sur Trixie, le premier démarrage est configuré par **cloud-init**. Imager écrit
`user-data`, `network-config` et `meta-data` sur la partition de démarrage FAT. On peut donc
encore corriger l'utilisateur ou la clé SSH dans ces fichiers, depuis n'importe quel ordinateur,
avant le premier démarrage.

## 5. Premier démarrage en Ethernet

1. Mettre la carte dans le Pi, brancher l'Ethernet, l'adaptateur DTECH et le VK-162, puis
   allumer.
2. Attendre environ 2 minutes, puis se connecter en SSH (si `jabuka.local` ne répond pas, prendre
   l'adresse du Pi dans la liste DHCP de la box) :

   ```bash
   ssh <user>@jabuka.local
   ```

3. Vérifier que les deux adaptateurs USB sont vus avec les identifiants attendus par les règles
   udev :

   ```bash
   lsusb
   ```

   Attendu : une ligne avec `0403:6001` (FTDI, le DTECH) et une ligne avec `1546:01a7` (u-blox 7,
   le VK-162).

   Si un identifiant diffère, corriger `deploy/udev/99-jabuka.rules` **sur le portable** avant
   l'étape 6. Si plusieurs appareils FTDI risquent d'être branchés un jour, épingler le DTECH par
   son numéro de série :

   ```bash
   udevadm info -a -n /dev/ttyUSB0 | grep -m1 'ATTRS{serial}'
   ```

   Puis ajouter `ATTRS{serial}=="<that value>"` à la règle fastnet.

## 6. Installation

1. Depuis le portable, copier le dépôt sur le Pi, avec `deploy/wheelhouse/` et
   `deploy/secrets.env`, mais sans les environnements virtuels du portable :

   ```bash
   rsync -a --delete --exclude '.venv*' --exclude '.git' --exclude '__pycache__' \
       ./ <user>@jabuka.local:jabuka/
   ```

2. Sur le Pi, toujours en Ethernet :

   ```bash
   cd ~/jabuka
   sudo deploy/provision.sh --psk-file deploy/secrets.env
   ```

   Attendu : les étapes a à k passent sans `ERROR`. La dernière étape monte le point d'accès et
   prévient qu'une session SSH par Wi-Fi serait coupée (la vôtre passe par l'Ethernet, elle
   reste). Le script se termine par `k. done` et rappelle de lancer les vérifications et de
   redémarrer.

   Le script est **idempotent** : le relancer après tout changement (par exemple une nouvelle
   wheelhouse). Il n'a besoin d'internet que pour `apt-get`. L'application et le Plan B fastnet2ip
   s'installent depuis la wheelhouse avec `--require-hashes` (`deploy/requirements.lock`,
   `deploy/fastnet2ip.lock`). Une fois tous les paquets apt installés, une nouvelle exécution
   fonctionne donc **hors ligne**.

3. Redémarrer une fois. Cela arme le chien de garde matériel (watchdog) et prouve que le Pi
   démarre proprement sans écran ni clavier :

   ```bash
   sudo reboot
   ```

## 7. Vérifications essentielles

Les cinq contrôles qui doivent passer avant d'aller plus loin. Ils sont tirés de
[PI-SETUP](../deploy/PI-SETUP.md) section 4 (lettres entre parenthèses).

1. **Les deux services tournent** (4 a) :

   ```bash
   systemctl status jabuka-ingest-fastnet jabuka-core
   systemctl is-enabled jabuka-ingest-fastnet jabuka-core
   ```

   Attendu : deux fois `active (running)` et deux fois `enabled`.

2. **Les périphériques Fastnet et GPS existent** (4 b) :

   ```bash
   ls -l /dev/fastnet /dev/gps
   ls -lL /dev/fastnet
   ```

   Attendu : les deux liens existent, et `/dev/fastnet` pointe vers un nœud `ttyUSB` affiché
   `crw-r----- 1 root dialout` (lecture seule pour le groupe du service).

3. **Position GPS et heure GPS** (4 e) :

   ```bash
   gpspipe -w -n 5 | grep TPV
   chronyc sources
   ```

   Attendu : des lignes TPV avec `"mode":3` (ou 2), et une ligne `#* GPS` dans `chronyc sources`
   une fois que chrony l'a choisie (compter quelques minutes après un démarrage à froid). Le GPS
   doit voir le ciel.

4. **Le chien de garde est armé** (4 k) :

   ```bash
   dmesg | grep -i watchdog
   ```

   Attendu : une ligne qui montre le watchdog bcm2835 en service, avec un délai d'environ 15 s.

5. **La tablette rejoint le point d'accès** (4 g) : sur la tablette, oublier les autres réseaux et
   couper les données mobiles. Rejoindre `jabuka` avec le mot de passe, puis ouvrir
   **http://10.42.0.1/**.

   Attendu : la page de diagnostic de Jabuka, avec les valeurs, leurs sources et leurs âges.

**Pour la liste complète** (réglages série du FTDI, seul l'ingest tient l'adaptateur, démarrage
sans internet, reprise après `kill -9`, débranchement des adaptateurs, 5 coupures de courant,
sonde sur bus débranché, revue du verrou des paquets), voir
[deploy/PI-SETUP.md section 4](../deploy/PI-SETUP.md#4-verify-checklist-human-check-record-passfail-for-each-item).

## 8. Charger le pack de course

Le Pi n'a pas internet en course. Tout ce que la tablette affiche et tout ce que le routeur sait
de la météo vient du **pack de course**, un dossier construit sur le portable (`var/racepack/`,
ignoré par git) puis copié sur le Pi dans `/var/lib/jabuka/racepack`. Le cœur le lit au
démarrage.

**La carte et la météo partagent le même dossier `var/racepack`.** La copie vers le Pi utilise
`rsync --delete` : construire **toutes** les parties (carte, météo, terre, polaire) avant de
copier, sinon ce qui manque sur le portable est effacé sur le Pi.

### 8.1 Carte hors ligne

Prérequis : internet, l'environnement de la section 3.1, et environ 300 Mo libres sous `var/`.

```bash
.venv/bin/jabuka-prep-map --out var/racepack
```

Attendu : le fond de carte `race.pmtiles` (environ 12 Mo, 6 190 tuiles, une dizaine de secondes),
puis les amers `seamarks.geojson` et le trait de côte `coastline.geojson` (téléchargement
Geofabrik d'environ 200 Mo, mis en cache), puis le manifeste `racepack.json` et un résumé.

Protomaps ne garde chaque construction quotidienne qu'**une semaine**. Refaire la carte le **11 ou
le 12 novembre**, à partir d'une construction récente. Si la sortie affiche `COASTLINE-ONLY PACK`,
il n'y a que le trait de côte : refaire la carte avec internet avant de partir.

Contrôle avant de quitter le quai :

```bash
.venv/bin/jabuka-prep-map --check var/racepack
```

Attendu : `check ok`. En cas de problème, une ligne `CHECK FAILED` par défaut, et le code 3.

Détails (options, replis, codes de sortie) : [RACE-PACK.md](RACE-PACK.md).

### 8.2 Météo (vent, vagues, courant, terre)

Le pack météo final se fait le **vendredi 13 novembre**, **après environ 15:40 UTC** (16:40 heure
locale), quand le run 12Z d'ICON-EU est complet. Suivre la
[Checklist vendredi 13 novembre](WEATHER-PACK.md#checklist-vendredi-13-novembre-pack-final) de
WEATHER-PACK.md, minute par minute. Les horaires de publication de DWD y sont expliqués.

Les commandes, depuis le dépôt sur le portable :

```bash
# 1. Vent ICON-EU
.venv/bin/jabuka-prep wind --out var/racepack

# 2. Vagues EWAM
.venv/bin/jabuka-prep waves --out var/racepack

# 3. Option : prévision de l'organisateur (GRIB1 ou GRIB2)
.venv/bin/jabuka-prep grib <fichier GRIB de l'organisateur> --out var/racepack --name wind_organiser

# 4. Option : courant Copernicus (fichier téléchargé avec votre compte, voir WEATHER-PACK.md)
.venv/bin/jabuka-prep current current_med.nc --out var/racepack

# 5. Masque terre
.venv/bin/jabuka-prep land build --out var/racepack

# 6. Champs de distance vers les marques (après land build, voir ROUTING.md)
.venv/bin/python -m jabuka.prep.cli geofields --marks src/jabuka/nav/data/marks.json --out var/racepack

# 7. Contrôle de tout le pack (mêmes règles que le Pi)
.venv/bin/jabuka-prep check --out var/racepack
```

Avec `--name wind_organiser`, le fichier de l'organisateur ne remplace pas `wind.npz` : on garde
les deux et on choisit plus tard (renommer en `wind.npz` / `wind.json`). Le masque terre et les
champs de distance peuvent être construits la veille ; ils restent dans `var/racepack`.

Lire le rapport (`coverage.txt`) :

- `COUVERTURE MÉTÉO : OK` et code **0** : le vent couvre toute la fenêtre, toutes les marques et
  tous les bords.
- `MÉTÉO INCOMPLÈTE` et code **3** : au moins une ligne `ALERTE : MÉTÉO INCOMPLÈTE : ...`. Les
  fichiers sont quand même écrits. Corriger (run plus récent, autre GRIB) avant de quitter le
  quai ; les cas « DWD en retard » sont dans WEATHER-PACK.md.
- Code **2** : problème d'entrée (fichier absent, GRIB illisible, pas de vent trouvé).

**Ne jamais copier seulement les fichiers `.npz`.** Chaque `.npz` a un fichier `.json` à côté
(avec son sha256). Sans ce fichier, le Pi rejette le `.npz`.

### 8.3 Polaire

Sans `polar.json` dans le pack, le cœur utilise la **polaire intérimaire** « X35 ORC OD 2019
(intérim) ». Pour mettre la polaire du bateau :

```bash
.venv/bin/jabuka-prep-polar <fichier polaire> --name "X35 owner" --out var/racepack/polar.json
```

Les formats OpenCPN / qtVlm, Expedition et les tableaux de certificat ORC sont reconnus par leur
contenu. L'outil affiche le tableau des cibles VMG : le comparer avec ce que le bateau marche
vraiment avant de copier. Une valeur fausse est signalée avec son numéro de ligne (code 2) et
rien n'est écrit. Si le cœur ne peut pas valider `polar.json`, il reprend la polaire intérimaire.

### 8.4 Copier le pack sur le Pi

Rejoindre le Wi-Fi `jabuka` (ou passer par l'Ethernet et `jabuka.local`), puis :

```bash
rsync -a --delete var/racepack/ <user>@10.42.0.1:/tmp/racepack/
ssh <user>@10.42.0.1
sudo rsync -a --delete /tmp/racepack/ /var/lib/jabuka/racepack/
sudo chown -R jabuka:jabuka /var/lib/jabuka/racepack
sudo systemctl restart jabuka-core
```

Le cœur lit `/var/lib/jabuka/racepack` par défaut (`--data-dir /var/lib/jabuka`).

### 8.5 Contrôles sur la tablette (onglet Diag)

- La ligne de santé `racepack` montre `tiles true` (ou `tiles false` avec `coastline true` pour un
  pack réduit au trait de côte).
- La carte s'affiche alors que la tablette n'a que le Wi-Fi `jabuka`, donc sans internet.
- On voit Plić Sestre (balise), Blitvenica et Mulo (feux).
- Le nom de la polaire en service est affiché sur Diag.
- Si la bannière **MÉTÉO INCOMPLÈTE** s'affiche sur les pages Barre et Diag, le vent du pack ne
  couvre pas toute la course. Au-delà de la dernière échéance, le routeur garde le dernier champ de
  vent. Refaire le pack météo si c'est possible (section 8.2).

### 8.6 Parcours

Le parcours se règle sur la tablette (connectée au Pi, section 9), d'après les instructions de
course (IC), le **13 novembre**. Ce que COMMISSIONING.md §7 prévoit :

- onglet Carte : parcours A ou B, côtés de passage et rayons contre les IC ; déplacer la ligne de
  Vodice du point provisoire 43.7500N 15.7800E vers la vraie ligne ;
- **« Côtés confirmés »** : l'alerte « Côtés à confirmer (IC) » disparaît ;
- exercice : passer à l'autre parcours, « Finir ici », l'annuler, revenir, en moins de 30 s ;
- imprimer ou écrire la carte du parcours (marques, côtés, ligne, réglages).

Le détail : [COMMISSIONING.md](COMMISSIONING.md), section 7.

## 9. Connecter la tablette

Résumé de [TABLET-SETUP.md](TABLET-SETUP.md). À faire une fois au port, Pi allumé.

1. **Réseau** : oublier les autres réseaux Wi-Fi, couper les données mobiles. Rejoindre **`jabuka`**
   (WPA2, mot de passe de `deploy/secrets.env`). Ouvrir Chrome sur **`http://10.42.0.1`** (port
   80, pas de `:8080` sur le bateau). La page s'ouvre sur l'onglet **Barre** ; le diagnostic est
   sur l'onglet **Diag**.
2. **Drapeau Chrome (indispensable)** pour garder l'écran allumé :
   - ouvrir `chrome://flags/#unsafely-treat-insecure-origin-as-secure` ;
   - le mettre sur **Enabled** et taper exactement **`http://10.42.0.1`** (schéma et adresse,
     sans port, sans barre finale) ;
   - toucher **Relaunch** ;
   - ouvrir `http://10.42.0.1`, toucher l'écran une fois : le badge du haut doit indiquer
     **`ÉCRAN: verrou`**.
3. **Écran toujours allumé** : activer les options pour développeurs (toucher 7 fois **Build
   number**), puis **Stay awake** sur ON ; tablette **en charge** pendant toute la course ; délai
   de mise en veille au maximum ; optimisation de batterie désactivée pour Chrome.
4. **Plein écran** : menu Chrome → **Add to Home screen**, puis ouvrir la barre depuis cette
   icône.
5. **Carte (WebGL)** : `chrome://gpu` doit indiquer **WebGL: Hardware accelerated**. Sur l'onglet
   Barre, la mer, la côte, le parcours, les marques, les laylines et les amers sont dessinés. Le
   badge **`CARTE INDISPONIBLE`** signifie pas de WebGL : les chiffres marchent, seule la carte
   manque.
6. **Mode nuit** : bouton **`☾ Nuit`** (fond noir, rouge seulement) et son curseur de luminosité ;
   baisser aussi la luminosité d'Android. Vérifier dans le noir : aucune lumière blanche ou
   verte.

Dans [TABLET-SETUP.md](TABLET-SETUP.md) : le verrouillage contre les embruns (section 8), la
signification des badges (section 9), le débogage à distance (section 10), et la check-list de la
veille, à refaire le 13 novembre.

## 10. Carte SD de secours

Une carte SD peut mourir en mer (coupures, sous-tensions, humidité). La parade : une **deuxième
carte identique**, clonée depuis la carte gelée, **déjà démarrée une fois**, rangée dans le sac
étanche. Détail complet : [SPARE-SD.md](SPARE-SD.md).

**Quand :** le **11 novembre**, après l'étape 8 de [FREEZE.md](FREEZE.md) (Pi réinstallé depuis le
tag `race-2026` et redémarré), et à nouveau après tout correctif d'urgence. Même modèle et au
moins la même capacité que la carte de course.

**Méthode A (recommandée), `dd` sur le portable** : éteindre le Pi (`sudo poweroff`), retirer la
carte de course, repérer le lecteur avec `lsblk -o NAME,SIZE,MODEL,TRAN` avant puis après
l'insertion, faire une image de la carte de course avec son `sha256sum`, l'écrire sur la carte de
secours, puis comparer avec `cmp` (attendu : `copie identique`). **Prendre les commandes exactes
dans [SPARE-SD.md](SPARE-SD.md) : se tromper de périphérique efface le disque du portable.** Sans
droits root sur le portable, prendre la méthode B (`rpi-clone` sur le Pi), décrite au même
endroit.

**Démarrer sur le clone** (une copie qui n'a jamais démarré n'est pas une copie de secours) :
mettre la carte de secours dans le Pi, démarrer, puis :

```sh
systemctl is-active jabuka-ingest-fastnet jabuka-core
sudo -u jabuka /opt/jabuka/venv/bin/jabuka-logcheck /var/lib/jabuka/logs
```

Attendu : `active` deux fois, `logcheck: OK`, code 0. SPARE-SD.md ajoute la sonde sur une capture,
la tablette, et la comparaison de l'empreinte du code entre les deux cartes. Remettre ensuite la
carte de course, étiqueter la carte de secours « JABUKA SECOURS race-2026 + date ».

**Échange en mer :** couper l'alimentation, changer de carte, rallumer, attendre environ
2 minutes. Puis **recopier le pack de course** (la carte de secours a celui du 11 novembre),
re-sélectionner le parcours et vérifier les réglages : voir SPARE-SD.md, « Échange de carte en
mer ».

**Racine en lecture seule (overlay) :** optionnelle, et **désactivée pour la course** (elle
effacerait le parcours et les réglages à chaque redémarrage). Voir l'annexe de SPARE-SD.md.

## 11. Avant la course

- **11 novembre, gel du code** : [FREEZE.md](FREEZE.md). Le bateau part avec exactement le tag
  `race-2026` ; après le gel, seule la configuration change. Contrôle :
  `bash scripts/freeze-check.sh` (`--pre --skip-gate` avant de poser le tag).
- **12 et 13 novembre, mise en service à bord** : [COMMISSIONING.md](COMMISSIONING.md) (câblage
  en écoute seule, capture du bus avant tout réglage, instruments, tablette, pack, parcours,
  exercices en mode dégradé, go / no-go). À répéter d'abord sur le portable avec
  `bash scripts/commissioning-rehearsal.sh` (`--steps all` pour la version complète).
- **Essai d'endurance de 36 h**, sur le portable puis sur le Pi : [SOAK.md](SOAK.md).

## 12. En cas de problème

- **Dépannage** (point d'accès absent, tablette qui ne se connecte pas, `/dev/fastnet` absent,
  ingest qui redémarre en boucle, bus muet, heure bloquée, disque plein) :
  [deploy/PI-SETUP.md section 6](../deploy/PI-SETUP.md#6-troubleshooting).
- **Plan B** si l'ingest Jabuka est inutilisable : fastnet2ip diffuse le NMEA 0183 sur le Wi-Fi
  `jabuka`, lu par OpenCPN sur le portable :
  [deploy/PI-SETUP.md section 5](../deploy/PI-SETUP.md#5-plan-b-fastnet2ip-and-opencpn).
