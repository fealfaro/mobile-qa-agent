"""Enmascaramiento de información sensible (secretos y datos personales chilenos comunes)."""
from __future__ import annotations

import logging
import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # RUT chileno: 12.345.678-9 / 12345678-K
    (re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b"), "[RUT]"),
    # Móvil Chile: +56 9 1234 5678 / 912345678
    (re.compile(r"(?<!\d)(?:\+?56\s?)?9\s?\d{4}\s?\d{4}(?!\d)"), "[PHONE]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?i)(password|passwd|pwd|token|authorization|secret)([\"'=:\s]+)(?!(?:true|false)\b)([^\s\"',;<>]+)"), r"\1\2[SECRET]"),
]


class Masker:
    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def register_secret(self, value: str) -> None:
        if value and len(value) >= 3:
            self._secrets.add(value)

    def mask(self, text: str) -> str:
        if not text:
            return text
        for s in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(s, "[SECRET]")
        for pat, repl in _PATTERNS:
            text = pat.sub(repl, text)
        return _CARD.sub(lambda m: "[CARD]" if _luhn(m.group(0)) else m.group(0), text)


# Tarjetas: 16 dígitos seguidos o 4 grupos de 4 con el mismo separador, y dígito verificador Luhn.
_CARD = re.compile(r"(?<!\d)(?:\d{16}|\d{4}([ -])\d{4}\1\d{4}\1\d{4})(?!\d)")


def _luhn(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


MASKER = Masker()


class MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = MASKER.mask(record.getMessage())
        record.args = ()
        return True
