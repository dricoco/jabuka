# Carte des abris (outil portable, hors appli de bord)

Aide à la décision avant le départ : où le relief des îles crée probablement des **abris**
(dévente) ou des **passes** (accélération) pour la direction de vent annoncée par le GRIB.
Ce n'est **pas** utilisé par le routeur ni par le Pi : ce sont des images PNG à regarder ou
imprimer, à croiser avec Windguru (ICON-WG 500 m) et le vent réel.

## Utilisation (portable, avec internet)

```bash
# 1. relief (une fois, ~38 Mo) + dernier run GFS sur la fenêtre (défaut 13/11 12Z -> 15/11 09Z, pas 3 h)
bash scripts/abris/fetch.sh
#    autre fenêtre : bash scripts/abris/fetch.sh 2026-11-13T15:00Z 2026-11-14T12:00Z 1

# 2. cartes (une PNG par échéance, heure locale dans le titre et le nom)
mkdir -p var/abris/out
uv run --python 3.13 --with numpy --with scipy --with rasterio --with matplotlib --with pygrib \
  python scripts/abris/abris.py var/abris/dem var/abris/gfs src/jabuka/nav/data/marks.json var/abris/out
```

`abris.py` accepte n'importe quel dossier de GRIB à raison d'**une échéance par fichier**
avec `10u`/`10v` (et `gust` en option) ; le vent est lu au point 43.68 N 15.75 E (archipel).
Tout est écrit sous `var/abris/` (ignoré par git).

Le même GFS peut servir de second avis au routeur :
`cat var/abris/gfs/*.grb2 > var/abris/gfs.grb2 && jabuka-prep grib var/abris/gfs.grb2 --out var/racepack --name wind_gfs`
(voir docs/WEATHER-PACK.md pour choisir lequel devient `wind.npz`).

## Méthode

- Relief : Copernicus DEM GLO-30 (30 m), max par bloc 3x3 (~90 m).
- Indice d'abri (Sx de Winstral) : pour chaque point de mer, max de `(h - 8 m) / d` sur 8 km au vent.
  Fort > 0,10 (moins de 10 fois la hauteur), moyen 0,05-0,10, léger 0,025-0,05.
- Passe (orange) : mer peu abritée (Sx < 0,025) avec du relief > 15 m des deux côtés à moins de
  1,5 km, perpendiculairement au vent.

## Limites (à lire avant de s'en servir)

- **Bora (NE fort)** : sous le vent des reliefs côtiers le vent tombe en **rafales violentes** ;
  les zones bleues près du continent ne sont pas des abris (avertissement imprimé sur la carte).
- Aucun effet thermique (brise de terre, nuit), aucune canalisation fine : relief seul.
- GFS 0,25° (~25 km) : direction quasi uniforme sur la zone.
- L'orange est bruité le long des côtes parallèles au vent.
- Non validé contre du vent mesuré : à comparer après la régate avec les logs du bord.
