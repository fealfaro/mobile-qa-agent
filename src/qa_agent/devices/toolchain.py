"""Detección del toolchain (Java, Android SDK, Appium, Xcode) y preparación del entorno."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_JAVA_CANDIDATES = [
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home",
    "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
    "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home",
]
_SDK_CANDIDATES = [
    "/opt/homebrew/share/android-commandlinetools",
    str(Path.home() / "Library/Android/sdk"),
]


def prepare_env() -> None:
    """Completa JAVA_HOME / ANDROID_HOME si no están definidos y hay una instalación conocida."""
    if not os.environ.get("JAVA_HOME"):
        for c in _JAVA_CANDIDATES:
            if Path(c, "bin/java").exists():
                os.environ["JAVA_HOME"] = c
                break
    if not (os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")):
        for c in _SDK_CANDIDATES:
            if Path(c, "platform-tools/adb").exists():
                os.environ["ANDROID_HOME"] = c
                break
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        os.environ.setdefault("ANDROID_SDK_ROOT", sdk)
        pt = str(Path(sdk, "platform-tools"))
        if pt not in os.environ.get("PATH", ""):
            os.environ["PATH"] = pt + os.pathsep + os.environ.get("PATH", "")


def adb_path() -> str | None:
    prepare_env()
    return shutil.which("adb")


def run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required_for: str
    fix: str = ""


def doctor() -> list[Check]:
    prepare_env()
    checks: list[Check] = []

    jh = os.environ.get("JAVA_HOME", "")
    checks.append(Check("JAVA_HOME", bool(jh and Path(jh, "bin/java").exists()), jh or "no definido",
                        "android", "brew install openjdk@21"))
    sdk = os.environ.get("ANDROID_HOME", "")
    checks.append(Check("ANDROID_HOME", bool(sdk), sdk or "no definido", "android",
                        "brew install --cask android-commandlinetools && sdkmanager platform-tools 'build-tools;35.0.0'"))
    adb = shutil.which("adb")
    checks.append(Check("adb", bool(adb), adb or "no encontrado", "android", "sdkmanager platform-tools"))
    emu = Path(sdk, "emulator/emulator").exists() if sdk else False
    checks.append(Check("android emulator", emu, "instalado" if emu else "no instalado (opcional si hay dispositivo físico)",
                        "android-emulator", "sdkmanager emulator 'system-images;android-35;google_apis_playstore;arm64-v8a'"))

    appium = shutil.which("appium")
    ver = run([appium, "--version"]).stdout.strip() if appium else ""
    checks.append(Check("appium", bool(appium), ver or "no encontrado", "android+ios", "npm install -g appium"))
    drivers = run([appium, "driver", "list", "--installed", "--json"], timeout=60).stdout if appium else ""
    checks.append(Check("appium uiautomator2", "uiautomator2" in drivers, "instalado" if "uiautomator2" in drivers else "falta",
                        "android", "appium driver install uiautomator2"))
    checks.append(Check("appium xcuitest", "xcuitest" in drivers, "instalado" if "xcuitest" in drivers else "falta",
                        "ios", "appium driver install xcuitest"))

    dev_dir = run(["xcode-select", "-p"]).stdout.strip() if shutil.which("xcode-select") else ""
    xcode_ok = dev_dir.endswith("Contents/Developer")
    checks.append(Check("Xcode", xcode_ok, dev_dir or "no encontrado", "ios",
                        "Instalar Xcode (App Store) y: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"))
    return checks
