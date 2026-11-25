"""Acciones de la pantalla principal. Ninguna es transaccional; los taps solo sobre objetivos revisados."""
from __future__ import annotations

import time

from qa_agent.core.context import ExecutionContext
from qa_agent.core.registry import Registry, StepOutcome
from qa_agent.core.testcase import Step
from qa_agent.execution.session import dismiss_overlays, poll_screen, reach_screen
from qa_agent.security.policy import PolicyViolation

from . import MODULE
from .explorer import explore


def register(reg: Registry) -> None:
    @reg.action("ensure_home", description="Abre la app y llega a la pantalla principal según session.mode")
    def ensure_home(ctx: ExecutionContext, step: Step) -> StepOutcome:
        cal = ctx.calibration(MODULE)
        if not cal:
            return StepOutcome(False, "Pantalla principal sin calibrar: ejecuta `qa-agent inspect` y revisa "
                                      f"config/calibration/{MODULE}.{ctx.platform}.yaml", blocked=True)
        if ctx.driver.app_state(ctx.app_id) != 4:
            ctx.driver.activate_app(ctx.app_id)
            time.sleep(3)
        r = reach_screen(ctx, cal, "home")
        overlays = dismiss_overlays(ctx, cal) if r.reached else []
        stuck = [o["overlay"] for o in overlays if not o["cleared"]]
        if stuck:
            snap = ctx.snapshot("ensure_home_overlay")
            return StepOutcome(False, f"Pantalla principal tapado por overlay que no se pudo cerrar: {stuck}",
                               snap.evidence + [e for o in overlays for e in o["evidence"]], blocked=True)
        snap = ctx.snapshot("ensure_home")
        ctx.state["home_match"] = r.match
        detail = "; ".join(r.match.detail) if r.match else ""
        msg = f"{r.message} [{detail}] en {r.waited_s:.1f}s"
        if r.reached:
            ctx.state["home_reached_s"] = round(r.waited_s, 1)
            if overlays:
                msg += f"; overlays cerrados: {[o['overlay'] for o in overlays]}"
            return StepOutcome(True, msg, snap.evidence + [e for o in overlays for e in o["evidence"]])
        return StepOutcome(False, msg, snap.evidence, blocked=r.blocked)

    @reg.action("explore_home", description="Recorre la pantalla principal con scroll (solo lectura) e inventaría componentes")
    def explore_home(ctx: ExecutionContext, step: Step) -> StepOutcome:
        exp = explore(ctx, int(step.params.get("max_swipes", 8)))
        ctx.state["exploration"] = exp
        inv = exp.inventory()
        ev = [p.screenshot for p in exp.pages] + [ctx.evidence.write_json("home_inventory", inv)]
        s = inv["summary"]
        return StepOutcome(True, f"{inv['pages']} páginas, {s['total']} componentes "
                                 f"({s['interactive']} interactivos, {s['needs_review']} para revisión)", ev)

    @reg.action("navigate_targets", description="Pulsa cada objetivo autorizado, valida respuesta y vuelve")
    def navigate_targets(ctx: ExecutionContext, step: Step) -> StepOutcome:
        cal = ctx.calibration(MODULE)
        if not cal or not cal.navigation_targets:
            return StepOutcome(False, "Sin navigation_targets revisados en la calibración", blocked=True)
        results: list[dict] = []
        evidence: list[str] = []
        only = set(step.params.get("only", []))
        for t in cal.navigation_targets:
            if only and t.component not in only:
                continue
            res = {"component": t.component, "status": "FAIL", "message": "", "evidence": []}
            results.append(res)
            comp = cal.components.get(t.component)
            if not comp:
                res.update(status="BLOCKED", message="componente no definido en calibración")
                continue
            dismiss_overlays(ctx, cal)
            before = ctx.snapshot(f"nav_{t.component}_before")
            el = ctx.driver.find(comp.locator.to_locator(), timeout_s=5)
            if el is None and comp.scroll_to_find:
                for _ in range(5):
                    ctx.driver.swipe("up", 0.5)
                    time.sleep(1)
                    el = ctx.driver.find(comp.locator.to_locator(), timeout_s=1)
                    if el is not None:
                        before = ctx.snapshot(f"nav_{t.component}_before_scrolled")
                        break
            if el is None:
                res.update(status="FAIL", message="elemento no encontrado", evidence=before.evidence)
                evidence += before.evidence
                continue
            names = [n.name for n in before.tree.match(comp.locator.to_locator())]
            try:
                ctx.policy.check_tap_target(t.component, *names)
            except PolicyViolation as e:
                res.update(status="BLOCKED", message=str(e))
                continue
            ctx.driver.tap_element(el)
            time.sleep(t.settle_s)
            after = ctx.snapshot(f"nav_{t.component}_after")
            sig_b, sig_a = before.tree.signature(), after.tree.signature()
            change = 1 - len(sig_a & sig_b) / max(len(sig_a | sig_b), 1)
            screen_changed = after.screen_id != before.screen_id or change > 0.35
            responded = screen_changed or change > 0.05
            ok = screen_changed if t.expect == "screen_change" else responded
            res.update(status="PASS" if ok else "FAIL", change_ratio=round(change, 2),
                       screen_before=before.screen_id, screen_after=after.screen_id,
                       message=("navegó" if screen_changed else "respuesta parcial" if responded else "sin respuesta"),
                       evidence=before.evidence + after.evidence)
            evidence += res["evidence"]
            # volver a la pantalla principal
            ctx.driver.back()
            time.sleep(1.5)
            m, _ = poll_screen(ctx, cal, "home", 8)
            if not (m and m.matched) and ctx.driver.app_state(ctx.app_id) != 4:
                ctx.driver.activate_app(ctx.app_id)
                m, _ = poll_screen(ctx, cal, "home", 10)
            if not (m and m.matched) and cal.home_component in cal.components:
                home = ctx.driver.find(cal.components[cal.home_component].locator.to_locator(), timeout_s=3)
                if home is not None:
                    ctx.driver.tap_element(home)
                    m, _ = poll_screen(ctx, cal, "home", 12)
                    res["returned_with"] = cal.home_component
            # Deshacer el scroll hecho para encontrar el objetivo.
            for _ in range(3):
                ctx.driver.swipe("down", 0.8)
            res["returned_to_home"] = bool(m and m.matched)
            if not res["returned_to_home"]:
                res["message"] += "; no se pudo volver a la pantalla principal"
                break
        ctx.state["nav_results"] = results
        evidence.append(ctx.evidence.write_json("navigation_results", results))
        passed = sum(1 for r in results if r["status"] == "PASS")
        return StepOutcome(True, f"{passed}/{len(results)} objetivos respondieron", evidence)
