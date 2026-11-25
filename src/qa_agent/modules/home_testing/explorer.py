"""Recorrido de solo lectura de la pantalla principal: scroll + snapshots + inventario de componentes."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from qa_agent.core.context import ExecutionContext, Snapshot
from qa_agent.inspection.classifier import Component, classify, summarize


@dataclass
class Exploration:
    pages: list[Snapshot] = field(default_factory=list)
    components: list[tuple[int, Component]] = field(default_factory=list)   # (página, componente)
    reached_end: bool = False

    def inventory(self) -> dict:
        comps = [c for _, c in self.components]
        return {
            "pages": len(self.pages),
            "reached_end": self.reached_end,
            "summary": summarize(comps),
            "components": [{"page": p, **c.to_dict()} for p, c in self.components],
        }


def _key(c: Component) -> str:
    e = c.element
    return f"{e.short_cls}|{e.resource_id}|{e.name[:60]}"


def explore(ctx: ExecutionContext, max_swipes: int = 8, label: str = "dash") -> Exploration:
    exp = Exploration()
    seen: set[str] = set()
    prev_sig: set[str] | None = None
    for i in range(max_swipes + 1):
        snap = ctx.snapshot(f"{label}_page{i}")
        sig = snap.tree.signature()
        if prev_sig is not None:
            overlap = len(sig & prev_sig) / max(len(sig), 1)
            if overlap > 0.9:          # el contenido no cambió: fin del scroll
                exp.reached_end = True
                break
        exp.pages.append(snap)
        w, h = snap.size
        for c in classify(snap.tree, w, h):
            k = _key(c)
            if k not in seen:
                seen.add(k)
                exp.components.append((i, c))
        prev_sig = sig
        if i < max_swipes:
            ctx.driver.swipe("up", 0.6)
            time.sleep(1.2)
    # volver arriba
    for _ in range(len(exp.pages)):
        ctx.driver.swipe("down", 0.8)
        time.sleep(0.4)
    # El último snapshot es de la parte inferior: invalidarlo para que las validaciones capturen de nuevo.
    ctx.last_snapshot = None
    return exp
