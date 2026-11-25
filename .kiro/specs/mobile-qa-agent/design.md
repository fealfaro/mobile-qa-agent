# Design: mobile-qa-agent

La arquitectura detallada está en `docs/architecture.md` y las decisiones en `docs/technical-decisions.md`.

## Componentes

```
consola web (FastAPI + SSE)          CLI qa-agent
        │                                 │
        ├── stores (Google Play, App Store)
        ├── profiles (crear, adjuntar ficha, aprobar levantamiento, publicar)
        ├── modules/home_testing/survey (levantamiento)
        └── Runner (execution/runner.py)
              ├─ DeviceManager ── Android (adb) / iOS (simctl, devicectl)
              ├─ AppiumServer + MobileDriver ── UiAutomator2 / XCUITest
              ├─ Registry ── builtin_actions + builtin_validators + modules/*.register()
              ├─ ExecutionContext ── snapshot() = screenshot + page source + UiTree; emit() = eventos
              ├─ ActionPolicy ── antes de cada acción y cada tap
              ├─ EvidenceStore + FileRunRepository ── runs/<run_id>/
              └─ Analyzer + reporte HTML
```

## Perfiles

- `profile.yaml` (modelo `AppCfg`) incluye:
  - `id`, `name`, `description`;
  - `stores.google_play` y `stores.app_store` (modelo `StoreListing`);
  - `android.package` e `ios.bundle_id`;
  - `session` y `safety.deny_keywords`.
- `PROFILES_DIR` es `./profiles` por defecto (variable `QA_PROFILES_DIR`). Normalmente es un clon del catálogo.
- El perfil activo se guarda en `runs/.state/active_profile`, fuera del versionado.
- Al crear un perfil se copia `templates/suites/home.yaml`.

## Casos que necesitan calibración

`modules/home_testing.REQUIRES_CALIBRATION` lista las acciones y validadores que dependen de una calibración revisada. La consola marca esos casos como "requiere levantamiento" y no permite seleccionarlos hasta que exista la calibración.

## Levantamiento

`run_survey()` es el mismo flujo para la CLI y para la web:
1. Abre la sesión y la app, y verifica que está en primer plano y que el teléfono no está bloqueado.
2. Recorre la pantalla con `explore()` y clasifica los componentes.
3. Escribe el borrador `calibration/home-testing.<platform>.draft.yaml` (enmascarado) y emite eventos con su progreso.

`approve_draft()` aplica las decisiones del revisor (firma, requeridos, navegación, `home_component`). Rechaza objetivos bloqueados por la política y revisores vacíos.

## Publicación

`profiles.publish()` hace `git add`, `commit` y `push` del perfil en el repositorio del catálogo, usando las credenciales de `gh` solo para ese comando. Antes revisa con el `Masker` que el perfil no contenga datos personales.

## Eventos (`core/events.py`)

- Ejecuciones: `run_started`, `session`, `case_started`, `step_started`, `step_finished`, `validation_started`, `validation`, `screenshot`, `observation`, `case_finished` y `run_finished`.
- Levantamientos: `survey_started`, `survey_phase` y `survey_finished`.
- Comunes: `error` y `stream_end`.

Todos se enmascaran antes de emitirse.

## Estados

- La precedencia es FAIL > BLOCKED > INCONCLUSIVE > NOT_EXECUTED > PASS.
- Un caso es PASS solo si todos sus pasos y validaciones son PASS.
- Un PASS sin evidencia se degrada a INCONCLUSIVE.

## Validación visual

- La baseline se guarda en `baselines/<app>/<módulo>/<plataforma_modelo_resolución>/<nombre>.png`.
- La comparación se hace en grises a 360 px, sobre una rejilla de 12×12 y con regiones ignoradas.
- Con una diferencia de hasta 3% es PASS. Desde 15% es FAIL, si la baseline es de la misma versión de la app. En el rango intermedio es INCONCLUSIVE.
