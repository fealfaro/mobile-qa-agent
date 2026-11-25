"""Validaciones funcionales específicas de la pantalla principal (basadas en la calibración revisada)."""
from __future__ import annotations

from qa_agent.core.context import ExecutionContext
from qa_agent.core.registry import Registry
from qa_agent.core.results import ValidationResult
from qa_agent.core.status import Status
from qa_agent.core.testcase import ValidationSpec
from qa_agent.inspection.screens import match_screen
from qa_agent.validation.builtin_validators import current_snapshot, result

from . import MODULE


def _blocked_uncalibrated(spec: ValidationSpec, what: str) -> ValidationResult:
    return result(spec, Status.BLOCKED, f"{what} no calibrado en config/calibration/{MODULE}.<platform>.yaml")


def register(reg: Registry) -> None:
    @reg.validator("home_recognized")
    def home_recognized(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        cal = ctx.calibration(MODULE)
        if not cal or "home" not in cal.screens:
            return _blocked_uncalibrated(spec, "Firma de pantalla 'home'")
        snap = current_snapshot(ctx, spec)
        m = match_screen(snap.tree, snap.screen_id, cal.screens["home"])
        st = Status.PASS if m.matched else Status.FAIL
        return result(spec, st, f"{m.hits}/{m.total} marcadores (mín {m.required}): " + "; ".join(m.detail),
                      snap.evidence, confidence=m.confidence, expected=m.required, actual=m.hits)

    @reg.validator("home_load_time")
    def home_load_time(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        t = ctx.state.get("home_reached_s")
        if t is None:
            return result(spec, Status.BLOCKED, "La pantalla principal no fue alcanzado en este caso")
        mx = float(spec.params.get("max_s", 15))
        ev = [ctx.last_snapshot.screenshot] if ctx.last_snapshot else []
        return result(spec, Status.PASS if t <= mx else Status.FAIL, f"Pantalla principal reconocido en {t}s (máx {mx}s)",
                      ev, expected=mx, actual=t, defect_category=None if t <= mx else "performance")

    def _component(ctx: ExecutionContext, spec: ValidationSpec):
        cal = ctx.calibration(MODULE)
        if not cal or not spec.target or spec.target not in cal.components:
            return None, None
        return cal.components[spec.target], current_snapshot(ctx, spec)

    @reg.validator("component_present")
    def component_present(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        comp, snap = _component(ctx, spec)
        if not comp:
            return _blocked_uncalibrated(spec, f"Componente '{spec.target}'")
        found = [e for e in snap.tree.match(comp.locator.to_locator()) if e.displayed]
        if not found and comp.scroll_to_find and ctx.state.get("exploration"):
            for p in ctx.state["exploration"].pages:
                found = p.tree.match(comp.locator.to_locator())
                if found:
                    snap = p
                    break
        return result(spec, Status.PASS if found else Status.FAIL,
                      f"'{spec.target}' ({comp.locator.strategy}={comp.locator.value}) "
                      f"{'presente' if found else 'ausente'}", snap.evidence,
                      defect_category=None if found else "missing_component")

    @reg.validator("component_text")
    def component_text(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        comp, snap = _component(ctx, spec)
        if not comp:
            return _blocked_uncalibrated(spec, f"Componente '{spec.target}'")
        expected = spec.params.get("expected") or comp.expected_text
        if not expected:
            return result(spec, Status.BLOCKED, f"'{spec.target}' sin expected_text definido")
        els = snap.tree.match(comp.locator.to_locator())
        if not els:
            return result(spec, Status.FAIL, f"'{spec.target}' ausente", snap.evidence, expected=expected)
        el = els[0]
        actual = el.name
        stack = list(el.children)
        texts = [actual] if actual else []
        while stack:
            c = snap.tree.elements[stack.pop(0)]
            if c.name:
                texts.append(c.name)
            stack.extend(c.children)
        ok = any(expected.lower() in t.lower() for t in texts)
        return result(spec, Status.PASS if ok else Status.FAIL, f"Esperado contiene {expected!r}", snap.evidence,
                      expected=expected, actual=texts[:5], defect_category=None if ok else "content")

    @reg.validator("component_enabled")
    def component_enabled(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        comp, snap = _component(ctx, spec)
        if not comp:
            return _blocked_uncalibrated(spec, f"Componente '{spec.target}'")
        els = snap.tree.match(comp.locator.to_locator())
        if not els:
            return result(spec, Status.FAIL, f"'{spec.target}' ausente", snap.evidence)
        ok = els[0].enabled
        return result(spec, Status.PASS if ok else Status.FAIL, f"enabled={els[0].enabled}", snap.evidence,
                      expected=True, actual=els[0].enabled)

    @reg.validator("required_components")
    def required_components(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        cal = ctx.calibration(MODULE)
        if not cal or not cal.components:
            return _blocked_uncalibrated(spec, "Componentes")
        exp = ctx.state.get("exploration")
        pages = exp.pages if exp else [current_snapshot(ctx, spec)]
        missing, present = [], []
        for name, comp in cal.components.items():
            if not comp.required:
                continue
            hit = any(p.tree.match(comp.locator.to_locator()) for p in pages)
            (present if hit else missing).append(name)
        ev = [p.screenshot for p in pages] + [p.page_source for p in pages]
        st = Status.FAIL if missing else Status.PASS
        return result(spec, st, f"{len(present)} presentes; ausentes: {missing or 'ninguno'}", ev,
                      expected=len(present) + len(missing), actual=len(present),
                      defect_category="missing_component" if missing else None)

    @reg.validator("components_identified")
    def components_identified(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        exp = ctx.state.get("exploration")
        if not exp:
            return result(spec, Status.BLOCKED, "Requiere paso previo explore_home")
        inv = exp.inventory()
        s = inv["summary"]
        mn = int(spec.params.get("min", 5))
        ev = [p.screenshot for p in exp.pages]
        review = s["needs_review"] > 0
        st = Status.PASS if s["total"] >= mn else Status.FAIL
        return result(spec, st, f"{s['total']} componentes identificados por accesibilidad {s['by_category']}; "
                                f"{s['needs_review']} con baja confianza o localizador frágil", ev,
                      expected=f">={mn}", actual=s["total"], needs_human_review=review)

    @reg.validator("overlays_accessible")
    def overlays_accessible(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        """Un modal visible debe estar expuesto en el árbol de accesibilidad (TalkBack/automatización)."""
        events = ctx.state.get("overlays", [])
        ev = [e for o in events for e in o["evidence"]] or ([ctx.last_snapshot.screenshot] if ctx.last_snapshot else [])
        if not events:
            return result(spec, Status.PASS, "No se detectaron overlays sobre la pantalla principal", ev)
        hidden = [o["overlay"] for o in events if not o["in_accessibility_tree"]]
        if hidden:
            return result(spec, Status.FAIL, f"Overlay visible pero ausente del árbol de accesibilidad: {hidden} "
                                             "(un usuario de TalkBack no puede leerlo ni cerrarlo)", ev,
                          actual=events, defect_category="accessibility", needs_human_review=True)
        return result(spec, Status.PASS, f"Overlays expuestos en accesibilidad: {[o['overlay'] for o in events]}", ev)

    @reg.validator("navigation_responds")
    def navigation_responds(ctx: ExecutionContext, spec: ValidationSpec) -> ValidationResult:
        res = ctx.state.get("nav_results")
        if res is None:
            return result(spec, Status.BLOCKED, "Requiere paso previo navigate_targets")
        ev = [e for r in res for e in r.get("evidence", [])]
        failed = [r["component"] for r in res if r["status"] == "FAIL"]
        blocked = [r["component"] for r in res if r["status"] == "BLOCKED"]
        if failed:
            return result(spec, Status.FAIL, f"Sin respuesta/navegación: {failed}", ev, actual=res,
                          defect_category="unresponsive_element")
        if blocked or not res:
            return result(spec, Status.BLOCKED, f"Objetivos bloqueados: {blocked}", ev, actual=res)
        return result(spec, Status.PASS, f"{len(res)} objetivos navegaron y volvieron a la pantalla principal", ev, actual=res)
