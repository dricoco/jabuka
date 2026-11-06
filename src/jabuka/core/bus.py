"""UDP listener for schema-v1 datagrams from ingest / replay / sim (bound to localhost only)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from jabuka.common import messages

log = logging.getLogger("jabuka.core.bus")


class BusProtocol(asyncio.DatagramProtocol):
    """Validates each datagram with messages.decode; invalid ones are counted and dropped."""

    def __init__(
        self,
        on_message: Callable[[dict], None],
        stats: dict[str, int],
        bus_log: Any | None = None,
    ) -> None:
        self.on_message = on_message
        self.stats = stats
        self.bus_log = bus_log
        for key in ("udp_rx", "udp_rejected", "handler_errors"):
            self.stats.setdefault(key, 0)

    def datagram_received(self, data: bytes, addr: Any) -> None:
        msg = messages.decode(data)
        if msg is None:
            self.stats["udp_rejected"] += 1
            return
        self.stats["udp_rx"] += 1
        if self.bus_log is not None:
            try:
                self.bus_log.write_line(json.dumps(msg, separators=(",", ":")))
            except Exception as e:  # logging must never stop state updates
                log.warning("bus log write failed: %s", e)
        try:
            self.on_message(msg)
        except Exception:
            self.stats["handler_errors"] += 1
            log.exception("message handler failed")

    def error_received(self, exc: Exception) -> None:
        log.debug("udp error: %s", exc)


async def start_udp_listener(
    host: str,
    port: int,
    on_message: Callable[[dict], None],
    *,
    stats: dict[str, int] | None = None,
    bus_log: Any | None = None,
) -> tuple[asyncio.DatagramTransport, BusProtocol]:
    """Bind host:port (default deployment: 127.0.0.1 only) and dispatch valid messages."""
    loop = asyncio.get_running_loop()
    stats = stats if stats is not None else {}
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: BusProtocol(on_message, stats, bus_log),
        local_addr=(host, port),
    )
    return transport, protocol  # type: ignore[return-value]
