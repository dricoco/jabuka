"""jabuka-replay-msgs: L1 replay of core bus logs (received datagrams) over UDP, at speed.

Each bus-log line is ``"<t_mono> <t_wall> <json>"`` (written by the core's BusProtocol). Every
message is re-sent to the core with ``t_sim`` set (kept if the message already carries one,
otherwise the line's t_wall), so a core started with ``--clock sim`` follows the recorded time.
Pacing follows the recorded t_mono differences divided by --speed; negative gaps (reboot inside
a log) and gaps over 60 s are clamped to 0 so a replay never stalls. Undecodable lines are
skipped and counted, never fatal.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

from jabuka.common import messages
from jabuka.ingest.rawlog import iter_log_lines

log = logging.getLogger("jabuka.sim.msg_replay")

MAX_GAP_S = 60.0


def _parse_line(line: str) -> tuple[float, float, dict] | None:
    parts = line.split(" ", 2)
    if len(parts) != 3:
        return None
    try:
        t_mono = float(parts[0])
        t_wall = float(parts[1])
    except ValueError:
        return None
    msg = messages.decode(parts[2].encode("utf-8", errors="replace"))
    if msg is None:
        return None
    return t_mono, t_wall, msg


async def replay_messages(
    paths: Sequence[str | Path],
    *,
    speed: float = 1.0,
    udp: tuple[str, int] = ("127.0.0.1", messages.DEFAULT_UDP_PORT),
    loop: bool = False,
) -> tuple[int, int]:
    """Replay bus logs in order. Returns (sent, skipped). speed <= 0: as fast as possible."""
    aloop = asyncio.get_running_loop()
    sent = skipped = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            t0 = aloop.time()
            virtual = 0.0  # recorded seconds elapsed (clamped gaps)
            prev_mono: float | None = None
            for path in paths:
                for line in iter_log_lines(path):
                    parsed = _parse_line(line)
                    if parsed is None:
                        skipped += 1
                        continue
                    t_mono, t_wall, msg = parsed
                    if prev_mono is not None:
                        gap = t_mono - prev_mono
                        if 0 < gap <= MAX_GAP_S:
                            virtual += gap
                    prev_mono = t_mono
                    if msg.get("t_sim") is None:
                        msg["t_sim"] = t_wall
                    try:
                        data = messages.encode(msg)
                    except (ValueError, TypeError):
                        skipped += 1
                        continue
                    if speed > 0:
                        delay = t0 + virtual / speed - aloop.time()
                        if delay > 0:
                            await asyncio.sleep(delay)
                    try:
                        sock.sendto(data, udp)
                        sent += 1
                    except OSError as e:  # core not listening / buffer full: count, go on
                        skipped += 1
                        log.debug("udp send failed: %s", e)
            if not loop:
                break
            await asyncio.sleep(0)
    finally:
        sock.close()
    return sent, skipped


def _parse_hostport(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"expected HOST:PORT, got {text!r}")
    return host, int(port)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-replay-msgs",
        description=(
            "L1 replay: re-send a core bus log (var/logs/bus/bus-*.log) over UDP at --speed, "
            "with t_sim, into a core started with --clock sim."
        ),
    )
    p.add_argument("logs", nargs="+", type=Path, metavar="LOG", help="bus log file(s), in order")
    p.add_argument("--speed", type=float, default=1.0, help="time acceleration (default 1)")
    p.add_argument(
        "--udp",
        type=_parse_hostport,
        default=("127.0.0.1", messages.DEFAULT_UDP_PORT),
        help=f"core UDP HOST:PORT (default 127.0.0.1:{messages.DEFAULT_UDP_PORT})",
    )
    p.add_argument("--loop", action="store_true", help="replay forever")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    for path in args.logs:
        if not path.is_file():
            print(f"jabuka-replay-msgs: no such log: {path}", file=sys.stderr)
            return 2
    try:
        sent, skipped = asyncio.run(
            replay_messages(args.logs, speed=args.speed, udp=args.udp, loop=args.loop)
        )
    except KeyboardInterrupt:
        return 0
    print(f"sent {sent}, skipped {skipped}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
