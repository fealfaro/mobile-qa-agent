"""Validadores genéricos (no dependen de selectores de una app concreta).

Cada validador devuelve un ValidationResult con evidencia. El runner degrada a INCONCLUSIVE
cualquier PASS que no adjunte evidencia.
"""
from __future__ import annotations

import re
import time

from qa_agent.core.context import ExecutionContext, Snapshot
from qa_agent.core.registry import Registry
from qa_agent.core.results import ValidationResult
from qa_agent.core.status import Status
from qa_agent.core.testcase import ValidationSpec
from qa_agent.inspection.classifier import classify
from qa_agent.inspection.ui_tree import parse

from . import visual

GENERIC_ERROR_PATTERNS = [
    r"\berror\b", r"algo sali[oó] mal", r"intenta(lo)? (de )?nuevo", r"intenta(lo)? m[aá]s tarde",
    r"no (est[aá] )?disponible", r"sin conexi[oó]n", r"no pudimos", r"servicio no disponible",
    r"ha ocurrido un problema", r"tuvimos un problema",
]


def result(spec: ValidationSpec, status: Status, message: str, evidence: list[str] | None = None,
           **kw) -> ValidationResult:
    return ValidationResult(id=spec.id, type=spec.type, description=spec.description, status=status,
                            severity=spec.severity.value, message=message, evidence=evidence or [], **kw)


def current_snapshot(ctx: ExecutionContext, spec: ValidationSpec) -> Snapshot:
    """Usa el último snapshot si es reciente; `params.fresh: true` fuerza uno nuevo."""
    max_age = float(spec.params.get("max_snapshot_age_s", 5))
    s = ctx.last_snapshot
    if spec.params.get("fresh") or s is None or time.time() - s.taken_at > max_age:
        s = ctx.snapshot(f"val_{spec.id}")
    return s


def register(reg: Registry) -> None:
    @reg.validator("app_installed")
    def app_installed(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        info = ctx.state.get("app_info")
        if not info:
            return result(spec, Status.FAIL, f"{ctx.app_id} no instalada en {ctx.device.id}")
        ev = ctx.evidence.write_json("app_info", info)
        expected = spec.params.get("min_version")
        msg = f"{ctx.app_id} v{info.get('version_name')} ({info.get('version_code')}) instalada"
        return result(spec, Status.PASS, msg, [ev], expected=expected, actual=info.get("version_name"))

    @reg.validator("app_in_foreground")
    def app_in_foreground(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        state = ctx.driver.app_state(ctx.app_id)
        ev = [ctx.screenshot_only("foreground_check")]
        ok = state == 4
        return result(spec, Status.PASS if ok else Status.FAIL,
                      f"app_state={state} (4=foreground)", ev, expected=4, actual=state)

    @reg.validator("no_crash")
    def no_crash(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        if ctx.platform != "android":
            return result(spec, Status.INCONCLUSIVE, "Detección de crash vía logcat solo en Android (iOS: pendiente)")
        since = ctx.state.get("device_time_start")
        crash = ctx.provider.crash_buffer(ctx.device, since)  # type: ignore[attr-defined]
        logs = ctx.provider.device_logs(ctx.device, since)
        ev = [ctx.evidence.write_text("logcat", "log", logs), ctx.evidence.write_text("logcat_crash", "log", crash or "(vacío)")]
        pkg = re.escape(ctx.app_id)
        hits = [l for l in (crash + "\n" + logs).splitlines()
                if re.search(rf"(FATAL EXCEPTION|ANR in {pkg}|Process: {pkg}|am_crash.*{pkg})", l)]
        if hits:
            return result(spec, Status.FAIL, f"{len(hits)} líneas de crash/ANR de la app", ev,
                          actual=hits[:10], defect_category="crash")
        return result(spec, Status.PASS, "Sin crash ni ANR de la app en logcat durante la ejecución", ev)

    @reg.validator("screen_not_blank")
    def screen_not_blank(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        snap = current_snapshot(ctx, spec)
        score = visual.blank_score(ctx.abs_path(snap.screenshot))
        min_std = float(spec.params.get("min_stddev", 12))
        ok = score >= min_std and len(snap.tree.visible) > 3
        return result(spec, Status.PASS if ok else Status.FAIL,
                      f"stddev={score:.1f} (mín {min_std}), elementos visibles={len(snap.tree.visible)}",
                      snap.evidence, actual=round(score, 1), defect_category=None if ok else "visual_blank")

    @reg.validator("loading_completes")
    def loading_completes(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        timeout = float(spec.params.get("timeout_s", 20))
        cal = ctx.calibration(ctx.state.get("module", ""))
        extra = [l.to_locator() for l in cal.loading_indicators] if cal else []
        t0 = time.time()
        while True:
            tree = parse(ctx.driver.page_source(), ctx.platform)
            w, h = ctx.driver.window_size()
            loaders = [c for c in classify(tree, w, h) if c.category == "loading_indicator"]
            loaders += [e for loc in extra for e in tree.match(loc) if e.displayed]
            if not loaders or time.time() - t0 > timeout:
                break
            time.sleep(1)
        snap = ctx.snapshot(f"val_{spec.id}")
        elapsed = round(time.time() - t0, 1)
        if loaders:
            return result(spec, Status.FAIL, f"Indicadores de carga visibles tras {timeout}s", snap.evidence,
                          actual=len(loaders), defect_category="loading_stuck")
        return result(spec, Status.PASS, f"Sin indicadores de carga visibles ({elapsed}s)", snap.evidence, actual=elapsed)

    @reg.validator("interactive_elements_present")
    def interactive_present(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        snap = current_snapshot(ctx, spec)
        n = len(snap.tree.interactive)
        mn = int(spec.params.get("min", 3))
        enabled = sum(1 for e in snap.tree.interactive if e.enabled)
        return result(spec, Status.PASS if n >= mn else Status.FAIL,
                      f"{n} elementos interactivos visibles ({enabled} habilitados), mínimo {mn}",
                      snap.evidence, expected=f">={mn}", actual=n)

    @reg.validator("accessibility_coverage")
    def accessibility_coverage(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        snap = current_snapshot(ctx, spec)
        tree = snap.tree
        inter = tree.interactive

        def named(e) -> bool:
            if e.name:
                return True
            stack = list(e.children)
            while stack:
                c = tree.elements[stack.pop()]
                if c.name:
                    return True
                stack.extend(c.children)
            return False

        unnamed = [e.to_dict() for e in inter if not named(e)]
        pct = round(100 * (len(inter) - len(unnamed)) / len(inter), 1) if inter else 0.0
        min_pct = float(spec.params.get("min_pct", 80))
        ev = snap.evidence + [ctx.evidence.write_json("unnamed_interactive", unnamed)]
        if not inter:
            return result(spec, Status.INCONCLUSIVE, "No hay elementos interactivos para medir", ev)
        st = Status.PASS if pct >= min_pct else Status.FAIL
        return result(spec, st, f"{pct}% de {len(inter)} interactivos con nombre accesible (mín {min_pct}%)",
                      ev, expected=min_pct, actual=pct, defect_category=None if st == Status.PASS else "accessibility")

    @reg.validator("no_error_messages")
    def no_error_messages(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        snap = current_snapshot(ctx, spec)
        pats = [re.compile(p, re.I) for p in GENERIC_ERROR_PATTERNS + spec.params.get("extra_patterns", [])]
        hits = [e.name for e in snap.tree.visible if e.name and not e.interactive and any(p.search(e.name) for p in pats)]
        cal = ctx.calibration(ctx.state.get("module", ""))
        if cal:
            hits += [f"[{l.value}]" for l in cal.error_indicators if snap.tree.match(l.to_locator())]
        if hits:
            return result(spec, Status.FAIL, f"Mensajes de error visibles: {hits[:5]}", snap.evidence,
                          actual=hits, needs_human_review=True, defect_category="error_message")
        return result(spec, Status.PASS, f"Sin mensajes de error en {len(snap.tree.texts())} textos visibles", snap.evidence)

    @reg.validator("visual_baseline")
    def visual_baseline(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        snap = current_snapshot(ctx, spec)
        module = ctx.state.get("module", "default")
        name = spec.params.get("name", spec.id)
        w, h = snap.size
        dclass = visual.device_class(ctx.platform, ctx.device.model, w, h)
        base = visual.baseline_path(ctx.app.id, module, dclass, name)
        cur = ctx.abs_path(snap.screenshot)
        app_version = (ctx.state.get("app_info") or {}).get("version_name")
        meta = {"app_version": app_version, "device": ctx.device.model, "os": ctx.device.os_version, "run": ctx.evidence.run_id}
        if not base.exists():
            cand = visual.save_candidate(ctx.evidence.run_id, ctx.app.id, module, dclass, name, cur, meta)
            return result(spec, Status.INCONCLUSIVE,
                          f"Sin baseline para {dclass}/{name}. Candidata guardada; aprobar con: "
                          f"qa-agent baseline approve {ctx.evidence.run_id}", snap.evidence,
                          needs_human_review=True, actual=str(cand.relative_to(visual.ROOT)))
        diff_rel = ctx.evidence.next_path(f"diff_{name}", "png")
        d = visual.compare(cur, base, diff_rel, float(spec.params.get("top_ignore", 0.05)),
                           spec.params.get("ignore_regions"))
        ev = snap.evidence + [ctx.evidence.rel(diff_rel)] if d.comparable else snap.evidence
        if not d.comparable:
            return result(spec, Status.INCONCLUSIVE, f"No comparable: {d.reason}", ev, needs_human_review=True)
        tol = float(spec.params.get("tolerance", 0.03))
        fail_at = float(spec.params.get("fail_threshold", 0.15))
        same_version = visual.baseline_meta(base).get("app_version") == app_version
        actual = {"changed_ratio": d.changed_ratio, "changed_cells": f"{d.changed_cells}/{d.total_cells}"}
        if d.changed_ratio <= tol:
            return result(spec, Status.PASS, f"Diferencia {d.changed_ratio:.1%} ≤ tolerancia {tol:.0%}", ev, actual=actual)
        if d.changed_ratio >= fail_at and same_version:
            return result(spec, Status.FAIL, f"Diferencia {d.changed_ratio:.1%} ≥ {fail_at:.0%} en {d.changed_cells} regiones",
                          ev, actual=actual, defect_category="visual_regression", needs_human_review=True)
        why = "baseline de otra versión de app" if not same_version else "diferencia en zona gris"
        return result(spec, Status.INCONCLUSIVE, f"Diferencia {d.changed_ratio:.1%} ({why}); requiere revisión",
                      ev, actual=actual, needs_human_review=True)
