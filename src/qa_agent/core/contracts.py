"""Contratos (interfaces) entre capas. Las implementaciones concretas viven en sus paquetes.

Capas:
  devices/     -> DeviceProvider          (Device Management)
  execution/   -> MobileDriver            (Mobile Execution Layer)
  validation/  -> Validator               (Validation Layer)
  evidence/    -> EvidenceStore           (Evidence Layer)
  reporting/   -> Reporter                (Reporting Layer)
  intelligence/-> AIProvider              (Intelligence Layer)
  modules/*    -> TestModule              (lógica de negocio por journey: home, tienda...)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .ui import Locator


class DeviceKind(str, Enum):
    ANDROID_EMULATOR = "android_emulator"
    ANDROID_PHYSICAL = "android_physical"
    IOS_SIMULATOR = "ios_simulator"
    IOS_PHYSICAL = "ios_physical"


@dataclass
class Device:
    id: str                      # serial adb / UDID
    platform: str                # android | ios
    kind: DeviceKind
    state: str                   # device | offline | unauthorized | Booted | Shutdown ...
    model: str = ""
    os_version: str = ""
    api_level: str = ""
    screen: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.state in {"device", "Booted", "connected", "available"}


@dataclass
class InstalledApp:
    package: str                 # applicationId / bundleId
    version_name: str | None = None
    version_code: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DeviceProvider(Protocol):
    platform: str

    def is_available(self) -> tuple[bool, str]: ...
    def list_devices(self) -> list[Device]: ...
    def find_packages(self, device: Device, keywords: list[str]) -> list[str]: ...
    def app_info(self, device: Device, package: str) -> InstalledApp | None: ...
    def install(self, device: Device, build_path: Path) -> None: ...
    def device_logs(self, device: Device, since: str | None = None) -> str: ...


@runtime_checkable
class MobileDriver(Protocol):
    """Fachada mínima sobre el motor de automatización (Appium hoy; Maestro u otro mañana)."""

    platform: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def activate_app(self, app_id: str) -> None: ...
    def terminate_app(self, app_id: str) -> None: ...
    def app_state(self, app_id: str) -> int: ...
    def current_screen_id(self) -> str: ...
    def page_source(self) -> str: ...
    def screenshot(self, path: Path) -> Path: ...
    def window_size(self) -> tuple[int, int]: ...
    def find(self, locator: Locator, timeout_s: float = 0) -> Any | None: ...
    def find_all(self, locator: Locator) -> list[Any]: ...
    def tap_element(self, element: Any) -> None: ...
    def tap_point(self, x: int, y: int) -> None: ...
    def type_text(self, element: Any, text: str) -> None: ...
    def back(self) -> None: ...
    def swipe(self, direction: str, ratio: float = 0.5) -> None: ...
    def hide_keyboard(self) -> None: ...


@runtime_checkable
class AIProvider(Protocol):
    """Proveedor LLM. Solo produce texto/estructuras; nunca ejecuta acciones."""

    name: str

    def complete(self, system: str, prompt: str, images: list[Path] | None = None) -> str: ...
