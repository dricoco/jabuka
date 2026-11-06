"""The Pi runtime is hash-locked for aarch64/cp313 and installable from an offline wheelhouse."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

EXPECTED_LOCKED = {
    "annotated-doc",
    "annotated-types",
    "anyio",
    "click",
    "fastapi",
    "h11",
    "idna",
    "opentelemetry-api",
    "pydantic",
    "pydantic-core",
    "pyfastnet",
    "pyserial",
    "starlette",
    "typing-extensions",
    "typing-inspection",
    "uvicorn",
    "websockets",
}
FORBIDDEN = {"watchfiles", "uvloop", "httptools"}  # uvicorn[standard] extras, not on the Pi


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _lock_entries(lock_text: str) -> dict[str, tuple[str, list[str]]]:
    """{name: (version, [sha256 hashes])} from a pip-compile style hash lock."""
    entries: dict[str, tuple[str, list[str]]] = {}
    current: str | None = None
    for line in lock_text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)\s*(\\)?$", line)
        if m:
            current = _norm(m.group(1))
            entries[current] = (m.group(2), [])
            continue
        h = re.match(r"^\s+--hash=sha256:([0-9a-f]{64})", line)
        if h and current is not None:
            entries[current][1].append(h.group(1))
            continue
        if line.strip() and not line.startswith((" ", "#")):
            pytest.fail(f"unexpected lock line: {line!r}")
    return entries


@pytest.fixture
def lock(deploy_dir: Path) -> dict[str, tuple[str, list[str]]]:
    return _lock_entries((deploy_dir / "requirements.lock").read_text())


def test_requirements_in_equals_pyproject_dependencies(repo_root: Path, deploy_dir: Path) -> None:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    assert _requirements((deploy_dir / "requirements.in").read_text()) == deps


def test_lock_is_fully_hashed_and_pins_the_direct_deps(deploy_dir: Path, lock) -> None:
    assert lock, "empty lock"
    for name, (version, hashes) in lock.items():
        assert hashes, f"{name}=={version} has no --hash=sha256"
    for req in _requirements((deploy_dir / "requirements.in").read_text()):
        name, _, version = req.partition("==")
        assert lock[_norm(name)][0] == version, req


def test_lock_is_for_the_pi(deploy_dir: Path, lock) -> None:
    header = (deploy_dir / "requirements.lock").read_text()
    assert "--python-platform aarch64-unknown-linux-gnu" in header
    assert "--python-version 3.13" in header
    assert "--generate-hashes" in header
    assert set(lock) == EXPECTED_LOCKED, "review new/removed packages before shipping"


def test_lock_has_no_uvicorn_standard_extras(lock) -> None:
    assert not FORBIDDEN & set(lock)


def test_wheelhouse(deploy_dir: Path, lock) -> None:
    wh = deploy_dir / "wheelhouse"
    if not wh.is_dir():
        pytest.skip("deploy/wheelhouse absent: run `bash scripts/build-wheelhouse.sh` (needs pypi)")
    names = sorted(p.name for p in wh.glob("*.whl"))
    assert "jabuka-0.1.0-py3-none-any.whl" in names
    for binary in ("pydantic_core", "websockets"):
        hits = [n for n in names if n.startswith(binary + "-")]
        assert len(hits) == 1, (binary, hits)
        assert "aarch64" in hits[0] and "cp313" in hits[0], hits[0]
    # exactly one wheel per locked package, at the locked version
    for name, (version, _) in lock.items():
        stem = re.sub(r"[-.]+", "_", name)
        hits = [n for n in names if _norm(n.split("-")[0]) == name]
        assert len(hits) == 1, (name, hits)
        assert hits[0].startswith(f"{stem}-{version}-"), (name, version, hits[0])
