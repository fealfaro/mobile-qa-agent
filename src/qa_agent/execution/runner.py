"""Orquestador de ejecución: suite -> dispositivo -> sesión -> casos -> evidencias -> reporte.

MVP: un dispositivo, ejecución secuencial.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from selenium.common.exceptions import WebDriverException

from qa_agent import __version__
from qa_agent.config.models import AppCfg, Calibration, EnvironmentCfg, load_app, load_calibration, load_environment
from qa_agent.core.context import ExecutionContext
from qa_agent.core.contracts import Device, DeviceProvider, InstalledApp
from qa_agent.core.events import Emitter, EventSink
from qa_agent.core.registry import Registry, build_registry
from qa_agent.core.results import AppSnapshot, CaseResult, DeviceSnapshot, RunResult, StepResult, ValidationResult, now
from qa_agent.core.status import Status, aggregate, enforce_evidence
from qa_agent.core.testcase import TestCase, TestSuite
from qa_agent.devices.manager import DeviceManager
from qa_agent.devices.toolchain import prepare_env
from qa_agent.evidence.store import EvidenceStore, FileRunRepository, new_run_id, setup_run_logger
from qa_agent.execution.appium_driver import create_driver
from qa_agent.execution.appium_server import AppiumServer
from qa_agent.security.policy import ActionPolicy, PolicyViolation
from qa_agent.security.secrets import env as getenv
from qa_agent.security.secrets import resolve_refs

log = logging.getLogger("qa_agent")


class AppResolutionError(RuntimeError):
    pass


def resolve_app_id(app: AppCfg, platform: str, provider: DeviceProvider, device: Device) -> str | None:
    """Usa el id configurado; si no hay, lo descubre por palabras clave entre las apps instaladas."""
    cfg = app.android if platform == "android" else app.ios
    configured = cfg.package if platform == "android" else cfg.bundle_id  # type: ignore[union-attr]
    if configured:
        return configured
    kws = cfg.package_keywords if platform == "android" else cfg.bundle_keywords  # type: ignore[union-attr]
    found = provider.find_packages(device, kws)
    if len(found) == 1:
        log.info("App detectada por palabra clave %s: %s", kws, found[0])
        return found[0]
    if len(found) > 1:
        raise AppResolutionError(f"Varias apps coinciden con {kws}: {found}. Define el id en profiles/{app.id}/profile.yaml")
    return None


def reviewed_calibration(app_id: str, module: str, platform: str) -> Calibration | None:
    cal = load_calibration(app_id, module, platform)
    if cal and cal.status != "reviewed":
        log.warning("Calibración %s/%s.%s con status=%s: se ignora hasta revisión humana", app_id, module, platform, cal.status)
        return None
    return cal


@dataclass
class Session:
    """Sesión preparada (servidor + dispositivo + app + driver). Reutilizada por `run` e `inspect`."""

    ctx: ExecutionContext
    server: AppiumServer
    app_info: InstalledApp | None

    def close(self) -> None:
        try:
            self.ctx.driver.stop()
        finally:
            self.server.stop()


def open_session(platform: str, app: AppCfg, envcfg: EnvironmentCfg, store: EvidenceStore,
                 modules: list[str], device_id: str | None = None) -> Session:
    prepare_env()
    dm = DeviceManager()
    device = dm.select(platform, device_id)
    provider = dm.provider(platform)
    log.info("Dispositivo: %s %s (%s %s, %s)", device.id, device.model, platform, device.os_version, device.kind.value)
    app_id = resolve_app_id(app, platform, provider, device)
    if not app_id:
        raise AppResolutionError(f"{app.name}: falta el id de la app para {platform} en el perfil '{app.id}' "
                                 "o no hay coincidencias instaladas")
    info = provider.app_info(device, app_id)
    if info is None and platform == "android":
        raise AppResolutionError(f"{app_id} no está instalada en {device.id}")
    log.info("App: %s versión %s (%s)", app_id, info.version_name if info else "?", info.version_code if info else "?")

    server = AppiumServer(envcfg.appium_url, store.dir / "appium.log")
    server.ensure(autostart=(getenv("APPIUM_AUTOSTART", "true") or "true").lower() == "true")
    driver = create_driver(platform, envcfg.appium_url, device, app_id, extra_caps=envcfg.capabilities,
                           new_command_timeout_s=envcfg.new_command_timeout_s)
    policy = ActionPolicy(envcfg.allow_transactions, app.safety.deny_keywords)
    cals = {m: c for m in modules if (c := reviewed_calibration(app.id, m, platform))}
    ctx = ExecutionContext(platform=platform, device=device, provider=provider, driver=driver, app=app,
                           app_id=app_id, env=envcfg, evidence=store, policy=policy, calibrations=cals)
    if platform == "android":
        try:
            ctx.state["device_time_start"] = provider.device_time(device)  # type: ignore[attr-defined]
        except Exception:
            pass
    if info:
        ctx.state["app_info"] = {"package": info.package, "version_name": info.version_name,
                                 "version_code": info.version_code, **info.extra}
    driver.start()
    return Session(ctx, server, info)


class Runner:
    def __init__(self, suite: TestSuite, platform: str, env_name: str, device_id: str | None = None,
                 case_filter: list[str] | None = None, verbose: bool = False,
                 on_event: EventSink | None = None, run_id: str | None = None,
                 cancel: threading.Event | None = None) -> None:
        self.emit = Emitter(on_event)
        self.run_id = run_id
        self.cancel = cancel or threading.Event()
        self.suite = suite
        self.platform = platform
        self.env_name = env_name
        self.device_id = device_id
        self.case_filter = set(case_filter or [])
        self.verbose = verbose
        self.registry: Registry = build_registry([suite.module])

    def _cases(self) -> list[TestCase]:
        return [c for c in self.suite.cases
                if self.platform in [p.value for p in c.platforms]
                and (not self.case_filter or c.id in self.case_filter)]

    def run(self) -> RunResult:
        run_id = self.run_id or new_run_id(f"{self.suite.module}-{self.platform}")
        store = EvidenceStore(run_id)
        setup_run_logger(store, self.verbose)
        run = RunResult(run_id=run_id, suite_id=self.suite.id, suite_name=self.suite.name, module=self.suite.module,
                        environment=self.env_name, agent_version=__version__)
        cases = self._cases()
        run.cases = [CaseResult(case_id=c.id, name=c.name, priority=c.priority.value) for c in cases]
        self.emit("run_started", run_id=run_id, suite=self.suite.name, platform=self.platform, plan=[
            {"case_id": c.id, "name": c.name, "priority": c.priority.value,
             "steps": [{"id": s.id, "action": s.action, "description": s.description} for s in c.steps],
             "validations": [{"id": v.id, "type": v.type, "description": v.description} for v in c.validations]}
            for c in cases])
        t0 = time.time()
        session: Session | None = None
        try:
            app = load_app(self.suite.app)
            envcfg = load_environment(self.env_name)
            session = open_session(self.platform, app, envcfg, store, [self.suite.module], self.device_id)
            ctx = session.ctx
            d = ctx.device
            run.device = DeviceSnapshot(id=d.id, platform=d.platform, kind=d.kind.value, model=d.model, os_version=d.os_version)
            info = session.app_info
            run.app = AppSnapshot(id=app.id, name=app.name, package=ctx.app_id,
                                  version=info.version_name if info else None, build=info.version_code if info else None)
            ctx.emit = self.emit
            self.emit("session", device=run.device.model_dump(), app=run.app.model_dump())
            for case, cres in zip(cases, run.cases):
                if self.cancel.is_set():
                    cres.errors.append("Cancelado por el operador")
                    self.emit("case_finished", case_id=case.id, status=cres.status.value, duration_s=0)
                    continue
                self._run_case(ctx, case, cres)
        except Exception as e:  # entorno no disponible => casos BLOCKED (no FAIL: no es defecto del producto)
            msg = f"{type(e).__name__}: {e}"
            log.error("Ejecución bloqueada: %s", msg)
            log.debug(traceback.format_exc())
            run.errors.append(msg)
            self.emit("error", message=msg)
            for c in run.cases:
                if c.status == Status.NOT_EXECUTED and not c.steps:
                    c.status = Status.BLOCKED
                    c.errors.append(msg)
                    self.emit("case_finished", case_id=c.case_id, status=c.status.value, duration_s=0)
        finally:
            if session:
                session.close()
        run.finished_at = now()
        run.duration_s = time.time() - t0
        run.status = aggregate([c.status for c in run.cases]) if run.cases else Status.NOT_EXECUTED
        self._finish(run, store)
        return run

    def _run_case(self, ctx: ExecutionContext, case: TestCase, cres: CaseResult) -> None:
        log.info("── Caso %s: %s", case.id, case.name)
        ctx.evidence.set_case(case.id)
        self.emit.case_id = case.id
        self.emit("case_started", name=case.name)
        keep = {k: ctx.state[k] for k in ("app_info", "device_time_start") if k in ctx.state}
        ctx.state.clear()
        ctx.state.update(keep, module=case.module, test_data=resolve_refs(case.test_data))
        ctx.last_snapshot = None
        t0 = time.time()
        stop = False
        for step in case.steps:
            if self.cancel.is_set() and not stop:
                stop = True
            if stop:
                msg = "Cancelado por el operador" if self.cancel.is_set() else "Omitido por fallo previo"
                cres.steps.append(StepResult(id=step.id, action=step.action, description=step.description,
                                             status=Status.NOT_EXECUTED, message=msg))
                self.emit("step_finished", step_id=step.id, action=step.action, status="NOT_EXECUTED", message=msg)
                continue
            self.emit("step_started", step_id=step.id, action=step.action, description=step.description)
            sr = self._run_step(ctx, case, step)
            cres.steps.append(sr)
            self.emit("step_finished", step_id=step.id, action=step.action, status=sr.status.value,
                      message=sr.message, duration_s=sr.duration_s, evidence=sr.evidence)
            log.info("   paso %-22s %-12s %s", step.id, sr.status.value, sr.message)
            if case.evidence.screenshot_each_step:
                sr.evidence.append(self._safe_shot(ctx, f"step_{step.id}"))
            if sr.status != Status.PASS and not step.continue_on_failure:
                stop = True
        for spec in case.validations:
            if self.cancel.is_set():
                vr = ValidationResult(id=spec.id, type=spec.type, description=spec.description,
                                      status=Status.NOT_EXECUTED, severity=spec.severity.value,
                                      message="Cancelado por el operador")
            else:
                self.emit("validation_started", validation_id=spec.id, vtype=spec.type, description=spec.description)
                vr = self._run_validation(ctx, spec)
            cres.validations.append(vr)
            self.emit("validation", validation_id=vr.id, vtype=vr.type, description=vr.description,
                      status=vr.status.value, message=vr.message, severity=vr.severity, evidence=vr.evidence,
                      needs_human_review=vr.needs_human_review, expected=vr.expected, actual=vr.actual)
            log.info("   valida %-21s %-12s %s", spec.id, vr.status.value, vr.message)
        cres.duration_s = round(time.time() - t0, 2)
        cres.finalize()
        if case.evidence.screenshot_at_end or (cres.status != Status.PASS and case.evidence.screenshot_on_failure):
            shot = self._safe_shot(ctx, "end")
            if shot:
                cres.evidence.append(shot)
        self.emit("case_finished", status=cres.status.value, duration_s=cres.duration_s)
        log.info("   => %s (%.1fs)", cres.status.value, cres.duration_s)

    def _safe_shot(self, ctx: ExecutionContext, label: str) -> str:
        try:
            return ctx.screenshot_only(label)
        except Exception as e:
            log.warning("No se pudo capturar screenshot %s: %s", label, e)
            return ""

    def _run_step(self, ctx: ExecutionContext, case: TestCase, step) -> StepResult:
        t0 = time.time()
        sr = StepResult(id=step.id, action=step.action, description=step.description, status=Status.FAIL)
        adef = self.registry.actions.get(step.action)
        try:
            if not adef:
                raise PolicyViolation(f"Acción '{step.action}' no registrada/autorizada")
            ctx.policy.check_action(step.action, adef.transactional)
            out = adef.handler(ctx, step)
            sr.status = Status.BLOCKED if out.blocked else Status.INCONCLUSIVE if out.inconclusive else \
                Status.PASS if out.ok else Status.FAIL
            sr.message, sr.evidence = out.message, [e for e in out.evidence if e]
        except PolicyViolation as e:
            sr.status, sr.message = Status.BLOCKED, f"Política de seguridad: {e}"
        except WebDriverException as e:
            sr.status, sr.message = Status.BLOCKED, f"Error de automatización: {e.msg or e}"
            sr.evidence = [s for s in [self._safe_shot(ctx, f"error_{step.id}")] if s]
        except Exception as e:
            sr.status, sr.message = Status.BLOCKED, f"Error del agente: {type(e).__name__}: {e}"
            log.debug(traceback.format_exc())
        sr.duration_s = round(time.time() - t0, 2)
        return sr

    def _run_validation(self, ctx: ExecutionContext, spec) -> ValidationResult:
        fn = self.registry.validators.get(spec.type)
        if not fn:
            return ValidationResult(id=spec.id, type=spec.type, description=spec.description, status=Status.BLOCKED,
                                    severity=spec.severity.value, message=f"Validador '{spec.type}' no registrado")
        try:
            vr = fn(ctx, spec)
        except Exception as e:
            log.debug(traceback.format_exc())
            return ValidationResult(id=spec.id, type=spec.type, description=spec.description, status=Status.BLOCKED,
                                    severity=spec.severity.value, message=f"No se pudo validar: {type(e).__name__}: {e}")
        vr.evidence = [e for e in vr.evidence if e]
        status, note = enforce_evidence(vr.status, vr.evidence)
        if note:
            vr.status, vr.message = status, f"{vr.message} | {note}"
        return vr

    def _finish(self, run: RunResult, store: EvidenceStore) -> None:
        from qa_agent.intelligence.analyzer import analyze_run
        from qa_agent.reporting.html import write_report

        analysis = analyze_run(run)
        (store.dir / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
        store.save_run(run)
        report = write_report(run, store.dir, analysis)
        FileRunRepository().add(run)
        s = run.summary()
        self.emit.case_id = None
        self.emit("run_finished", status=run.status.value, summary=s, report="report.html",
                  defects=len(analysis.get("defects", [])), review=len(analysis.get("needs_human_review", [])))
        log.info("RESULTADO %s | casos %s | validaciones %s | %.1fs", run.status.value, s["cases"], s["validations"], run.duration_s)
        log.info("Reporte: %s", report)


def load_suite(path: Path) -> TestSuite:
    from qa_agent.importers import load_suite_file

    return load_suite_file(path)
