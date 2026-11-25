"""Análisis de resultados (Intelligence Layer).

MVP: análisis determinista por reglas (clasificación de defectos + cola de revisión humana).
Sprint 4: si LLM_PROVIDER != none, se agrega una explicación generada por IA. La IA solo
produce texto; no cambia estados ni ejecuta acciones.
"""
from __future__ import annotations

from qa_agent.core.results import RunResult
from qa_agent.core.status import Status

from .providers import get_provider

CATEGORY_HINTS = {
    "crash": "La app terminó inesperadamente o tuvo ANR. Revisar logcat adjunto (FATAL EXCEPTION).",
    "loading_stuck": "La pantalla quedó cargando. Posible backend lento/caído o spinner no ocultado.",
    "missing_component": "Un componente calibrado no apareció. Puede ser cambio de versión, segmentación del cliente o defecto.",
    "content": "El texto mostrado no coincide con lo esperado.",
    "accessibility": "Elementos interactivos sin nombre accesible: afecta lectores de pantalla y la estabilidad de la automatización.",
    "error_message": "Se mostró un mensaje de error al usuario.",
    "unresponsive_element": "Un elemento autorizado no produjo navegación ni cambio visible al pulsarlo.",
    "visual_regression": "Diferencias visuales relevantes respecto de la baseline aprobada.",
    "visual_blank": "La pantalla está vacía o de un solo color.",
    "performance": "El tiempo de carga superó el umbral.",
}


def analyze_run(run: RunResult) -> dict:
    defects, review, blocked = [], [], []
    for c in run.cases:
        for s in c.steps:
            if s.status == Status.BLOCKED:
                blocked.append({"case": c.case_id, "step": s.id, "reason": s.message})
        for v in c.validations:
            item = {"case": c.case_id, "validation": v.id, "type": v.type, "status": v.status.value,
                    "severity": v.severity, "message": v.message, "evidence": v.evidence[:4]}
            if v.status == Status.FAIL:
                cat = v.defect_category or "functional"
                defects.append({**item, "category": cat, "explanation": CATEGORY_HINTS.get(cat, "Fallo funcional.")})
            if v.needs_human_review or v.status == Status.INCONCLUSIVE:
                review.append(item)
            if v.status == Status.BLOCKED:
                blocked.append({"case": c.case_id, "validation": v.id, "reason": v.message})
    out = {"defects": defects, "needs_human_review": review, "blocked": blocked, "ai": None}
    provider = get_provider()
    if provider and defects:
        try:
            out["ai"] = provider.complete(
                "Eres un analista QA. Explica brevemente probables causas de estos fallos. No inventes datos.",
                str(defects)[:6000],
            )
        except Exception as e:  # la IA nunca debe romper una ejecución
            out["ai"] = f"<IA no disponible: {e}>"
    return out
