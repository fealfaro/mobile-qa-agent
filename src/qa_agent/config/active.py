"""Perfil de app activo (selección local, no se versiona)."""
from __future__ import annotations

from qa_agent.config.models import list_profiles
from qa_agent.evidence.store import RUNS_DIR

_STATE = RUNS_DIR / ".state" / "active_profile"


def get_active() -> str | None:
    profiles = list_profiles()
    if _STATE.exists():
        v = _STATE.read_text(encoding="utf-8").strip()
        if v in profiles:
            return v
    return profiles[0] if len(profiles) == 1 else None


def set_active(app_id: str) -> None:
    if app_id not in list_profiles():
        raise ValueError(f"Perfil desconocido: {app_id}")
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(app_id, encoding="utf-8")
