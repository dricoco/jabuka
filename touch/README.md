# jabuka-touch — menu tactile de l'écran 3,5 pouces

Menu en français pour l'écran MHS35 (480 × 320) du Pi : en arrivant au bateau, on vérifie tout le
système d'un coup d'œil et on agit au doigt, sans ordinateur. Le menu est un simple ajout : il
lit l'API du cœur (127.0.0.1) et lance des commandes existantes. S'il plante ou s'il est
désinstallé, la navigation (jabuka-core, jabuka-ingest-fastnet) continue.

## Ce que montre et fait le menu

- **Accueil** : dix voyants (vert = ok, orange = attention, rouge = problème, gris = inconnu),
  mis à jour chaque seconde : BUS Fastnet, GPS + horloge, VENT, MÉTÉO (pack), ROUTE, WI-FI
  (mode, clients), ALIM (sous-tension), TEMP. CPU, DISQUE (/var/lib/jabuka), SERVICES. Toucher
  les voyants ouvre le détail. « cœur muet » en rouge = jabuka-core ne répond pas.
- **MÉTÉO / WI-FI** : LANCER PRERACE (météo par le partage du téléphone), JOURNAL (suivi en
  direct, RÉSULTAT = `prerace status`), WI-FI BATEAU / WI-FI TÉLÉPHONE.
- **DÉMO** : bateau simulé que la tablette voit sur http://10.42.0.1 ; MODE COURSE revient aux
  capteurs réels.
- **SYSTÈME** : REDÉMARRER SERVICES, TERMINAL, NUIT / JOUR, REDÉMARRER LE PI, ÉTEINDRE.

Toute action risquée demande une confirmation OUI / NON (annulée seule après 8 s). Les appuis
sont ignorés 0,6 s après chaque changement d'écran.

## Installation (sur le Pi)

Paquets système : `sudo apt install python3-pil python3-numpy fonts-dejavu-core`, puis depuis la
copie du dépôt sur le Pi :

    cd touch && python3 -m jabuka_touch selftest --out /tmp/touch-png   # rend chaque écran en PNG
    sudo bash touch/install.sh

Le script est rejouable (mise à jour) ; il garde `/etc/jabuka-touch.json` (calibration) et ne
touche ni à la configuration de démarrage du Pi, ni à /opt/jabuka, ni aux unités du cœur.

## Depuis un shell (clavier USB sur l'écran, ou SSH)

- revenir au menu depuis le TERMINAL : `sudo jabuka-touch` (ou redémarrer le Pi) ;
- état en texte : `sudo jabuka-touch status` ;
- quitter la démo, mode course : `sudo jabuka-touch course` ;
- recalibrer le toucher : `sudo jabuka-touch calibrate` (toucher le centre de 3 croix ; valeurs
  dans la section `touch` de `/etc/jabuka-touch.json`, défaut 3936 227 268 3880 + swap_xy).

## Ce que change la DÉMO

- Deux drop-ins **volatils** `zz-jabuka-touch-demo.conf` dans
  `/run/systemd/system/{jabuka-core,jabuka-ingest-fastnet}.service.d/` : l'ExecStart installé
  (drop-ins de l'opérateur compris, par exemple `--awa-sign -1`) avec seulement les données,
  le pack, l'horloge simulée, le faux gpsd (:2948) et le pty du bateau simulé changés.
- Les données de démo vont dans `/var/lib/jabuka-demo` (effacé à chaque démarrage). Les données
  de course (`/var/lib/jabuka` : pack, parcours, réglages) sont seulement lues.
- Un redémarrage du Pi revient **toujours** en mode course (`/run` est vidé).
- La démo refuse de démarrer (« ÉCHEC démo ») si un drop-in local s'appliquerait après le sien, si
  un soak ou prerace tourne, ou si le pack de course manque ; tout échec revient en mode course.
- Ne jamais lancer un soak (`scripts/soak.sh --systemd system`) pendant une démo : notre drop-in
  `zz-` passerait devant le `50-` du soak. Revenir d'abord en mode course.
- Si MODE COURSE dit qu'une unité n'est pas active : redémarrer le Pi.

## Désinstaller

    sudo bash touch/uninstall.sh

Termine d'abord une démo en cours, retire le menu et rend tty1 à la console texte (getty).
`/etc/jabuka-touch.json` est gardé.

## Tests

`.venv313/bin/python -m pytest tests/touch` (fait partie de `scripts/check.sh`). Le rendu
(Pillow) est testé par `cd touch && python3 -m jabuka_touch selftest --out DIR`, qui rend chaque
écran en PNG ; à faire aussi sur le Pi avant d'installer.
