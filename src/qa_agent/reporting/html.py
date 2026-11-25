"""Reporting Layer: reporte HTML autocontenido por ejecución (las imágenes se enlazan en relativo)."""
from __future__ import annotations

import html
from pathlib import Path

from qa_agent.core.results import RunResult
from qa_agent.security.masking import MASKER

COLORS = {"PASS": "#1a7f37", "FAIL": "#cf222e", "BLOCKED": "#9a6700", "INCONCLUSIVE": "#8250df", "NOT_EXECUTED": "#6e7781"}

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2328;background:#f6f8fa}
h1{margin:0 0 4px} .muted{color:#656d76;font-size:13px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:12px 16px;min-width:110px}
.card b{font-size:24px;display:block}
.case{background:#fff;border:1px solid #d0d7de;border-radius:8px;margin:12px 0;padding:12px 16px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
td,th{border-bottom:1px solid #eaeef2;padding:6px;text-align:left;vertical-align:top}
.badge{color:#fff;border-radius:12px;padding:2px 8px;font-size:12px;font-weight:600;white-space:nowrap}
.thumbs img{height:220px;border:1px solid #d0d7de;border-radius:6px;margin:4px}
details summary{cursor:pointer;font-weight:600}
code{font-size:12px;background:#eaeef2;padding:1px 4px;border-radius:4px}
"""


def _e(s: object) -> str:
    return html.escape(MASKER.mask(str(s if s is not None else "")))


def badge(status: str) -> str:
    return f'<span class="badge" style="background:{COLORS.get(status, "#555")}">{status}</span>'


def _evidence_links(ev: list[str]) -> str:
    out = []
    for e in ev:
        if not e:
            continue
        name = e.rsplit("/", 1)[-1]
        out.append(f'<a href="{html.escape(e)}" target="_blank">{html.escape(name)}</a>')
    return " · ".join(out)


def _thumbs(ev: list[str], limit: int = 8) -> str:
    imgs = [e for e in ev if e.endswith(".png")][:limit]
    return '<div class="thumbs">' + "".join(
        f'<a href="{html.escape(i)}" target="_blank"><img src="{html.escape(i)}" loading="lazy"></a>' for i in imgs) + "</div>"


def write_report(run: RunResult, run_dir: Path, analysis: dict | None = None) -> Path:
    s = run.summary()
    dev = run.device
    app = run.app
    parts = [f"<!doctype html><html lang='es'><meta charset='utf-8'><title>QA {run.run_id}</title><style>{CSS}</style><body>",
             f"<h1>{_e(run.suite_name)} {badge(run.status.value)}</h1>",
             f"<div class='muted'>Run <code>{_e(run.run_id)}</code> · módulo {_e(run.module)} · ambiente {_e(run.environment)} · "
             f"{_e(run.started_at.strftime('%Y-%m-%d %H:%M:%S UTC'))} · {s['duration_s']}s · agente v{_e(run.agent_version)}</div>",
             f"<div class='muted'>App: {_e(app.name if app else '-')} <code>{_e(app.package if app else '-')}</code> "
             f"v{_e(app.version if app else '-')} ({_e(app.build if app else '-')}) · Dispositivo: {_e(dev.model if dev else '-')} "
             f"<code>{_e(dev.id if dev else '-')}</code> {_e(dev.platform if dev else '')} {_e(dev.os_version if dev else '')} "
             f"({_e(dev.kind if dev else '')})</div>"]

    parts.append("<div class='cards'>")
    parts.append(f"<div class='card'>Casos<b>{s['total_cases']}</b></div>")
    for st, n in s["cases"].items():
        parts.append(f"<div class='card' style='border-top:4px solid {COLORS[st]}'>{st}<b>{n}</b></div>")
    parts.append(f"<div class='card'>Éxito casos<b>{s['pass_rate_cases']}%</b></div>")
    parts.append(f"<div class='card'>Validaciones<b>{s['total_validations']}</b>"
                 f"<span class='muted'>{' · '.join(f'{k} {v}' for k, v in s['validations'].items() if v)}</span></div>")
    parts.append(f"<div class='card'>Éxito validaciones<b>{s['pass_rate_validations']}%</b></div></div>")

    if run.errors:
        parts.append("<div class='case' style='border-color:#9a6700'><b>Errores de ejecución</b><ul>"
                     + "".join(f"<li>{_e(e)}</li>" for e in run.errors) + "</ul></div>")

    if analysis and analysis.get("defects"):
        parts.append("<div class='case'><b>Defectos detectados</b><table><tr><th>Caso</th><th>Validación</th>"
                     "<th>Categoría</th><th>Severidad</th><th>Detalle</th><th>Análisis</th></tr>")
        for d in analysis["defects"]:
            parts.append(f"<tr><td>{_e(d['case'])}</td><td>{_e(d['validation'])}</td><td>{_e(d['category'])}</td>"
                         f"<td>{_e(d['severity'])}</td><td>{_e(d['message'])}</td><td>{_e(d['explanation'])}</td></tr>")
        parts.append("</table></div>")
    if analysis and analysis.get("needs_human_review"):
        parts.append(f"<div class='case'><b>Requiere revisión humana ({len(analysis['needs_human_review'])})</b><ul>"
                     + "".join(f"<li>{_e(r['case'])} / {_e(r['validation'])}: {_e(r['message'])}</li>"
                               for r in analysis["needs_human_review"]) + "</ul></div>")

    for c in run.cases:
        parts.append(f"<div class='case'><h3>{badge(c.status.value)} {_e(c.case_id)} · {_e(c.name)} "
                     f"<span class='muted'>{_e(c.priority)} · {c.duration_s}s</span></h3>")
        if c.errors:
            parts.append("<div>" + "<br>".join(_e(e) for e in c.errors) + "</div>")
        if c.steps:
            parts.append("<details open><summary>Pasos</summary><table><tr><th>#</th><th>Acción</th><th>Resultado</th>"
                         "<th>Mensaje</th><th>s</th><th>Evidencia</th></tr>")
            for st in c.steps:
                parts.append(f"<tr><td>{_e(st.id)}</td><td><code>{_e(st.action)}</code></td><td>{badge(st.status.value)}</td>"
                             f"<td>{_e(st.message)}</td><td>{st.duration_s}</td><td>{_evidence_links(st.evidence)}</td></tr>")
            parts.append("</table></details>")
        if c.validations:
            parts.append("<details open><summary>Validaciones</summary><table><tr><th>ID</th><th>Tipo</th><th>Resultado</th>"
                         "<th>Mensaje</th><th>Esperado</th><th>Obtenido</th><th>Evidencia</th></tr>")
            for v in c.validations:
                rv = " 👁 revisión" if v.needs_human_review else ""
                parts.append(f"<tr><td>{_e(v.id)}<div class='muted'>{_e(v.description)}</div></td><td><code>{_e(v.type)}</code></td>"
                             f"<td>{badge(v.status.value)}{rv}</td><td>{_e(v.message)}</td><td>{_e(v.expected)}</td>"
                             f"<td>{_e(v.actual)[:300]}</td><td>{_evidence_links(v.evidence)}</td></tr>")
            parts.append("</table></details>")
        ev = [e for st in c.steps for e in st.evidence] + [e for v in c.validations for e in v.evidence] + c.evidence
        seen: list[str] = []
        for e in ev:
            if e and e not in seen:
                seen.append(e)
        parts.append(f"<details><summary>Screenshots</summary>{_thumbs(seen, 20)}</details></div>")

    parts.append("<p class='muted'>Logs: <a href='agent.log'>agent.log</a> · <a href='appium.log'>appium.log</a> · "
                 "<a href='run.json'>run.json</a> · <a href='analysis.json'>analysis.json</a></p></body></html>")
    out = run_dir / "report.html"
    out.write_text("".join(parts), encoding="utf-8")
    return out


def write_inspection_report(out: Path, inventory: dict, screenshots: list[str], device: str, app: str) -> Path:
    rows = "".join(
        f"<tr><td>{c['page']}</td><td><b>{_e(c['category'])}</b></td><td>{_e(c['name'])}</td><td><code>{_e(c['class'])}</code></td>"
        f"<td><code>{_e(c['resource_id'])}</code></td><td>{_e(c['bounds'])}</td><td>{c['confidence']}</td>"
        f"<td>{_e(c['suggested_locator'])}</td><td>{_e(c['locator_quality'])}</td>"
        f"<td>{'⚠️' if c['needs_review'] else ''}</td></tr>" for c in inventory["components"])
    s = inventory["summary"]
    page = (f"<!doctype html><html lang='es'><meta charset='utf-8'><title>Inspección</title><style>{CSS}</style><body>"
            f"<h1>Inspección de la pantalla principal</h1><div class='muted'>{_e(app)} · {_e(device)} · {inventory['pages']} páginas "
            f"· fin de scroll: {inventory['reached_end']}</div>"
            f"<div class='cards'><div class='card'>Componentes<b>{s['total']}</b></div>"
            f"<div class='card'>Interactivos<b>{s['interactive']}</b></div>"
            f"<div class='card'>Con nombre accesible<b>{s['with_accessible_name']}</b></div>"
            f"<div class='card'>Revisión<b>{s['needs_review']}</b></div></div>"
            f"<div class='case'>Por categoría: {_e(s['by_category'])}</div>"
            f"<div class='case'>{_thumbs(screenshots, 12)}</div>"
            f"<div class='case'><table><tr><th>Pág</th><th>Categoría</th><th>Nombre</th><th>Clase</th><th>resource-id</th>"
            f"<th>Bounds</th><th>Conf.</th><th>Localizador sugerido</th><th>Calidad</th><th></th></tr>{rows}</table></div></body></html>")
    out.write_text(page, encoding="utf-8")
    return out
