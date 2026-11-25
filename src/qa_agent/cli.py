"""CLI: qa-agent <comando>.

  doctor                         verifica toolchain (Java, SDK, adb, Appium, drivers, Xcode)
  devices [--app ID]             lista dispositivos, SO y si la app está instalada
  install --build RUTA --authorized   instala un build autorizado (APK/IPA/.app)
  profiles [--use ID]            perfiles de app disponibles / activo\n  inspect [--app ID]             levantamiento: recorre la pantalla principal y genera calibración borrador
  run --suite RUTA               ejecuta una suite y genera reporte
  history                        historial de ejecuciones
  baseline approve RUN_ID        promueve screenshots candidatas a baseline visual
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qa_agent.config.models import PROFILES_DIR, ROOT, list_profiles, load_app, load_environment
from qa_agent.devices.manager import DeviceManager
from qa_agent.devices.toolchain import doctor, prepare_env
from qa_agent.security.secrets import env


def _p(s: str = "") -> None:
    print(s, flush=True)


def cmd_doctor(a: argparse.Namespace) -> int:
    checks = doctor()
    for c in checks:
        _p(f"{'✔' if c.ok else '✖'} {c.name:<22} {c.detail}  [{c.required_for}]")
        if not c.ok and c.fix:
            _p(f"    → {c.fix}")
    android_ok = all(c.ok for c in checks if c.required_for == "android")
    devs = DeviceManager().provider("android").list_devices() if android_ok else []
    _p(f"\nAndroid: {'listo' if android_ok else 'faltan dependencias'}; dispositivos conectados: {len(devs)}")
    return 0 if android_ok else 1


def cmd_devices(a: argparse.Namespace) -> int:
    from qa_agent.execution.runner import AppResolutionError, resolve_app_id

    prepare_env()
    app = load_app(_app_id(a))
    dm = DeviceManager()
    found = False
    for platform, prov in dm.providers.items():
        ok, why = prov.is_available()
        if not ok:
            _p(f"[{platform}] no disponible: {why}")
            continue
        devs = prov.list_devices()
        if not devs:
            _p(f"[{platform}] sin dispositivos conectados")
        for d in devs:
            found = True
            _p(f"[{platform}] {d.id}  {d.model}  {d.kind.value}  estado={d.state}  SO={d.os_version} "
               f"api={d.api_level} pantalla={d.screen}")
            if not d.available:
                continue
            try:
                app_id = resolve_app_id(app, platform, prov, d)
            except AppResolutionError as e:
                _p(f"    {app.name}: {e}")
                continue
            info = prov.app_info(d, app_id) if app_id else None
            if info:
                _p(f"    {app.name}: INSTALADA {info.package} v{info.version_name} ({info.version_code}) "
                   f"launch={info.extra.get('launch_activity', '')}")
            else:
                _p(f"    {app.name}: NO instalada")
    return 0 if found else 1


def cmd_install(a: argparse.Namespace) -> int:
    if not a.authorized:
        _p("Debes confirmar con --authorized que el build es un build de pruebas autorizado.")
        return 2
    build = Path(a.build).resolve()
    allowed = (ROOT / "builds").resolve()
    if allowed not in build.parents:
        _p(f"Por seguridad solo se instalan builds ubicados en {allowed}/")
        return 2
    dm = DeviceManager()
    platform = "ios" if build.suffix in (".ipa", ".app") else "android"
    dev = dm.select(platform, a.device)
    _p(f"Instalando {build.name} en {dev.id} ({dev.model})...")
    dm.provider(platform).install(dev, build)
    _p("Instalado.")
    return 0


def cmd_inspect(a: argparse.Namespace) -> int:
    from qa_agent.evidence.store import EvidenceStore, new_run_id, setup_run_logger
    from qa_agent.modules.home_testing.survey import run_survey

    app = load_app(_app_id(a))
    envcfg = load_environment(a.env)
    store = EvidenceStore(new_run_id(f"survey-{app.id}-{a.platform}"))
    log = setup_run_logger(store, a.verbose)

    def wait() -> None:
        if sys.stdin.isatty() and not a.no_wait:
            input("\n>>> Si la app no está en la pantalla principal, inicia sesión con la cuenta de PRUEBA.\n"
                  ">>> Cuando la veas, presiona Enter para continuar... ")

    r = run_survey(app, envcfg, store, a.platform, a.device, a.settle, a.max_swipes, wait_operator=wait)
    s = r.inventory["summary"]
    log.info("Inventario: %s componentes %s; %s interactivos; %s para revisión",
             s["total"], s["by_category"], s["interactive"], s["needs_review"])
    log.info("Calibración borrador: %s", r.draft_path)
    log.info("Reporte de levantamiento: %s", r.report)
    return 0


def _app_id(a: argparse.Namespace) -> str:
    from qa_agent.config.active import get_active

    app_id = getattr(a, "app", None) or get_active()
    if not app_id:
        raise SystemExit("Indica --app <perfil> (perfiles: " + ", ".join(list_profiles()) + ")")
    return app_id


def cmd_profiles(a: argparse.Namespace) -> int:
    from qa_agent.config.active import get_active, set_active

    if a.use:
        set_active(a.use)
    active = get_active()
    for pid in list_profiles():
        app = load_app(pid)
        cal = "calibrada" if (PROFILES_DIR / pid / "calibration" / "home-testing.android.yaml").exists() \
            else "sin levantamiento"
        _p(f"{'*' if pid == active else ' '} {pid:<28} {app.name:<30} android={app.android.package or '-'} "
           f"ios={app.ios.bundle_id or '-'} [{cal}]")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    from qa_agent.config.models import suite_files
    from qa_agent.execution.runner import Runner, load_suite

    path = Path(a.suite) if a.suite else (suite_files(_app_id(a)) or [None])[0]
    if not path:
        raise SystemExit("El perfil no tiene suites; usa --suite")
    suite = load_suite(path)
    run = Runner(suite, a.platform, a.env, a.device, a.case, a.verbose).run()
    s = run.summary()
    _p(json.dumps({"run_id": run.run_id, "status": run.status.value, **s}, indent=2, ensure_ascii=False))
    _p(f"Reporte: {ROOT / 'runs' / run.run_id / 'report.html'}")
    return 0 if run.status.value == "PASS" else 1


def cmd_history(a: argparse.Namespace) -> int:
    from qa_agent.evidence.store import FileRunRepository

    for r in FileRunRepository().list()[: a.limit]:
        s = r["summary"]
        _p(f"{r['run_id']:<40} {r['status']:<13} {r.get('platform') or '-':<8} {r.get('device') or '-':<18} "
           f"app={r.get('app_version') or '-':<10} casos={s['cases']} val%={s['pass_rate_validations']}")
    return 0


def cmd_baseline(a: argparse.Namespace) -> int:
    from qa_agent.validation.visual import approve_candidates

    out = approve_candidates(a.run_id)
    _p(f"{len(out)} baselines aprobadas" + "".join(f"\n  {p}" for p in out))
    return 0 if out else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="qa-agent", description="Mobile QA Agent")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    default_env = env("QA_ENV", "prod-readonly")

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("devices")
    s.add_argument("--app", help="id del perfil (por defecto el activo)")
    s.set_defaults(fn=cmd_devices)

    s = sub.add_parser("profiles", help="lista perfiles de app; --use <id> lo deja activo")
    s.add_argument("--use")
    s.set_defaults(fn=cmd_profiles)

    s = sub.add_parser("install")
    s.add_argument("--build", required=True)
    s.add_argument("--device")
    s.add_argument("--authorized", action="store_true")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("inspect")
    s.add_argument("--platform", default="android", choices=["android", "ios"])
    s.add_argument("--app", help="id del perfil (por defecto el activo)")
    s.add_argument("--env", default=default_env)
    s.add_argument("--device")
    s.add_argument("--settle", type=float, default=6)
    s.add_argument("--max-swipes", type=int, default=8)
    s.add_argument("--no-wait", action="store_true", help="no pedir confirmación del operador")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("run")
    s.add_argument("--suite", help="por defecto la primera suite del perfil activo")
    s.add_argument("--app")
    s.add_argument("--platform", default="android", choices=["android", "ios"])
    s.add_argument("--env", default=default_env)
    s.add_argument("--device")
    s.add_argument("--case", action="append", help="ejecutar solo este caso (repetible)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("web", help="consola web local (http://127.0.0.1:8765)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=lambda a: (__import__("qa_agent.web.server", fromlist=["serve"]).serve(a.port, not a.no_browser), 0)[1])

    s = sub.add_parser("history")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("baseline")
    bs = s.add_subparsers(dest="bcmd", required=True)
    b = bs.add_parser("approve")
    b.add_argument("run_id")
    b.set_defaults(fn=cmd_baseline)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        _p(f"ERROR: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
