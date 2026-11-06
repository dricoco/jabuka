"""DWD open data (https://opendata.dwd.de): listings, run selection, parallel download.

ICON-EU 10 m wind and EWAM waves (RESEARCH "Data Sources"). Each ``{HH}/`` directory holds only
the latest run(s) of that hour and a run's files appear progressively over ~50 min, so a run is
usable only when every step the race window needs is listed (Pitfall 5).

Downloads: https only, host opendata.dwd.de only, <= 6 concurrent requests, 60 s timeout,
3 attempts with backoff, 50 MB per file, bz2 integrity verified by full decompression (100 MB
output cap), atomic writes into the cache; cached files that verify are not downloaded again.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jabuka.prep.grib import bz2_decompress_capped

BASE = "https://opendata.dwd.de/weather"
ICON_EU_DIR = BASE + "/nwp/icon-eu/grib/{hh:02d}/{var}/"
ICON_EU_FILE = "icon-eu_europe_regular-lat-lon_single-level_{run}_{step:03d}_{VAR}.grib2.bz2"
EWAM_DIR = BASE + "/maritime/wave_models/ewam/grib/{hh:02d}/{var}/"
EWAM_FILE = "EWAM_{VAR}_{run}_{step:03d}.grib2.bz2"

ALLOWED_HOSTS = ("opendata.dwd.de",)
MAX_WORKERS = 6
TIMEOUT_S = 60
ATTEMPTS = 3
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

ICON_VARS = ("u_10m", "v_10m")
EWAM_VARS = ("swh", "mwd")
ICON_RUN_HOURS = tuple(range(0, 24, 3))
EWAM_RUN_HOURS = (0, 12)


def icon_listing_pattern(var: str) -> str:
    return (
        r"icon-eu_europe_regular-lat-lon_single-level_(?P<run>\d{10})_(?P<step>\d{3})_"
        + re.escape(var.upper())
        + r"\.grib2\.bz2"
    )


def ewam_listing_pattern(var: str) -> str:
    return r"EWAM_" + re.escape(var.upper()) + r"_(?P<run>\d{10})_(?P<step>\d{3})\.grib2\.bz2"


def model_steps(model: str, run_hour: int) -> list[int]:
    """Published forecast steps (hours) of a run."""
    if model == "ICON-EU":
        if run_hour % 6 == 0:
            return list(range(0, 79)) + list(range(81, 121, 3))
        return list(range(0, 52))
    if model == "EWAM":
        return list(range(0, 79))
    raise ValueError(f"modèle inconnu : {model}")


def _run_dt(run: str) -> datetime:
    return datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=UTC)


def parse_listing(html: str, pattern: str) -> dict[datetime, set[int]]:
    """Directory listing HTML -> {run time (UTC): {steps}} (regex on file names, no HTML parser)."""
    out: dict[datetime, set[int]] = {}
    for m in re.finditer(r'href="(' + pattern + r')"', html):
        out.setdefault(_run_dt(m.group("run")), set()).add(int(m.group("step")))
    return out


def missing_steps(model: str, run: datetime, steps: Iterable[int]) -> list[int]:
    """Steps of the model schedule not (yet) present for this run."""
    have = set(steps)
    return [s for s in model_steps(model, run.hour) if s not in have]


def merge_listings(*listings: Mapping[datetime, set[int]]) -> dict[datetime, set[int]]:
    out: dict[datetime, set[int]] = {}
    for lst in listings:
        for run, steps in lst.items():
            out.setdefault(run, set()).update(steps)
    return out


def needed_steps(model: str, run: datetime, start_utc: int, end_utc: int) -> list[int]:
    """Schedule steps bracketing [start, end]: the step at/before start .. the one at/after end."""
    sched = model_steps(model, run.hour)
    r = int(run.timestamp())
    lo_h = (start_utc - r) / 3600.0
    hi_h = (end_utc - r) / 3600.0
    if hi_h < 0 or lo_h > sched[-1]:
        return []
    lo = max([s for s in sched if s <= lo_h], default=sched[0])
    hi = min([s for s in sched if s >= hi_h], default=sched[-1])
    return [s for s in sched if lo <= s <= hi]


@dataclass
class RunChoice:
    run: datetime
    steps: list[int]
    incomplete: bool  # True: the run does not cover the window (benchmark pack, loud warning)
    reason: str = ""
    skipped: list[str] = field(default_factory=list)


def select_run(
    listings: Mapping[str, Mapping[datetime, set[int]]],
    window: Any,
    now: int,
    model: str,
    *,
    fallback_hours: int = 48,
) -> RunChoice | None:
    """Choose the run to download.

    ``listings`` maps each variable (u_10m and v_10m, or swh [and mwd]) to {run: steps}.
    1. Newest run (<= now) with run <= window start, run + last step >= window end, and every
       needed step listed for every variable.
    2. Else the newest run whose whole schedule is published for every variable, flagged
       incomplete (steps: the part of the window it covers, else the first ``fallback_hours``).
    """
    variables = list(listings)
    runs = sorted({r for lst in listings.values() for r in lst}, reverse=True)
    runs = [r for r in runs if int(r.timestamp()) <= now]
    skipped: list[str] = []
    for run in runs:
        sched = model_steps(model, run.hour)
        r = int(run.timestamp())
        if r > window.start_utc or r + sched[-1] * 3600 < window.end_utc:
            continue
        need = needed_steps(model, run, window.start_utc, window.end_utc)
        lacking = {v: sorted(set(need) - set(listings[v].get(run, set()))) for v in variables}
        lacking = {v: s for v, s in lacking.items() if s}
        if not lacking:
            return RunChoice(run=run, steps=need, incomplete=False, skipped=skipped)
        detail = ", ".join(f"{v} +{s[0]}..+{s[-1]} ({len(s)})" for v, s in lacking.items())
        skipped.append(f"run {run:%d/%m %HZ} incomplet : manque {detail}")
    for run in runs:
        if any(missing_steps(model, run, listings[v].get(run, set())) for v in variables):
            continue
        sched = model_steps(model, run.hour)
        steps = needed_steps(model, run, window.start_utc, window.end_utc)
        if not steps:
            steps = [s for s in sched if s <= fallback_hours]
        return RunChoice(
            run=run,
            steps=steps,
            incomplete=True,
            skipped=skipped,
            reason="aucun run complet ne couvre la fenêtre de course",
        )
    return None


def _run_str(run: datetime) -> str:
    return run.strftime("%Y%m%d%H")


def icon_eu_urls(run: datetime, steps: Iterable[int], var: str) -> list[str]:
    if var not in ICON_VARS:
        raise ValueError(f"variable ICON-EU inconnue : {var}")
    base = ICON_EU_DIR.format(hh=run.hour, var=var)
    return [base + ICON_EU_FILE.format(run=_run_str(run), step=s, VAR=var.upper()) for s in steps]


def ewam_urls(run: datetime, steps: Iterable[int], var: str) -> list[str]:
    if var not in EWAM_VARS:
        raise ValueError(f"variable EWAM inconnue : {var}")
    base = EWAM_DIR.format(hh=run.hour, var=var)
    return [base + EWAM_FILE.format(run=_run_str(run), step=s, VAR=var.upper()) for s in steps]


def icon_listing_urls(var: str) -> list[str]:
    return [ICON_EU_DIR.format(hh=h, var=var) for h in ICON_RUN_HOURS]


def ewam_listing_urls(var: str) -> list[str]:
    return [EWAM_DIR.format(hh=h, var=var) for h in EWAM_RUN_HOURS]


# --------------------------------------------------------------------------- download

Opener = Callable[..., Any]
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def check_host(url: str) -> None:
    """ValueError unless the URL is https on an allowed host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"URL refusée (https obligatoire) : {url}")
    if parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"URL refusée (hôte non autorisé) : {url}")


def check_url(url: str) -> str:
    """Return the cache file name for an allowed file URL; ValueError otherwise."""
    check_host(url)
    parts = urlsplit(url)
    name = parts.path.rsplit("/", 1)[-1]
    if not _SAFE_NAME.match(name) or name in (".", ".."):
        raise ValueError(f"nom de fichier refusé : {url}")
    return name


def _read_capped(resp: Any, cap: int) -> bytes:
    buf = bytearray()
    while True:
        chunk = resp.read(min(1 << 20, cap + 1 - len(buf)))
        if not chunk:
            break
        buf += chunk
        if len(buf) > cap:
            raise ValueError(f"téléchargement trop gros (> {cap / 1e6:.0f} Mo)")
    return bytes(buf)


def _verify(data: bytes) -> None:
    bz2_decompress_capped(data)


def _cached_ok(path: Path) -> bool:
    try:
        _verify(path.read_bytes())
        return True
    except (OSError, ValueError):
        return False


def _atomic_cache_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class DownloadResult:
    paths: list[Path]
    downloaded_bytes: int = 0
    downloaded: int = 0
    cached: int = 0


def _fetch_listing(url: str, opener: Opener, timeout: float) -> str:
    check_host(url)
    with opener(url, timeout=timeout) as resp:
        return _read_capped(resp, 5 * 1024 * 1024).decode("utf-8", "replace")


def fetch_listings(
    urls: Sequence[str], opener: Opener = urllib.request.urlopen, timeout: float = TIMEOUT_S
) -> dict[str, str]:
    """{url: html}; a directory that cannot be listed maps to '' (its runs are just ignored)."""
    out: dict[str, str] = {}
    for url in urls:
        try:
            out[url] = _fetch_listing(url, opener, timeout)
        except ValueError:
            raise
        except Exception:  # noqa: BLE001 - network errors: the directory is skipped
            out[url] = ""
    return out


def download_all(
    urls: Sequence[str],
    cache_dir: str | Path,
    opener: Opener = urllib.request.urlopen,
    *,
    max_workers: int = MAX_WORKERS,
    timeout: float = TIMEOUT_S,
    attempts: int = ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> DownloadResult:
    """Download every URL into ``cache_dir`` (skipping cached files that verify)."""
    names = [check_url(u) for u in urls]  # refuse everything before the first request
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    res = DownloadResult(paths=[cache / n for n in names])
    errors: list[str] = []

    def one(url: str, path: Path) -> None:
        if path.exists() and _cached_ok(path):
            with lock:
                res.cached += 1
            return
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                with opener(url, timeout=timeout) as resp:
                    data = _read_capped(resp, MAX_DOWNLOAD_BYTES)
                _verify(data)
                _atomic_cache_write(path, data)
                with lock:
                    res.downloaded += 1
                    res.downloaded_bytes += len(data)
                return
            except Exception as exc:  # noqa: BLE001 - retried, then reported
                last = exc
                if attempt + 1 < attempts:
                    sleep(2.0**attempt)
        with lock:
            errors.append(f"{path.name} : {type(last).__name__}: {last}")

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, MAX_WORKERS))) as ex:
        list(ex.map(one, urls, res.paths))
    if errors:
        raise RuntimeError(f"{len(errors)} téléchargement(s) en échec : " + "; ".join(errors[:5]))
    return res
