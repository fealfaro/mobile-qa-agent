"""Modelos de configuración: perfiles de app, ambientes y calibración de pantallas.

Un perfil es una carpeta `profiles/<app-id>/` (puede ser un clon del catálogo público de perfiles):
  profile.yaml                          ficha de la app (ids Android/iOS, tiendas, sesión, seguridad)
  calibration/<module>.<platform>.yaml  selectores revisados por un humano
  calibration/<module>.<platform>.draft.yaml  borrador del levantamiento (no se usa en ejecuciones)
  suites/*.yaml                         casos de prueba
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from qa_agent.core.ui import Locator

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"
TEMPLATES_DIR = ROOT / "templates"
PROFILES_DIR = Path(os.environ.get("QA_PROFILES_DIR") or ROOT / "profiles")


class LocatorCfg(BaseModel):
    strategy: Literal["id", "accessibility_id", "text", "text_contains", "xpath", "class"]
    value: str

    def to_locator(self) -> Locator:
        return Locator(self.strategy, self.value)


class AndroidAppCfg(BaseModel):
    package: str | None = None
    package_keywords: list[str] = Field(default_factory=list)
    activity: str | None = None
    authorized_builds_dir: str = "builds/android"


class IOSAppCfg(BaseModel):
    bundle_id: str | None = None
    bundle_keywords: list[str] = Field(default_factory=list)
    authorized_builds_dir: str = "builds/ios"


class SessionCfg(BaseModel):
    # existing: la cuenta de prueba ya está logueada en el dispositivo (noReset)
    # manual: el agente espera a que un operador inicie sesión (OTP, captcha, etc.)
    # credentials: el agente usa login_flow de la calibración + secretos
    mode: Literal["existing", "manual", "credentials"] = "existing"
    manual_timeout_s: int = 300
    home_timeout_s: int = 45


class SafetyCfg(BaseModel):
    deny_keywords: list[str] = Field(default_factory=list)


class StoreListing(BaseModel):
    """Ficha pública de la app en una tienda (resultado del buscador)."""

    id: str                              # applicationId (Google Play) / bundleId (App Store)
    title: str = ""
    developer: str = ""
    icon: str | None = None
    url: str | None = None
    rating: float | None = None
    track_id: str | None = None          # id numérico de App Store


class AppCfg(BaseModel):
    id: str
    name: str
    description: str = ""
    stores: dict[str, StoreListing] = Field(default_factory=dict)   # google_play / app_store
    android: AndroidAppCfg = Field(default_factory=AndroidAppCfg)
    ios: IOSAppCfg = Field(default_factory=IOSAppCfg)
    session: SessionCfg = Field(default_factory=SessionCfg)
    safety: SafetyCfg = Field(default_factory=SafetyCfg)


class EnvironmentCfg(BaseModel):
    name: str
    description: str = ""
    allow_transactions: bool = False   # el MVP exige False
    appium_url: str = "http://127.0.0.1:4723"
    new_command_timeout_s: int = 300
    capabilities: dict[str, Any] = Field(default_factory=dict)


class ScreenSignature(BaseModel):
    """Una pantalla se reconoce si coinciden al menos `min_matches` localizadores."""

    locators: list[LocatorCfg] = Field(default_factory=list)
    min_matches: int = 1
    screen_ids: list[str] = Field(default_factory=list)   # Activity Android (opcional)


class ComponentCfg(BaseModel):
    locator: LocatorCfg
    category: str = "unknown"          # header, bottom_nav, card, banner, shortcut, button...
    required: bool = True
    expected_text: str | None = None
    must_be_enabled: bool = False
    scroll_to_find: bool = False
    notes: str = ""


class NavigationTarget(BaseModel):
    """Elemento cuya pulsación fue revisada y autorizada por un humano (no transaccional)."""

    component: str
    expect: Literal["screen_change", "any_response"] = "screen_change"
    return_with: Literal["back"] = "back"
    settle_s: float = 2.5


class LoginFlowCfg(BaseModel):
    pre_taps: list[LocatorCfg] = Field(default_factory=list)
    username_field: LocatorCfg | None = None
    password_field: LocatorCfg | None = None
    submit: LocatorCfg | None = None


class OverlayCfg(BaseModel):
    """Modal/interstitial que tapa la pantalla. Se detecta por localizador o, si no está expuesto en
    accesibilidad, visualmente (región oscurecida). Se cierra con un localizador o un punto revisado."""

    name: str
    detect_locator: LocatorCfg | None = None
    detect_dim_region: list[float] | None = None   # [x, y, w, h] en fracciones de pantalla
    max_brightness: float = 180                    # brillo medio (0-255) bajo el cual se considera tapada
    dismiss_locator: LocatorCfg | None = None
    dismiss_point: list[float] | None = None       # [x, y] en fracciones de pantalla (revisado por humano)
    max_attempts: int = 3
    notes: str = ""


class Calibration(BaseModel):
    module: str
    platform: Literal["android", "ios"]
    app_version: str | None = None
    calibrated_by: str = ""
    calibrated_at: str = ""
    status: Literal["draft", "reviewed"] = "draft"
    screens: dict[str, ScreenSignature] = Field(default_factory=dict)
    components: dict[str, ComponentCfg] = Field(default_factory=dict)
    navigation_targets: list[NavigationTarget] = Field(default_factory=list)
    loading_indicators: list[LocatorCfg] = Field(default_factory=list)
    error_indicators: list[LocatorCfg] = Field(default_factory=list)
    login_flow: LoginFlowCfg = Field(default_factory=LoginFlowCfg)
    # Componente que lleva a la pantalla principal (p.ej. ítem "Inicio" del footer). Se usa si "back" no vuelve.
    home_component: str | None = None
    overlays: list[OverlayCfg] = Field(default_factory=list)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def profile_dir(app_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,80}", app_id):
        raise ValueError(f"Id de perfil inválido: {app_id!r}")
    return PROFILES_DIR / app_id


def list_profiles() -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    return sorted(p.parent.name for p in PROFILES_DIR.glob("*/profile.yaml"))


def load_app(app_id: str) -> AppCfg:
    p = profile_dir(app_id) / "profile.yaml"
    if not p.exists():
        raise FileNotFoundError(f"No existe el perfil '{app_id}' ({p})")
    return AppCfg.model_validate(_load_yaml(p))


def save_app(app: AppCfg) -> Path:
    d = profile_dir(app.id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "profile.yaml"
    data = app.model_dump(mode="json", exclude_none=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    return p


def load_environment(name: str) -> EnvironmentCfg:
    env = EnvironmentCfg.model_validate(_load_yaml(CONFIG_DIR / "environments" / f"{name}.yaml"))
    if env.allow_transactions:
        raise ValueError("El MVP no permite ambientes con allow_transactions=true")
    return env


def calibration_path(app_id: str, module: str, platform: str, draft: bool = False) -> Path:
    return profile_dir(app_id) / "calibration" / f"{module}.{platform}{'.draft' if draft else ''}.yaml"


def load_calibration(app_id: str, module: str, platform: str, draft: bool = False) -> Calibration | None:
    p = calibration_path(app_id, module, platform, draft)
    if not p.exists():
        return None
    return Calibration.model_validate(_load_yaml(p))


def suite_files(app_id: str) -> list[Path]:
    d = profile_dir(app_id) / "suites"
    return sorted(d.glob("*.y*ml")) if d.exists() else []
