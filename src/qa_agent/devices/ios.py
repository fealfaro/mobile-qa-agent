"""Gestión de dispositivos iOS: simuladores (simctl) y físicos (devicectl). Requiere Xcode completo."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from qa_agent.core.contracts import Device, DeviceKind, InstalledApp

from .toolchain import run


class IOSDeviceProvider:
    platform = "ios"

    def is_available(self) -> tuple[bool, str]:
        if not shutil.which("xcrun"):
            return False, "xcrun no encontrado"
        dev_dir = run(["xcode-select", "-p"]).stdout.strip()
        if not dev_dir.endswith("Contents/Developer"):
            return False, f"Xcode no instalado/seleccionado (developer dir actual: {dev_dir})"
        return True, dev_dir

    def list_devices(self) -> list[Device]:
        ok, _ = self.is_available()
        if not ok:
            return []
        return self._simulators() + self._physical()

    def _simulators(self) -> list[Device]:
        res = run(["xcrun", "simctl", "list", "devices", "available", "-j"], timeout=60)
        if res.returncode != 0:
            return []
        out: list[Device] = []
        for runtime, devs in json.loads(res.stdout).get("devices", {}).items():
            os_ver = runtime.rsplit(".", 1)[-1].replace("iOS-", "").replace("-", ".")
            if "iOS" not in runtime:
                continue
            for d in devs:
                out.append(Device(id=d["udid"], platform="ios", kind=DeviceKind.IOS_SIMULATOR,
                                  state=d.get("state", ""), model=d.get("name", ""), os_version=os_ver))
        return out

    def _physical(self) -> list[Device]:
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp, "devices.json")
            res = run(["xcrun", "devicectl", "list", "devices", "--json-output", str(out_json)], timeout=60)
            if res.returncode != 0 or not out_json.exists():
                return []
            data = json.loads(out_json.read_text())
        out: list[Device] = []
        for d in data.get("result", {}).get("devices", []):
            hw = d.get("hardwareProperties", {})
            props = d.get("deviceProperties", {})
            conn = d.get("connectionProperties", {})
            out.append(Device(
                id=hw.get("udid", d.get("identifier", "")), platform="ios", kind=DeviceKind.IOS_PHYSICAL,
                state="connected" if conn.get("tunnelState") == "connected" else conn.get("tunnelState", "unknown"),
                model=props.get("name", hw.get("marketingName", "")), os_version=props.get("osVersionNumber", ""),
            ))
        return out

    def find_packages(self, device: Device, keywords: list[str]) -> list[str]:
        if device.kind != DeviceKind.IOS_SIMULATOR:
            # Dispositivo físico: Appium (mobile: listApps) lo resuelve en sesión; ver docs.
            return []
        res = run(["xcrun", "simctl", "listapps", device.id], timeout=60)
        # Formato: `CFBundleIdentifier = "com.empresa.app";`
        ids = [l.split("=", 1)[1].strip().strip('";') for l in res.stdout.splitlines()
               if l.strip().startswith("CFBundleIdentifier")]
        kws = [k.lower() for k in keywords]
        return sorted({i for i in ids if any(k in i.lower() for k in kws)})

    def app_info(self, device: Device, package: str) -> InstalledApp | None:
        if device.kind == DeviceKind.IOS_SIMULATOR:
            res = run(["xcrun", "simctl", "appinfo", device.id, package], timeout=30)
            if res.returncode != 0 or "CFBundleIdentifier" not in res.stdout:
                return None
            return InstalledApp(package)
        return None

    def install(self, device: Device, build_path: Path) -> None:
        if device.kind == DeviceKind.IOS_SIMULATOR:
            res = run(["xcrun", "simctl", "install", device.id, str(build_path)], timeout=300)
        else:
            res = run(["xcrun", "devicectl", "device", "install", "app", "--device", device.id, str(build_path)], timeout=300)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip())

    def device_logs(self, device: Device, since: str | None = None) -> str:
        return "<logs iOS se capturan vía Appium (syslog) durante la sesión>"
