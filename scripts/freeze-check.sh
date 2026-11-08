#!/usr/bin/env bash
# Feature-freeze checker (2026-11-11, docs/FREEZE.md, plan 04-02).
#
#   bash scripts/freeze-check.sh [--repo DIR] [--pre] [--skip-gate]
#
#   F1  working tree clean (tracked files)
#   F2  the gate: JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh  (--skip-gate)
#   F3  laptop race-36h soak report (host.machine x86_64): verdict PASS, git.dirty false, and no
#       change under src/, deploy/ (except *.md) or pyproject.toml between git.head and HEAD.
#       A report with a `code` block (empreinte du paquet exécuté, docs/SOAK.md) must also have
#       code.sha256 = the fingerprint of src/jabuka at HEAD and, for the Pi (source "units"),
#       code.units = deploy/systemd at HEAD; then git.head may be null (Pi copy without .git)
#   F4  Pi race-36h soak report (aarch64; copy the Pi's var/soak/<run>/ back into var/soak/). It
#       must come from `sudo bash scripts/soak.sh --systemd system …` (mode systemd, code.source
#       units) and carry the code block: code.sha256 = the fingerprint of src/jabuka at HEAD and
#       code.units = deploy/systemd at HEAD; git.head may then be null (Pi copy without .git).
#       When git.head is present the F3 git rules apply on top; git alone never suffices for F4
#   F5  sha256 of deploy/requirements.lock = the "Lock revu : sha256 <hex>" line of docs/FREEZE.md
#   F6  deploy/wheelhouse: one wheel per lock pin, and the jabuka wheel's jabuka/ files are
#       byte-identical to the tracked src/jabuka/ files
#   F7  the race-2026 tag points at HEAD  (SKIP with --pre: before the tag is made)
#   F8  pending UAT items (result: [pending] in .planning/phases/*/*-UAT.md): WARN, never FAIL
#   F9  spare SD cloned and boot-checked (docs/SPARE-SD.md): HUMAN
#
# One line per item: [PASS|FAIL|WARN|SKIP|HUMAN] Fn <text>. Exit 0 when no item FAILs.
# Reads soak reports written by jabuka-soak (plan 04-01, report.json schema 1): only verdict,
# scenario, mode, host.machine, git.head, git.dirty, code.sha256, code.source and code.units.
set -euo pipefail

GIT="${GIT:-/usr/bin/git}"
PY="${PYTHON:-python3}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PRE=0
SKIP_GATE=0
TAG=race-2026

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="$(cd "$2" && pwd)"; shift 2 ;;
        --repo=*) REPO="$(cd "${1#--repo=}" && pwd)"; shift ;;
        --pre) PRE=1; shift ;;
        --skip-gate) SKIP_GATE=1; shift ;;
        -h | --help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "freeze-check: unknown argument: $1" >&2; exit 2 ;;
    esac
done

g() { "$GIT" -C "$REPO" "$@"; }
FAILS=0
say() { # STATUS ID TEXT
    echo "[$1] $2 $3"
    if [ "$1" = FAIL ]; then FAILS=$((FAILS + 1)); fi
}

HEAD_SHA="$(g rev-parse HEAD)"
echo "freeze-check: $REPO @ ${HEAD_SHA:0:12} ($(g rev-parse --abbrev-ref HEAD))"

# -- F1 clean tree -----------------------------------------------------------------------------
dirty="$(g status --porcelain --untracked-files=no)"
if [ -z "$dirty" ]; then
    say PASS F1 "arbre de travail propre (fichiers suivis)"
else
    say FAIL F1 "fichiers modifiés : $(echo "$dirty" | awk '{print $NF}' | head -5 | tr '\n' ' ')-> commit ou git checkout -- <fichier>"
fi

# -- F2 gate -----------------------------------------------------------------------------------
if [ "$SKIP_GATE" -eq 1 ]; then
    say SKIP F2 "porte non lancée (--skip-gate) : JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh"
else
    log="$(mktemp)"
    if (cd "$REPO" && JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh) >"$log" 2>&1; then
        say PASS F2 "porte verte : $(grep -E 'passed' "$log" | tail -2 | tr '\n' ' ')"
    else
        say FAIL F2 "porte en échec : $(tail -3 "$log" | tr '\n' ' ')"
    fi
    rm -f "$log"
fi

# -- F3 / F4 soak reports ----------------------------------------------------------------------
soak() { # ID MACHINE LABEL
    local id="$1" machine="$2" label="$3" found
    # stdlib only (python3 from PATH, jabuka not importable). Prints one record for the newest
    # race-36h report of MACHINE: path, verdict, head, dirty, code_state, detail (tab-separated,
    # never an empty field). code_state: absent | match | differ | units-differ | units-missing |
    # error, and for aarch64 only: no-code (no valid code.sha256) | not-units (mode is not
    # systemd or code.source is not units: not a `--systemd system` soak; overrides differ,
    # units-* and match). A helper crash becomes an error record (|| fallback), never an abort
    # under set -e.
    found="$("$PY" - "$REPO/var/soak" "$machine" "$REPO" "$GIT" <<'PY'
import hashlib, io, json, re, subprocess, sys, tarfile
from pathlib import Path
soak, machine, repo, git = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
UNITS = ("jabuka-core.service", "jabuka-ingest-fastnet.service")


def fingerprint(entries):
    # = jabuka.soak.report.fingerprint_entries (FINGERPRINT_SH), parity-tested in
    # tests/soak/test_soak_identity.py: compiled files skipped, "<sha256>  ./<rel>\n" lines in
    # C byte order of "./<rel>", sha256 of the manifest
    lines = []
    for rel, data in entries:
        parts = rel.split("/")
        if parts[-1].endswith(".pyc") or "__pycache__" in parts[:-1]:
            continue
        name = "./" + rel
        lines.append((name.encode(), hashlib.sha256(data).hexdigest() + "  " + name + "\n"))
    lines.sort(key=lambda x: x[0])
    return hashlib.sha256("".join(x for _, x in lines).encode()).hexdigest(), len(lines)


def head_fingerprint():
    out = subprocess.run([git, "-C", repo, "archive", "--format=tar", "HEAD", "src/jabuka"],
                         check=True, capture_output=True, timeout=120).stdout
    entries = []
    with tarfile.open(fileobj=io.BytesIO(out)) as tar:
        for m in tar.getmembers():
            if m.isfile() and m.name.startswith("src/jabuka/"):
                entries.append((m.name[len("src/jabuka/"):], tar.extractfile(m).read()))
    return fingerprint(entries)


def head_unit_sha(unit):
    r = subprocess.run([git, "-C", repo, "show", f"HEAD:deploy/systemd/{unit}"],
                       capture_output=True, timeout=60)
    return hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 else None


def code_state(code):
    sha = code.get("sha256") if isinstance(code, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        return "absent", "-"
    try:
        want, n = head_fingerprint()
    except Exception as exc:  # noqa: BLE001
        return "error", f"empreinte de src/jabuka à HEAD impossible : {exc!r}"
    if sha != want:
        return "differ", f"{sha[:12]} {want[:12]}"
    if code.get("source") == "units":
        units = code.get("units")
        for unit in UNITS:
            got = units.get(unit) if isinstance(units, dict) else None
            if not isinstance(got, str):
                return "units-missing", f"{unit} absente du rapport"
            try:
                ref = head_unit_sha(unit)
            except Exception as exc:  # noqa: BLE001
                return "error", f"deploy/systemd/{unit} à HEAD illisible : {exc!r}"
            if ref is None or got != ref:
                return "units-differ", unit
    return "match", f"empreinte {sha[:12]}, {code.get('files')} fichiers"


best = None
for p in soak.glob("*/report.json"):
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    if not isinstance(r, dict) or r.get("scenario") != "race-36h":
        continue
    if (r.get("host") or {}).get("machine") != machine:
        continue
    if best is None or p.parent.name > best[0]:
        best = (p.parent.name, p, r)
if best is not None:
    _, p, r = best
    g = r.get("git") or {}
    state, detail = code_state(r.get("code"))
    if machine == "aarch64":
        # F4 counts only the documented `--systemd system` Pi soak (plan 04-06, CR-01)
        code = r.get("code") if isinstance(r.get("code"), dict) else {}
        if state == "absent":
            state, detail = "no-code", "-"
        elif state != "error" and (r.get("mode") != "systemd" or code.get("source") != "units"):
            state, detail = "not-units", f"mode {r.get('mode')}, source {code.get('source')}"
    print(p, r.get("verdict"), g.get("head") or "-", "true" if g.get("dirty") is not False else "false", state, detail, sep="\t")
PY
)" || found="$(printf '%s\t%s\t%s\t%s\t%s\t%s' - PASS - true error "helper F3/F4 en échec ($PY)")"
    if [ -z "$found" ]; then
        say FAIL "$id" "pas de rapport race-36h $label ($machine) dans var/soak : bash scripts/soak.sh (docs/SOAK.md)"
        return
    fi
    local path verdict head dirty cstate detail
    IFS=$'\t' read -r path verdict head dirty cstate detail <<<"$found"
    path="${path#"$REPO"/}"
    if [ "$cstate" = error ]; then
        say FAIL "$id" "$label : $path : $detail"
    elif [ "$verdict" != PASS ]; then
        say FAIL "$id" "$label : $path verdict $verdict"
    elif [ "$cstate" = no-code ]; then
        say FAIL "$id" "$label : $path sans empreinte du code (pas de code.sha256) : refaire le soak du Pi avec le banc actuel : sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M (docs/SOAK.md)"
    elif [ "$cstate" = not-units ]; then
        say FAIL "$id" "$label : $path n'est pas un soak --systemd system ($detail) : F4 ne compte que le soak des unités installées : sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M (docs/SOAK.md)"
    elif [ "$cstate" = differ ]; then
        say FAIL "$id" "$label : $path code soaké (empreinte ${detail%% *}) différent de src/jabuka à HEAD (${detail##* }) : réinstaller depuis HEAD puis refaire le soak"
    elif [ "$cstate" = units-differ ] || [ "$cstate" = units-missing ]; then
        say FAIL "$id" "$label : $path unités installées différentes de deploy/systemd à HEAD ($detail) : sudo deploy/provision.sh puis refaire le soak"
    elif [ "$cstate" = match ] && [ "$head" = - ]; then
        say PASS "$id" "$label : $path PASS, paquet installé = src/jabuka à HEAD ($detail)"
    elif [ "$dirty" = true ]; then
        say FAIL "$id" "$label : $path fait sur un arbre dirty (git.dirty pas false) : refaire le soak sur un commit propre"
    elif [ "$head" = - ] || ! g cat-file -e "$head^{commit}" 2>/dev/null; then
        say FAIL "$id" "$label : $path git.head inconnu ($head)"
    elif ! g merge-base --is-ancestor "$head" HEAD; then
        say FAIL "$id" "$label : $path fait sur ${head:0:12}, qui n'est pas un ancêtre de HEAD"
    elif ! g diff --quiet "$head" HEAD -- src deploy pyproject.toml ':(exclude)deploy/*.md'; then
        say FAIL "$id" "$label : code modifié depuis le soak (${head:0:12} -> HEAD : $(g diff --name-only "$head" HEAD -- src deploy pyproject.toml ':(exclude)deploy/*.md' | head -3 | tr '\n' ' ')) : refaire bash scripts/soak.sh"
    else
        say PASS "$id" "$label : $path PASS sur ${head:0:12}, code identique à HEAD"
    fi
}
soak F3 x86_64 portable
soak F4 aarch64 Pi

# -- F5 lock review hash -----------------------------------------------------------------------
lock="$REPO/deploy/requirements.lock"
doc="$REPO/docs/FREEZE.md"
if [ ! -f "$lock" ]; then
    say FAIL F5 "deploy/requirements.lock absent"
else
    sha="$(sha256sum "$lock" | awk '{print $1}')"
    line="$(grep -E '^Lock revu : sha256 ' "$doc" 2>/dev/null | head -1 || true)"
    shown="${line#Lock revu : sha256 }"
    want="${shown%% *}"
    if [ -z "$line" ]; then
        say FAIL F5 "ligne « Lock revu : sha256 … » absente de docs/FREEZE.md (sha256 du verrou : $sha)"
    elif [ "$want" = "$sha" ]; then
        say PASS F5 "verrou revu : sha256 ${sha:0:16}… = docs/FREEZE.md"
    else
        say FAIL F5 "verrou non revu ou modifié : docs/FREEZE.md dit « $shown », sha256 du verrou $sha (revue 01-UAT #8 / 02-UAT #10, puis écrire ce hash)"
    fi
fi

# -- F6 wheelhouse from the frozen source -------------------------------------------------------
f6="$("$PY" - "$REPO" "$GIT" <<'PY'
import re, subprocess, sys, zipfile
from pathlib import Path
repo = Path(sys.argv[1])
lock, wh = repo / "deploy" / "requirements.lock", repo / "deploy" / "wheelhouse"
norm = lambda s: re.sub(r"[-_.]+", "_", s).lower()  # noqa: E731
if not wh.is_dir():
    print("FAIL\tdeploy/wheelhouse absent : bash scripts/build-wheelhouse.sh")
    sys.exit()
pins = {}
for line in lock.read_text(encoding="utf-8").splitlines():
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)", line)
    if m:
        pins[norm(m.group(1))] = m.group(2)
by = {}
for w in sorted(wh.glob("*.whl")):
    name, version = w.name.split("-")[:2]
    by.setdefault(norm(name), []).append((version, w))
bad = [f"{n}=={v} (trouvé {[x for x, _ in by.get(n, [])]})" for n, v in sorted(pins.items())
       if [x for x, _ in by.get(n, [])] != [v]]
jab = by.get("jabuka", [])
if len(jab) != 1:
    bad.append(f"{len(jab)} roue(s) jabuka au lieu d'une")
else:
    git = sys.argv[2] if len(sys.argv) > 2 else "/usr/bin/git"
    tracked = subprocess.run([git, "-C", str(repo), "ls-files", "-z", "src/jabuka"],
                             check=True, capture_output=True).stdout.decode().split("\0")
    src = {p[len("src/"):]: (repo / p) for p in tracked if p}
    with zipfile.ZipFile(jab[0][1]) as z:
        inwheel = {n: n for n in z.namelist() if n.startswith("jabuka/") and not n.endswith("/")}
        diff = sorted(n for n in inwheel if n not in src or z.read(n) != src[n].read_bytes())
    missing = sorted(n for n in src if n not in inwheel)
    if diff:
        bad.append(f"roue jabuka différente de src/ : {diff[:4]}")
    if missing:
        bad.append(f"absents de la roue jabuka : {missing[:4]}")
if bad:
    print("FAIL\t" + " ; ".join(bad[:4]) + " -> bash scripts/build-wheelhouse.sh depuis le tag")
else:
    print(f"PASS\t{len(pins)} paquets, une roue chacun ; roue jabuka = src/jabuka ({len(src)} fichiers)")
PY
)"
say "${f6%%$'\t'*}" F6 "${f6#*$'\t'}"

# -- F7 tag ------------------------------------------------------------------------------------
if [ "$PRE" -eq 1 ]; then
    say SKIP F7 "tag $TAG pas encore attendu (--pre)"
elif tag_sha="$(g rev-parse -q --verify "refs/tags/$TAG^{commit}" 2>/dev/null)" && [ "$tag_sha" = "$HEAD_SHA" ]; then
    say PASS F7 "tag $TAG sur HEAD (${HEAD_SHA:0:12})"
elif [ -n "${tag_sha:-}" ]; then
    say FAIL F7 "tag $TAG sur ${tag_sha:0:12}, pas sur HEAD ${HEAD_SHA:0:12} : correctif d'urgence ? voir docs/FREEZE.md (race-2026.1)"
else
    say FAIL F7 "pas de tag $TAG : git tag -a $TAG -m \"Regata Jabuka 2026 : version gelée\""
fi

# -- F8 pending UAT items ----------------------------------------------------------------------
pending=0
shopt -s nullglob
for f in "$REPO"/.planning/phases/*/*-UAT.md; do
    n="$(grep -c 'result: \[pending\]' "$f" || true)"
    pending=$((pending + n))
done
if [ "$pending" -gt 0 ]; then
    say WARN F8 "$pending éléments UAT en attente (result: [pending]) : à traiter à bord, docs/COMMISSIONING.md annexe B"
else
    say PASS F8 "aucun élément UAT en attente"
fi

# -- F9 spare SD -------------------------------------------------------------------------------
say HUMAN F9 "carte SD de secours clonée depuis la version gelée et démarrée : docs/SPARE-SD.md"

if [ "$FAILS" -gt 0 ]; then
    echo "freeze-check: $FAILS item(s) FAIL"
    exit 1
fi
echo "freeze-check: ok"
