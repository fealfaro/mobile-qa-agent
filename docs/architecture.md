# Arquitectura: mobile-qa-agent

## Capas y paquetes

| Capa | Paquete | Responsabilidad |
|---|---|---|
| Core | `qa_agent/core` | Modelo universal de casos, resultados, estados, contratos, registry, contexto y eventos |
| Configuración | `qa_agent/config` | Perfiles de app (`profiles/<app>/`), ambientes y calibraciones; perfil activo |
| Perfiles | `qa_agent/profiles.py`, `qa_agent/stores` | Búsqueda en tiendas, creación de perfiles, aprobación de levantamientos y publicación en el catálogo |
| A. Intelligence | `qa_agent/intelligence`, `qa_agent/importers` | Importación de casos y análisis de resultados. Proveedor LLM opcional, que nunca ejecuta acciones |
| B. Mobile Execution | `qa_agent/devices`, `qa_agent/execution`, `qa_agent/inspection` | Dispositivos, Appium, gestos, sesión, overlays y lectura de la UI |
| C. Validation | `qa_agent/validation` | Validadores genéricos, comparación visual tolerante y clasificación de defectos |
| D. Evidence | `qa_agent/evidence` | Evidencias por ejecución, logs enmascarados e historial |
| E. Reporting | `qa_agent/reporting`, `qa_agent/web` | Reporte HTML y consola web con ejecución en vivo (eventos por SSE) |
| Seguridad (transversal) | `qa_agent/security` | Secretos, enmascaramiento y política de acciones |
| Módulos funcionales | `qa_agent/modules/<módulo>` | Hoy solo `home_testing` (pantalla principal): acciones, validadores, explorador y levantamiento |

## Regla de dependencias

```
web, cli   ──►  profiles, stores, execution, modules
modules/*  ──►  core, execution, validation, inspection, security
execution  ──►  core, devices, inspection, security, evidence
core       ──►  (no depende de modules ni de Appium)
```

- Ninguna capa conoce una app concreta. Todo lo específico de una app vive en su perfil: ids, selectores revisados, overlays, palabras bloqueadas y suites.
- Appium solo se importa en `execution/appium_driver.py`.

## Flujo de una app nueva

```
buscador (Google Play / App Store) ─► perfil (profile.yaml + suite genérica)
   ─► ¿instalada en el dispositivo? ── no ─► abrir la tienda en el teléfono (el usuario instala)
   ─► levantamiento (explorer + classifier) ─► calibration/*.draft.yaml
   ─► revisión humana en la web ─► calibration/*.yaml (status: reviewed)
   ─► ejecución de suites ─► runs/<run_id>/ (evidencias, reporte)
   ─► publicar perfil ─► catálogo público (control previo de datos personales)
```

## Datos de una ejecución

```
suite.yaml ─► TestSuite ─► Runner ─► por caso: pasos ─► validaciones ─► CaseResult
                                │                  │
                         ExecutionContext ◄── Snapshot (png + xml + UiTree)
                                │
           runs/<run_id>/{run.json, analysis.json, report.html, agent.log, appium.log, cases/...}
           runs/index.json (historial por app)
```

## Cómo agregar un módulo funcional (por ejemplo, un checkout de solo lectura)

1. Crear `src/qa_agent/modules/<modulo>/__init__.py` con `register(reg)` y sus acciones y validadores.
2. Agregar una plantilla de suite en `templates/suites/`.
3. Las calibraciones del módulo van en `profiles/<app>/calibration/<modulo>.<platform>.yaml`.
4. No se modifica `core/`, `execution/` ni `validation/`.

## Escalabilidad prevista

- **Varios dispositivos:** un `Runner` por dispositivo, con su propio puerto de Appium y `systemPort`.
- **Persistencia:** reemplazar `FileRunRepository` por una implementación sobre PostgreSQL con el mismo contrato.
- **IA:** un `AIProvider` para explicar fallos y clasificar componentes de baja confianza. Su salida es siempre una propuesta.
