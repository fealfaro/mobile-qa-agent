"""Modelo universal de casos de prueba (independiente de cualquier módulo/journey).

Las fuentes futuras (Excel, Jira, Word, PDF, Markdown, formularios) deben convertirse a
este modelo mediante un `importer` (ver qa_agent.importers). El MVP soporta YAML/JSON.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Platform(str, Enum):
    ANDROID = "android"
    IOS = "ios"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Step(_Strict):
    """Paso ejecutable. `action` debe existir en el ActionRegistry y estar permitido por la política."""

    id: str
    action: str
    description: str = ""
    target: str | None = None          # nombre lógico de componente (resuelto vía calibración)
    params: dict[str, Any] = Field(default_factory=dict)
    expected: str = ""
    continue_on_failure: bool = False


class ValidationSpec(_Strict):
    """Validación explícita. `type` debe existir en el ValidatorRegistry."""

    id: str
    type: str
    description: str = ""
    target: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.MAJOR


class EvidencePolicy(_Strict):
    screenshot_each_step: bool = False
    screenshot_on_failure: bool = True
    screenshot_at_end: bool = True
    page_source: bool = True
    device_logs: bool = True


class TestCase(_Strict):
    id: str
    name: str
    description: str = ""
    module: str                                    # p.ej. "home"
    platforms: list[Platform] = Field(default_factory=lambda: [Platform.ANDROID, Platform.IOS])
    priority: Priority = Priority.P2
    tags: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)  # admite "${secret:NOMBRE}"
    steps: list[Step] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    validations: list[ValidationSpec] = Field(default_factory=list)
    evidence: EvidencePolicy = Field(default_factory=EvidencePolicy)
    source: dict[str, Any] = Field(default_factory=dict)      # trazabilidad (archivo, Jira key, fila Excel...)


class TestSuite(_Strict):
    id: str
    name: str
    description: str = ""
    app: str = ""                                  # id del perfil (se infiere de profiles/<app>/suites/)
    module: str
    cases: list[TestCase]
