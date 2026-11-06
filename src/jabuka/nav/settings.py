"""Phase 2 settings: one pydantic model with bounds and French labels, persisted atomically with a
version for optimistic concurrency (CRSE-05, RESEARCH Pattern 7, Security Domain V5).

<data-dir>/settings.json = {"version": int, "settings": {...}}. A torn or invalid file falls back to
NAME.bak, then to the defaults with an alert string.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jabuka.common.atomicio import atomic_write_json, load_json_with_bak

SETTINGS_FILE = "settings.json"


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


class SettingsStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / SETTINGS_FILE
        self.alerts: list[str] = []
        raw = load_json_with_bak(self.path, None)
        self.version = 0
        self.settings = Settings()
        if raw is not None:
            try:
                if not isinstance(raw, dict):
                    raise ValueError("not an object")
                self.settings = Settings.model_validate(raw.get("settings", {}))
                v = raw.get("version", 0)
                self.version = v if isinstance(v, int) and not isinstance(v, bool) else 0
            except (ValidationError, ValueError):
                self.alerts.append("Réglages illisibles : valeurs par défaut")
                self.settings = Settings()

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
