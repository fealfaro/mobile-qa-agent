"""Contexto de ejecución compartido por acciones y validadores."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qa_agent.config.models import AppCfg, Calibration, EnvironmentCfg
from qa_agent.core.contracts import Device, DeviceProvider, MobileDriver
from qa_agent.core.events import Emitter
from qa_agent.core.ui import Locator, UiElement
from qa_agent.evidence.store import EvidenceStore
from qa_agent.inspection.ui_tree import UiTree, parse
from qa_agent.security.policy import ActionPolicy


@dataclass
class Snapshot:
    """Estado observado de la pantalla en un instante. Es la evidencia base de toda validación."""

    label: str
    taken_at: float
    tree: UiTree
    screen_id: str
    screenshot: str            # ruta relativa al run
    page_source: str           # ruta relativa al run
    size: tuple[int, int]

    @property
    def evidence(self) -> list[str]:
        return [self.screenshot, self.page_source]


@dataclass
class ExecutionContext:
    platform: str
    device: Device
    provider: DeviceProvider
    driver: MobileDriver
    app: AppCfg
    app_id: str                          # package / bundle id resuelto
    env: EnvironmentCfg
    evidence: EvidenceStore
    policy: ActionPolicy
    calibrations: dict[str, Calibration] = field(default_factory=dict)
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("qa_agent"))
    state: dict[str, Any] = field(default_factory=dict)   # memoria entre pasos de un caso
    last_snapshot: Snapshot | None = None
    emit: Emitter = field(default_factory=Emitter)

    def calibration(self, module: str) -> Calibration | None:
        return self.calibrations.get(module)

    def snapshot(self, label: str) -> Snapshot:
        shot = self.evidence.next_path(label, "png")
        self.driver.screenshot(shot)
        xml = self.driver.page_source()
        src = self.evidence.write_text(label, "xml", xml)  # enmascarado al persistir
        snap = Snapshot(
            label=label, taken_at=time.time(), tree=parse(xml, self.platform),
            screen_id=self.driver.current_screen_id(), screenshot=self.evidence.rel(shot),
            page_source=src, size=self.driver.window_size(),
        )
        self.last_snapshot = snap
        self.emit("screenshot", label=label, path=snap.screenshot, screen_id=snap.screen_id)
        return snap

    def screenshot_only(self, label: str) -> str:
        p = self.evidence.next_path(label, "png")
        self.driver.screenshot(p)
        rel = self.evidence.rel(p)
        self.emit("screenshot", label=label, path=rel)
        return rel

    def resolve(self, module: str, component: str) -> tuple[Locator, Any] | None:
        cal = self.calibration(module)
        if not cal or component not in cal.components:
            return None
        return cal.components[component].locator.to_locator(), cal.components[component]

    def tree_find(self, loc: Locator, snap: Snapshot | None = None) -> list[UiElement]:
        snap = snap or self.last_snapshot
        return snap.tree.match(loc) if snap else []

    def abs_path(self, rel: str) -> Path:
        return self.evidence.dir / rel
