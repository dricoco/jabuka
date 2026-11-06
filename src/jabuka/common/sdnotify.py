"""systemd notify protocol without libsystemd (sd_notify(3) "standalone implementations").

notify("READY=1") after startup, watchdog_loop() pings WATCHDOG=1 from inside the event loop (a
blocked loop stops the pings and systemd restarts the service), notify("STOPPING=1") on shutdown.
Outside systemd (laptop, tests) NOTIFY_SOCKET is unset and everything is a no-op.
"""

from __future__ import annotations

import asyncio
import os
import socket


def notify(state: str) -> bool:
    """Send state to $NOTIFY_SOCKET. Returns True if sent; never raises."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr[0] == "@":
        addr = "\0" + addr[1:]  # Linux abstract namespace
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
            s.connect(addr)
            s.sendall(state.encode())
        return True
    except (OSError, ValueError, UnicodeError):
        return False


def watchdog_interval() -> float | None:
    """Ping interval in seconds: WATCHDOG_USEC / 2, or None when no watchdog is configured."""
    raw = os.environ.get("WATCHDOG_USEC")
    if not raw:
        return None
    try:
        usec = int(raw)
    except ValueError:
        return None
    if usec <= 0:
        return None
    pid = os.environ.get("WATCHDOG_PID")
    if pid and pid != str(os.getpid()):
        return None  # the watchdog belongs to another process (e.g. our parent)
    return usec / 2e6


async def watchdog_loop(interval: float) -> None:
    """Send WATCHDOG=1 now and then every interval seconds until cancelled."""
    while True:
        notify("WATCHDOG=1")
        await asyncio.sleep(interval)
