"""Carte des abris / accélérations probables (heuristique relief + direction GRIB).

Usage: python abris.py DEM_DIR GRIB_DIR MARKS_JSON OUT_DIR
Indice d'abri = Sx de Winstral : max sur la distance au vent de (h - z_obs) / d.
  Sx > 0.10  (à moins de 10 x la hauteur du relief) : abri fort
  0.05-0.10  (10-20 H)                              : abri moyen
  0.025-0.05 (20-40 H)                              : abri léger
Passe : mer peu abritée avec relief > 15 m des deux côtés à moins de 1.5 km (perpendiculaire au vent).
"""

import glob
import json
import math
import sys
from zoneinfo import ZoneInfo

import matplotlib
import numpy as np
import pygrib
import rasterio
from rasterio.merge import merge
from scipy.ndimage import map_coordinates

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, ListedColormap

dem_dir, grib_dir, marks_path, out_dir = sys.argv[1:5]
ARC = 3 / 3600  # ~90 m N-S, ~67 m E-W
OUTER = (15.20, 43.30, 16.30, 44.00)  # W S E N (marge au vent pour le calcul)
INNER = (15.40, 43.45, 16.05, 43.88)  # zone affichée
Z_OBS = 8.0  # hauteur du vent "vu" par les voiles (m)
DMAX = 8000.0  # distance max au vent (m)
STEP = 90.0
LOCAL = ZoneInfo("Europe/Zagreb")

src = [rasterio.open(f) for f in sorted(glob.glob(dem_dir + "/*.tif"))]
mos, tr = merge(src, bounds=OUTER)
full = np.nan_to_num(mos[0].astype(np.float32), nan=0.0)
H3, W3 = full.shape[0] // 3, full.shape[1] // 3
h = full[: H3 * 3, : W3 * 3].reshape(H3, 3, W3, 3).max(axis=(1, 3))  # max par bloc 3x3 (~90 m)
tr = tr * tr.scale(3, 3)
h[h < 0] = 0
ny, nx = h.shape
lon = tr.c + (np.arange(nx) + 0.5) * tr.a
lat = tr.f + (np.arange(ny) + 0.5) * tr.e
lat0 = 43.65
m_lon = ARC * 111320 * math.cos(math.radians(lat0))
m_lat = ARC * 110950
sea = h <= 1.0
rows, cols = np.mgrid[0:ny, 0:nx].astype(np.float32)


def sample(dx_m, dy_m):
    return map_coordinates(h, [rows - dy_m / m_lat, cols + dx_m / m_lon], order=1, cval=0.0)


def shelter(twd):
    """twd = direction d'où vient le vent (deg). Renvoie Sx."""
    ux, uy = math.sin(math.radians(twd)), math.cos(math.radians(twd))  # vers l'amont
    sx = np.zeros_like(h)
    for d in np.arange(STEP, DMAX + 1, STEP):
        sx = np.maximum(sx, (sample(ux * d, uy * d) - Z_OBS) / d)
    return sx


def gaps(twd, sx):
    px, py = math.cos(math.radians(twd)), -math.sin(math.radians(twd))  # perpendiculaire
    left = np.zeros_like(h, bool)
    right = np.zeros_like(h, bool)
    for d in np.arange(150, 1501, 150):
        left |= sample(px * d, py * d) > 15
        right |= sample(-px * d, -py * d) > 15
    return sea & left & right & (sx < 0.025)


# vent GFS au centre de la zone
winds = []
for f in sorted(glob.glob(grib_dir + "/*.grb2")):
    g = pygrib.open(f)
    rec = {m.shortName: m for m in g}
    la, lo = rec["10u"].latlons()
    i = np.unravel_index(np.argmin((la - 43.68) ** 2 + (lo - 15.75) ** 2), la.shape)
    u, v = float(rec["10u"].values[i]), float(rec["10v"].values[i])
    gust = float(rec["gust"].values[i]) * 1.94384 if "gust" in rec else None
    t = rec["10u"].validDate.replace(tzinfo=ZoneInfo("UTC")).astimezone(LOCAL)
    winds.append((t, math.degrees(math.atan2(-u, -v)) % 360, math.hypot(u, v) * 1.94384, gust))

marks = json.load(open(marks_path))["marks"]
cmap = ListedColormap(["#ffffff00", "#cfe3ff", "#7fb0f0", "#2f6fd0"])
ls = LightSource(azdeg=315, altdeg=40)
ext = (lon[0], lon[-1], lat[-1], lat[0])
summary = []
for t, twd, tws, gust in winds:
    sx = shelter(twd)
    cls = np.zeros_like(h, np.int8)
    cls[sx > 0.025] = 1
    cls[sx > 0.05] = 2
    cls[sx > 0.10] = 3
    cls[~sea] = 0
    gp = gaps(twd, sx)
    fig, ax = plt.subplots(figsize=(11, 8.5), dpi=110)
    ax.imshow(np.where(sea, 1, 0), extent=ext, cmap=ListedColormap(["#f4f1ea", "#ffffff"]))
    ax.imshow(cls, extent=ext, cmap=cmap, vmin=0, vmax=3, interpolation="nearest")
    gm = np.ma.masked_where(~gp, gp.astype(float))
    ax.imshow(gm, extent=ext, cmap=ListedColormap(["#e8590c"]), alpha=0.75, interpolation="nearest")
    land = np.ma.masked_where(sea, ls.hillshade(h, vert_exag=3, dx=m_lon, dy=m_lat))
    ax.imshow(land, extent=ext, cmap="Greys_r", vmin=0, vmax=1.2, alpha=0.9)
    ax.contour(lon, lat, h, levels=[1.0], colors="#555", linewidths=0.4)
    for m in marks:
        if INNER[0] <= m["lon"] <= INNER[2] and INNER[1] <= m["lat"] <= INNER[3]:
            ax.plot(m["lon"], m["lat"], "o", ms=7, mfc="#ffd400", mec="k")
            ax.annotate(
                m["name"],
                (m["lon"], m["lat"]),
                xytext=(6, 6),
                textcoords="offset points",
                fontsize=10,
                weight="bold",
            )
    # flèche de vent (vers où il souffle)
    cx, cy = INNER[0] + 0.06, INNER[3] - 0.05
    k = 0.035
    dxa = -math.sin(math.radians(twd)) * k / math.cos(math.radians(lat0))
    dya = -math.cos(math.radians(twd)) * k
    ax.annotate(
        "",
        xy=(cx + dxa, cy + dya),
        xytext=(cx - dxa, cy - dya),
        arrowprops=dict(arrowstyle="-|>", lw=3, color="k"),
    )
    bora = 0 <= twd <= 90 and tws >= 15
    title = f"{t:%a %d/%m %H:%M} (heure locale) — GFS : vent du {twd:03.0f}° {tws:.0f} kt"
    if gust:
        title += f", rafales {gust:.0f} kt"
    ax.set_title(title, fontsize=12, weight="bold")
    note = (
        "Bleu : abri probable (clair = léger, foncé = fort). Orange : passe, accélération possible.\n"
        "Heuristique relief seul (Copernicus DEM 30 m), sans thermique. GFS 0,25° : direction quasi uniforme."
    )
    if bora:
        note += (
            "\nATTENTION BORA (NE fort) : sous le vent des reliefs côtiers le vent tombe en RAFALES "
            "violentes ;\nles zones bleues près de la côte continentale ne sont PAS des abris fiables."
        )
    ax.text(
        0.01,
        0.01,
        note,
        transform=ax.transAxes,
        fontsize=8.5,
        va="bottom",
        bbox=dict(fc="white", ec="#999", alpha=0.9),
    )
    ax.set_xlim(INNER[0], INNER[2])
    ax.set_ylim(INNER[1], INNER[3])
    ax.set_aspect(1 / math.cos(math.radians(lat0)))
    ax.set_xlabel("lon E")
    ax.set_ylabel("lat N")
    name = f"{out_dir}/abris_{t:%d_%H%M}.png"
    fig.savefig(name, bbox_inches="tight")
    plt.close(fig)
    summary.append(f"{t:%a %d %H:%M} {twd:03.0f}° {tws:4.1f} kt -> {name}")
print("\n".join(summary))
