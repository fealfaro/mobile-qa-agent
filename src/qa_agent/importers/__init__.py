"""Importadores de casos de prueba hacia el modelo universal.

MVP: YAML / JSON. Futuro: Excel, Jira, Word, PDF, Markdown, formularios (cada uno implementa
`SuiteImporter` y produce un TestSuite; si se usa IA para interpretar texto libre, el resultado
debe quedar como borrador para revisión humana antes de ejecutarse).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import yaml

from qa_agent.core.testcase import TestSuite


class SuiteImporter(Protocol):
    extensions: tuple[str, ...]

    def load(self, path: Path) -> TestSuite: ...


class YamlJsonImporter:
    extensions = (".yaml", ".yml", ".json")

    def load(self, path: Path) -> TestSuite:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        suite = TestSuite.model_validate(data)
        if not suite.app and path.parent.name == "suites" and (path.parent.parent / "profile.yaml").exists():
            suite.app = path.parent.parent.name
        if not suite.app:
            raise ValueError(f"La suite {path} no indica `app` y no está dentro de profiles/<app>/suites/")
        for c in suite.cases:
            c.source.setdefault("file", str(path))
        return suite


IMPORTERS: list[SuiteImporter] = [YamlJsonImporter()]


def load_suite_file(path: Path) -> TestSuite:
    for imp in IMPORTERS:
        if path.suffix.lower() in imp.extensions:
            return imp.load(path)
    raise ValueError(f"Formato no soportado: {path.suffix}")
