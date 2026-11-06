"""The commissioning docs cannot drift from the code (plan 04-02, T-04-02-03).

- the fastnet-probe exit-code table in docs/COMMISSIONING.md is jabuka.tools.probe's table;
- every tool command in a sh block parses with that tool's real argparse parser;
- the nine runbook sections exist in order with their CONTEXT keywords;
- 01-UAT / 02-UAT / PI-SETUP / TABLET-SETUP references point at existing items;
- relative Markdown links resolve;
- the Slovenian card stays one page with the on-screen glossary.
"""

from __future__ import annotations

import argparse
import importlib
import re
import shlex
from collections.abc import Callable
from pathlib import Path

import pytest

from jabuka.tools import probe

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
RUNBOOK = DOCS / "COMMISSIONING.md"
CARD = DOCS / "COMMISSIONING-SL.md"
PHASES = REPO / ".planning" / "phases"
UAT = {
    "01": PHASES / "01-foundation-data-backbone-bus-test-kit" / "01-UAT.md",
    "02": PHASES / "02-helm-mvp-laylines-marks-map" / "02-UAT.md",
}
PI_SETUP = REPO / "deploy" / "PI-SETUP.md"
TABLET = DOCS / "TABLET-SETUP.md"
# created by plan 04-01 in the same wave: links to them are allowed before they exist
LINK_ALLOW = {"docs/SOAK.md", "scripts/soak.sh"}
COMMAND_DOCS = [RUNBOOK]

SECTIONS = [
    (1, "Avant de partir (maison)"),
    (2, "Câblage du bus Fastnet"),
    (3, "Capture et inventaire"),
    (4, "Contrôles des instruments"),
    (5, "Tablette"),
    (6, "Pack de course"),
    (7, "Parcours"),
    (8, "Exercices en mode dégradé"),
    (9, "Go / no-go et plans B"),
]
KEYWORDS = {
    1: ["SD de secours", "DTECH", "VK-162", "12 V", "USB", "fusibles", "outils", "3D",
        "Banc d'essai Pi", "route_level", "SOAK.md", "FREEZE.md", "SPARE-SD.md"],
    2: ["Blanc = Data+", "Vert = Data−", "terminaison", "Écoute seule", "Photos",
        "fastnet-probe", "croiser Blanc et Vert"],
    3: ["avant tout autre", "toutes les pages", "inventory.json", "archive"],
    4: ["variation_deg", "heading_offset_deg", "COG", "AWA", "BSP", "TWD", "true_wind_source",
        "au moteur", "Pitfall 4"],
    5: ["mode avion", "unsafely-treat-insecure-origin-as-secure", "Stay awake", "luminosité",
        "verrou", "support 3D", "Pitfall 17"],
    6: ["ICON-EU", "EWAM", "Overpass", "organisateur", "racepack-dryrun.sh", "COUVERTURE",
        "Checklist vendredi 13 novembre", "15:40 UTC"],
    7: ["IC", "Côtés confirmés", "30 s", "inscription", "Pitfall 19"],
    8: ["GRIB", "MANUEL", "ON RESTE", "alimentation", "SPARE-SD.md"],
    9: ["GO", "Plan B", "OpenCPN", "Plan C", "papier", "route_level", "10°"],
}  # fmt: skip

TOOLS: dict[str, tuple[str, str]] = {
    "fastnet-probe": ("jabuka.tools.probe", "build_arg_parser"),
    "jabuka-replay": ("jabuka.sim.pty_replay", "build_arg_parser"),
    "jabuka-sim": ("jabuka.sim.synth", "build_arg_parser"),
    "jabuka-logcheck": ("jabuka.tools.logcheck", "build_arg_parser"),
    "jabuka-prep": ("jabuka.prep.cli", "build_parser"),
    "jabuka-route-bench": ("jabuka.route.bench", ""),  # parser built inside main()
    "jabuka-core": ("jabuka.core.main", "build_arg_parser"),
    "jabuka-ingest-fastnet": ("jabuka.ingest.fastnet_main", "build_arg_parser"),
}
PLACEHOLDER = re.compile(r"<[^<>]+>")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sections(text: str) -> dict[int, str]:
    heads = list(re.finditer(r"^## (\d)\. (.+)$", text, re.M))
    out: dict[int, str] = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.search(r"^## (?!\d\.)", text[m.end() : end], re.M)
        out[int(m.group(1))] = text[m.start() : m.end() + nxt.start() if nxt else end]
    return out


# -- structure ---------------------------------------------------------------------------------
def test_nine_sections_in_order_with_their_keywords() -> None:
    text = _text(RUNBOOK)
    heads = re.findall(r"^## (\d)\. (.+)$", text, re.M)
    assert [int(n) for n, _ in heads] == list(range(1, 10)), heads
    for (n, title), (got_n, got_title) in zip(SECTIONS, heads, strict=True):
        assert int(got_n) == n and got_title.startswith(title), (n, got_title)
    secs = _sections(text)
    for n, words in KEYWORDS.items():
        missing = [w for w in words if w not in secs[n]]
        assert not missing, f"§{n} lacks {missing}"
    for anchor in ("Plan des deux journées", "Annexe A", "Annexe B", "jeudi 12", "vendredi 13"):
        assert anchor in text, anchor
    assert len(text.splitlines()) >= 250
    assert "À compléter" not in text


def test_exit_code_table_is_the_probes() -> None:
    sec = _sections(_text(RUNBOOK))[2]
    rows = re.findall(r"^\| (\d) \| `[^`]+`(?: / `[^`]+`)? \(([a-z_]+|erreur)\) \|", sec, re.M)
    table = {verdict: int(code) for code, verdict in rows}
    assert sorted(int(c) for c, _ in rows) == [0, 1, 2, 3, 4, 5], rows
    assert table.pop("erreur") == probe.EXIT_ERROR
    assert table == probe.EXIT_CODES


# -- commands ----------------------------------------------------------------------------------
def _sh_commands(text: str) -> list[str]:
    """Logical lines (backslash continuations joined) of ```sh / ```bash blocks."""
    out: list[str] = []
    for block in re.findall(r"^```(?:sh|bash)\n(.*?)^```", text, re.M | re.S):
        buf = ""
        for raw in block.splitlines():
            line = raw.rstrip()
            if line.endswith("\\"):
                buf += line[:-1] + " "
                continue
            out.append((buf + line).strip())
            buf = ""
    return out


def _tool_argv(line: str) -> tuple[str, list[str]] | None:
    """(tool, argv) when the line runs a jabuka tool (optionally via sudo -u USER and a venv
    path such as /opt/jabuka/venv/bin/), else None."""
    words = shlex.split(PLACEHOLDER.sub("1", line), comments=True)
    if words[:1] == ["sudo"]:
        words = words[1:]
        if words[:1] == ["-u"]:
            words = words[2:]
    if not words:
        return None
    tool = words[0].rsplit("/", 1)[-1]
    if tool not in TOOLS:
        return None
    argv: list[str] = []
    for w in words[1:]:
        if w in ("|", "||", "&&", ";", ">", "2>&1") or w.startswith((">", "|")):
            break
        argv.append(w)
    return tool, argv


class _Parsed(Exception):
    pass


def _parse(tool: str, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    module, builder = TOOLS[tool]
    mod = importlib.import_module(module)
    if builder:
        getattr(mod, builder)().parse_args(argv)
        return
    original = argparse.ArgumentParser.parse_args

    def parse_then_stop(self, args=None, namespace=None):  # type: ignore[no-untyped-def]
        original(self, args, namespace)
        raise _Parsed

    with monkeypatch.context() as m:
        m.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
        with pytest.raises(_Parsed):
            mod.main(argv)


def _check_commands(doc: Path, monkeypatch: pytest.MonkeyPatch) -> set[str]:
    seen: set[str] = set()
    for line in _sh_commands(_text(doc)):
        parsed = _tool_argv(line)
        if parsed is None:
            continue
        tool, argv = parsed
        try:
            _parse(tool, argv, monkeypatch)
        except SystemExit as e:
            pytest.fail(f"{doc.name}: `{line}` does not parse with {tool}'s parser (exit {e})")
        seen.add(tool)
    return seen


@pytest.mark.parametrize("doc", COMMAND_DOCS, ids=lambda p: p.name)
def test_tool_commands_parse(doc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _check_commands(doc, monkeypatch)
    if doc == RUNBOOK:
        assert {"fastnet-probe", "jabuka-logcheck", "jabuka-prep"} <= seen, seen


def test_command_checker_catches_a_bad_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        _parse("fastnet-probe", ["--device", "/dev/x", "--secs", "5"], monkeypatch)
    with pytest.raises(SystemExit):
        _parse("jabuka-route-bench", ["--nope"], monkeypatch)
    _parse("jabuka-route-bench", ["--pack", "var/racepack", "--quick"], monkeypatch)
    assert _tool_argv("sudo -u jabuka /opt/jabuka/venv/bin/jabuka-logcheck <dir>") == (
        "jabuka-logcheck",
        ["1"],
    )


# -- references --------------------------------------------------------------------------------
def _uat_numbers(path: Path) -> set[int]:
    return {int(n) for n in re.findall(r"^### (\d+)\.", _text(path), re.M)}


def _pi_setup_letters() -> set[str]:
    text = _text(PI_SETUP)
    sec4 = text[text.index("## 4.") : text.index("## 5.")]
    return set(re.findall(r"^([a-z])\. \*\*", sec4, re.M))


def _numbered_headings(path: Path) -> set[int]:
    return {int(n) for n in re.findall(r"^## (\d+)\.", _text(path), re.M)}


def _letters(spec: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r", | et | ", spec):
        m = re.fullmatch(r"([a-z])[–-]([a-z])", part)
        if m:
            out += [chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)]
        elif re.fullmatch(r"[a-z]", part):
            out.append(part)
    return out


def check_references(doc: Path) -> None:
    text = _text(doc)
    for phase, path in UAT.items():
        known = _uat_numbers(path)
        for spec in re.findall(rf"{phase}-UAT #(\d+(?:[–-]#?\d+)?)", text):
            nums = [int(x) for x in re.findall(r"\d+", spec)]
            if len(nums) == 2:
                nums = list(range(nums[0], nums[1] + 1))
            for n in nums:
                assert n in known, f"{doc.name}: {phase}-UAT #{n} does not exist"
    letters = _pi_setup_letters()
    for spec in re.findall(r"PI-SETUP §4 ([a-z](?:(?:, | et |[–-])[a-z])*)\b", text):
        for letter in _letters(spec):
            assert letter in letters, f"{doc.name}: PI-SETUP §4 {letter} does not exist"
    pi_heads = _numbered_headings(PI_SETUP)
    for n in re.findall(r"PI-SETUP §(\d+)", text):
        assert int(n) in pi_heads, f"{doc.name}: PI-SETUP §{n} does not exist"
    tab_heads = _numbered_headings(TABLET)
    for a, b in re.findall(r"TABLET-SETUP §(\d+)(?:[–-]§?(\d+))?", text):
        for n in range(int(a), int(b or a) + 1):
            assert n in tab_heads, f"{doc.name}: TABLET-SETUP §{n} does not exist"


def check_links(doc: Path) -> None:
    for target in re.findall(r"\]\(([^)\s]+)\)", _text(doc)):
        target = target.split("#", 1)[0]
        if not target or re.match(r"^[a-z]+:", target):
            continue
        resolved = (doc.parent / target).resolve()
        rel = resolved.relative_to(REPO).as_posix() if resolved.is_relative_to(REPO) else target
        if rel in LINK_ALLOW:
            continue
        assert resolved.exists(), f"{doc.name}: broken link {target}"


def test_runbook_references_exist() -> None:
    text = _text(RUNBOOK)
    for needed in ("01-UAT #5", "01-UAT #7", "02-UAT #6", "02-UAT #8", "02-UAT #9", "PI-SETUP §5"):
        assert needed in text, needed
    check_references(RUNBOOK)


@pytest.mark.parametrize("doc", [RUNBOOK, CARD], ids=lambda p: p.name)
def test_relative_links_resolve(doc: Path) -> None:
    check_links(doc)


def test_reference_checker_catches_a_bad_reference(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    for text in ("voir 01-UAT #42", "voir PI-SETUP §4 z", "voir TABLET-SETUP §77", "[x](nope.md)"):
        bad.write_text(text, encoding="utf-8")
        check: Callable[[Path], None] = check_links if "](" in text else check_references
        with pytest.raises(AssertionError):
            check(bad)


# -- Slovenian card ----------------------------------------------------------------------------
def test_slovenian_card_is_one_page_with_the_glossary() -> None:
    text = _text(CARD)
    assert len(text.splitlines()) <= 80
    for word in (
        "http://10.42.0.1",
        "LIVE",
        "GRIB",
        "MANUEL",
        "ON RESTE",
        "VIREZ",
        "Virement dans",
        "Ne pas virer",
        "CAP À SUIVRE",
        "Route mise à jour",
        "Marque suivante",
        "brouillon, à relire par un locuteur slovène",
    ):
        assert word in text, word


def test_pi_setup_points_to_the_phase4_docs() -> None:
    text = _text(PI_SETUP)
    sec7 = text[text.index("## 7.") :]
    for doc in ("SOAK.md", "COMMISSIONING.md", "SPARE-SD.md", "FREEZE.md"):
        assert doc in sec7, doc
    assert "Deferred to Phase 4" not in text
