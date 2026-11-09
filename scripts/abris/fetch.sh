#!/usr/bin/env bash
# Télécharge les entrées de la carte des abris (portable, avec internet) :
#   - relief Copernicus DEM GLO-30 (4 dalles, ~38 Mo, une seule fois)
#   - vent GFS 0,25° (NOAA NOMADS, découpé 42.8-44.4 N / 14.6-16.4 E) du dernier run dispo
# Usage : scripts/abris/fetch.sh [DEBUT_UTC] [FIN_UTC] [PAS_H]
#   défaut : 2026-11-13T12:00Z  2026-11-15T09:00Z  3
# Sortie : ${ABRIS_DIR:-var/abris}/dem/*.tif et .../gfs/gfs.<run>.fNNN.grb2
set -euo pipefail

DIR="${ABRIS_DIR:-var/abris}"
START="${1:-2026-11-13T12:00Z}"
END="${2:-2026-11-15T09:00Z}"
STEP="${3:-3}"
mkdir -p "$DIR/dem" "$DIR/gfs"

# --- relief (une fois) ---
for t in N42_00_E015 N42_00_E016 N43_00_E015 N43_00_E016; do
  n="Copernicus_DSM_COG_10_${t}_00_DEM"
  if [ ! -s "$DIR/dem/$n.tif" ]; then
    echo "relief $t ..."
    curl -sSf -o "$DIR/dem/$n.tif.part" "https://copernicus-dem-30m.s3.amazonaws.com/$n/$n.tif"
    mv "$DIR/dem/$n.tif.part" "$DIR/dem/$n.tif"
  fi
done

# --- dernier run GFS complet (le fichier f120 doit exister) ---
NOMADS="https://nomads.ncep.noaa.gov"
RUN=""
for back in 0 6 12 18 24 30; do
  cand=$(date -u -d "-${back} hour" +%Y%m%d%H)
  d=${cand:0:8}
  h=$(printf "%02d" $(((10#${cand:8:2} / 6) * 6)))
  idx="$NOMADS/pub/data/nccf/com/gfs/prod/gfs.$d/$h/atmos/gfs.t${h}z.pgrb2.0p25.f120.idx"
  if curl -sf -o /dev/null "$idx"; then RUN="$d$h"; break; fi
done
[ -n "$RUN" ] || { echo "aucun run GFS trouvé sur NOMADS" >&2; exit 2; }
RD=${RUN:0:8}
RH=${RUN:8:2}
echo "run GFS $RD ${RH}Z"

run_s=$(date -u -d "${RD:0:4}-${RD:4:2}-${RD:6:2}T${RH}:00Z" +%s)
t=$(date -u -d "$START" +%s)
end_s=$(date -u -d "$END" +%s)
rm -f "$DIR"/gfs/*.grb2
n=0
while [ "$t" -le "$end_s" ]; do
  f=$(((t - run_s) / 3600))
  if [ "$f" -ge 0 ] && [ "$f" -le 384 ]; then
    F=$(printf "%03d" "$f")
    url="$NOMADS/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.$RD%2F$RH%2Fatmos&file=gfs.t${RH}z.pgrb2.0p25.f$F"
    url+="&var_UGRD=on&var_VGRD=on&var_GUST=on&var_PRMSL=on"
    url+="&lev_10_m_above_ground=on&lev_surface=on&lev_mean_sea_level=on"
    url+="&subregion=&toplat=44.4&leftlon=14.6&rightlon=16.4&bottomlat=42.8"
    if curl -sSf -o "$DIR/gfs/gfs.$RUN.f$F.grb2" "$url"; then
      n=$((n + 1))
    else
      echo "échéance f$F absente (ignorée)" >&2
    fi
    sleep 1  # politesse NOMADS
  fi
  t=$((t + STEP * 3600))
done
echo "$n échéances GFS dans $DIR/gfs"
echo "Astuce : cat $DIR/gfs/*.grb2 > gfs.grb2 ; jabuka-prep grib gfs.grb2 --name wind_gfs"
