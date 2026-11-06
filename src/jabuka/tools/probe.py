"""fastnet-probe: diagnose the B&G Fastnet bus wiring in seconds, receive-only.

Live mode opens the device O_RDONLY (open_fastnet), reads for --seconds, writes every chunk to
``OUT/capture.log`` (Jabuka raw-log format, replayable with jabuka-replay) and prints a verdict:
OK / NO BYTES / BYTES BUT NO VALID FRAMES (swap A/B) / NOISY / FEW BYTES. ``--file`` analyses an
existing capture instead. Both modes write ``OUT/inventory.json``: every channel seen with its
name, count, last value/display, layouts seen and (for Heading, TWD, Tidal Set and unidentified
layouts) raw record hex, so the unknown "°T" layout code can be found offline.

Exit codes: 0 ok, 2 silent, 3 no_frames (swap wires), 4 noisy, 5 few_bytes, 1 error/device
missing. Stop jabuka-ingest-fastnet first: only one process may own the port.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import select
import struct
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fastnet_decoder
from fastnet_decoder import interpreter as _interp

from jabuka.common.atomicio import atomic_write_json
from jabuka.ingest.bus_health import classify
from jabuka.ingest.fastnet_decode import decode_to_values
from jabuka.ingest.fastnet_framing import (
    BROADCAST,
    KEEP_ALIVE,
    LATLON,
    LIGHT,
    CountingFramer,
    load_capture,
)
from jabuka.ingest.fastnet_records import iter_records, layout_code, record_hex
from jabuka.ingest.rawlog import RotatingAppendLog
from jabuka.ingest.serial_ro import open_fastnet

WIRE_RATE = 2400.0  # bytes/s at 28800 8O2 (12 bits per byte)
LIVE_MIN_SECONDS = 5.0
RAW_RECORD_CHANNELS = (0x49, 0x6D, 0x84)
MAX_RAW_RECORDS = 5
TIOCGICOUNT = 0x545D
# struct serial_icounter_struct: cts dsr rng dcd rx tx frame overrun parity brk buf_overrun
# reserved[9] (20 ints)
_ICOUNT_FMT = "20i"
_ICOUNT_KEYS = ("rx", "frame", "overrun", "parity", "brk", "buf_overrun")
_ICOUNT_INDEX = {"rx": 4, "frame": 6, "overrun": 7, "parity": 8, "brk": 9, "buf_overrun": 10}

EXIT_CODES = {"ok": 0, "silent": 2, "no_frames": 3, "noisy": 4, "few_bytes": 5}
EXIT_ERROR = 1

VERDICT_TITLES = {
    "ok": "OK",
    "silent": "NO BYTES",
    "no_frames": "BYTES BUT NO VALID FRAMES",
    "few_bytes": "FEW BYTES, NO FRAMES",
    "noisy": "NOISY",
    "missing": "DEVICE MISSING",
}

fastnet_decoder.set_log_level("ERROR")


def _hx(n: int) -> str:
    return f"0x{n & 0xFF:02X}"


def read_icount(fd: int) -> dict[str, int] | None:
    """TIOCGICOUNT line counters (FTDI); None where unsupported (a pty gives ENOTTY)."""
    try:
        buf = fcntl.ioctl(fd, TIOCGICOUNT, bytes(struct.calcsize(_ICOUNT_FMT)))
    except OSError:
        return None
    vals = struct.unpack(_ICOUNT_FMT, buf)
    return {k: vals[_ICOUNT_INDEX[k]] for k in _ICOUNT_KEYS}


@dataclass
class ChannelInfo:
    channel_id: int
    name: str = ""
    count: int = 0
    value: Any = None
    disp: str | None = None
    unit: str | None = None
    paths: set[str] = field(default_factory=set)
    si_values: dict[str, Any] = field(default_factory=dict)
    layouts_seen: set[str | None] = field(default_factory=set)
    layout_codes_seen: set[int] = field(default_factory=set)
    formats_seen: set[int] = field(default_factory=set)
    raw_records: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": _hx(self.channel_id),
            "name": self.name,
            "count": self.count,
            "value": self.value,
            "disp": self.disp,
            "unit": self.unit,
            "paths": sorted(self.paths),
            "si_values": self.si_values,
            "layouts_seen": sorted(self.layouts_seen, key=lambda x: (x is None, str(x))),
            "layout_codes_seen": [_hx(c) for c in sorted(self.layout_codes_seen)],
            "formats_seen": [_hx(f) for f in sorted(self.formats_seen)],
            "raw_records": list(self.raw_records),
        }


class Inventory:
    """Accumulates per-channel, per-address and per-command statistics from valid frames."""

    def __init__(self) -> None:
        self.channels: dict[int, ChannelInfo] = {}
        self.from_addresses: Counter[int] = Counter()
        self.decode_errors = 0
        self.undecoded_commands: Counter[int] = Counter()
        self.unknown_ch: set[str] = set()

    def _ch(self, channel_id: int) -> ChannelInfo:
        info = self.channels.get(channel_id)
        if info is None:
            info = ChannelInfo(
                channel_id,
                name=_interp._lookup_or_unknown(_interp.CHANNEL_LOOKUP, channel_id),
            )
            self.channels[channel_id] = info
        return info

    def add_frame(self, frame: bytes) -> None:
        if len(frame) < 6:
            return
        self.from_addresses[frame[1]] += 1
        command = frame[3]
        if command == BROADCAST:
            self._add_broadcast(frame)
        elif command == LATLON:
            self._add_latlon(frame)
        elif command in (LIGHT, KEEP_ALIVE):
            pass
        else:
            self.undecoded_commands[command] += 1
        try:
            res = decode_to_values(frame)
        except Exception:
            self.decode_errors += 1
            return
        if res.error is not None:
            self.decode_errors += 1
            return
        self.unknown_ch.update(res.unknown_ch)
        for v in res.values:
            ch = v.get("ch")
            if not isinstance(ch, str):
                continue
            try:
                info = self._ch(int(ch, 16))
            except ValueError:
                continue
            info.paths.add(v["path"])
            info.si_values[v["path"]] = v.get("value")
            if v.get("unit") is not None:
                info.unit = v["unit"]

    def _add_broadcast(self, frame: bytes) -> None:
        for channel_id, format_byte, data in iter_records(frame):
            info = self._ch(channel_id)
            info.count += 1
            info.formats_seen.add(format_byte & 0x0F)
            rich = _interp.decode_channel_value(channel_id, format_byte, data)
            layout = rich.get("layout") if isinstance(rich, dict) else None
            if isinstance(rich, dict):
                info.value = rich.get("value")
                disp = rich.get("display_text")
                info.disp = None if disp is None else str(disp)
            info.layouts_seen.add(layout)
            code = layout_code(format_byte, data)
            if code is not None:
                info.layout_codes_seen.add(code)
            if channel_id in RAW_RECORD_CHANNELS or layout in ("TBC", None):
                rec = record_hex(channel_id, format_byte, data)
                if rec not in info.raw_records and len(info.raw_records) < MAX_RAW_RECORDS:
                    info.raw_records.append(rec)

    def _add_latlon(self, frame: bytes) -> None:
        decoded = fastnet_decoder.decode_ascii_frame(frame)
        values = decoded.get("values") if isinstance(decoded, dict) else None
        if not isinstance(values, dict):
            return
        for name, entry in values.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("channel_id"), str):
                continue
            try:
                info = self._ch(int(entry["channel_id"], 16))
            except ValueError:
                continue
            info.name = info.name if not info.name.startswith("Unknown") else str(name)
            info.count += 1
            info.value = entry.get("value")
            disp = entry.get("display_text")
            info.disp = None if disp is None else str(disp)
            info.layouts_seen.add(entry.get("layout"))

    def channels_json(self) -> dict[str, dict]:
        return {_hx(k): self.channels[k].to_json() for k in sorted(self.channels)}

    def addresses_json(self) -> dict[str, dict]:
        return {
            _hx(a): {"name": _interp._lookup_or_unknown(_interp.ADDRESS_LOOKUP, a), "count": n}
            for a, n in sorted(self.from_addresses.items())
        }


@dataclass
class ProbeReport:
    state: str
    hint: str
    exit_code: int
    inventory: dict
    inventory_path: Path | None
    capture_path: Path | None
    bytes_received: int = 0

    @property
    def channels(self) -> dict[str, dict]:
        return self.inventory.get("channels", {})


def _finish_capture(out_dir: Path) -> Path | None:
    """Collapse the RotatingAppendLog part file(s) into OUT/capture.log."""
    parts = sorted(out_dir.glob("capture-*.log"))
    target = out_dir / "capture.log"
    if not parts:
        return None
    if len(parts) == 1:
        os.replace(parts[0], target)
        return target
    with open(target, "wb") as out:
        for p in parts:
            out.write(p.read_bytes())
        out.flush()
        os.fsync(out.fileno())
    for p in parts:
        p.unlink()
    return target


def _read_live(
    device: str,
    seconds: float,
    out_dir: Path,
    framer: CountingFramer,
    inv: Inventory,
    on_open: Callable[[], None] | None,
) -> tuple[dict, str | None]:
    """Read the device for `seconds`. Returns (info, device_error)."""
    ser = open_fastnet(device)
    fd = ser.fileno()
    capture = RotatingAppendLog(out_dir, "capture", guard_prefixes=())
    icount_start = read_icount(fd)
    device_error: str | None = None
    t0 = time.monotonic()
    if on_open is not None:
        on_open()
    try:
        deadline = t0 + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.25))
            if not ready:
                continue
            try:
                b = os.read(fd, 4096)
            except BlockingIOError:
                continue
            except OSError as e:  # EIO: adapter unplugged mid-probe
                device_error = f"read error: {e}"
                break
            if not b:
                device_error = "device EOF (unplugged?)"
                break
            capture.write_chunk(b)  # raw first
            for frame in framer.feed(b):
                inv.add_frame(frame)
        icount_end = read_icount(fd)
    finally:
        elapsed = time.monotonic() - t0
        capture.close()
        ser.close()
    tioc: dict | None = None
    if icount_start is not None and icount_end is not None:
        tioc = {k: icount_end[k] - icount_start[k] for k in _ICOUNT_KEYS}
    return {"elapsed_s": elapsed, "tiocgicount": tioc}, device_error


def run_probe(
    source: str | Path,
    *,
    seconds: float = 10.0,
    out_dir: Path,
    file_mode: bool | None = None,
    on_open: Callable[[], None] | None = None,
) -> ProbeReport:
    """Probe a live device (read for `seconds`) or analyse a capture file.

    file_mode None picks by the path: a regular file is a capture, anything else a device.
    on_open (live mode) is called once the device is open and flushed: bytes written into the
    port before that are discarded by the open, exactly like on real hardware.
    """
    source = str(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if file_mode is None:
        file_mode = Path(source).is_file()

    framer = CountingFramer()
    inv = Inventory()
    error: str | None = None
    tioc: dict | None = None
    capture_path: Path | None = None

    if file_mode:
        data = load_capture(source)
        for i in range(0, len(data), 256):  # chunked like the wire: the framer caps its buffer
            for frame in framer.feed(data[i : i + 256]):
                inv.add_frame(frame)
        window_s = len(data) / WIRE_RATE  # equivalent wire time
        mode = "file"
    else:
        mode = "live"
        try:
            info, error = _read_live(source, seconds, out_dir, framer, inv, on_open)
            window_s = info["elapsed_s"]
            tioc = info["tiocgicount"]
        except Exception as e:  # FileNotFoundError, SerialException, termios errors
            window_s = 0.0
            error = f"cannot open {source}: {e}"
        capture_path = _finish_capture(out_dir)

    s = framer.stats
    if mode == "live" and error is not None and s.bytes_in == 0:
        state, hint = "missing", f"DEVICE MISSING: {error}"
        exit_code = EXIT_ERROR
    else:
        state, hint = classify(
            s.bytes_in, s.bytes_discarded, s.frames_ok, max(window_s, 0.0), len(inv.channels)
        )
        exit_code = EXIT_CODES[state]

    inventory = {
        "v": 1,
        "mode": mode,
        "device": None if file_mode else source,
        "file": source if file_mode else None,
        "started_utc": started_utc,
        "seconds": round(window_s, 3),
        "verdict": {"state": state, "hint": hint, "exit_code": exit_code, "error": error},
        "stats": {
            "bytes_in": s.bytes_in,
            "bytes_discarded": s.bytes_discarded,
            "frames_ok": s.frames_ok,
            "valid_ratio": round(1 - s.bytes_discarded / s.bytes_in, 4) if s.bytes_in else None,
            "bytes_per_s": round(s.bytes_in / window_s, 1) if window_s > 0 else 0.0,
            "frames_per_s": round(s.frames_ok / window_s, 1) if window_s > 0 else 0.0,
            "by_command": {_hx(c): n for c, n in sorted(s.by_command.items())},
            "decode_errors": inv.decode_errors,
            "undecoded_commands": {_hx(c): n for c, n in sorted(inv.undecoded_commands.items())},
            "unknown_ch": sorted(inv.unknown_ch),
        },
        "tiocgicount": tioc,
        "channels": inv.channels_json(),
        "from_addresses": inv.addresses_json(),
        "capture": str(capture_path) if capture_path is not None else None,
    }
    inv_path = out_dir / "inventory.json"
    atomic_write_json(inv_path, inventory)
    return ProbeReport(
        state=state,
        hint=hint,
        exit_code=exit_code,
        inventory=inventory,
        inventory_path=inv_path,
        capture_path=capture_path,
        bytes_received=s.bytes_in,
    )


def format_report(report: ProbeReport) -> str:
    inv = report.inventory
    st = inv["stats"]
    lines = [
        f"VERDICT: {VERDICT_TITLES.get(report.state, report.state.upper())} — {report.hint}",
        (
            f"stats: {st['bytes_in']} bytes ({st['bytes_per_s']} B/s), "
            f"{st['frames_ok']} valid frames ({st['frames_per_s']} frames/s), "
            f"{st['bytes_discarded']} bytes discarded, valid ratio {st['valid_ratio']}, "
            f"decode errors {st['decode_errors']}, window {inv['seconds']} s"
        ),
    ]
    if inv.get("tiocgicount"):
        lines.append(f"line counters (TIOCGICOUNT delta): {inv['tiocgicount']}")
    if st["undecoded_commands"]:
        lines.append(f"undecoded commands: {st['undecoded_commands']}")
    chans = inv["channels"]
    if chans:
        lines.append("")
        lines.append(f"{'ID':<5} {'NAME':<34} {'COUNT':>6}  {'LAST':<14} LAYOUTS")
        for cid, c in chans.items():
            layouts = ",".join("null" if x is None else str(x) for x in c["layouts_seen"])
            codes = ",".join(c["layout_codes_seen"])
            last = "" if c["disp"] is None else str(c["disp"])
            lines.append(
                f"{cid:<5} {c['name'][:34]:<34} {c['count']:>6}  {last[:14]:<14} "
                f"{layouts}{(' [' + codes + ']') if codes else ''}"
            )
    if inv.get("from_addresses"):
        addrs = ", ".join(
            f"{a} {v['name']} ×{v['count']}" for a, v in inv["from_addresses"].items()
        )
        lines.append("")
        lines.append(f"from: {addrs}")
    lines.append("")
    lines.append(
        "Reminder: cycle EVERY B&G display page (incl. Heading True/Magnetic, TWD, Set/Drift) "
        "during the capture so every channel and layout is broadcast."
    )
    if report.inventory_path is not None:
        lines.append(f"inventory: {report.inventory_path}")
    if report.capture_path is not None:
        lines.append(f"capture:   {report.capture_path} (replay with jabuka-replay)")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fastnet-probe",
        description=(
            "Receive-only B&G Fastnet bus probe: verdict (OK / NO BYTES / swap A/B / NOISY), "
            "channel inventory (inventory.json) and a replayable capture (capture.log). "
            "STOP the ingest first (sudo systemctl stop jabuka-ingest-fastnet): only one "
            "process may own the port."
        ),
        epilog=(
            "Exit codes: 0 ok, 2 no bytes (silent), 3 bytes but no valid frames (swap "
            "White/Green A/B), 4 noisy, 5 few bytes, 1 error / device missing. "
            "Restart the ingest afterwards: sudo systemctl start jabuka-ingest-fastnet."
        ),
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument("--device", default=None, help="serial device (default /dev/fastnet)")
    src.add_argument("--file", type=Path, default=None, help="analyse a capture file instead")
    p.add_argument(
        "--seconds",
        type=float,
        default=10.0,
        help=f"live capture duration (default 10, minimum {LIVE_MIN_SECONDS:g} on a device)",
    )
    p.add_argument("--out", type=Path, default=None, help="output dir (default ./probe-<UTC>)")
    p.add_argument("--json", action="store_true", help="print inventory.json to stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    out = args.out
    if out is None:
        out = Path(f"probe-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
    try:
        if args.file is not None:
            if not args.file.is_file():
                print(f"fastnet-probe: no such capture file: {args.file}", file=sys.stderr)
                return EXIT_ERROR
            report = run_probe(args.file, out_dir=out, file_mode=True)
        else:
            device = args.device or "/dev/fastnet"
            seconds = args.seconds
            if seconds < LIVE_MIN_SECONDS:
                print(
                    f"fastnet-probe: --seconds raised to {LIVE_MIN_SECONDS:g} "
                    "(shorter windows misjudge the bus)",
                    file=sys.stderr,
                )
                seconds = LIVE_MIN_SECONDS
            print(f"fastnet-probe: reading {device} for {seconds:g} s ...", file=sys.stderr)
            report = run_probe(device, seconds=seconds, out_dir=out, file_mode=False)
    except (OSError, ValueError) as e:
        if isinstance(e, OSError) and e.errno == errno.EPIPE:
            return EXIT_ERROR
        print(f"fastnet-probe: error: {e}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps(report.inventory, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
