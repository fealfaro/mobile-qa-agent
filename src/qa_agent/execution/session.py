"""Gestión de sesión/autenticación reutilizable por cualquier módulo.

Modos (config/apps/<app>.yaml -> session.mode):
  existing    la cuenta de prueba ya está logueada en el dispositivo; si no, BLOCKED.
  manual      el agente espera a que un operador autorizado complete el login (OTP, etc.).
  credentials el agente completa el login con `login_flow` calibrado + secretos.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from qa_agent.config.models import Calibration
from qa_agent.core.context import ExecutionContext
from qa_agent.inspection.screens import ScreenMatch, match_screen
from qa_agent.inspection.ui_tree import parse
from qa_agent.security.secrets import get_secret


@dataclass
class ReachResult:
    reached: bool
    blocked: bool
    message: str
    match: ScreenMatch | None = None
    waited_s: float = 0.0


def poll_screen(ctx: ExecutionContext, cal: Calibration, screen: str, timeout_s: float,
                interval_s: float = 1.5) -> tuple[ScreenMatch | None, float]:
    sig = cal.screens.get(screen)
    if not sig:
        return None, 0.0
    t0 = time.time()
    last: ScreenMatch | None = None
    while True:
        tree = parse(ctx.driver.page_source(), ctx.platform)
        last = match_screen(tree, ctx.driver.current_screen_id(), sig)
        if last.matched or time.time() - t0 >= timeout_s:
            return last, time.time() - t0
        time.sleep(interval_s)


def _region_brightness(path, region: list[float]) -> float:
    from PIL import Image, ImageStat

    with Image.open(path) as im:
        w, h = im.size
        x, y, rw, rh = region
        box = (int(x * w), int(y * h), int((x + rw) * w), int((y + rh) * h))
        return float(ImageStat.Stat(im.convert("L").crop(box)).mean[0])


def _overlay_present(ctx: ExecutionContext, ov) -> tuple[bool, str, str]:
    """Devuelve (presente, detalle, screenshot_rel)."""
    shot = ctx.evidence.next_path(f"overlay_check_{ov.name}", "png")
    ctx.driver.screenshot(shot)
    rel = ctx.evidence.rel(shot)
    if ov.detect_locator and ctx.driver.find(ov.detect_locator.to_locator()) is not None:
        return True, f"localizador {ov.detect_locator.value}", rel
    if ov.detect_dim_region:
        b = _region_brightness(shot, ov.detect_dim_region)
        if b < ov.max_brightness:
            return True, f"región oscurecida (brillo {b:.0f} < {ov.max_brightness:.0f})", rel
    return False, "", rel


def dismiss_overlays(ctx: ExecutionContext, cal: Calibration) -> list[dict]:
    """Cierra modales calibrados. Devuelve un registro por overlay detectado (con evidencia)."""
    events: list[dict] = []
    for ov in cal.overlays:
        for attempt in range(ov.max_attempts):
            present, detail, shot = _overlay_present(ctx, ov)
            if not present:
                if attempt:
                    events[-1]["cleared"] = True
                    events[-1]["evidence"].append(shot)
                break
            tree = parse(ctx.driver.page_source(), ctx.platform)
            ev = {"overlay": ov.name, "detail": detail, "attempt": attempt + 1, "cleared": False,
                  "in_accessibility_tree": bool(ov.detect_locator and tree.match(ov.detect_locator.to_locator())),
                  "evidence": [shot]}
            events.append(ev)
            ctx.emit("observation", level="warning", title=f"Overlay '{ov.name}' sobre la pantalla",
                     message=f"Detectado por {detail}; el agente lo cerrará" +
                             ("" if ev["in_accessibility_tree"] else ". No está expuesto en accesibilidad."),
                     evidence=[shot])
            ctx.log.info("Overlay '%s' detectado (%s); cerrando (intento %s)", ov.name, detail, attempt + 1)
            if ov.dismiss_locator:
                el = ctx.driver.find(ov.dismiss_locator.to_locator(), timeout_s=2)
                if el is None:
                    break
                ctx.policy.check_tap_target(ov.name)
                ctx.driver.tap_element(el)
            elif ov.dismiss_point:
                ctx.policy.check_tap_target(ov.name)
                # Coordenadas de pantalla completa (las del screenshot), no del viewport de la app.
                from PIL import Image

                with Image.open(ctx.abs_path(shot)) as im:
                    w, h = im.size
                ctx.driver.tap_point(int(ov.dismiss_point[0] * w), int(ov.dismiss_point[1] * h))
            else:
                break
            time.sleep(2)
        else:
            present, _, shot = _overlay_present(ctx, ov)
            if events and events[-1]["overlay"] == ov.name:
                events[-1]["cleared"] = not present
                events[-1]["evidence"].append(shot)
    ctx.state.setdefault("overlays", []).extend(events)
    return events


def _login_with_credentials(ctx: ExecutionContext, cal: Calibration) -> str | None:
    lf = cal.login_flow
    if not (lf.username_field and lf.password_field and lf.submit):
        return "login_flow no calibrado (username_field/password_field/submit)"
    user = get_secret("QA_USERNAME")
    pwd = get_secret("QA_PASSWORD")
    for loc in lf.pre_taps:
        el = ctx.driver.find(loc.to_locator(), timeout_s=10)
        if el is None:
            return f"pre_tap {loc.strategy}={loc.value} no encontrado"
        ctx.driver.tap_element(el)
        time.sleep(1.5)
    for loc, value in ((lf.username_field, user), (lf.password_field, pwd)):
        el = ctx.driver.find(loc.to_locator(), timeout_s=15)
        if el is None:
            return f"campo {loc.strategy}={loc.value} no encontrado"
        ctx.driver.type_text(el, value or "")
    ctx.driver.hide_keyboard()
    btn = ctx.driver.find(lf.submit.to_locator(), timeout_s=5)
    if btn is None:
        return "botón submit no encontrado"
    ctx.driver.tap_element(btn)
    return None


def reach_screen(ctx: ExecutionContext, cal: Calibration, screen: str = "home") -> ReachResult:
    mode = ctx.app.session.mode
    timeout = ctx.app.session.home_timeout_s
    if screen not in cal.screens:
        return ReachResult(False, True, f"Pantalla '{screen}' sin firma calibrada")

    m, waited = poll_screen(ctx, cal, screen, timeout)
    if m and m.matched:
        return ReachResult(True, False, f"Pantalla '{screen}' reconocida ({m.hits}/{m.total})", m, waited)

    if mode == "existing":
        return ReachResult(False, True, f"'{screen}' no alcanzado en {timeout}s con session.mode=existing "
                                         "(¿la cuenta de prueba no está logueada?)", m, waited)
    if mode == "credentials":
        err = _login_with_credentials(ctx, cal)
        if err:
            return ReachResult(False, True, f"Login automático no posible: {err}", m, waited)
        m, w2 = poll_screen(ctx, cal, screen, timeout)
        ok = bool(m and m.matched)
        return ReachResult(ok, False, "Pantalla principal alcanzado tras login" if ok else "Login ejecutado pero Pantalla principal no reconocido",
                           m, waited + w2)
    # manual
    ctx.log.warning(">>> INTERVENCIÓN HUMANA: inicia sesión en el dispositivo con la cuenta de prueba autorizada. "
                    "Esperando hasta %ss a que aparezca '%s'...", ctx.app.session.manual_timeout_s, screen)
    m, w2 = poll_screen(ctx, cal, screen, ctx.app.session.manual_timeout_s, interval_s=3)
    ok = bool(m and m.matched)
    return ReachResult(ok, not ok, "Pantalla principal alcanzado tras login manual" if ok else "Timeout de login manual",
                       m, waited + w2)
