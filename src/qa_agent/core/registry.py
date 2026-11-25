"""Registro de acciones, validadores y módulos.

El core solo conoce este registro. Cada módulo de negocio (home, tienda, ...) aporta
sus acciones/validadores llamando a `register(registry)` sin modificar el core.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .context import ExecutionContext
    from .results import ValidationResult
    from .testcase import Step, ValidationSpec


@dataclass
class StepOutcome:
    ok: bool
    message: str = ""
    evidence: list[str] = field(default_factory=list)
    blocked: bool = False         # precondición/entorno impide continuar
    inconclusive: bool = False


ActionHandler = Callable[["ExecutionContext", "Step"], StepOutcome]
ValidatorFn = Callable[["ExecutionContext", "ValidationSpec"], "ValidationResult"]


@dataclass
class ActionDef:
    name: str
    handler: ActionHandler
    transactional: bool = False   # True => bloqueada por la política de seguridad del MVP
    description: str = ""


class Registry:
    def __init__(self) -> None:
        self.actions: dict[str, ActionDef] = {}
        self.validators: dict[str, ValidatorFn] = {}
        self.modules: set[str] = set()

    def action(self, name: str, *, transactional: bool = False, description: str = ""):
        def deco(fn: ActionHandler) -> ActionHandler:
            if name in self.actions:
                raise ValueError(f"Acción duplicada: {name}")
            self.actions[name] = ActionDef(name, fn, transactional, description)
            return fn
        return deco

    def validator(self, name: str):
        def deco(fn: ValidatorFn) -> ValidatorFn:
            if name in self.validators:
                raise ValueError(f"Validador duplicado: {name}")
            self.validators[name] = fn
            return fn
        return deco

    def load_module(self, name: str) -> None:
        """Carga `qa_agent.modules.<name>` (paquete con función `register(registry)`)."""
        if name in self.modules:
            return
        mod = importlib.import_module(f"qa_agent.modules.{name.replace('-', '_')}")
        mod.register(self)
        self.modules.add(name)


def build_registry(modules: list[str]) -> Registry:
    from qa_agent.execution import builtin_actions
    from qa_agent.validation import builtin_validators

    reg = Registry()
    builtin_actions.register(reg)
    builtin_validators.register(reg)
    for m in modules:
        reg.load_module(m)
    return reg
