"""Adaptadores Appium (Android UiAutomator2 / iOS XCUITest) que implementan MobileDriver.

Toda la lógica específica de plataforma del motor de automatización vive aquí.
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from qa_agent.core.contracts import Device, DeviceKind
from qa_agent.core.ui import Locator
from qa_agent.security.secrets import env

log = logging.getLogger("qa_agent")


def _q(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


class AppiumMobileDriver:
    """Base común. Las subclases definen capabilities y gestos propios de la plataforma."""

    platform = ""

    def __init__(self, url: str, device: Device, app_id: str, extra_caps: dict[str, Any] | None = None,
                 new_command_timeout_s: int = 300) -> None:
        self.url = url
        self.device = device
        self.app_id = app_id
        self.extra_caps = extra_caps or {}
        self.new_command_timeout_s = new_command_timeout_s
        self.d: webdriver.Remote | None = None

    # --- ciclo de vida -------------------------------------------------
    def _options(self):  # pragma: no cover - abstracto
        raise NotImplementedError

    def start(self) -> None:
        opts = self._options()
        log.info("Creando sesión Appium (%s) en %s", self.platform, self.device.id)
        self.d = webdriver.Remote(self.url, options=opts)
        self.d.implicitly_wait(0)

    def stop(self) -> None:
        if self.d:
            try:
                self.d.quit()
            except WebDriverException:
                pass
            self.d = None

    @property
    def drv(self) -> webdriver.Remote:
        if not self.d:
            raise RuntimeError("Sesión Appium no iniciada")
        return self.d

    # --- app -------------------------------------------------------------
    def activate_app(self, app_id: str) -> None:
        self.drv.activate_app(app_id)

    def terminate_app(self, app_id: str) -> None:
        self.drv.terminate_app(app_id)

    def app_state(self, app_id: str) -> int:
        """0 no instalada, 1 no corriendo, 2 bg suspendida, 3 background, 4 foreground."""
        return int(self.drv.query_app_state(app_id))

    def current_screen_id(self) -> str:
        return ""

    # --- inspección ------------------------------------------------------
    def page_source(self) -> str:
        return self.drv.page_source

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.drv.get_screenshot_as_file(str(path))
        return path

    def window_size(self) -> tuple[int, int]:
        s = self.drv.get_window_size()
        return int(s["width"]), int(s["height"])

    # --- búsqueda --------------------------------------------------------
    def _by(self, loc: Locator) -> tuple[str, str]:  # pragma: no cover - abstracto
        raise NotImplementedError

    def find(self, locator: Locator, timeout_s: float = 0) -> Any | None:
        by, val = self._by(locator)
        deadline = time.time() + timeout_s
        while True:
            try:
                return self.drv.find_element(by, val)
            except NoSuchElementException:
                if time.time() >= deadline:
                    return None
                time.sleep(0.5)

    def find_all(self, locator: Locator) -> list[Any]:
        by, val = self._by(locator)
        return list(self.drv.find_elements(by, val))

    # --- interacción -----------------------------------------------------
    def tap_element(self, element: Any) -> None:
        element.click()

    def type_text(self, element: Any, text: str) -> None:
        element.clear()
        element.send_keys(text)

    def hide_keyboard(self) -> None:
        try:
            self.drv.hide_keyboard()
        except WebDriverException:
            pass


class AndroidAppiumDriver(AppiumMobileDriver):
    platform = "android"

    def _options(self) -> UiAutomator2Options:
        o = UiAutomator2Options()
        o.platform_name = "Android"
        o.automation_name = "UiAutomator2"
        o.udid = self.device.id
        o.app_package = self.app_id
        o.no_reset = True                    # nunca borrar datos/sesión de la cuenta de prueba
        o.full_reset = False
        o.auto_grant_permissions = False
        o.new_command_timeout = self.new_command_timeout_s
        o.set_capability("appium:forceAppLaunch", False)
        o.set_capability("appium:autoLaunch", False)
        o.set_capability("appium:disableWindowAnimation", True)
        o.set_capability("appium:ignoreHiddenApiPolicyError", True)
        o.set_capability("appium:settings[ignoreUnimportantViews]", False)
        o.set_capability("appium:uiautomator2ServerInstallTimeout", 120000)
        for k, v in self.extra_caps.items():
            o.set_capability(k, v)
        return o

    def current_screen_id(self) -> str:
        try:
            return self.drv.current_activity or ""
        except WebDriverException:
            return ""

    def screenshot(self, path: Path) -> Path:
        """Appium primero; si falla (pantalla bloqueada momentánea, error transitorio), adb screencap."""
        try:
            return super().screenshot(path)
        except WebDriverException as e:
            from qa_agent.devices.toolchain import adb_path

            log.warning("Screenshot Appium falló (%s); usando adb screencap", (e.msg or str(e))[:120])
            adb = adb_path()
            if not adb:
                raise
            with path.open("wb") as f:
                res = subprocess.run([adb, "-s", self.device.id, "exec-out", "screencap", "-p"],
                                     stdout=f, stderr=subprocess.PIPE, timeout=30)
            if res.returncode != 0 or path.stat().st_size < 1000:
                raise RuntimeError(f"No se pudo capturar pantalla (Appium y adb): {res.stderr.decode()[:200]}") from e
            return path

    def _by(self, loc: Locator) -> tuple[str, str]:
        s, v = loc.strategy, loc.value
        if s == "id":
            if ":id/" in v:
                return AppiumBy.ID, v
            # Ids de contenido WebView/híbrido (p.ej. "b7-Accesso") no llevan prefijo de package.
            return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().resourceId("{_q(v)}")'
        if s == "accessibility_id":
            return AppiumBy.ACCESSIBILITY_ID, v
        if s == "text":
            return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{_q(v)}")'
        if s == "text_contains":
            return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{_q(v)}")'
        if s == "class":
            return AppiumBy.CLASS_NAME, v
        if s == "xpath":
            return AppiumBy.XPATH, v
        raise ValueError(f"Estrategia no soportada: {s}")

    def tap_point(self, x: int, y: int) -> None:
        self.drv.execute_script("mobile: clickGesture", {"x": x, "y": y})

    def back(self) -> None:
        self.drv.back()

    def swipe(self, direction: str, ratio: float = 0.5) -> None:
        w, h = self.window_size()
        # Área central para no disparar gestos de sistema ni barras fijas.
        self.drv.execute_script("mobile: swipeGesture", {
            "left": int(w * 0.1), "top": int(h * 0.25), "width": int(w * 0.8), "height": int(h * 0.5),
            "direction": direction, "percent": ratio,
        })


class IOSAppiumDriver(AppiumMobileDriver):
    platform = "ios"

    def _options(self) -> XCUITestOptions:
        o = XCUITestOptions()
        o.platform_name = "iOS"
        o.automation_name = "XCUITest"
        o.udid = self.device.id
        o.bundle_id = self.app_id
        o.no_reset = True
        o.full_reset = False
        o.new_command_timeout = self.new_command_timeout_s
        o.set_capability("appium:autoLaunch", False)
        if self.device.kind == DeviceKind.IOS_PHYSICAL:
            o.set_capability("appium:xcodeOrgId", env("IOS_XCODE_ORG_ID", ""))
            o.set_capability("appium:xcodeSigningId", env("IOS_XCODE_SIGNING_ID", "iPhone Developer"))
            if env("IOS_WDA_BUNDLE_ID"):
                o.set_capability("appium:updatedWDABundleId", env("IOS_WDA_BUNDLE_ID"))
        for k, v in self.extra_caps.items():
            o.set_capability(k, v)
        return o

    def _by(self, loc: Locator) -> tuple[str, str]:
        s, v = loc.strategy, loc.value
        if s in ("id", "accessibility_id"):
            return AppiumBy.ACCESSIBILITY_ID, v
        if s == "text":
            return AppiumBy.IOS_PREDICATE, f'label == "{_q(v)}" OR value == "{_q(v)}"'
        if s == "text_contains":
            return AppiumBy.IOS_PREDICATE, f'label CONTAINS "{_q(v)}" OR value CONTAINS "{_q(v)}"'
        if s == "class":
            return AppiumBy.CLASS_NAME, v
        if s == "xpath":
            return AppiumBy.XPATH, v
        raise ValueError(f"Estrategia no soportada: {s}")

    def tap_point(self, x: int, y: int) -> None:
        self.drv.execute_script("mobile: tap", {"x": x, "y": y})

    def back(self) -> None:
        # iOS no tiene botón "atrás" de sistema: usar el primer botón de la barra de navegación.
        btn = self.find(Locator("xpath", "//XCUIElementTypeNavigationBar/XCUIElementTypeButton[1]"))
        if btn is None:
            raise RuntimeError("No se encontró botón de retroceso en la NavigationBar")
        btn.click()

    def swipe(self, direction: str, ratio: float = 0.5) -> None:
        self.drv.execute_script("mobile: swipe", {"direction": direction})


def create_driver(platform: str, url: str, device: Device, app_id: str, **kw: Any) -> AppiumMobileDriver:
    if platform == "android":
        return AndroidAppiumDriver(url, device, app_id, **kw)
    if platform == "ios":
        return IOSAppiumDriver(url, device, app_id, **kw)
    raise ValueError(platform)
