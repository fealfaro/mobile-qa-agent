"""Módulo home-testing: reconocimiento, recorrido y validación de la pantalla principal AS IS."""
from __future__ import annotations

from qa_agent.core.registry import Registry

MODULE = "home-testing"

# Acciones y validadores que necesitan una calibración revisada de la app (los demás funcionan sin ella).
REQUIRES_CALIBRATION = {
    "ensure_home", "navigate_targets", "tap", "wait_for",
    "home_recognized", "home_load_time", "component_present", "component_text", "component_enabled",
    "required_components", "navigation_responds", "visual_baseline", "overlays_accessible",
}


def register(reg: Registry) -> None:
    from . import actions, validators

    actions.register(reg)
    validators.register(reg)
