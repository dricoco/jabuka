"""Bus-health verdict shared by fastnet-probe and the ingest heartbeat.

classify() turns framer counters over a window into one of STATES plus a wiring hint, in this
order (RESEARCH Pitfall 2):

- no bytes at all                    -> "silent"     (wrong terminals, adapter mode, no power)
- >= 2000 bytes but no valid frame   -> "no_frames"  (A/B swapped, or wrong serial settings)
- some bytes but no valid frame      -> "few_bytes"  (too short a window, or a bad ground)
  ("no valid frame" also covers a valid ratio below 0.1: chance checksum matches in noise)
- valid ratio below 0.9              -> "noisy"      (ground/termination)
- otherwise                          -> "ok"

"missing" (device absent) is set by the caller; classify() only judges bytes.
Random noise yields zero valid frames, so frames_ok == 0 is a strong signal.
"""

from __future__ import annotations

from collections import deque
from typing import Any

STATES = ("ok", "silent", "few_bytes", "no_frames", "noisy", "missing")

NO_FRAMES_MIN_BYTES = 2000
MIN_VALID_RATIO = 0.9
NO_FRAMES_MAX_RATIO = 0.1  # below this, the few "frames" are checksum coincidences

HINT_SILENT = "NO BYTES: wires on T/R+ T/R− (not RXD±)? adapter in RS485 mode? instruments powered?"
HINT_NO_FRAMES = "BYTES BUT NO VALID FRAMES: swap White/Green (A/B); confirm 28800 8O2"
HINT_FEW_BYTES = "FEW BYTES, NO FRAMES: run longer; check Black→GND and A/B"
HINT_NOISY = "NOISY: connect Black→GND; remove any added termination"
HINT_MISSING = "DEVICE MISSING: adapter unplugged or /dev/fastnet symlink absent"


def classify(
    bytes_in: int,
    bytes_discarded: int,
    frames_ok: int,
    window_s: float,
    n_channels: int = 0,
) -> tuple[str, str]:
    """Return (state, hint) for counters accumulated over window_s seconds."""
    if bytes_in <= 0:
        return "silent", HINT_SILENT
    valid_ratio = 1.0 - (bytes_discarded / bytes_in)
    # Two 8-bit checksums let random bytes pass as a "frame" about once per 65k bytes (a
    # byte-inverted example2 capture yields exactly 1), so near-zero framing counts as none.
    if frames_ok <= 0 or valid_ratio < NO_FRAMES_MAX_RATIO:
        if bytes_in >= NO_FRAMES_MIN_BYTES:
            return "no_frames", HINT_NO_FRAMES
        return "few_bytes", HINT_FEW_BYTES
    if valid_ratio < MIN_VALID_RATIO:
        return "noisy", HINT_NOISY
    fps = frames_ok / window_s if window_s > 0 else 0.0
    return "ok", f"OK: {fps:.1f} frames/s, {n_channels} channels"


class WindowStats:
    """Sliding window over cumulative framer counters.

    push(t, stats) records a snapshot of (bytes_in, bytes_discarded, frames_ok) at time t (any
    monotonic seconds). rates() returns the deltas between the oldest and newest snapshot within
    the last window_s seconds, plus per-second rates.
    """

    def __init__(self, window_s: float = 5.0) -> None:
        self.window_s = float(window_s)
        self._snaps: deque[tuple[float, int, int, int]] = deque()

    def push(self, t: float, stats: Any) -> None:
        snap = (float(t), int(stats.bytes_in), int(stats.bytes_discarded), int(stats.frames_ok))
        if self._snaps and snap[0] < self._snaps[-1][0]:
            self._snaps.clear()  # time went backwards: restart the window
        self._snaps.append(snap)
        cutoff = snap[0] - self.window_s
        # keep the newest snapshot at or before the cutoff as the window's baseline
        while len(self._snaps) >= 2 and self._snaps[1][0] <= cutoff:
            self._snaps.popleft()

    def reset(self) -> None:
        self._snaps.clear()

    def rates(self) -> dict[str, float]:
        if not self._snaps:
            return {
                "bytes_in": 0,
                "bytes_discarded": 0,
                "frames_ok": 0,
                "span_s": 0.0,
                "bytes_per_s": 0.0,
                "frames_per_s": 0.0,
            }
        t0, b0, d0, f0 = self._snaps[0]
        t1, b1, d1, f1 = self._snaps[-1]
        # counters can only shrink if the framer was replaced: treat that as a fresh start
        db, dd, df = max(0, b1 - b0), max(0, d1 - d0), max(0, f1 - f0)
        span = max(0.0, t1 - t0)
        return {
            "bytes_in": db,
            "bytes_discarded": dd,
            "frames_ok": df,
            "span_s": round(span, 3),
            "bytes_per_s": round(db / span, 1) if span > 0 else 0.0,
            "frames_per_s": round(df / span, 1) if span > 0 else 0.0,
        }
