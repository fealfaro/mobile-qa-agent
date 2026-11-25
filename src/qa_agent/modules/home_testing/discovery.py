"""Descubrimiento (sin calibración): inspecciona la app real y genera una calibración BORRADOR.

El borrador nunca se usa en ejecuciones hasta que un humano lo revisa y lo guarda como
config/calibration/home-testing.<platform>.yaml con `status: reviewed`.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

import yaml

from qa_agent.config.models import calibration_path
from qa_agent.core.context import ExecutionContext
from qa_agent.inspection.classifier import Component
from qa_agent.security.masking import MASKER

from . import MODULE
from .explorer import Exploration, explore

_SIG_CATEGORIES = ("header", "bottom_nav", "bottom_nav_item", "header_action", "button", "text")


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:32] or "x"


def _comp_name(c: Component, used: set[str]) -> str:
    base = f"{c.category}_{_slug(c.element.name or c.element.resource_id.rsplit('/', 1)[-1] or str(c.element.index))}"
    name, i = base, 2
    while name in used:
        name, i = f"{base}_{i}", i + 1
    used.add(name)
    return name


def build_draft(ctx: ExecutionContext, exp: Exploration, app_version: str | None) -> dict:
    first = [c for p, c in exp.components if p == 0]
    stable = [c for c in first if c.locator_quality == "stable" and c.category in _SIG_CATEGORIES
              and not ctx.policy.denied_keyword(c.element.name)]
    stable.sort(key=lambda c: _SIG_CATEGORIES.index(c.category))
    sig = [c.suggested_locator for c in stable[:6]]

    used: set[str] = set()
    components: dict = {}
    nav_candidates: list[dict] = []
    for page, c in exp.components:
        if c.category == "text" or c.locator_quality in ("none",):
            continue
        name = _comp_name(c, used)
        components[name] = {
            "locator": c.suggested_locator,
            "category": c.category,
            "required": False,
            "scroll_to_find": page > 0,
            "notes": f"conf={c.confidence:.2f} loc={c.locator_quality} page={page} name={c.element.name!r}",
        }
        if c.element.interactive:
            denied = ctx.policy.denied_keyword(c.element.name, name)
            nav_candidates.append({"component": name, "denied_by_policy": denied, "label": c.element.name})

    return {
        "module": MODULE,
        "platform": ctx.platform,
        "app_version": app_version,
        "calibrated_by": "",
        "calibrated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "draft",
        "screens": {"home": {
            "locators": sig,
            "min_matches": max(1, math.ceil(len(sig) * 0.6)),
            "screen_ids": [exp.pages[0].screen_id] if exp.pages and exp.pages[0].screen_id else [],
        }},
        "components": components,
        "navigation_targets": [],
        "navigation_candidates": nav_candidates,
        "loading_indicators": [],
        "error_indicators": [],
        "login_flow": {},
    }


def discover(ctx: ExecutionContext, app_version: str | None, max_swipes: int = 8) -> tuple[Exploration, Path, dict]:
    exp = explore(ctx, max_swipes=max_swipes, label="discover")
    draft = build_draft(ctx, exp, app_version)
    out = calibration_path(ctx.app.id, MODULE, ctx.platform, draft=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# BORRADOR generado automáticamente desde la app real. NO se usa hasta revisarlo.\n"
        "# 1) Verifica que la firma 'home' identifica inequívocamente la pantalla principal.\n"
        "# 2) Renombra componentes, marca required: true los que deben existir siempre.\n"
        "# 3) Copia a navigation_targets SOLO elementos no transaccionales (desde navigation_candidates).\n"
        f"# 4) Guarda como {MODULE}.{ctx.platform}.yaml con status: reviewed y calibrated_by.\n"
    )
    body = MASKER.mask(yaml.safe_dump(draft, allow_unicode=True, sort_keys=False, width=140))
    out.write_text(header + body, encoding="utf-8")
    return exp, out, draft
