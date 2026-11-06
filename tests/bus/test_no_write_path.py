"""Static receive-only guard: nothing in jabuka.ingest or jabuka.tools can write to, or drive the
line of, a serial device (RESEARCH Test Strategy SC2, threat T-02-01).

The kernel enforces data writes (O_RDONLY fd) and ReadOnlySerial refuses line control at runtime
(WR-01); this scan is the third layer. It flags (WR-02):
- any reference to a line-control ioctl, termios call or pyserial method (break, RTS/DTR, RS-485,
  tcflow), as a name, an attribute or an exact string (getattr/setattr);
- any assignment to a pyserial line attribute (break_condition, rts, dtr, rs485_mode, rtscts,
  dsrdtr, xonxoff), via `x.attr = ...` or setattr, and enabling keywords for those in calls;
- importing pyserial anywhere except ingest/serial_ro.py;
- os write calls/flags through any alias (`import os as o`, `w = os.write`, `from os import ...`);
- os.open() whose flags are not literally read-only flags, and open()/Path.open() in a writing
  mode outside the allowlisted log writers; Path.write_bytes/write_text;
- fcntl.ioctl() with a request that is not a known read-only request;
- .write() on device-like names; defining a line-control method that does more than refuse.
"""

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
OS_WRITE_NAMES = {
    "O_RDWR",
    "O_WRONLY",
    "O_APPEND",
    "O_TRUNC",
    "O_CREAT",
    "write",
    "writev",
    "pwrite",
    "pwritev",
    "sendfile",
    "fdopen",
}
RO_OPEN_FLAGS = {"O_RDONLY", "O_NOCTTY", "O_NONBLOCK", "O_NDELAY", "O_CLOEXEC"}
LINE_CONTROL_NAMES = {
    # ioctls / termios
    "TIOCSBRK",
    "TIOCCBRK",
    "TCSBRK",
    "TCSBRKP",
    "TIOCMSET",
    "TIOCMBIS",
    "TIOCMBIC",
    "TIOCSRS485",
    "TIOCSSERIAL",
    "tcsendbreak",
    "tcflow",
    "TCION",
    "TCIOFF",
    "TCOON",
    "TCOOFF",
    # pyserial methods that reach them
    "send_break",
    "sendBreak",
    "setRTS",
    "setDTR",
    "setXON",
    "flowControlOut",
    "set_input_flow_control",
    "set_output_flow_control",
    "_update_break_state",
    "_update_rts_state",
    "_update_dtr_state",
    "_set_rs485_mode",
}
LINE_ATTRS = {"break_condition", "rts", "dtr", "rs485_mode", "rtscts", "dsrdtr", "xonxoff"}
READ_ONLY_IOCTLS = {"TIOCGICOUNT", "TIOCMGET", "TIOCINQ", "FIONREAD", "TIOCOUTQ", "TCGETS"}
SERIAL_IMPORT_ALLOWED = {"ingest/serial_ro.py"}
# (file, enclosing function) allowed to open a file for writing: log files, never a device
WRITE_OPEN_ALLOWED = {("ingest/rawlog.py", "_open"), ("tools/probe.py", "_finish_capture")}
WRITE_MODE_CHARS = set("wax+")


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


def _os_aliases(tree: ast.AST) -> set[str]:
    names = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "os":
                    names.add(a.asname or "os")
    return names


def _ro_flags(node: ast.AST, os_names: set[str]) -> bool:
    """flags expression built only from os.O_RDONLY | os.O_NOCTTY | ... (no numbers)."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _ro_flags(node.left, os_names) and _ro_flags(node.right, os_names)
    if isinstance(node, ast.Attribute) and _name(node.value) in os_names:
        return node.attr in RO_OPEN_FLAGS
    return False


def _mode_arg(call: ast.Call, positional: int) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    if len(call.args) > positional:
        return call.args[positional]
    return None


def _writing_mode(mode: ast.AST | None) -> bool:
    if mode is None:
        return False  # default "r"
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(WRITE_MODE_CHARS & set(mode.value))
    return True  # not a literal: cannot prove read-only


def _enclosing_functions(tree: ast.AST) -> dict[ast.AST, str]:
    out: dict[ast.AST, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            for n in ast.walk(fn):
                out[n] = fn.name  # inner functions overwrite: walk order is outer first
    return out


def violations(source: str, filename: str = "<src>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    os_names = _os_aliases(tree)
    owner = _enclosing_functions(tree)
    out: list[str] = []

    def flag(node: ast.AST, what: str) -> None:
        out.append(f"{filename}:{getattr(node, 'lineno', 0)} {what}")

    for node in ast.walk(tree):
        # -- imports
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "serial" and filename not in SERIAL_IMPORT_ALLOWED:
                    flag(node, f"import {a.name}")
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root == "serial" and filename not in SERIAL_IMPORT_ALLOWED:
                flag(node, f"from {node.module} import")
            for a in node.names:
                if root == "os" and a.name in OS_WRITE_NAMES | {"open"}:
                    flag(node, f"from os import {a.name}")
                if a.name in LINE_CONTROL_NAMES:
                    flag(node, f"from {node.module} import {a.name}")
        # -- names, attributes, strings
        if isinstance(node, ast.Name) and node.id in LINE_CONTROL_NAMES:
            flag(node, node.id)
        if isinstance(node, ast.Attribute):
            if node.attr in LINE_CONTROL_NAMES:
                flag(node, f".{node.attr}")
            if node.attr in OS_WRITE_NAMES and _name(node.value) in os_names:
                flag(node, f"os.{node.attr}")
            if node.attr in LINE_ATTRS and isinstance(node.ctx, ast.Store | ast.Del):
                flag(node, f".{node.attr} = ...")
            if node.attr in ("write_bytes", "write_text"):
                flag(node, f".{node.attr}")
        if isinstance(node, ast.Constant) and node.value in LINE_CONTROL_NAMES:
            flag(node, repr(node.value))
        # -- definitions
        if isinstance(node, ast.FunctionDef) and node.name in LINE_CONTROL_NAMES:
            if not _only_refuses(node):
                flag(node, f"def {node.name}")
        # -- calls
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = _name(func)
        recv = _name(func.value) if isinstance(func, ast.Attribute) else None
        if fname in ("setattr", "delattr") and len(node.args) >= 2:
            attr = node.args[1]
            if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)):
                flag(node, f"{fname}() with a computed name")
            elif attr.value in LINE_ATTRS:
                flag(node, f"{fname}(..., {attr.value!r})")
        for kw in node.keywords:
            if kw.arg in LINE_ATTRS and not (
                isinstance(kw.value, ast.Constant) and kw.value.value in (False, None)
            ):
                flag(node, f"{kw.arg}= keyword")
        if recv in os_names and fname == "open":
            flags = node.args[1] if len(node.args) > 1 else None
            for kw in node.keywords:
                if kw.arg == "flags":
                    flags = kw.value
            if flags is None or not _ro_flags(flags, os_names):
                flag(node, "os.open() without literal read-only flags")
        elif fname == "open" or (isinstance(func, ast.Attribute) and fname == "open"):
            positional = 0 if isinstance(func, ast.Attribute) else 1  # Path.open(mode)
            if _writing_mode(_mode_arg(node, positional)):
                if (filename, owner.get(node)) not in WRITE_OPEN_ALLOWED:
                    flag(node, "open() in a writing mode")
        if fname == "ioctl":
            req = node.args[1] if len(node.args) > 1 else None
            if req is None or _name(req) not in READ_ONLY_IOCTLS:
                flag(node, "ioctl() with a request that is not known read-only")
        if recv == "serial" and fname in ("Serial", "serial_for_url"):
            flag(node, f"serial.{fname}()")
        if fname == "write" and recv in DEVICE_NAMES:
            flag(node, f"{recv}.write()")
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
        # WR-02: every construct the review found undetected
        "ser.break_condition = True",
        "ser.rts = True",
        "ser.dtr = False",
        "import fcntl, termios\nfcntl.ioctl(fd, termios.TIOCSBRK)",
        "import termios\ntermios.tcsendbreak(fd, 0)",
        "from serial import Serial\nSerial('/dev/fastnet')",
        "open('/dev/fastnet', 'wb').write(b'x')",
        "import os\nos.open('/dev/fastnet', 2)",
        "from pathlib import Path\nPath('/dev/fastnet').write_bytes(b'x')",
        "self.ser.sendBreak()",
        "import os as o\no.write(3, b'x')",
        "import os\nw = os.write\nw(3, b'x')",
        "s.rs485_mode = x",
        # and their close relatives
        "import termios\ntermios.tcflow(fd, termios.TCIOFF)",
        "import fcntl\nfcntl.ioctl(fd, 0x5427)",
        "import fcntl\nfcntl.ioctl(fd, TIOCMBIS, b'')",
        "setattr(ser, 'rts', True)",
        "setattr(ser, name, True)",
        "getattr(termios, 'TIOCSBRK')",
        "ser.setRTS(1)",
        "ser.xonxoff = True",
        "ReadOnlySerial('/dev/fastnet', rtscts=True)",
        "import serial.tools.list_ports",
        "import os as o\nfd = o.open('/dev/fastnet', o.O_RDWR)",
        "from os import open as osopen",
        "import os\nos.fdopen(3, 'wb')",
        "open(path, mode)",
        "open(path, 'a')",
        "open(path, mode='r+b')",
        "from pathlib import Path\nPath(p).open('wb')",
        "class S:\n    def send_break(self):\n        termios.tcsendbreak(self.fd, 0)",
        "class S:\n    def _update_rts_state(self):\n        pass",
    ],
)
def test_guard_catches_each_forbidden_construct(snippet: str) -> None:
    assert violations(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "fh.write(b'log line')",
        "out.write(data)",
        "import os\nfd = os.open(p, os.O_RDONLY | os.O_NOCTTY)",
        "import os as o\nfd = o.open(p, o.O_RDONLY | o.O_NOCTTY | o.O_NONBLOCK)",
        "open('/proc/sys/kernel/random/boot_id')",
        "open(p, 'rb')",
        "from pathlib import Path\nPath(p).read_bytes()",
        "import fcntl\nfcntl.ioctl(fd, TIOCGICOUNT, buf)",
        "class S:\n    def send_break(self, d=0.25):\n        raise PermissionError('ro')",
        "ser.rts",
        "writer.write(b'?WATCH;')",
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


def test_allowlisted_writers_still_exist() -> None:
    """The open-for-writing allowlist must not silently cover renamed code."""
    for rel, func in WRITE_OPEN_ALLOWED:
        tree = ast.parse((PKG / rel).read_text())
        assert any(isinstance(n, ast.FunctionDef) and n.name == func for n in ast.walk(tree)), (
            rel,
            func,
        )


def test_write_open_outside_the_allowlist_is_flagged() -> None:
    src = "def _open(self):\n    open(p, 'xb')\n"
    assert violations(src, "ingest/rawlog.py") == []
    assert violations(src, "ingest/other.py")
    assert violations("def g():\n    open(p, 'xb')\n", "ingest/rawlog.py")


def test_pyserial_import_only_in_serial_ro() -> None:
    src = "import serial\nclass ReadOnlySerial(serial.Serial):\n    pass"
    assert violations(src, "ingest/serial_ro.py") == []
    assert violations(src, "tools/probe.py")
