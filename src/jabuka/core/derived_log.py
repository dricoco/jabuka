"""1 Hz derived-state log: one JSON line per core tick with the full diag snapshot.

The writer runs on the core's injected clock (monotonic + wall), so sim replays rotate on sim time.
"""

from __future__ import annotations

from pathlib import Path

from jabuka.common.clock import Clock
from jabuka.ingest.rawlog import RotatingAppendLog


class DerivedLogger:
    def __init__(self, directory: Path, clock: Clock, **log_kwargs) -> None:
        self.clock = clock
        log_kwargs.setdefault("guard_prefixes", ())
        self.log = RotatingAppendLog(
            Path(directory),
            "derived",
            suffix=".jsonl",
            mono=clock.monotonic,
            wall=clock.wall,
            **log_kwargs,
        )

    @property
    def current_name(self) -> str | None:
        p = self.log.current_path
        return p.name if p is not None else None

    def write(self, diag: dict) -> None:
        status = diag.get("clock") or self.clock.status()
        rec = {
            "type": "derived",
            "t_mono": self.clock.monotonic(),
            "t_wall": self.clock.wall(),
            "utc": status.get("utc"),
            "clock": status,
            "values": diag.get("values", []),
            "health": diag.get("health", {}),
            "core": diag.get("core", {}),
        }
        self.log.write_json(rec)

    def maybe_flush(self) -> None:
        self.log.maybe_flush()

    def close(self) -> None:
        self.log.close()
