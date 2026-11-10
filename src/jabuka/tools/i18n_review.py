"""Slovenian proofreading sheet of the tablet UI (quick 001): docs/I18N-SL-REVIEW.md, one row per
key of web/static/i18n.js with the French source, the English reference and the proposed
Slovenian text.

    python -m jabuka.tools.i18n_review            # rewrite docs/I18N-SL-REVIEW.md
    python -m jabuka.tools.i18n_review --check    # exit 1 when the file is out of date

The dictionaries live in JavaScript, so they are read through node (dev laptop only).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jabuka
from jabuka.common.atomicio import atomic_write_bytes

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
I18N = STATIC / "i18n.js"
REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "I18N-SL-REVIEW.md"

SECTIONS = [
    ("app.", "Shell: tabs, night mode, top-bar badges"),
    ("tab.", "Shell: tabs, night mode, top-bar badges"),
    ("aria.", "Shell: tabs, night mode, top-bar badges"),
    ("theme.", "Shell: tabs, night mode, top-bar badges"),
    ("badge.", "Shell: tabs, night mode, top-bar badges"),
    ("wake.", "Shell: tabs, night mode, top-bar badges"),
    ("common.", "Shell: tabs, night mode, top-bar badges"),
    ("unit.", "Shell: tabs, night mode, top-bar badges"),
    ("helm.", "Helm (Barre): big numbers, hints, countdown"),
    ("flag.", "Helm (Barre): big numbers, hints, countdown"),
    ("tack.", "Helm (Barre): big numbers, hints, countdown"),
    ("route.", "Route band and ON RESTE"),
    ("side.", "Course (Carte)"),
    ("carte.", "Course (Carte)"),
    ("banner.", "Course (Carte)"),
    ("lang.", "Settings (Réglages)"),
    ("manual.", "Settings (Réglages)"),
    ("src.", "Settings (Réglages)"),
    ("reglages.", "Settings (Réglages)"),
    ("opt.", "Settings (Réglages)"),
    ("settings.", "Settings (Réglages)"),
    ("lock.", "Lock"),
    ("diag.", "Diagnostics page"),
    ("start.", "Start mode (Départ)"),
    ("srv.", "Alerts and reasons from the core (translated on the tablet)"),
]

HEADER = """# Slovenian UI texts: proofreading sheet

Generated from `src/jabuka/web/static/i18n.js` by `python -m jabuka.tools.i18n_review`. Do not
edit by hand: correct the `sl` column in i18n.js, then regenerate.

**Status: proposed translation, NOT yet proofread by a native speaker.** Please check every
`sl` cell, in particular the sailing terms. Short texts matter: the helm labels and the
countdown must fit on the tablet in big letters.

How to propose corrections: mark the row (key) and write the better Slovenian text next to it,
on paper, in a message or straight in this file. The owner will copy them into i18n.js.

Terms chosen (to confirm first):

| English | French | Proposed Slovenian |
|---|---|---|
| tack (manoeuvre) | virement | obrat ("Obrat čez 08:30", "OBRNI") |
| gybe | empannage | križ ("Križ čez 04:30", "KRIŽAJ") |
| layline | layline | layline |
| mark | marque | boja |
| course (sequence of marks) | parcours | proga |
| route (computed) | route | pot |
| heading / course to steer | cap / cap à suivre | smer / smer krmarjenja |
| true wind | vent réel | pravi veter |
| port / starboard | bâbord / tribord | levo / desno |
| head up / bear away | lofer / abattre | orcaj / odpadi |
| hold the tack | on reste | ostanemo |
| knots | nœuds (nds) | kn |

`{name}` placeholders are filled in by the program: keep them unchanged.
"""


def load_dict(node: str | None = None) -> dict[str, dict[str, str]]:
    """{"fr": {...}, "en": {...}, "sl": {...}} from i18n.js (through node)."""
    node = node or shutil.which("node")
    if node is None:
        raise RuntimeError("node is needed to read web/static/i18n.js")
    code = (
        f"import {{ DICT }} from {json.dumps(I18N.as_uri())};\n"
        "process.stdout.write(JSON.stringify(DICT));\n"
    )
    proc = subprocess.run(
        [node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "node failed")
    return json.loads(proc.stdout)


def _cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render(d: dict[str, dict[str, str]]) -> str:
    fr, en, sl = d["fr"], d["en"], d["sl"]
    groups: dict[str, list[str]] = {}
    for key in fr:
        title = next((t for p, t in SECTIONS if key.startswith(p)), "Other")
        groups.setdefault(title, []).append(key)
    out = [HEADER]
    for title in dict.fromkeys(t for _, t in SECTIONS):
        keys = groups.get(title)
        if not keys:
            continue
        out.append(f"\n## {title}\n")
        out.append("| key | fr | en (reference) | sl (to proofread) |")
        out.append("|---|---|---|---|")
        for k in keys:
            out.append(
                f"| `{k}` | {_cell(fr[k])} | {_cell(en.get(k, ''))} | {_cell(sl.get(k, ''))} |"
            )
    if "Other" in groups:
        out.append("\n## Other\n")
        out.append("| key | fr | en (reference) | sl (to proofread) |")
        out.append("|---|---|---|---|")
        for k in groups["Other"]:
            out.append(
                f"| `{k}` | {_cell(fr[k])} | {_cell(en.get(k, ''))} | {_cell(sl.get(k, ''))} |"
            )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jabuka-i18n-review", description=__doc__.split("\n")[0])
    p.add_argument("--check", action="store_true", help="exit 1 if the sheet is out of date")
    p.add_argument("--out", type=Path, default=DOC)
    args = p.parse_args(argv)
    text = render(load_dict())
    if args.check:
        ok = args.out.is_file() and args.out.read_text(encoding="utf-8") == text
        print(f"{args.out}: {'à jour' if ok else 'PAS À JOUR (relancer sans --check)'}")
        return 0 if ok else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(args.out, text.encode("utf-8"))
    print(f"écrit : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
