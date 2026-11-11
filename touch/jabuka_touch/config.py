"""Configuration (/etc/jabuka-touch.json) and the injectable filesystem paths.

load() never fails: missing keys keep their defaults, a wrong type or an out-of-range value is
ignored (and logged), a corrupt file gives the defaults. save() is atomic (tmp + os.replace).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger("jabuka_touch.config")

CONFIG_PATH = Path("/etc/jabuka-touch.json")


@dataclass
class TouchCfg:
    """ADS7846 calibration (goodtft rotate=90, xorg evdev semantics: swap first, then scale)."""

    x_min: float = 3936
    x_max: float = 227
    y_min: float = 268
    y_max: float = 3880
    swap_xy: bool = True
    device_name: str = "ADS7846 Touchscreen"
    debounce_s: float = 0.25


@dataclass
class DemoCfg:
    speed: float = 2.0
    shift_deg_h: float = 6.0
    start_utc: str = "2026-11-13T18:00:00+00:00"


@dataclass
class Config:
    touch: TouchCfg = field(default_factory=TouchCfg)
    fb_name: str = "fb_ili9486"
    core_url: str = "http://127.0.0.1"
    night: bool = False
    confirm_timeout_s: float = 8.0
    tap_guard_s: float = 0.6
    demo: DemoCfg = field(default_factory=DemoCfg)


@dataclass(frozen=True)
class Paths:
    """Every filesystem path the menu reads or writes (tests point them into tmp)."""

    config: Path = CONFIG_PATH
    proc_fb: Path = Path("/proc/fb")
    sys_graphics: Path = Path("/sys/class/graphics")
    dev: Path = Path("/dev")
    sys_input: Path = Path("/sys/class/input")
    dev_input: Path = Path("/dev/input")
    tty: Path = Path("/dev/tty1")
    thermal: Path = Path("/sys/class/thermal/thermal_zone0/temp")
    data_dir: Path = Path("/var/lib/jabuka")
    prerace_last: Path = Path("/var/lib/jabuka/prerace-last.txt")
    current_last: Path = Path("/var/lib/jabuka/current-last.txt")
    current_npz: Path = Path("/var/lib/jabuka/racepack/current.npz")
    demo_flag: Path = Path("/run/systemd/system/jabuka-core.service.d/zz-jabuka-touch-demo.conf")


# (min, max) of the numeric keys; None = no bound on that side
_RANGES: dict[str, tuple[float | None, float | None]] = {
    "touch.x_min": (0, 65535),
    "touch.x_max": (0, 65535),
    "touch.y_min": (0, 65535),
    "touch.y_max": (0, 65535),
    "touch.debounce_s": (0.0, 2.0),
    "confirm_timeout_s": (2.0, 60.0),
    "tap_guard_s": (0.0, 3.0),
    "demo.speed": (0.1, 20.0),
    "demo.shift_deg_h": (-30.0, 30.0),
}


def _ok_value(key: str, default: object, value: object) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        lo, hi = _RANGES.get(key, (None, None))
        v = float(value)
        if v != v:  # NaN
            return False
        return (lo is None or v >= lo) and (hi is None or v <= hi)
    if isinstance(default, str):
        if not isinstance(value, str) or not value:
            return False
        if key == "core_url":
            return value.startswith("http://") and " " not in value
        if key == "demo.start_utc":
            try:
                return datetime.fromisoformat(value).tzinfo is not None
            except ValueError:
                return False
        return True
    return False


def _merge(obj: object, data: dict, prefix: str = "") -> None:
    for f in dataclasses.fields(obj):  # type: ignore[arg-type]
        if f.name not in data:
            continue
        key = f"{prefix}{f.name}"
        cur = getattr(obj, f.name)
        val = data[f.name]
        if dataclasses.is_dataclass(cur):
            if isinstance(val, dict):
                _merge(cur, val, key + ".")
            else:
                log.warning("config : %s ignoré (objet attendu)", key)
            continue
        if _ok_value(key, cur, val):
            setattr(obj, f.name, float(val) if isinstance(cur, float) else val)
        else:
            log.warning("config : %s=%r ignoré (valeur invalide)", key, val)


def load(path: Path | str = CONFIG_PATH) -> Config:
    cfg = Config()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return cfg
    except OSError as e:
        log.warning("config : lecture de %s impossible (%s), valeurs par défaut", path, e)
        return cfg
    try:
        data = json.loads(text)
    except ValueError as e:
        log.warning("config : %s corrompu (%s), valeurs par défaut", path, e)
        return cfg
    if not isinstance(data, dict):
        log.warning("config : %s n'est pas un objet JSON, valeurs par défaut", path)
        return cfg
    _merge(cfg, data)
    if cfg.touch.x_min == cfg.touch.x_max or cfg.touch.y_min == cfg.touch.y_max:
        log.warning("config : calibration dégénérée, calibration par défaut")
        cfg.touch = TouchCfg(device_name=cfg.touch.device_name, debounce_s=cfg.touch.debounce_s)
    return cfg


def to_dict(cfg: Config) -> dict:
    return dataclasses.asdict(cfg)


def defaults_dict() -> dict:
    return to_dict(Config())


def write_json(path: Path | str, data: dict) -> None:
    """Atomic JSON write (tmp + fsync + os.replace), mode 0644."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o644)
    os.replace(tmp, p)


def save(path: Path | str, cfg: Config) -> None:
    write_json(path, to_dict(cfg))
