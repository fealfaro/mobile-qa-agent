"""Clasificación heurística y genérica de componentes de pantalla a partir del árbol de accesibilidad.

No contiene selectores de ninguna app concreta: usa clase, posición, tamaño e interactividad.
Cada clasificación lleva una confianza; bajo el umbral se marca para revisión humana.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from qa_agent.core.ui import UiElement

from .ui_tree import UiTree

CONFIDENCE_THRESHOLD = 0.6
_DYNAMIC_TEXT = re.compile(r"\d")  # textos con dígitos suelen ser dinámicos (saldos, fechas, números)


@dataclass
class Component:
    category: str
    element: UiElement
    confidence: float
    reasons: list[str] = field(default_factory=list)
    suggested_locator: dict | None = None
    locator_quality: str = "none"     # stable | medium | fragile | none

    @property
    def needs_review(self) -> bool:
        return self.confidence < CONFIDENCE_THRESHOLD or self.locator_quality in ("fragile", "none")

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "name": self.element.name,
            "class": self.element.short_cls,
            "resource_id": self.element.resource_id,
            "bounds": self.element.to_dict()["bounds"],
            "clickable": self.element.clickable,
            "enabled": self.element.enabled,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
            "suggested_locator": self.suggested_locator,
            "locator_quality": self.locator_quality,
            "needs_review": self.needs_review,
        }


def suggest_locator(tree: UiTree, el: UiElement) -> tuple[dict | None, str]:
    ids = Counter(e.resource_id for e in tree.elements if e.resource_id)
    labels = Counter(e.label for e in tree.elements if e.label)
    texts = Counter(e.text for e in tree.elements if e.text)
    if el.resource_id and ids[el.resource_id] == 1:
        return {"strategy": "id", "value": el.resource_id}, "stable"
    if el.label and labels[el.label] == 1:
        q = "medium" if _DYNAMIC_TEXT.search(el.label) else "stable"
        return {"strategy": "accessibility_id", "value": el.label}, q
    if el.text and texts[el.text] == 1 and not _DYNAMIC_TEXT.search(el.text):
        return {"strategy": "text", "value": el.text}, "medium"
    if el.xpath:
        return {"strategy": "xpath", "value": el.xpath}, "fragile"
    return None, "none"


def _descendant_names(tree: UiTree, el: UiElement, limit: int = 4) -> list[str]:
    out: list[str] = []
    stack = list(el.children)
    while stack and len(out) < limit:
        c = tree.elements[stack.pop(0)]
        if c.name:
            out.append(c.name)
        stack.extend(c.children)
    return out


def classify(tree: UiTree, screen_w: int, screen_h: int) -> list[Component]:
    comps: list[Component] = []
    visible = tree.visible
    claimed: set[int] = set()

    def add(cat: str, el: UiElement, conf: float, *reasons: str) -> None:
        loc, q = suggest_locator(tree, el)
        comps.append(Component(cat, el, conf, list(reasons), loc, q))
        claimed.add(el.index)

    # 1) Clases con semántica inequívoca
    for el in visible:
        c = el.short_cls
        if c in ("ProgressBar", "ActivityIndicator") or "progress" in el.resource_id.lower() or "shimmer" in el.resource_id.lower():
            add("loading_indicator", el, 0.95 if "Progress" in c or "Activity" in c else 0.7, f"clase {c}")
        elif c in ("WebView",):
            add("webview", el, 0.95, "contenido híbrido (WebView)")
        elif c in ("EditText", "TextField", "SecureTextField", "SearchField"):
            add("input", el, 0.95, f"clase {c}")
        elif c in ("TabBar", "BottomNavigationView") or re.search(r"bottom.?nav|tab.?bar|navigation.?bar", el.resource_id, re.I):
            add("bottom_nav", el, 0.9, f"clase/id de navegación ({c} {el.resource_id})")
        elif c in ("Toolbar", "NavigationBar", "ActionBar") or re.search(r"toolbar|app.?bar|header", el.resource_id, re.I):
            add("header", el, 0.85, f"clase/id de cabecera ({c} {el.resource_id})")

    # 2) Navegación inferior por posición: ≥3 interactivos alineados en el 12% inferior
    bottom = [e for e in visible if e.interactive and e.index not in claimed and e.bounds
              and e.bounds.y >= screen_h * 0.85 and e.bounds.h < screen_h * 0.15]
    rows = Counter(e.bounds.cy // 20 for e in bottom)
    for row, n in rows.items():
        if n >= 3:
            for e in bottom:
                if e.bounds.cy // 20 == row:
                    add("bottom_nav_item", e, 0.8, f"{n} elementos interactivos alineados en la franja inferior")

    # 3) Elementos interactivos restantes
    for el in visible:
        if el.index in claimed or not el.interactive or not el.bounds:
            continue
        b, c = el.bounds, el.short_cls
        wide = b.w >= screen_w * 0.85
        names = [el.name] if el.name else _descendant_names(tree, el)
        if c in ("Button", "ImageButton", "Link"):
            add("button", el, 0.85 if el.name else 0.6, f"clase {c}", "sin nombre accesible" if not el.name else "")
        elif b.y < screen_h * 0.12 and b.h < screen_h * 0.12:
            add("header_action", el, 0.65, "interactivo en la franja superior")
        elif wide and screen_h * 0.12 <= b.h <= screen_h * 0.4 and not names:
            add("banner", el, 0.55, "interactivo ancho sin texto (posible imagen/banner)")
        elif b.w >= screen_w * 0.4 and b.h >= screen_h * 0.06 and names:
            add("card", el, 0.65, f"contenedor interactivo con contenido: {names[:2]}")
        elif names:
            add("shortcut", el, 0.6, f"interactivo pequeño con nombre: {names[:1]}")
        else:
            add("unknown_interactive", el, 0.3, "interactivo sin nombre ni rol reconocible")

    # 4) Banners no interactivos (imágenes anchas)
    for el in visible:
        if el.index in claimed or not el.bounds:
            continue
        if el.short_cls in ("ImageView", "Image") and el.bounds.w >= screen_w * 0.85 and screen_h * 0.12 <= el.bounds.h <= screen_h * 0.4:
            add("banner", el, 0.5, "imagen ancha")

    # 5) Textos informativos
    for el in visible:
        if el.index in claimed or el.interactive or not el.text:
            continue
        if el.short_cls in ("TextView", "StaticText", "Text"):
            add("text", el, 0.9, "texto visible")

    comps.sort(key=lambda c: (c.element.bounds.y if c.element.bounds else 0, c.element.bounds.x if c.element.bounds else 0))
    for c in comps:
        c.reasons = [r for r in c.reasons if r]
    return comps


def summarize(comps: list[Component]) -> dict:
    by_cat = Counter(c.category for c in comps)
    return {
        "total": len(comps),
        "by_category": dict(sorted(by_cat.items())),
        "interactive": sum(1 for c in comps if c.element.interactive),
        "needs_review": sum(1 for c in comps if c.needs_review),
        "with_accessible_name": sum(1 for c in comps if c.element.name),
    }
