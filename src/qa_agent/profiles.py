"""Gestión de perfiles de app: crear desde una tienda, adjuntar la ficha de otra tienda, estado y publicación.

Los perfiles viven en PROFILES_DIR, que puede ser un repositorio git propio (catálogo de perfiles).
Publicar = commit + push del perfil en ese repositorio, con control de datos personales previo.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

from qa_agent.config.models import (PROFILES_DIR, TEMPLATES_DIR, AppCfg, StoreListing, calibration_path,
                                    list_profiles, load_app, load_calibration, profile_dir, save_app, suite_files)
from qa_agent.security.masking import MASKER
from qa_agent.stores import StoreApp

MODULE = "home-testing"


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:48] or "app"


def find_by_store_id(store: str, app_id: str) -> str | None:
    for pid in list_profiles():
        a = load_app(pid)
        if (store == "google_play" and a.android.package == app_id) or (store == "app_store" and a.ios.bundle_id == app_id):
            return pid
        if store in a.stores and a.stores[store].id == app_id:
            return pid
    return None


def _listing(s: StoreApp) -> StoreListing:
    return StoreListing(id=s.id, title=s.title, developer=s.developer, icon=s.icon, url=s.url, rating=s.rating,
                        track_id=s.track_id)


def attach_listing(app: AppCfg, s: StoreApp) -> AppCfg:
    app.stores[s.store] = _listing(s)
    if s.store == "google_play":
        app.android.package = s.id
    else:
        app.ios.bundle_id = s.id
    return app


def create_from_store(s: StoreApp) -> tuple[str, bool]:
    """Devuelve (profile_id, creado). Si ya existe un perfil con ese id de tienda, lo reutiliza."""
    existing = find_by_store_id(s.store, s.id)
    if existing:
        return existing, False
    base = slugify(s.title)
    pid, n = base, 2
    while (PROFILES_DIR / pid).exists():
        pid, n = f"{base}-{n}", n + 1
    app = AppCfg(id=pid, name=s.title, description=f"{s.title} ({s.developer})")
    attach_listing(app, s)
    save_app(app)
    suites = profile_dir(pid) / "suites"
    suites.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATES_DIR / "suites" / "home.yaml", suites / "home.yaml")
    (profile_dir(pid) / "calibration").mkdir(exist_ok=True)
    return pid, True


def status(pid: str, platform: str = "android") -> dict:
    reviewed = load_calibration(pid, MODULE, platform)
    draft = load_calibration(pid, MODULE, platform, draft=True)
    return {
        "calibrated": bool(reviewed and reviewed.status == "reviewed"),
        "calibrated_by": reviewed.calibrated_by if reviewed else None,
        "calibrated_at": reviewed.calibrated_at if reviewed else None,
        "calibrated_version": reviewed.app_version if reviewed else None,
        "has_draft": draft is not None,
        "components": len(reviewed.components) if reviewed else 0,
        "navigation_targets": len(reviewed.navigation_targets) if reviewed else 0,
        "suites": [str(p.relative_to(PROFILES_DIR)) for p in suite_files(pid)],
    }


def load_draft(pid: str, platform: str = "android") -> dict | None:
    p = calibration_path(pid, MODULE, platform, draft=True)
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def approve_draft(pid: str, platform: str, reviewer: str, required: list[str], navigation: list[str],
                  signature: list[int] | None = None, home_component: str | None = None) -> Path:
    """Convierte el borrador en calibración revisada con las decisiones del revisor humano."""
    draft = load_draft(pid, platform)
    if not draft:
        raise ValueError("No hay borrador de levantamiento para aprobar")
    if not reviewer.strip():
        raise ValueError("Indica quién revisa la calibración")
    comps = draft.get("components", {})
    unknown = (set(required) | set(navigation)) - set(comps)
    if unknown:
        raise ValueError(f"Componentes desconocidos: {sorted(unknown)}")
    denied = {c["component"] for c in draft.get("navigation_candidates", []) if c.get("denied_by_policy")}
    if set(navigation) & denied:
        raise ValueError(f"Objetivos bloqueados por la política de seguridad: {sorted(set(navigation) & denied)}")
    for name, c in comps.items():
        c["required"] = name in required
    sig = draft["screens"]["home"]
    if signature is not None:
        locs = [sig["locators"][i] for i in signature if 0 <= i < len(sig["locators"])]
        if not locs:
            raise ValueError("La firma de la pantalla principal necesita al menos un localizador")
        sig["locators"] = locs
        sig["min_matches"] = max(1, -(-len(locs) * 6 // 10))
    cal = {k: v for k, v in draft.items() if k != "navigation_candidates"}
    cal.update(status="reviewed", calibrated_by=reviewer.strip(),
               calibrated_at=datetime.now().isoformat(timespec="seconds"),
               navigation_targets=[{"component": n, "expect": "screen_change"} for n in navigation])
    if home_component and home_component in comps:
        cal["home_component"] = home_component
    out = calibration_path(pid, MODULE, platform)
    header = (f"# Calibración revisada de la pantalla principal ({platform}).\n"
              f"# Generada por levantamiento sobre la app real y aprobada por: {reviewer.strip()}.\n")
    out.write_text(header + MASKER.mask(yaml.safe_dump(cal, allow_unicode=True, sort_keys=False, width=140)),
                   encoding="utf-8")
    calibration_path(pid, MODULE, platform, draft=True).unlink(missing_ok=True)
    return out


# ------------------------------------------------------------------ publicación
def _git(*args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    cred = ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"] if shutil.which("gh") else []
    return subprocess.run(["git", *cred, "-C", str(PROFILES_DIR), *args], capture_output=True, text=True,
                          timeout=timeout, env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"})


def catalog_info() -> dict:
    if not (PROFILES_DIR / ".git").exists():
        return {"is_repo": False, "remote": None}
    r = _git("remote", "get-url", "origin")
    url = r.stdout.strip() if r.returncode == 0 else None
    web = re.sub(r"\.git$", "", url) if url and url.startswith("https://") else url
    return {"is_repo": True, "remote": web}


def privacy_findings(pid: str) -> list[str]:
    """Archivos del perfil que contienen datos que el enmascarador modificaría (RUT, teléfono, email...)."""
    out = []
    for f in profile_dir(pid).rglob("*"):
        if f.is_file() and f.suffix in (".yaml", ".yml", ".md", ".json"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            if MASKER.mask(text) != text:
                out.append(str(f.relative_to(PROFILES_DIR)))
    return out


def pending_changes(pid: str) -> list[str]:
    if not catalog_info()["is_repo"]:
        return []
    r = _git("status", "--porcelain", "--", pid)
    return [l[3:] for l in r.stdout.splitlines() if l.strip()]


def publish(pid: str, author_name: str, author_email: str) -> dict:
    info = catalog_info()
    if not info["is_repo"] or not info["remote"]:
        raise RuntimeError(f"{PROFILES_DIR} no es un repositorio git con remoto 'origin'")
    leaks = privacy_findings(pid)
    if leaks:
        raise RuntimeError(f"Publicación bloqueada: posibles datos personales en {leaks}")
    changes = pending_changes(pid)
    if not changes:
        return {"published": False, "message": "Sin cambios que publicar", "url": f"{info['remote']}/tree/main/{pid}"}
    for args in (("add", "--", pid),
                 ("-c", f"user.name={author_name}", "-c", f"user.email={author_email}",
                  "commit", "-m", f"Perfil {pid}: actualización", "--", pid),
                 ("push", "origin", "HEAD")):
        r = _git(*args, timeout=180)
        if r.returncode != 0:
            raise RuntimeError(f"git {args[0] if args[0] != '-c' else 'commit'} falló: {(r.stderr or r.stdout).strip()[:300]}")
    return {"published": True, "message": f"{len(changes)} archivo(s) publicados",
            "url": f"{info['remote']}/tree/main/{pid}"}
