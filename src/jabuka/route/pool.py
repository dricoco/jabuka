"""Router worker pool: interface skeleton (RED phase, behaviour not implemented yet)."""

from __future__ import annotations

from typing import Any, NamedTuple

WORKER_START_METHOD: str | None = None


class PoolOutcome(NamedTuple):
    status: str
    value: Any
    elapsed_s: float
    error: str | None


def kill_pool(executor: Any) -> None:
    pass


class RouterPool:
    def __init__(self, init_fn: Any = None, init_args: tuple = (), **_kw: Any) -> None:
        self.stats: dict[str, Any] = {}

    def start(self) -> None:
        pass

    async def run_latest(self, fn: Any, arg: Any) -> PoolOutcome:
        return PoolOutcome("error", None, 0.0, "not implemented")

    def restart(self) -> None:
        pass

    def close(self) -> None:
        pass
