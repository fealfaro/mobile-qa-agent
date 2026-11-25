"""Reconocimiento de pantallas por firma calibrada (localizadores + Activity opcional)."""
from __future__ import annotations

from dataclasses import dataclass

from qa_agent.config.models import ScreenSignature

from .ui_tree import UiTree


@dataclass
class ScreenMatch:
    matched: bool
    hits: int
    required: int
    total: int
    detail: list[str]

    @property
    def confidence(self) -> float:
        return round(self.hits / self.total, 2) if self.total else 0.0


def match_screen(tree: UiTree, screen_id: str, sig: ScreenSignature) -> ScreenMatch:
    detail: list[str] = []
    hits = 0
    for loc in sig.locators:
        found = bool(tree.match(loc.to_locator()))
        hits += found
        detail.append(f"{'✓' if found else '✗'} {loc.strategy}={loc.value}")
    id_ok = True
    if sig.screen_ids:
        id_ok = any(screen_id.endswith(s) for s in sig.screen_ids)
        detail.append(f"{'✓' if id_ok else '✗'} screen_id={screen_id} ∈ {sig.screen_ids}")
    required = min(sig.min_matches, len(sig.locators)) if sig.locators else 0
    matched = bool(sig.locators) and hits >= required and id_ok
    return ScreenMatch(matched, hits, required, len(sig.locators), detail)
