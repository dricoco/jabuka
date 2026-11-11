"""Demo wind for the jabuka-touch DÉMO: wind.npz + wind.json into the demo race pack.

Run ONLY by the Jabuka venv python, as user jabuka, never imported by the menu:

    runuser -u jabuka -- /opt/jabuka/venv/bin/python -I demo_wind.py \\
        DEST ROOT START END TWD TWS SHIFT

(DEST inside ROOT; START/END UTC epoch seconds; TWD deg, TWS kn, SHIFT deg/h). This is the only
file of the package allowed to import jabuka (jabuka.soak.pack.write_wind: numpy + wxpack only).
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 8:
        print("usage : demo_wind.py DEST ROOT START END TWD TWS SHIFT", file=sys.stderr)
        return 2
    try:
        dest, root = Path(argv[1]), Path(argv[2])
        start, end, twd, tws, shift = (float(v) for v in argv[3:8])
        from jabuka.soak.pack import write_wind

        path = write_wind(dest, root, start, end, twd=twd, tws_kn=tws, shift_deg_h=shift)
    except Exception as e:  # noqa: BLE001 - reported to the menu through the exit code
        print(f"demo_wind : {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
