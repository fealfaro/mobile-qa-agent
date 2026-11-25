"""Parser del page source de Appium (Android UiAutomator2 / iOS XCUITest) a UiElement normalizados."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from qa_agent.core.ui import Bounds, Locator, UiElement

_ANDROID_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _b(v: str | None) -> bool:
    return (v or "").lower() == "true"


@dataclass
class UiTree:
    platform: str
    elements: list[UiElement]

    @property
    def visible(self) -> list[UiElement]:
        return [e for e in self.elements if e.displayed and e.bounds and e.bounds.area > 0]

    @property
    def interactive(self) -> list[UiElement]:
        return [e for e in self.visible if e.interactive]

    def match(self, loc: Locator) -> list[UiElement]:
        s, v = loc.strategy, loc.value
        if s == "id":
            return [e for e in self.elements if e.resource_id == v or e.resource_id.endswith(":id/" + v)]
        if s == "accessibility_id":
            if self.platform == "ios":  # en XCUITest el accessibility id es el atributo `name`
                return [e for e in self.elements if e.resource_id == v]
            return [e for e in self.elements if e.label == v]
        if s == "text":
            return [e for e in self.elements if e.text == v or e.label == v]
        if s == "text_contains":
            lv = v.lower()
            return [e for e in self.elements if lv in e.text.lower() or lv in e.label.lower()]
        if s == "class":
            return [e for e in self.elements if e.cls == v or e.short_cls == v]
        if s == "xpath":
            return [e for e in self.elements if e.xpath == v]
        raise ValueError(f"Estrategia de localizador no soportada: {s}")

    def texts(self) -> list[str]:
        return [e.name for e in self.visible if e.name]

    def signature(self) -> set[str]:
        """Huella estructural para detectar cambios de pantalla (ids + clases + nombres visibles)."""
        return {f"{e.short_cls}|{e.resource_id}|{e.name[:40]}" for e in self.visible}


def parse(xml: str, platform: str) -> UiTree:
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    elements: list[UiElement] = []

    def walk(node: ET.Element, depth: int, parent: int | None, path: str) -> None:
        a = node.attrib
        idx = len(elements)
        if platform == "android":
            tag_cls = a.get("class", node.tag)
            m = _ANDROID_BOUNDS.match(a.get("bounds", ""))
            bounds = Bounds(int(m[1]), int(m[2]), int(m[3]) - int(m[1]), int(m[4]) - int(m[2])) if m else None
            el = UiElement(
                index=idx, depth=depth, platform=platform, cls=tag_cls,
                text="" if _b(a.get("password")) else a.get("text", ""),
                label=a.get("content-desc", ""), resource_id=a.get("resource-id", ""), bounds=bounds,
                clickable=_b(a.get("clickable")), enabled=_b(a.get("enabled", "true")),
                displayed=_b(a.get("displayed", "true")), focusable=_b(a.get("focusable")),
                scrollable=_b(a.get("scrollable")), checkable=_b(a.get("checkable")),
                selected=_b(a.get("selected")), parent_index=parent, xpath=path,
                raw={k: a.get(k, "") for k in ("package", "hint", "long-clickable", "password")},
            )
        else:
            try:
                bounds = Bounds(int(a.get("x", 0)), int(a.get("y", 0)), int(a.get("width", 0)), int(a.get("height", 0)))
            except ValueError:
                bounds = None
            cls = a.get("type", node.tag)
            el = UiElement(
                index=idx, depth=depth, platform=platform, cls=cls,
                text=a.get("value", "") if cls != "XCUIElementTypeSecureTextField" else "",
                label=a.get("label", ""), resource_id=a.get("name", ""), bounds=bounds,
                clickable=_b(a.get("accessible")) and cls.endswith(("Button", "Cell", "Link", "Switch")),
                enabled=_b(a.get("enabled", "true")), displayed=_b(a.get("visible", "true")),
                parent_index=parent, xpath=path,
            )
        elements.append(el)
        if parent is not None:
            elements[parent].children.append(idx)
        counters: dict[str, int] = {}
        for child in node:
            counters[child.tag] = counters.get(child.tag, 0) + 1
            walk(child, depth + 1, idx, f"{path}/{child.tag}[{counters[child.tag]}]")

    start_nodes = list(root) if root.tag in ("hierarchy", "AppiumAUT") else [root]
    counters: dict[str, int] = {}
    for n in start_nodes:
        counters[n.tag] = counters.get(n.tag, 0) + 1
        walk(n, 0, None, f"/{root.tag}/{n.tag}[{counters[n.tag]}]" if root.tag != n.tag else f"/{n.tag}")
    return UiTree(platform, elements)
