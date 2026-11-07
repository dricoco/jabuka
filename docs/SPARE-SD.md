# Carte SD de secours

## Pourquoi

Sur un bateau en 12 V, les coupures d'alimentation, les sous-tensions au démarrage du moteur et
l'humidité finissent par corrompre une carte SD (PITFALLS Pitfall 15). Jabuka écrit ses fichiers
de façon atomique et se relance seul après une coupure, mais une carte morte ne se répare pas en
mer. La parade : une **deuxième carte identique**, clonée depuis la carte gelée, déjà démarrée une
fois, dans le sac étanche. En mer, on change de carte en 5 minutes.

## Quand

Le **11 novembre**, après l'étape 8 de [FREEZE](FREEZE.md) (Pi réinstallé depuis le tag
`race-2026` et redémarré), et à nouveau après tout correctif d'urgence. Carte de secours : même
modèle et même capacité que la carte de course (au moins la même taille).

## Méthode A (recommandée) : `dd` sur le portable, carte du Pi éteinte

Il faut les droits root sur le portable. Sans `sudo`, prendre la méthode B.

1. Éteindre proprement le Pi (`sudo poweroff`), retirer la carte de course.
2. **Repérer le lecteur de carte**. Lister les disques **avant** d'insérer la carte, puis
   **après** : le nouveau périphérique est la carte.

   ```sh
   lsblk -o NAME,SIZE,MODEL,TRAN
   ```

   **ATTENTION : se tromper de périphérique efface le disque du portable.** Ne jamais écrire sur
   le disque système du portable (`nvme0n1`, `sda` en `TRAN sata`/`nvme`). La carte est celle qui
   vient d'apparaître, de la bonne taille (≈ 16 ou 32 Go), souvent `mmcblk0` ou `sdX` en
   `TRAN usb`. Vérifier taille **et** modèle. Démonter ses partitions si le bureau les a montées
   (`sudo umount /dev/<carte>*`).

3. **Image de la carte de course** (`<carte>` = le nom trouvé, par exemple `mmcblk0`) :

   ```sh
   sudo dd if=/dev/<carte> of=var/jabuka-race-2026.img bs=4M status=progress conv=fsync
   sha256sum var/jabuka-race-2026.img > var/jabuka-race-2026.img.sha256
   ```

4. Retirer la carte de course, insérer la **carte de secours**, refaire `lsblk` pour la repérer
   (elle doit être **au moins aussi grande** que l'image), puis écrire l'image :

   ```sh
   sudo dd if=var/jabuka-race-2026.img of=/dev/<carte> bs=4M status=progress conv=fsync
   sync
   sudo cmp -n "$(stat -c %s var/jabuka-race-2026.img)" var/jabuka-race-2026.img /dev/<carte> && echo "copie identique"
   ```

   `cmp` compare la carte à l'image sur la taille de l'image : aucune sortie sauf `copie
   identique`. Garder l'image et son `.sha256` sur la clé USB (pour refaire une carte à quai).

5. Remettre la carte de course dans le Pi.

## Méthode B : `rpi-clone` sur le Pi avec un lecteur USB

Sans root sur le portable : le Pi clone sa propre carte vers la carte de secours dans un lecteur
de cartes USB.

1. À la maison, **avec internet**, installer `rpi-clone` depuis le fork maintenu
   (`github.com/geerlingguy/rpi-clone`, script `install` du dépôt), une seule fois.
2. Arrêter les services Jabuka avant de cloner un système qui tourne :

   ```sh
   sudo systemctl stop jabuka-core jabuka-ingest-fastnet
   lsblk -o NAME,SIZE,MODEL,TRAN
   sudo rpi-clone sda
   sudo systemctl start jabuka-ingest-fastnet jabuka-core
   ```

   (`sda` = la carte de secours dans le lecteur USB, d'après `lsblk` ; jamais `mmcblk0`, la carte
   qui fait tourner le Pi.)

## Vérification : démarrer sur le clone

Une copie qui n'a jamais démarré n'est pas une copie de secours.

1. Éteindre le Pi, mettre la **carte de secours**, démarrer (Ethernet ou Wi-Fi `jabuka`).
2. Services actifs et journaux sains :

   ```sh
   systemctl is-active jabuka-ingest-fastnet jabuka-core
   sudo -u jabuka /opt/jabuka/venv/bin/jabuka-logcheck /var/lib/jabuka/logs
   ```

   Attendu : `active` deux fois, `logcheck: OK`, code 0.

3. La sonde sur une capture copiée avec le dépôt (rien à brancher) :

   ```sh
   sudo -u jabuka /opt/jabuka/venv/bin/fastnet-probe --file /home/<user>/jabuka/tests/fixtures/fastnet/example2_fastnet_data.txt --out /tmp/probe-clone
   ```

   Attendu : verdict `OK`, code 0 (avec la capture du 12 novembre, aussi `OK`).

4. La tablette ouvre `http://10.42.0.1` (onglet Barre) et l'onglet **Diag** (services, GPS).
5. **Même code que la carte de course** : empreinte du paquet `jabuka` installé. Sur chacune des
   deux cartes, noter la dernière ligne :

   ```sh
   cd /opt/jabuka/venv/lib/python3.13/site-packages/jabuka && find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum
   ```

   Les deux empreintes doivent être identiques. C'est la même valeur que `code.sha256` du
   rapport de soak du Pi et que l'empreinte affichée par `freeze-check` F4.
6. Éteindre, remettre la **carte de course**, redémarrer, vérifier `active`. Étiqueter la carte de
   secours « JABUKA SECOURS race-2026 + date », la ranger dans le sac étanche.

## Échange de carte en mer

Quand le Pi ne redémarre plus, ou que la page reste vide malgré plusieurs coupures :

1. **Éteindre** le Pi (couper son alimentation).
2. Changer de carte (carte de secours depuis le sac étanche ; garder l'ancienne au sec).
3. Rallumer. Attendre **environ 2 minutes** (démarrage, AP Wi-Fi, heure GPS).
4. La tablette se **reconnecte** seule au Wi-Fi `jabuka` ; recharger `http://10.42.0.1`.
5. **Recopier le pack de course** : la carte de secours a le pack du 11 novembre, pas celui du
   vendredi. Depuis le portable ou la clé USB, RACE-PACK « Copy to the Pi » / WEATHER-PACK
   « Copying the pack to the Pi », puis redémarrer `jabuka-core`. Sans portable : courir avec
   l'ancien pack, ou en laylines.
6. **Re-sélectionner le parcours** et confirmer les côtés d'après la carte du parcours imprimée
   (COMMISSIONING.md §7) ; remettre la marque active.
7. **Vérifier les réglages** : `variation_deg`, `heading_offset_deg`, `true_wind_source`,
   `route_level`, `efficiency` comme notés sur la carte du parcours ; drop-in `--awa-sign` si le
   bateau en avait un.

## Annexe — Système de fichiers en lecture seule (optionnel)

Une racine en lecture seule (overlay) protège la carte des coupures, mais **toute écriture dans
`/var/lib/jabuka` (journaux, parcours, réglages, vent manuel) est perdue au redémarrage**. Le
parcours et les réglages ne survivraient plus à une coupure, ce qui annule CRSE-05. **Pour la
course, l'overlay reste désactivé** : écritures atomiques et carte de secours.

Essai unique, facultatif, à la maison (avant le 9 novembre), pour savoir si c'est possible :

```sh
sudo raspi-config nonint enable_overlayfs
sudo reboot
```

Confiance faible à moyenne sur cette commande : vérifier dans le menu `sudo raspi-config` →
*Performance Options* → *Overlay File System* que l'overlay est bien actif après le redémarrage
(`mount | grep overlay`).

Retour arrière (obligatoire avant le gel) :

```sh
sudo raspi-config nonint disable_overlayfs
sudo reboot
```

Si raspi-config a aussi mis la partition de démarrage en lecture seule, la remettre en écriture
dans le même menu (*Overlay File System* → partition de démarrage en écriture), puis redémarrer.
Vérifier ensuite qu'un changement de parcours survit à un redémarrage (02-UAT #9).
