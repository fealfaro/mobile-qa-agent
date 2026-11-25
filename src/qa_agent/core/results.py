"""Modelo de resultados de ejecución (persistido como JSON; contrato estable para reporting)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .status import Status, aggregate


def now() -> datetime:
    return datetime.now(timezone.utc)


class ValidationResult(BaseModel):
    id: str
    type: str
    description: str = ""
    status: Status
    severity: str = "major"
    message: str = ""
    expected: Any = None
    actual: Any = None
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)   # rutas relativas al directorio del run
    needs_human_review: bool = False
    defect_category: str | None = None


class StepResult(BaseModel):
    id: str
    action: str
    description: str = ""
    status: Status
    message: str = ""
    started_at: datetime = Field(default_factory=now)
    duration_s: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    case_id: str
    name: str
    priority: str
    status: Status = Status.NOT_EXECUTED
    started_at: datetime = Field(default_factory=now)
    duration_s: float = 0.0
    steps: list[StepResult] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    def finalize(self) -> None:
        parts = [s.status for s in self.steps] + [v.status for v in self.validations]
        self.status = aggregate(parts) if parts else Status.NOT_EXECUTED


class DeviceSnapshot(BaseModel):
    id: str
    platform: str
    kind: str
    model: str = ""
    os_version: str = ""


class AppSnapshot(BaseModel):
    id: str
    name: str
    package: str | None = None
    version: str | None = None
    build: str | None = None


class RunResult(BaseModel):
    run_id: str
    suite_id: str
    suite_name: str
    module: str
    environment: str
    started_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None
    duration_s: float = 0.0
    device: DeviceSnapshot | None = None
    app: AppSnapshot | None = None
    status: Status = Status.NOT_EXECUTED
    cases: list[CaseResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    agent_version: str = ""

    def summary(self) -> dict[str, Any]:
        vals = [v for c in self.cases for v in c.validations]
        counts = {s.value: 0 for s in Status}
        for c in self.cases:
            counts[c.status.value] += 1
        vcounts = {s.value: 0 for s in Status}
        for v in vals:
            vcounts[v.status.value] += 1
        executed = len(self.cases) - counts["NOT_EXECUTED"]
        return {
            "total_cases": len(self.cases),
            "cases": counts,
            "pass_rate_cases": round(100 * counts["PASS"] / executed, 1) if executed else 0.0,
            "total_validations": len(vals),
            "validations": vcounts,
            "pass_rate_validations": round(100 * vcounts["PASS"] / len(vals), 1) if vals else 0.0,
            "duration_s": round(self.duration_s, 1),
        }
