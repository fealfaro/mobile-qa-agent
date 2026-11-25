"""Política de acciones: solo acciones registradas, no transaccionales y sobre objetivos permitidos.

La IA y los casos de prueba NO pueden saltarse esta política.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

# Palabras que indican acciones transaccionales/destructivas. Se combinan con las de config/apps.
DEFAULT_DENY = [
    "comprar", "compra", "pagar", "pago", "contratar", "contrata", "suscribir", "confirmar",
    "recargar", "recarga", "portar", "portabilidad", "eliminar", "borrar", "dar de baja",
    "cancelar plan", "cambiar plan", "agregar al carro", "checkout", "finalizar", "aceptar oferta",
    "cerrar sesion", "cerrar sesión", "logout", "desvincular", "transferir", "canjear", "activar",
    "buy", "purchase", "pay now", "subscribe", "confirm", "delete", "remove account", "sign out", "log out",
    "add to cart", "place order", "transfer", "redeem", "donate", "install", "instalar", "desinstalar",
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


class PolicyViolation(Exception):
    pass


@dataclass
class ActionPolicy:
    allow_transactions: bool = False
    deny_keywords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._deny = sorted({_norm(k) for k in DEFAULT_DENY + self.deny_keywords if k})

    def check_action(self, action: str, transactional: bool) -> None:
        if transactional and not self.allow_transactions:
            raise PolicyViolation(f"Acción transaccional '{action}' bloqueada por política del MVP")

    def denied_keyword(self, *labels: str) -> str | None:
        for label in labels:
            n = _norm(label)
            if not n:
                continue
            for k in self._deny:
                if k in n:
                    return k
        return None

    def check_tap_target(self, *labels: str) -> None:
        hit = self.denied_keyword(*labels)
        if hit:
            raise PolicyViolation(f"Tap bloqueado: el objetivo contiene la palabra sensible '{hit}'")
