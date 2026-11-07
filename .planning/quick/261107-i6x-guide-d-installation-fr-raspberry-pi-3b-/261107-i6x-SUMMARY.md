---
phase: quick-261107-i6x
plan: 01
subsystem: docs
tags: [docs, install, raspberry-pi, french]
status: complete
requires: []
provides: [docs/INSTALL-PI.md]
affects: [README.md]
tech-stack:
  added: []
  patterns: [synthesis doc linking to runbooks]
key-files:
  created: [docs/INSTALL-PI.md]
  modified: [README.md]
decisions:
  - "Méthode A de la SD de secours résumée sans recopier les commandes dd : elles restent dans SPARE-SD.md (risque d'effacer le disque du portable, procédure lsblk à suivre telle quelle)"
  - "Commandes jabuka-prep écrites avec .venv/bin/ comme dans COMMISSIONING.md (WEATHER-PACK.md les écrit sans préfixe)"
  - "Copie du pack : la procédure RACE-PACK.md (/tmp/racepack puis /var/lib/jabuka/racepack, chown, restart) plutôt que la forme $PI:$PACK_DIR de WEATHER-PACK.md"
metrics:
  completed: 2026-11-07
plan_head_before: b04dae839a02d7dc6ba9687de9ca246ba1ef2c83
actuals:
  tokens: 5300
  tasks: 2
  commits: 2
---

# Quick 261107-i6x: guide d'installation FR du Pi 3B — Summary

docs/INSTALL-PI.md : guide unique en français, de la carte SD vierge à la tablette en course
(12 sections), chaque commande reprise des runbooks et des scripts du dépôt, avec renvois vers
deploy/PI-SETUP.md pour les vérifications complètes, le Plan B et le dépannage. README.md pointe
vers lui.

## Tasks

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Écrire docs/INSTALL-PI.md | 24c87d0 | docs/INSTALL-PI.md |
| 2 | Lien depuis README.md | b789b88 | README.md |

## Sections écrites

1 Introduction (résultat, où trouver le détail) · 2 Matériel · 3 Sur le portable (bootstrap-dev,
wheelhouse, secrets.env, dry run) · 4 Flasher la carte SD (Imager, dd, cloud-init) · 5 Premier
démarrage en Ethernet (ssh, lsusb, règle udev) · 6 Installation (rsync, provision.sh, reboot) ·
7 Vérifications essentielles (PI-SETUP §4 a, b, e, k, g + lien vers la liste complète) · 8 Pack de
course (8.1 carte, 8.2 météo + terre + geofields + check, 8.3 polaire, 8.4 copie, 8.5 contrôles
Diag, 8.6 parcours) · 9 Tablette · 10 SD de secours · 11 Avant la course (FREEZE, COMMISSIONING,
SOAK) · 12 En cas de problème (PI-SETUP §6 et §5).

## Divergences entre sources (aucune contradiction avec les scripts)

- WEATHER-PACK.md écrit `jabuka-prep ...` sans préfixe, COMMISSIONING.md écrit
  `.venv/bin/jabuka-prep ...` : le guide utilise `.venv/bin/` (console script déclaré dans
  pyproject.toml).
- `geofields` : ROUTING.md donne `.venv/bin/python -m jabuka.prep.cli geofields ...` (repris tel
  quel ; la sous-commande existe dans src/jabuka/prep/cli.py). WEATHER-PACK.md le cite sans
  commande.
- Copie du pack : WEATHER-PACK.md utilise `rsync -av --delete var/racepack/ "$PI:$PACK_DIR/"`,
  RACE-PACK.md la procédure explicite via /tmp/racepack ; le guide suit RACE-PACK.md comme demandé
  par le plan.

## Lacunes (écrites comme renvoi seulement)

- Méthode A de la SD de secours : résumée en prose ; les commandes `dd`/`cmp` exactes sont
  laissées dans SPARE-SD.md (les recopier aurait aussi introduit le nom d'image
  `jabuka-race-2026.img`, absent des scripts/src, que le contrôle mécanique refuse).
- Saisie du parcours : aucun document ne décrit l'interface au-delà de COMMISSIONING.md §7 ; le
  guide reprend uniquement ces lignes et renvoie à §7.

## Deviations from Plan

- [Rule 3 - Blocking] Les commandes de vérification du plan font `cd /home/drico/git/jabuka`
  (checkout principal) ; exécutées ici dans le worktree. `deploy/wheelhouse` est gitignoré et
  absent d'un worktree neuf : ajouté à l'exception déjà prévue pour `deploy/secrets.env` dans le
  contrôle des chemins (le chemin existe dans le checkout principal).
- Task 2 verify attend README.md et docs/INSTALL-PI.md modifiés dans l'arbre de travail ; Task 1
  étant déjà commitée, le contrôle équivalent a été fait sur `git diff --stat b04dae8 HEAD` :
  seuls README.md (+3) et docs/INSTALL-PI.md (+476) changent ; docs/SOAK.md intact.

## Verification

- Task 1 : `GUIDE-OK` (25 liens relatifs, tous résolus ; chemins scripts/deploy, noms jabuka-* et
  options --flag tous trouvés dans le dépôt ; fr=493, en=4).
- Task 2 : un lien `](docs/INSTALL-PI.md)` dans README.md ; `git status -- docs/SOAK.md` vide ;
  diff vs base limité aux deux fichiers.

## Self-Check: PASSED

- docs/INSTALL-PI.md : FOUND
- README.md lien : FOUND
- 24c87d0, b789b88 : FOUND
