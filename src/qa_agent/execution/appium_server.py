"""Arranque/verificación del servidor Appium local."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from qa_agent.devices.toolchain import prepare_env

log = logging.getLogger("qa_agent")


def appium_status(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/status", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


class AppiumServer:
    def __init__(self, url: str, log_file: Path | None = None) -> None:
        self.url = url
        self.log_file = log_file
        self.proc: subprocess.Popen | None = None

    def ensure(self, autostart: bool = True, timeout_s: float = 40) -> None:
        if appium_status(self.url):
            log.info("Appium ya está corriendo en %s", self.url)
            return
        if not autostart:
            raise RuntimeError(f"Appium no responde en {self.url} (APPIUM_AUTOSTART=false). Ejecuta: appium")
        exe = shutil.which("appium")
        if not exe:
            raise RuntimeError("Appium no instalado: npm install -g appium && appium driver install uiautomator2")
        prepare_env()
        u = urlparse(self.url)
        args = [exe, "--address", u.hostname or "127.0.0.1", "--port", str(u.port or 4723), "--log-no-colors"]
        if self.log_file:
            args += ["--log", str(self.log_file), "--log-level", "info"]
        log.info("Iniciando Appium: %s", " ".join(args[1:]))
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if appium_status(self.url):
                log.info("Appium listo")
                return
            if self.proc.poll() is not None:
                raise RuntimeError(f"Appium terminó al iniciar (código {self.proc.returncode}); ver {self.log_file}")
            time.sleep(1)
        raise RuntimeError("Timeout esperando a Appium")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
