"""Levantamiento de la pantalla principal de una app real: abre la app, recorre con scroll (solo lectura),
inventaría componentes y genera una calibración BORRADOR para revisión humana.

Lo usan `qa-agent inspect` (CLI) y la consola web. Nunca modifica una calibración revisada.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qa_agent.config.models import AppCfg, EnvironmentCfg
from qa_agent.core.events import Emitter, EventSink
from qa_agent.evidence.store import EvidenceStore
from qa_agent.reporting.html import write_inspection_report
from qa_agent.security.masking import MASKER

from . import MODULE
from .discovery import discover


@dataclass
class SurveyResult:
    run_id: str
    draft_path: Path
    draft: dict
    inventory: dict
    report: Path
    screenshots: list[str]


def run_survey(app: AppCfg, envcfg: EnvironmentCfg, store: EvidenceStore, platform: str = "android",
               device_id: str | None = None, settle_s: float = 6, max_swipes: int = 6,
               on_event: EventSink | None = None, wait_operator: Callable[[], None] | None = None) -> SurveyResult:
    from qa_agent.execution.runner import open_session, reviewed_calibration
    from qa_agent.execution.session import poll_screen

    emit = Emitter(on_event)
    store.set_case("survey")
    emit("survey_started", app=app.id, platform=platform)
    session = open_session(platform, app, envcfg, store, [MODULE], device_id)
    try:
        ctx = session.ctx
        ctx.emit = emit
        d = ctx.device
        emit("session", device={"model": d.model, "os_version": d.os_version, "id": d.id},
             app={"name": app.name, "version": (ctx.state.get("app_info") or {}).get("version_name"),
                  "build": (ctx.state.get("app_info") or {}).get("version_code")})
        emit("survey_phase", phase="launch", message="Abriendo la app")
        ctx.driver.activate_app(ctx.app_id)
        time.sleep(settle_s)
        snap = ctx.snapshot("launch")
        pkgs = {e.raw.get("package") for e in snap.tree.elements if e.raw.get("package")}
        locked = any("keyguard" in e.resource_id or "bouncer" in e.resource_id for e in snap.tree.elements)
        if platform == "android" and (ctx.app_id not in pkgs or locked):
            raise RuntimeError(f"La app no está visible en primer plano (paquetes en pantalla: {sorted(pkgs)}). "
                               "¿Teléfono bloqueado? Desbloquéalo y reintenta.")
        cal = reviewed_calibration(app.id, MODULE, platform)
        if cal and "home" in cal.screens:
            m, _ = poll_screen(ctx, cal, "home", app.session.home_timeout_s)
            emit("observation", level="info", title="Calibración vigente",
                 message=f"Pantalla principal {'reconocida' if m and m.matched else 'NO reconocida'} con la firma revisada")
        elif wait_operator:
            wait_operator()
        emit("survey_phase", phase="explore", message="Recorriendo la pantalla con scroll (solo lectura)")
        version = (ctx.state.get("app_info") or {}).get("version_name")
        exp, draft_path, draft = discover(ctx, version, max_swipes)
        inv = exp.inventory()
        (store.dir / "inventory.json").write_text(MASKER.mask(json.dumps(inv, indent=2, ensure_ascii=False)),
                                                  encoding="utf-8")
        shots = [p.screenshot for p in exp.pages]
        rep = write_inspection_report(store.dir / "inspection.html", inv, shots,
                                      f"{d.model} {d.os_version}", ctx.app_id)
        s = inv["summary"]
        emit("survey_finished", summary=s, pages=inv["pages"], draft=str(draft_path.name),
             signature=draft["screens"]["home"]["locators"], screenshots=shots, report="inspection.html")
        return SurveyResult(store.run_id, draft_path, draft, inv, rep, shots)
    finally:
        session.close()
