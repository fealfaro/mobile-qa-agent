"""Estados de resultado y reglas de agregación.

Regla central: ningún resultado es PASS sin evidencia verificable (ver `enforce_evidence`).
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"            # no se pudo ejecutar por una precondición/entorno
    INCONCLUSIVE = "INCONCLUSIVE"  # se ejecutó pero no hay confianza/evidencia suficiente
    NOT_EXECUTED = "NOT_EXECUTED"  # no se intentó (filtro, abortado antes, etc.)


# Precedencia para agregar resultados de hijos a un padre (mayor = domina).
_PRECEDENCE = {
    Status.FAIL: 5,
    Status.BLOCKED: 4,
    Status.INCONCLUSIVE: 3,
    Status.NOT_EXECUTED: 2,
    Status.PASS: 1,
}


def aggregate(statuses: Iterable[Status]) -> Status:
    """Un caso es PASS solo si TODOS sus componentes son PASS."""
    items = list(statuses)
    if not items:
        return Status.NOT_EXECUTED
    return max(items, key=lambda s: _PRECEDENCE[s])


def enforce_evidence(status: Status, evidence: list[str]) -> tuple[Status, str | None]:
    """Degrada PASS sin evidencia a INCONCLUSIVE."""
    if status == Status.PASS and not evidence:
        return Status.INCONCLUSIVE, "PASS degradado: no se adjuntó evidencia verificable"
    return status, None
