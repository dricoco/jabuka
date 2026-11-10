"""Phase 2 settings: one pydantic model with bounds and French labels, persisted atomically with a
version for optimistic concurrency (CRSE-05, RESEARCH Pattern 7, Security Domain V5).

<data-dir>/settings.json = {"version": int, "settings": {...}}. A torn or invalid file falls back to
NAME.bak with a "restauré" alert (04-REVIEW WR-04), then to the defaults with an "illisible"
alert. wind_manual.json follows the same rule.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from jabuka.common.atomicio import atomic_write_json, load_json_status

SETTINGS_FILE = "settings.json"
LOCAL_ISO = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"  # local wall-clock minutes, no zone


def _f(default: Any, label: str, **kw: Any) -> Any:
    return Field(default, json_schema_extra={"label": label}, **kw)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # -- TRUE boundary (WIND-03) -----------------------------------------------------------------
    variation_deg: float = _f(4.7, "Déclinaison (°E)", ge=-30.0, le=30.0)
    heading_offset_deg: float = _f(0.0, "Décalage compas (°)", ge=-30.0, le=30.0)
    heading_ref_unknown: Literal["M", "T"] = _f("M", "Cap de référence inconnue traité comme")
    heading_display: Literal["M", "T"] = _f("M", "Affichage des caps")
    true_wind_source: Literal["computed", "instrument"] = _f("computed", "Source du vent réel")
    # -- polar (WIND-01/02) ----------------------------------------------------------------------
    efficiency: float = _f(0.92, "Efficacité polaire", ge=0.5, le=1.2)
    efficiency_up: float | None = _f(None, "Efficacité au près (optionnel)", ge=0.5, le=1.2)
    efficiency_down: float | None = _f(None, "Efficacité au portant (optionnel)", ge=0.5, le=1.2)
    # heavy-weather reduction on the polar curves (helm + router), before the efficiency
    heavy_wind_start_kn: float = _f(18.0, "Vent fort : début de réduction (nds)", ge=10.0, le=35.0)
    heavy_wind_full_kn: float = _f(25.0, "Vent fort : réduction complète (nds)", ge=12.0, le=40.0)
    heavy_wind_reduction: float = _f(0.05, "Vent fort : réduction", ge=0.0, le=0.3)
    # -- laylines (NAV-01/03) --------------------------------------------------------------------
    layline_source: Literal["polar", "sailed"] = _f("polar", "Angles des lay-lines")
    use_current: bool = _f(False, "Courant sur les lay-lines")
    leeway_deg: float = _f(0.0, "Dérive (°)", ge=0.0, le=15.0)
    # -- damping ---------------------------------------------------------------------------------
    tau_helm_s: float = _f(10.0, "Amortissement barre (s)", ge=2.0, le=60.0)
    tau_layline_s: float = _f(60.0, "Amortissement lay-lines (s)", ge=10.0, le=300.0)
    # -- Jabuka magnetic zone (WIND-07) ----------------------------------------------------------
    zone_lat: float = _f(43.09153, "Zone magnétique : latitude", ge=42.0, le=45.0)
    zone_lon: float = _f(15.46054, "Zone magnétique : longitude", ge=14.0, le=17.0)
    zone_radius_nm: float = _f(3.0, "Zone magnétique : rayon (nm)", ge=0.0, le=20.0)
    # -- manual wind (WIND-04) -------------------------------------------------------------------
    manual_wind_max_age_min: float = _f(30.0, "Vent manuel périmé après (min)", ge=1.0, le=240.0)
    # -- routing (Phase 3, plan 03-05) -----------------------------------------------------------
    routing_enabled: bool = _f(True, "Routage actif")
    route_level: Literal["L0", "L1", "L2", "L3", "L4", "L5"] = _f(
        "L0", "Niveau de routage (banc Pi)"
    )
    route_cadence_min: float = _f(5.0, "Recalcul toutes les (min)", ge=2.0, le=30.0)
    tack_penalty_s: float = _f(45.0, "Pénalité de virement (s)", ge=0.0, le=180.0)
    stay_extra_min: float = _f(5.0, "On reste : marge (min)", ge=1.0, le=30.0)
    route_waves: bool = _f(True, "Vagues dans le routage")
    route_current: bool = _f(True, "Courant dans le routage")
    # -- start mode (quick 261110-cuk): the one tack cost of start mode only (O-01) -------------
    start_tack_s: float = _f(10.0, "Départ : durée d'un virement (s)", ge=0.0, le=60.0)
    # -- GRIB wind (WIND-05/06) ------------------------------------------------------------------
    grib_wind_fallback: bool = _f(True, "Vent GRIB sans instruments")
    bias_enabled: bool = _f(True, "Correction du GRIB (biais)")
    bias_tau_decay_h: float = _f(2.5, "Biais : décroissance (h)", ge=0.5, le=12.0)
    # -- race window for the weather coverage check (local time, Europe/Zagreb) -----------------
    race_start_local: str = _f("2026-11-13T18:00", "Fenêtre météo : début", pattern=LOCAL_ISO)
    race_end_local: str = _f("2026-11-15T10:00", "Fenêtre météo : fin", pattern=LOCAL_ISO)

    @field_validator("race_start_local", "race_end_local")
    @classmethod
    def _local_iso(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"date locale invalide : {v}") from exc
        return v

    @model_validator(mode="after")
    def _window_order(self) -> Settings:
        if datetime.fromisoformat(self.race_end_local) <= datetime.fromisoformat(
            self.race_start_local
        ):
            raise ValueError("fenêtre météo : la fin doit suivre le début")
        return self

    @model_validator(mode="after")
    def _heavy_wind_order(self) -> Settings:
        if self.heavy_wind_full_kn <= self.heavy_wind_start_kn:
            raise ValueError("vent fort : la réduction complète doit suivre le début")
        return self

    def eff_up(self) -> float:
        return self.efficiency_up if self.efficiency_up is not None else self.efficiency

    def eff_down(self) -> float:
        return self.efficiency_down if self.efficiency_down is not None else self.efficiency


class VersionConflict(Exception):
    """A write was based on a stale version (HTTP 409). Carries the current state."""

    def __init__(self, version: int, current: Any) -> None:
        super().__init__(f"stale base_version (current {version})")
        self.version = version
        self.current = current


def _parse_settings_file(raw: Any) -> tuple[Settings, int]:
    """settings.json content -> (settings, version). Raises ValueError (pydantic ValidationError
    included) when invalid: load_json_status then tries NAME.bak."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    settings = Settings.model_validate(raw.get("settings", {}))
    v = raw.get("version", 0)
    return settings, (v if isinstance(v, int) and not isinstance(v, bool) else 0)


class SettingsStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / SETTINGS_FILE
        self.alerts: list[str] = []
        parsed, source = load_json_status(self.path, None, validate=_parse_settings_file)
        self.version = 0
        self.settings = Settings()
        if parsed is not None:  # "main" or "bak"
            self.settings, self.version = parsed
        if source == "bak":  # older settings may come back: never silent (04-REVIEW WR-04)
            self.alerts.append("Réglages restaurés depuis la sauvegarde : vérifier les réglages")
        elif source == "unreadable":  # present but neither NAME nor NAME.bak valid (04-01 soak)
            self.alerts.append("Réglages illisibles : valeurs par défaut")

    def to_api(self) -> dict:
        return {"version": self.version, "settings": self.settings.model_dump()}

    def update(self, patch: dict[str, Any], base_version: int | None) -> dict:
        """Apply a partial update. Raises VersionConflict (stale base_version) or
        pydantic.ValidationError (out of bounds / unknown key); nothing is written then."""
        if base_version is not None and base_version != self.version:
            raise VersionConflict(self.version, self.to_api())
        merged = self.settings.model_dump() | dict(patch)
        new = Settings.model_validate(merged)
        self._save(new, self.version + 1)
        return self.to_api()

    def _save(self, settings: Settings, version: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, {"version": version, "settings": settings.model_dump()})
        self.settings = settings
        self.version = version

    @staticmethod
    def schema() -> dict:
        return Settings.model_json_schema()


# -- manual wind (WIND-04) -----------------------------------------------------------------------
MANUAL_WIND_FILE = "wind_manual.json"


class ManualWind(BaseModel):
    """One manual wind entry, already TRUE (converted once, at entry time, Pitfall 6).

    twd_entered/ref_entered keep what the helmsman typed (B&G display, often °M) for the log and
    the form; twd_t_deg is what the pipeline uses. t_set_wall is the trusted (GPS) UTC epoch at
    entry, so the age survives a core restart; None when the clock was not synced (age unknown,
    never computed from the system clock, WR-03)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    twd_t_deg: float = Field(ge=0.0, lt=360.0)
    tws_kn: float = Field(ge=0.0, le=80.0)
    ref_entered: Literal["M", "T"]
    twd_entered: float = Field(ge=0.0, lt=360.0)
    t_set_wall: float | None = None


def _parse_manual_file(raw: Any) -> ManualWind | None:
    """wind_manual.json content -> the entry, None when cleared ({}). Raises ValueError (pydantic
    ValidationError included) when invalid: load_json_status then tries NAME.bak."""
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    return ManualWind.model_validate(raw)


class ManualWindStore:
    """<data-dir>/wind_manual.json: the stored manual wind ({} when cleared). Sticky until cleared:
    live instrument wind outranks it without deleting it (next outage reuses it)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / MANUAL_WIND_FILE
        self.alerts: list[str] = []
        self.entry: ManualWind | None = None
        # bumps on every set/clear: observers key on it, never on t_set_wall, which is None
        # without trusted GPS time (03-REVIEW LO-01)
        self.version = 0
        self.entry, source = load_json_status(self.path, None, validate=_parse_manual_file)
        if source == "bak":  # an older wind may come back: never silent (04-REVIEW WR-04)
            self.alerts.append("Vent manuel restauré depuis la sauvegarde : vérifier le vent")
        elif source == "unreadable":  # present but neither NAME nor NAME.bak valid (04-01 soak)
            self.alerts.append("Vent manuel illisible : ignoré")

    def set(
        self, twd: float, tws_kn: float, ref: str, variation_deg: float, t_wall: float | None
    ) -> ManualWind:
        """Store an entry. A °M direction becomes TRUE with the variation in force now.
        Raises pydantic.ValidationError (bad values) or OSError (disk); nothing changes then."""
        twd_t = (twd + variation_deg) % 360.0 if ref == "M" else twd % 360.0
        if twd_t >= 360.0:  # -tiny % 360 rounds to 360
            twd_t = 0.0
        entry = ManualWind(
            twd_t_deg=round(twd_t, 3),
            tws_kn=tws_kn,
            ref_entered=ref,
            twd_entered=twd,
            t_set_wall=t_wall,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, entry.model_dump())
        self.entry = entry
        self.version += 1
        return entry

    def clear(self) -> None:
        """Forget the entry (an empty record is written atomically)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, {})
        self.entry = None
        self.version += 1

    def to_api(self) -> dict | None:
        return self.entry.model_dump() if self.entry is not None else None
