"""Servidor de la consola web (FastAPI). Solo escucha en localhost.

La web es una capa de presentación: usa el mismo Runner, la misma política de acciones y el mismo
almacenamiento de evidencias que la CLI. No puede ejecutar acciones que el runner no permita.
Flujo: buscar app en tienda -> perfil -> verificar instalación -> levantamiento -> revisión -> pruebas -> publicar.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from qa_agent import profiles as P
from qa_agent.config.active import get_active, set_active
from qa_agent.config.models import PROFILES_DIR, list_profiles, load_app, load_environment, suite_files
from qa_agent.devices.manager import DeviceManager
from qa_agent.devices.toolchain import adb_path, prepare_env
from qa_agent.evidence.store import RUNS_DIR, EvidenceStore, FileRunRepository, new_run_id, setup_run_logger
from qa_agent.execution.appium_server import appium_status
from qa_agent.execution.runner import Runner, load_suite
from qa_agent.modules.home_testing import REQUIRES_CALIBRATION
from qa_agent.security.secrets import env
from qa_agent.stores import StoreApp, StoreError, search as store_search

STATIC = Path(__file__).parent / "static"
CACHE = RUNS_DIR / ".cache"
PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


@dataclass
class LiveRun:
    run_id: str
    kind: str                      # run | survey
    profile: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def push(self, evt: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(evt)


class State:
    def __init__(self) -> None:
        self.runs: dict[str, LiveRun] = {}
        self.active: LiveRun | None = None
        self.lock = threading.Lock()
        self._overview: tuple[float, str | None, dict] | None = None


STATE = State()
app = FastAPI(title="Mobile QA Agent", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- helpers
def _busy() -> bool:
    return bool(STATE.active and not STATE.active.done)


def _require_profile(pid: str) -> None:
    if pid not in list_profiles():
        raise HTTPException(404, f"Perfil desconocido: {pid}")


def _suites(pid: str | None) -> list[dict]:
    if not pid:
        return []
    calibrated = P.status(pid)["calibrated"]
    out = []
    for p in suite_files(pid):
        try:
            s = load_suite(p)
        except Exception as e:
            out.append({"path": str(p.relative_to(PROFILES_DIR)), "error": str(e)})
            continue
        cases = []
        for c in s.cases:
            needs = any(st.action in REQUIRES_CALIBRATION for st in c.steps) or \
                any(v.type in REQUIRES_CALIBRATION for v in c.validations)
            cases.append({"id": c.id, "name": c.name, "priority": c.priority.value, "tags": c.tags,
                          "description": c.description, "platforms": [x.value for x in c.platforms],
                          "steps": len(c.steps), "validations": len(c.validations),
                          "needs_calibration": needs, "blocked_by_calibration": needs and not calibrated,
                          "validation_list": [v.description or v.type for v in c.validations]})
        out.append({"path": str(p.relative_to(PROFILES_DIR)), "id": s.id, "name": s.name, "module": s.module,
                    "app": s.app, "cases": cases})
    return out


def _history(pid: str | None) -> list[dict]:
    return [r for r in FileRunRepository().list() if pid and r.get("app_id") == pid][:8]


def _profiles_list() -> list[dict]:
    out = []
    for pid in list_profiles():
        a = load_app(pid)
        icon = next((s.icon for s in a.stores.values() if s.icon), None)
        out.append({"id": pid, "name": a.name, "icon": icon, "android": a.android.package, "ios": a.ios.bundle_id,
                    "calibrated": P.status(pid)["calibrated"]})
    return out


def _app_basic(pid: str | None) -> dict:
    if not pid:
        return {}
    a = load_app(pid)
    return {"id": a.id, "name": a.name, "android_package": a.android.package, "ios_bundle": a.ios.bundle_id,
            "stores": {k: v.model_dump() for k, v in a.stores.items()},
            "store_icon": next((s.icon for s in a.stores.values() if s.icon), None)}


def _fast(pid: str | None) -> dict:
    return {"profile_id": pid, "app_basic": _app_basic(pid), "profiles": _profiles_list(), "suites": _suites(pid), "history": _history(pid),
            "active_run": STATE.active.run_id if _busy() else None,
            "active_kind": STATE.active.kind if _busy() else None,
            "last_live_run": STATE.active.run_id if STATE.active and STATE.active.profile == pid else None,
            "last_live_kind": STATE.active.kind if STATE.active and STATE.active.profile == pid else None}


def _overview(force: bool = False) -> dict:
    pid = get_active()
    if STATE._overview and not force and STATE._overview[1] == pid and time.time() - STATE._overview[0] < 15:
        return {**STATE._overview[2], **_fast(pid)}
    prepare_env()
    dm = DeviceManager()
    prov = dm.provider("android")
    devices = []
    for d in prov.list_devices():
        item = {"id": d.id, "platform": d.platform, "kind": d.kind.value, "state": d.state, "model": d.model,
                "os_version": d.os_version, "api_level": d.api_level, "screen": d.screen}
        if d.available:
            item["battery"] = prov.battery(d)  # type: ignore[attr-defined]
        devices.append(item)
    ready = next((d for d in prov.list_devices() if d.available), None) if devices else None
    app_info: dict[str, Any] = {}
    install = "no_profile"
    if pid:
        a = load_app(pid)
        app_info = {"id": a.id, "name": a.name, "description": a.description, "session_mode": a.session.mode,
                    "android_package": a.android.package, "ios_bundle": a.ios.bundle_id,
                    "stores": {k: v.model_dump() for k, v in a.stores.items()},
                    "store_icon": next((s.icon for s in a.stores.values() if s.icon), None)}
        if not a.android.package:
            install = "no_android_id"
        elif not ready:
            install = "no_device"
        else:
            meta = prov.app_details(ready, a.android.package, CACHE / "apps")  # type: ignore[attr-defined]
            if meta:
                install = "installed"
                app_info.update(meta)
                app_info["device_id"] = ready.id
            else:
                install = "not_installed"
        app_info["status"] = P.status(pid)
    ios_ok, ios_why = dm.provider("ios").is_available()
    data = {
        "app": app_info, "install_state": install, "app_installed": install == "installed",
        "devices": devices, "ios": {"available": ios_ok, "detail": ios_why},
        "appium": bool(appium_status(env("APPIUM_URL", "http://127.0.0.1:4723") or "")),
        "environment": env("QA_ENV", "prod-readonly"), "catalog": P.catalog_info(),
        "pending_publish": P.pending_changes(pid) if pid else [],
    }
    STATE._overview = (time.time(), pid, data)
    return {**data, **_fast(pid)}


def _invalidate() -> None:
    STATE._overview = None


def _safe_run_path(run_id: str, rel: str) -> Path:
    base = (RUNS_DIR / run_id).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404)
    return p


def _start_job(kind: str, pid: str, run_id: str, work: Callable[[LiveRun], None]) -> LiveRun:
    with STATE.lock:
        if _busy():
            raise HTTPException(409, f"Ya hay una ejecución en curso: {STATE.active.run_id}")
        live = LiveRun(run_id, kind, pid)

        def wrapper() -> None:
            try:
                work(live)
            except Exception as e:
                live.push({"type": "error", "ts": time.time(), "message": f"{type(e).__name__}: {e}"})
            finally:
                live.done = True
                live.push({"type": "stream_end", "ts": time.time()})
                _invalidate()

        live.thread = threading.Thread(target=wrapper, name=f"{kind}-{run_id}", daemon=True)
        STATE.runs[run_id] = live
        STATE.active = live
        _invalidate()
        live.thread.start()
    return live


# ---------------------------------------------------------------- rutas: estado
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/suites")
def suites_fast() -> dict:
    """Rápido (sin adb): pinta casos y perfiles mientras se consulta el dispositivo."""
    return _fast(get_active())


@app.get("/api/overview")
def overview(refresh: bool = False) -> dict:
    return _overview(force=refresh)


@app.get("/api/app-icon")
def app_icon() -> Response:
    pid = get_active()
    if not pid:
        raise HTTPException(404)
    a = load_app(pid)
    if not a.android.package:
        raise HTTPException(404)
    for d in sorted((CACHE / "apps").glob(f"{a.android.package}-*"), reverse=True):
        for f in d.glob("icon.*"):
            return FileResponse(f)
    raise HTTPException(404)


# ---------------------------------------------------------------- rutas: tiendas y perfiles
@app.get("/api/stores/search")
def stores_search(store: str, q: str, country: str = "cl") -> dict:
    if not re.fullmatch(r"[a-z]{2}", country):
        raise HTTPException(400, "País inválido")
    try:
        results = store_search(store, q, country)
    except StoreError as e:
        raise HTTPException(502, str(e))
    for r in results:
        r_pid = P.find_by_store_id(r.store, r.id)
        setattr(r, "profile", r_pid)
    return {"results": [{**r.to_dict(), "profile": getattr(r, "profile")} for r in results]}


class StoreAppIn(BaseModel):
    store: str
    id: str
    title: str
    developer: str = ""
    icon: str | None = None
    url: str = ""
    rating: float | None = None
    genre: str = ""
    track_id: str | None = None


def _to_store_app(x: StoreAppIn) -> StoreApp:
    if x.store not in ("google_play", "app_store") or not PKG_RE.match(x.id):
        raise HTTPException(400, "Datos de tienda inválidos")
    return StoreApp(x.store, x.id, x.title[:120], x.developer[:120], x.icon, x.url, x.rating, x.genre, x.track_id)


@app.post("/api/profiles")
def create_profile(x: StoreAppIn) -> dict:
    if _busy():
        raise HTTPException(409, "Espera a que termine la ejecución en curso")
    pid, created = P.create_from_store(_to_store_app(x))
    set_active(pid)
    _invalidate()
    return {"profile": pid, "created": created}


@app.post("/api/profiles/{pid}/attach")
def attach_store(pid: str, x: StoreAppIn) -> dict:
    _require_profile(pid)
    from qa_agent.config.models import save_app

    other = P.find_by_store_id(x.store, x.id)
    if other and other != pid:
        raise HTTPException(409, f"Ese id ya pertenece al perfil {other}")
    save_app(P.attach_listing(load_app(pid), _to_store_app(x)))
    _invalidate()
    return {"ok": True}


class SelectIn(BaseModel):
    id: str


@app.post("/api/profiles/active")
def select_profile(x: SelectIn) -> dict:
    if _busy():
        raise HTTPException(409, "Espera a que termine la ejecución en curso")
    _require_profile(x.id)
    set_active(x.id)
    _invalidate()
    return {"profile": x.id}


@app.post("/api/profiles/{pid}/open-store")
def open_store(pid: str) -> dict:
    """Abre la ficha de la app en la tienda del teléfono. La instalación la hace el usuario."""
    _require_profile(pid)
    pkg = load_app(pid).android.package
    if not pkg or not PKG_RE.match(pkg):
        raise HTTPException(400, "El perfil no tiene id de Android")
    dev = next((d for d in DeviceManager().provider("android").list_devices() if d.available), None)
    adb = adb_path()
    if not dev or not adb:
        raise HTTPException(409, "No hay dispositivo Android conectado")
    r = subprocess.run([adb, "-s", dev.id, "shell", "am", "start", "-a", "android.intent.action.VIEW",
                        "-d", f"market://details?id={pkg}"], capture_output=True, text=True, timeout=20)
    if r.returncode != 0 or "Error" in r.stdout:
        raise HTTPException(502, f"No se pudo abrir la tienda: {(r.stderr or r.stdout).strip()[:200]}")
    return {"ok": True, "device": dev.model}


# ---------------------------------------------------------------- rutas: levantamiento
class SurveyIn(BaseModel):
    platform: str = "android"
    device: str | None = None
    max_swipes: int = 6


@app.post("/api/profiles/{pid}/survey")
def start_survey(pid: str, x: SurveyIn) -> dict:
    _require_profile(pid)
    from qa_agent.modules.home_testing.survey import run_survey

    run_id = new_run_id(f"survey-{pid}-{x.platform}")

    def work(live: LiveRun) -> None:
        store = EvidenceStore(run_id)
        setup_run_logger(store)
        run_survey(load_app(pid), load_environment(env("QA_ENV", "prod-readonly") or "prod-readonly"), store,
                   x.platform, x.device, max_swipes=max(1, min(x.max_swipes, 10)), on_event=live.push)

    _start_job("survey", pid, run_id, work)
    return {"run_id": run_id}


@app.get("/api/profiles/{pid}/draft")
def get_draft(pid: str, platform: str = "android") -> dict:
    _require_profile(pid)
    d = P.load_draft(pid, platform)
    if not d:
        raise HTTPException(404, "No hay borrador de levantamiento")
    denied = {c["component"]: c.get("denied_by_policy") for c in d.get("navigation_candidates", [])}
    comps = [{"name": n, **c, "interactive": n in denied, "denied": denied.get(n)} for n, c in d.get("components", {}).items()]
    return {"signature": d["screens"]["home"]["locators"], "min_matches": d["screens"]["home"].get("min_matches"),
            "screen_ids": d["screens"]["home"].get("screen_ids", []), "app_version": d.get("app_version"),
            "components": comps}


class ApproveIn(BaseModel):
    reviewer: str
    required: list[str] = []
    navigation: list[str] = []
    signature: list[int] | None = None
    home_component: str | None = None
    platform: str = "android"


@app.post("/api/profiles/{pid}/approve")
def approve(pid: str, x: ApproveIn) -> dict:
    _require_profile(pid)
    try:
        out = P.approve_draft(pid, x.platform, x.reviewer[:80], x.required, x.navigation, x.signature, x.home_component)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _invalidate()
    return {"ok": True, "calibration": str(out.relative_to(PROFILES_DIR))}


class PublishIn(BaseModel):
    confirm: bool = False


@app.post("/api/profiles/{pid}/publish")
def publish(pid: str, x: PublishIn) -> dict:
    _require_profile(pid)
    if not x.confirm:
        raise HTTPException(400, "Confirma la publicación en el repositorio público")
    name, email = _git_identity()
    try:
        res = P.publish(pid, name, email)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    _invalidate()
    return res


def _git_identity() -> tuple[str, str]:
    """Autor de commits: cuenta de GitHub autenticada en `gh` (email noreply)."""
    try:
        r = subprocess.run(["gh", "api", "user", "--jq", '.login + " " + (.id|tostring)'], capture_output=True,
                           text=True, timeout=20)
        login, uid = r.stdout.split()
        return login, f"{uid}+{login}@users.noreply.github.com"
    except Exception:
        return "mobile-qa-agent", "mobile-qa-agent@users.noreply.github.com"


# ---------------------------------------------------------------- rutas: ejecuciones
class StartRun(BaseModel):
    suite: str
    cases: list[str]
    platform: str = "android"
    device: str | None = None


@app.post("/api/runs")
def start_run(req: StartRun) -> dict:
    suite_path = (PROFILES_DIR / req.suite).resolve()
    if PROFILES_DIR.resolve() not in suite_path.parents or suite_path.parent.name != "suites" or not suite_path.is_file():
        raise HTTPException(400, "Suite inválida")
    if not req.cases:
        raise HTTPException(400, "Selecciona al menos un caso")
    suite = load_suite(suite_path)
    unknown = set(req.cases) - {c.id for c in suite.cases}
    if unknown:
        raise HTTPException(400, f"Casos desconocidos: {sorted(unknown)}")
    run_id = new_run_id(f"{suite.app}-{req.platform}")

    def work(live: LiveRun) -> None:
        Runner(suite, req.platform, env("QA_ENV", "prod-readonly") or "prod-readonly", req.device, req.cases,
               on_event=live.push, run_id=run_id, cancel=live.cancel).run()

    _start_job("run", suite.app, run_id, work)
    return {"run_id": run_id}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    live = STATE.runs.get(run_id)
    if not live:
        raise HTTPException(404)
    live.cancel.set()
    live.push({"type": "observation", "ts": time.time(), "case_id": None, "level": "info",
               "title": "Cancelación solicitada", "message": "Se detendrá al terminar el paso actual"})
    return {"ok": True}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    live = STATE.runs.get(run_id)
    if not live:
        raise HTTPException(404)

    async def gen():
        i = 0
        last_ping = time.time()
        while True:
            with live.lock:
                batch = live.events[i:]
            for evt in batch:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            i += len(batch)
            if live.done and i >= len(live.events):
                break
            if time.time() - last_ping > 15:
                yield ": ping\n\n"
                last_ping = time.time()
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/runs/{run_id}/{rel:path}")
def run_file(run_id: str, rel: str, w: int | None = None) -> Response:
    p = _safe_run_path(run_id, rel)
    if w and p.suffix == ".png":
        from PIL import Image

        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((min(w, 1080), 10000))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
    return FileResponse(p)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    if open_browser:
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
