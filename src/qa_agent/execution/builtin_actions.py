"""Acciones genéricas (independientes de journey). Todas son de lectura o navegación no transaccional."""
from __future__ import annotations

import time

from qa_agent.core.context import ExecutionContext
from qa_agent.core.registry import Registry, StepOutcome
from qa_agent.core.testcase import Step
from qa_agent.core.ui import Locator

MAX_WAIT_S = 60


def _target_locator(ctx: ExecutionContext, step: Step) -> tuple[Locator | None, str]:
    if step.target:
        r = ctx.resolve(ctx.state.get("module", ""), step.target)
        if not r:
            return None, f"Componente '{step.target}' no calibrado (ver config/calibration)"
        return r[0], step.target
    loc = step.params.get("locator")
    if loc:
        return Locator(loc["strategy"], loc["value"]), Locator(loc["strategy"], loc["value"]).describe()
    return None, "El paso no define target ni locator"


def _attr(el, name: str) -> str:
    try:
        return el.get_attribute(name) or ""
    except Exception:
        return ""


def register(reg: Registry) -> None:
    @reg.action("launch_app", description="Abre la app bajo prueba (sin borrar datos)")
    def launch_app(ctx: ExecutionContext, step: Step) -> StepOutcome:
        ctx.driver.activate_app(ctx.app_id)
        time.sleep(float(step.params.get("settle_s", 3)))
        state = ctx.driver.app_state(ctx.app_id)
        ctx.state["app_state_after_launch"] = state
        ev = [ctx.screenshot_only("launch")]
        if state != 4:
            return StepOutcome(False, f"App no quedó en primer plano (app_state={state})", ev)
        return StepOutcome(True, "App en primer plano (app_state=4)", ev)

    @reg.action("restart_app", description="Cierra y vuelve a abrir la app")
    def restart_app(ctx: ExecutionContext, step: Step) -> StepOutcome:
        ctx.driver.terminate_app(ctx.app_id)
        time.sleep(1)
        return launch_app(ctx, step)

    @reg.action("wait", description="Espera fija acotada")
    def wait(ctx: ExecutionContext, step: Step) -> StepOutcome:
        s = min(float(step.params.get("seconds", 1)), MAX_WAIT_S)
        time.sleep(s)
        return StepOutcome(True, f"Esperó {s}s")

    @reg.action("capture", description="Screenshot + árbol de accesibilidad")
    def capture(ctx: ExecutionContext, step: Step) -> StepOutcome:
        snap = ctx.snapshot(step.params.get("label", step.id))
        return StepOutcome(True, f"{len(snap.tree.visible)} elementos visibles", snap.evidence)

    @reg.action("back", description="Navegación atrás")
    def back(ctx: ExecutionContext, step: Step) -> StepOutcome:
        ctx.driver.back()
        time.sleep(float(step.params.get("settle_s", 1.5)))
        return StepOutcome(True, "Back ejecutado", [ctx.screenshot_only("after_back")])

    @reg.action("swipe", description="Desplazamiento (up/down/left/right)")
    def swipe(ctx: ExecutionContext, step: Step) -> StepOutcome:
        direction = step.params.get("direction", "up")
        ctx.driver.swipe(direction, float(step.params.get("ratio", 0.5)))
        time.sleep(1)
        return StepOutcome(True, f"Swipe {direction}", [ctx.screenshot_only(f"swipe_{direction}")])

    @reg.action("wait_for", description="Espera a que aparezca un componente calibrado")
    def wait_for(ctx: ExecutionContext, step: Step) -> StepOutcome:
        loc, desc = _target_locator(ctx, step)
        if not loc:
            return StepOutcome(False, desc, blocked=True)
        t = min(float(step.params.get("timeout_s", 15)), MAX_WAIT_S)
        found = ctx.driver.find(loc, timeout_s=t)
        ev = [ctx.screenshot_only(f"wait_for_{step.id}")]
        return StepOutcome(found is not None, f"{desc} {'encontrado' if found else f'no apareció en {t}s'}", ev)

    @reg.action("tap", description="Pulsa un componente calibrado y revisado (con control de política)")
    def tap(ctx: ExecutionContext, step: Step) -> StepOutcome:
        loc, desc = _target_locator(ctx, step)
        if not loc:
            return StepOutcome(False, desc, blocked=True)
        el = ctx.driver.find(loc, timeout_s=float(step.params.get("timeout_s", 5)))
        if el is None:
            return StepOutcome(False, f"{desc} no encontrado", [ctx.screenshot_only("tap_not_found")])
        labels = [_attr(el, a) for a in (("text", "content-desc") if ctx.platform == "android" else ("label", "name", "value"))]
        ctx.policy.check_tap_target(desc, *labels)
        ctx.driver.tap_element(el)
        time.sleep(float(step.params.get("settle_s", 2)))
        return StepOutcome(True, f"Tap en {desc}", [ctx.screenshot_only(f"after_tap_{step.id}")])
