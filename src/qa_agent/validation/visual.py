"""Validación visual tolerante: compara contra baseline por clase de dispositivo.

No toda diferencia de píxeles es un defecto:
  - se compara en escala reducida y escala de grises (anti-aliasing, fuentes, compresión),
  - se ignoran la barra de estado y regiones dinámicas declaradas,
  - el resultado se basa en regiones cambiadas (rejilla), no en píxeles sueltos,
  - entre tolerancia y umbral de fallo => INCONCLUSIVE (revisión humana / IA),
  - si la baseline es de otra versión de app, un FAIL se degrada a INCONCLUSIVE.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from qa_agent.config.models import ROOT

BASELINES = ROOT / "baselines"
CANDIDATES = BASELINES / "_candidates"
WORK_W = 360
GRID = 12


def device_class(platform: str, model: str, w: int, h: int) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{platform}/{model}_{w}x{h}")


def baseline_path(app_id: str, module: str, dclass: str, name: str) -> Path:
    return BASELINES / app_id / module / dclass / f"{name}.png"


@dataclass
class VisualDiff:
    changed_ratio: float          # fracción de píxeles (área útil) con cambio significativo
    changed_cells: int
    total_cells: int
    comparable: bool
    reason: str = ""


def blank_score(img_path: Path) -> float:
    """Desviación estándar en grises: ~0 indica pantalla vacía/negra/blanca."""
    with Image.open(img_path) as im:
        return float(ImageStat.Stat(im.convert("L").resize((90, 160))).stddev[0])


def _prep(p: Path, top_ignore: float, regions: list[list[float]]) -> Image.Image:
    with Image.open(p) as im:
        im = im.convert("L")
        h = int(im.height * WORK_W / im.width)
        im = im.resize((WORK_W, h))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, WORK_W, int(h * top_ignore)], fill=0)
    for x, y, w, hh in regions:      # fracciones de pantalla
        d.rectangle([int(x * WORK_W), int(y * h), int((x + w) * WORK_W), int((y + hh) * h)], fill=0)
    return im


def compare(current: Path, baseline: Path, diff_out: Path, top_ignore: float = 0.05,
            ignore_regions: list[list[float]] | None = None, pixel_threshold: int = 40) -> VisualDiff:
    regions = ignore_regions or []
    with Image.open(current) as a, Image.open(baseline) as b:
        ra, rb = a.height / a.width, b.height / b.width
    if abs(ra - rb) / rb > 0.03:
        return VisualDiff(0, 0, 0, False, f"relación de aspecto distinta ({ra:.3f} vs {rb:.3f})")
    ia = _prep(current, top_ignore, regions)
    ib = _prep(baseline, top_ignore, regions).resize(ia.size)
    diff = ImageChops.difference(ia, ib).point(lambda v: 255 if v > pixel_threshold else 0)
    px = list(diff.getdata())
    changed = sum(1 for v in px if v) / len(px)
    w, h = diff.size
    cw, ch = w // GRID, h // GRID
    cells = 0
    overlay = Image.open(current).convert("RGB").resize((w, h))
    draw = ImageDraw.Draw(overlay)
    for gx in range(GRID):
        for gy in range(GRID):
            box = (gx * cw, gy * ch, (gx + 1) * cw, (gy + 1) * ch)
            region = diff.crop(box)
            frac = sum(1 for v in region.getdata() if v) / max(cw * ch, 1)
            if frac > 0.08:
                cells += 1
                draw.rectangle(box, outline=(255, 0, 0), width=2)
    diff_out.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(diff_out)
    return VisualDiff(round(changed, 4), cells, GRID * GRID, True)


def save_candidate(run_id: str, app_id: str, module: str, dclass: str, name: str, src: Path, meta: dict) -> Path:
    dst = CANDIDATES / run_id / app_id / module / dclass / f"{name}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return dst


def baseline_meta(p: Path) -> dict:
    m = p.with_suffix(".json")
    return json.loads(m.read_text()) if m.exists() else {}


def approve_candidates(run_id: str) -> list[Path]:
    src_root = CANDIDATES / run_id
    out: list[Path] = []
    for png in src_root.rglob("*.png"):
        rel = png.relative_to(src_root)
        dst = BASELINES / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(png, dst)
        if png.with_suffix(".json").exists():
            shutil.copy2(png.with_suffix(".json"), dst.with_suffix(".json"))
        out.append(dst)
    return out
