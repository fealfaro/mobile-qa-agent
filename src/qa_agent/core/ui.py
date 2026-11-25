"""Representación de UI independiente de plataforma (Android UiAutomator2 / iOS XCUITest)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Bounds:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    @property
    def area(self) -> int:
        return max(self.w, 0) * max(self.h, 0)


@dataclass
class UiElement:
    """Nodo normalizado del árbol de accesibilidad."""

    index: int                  # orden en recorrido DFS (estable dentro de un snapshot)
    depth: int
    platform: str
    cls: str                    # android.widget.Button / XCUIElementTypeButton
    text: str = ""
    label: str = ""             # content-desc (Android) / label (iOS)
    resource_id: str = ""       # resource-id (Android) / name (iOS)
    bounds: Bounds | None = None
    clickable: bool = False
    enabled: bool = True
    displayed: bool = True
    focusable: bool = False
    scrollable: bool = False
    checkable: bool = False
    selected: bool = False
    parent_index: int | None = None
    children: list[int] = field(default_factory=list)
    xpath: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def short_cls(self) -> str:
        return self.cls.rsplit(".", 1)[-1].replace("XCUIElementType", "")

    @property
    def name(self) -> str:
        """Mejor nombre accesible disponible."""
        return (self.label or self.text or "").strip()

    @property
    def interactive(self) -> bool:
        return self.clickable or self.checkable or self.short_cls in {
            "Button", "ImageButton", "Switch", "CheckBox", "Link", "Cell", "Tab", "TabBarButton",
        }

    def to_dict(self) -> dict[str, Any]:
        b = self.bounds
        return {
            "index": self.index,
            "class": self.cls,
            "text": self.text,
            "label": self.label,
            "resource_id": self.resource_id,
            "bounds": [b.x, b.y, b.w, b.h] if b else None,
            "clickable": self.clickable,
            "enabled": self.enabled,
            "displayed": self.displayed,
            "scrollable": self.scrollable,
            "xpath": self.xpath,
        }


@dataclass
class Locator:
    """Localizador declarativo. `strategy` ∈ {id, accessibility_id, text, text_contains, xpath, class}."""

    strategy: str
    value: str

    def describe(self) -> str:
        return f"{self.strategy}={self.value!r}"
