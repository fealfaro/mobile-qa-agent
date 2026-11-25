"""Eventos de ejecución (contrato genérico para UIs en vivo: web, CLI, integraciones).

Un `EventSink` recibe dicts serializables a JSON con al menos {"type", "ts"}. Tipos emitidos:
  run_started {run_id, plan:[{case_id,name,priority,steps:[...],validations:[...]}]}
  session     {device:{...}, app:{...}}
  case_started / case_finished {case_id, status?, duration_s?}
  step_started / step_finished {case_id, step_id, action, description, status?, message?, evidence?}
  validation  {case_id, validation_id, vtype, description, status, message, severity, evidence, needs_human_review}
  screenshot  {case_id, label, path, screen_id}
  observation {case_id, level: info|warning|error, title, message, evidence?}
  run_finished {status, summary, report}
  error       {message}
Los textos se enmascaran antes de emitir.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from qa_agent.security.masking import MASKER

EventSink = Callable[[dict[str, Any]], None]
log = logging.getLogger("qa_agent")


def noop(_: dict[str, Any]) -> None:
    pass


class Emitter:
    def __init__(self, sink: EventSink | None = None) -> None:
        self.sink = sink or noop
        self.case_id: str | None = None

    def __call__(self, type_: str, **data: Any) -> None:
        if self.sink is noop:
            return
        evt = {"type": type_, "ts": time.time(), "case_id": data.pop("case_id", self.case_id), **data}
        try:
            evt = json.loads(MASKER.mask(json.dumps(evt, ensure_ascii=False, default=str)))
            self.sink(evt)
        except Exception as e:  # una UI caída nunca debe romper la ejecución
            log.debug("Evento descartado (%s): %s", type_, e)
