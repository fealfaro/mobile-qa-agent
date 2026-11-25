"""Proveedores LLM (Sprint 4). En el MVP no hay proveedor activo (LLM_PROVIDER=none).

Para agregar uno: implementar `AIProvider` (core/contracts.py) y registrarlo en `_PROVIDERS`.
Regla: la salida del LLM es una propuesta o explicación; nunca se ejecuta como acción.
"""
from __future__ import annotations

from qa_agent.core.contracts import AIProvider
from qa_agent.security.secrets import env

_PROVIDERS: dict[str, type] = {}


def get_provider() -> AIProvider | None:
    name = (env("LLM_PROVIDER", "none") or "none").lower()
    if name == "none":
        return None
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"LLM_PROVIDER '{name}' no implementado")
    return cls()
