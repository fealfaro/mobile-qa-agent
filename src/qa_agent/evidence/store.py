"""Evidence Layer: almacenamiento de evidencias por ejecución y repositorio de historial.

Estructura:
  runs/<run_id>/
    run.json                 resultado completo (contrato RunResult)
    agent.log                log del agente (enmascarado)
    appium.log               log del servidor Appium (si lo inició el agente)
    report.html              reporte
    cases/<case_id>/         screenshots, page sources (enmascarados), logs de dispositivo
  runs/index.json            historial de ejecuciones (FileRunRepository)
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from qa_agent.config.models import ROOT
from qa_agent.core.results import RunResult
from qa_agent.security.masking import MASKER, MaskingFilter

RUNS_DIR = ROOT / "runs"


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]


class EvidenceStore:
    def __init__(self, run_id: str, base: Path = RUNS_DIR) -> None:
        self.run_id = run_id
        self.dir = base / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._case = "_run"
        self._seq = 0

    def set_case(self, case_id: str) -> None:
        self._case = _safe(case_id)
        self._seq = 0

    @property
    def case_dir(self) -> Path:
        d = self.dir / "cases" / self._case
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.dir))

    def next_path(self, label: str, ext: str) -> Path:
        self._seq += 1
        return self.case_dir / f"{self._seq:03d}_{_safe(label)}.{ext}"

    def write_text(self, label: str, ext: str, content: str, mask: bool = True) -> str:
        p = self.next_path(label, ext)
        p.write_text(MASKER.mask(content) if mask else content, encoding="utf-8")
        return self.rel(p)

    def write_json(self, label: str, data: object) -> str:
        return self.write_text(label, "json", json.dumps(data, ensure_ascii=False, indent=2, default=str))

    def save_run(self, run: RunResult) -> Path:
        p = self.dir / "run.json"
        p.write_text(MASKER.mask(run.model_dump_json(indent=2)), encoding="utf-8")
        return p


def setup_run_logger(store: EvidenceStore, verbose: bool = False) -> logging.Logger:
    log = logging.getLogger("qa_agent")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(store.dir / "agent.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(MaskingFilter())
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    sh.addFilter(MaskingFilter())
    log.addHandler(fh)
    log.addHandler(sh)
    return log


class FileRunRepository:
    """Persistencia del MVP (JSON). Contrato pensado para migrar a PostgreSQL sin cambiar callers."""

    def __init__(self, base: Path = RUNS_DIR) -> None:
        self.base = base
        self.index = base / "index.json"

    def _load(self) -> list[dict]:
        if self.index.exists():
            return json.loads(self.index.read_text(encoding="utf-8"))
        return []

    def add(self, run: RunResult) -> None:
        items = [i for i in self._load() if i["run_id"] != run.run_id]
        items.append({
            "run_id": run.run_id, "suite_id": run.suite_id, "module": run.module,
            "app_id": run.app.id if run.app else None,
            "started_at": run.started_at.isoformat(), "status": run.status.value,
            "platform": run.device.platform if run.device else None,
            "device": run.device.model if run.device else None,
            "app_version": run.app.version if run.app else None,
            "summary": run.summary(), "recorded_at": time.time(),
        })
        self.base.mkdir(parents=True, exist_ok=True)
        self.index.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    def list(self) -> list[dict]:
        return sorted(self._load(), key=lambda i: i["started_at"], reverse=True)

    def get(self, run_id: str) -> RunResult:
        return RunResult.model_validate_json((self.base / run_id / "run.json").read_text(encoding="utf-8"))
