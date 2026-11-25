"""Gestión de dispositivos Android vía adb (emuladores y físicos)."""
from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path

from qa_agent.core.contracts import Device, DeviceKind, InstalledApp

from .toolchain import adb_path, run


def _aapt() -> str | None:
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        return None
    found = sorted(Path(sdk, "build-tools").glob("*/aapt"))
    return str(found[-1]) if found else None


def _extract_icon(apk: Path, badging: str, out_dir: Path) -> Path | None:
    """Ícono de mayor densidad en formato bitmap. Los adaptive icons (.xml) se resuelven buscando el PNG/WebP
    de launcher más grande dentro del APK."""
    cands = re.findall(r"application-icon-(\d+):'([^']+)'", badging)
    cands.sort(key=lambda c: int(c[0]), reverse=True)
    with zipfile.ZipFile(apk) as z:
        infos = {i.filename: i for i in z.infolist()}
        listed = [infos[p] for _, p in cands if p in infos and p.endswith((".png", ".webp"))]
        # Mismo nombre de archivo que el ícono declarado, en cualquier densidad (mipmap-xxxhdpi, etc.).
        stems = {Path(i.filename).name for i in listed}
        same = [i for n, i in infos.items() if n.startswith("res/") and Path(n).name in stems]
        named = [i for n, i in infos.items() if n.startswith("res/") and n.endswith((".png", ".webp"))
                 and re.search(r"ic_launcher(?!_(foreground|background|monochrome))", n.lower())]
        pool = listed + same + named
        pick = max(pool, key=lambda i: i.file_size).filename if pool else None
        if not pick:
            return None
        dst = out_dir / ("icon" + Path(pick).suffix)
        dst.write_bytes(z.read(pick))
        return dst


class AndroidDeviceProvider:
    platform = "android"

    def __init__(self) -> None:
        self.adb = adb_path()

    def is_available(self) -> tuple[bool, str]:
        if not self.adb:
            return False, "adb no encontrado (instalar Android platform-tools y definir ANDROID_HOME)"
        return True, self.adb

    def _adb(self, serial: str | None, *args: str, timeout: float = 30) -> str:
        if not self.adb:
            raise RuntimeError("adb no disponible")
        cmd = [self.adb] + (["-s", serial] if serial else []) + list(args)
        res = run(cmd, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} falló: {res.stderr.strip() or res.stdout.strip()}")
        return res.stdout

    def _prop(self, serial: str, name: str) -> str:
        try:
            return self._adb(serial, "shell", "getprop", name, timeout=10).strip()
        except RuntimeError:
            return ""

    def list_devices(self) -> list[Device]:
        if not self.adb:
            return []
        out = self._adb(None, "devices", "-l")
        devices: list[Device] = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            serial, state = parts[0], parts[1]
            attrs = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            is_emu = serial.startswith("emulator-")
            dev = Device(
                id=serial,
                platform="android",
                kind=DeviceKind.ANDROID_EMULATOR if is_emu else DeviceKind.ANDROID_PHYSICAL,
                state=state,
                model=attrs.get("model", "").replace("_", " "),
                extra={"transport": attrs.get("transport_id", ""), "product": attrs.get("product", "")},
            )
            if dev.available:
                dev.os_version = self._prop(serial, "ro.build.version.release")
                dev.api_level = self._prop(serial, "ro.build.version.sdk")
                dev.model = self._prop(serial, "ro.product.model") or dev.model
                dev.extra["manufacturer"] = self._prop(serial, "ro.product.manufacturer")
                if self._prop(serial, "ro.kernel.qemu") == "1":
                    dev.kind = DeviceKind.ANDROID_EMULATOR
                try:
                    m = re.search(r"(\d+x\d+)", self._adb(serial, "shell", "wm", "size", timeout=10))
                    dev.screen = m.group(1) if m else ""
                except RuntimeError:
                    pass
            devices.append(dev)
        return devices

    def find_packages(self, device: Device, keywords: list[str]) -> list[str]:
        out = self._adb(device.id, "shell", "pm", "list", "packages")
        pkgs = [l.removeprefix("package:").strip() for l in out.splitlines() if l.startswith("package:")]
        kws = [k.lower() for k in keywords]
        return sorted(p for p in pkgs if any(k in p.lower() for k in kws))

    def app_info(self, device: Device, package: str) -> InstalledApp | None:
        out = self._adb(device.id, "shell", "dumpsys", "package", package, timeout=30)
        if f"Package [{package}]" not in out:
            return None
        vn = re.search(r"versionName=(\S+)", out)
        vc = re.search(r"versionCode=(\d+)", out)
        info = InstalledApp(package, vn.group(1) if vn else None, vc.group(1) if vc else None)
        first = re.search(r"firstInstallTime=(.+)", out)
        last = re.search(r"lastUpdateTime=(.+)", out)
        info.extra["first_install"] = first.group(1).strip() if first else ""
        info.extra["last_update"] = last.group(1).strip() if last else ""
        try:
            act = self._adb(device.id, "shell", "cmd", "package", "resolve-activity", "--brief", package).strip()
            info.extra["launch_activity"] = act.splitlines()[-1] if "/" in act else ""
        except RuntimeError:
            info.extra["launch_activity"] = ""
        return info

    def battery(self, device: Device) -> dict:
        try:
            out = self._adb(device.id, "shell", "dumpsys", "battery", timeout=10)
        except RuntimeError:
            return {}
        level = re.search(r"level: (\d+)", out)
        status = re.search(r"status: (\d+)", out)   # 2 = cargando, 5 = llena
        return {"level": int(level.group(1)) if level else None,
                "charging": status.group(1) in ("2", "5") if status else None}

    def app_details(self, device: Device, package: str, cache_dir: Path) -> dict:
        """Peso (suma de APKs base+splits), etiqueta e ícono extraídos del APK instalado. Cacheado por versión."""
        info = self.app_info(device, package)
        if not info:
            return {}
        key = cache_dir / f"{package}-{info.version_code}"
        meta_path = key / "meta.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        key.mkdir(parents=True, exist_ok=True)
        paths = [l.removeprefix("package:").strip()
                 for l in self._adb(device.id, "shell", "pm", "path", package).splitlines() if l.startswith("package:")]
        size = 0
        for p in paths:
            try:
                size += int(self._adb(device.id, "shell", "stat", "-c", "%s", p, timeout=10).strip())
            except (RuntimeError, ValueError):
                pass
        meta: dict = {"package": package, "version_name": info.version_name, "version_code": info.version_code,
                      "size_bytes": size, "apks": len(paths), "last_update": info.extra.get("last_update", ""),
                      "first_install": info.extra.get("first_install", ""), "label": None, "icon": None,
                      "target_sdk": None, "min_sdk": None}
        base = next((p for p in paths if p.endswith("base.apk")), paths[0] if paths else None)
        aapt = _aapt()
        if base and aapt:
            local = key / "base.apk"
            try:
                self._adb(device.id, "pull", base, str(local), timeout=300)
                badging = run([aapt, "dump", "badging", str(local)], timeout=60).stdout
                lab = re.search(r"application-label(?:-es)?:'([^']*)'", badging)
                meta["label"] = lab.group(1) if lab else None
                tsdk = re.search(r"targetSdkVersion:'(\d+)'", badging)
                msdk = re.search(r"(?:minSdkVersion|sdkVersion):'(\d+)'", badging)
                meta["target_sdk"], meta["min_sdk"] = (tsdk.group(1) if tsdk else None), (msdk.group(1) if msdk else None)
                icon = _extract_icon(local, badging, key)
                meta["icon"] = icon.name if icon else None
            except Exception:
                pass
            finally:
                local.unlink(missing_ok=True)   # no guardar el APK (peso y propiedad intelectual)
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        return meta

    def install(self, device: Device, build_path: Path) -> None:
        if build_path.suffix.lower() != ".apk":
            raise ValueError("Solo se soportan .apk en el MVP (para .aab instalar bundletool)")
        self._adb(device.id, "install", "-r", str(build_path), timeout=300)

    def device_time(self, device: Device) -> str:
        return self._adb(device.id, "shell", "date", "+%m-%d %H:%M:%S.000", timeout=10).strip()

    def device_logs(self, device: Device, since: str | None = None) -> str:
        args = ["logcat", "-d", "-v", "threadtime"]
        args += ["-T", since] if since else ["-t", "5000"]
        try:
            return self._adb(device.id, *args, timeout=60)
        except RuntimeError as e:
            return f"<no se pudo obtener logcat: {e}>"

    def crash_buffer(self, device: Device, since: str | None = None) -> str:
        args = ["logcat", "-d", "-b", "crash", "-v", "threadtime"]
        if since:
            args += ["-T", since]
        try:
            return self._adb(device.id, *args, timeout=30)
        except RuntimeError:
            return ""
