"""Static receive-only guard: nothing in jabuka.ingest or jabuka.tools can write to a serial
device (RESEARCH Test Strategy SC2, threat T-02-01). The kernel enforces it too (O_RDONLY fd)."""

from __future__ import annotations

import ast
import errno
import fcntl
import os
from pathlib import Path

import pytest

import jabuka
from jabuka.ingest.serial_ro import open_fastnet
from jabuka.sim.pty_replay import PtyFeeder

PKG = Path(jabuka.__file__).resolve().parent
SCANNED_DIRS = (PKG / "ingest", PKG / "tools")
DEVICE_NAMES = {"ser", "serial", "port", "tty", "dev", "device", "fastnet"}
WRITE_FLAGS = {"O_RDWR", "O_WRONLY"}


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _only_refuses(fn: ast.FunctionDef) -> bool:
    """A method whose whole body is `raise PermissionError(...)` (ReadOnlySerial's overrides)."""
    body = [
        n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    ]
    return (
        len(body) == 1
        and isinstance(body[0], ast.Raise)
        and isinstance(body[0].exc, ast.Call)
        and _name(body[0].exc.func) == "PermissionError"
    )


def violations(source: str, filename: str = "<src>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    out: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute):
            if node.attr in WRITE_FLAGS and _name(node.value) == "os":
                out.append(f"{filename}:{line} os.{node.attr}")
            if node.attr == "send_break":
                out.append(f"{filename}:{line} .send_break")
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name in WRITE_FLAGS or alias.name == "write":
                    out.append(f"{filename}:{line} from os import {alias.name}")
        if isinstance(node, ast.FunctionDef) and node.name == "send_break":
            if not _only_refuses(node):
                out.append(f"{filename}:{line} def send_break")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            recv = _name(func.value)
            if func.attr == "write" and recv == "os":
                out.append(f"{filename}:{line} os.write()")
            if recv == "serial" and func.attr in ("Serial", "serial_for_url"):
                out.append(f"{filename}:{line} serial.{func.attr}()")
            if func.attr == "write" and recv in DEVICE_NAMES:
                out.append(f"{filename}:{line} {recv}.write()")
    return out


def _sources() -> list[Path]:
    files: list[Path] = []
    for d in SCANNED_DIRS:
        files += sorted(d.glob("*.py"))
    return files


def test_scan_covers_ingest_and_tools() -> None:
    names = {p.name for p in _sources()}
    for expected in ("serial_ro.py", "fastnet_main.py", "probe.py", "bus_health.py"):
        assert expected in names


def test_no_write_constructs_in_ingest_or_tools() -> None:
    found: list[str] = []
    for path in _sources():
        found += violations(path.read_text(), str(path.relative_to(PKG)))
    assert found == [], "receive-only violated:\n" + "\n".join(found)


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\nfd = os.open('/dev/fastnet', os.O_RDWR)",
        "import os\nfd = os.open('/dev/fastnet', os.O_WRONLY)",
        "from os import O_RDWR",
        "import os\nos.write(3, b'x')",
        "import serial\ns = serial.Serial('/dev/fastnet')",
        "import serial\ns = serial.serial_for_url('/dev/fastnet')",
        "ser.send_break(0.25)",
        "ser.write(b'x')",
        "self.ser.write(b'x')",
        "port.write(b'x')",
        "self.device.write(b'x')",
        "fastnet.write(b'x')",
    ],
)
def test_guard_catches_each_forbidden_construct(snippet: str) -> None:
    assert violations(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "import serial\nclass ReadOnlySerial(serial.Serial):\n    pass",
        "fh.write(b'log line')",
        "out.write(data)",
        "import os\nfd = os.open(p, os.O_RDONLY | os.O_NOCTTY)",
    ],
)
def test_guard_allows_safe_constructs(snippet: str) -> None:
    assert violations(snippet) == []


def test_open_fastnet_reopens_the_same_tty() -> None:
    """Ingest restart / reconnect on a tty that was already set to 28800 8O2 (glibc 2.43 used to
    reject the second open with EINVAL)."""
    with PtyFeeder() as feeder:
        for _ in range(3):
            ser = open_fastnet(feeder.slave_path)
            try:
                assert fcntl.fcntl(ser.fileno(), fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
            finally:
                ser.close()


def test_open_fastnet_on_a_pty_is_read_only() -> None:
    with PtyFeeder() as feeder:
        ser = open_fastnet(feeder.slave_path)
        try:
            fd = ser.fileno()
            assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
            with pytest.raises(OSError) as ei:
                os.write(fd, b"\x00")
            assert ei.value.errno == errno.EBADF
            with pytest.raises(PermissionError):
                ser.write(b"\x00")
        finally:
            ser.close()
