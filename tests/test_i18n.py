"""Tablet UI languages (quick 001, web/static/i18n.js), run through node:

- every key exists in fr, en and sl, with the same {placeholders}, and every Settings field has a
  label (fr = the server's schema label);
- no French literal is left in the static JS outside i18n.js (heuristic scan, allowlist below);
- every alert / reason text the core emits (collected from the Python sources) is translated in en
  and sl, and left exactly as sent in fr;
- helm and route values in en and sl (decimal point / comma, countdown words);
- docs/I18N-SL-REVIEW.md is in sync with the dictionaries."""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka
from jabuka.tools import i18n_review

SRC = Path(jabuka.__file__).resolve().parent
STATIC = SRC / "web" / "static"
I18N = STATIC / "i18n.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def node(body: str, *modules: str) -> object:
    """Run body (an ES module snippet with the named static modules imported as M0, M1, ... and
    i18n.js as I) and return what it writes as JSON."""
    imports = [f"import * as I from {json.dumps(I18N.as_uri())};"]
    for i, name in enumerate(modules):
        imports.append(f"import * as M{i} from {json.dumps((STATIC / name).as_uri())};")
    code = "\n".join(imports) + "\n" + body + "\n"
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def out(expr: str) -> str:
    return f"process.stdout.write(JSON.stringify({expr}));"


# -- dictionaries ---------------------------------------------------------------------------------
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_every_key_in_every_language_with_the_same_placeholders() -> None:
    d = node(out("I.DICT"))
    assert node(out("[I.LANGS, I.DEFAULT_LANG, I.getLang()]")) == [["fr", "en", "sl"], "fr", "fr"]
    fr = d["fr"]
    assert len(fr) > 250
    for lang in ("en", "sl"):
        assert set(d[lang]) == set(fr), (
            lang,
            sorted(set(fr) ^ set(d[lang])),
        )
        for key, text in d[lang].items():
            assert isinstance(text, str) and text.strip(), (lang, key)
            assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(fr[key])), (lang, key)


def test_settings_labels_cover_every_field_and_match_the_schema() -> None:
    from jabuka.nav.settings import Settings

    fr = node(out("I.DICT.fr"))
    schema = Settings.model_json_schema()["properties"]
    for field, prop in schema.items():
        assert fr.get(f"settings.{field}") == prop["label"], field


def test_t_falls_back_and_fills_placeholders() -> None:
    res = node(
        "const a = I.t('helm.tackIn', {t: '08:30'});\n"
        "I.setLang('sl', {persist: false});\n"
        "const b = I.t('helm.tackIn', {t: '08:30'});\n"
        "const c = I.t('no.such.key');\n"
        "I.setLang('xx', {persist: false});\n" + out("[a, b, c, I.getLang(), I.fmtDec(0.35, 2)]")
    )
    assert res == ["Virement dans 08:30", "Obrat čez 08:30", "no.such.key", "fr", "0,35"]


# -- no French left in the static JS --------------------------------------------------------------
# literal -> why it may stay (internal ids and values compared with what the core sends)
ALLOWED = {
    "vidéo": "wakelock.js state id (shown through t('wake.video'))",
    "MANUEL": "core wind source id (nav.wind.source)",
    "Noto Sans Medium": "map font name",
}
ACCENTED = re.compile(r"[àâäçéèêëîïôöùûüÿœæÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒÆ]")
FRENCH_WORDS = re.compile(
    r"\b(dans|pour|avec|sans|une|les|des|du|pas|est|sur|aucun|aucune|marque|parcours|annuler|"
    r"fermer|supprimer|ajouter|valeur|impossible|indisponible|nuit|jour|virement|empannage|bord|"
    r"cible|vent|routage|garder|renommer|monter|descendre|centrer|appliquer|effacer|nds)\b",
    re.IGNORECASE,
)
FRENCH_SINGLE = {
    "Fermer",
    "Annuler",
    "Garder",
    "Centrer",
    "Ajouter",
    "Renommer",
    "Monter",
    "Descendre",
    "Supprimer",
    "Nom",
    "Rayon",
    "Appliquer",
    "Effacer",
    "Jour",
    "Nuit",
    "Barre",
    "Carte",
    "LOFER",
    "ABATTRE",
    "COURANT",
    "VIREZ",
    "EMPANNEZ",
    "Aucun",
    "Polaire",
    "Temps",
}


def js_strings(src: str) -> list[tuple[int, str]]:
    """(line, text) of every string and template literal (template expressions scanned too),
    comments skipped. Regex literals are read as code (none of ours holds a quote)."""
    found: list[tuple[int, str]] = []
    n = len(src)

    def line_at(pos: int) -> int:
        return src.count("\n", 0, pos) + 1

    def scan_code(i: int, stop_on_brace: bool) -> int:
        depth = 0
        while i < n:
            c = src[i]
            if src.startswith("//", i):
                j = src.find("\n", i)
                i = n if j < 0 else j
            elif src.startswith("/*", i):
                j = src.find("*/", i + 2)
                i = n if j < 0 else j + 2
            elif c in "'\"":
                j = i + 1
                while j < n and src[j] != c:
                    j += 2 if src[j] == "\\" else 1
                found.append((line_at(i), src[i + 1 : j]))
                i = j + 1
            elif c == "`":
                i = scan_template(i + 1)
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if stop_on_brace and depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        return i

    def scan_template(i: int) -> int:
        start, parts = i, []
        while i < n and src[i] != "`":
            if src[i] == "\\":
                parts.append(src[i : i + 2])
                i += 2
            elif src.startswith("${", i):
                parts.append(" ")
                i = scan_code(i + 2, True)
            else:
                parts.append(src[i])
                i += 1
        found.append((line_at(start), "".join(parts)))
        return i + 1

    scan_code(0, False)
    return found


def looks_french(text: str) -> bool:
    if text in ALLOWED:
        return False
    if ACCENTED.search(text):
        return True
    if text.strip() in FRENCH_SINGLE:
        return True
    return " " in text.strip() and bool(FRENCH_WORDS.search(text))


def test_the_scanner_finds_french() -> None:
    sample = 'const a = "Virement dans"; // "Annuler"\nconst b = `x ${y ? `Fermer` : "ok"} z`;'
    texts = [t for _, t in js_strings(sample)]
    assert "Virement dans" in texts and "Fermer" in texts and "Annuler" not in texts
    assert [t for t in texts if looks_french(t)] == ["Virement dans", "Fermer"]


def test_no_french_literal_in_the_static_js_outside_i18n() -> None:
    bad = []
    for path in sorted(STATIC.glob("*.js")):
        if path.name == "i18n.js":
            continue
        for line, text in js_strings(path.read_text(encoding="utf-8")):
            if looks_french(text):
                bad.append(f"{path.name}:{line}: {text!r}")
    assert bad == [], "\n".join(bad)


# -- the core's texts -----------------------------------------------------------------------------
CORE_FILES = [
    "core/nav_service.py",
    "core/router_service.py",
    "nav/course.py",
    "nav/settings.py",
    "nav/wind.py",
    "route/cycle.py",
    "route/isochrone.py",
    "route/racepack.py",
]
CALLS = {"RouteFailure", "_pool_alarm", "_recycle_pool", "_invalid", "_failed", "failed_block"}
NAME_RE = re.compile(
    r"(^ALERT|^REASON_|WRITE_ALERT|^PACK_CHANGED|_ERROR$|reason|alerts|fail)", re.IGNORECASE
)
SAMPLE = "7"


def _consts(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node_ in tree.body:
        if isinstance(node_, ast.Assign) and isinstance(node_.value, ast.Constant):
            for tgt in node_.targets:
                if isinstance(tgt, ast.Name) and isinstance(node_.value.value, str):
                    out[tgt.id] = node_.value.value
    return out


def _render(node_: ast.AST, consts: dict[str, str]) -> str | None:
    if isinstance(node_, ast.Constant) and isinstance(node_.value, str):
        return node_.value
    if isinstance(node_, ast.JoinedStr):
        parts = []
        for v in node_.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                parts.append(consts.get(v.value.id, SAMPLE))
            else:
                parts.append(SAMPLE)
        return "".join(parts)
    return None


def _strings(node_: ast.AST, consts: dict[str, str]) -> list[str]:
    """Strings of an expression: itself, or the members of a BoolOp / tuple / list."""
    s = _render(node_, consts)
    if s is not None:
        return [s]
    out: list[str] = []
    if isinstance(node_, ast.BoolOp):
        for v in node_.values:
            out += _strings(v, consts)
    elif isinstance(node_, ast.Tuple | ast.List):
        for v in node_.elts:
            out += _strings(v, consts)
    elif isinstance(node_, ast.Call):  # "; ".join(...) or "x"
        for a in node_.args:
            out += _strings(a, consts)
    return out


def _target_names(tgt: ast.AST) -> list[str]:
    if isinstance(tgt, ast.Name):
        return [tgt.id]
    if isinstance(tgt, ast.Attribute):
        return [tgt.attr]
    if isinstance(tgt, ast.Tuple):
        return [n for e in tgt.elts for n in _target_names(e)]
    return []


def core_texts() -> set[str]:
    """Every alert / reason / banner text the core can send, rendered with sample values."""
    found: set[str] = set()
    for rel in CORE_FILES:
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        consts = _consts(tree)
        for node_ in ast.walk(tree):
            if isinstance(node_, ast.Call):
                f = node_.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                recv = f.value if isinstance(f, ast.Attribute) else None
                recv_name = ""
                if isinstance(recv, ast.Attribute):
                    recv_name = recv.attr
                elif isinstance(recv, ast.Name):
                    recv_name = recv.id
                elif isinstance(recv, ast.Subscript) and isinstance(recv.slice, ast.Constant):
                    recv_name = str(recv.slice.value)
                if (name == "append" and NAME_RE.search(recv_name)) or name in CALLS:
                    for a in node_.args:
                        found.update(_strings(a, consts))
                if name == "Banner":
                    for kw in node_.keywords:
                        if kw.arg == "text":
                            found.update(_strings(kw.value, consts))
            elif isinstance(node_, ast.Assign):
                names = [n for t in node_.targets for n in _target_names(t)]
                if any(NAME_RE.search(n) for n in names):
                    found.update(_strings(node_.value, consts))
            elif isinstance(node_, ast.FunctionDef) and "withdraw" in node_.name:
                for sub in ast.walk(node_):
                    if isinstance(sub, ast.Return) and sub.value is not None:
                        found.update(_strings(sub.value, consts))
    # UI text only: at least one real word and a space (ids like "failed" are not shown)
    texts = {s for s in found if " " in s.strip() and re.search(r"[A-Za-zÀ-ÿ]{3}", s)}
    # prefixes are always followed by a reason
    return {s + "route invalide (terre)" if s.endswith(": ") else s for s in texts}


# composites built by concatenation in the core (racepack ALERT_PREFIX + problem, the banner
# without its " — Annuler", reasons joined by "; ")
COMPOSITES = [
    "MÉTÉO INCOMPLÈTE : vent à partir du 14/11 19:00 seulement, début requis 13/11 19:00",
    "MÉTÉO INCOMPLÈTE : vent jusqu'au 14/11 19:00 seulement, fin requise 15/11 11:00",
    "MÉTÉO INCOMPLÈTE : vent hors de la zone couverte à Jabuka (43.0915N 15.4605E)",
    "MÉTÉO INCOMPLÈTE : vent valeurs manquantes (NaN) sur le bord Vodice → Plić Sestre "
    "(43.700N 15.800E)",
    "ROUTE INVALIDE : route invalide (terre)",
    "ROUTEUR RELANCÉ : calcul bloqué depuis plus de 120 s",
    "Marque suivante : Plić Sestre",
    "ARRIVÉE — Vodice",
    "virement manqué : nouvelle route impossible (échec du routage)",
    "vent absent; landmask.npz absent du pack /data/racepack",
    # quick-261110-klg: the course-change withdrawal names the real failure, and the rounding
    # ValueError (rounding.py, not a CORE_FILE) reaches the tablet through RouteFailure
    "parcours modifié : cible dans la terre, aucune eau libre à 1 nm : Blitvenica",
    "impossible de contourner Blitvenica : aucun point en eau libre à moins de 1.05 nm au "
    "relèvement 189°",
]


def test_the_collector_sees_the_core_alerts() -> None:
    texts = core_texts()
    for expected in (
        "PAS DE VENT",
        "Erreur de calcul nav",
        "VENT GRIB (pas d'instruments)",
        "Route sauvegardée illisible : ignorée",
        "PACK DE COURSE MODIFIÉ : redémarrer jabuka-core",
        "ROUTE INVALIDE : route invalide (terre)",
        "Vent manuel ancien (> 7 min)",
        "Écriture du parcours impossible",
        "Marque suivante : 7 — Annuler",
    ):
        assert expected in texts, expected
    assert len(texts) >= 40, sorted(texts)


def test_every_core_text_is_translated_in_en_and_sl_and_untouched_in_fr() -> None:
    texts = sorted(core_texts() | set(COMPOSITES))
    # carte.js bannerView drops the trailing " — Annuler" before translating
    texts = [re.sub(r"\s*—\s*Annuler\s*$", "", s) for s in texts]
    res = node(
        f"const texts = {json.dumps(texts)};\n"
        "const r = {};\n"
        "for (const lang of I.LANGS) { I.setLang(lang, {persist: false}); "
        "r[lang] = texts.map((s) => I.trServer(s)); }\n" + out("r")
    )
    assert res["fr"] == texts
    for lang in ("en", "sl"):
        missing = [s for s, tr in zip(texts, res[lang], strict=True) if tr == s]
        assert missing == [], f"{lang}: untranslated core texts:\n" + "\n".join(missing)
        assert not [tr for tr in res[lang] if PLACEHOLDER.search(tr)], lang
    assert res["en"][texts.index("ROUTE INVALIDE : route invalide (terre)")] == (
        "INVALID ROUTE: route invalid (land)"
    )
    assert res["sl"][texts.index("Marque suivante : Plić Sestre")] == "Naslednja boja: Plić Sestre"
    changed = texts.index(
        "parcours modifié : cible dans la terre, aucune eau libre à 1 nm : Blitvenica"
    )
    assert res["en"][changed] == (
        "course changed: target on land, no open water within 1 nm: Blitvenica"
    )
    assert res["sl"][changed] == (
        "proga spremenjena: cilj na kopnem, ni proste vode v 1 nm: Blitvenica"
    )
    unknown = node(
        "I.setLang('en', {persist: false});\n" + out("I.trServer('message inconnu du cœur')")
    )
    assert unknown == "message inconnu du cœur"


# -- formatting in each language ------------------------------------------------------------------
NAV = {
    "type": "nav",
    "wind": {"source": "LIVE", "stale": False, "heading_trusted": True},
    "helm": {"primary": "twa_up", "target": 42.4, "deviation": 3.2},
    "boat": {"bsp_kn": 6.84},
    "polar": {"target_bsp_kn": 7.06, "pct": 97},
    "mark": {"name": "Plić Sestre", "dtw_nm": 0.35, "ttw_s": 300, "btw_t": 160},
    "display": {"heading_ref": "M", "variation": 4.7},
    "leg": "beat",
    "layline": {
        "state": "normal",
        "countdown_s": 720,
        "dist_nm": 1.52,
        "other_tack_hdg_t": 210,
    },
    "alerts": ["VENT GRIB (pas d'instruments)", "PAS DE VENT"],
}


def _views(lang: str, nav: dict) -> dict:
    return node(
        f"I.setLang({json.dumps(lang)}, {{persist: false}});\n"
        f"const v = M0.helmView({json.dumps(nav)});\n" + out("v"),
        "helm_logic.js",
    )


def test_helm_in_english_and_slovenian() -> None:
    fr, en, sl = (_views(lang, NAV) for lang in ("fr", "en", "sl"))
    assert fr["speed"] == "6,8 / 7,1 nds" and fr["countdown"] == "Virement dans 12 min"
    assert fr["primary"]["label"] == "TWA CIBLE ↑" and fr["dev"]["hint"] == "LOFER"
    assert en["speed"] == "6.8 / 7.1 kn" and en["countdown"] == "Tack in 12 min"
    assert en["markLine"] == "Plić Sestre 0.35 nm · 5 min"
    assert en["laylineDist"] == "Layline in 1.5 nm"
    assert en["primary"]["label"] == "TARGET TWA ↑" and en["dev"]["hint"] == "HEAD UP"
    assert en["alerts"] == ["GRIB WIND (no instruments)"]
    assert sl["speed"] == "6,8 / 7,1 kn" and sl["countdown"] == "Obrat čez 12 min"
    assert sl["markLine"] == "Plić Sestre 0,35 nm · 5 min"
    assert sl["primary"]["label"] == "CILJNI TWA ↑" and sl["dev"]["hint"] == "ORCAJ"
    assert sl["otherTack"].startswith("Po obratu ")
    assert sl["alerts"] == ["VETER GRIB (brez instrumentov)"]
    assert sl["badge"] == {"text": "LIVE", "cls": "good"}


def test_route_band_in_english_and_slovenian() -> None:
    route = {
        "state": "ok",
        "primary": "twa",
        "target": 42.0,
        "target_tack": "stbd",
        "target_hdg_t": 119.0,
        "deviation": 1.0,
        "countdown_s": 510,
        "tack_kind": "tack",
        "age_s": 190,
        "cost_text": "+4 min",
        "stay": {"active": True, "tack": "stbd"},
        "level": "L0",
        "bias": {"enabled": True, "valid": False, "state": "apprentissage"},
    }
    nav = {**NAV, "route": route}
    res = {}
    for lang in ("fr", "en", "sl"):
        res[lang] = node(
            f"I.setLang({json.dumps(lang)}, {{persist: false}});\n"
            f"const nav = {json.dumps(nav)};\n"
            "const out = {band: M0.routeBand(nav), cd: M0.countdownView(nav),\n"
            "  stay: M0.stayButton(nav.route), p: M1.primaryView(nav),\n"
            "  why: M0.routeBand({route: {state: 'outdated', reason: 'route périmée (25 min) : "
            "erreur du routeur'}}).lines.status};\n" + out("out"),
            "route_logic.js",
            "helm_logic.js",
        )
    fr, en, sl = res["fr"], res["en"], res["sl"]
    assert fr["cd"]["text"] == "Virement dans 08:30" and fr["stay"]["label"] == "ANNULER ON RESTE"
    assert fr["why"] == "Route retirée : route périmée (25 min) : erreur du routeur"
    assert en["cd"]["text"] == "Tack in 08:30" and en["p"]["value"] == "42° starboard"
    assert en["band"]["lines"]["cost"] == "Not tacking: +4 min"
    assert en["band"]["lines"]["status"] == "Holding tack (starboard)"
    assert en["band"]["lines"]["bias"] == "GRIB bias: learning"
    assert en["why"] == "Route withdrawn: route outdated (25 min): router error"
    assert sl["cd"]["text"] == "Obrat čez 08:30" and sl["p"]["value"] == "42° desno"
    assert sl["stay"]["label"] == "PREKLIČI OSTANEMO"
    assert sl["band"]["lines"]["age"] == "Pot: pred 3 min"
    assert sl["why"] == "Pot umaknjena: pot zastarela (25 min): napaka izračuna poti"


# -- review sheet ---------------------------------------------------------------------------------
def test_the_slovenian_review_sheet_is_up_to_date() -> None:
    text = i18n_review.render(i18n_review.load_dict(NODE))
    assert "NOT yet proofread" in text and "| `helm.tackIn` |" in text
    assert i18n_review.DOC.read_text(encoding="utf-8") == text, (
        "docs/I18N-SL-REVIEW.md is out of date: python -m jabuka.tools.i18n_review"
    )
