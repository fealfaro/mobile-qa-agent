"""Resolución de secretos: variables de entorno / .env, con fallback al Llavero de macOS.

Los valores resueltos se registran en el Masker para que nunca aparezcan en logs/reportes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from dotenv import load_dotenv

from qa_agent.config.models import ROOT

from .masking import MASKER

KEYCHAIN_SERVICE = "mobile-qa-agent"
_SECRET_REF = re.compile(r"\$\{secret:([A-Z0-9_]+)\}")

load_dotenv(ROOT / ".env", override=False)


def get_secret(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name) or _from_keychain(name)
    if value:
        MASKER.register_secret(value)
        return value
    if required:
        raise KeyError(
            f"Secreto '{name}' no definido. Defínelo en .env o en el Llavero: "
            f"security add-generic-password -s {KEYCHAIN_SERVICE} -a {name} -w '<valor>'"
        )
    return None


def _from_keychain(name: str) -> str | None:
    if not shutil.which("security"):
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def resolve_refs(data: Any) -> Any:
    """Reemplaza "${secret:NOMBRE}" recursivamente."""
    if isinstance(data, str):
        return _SECRET_REF.sub(lambda m: get_secret(m.group(1)) or "", data)
    if isinstance(data, dict):
        return {k: resolve_refs(v) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_refs(v) for v in data]
    return data


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
