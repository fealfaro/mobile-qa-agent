# mobile-qa-agent: contexto del proyecto

- Python en `src/qa_agent`. Ejecutar con `.venv/bin/qa-agent` (el venv real es `.venv.nosync`, porque el proyecto está en iCloud).
- El toolchain se autodetecta con `toolchain.prepare_env()` (JAVA_HOME, ANDROID_HOME).
- Appium está instalado globalmente (`appium`, con el driver uiautomator2).
- Producto white label:
  - El código, la interfaz y la documentación no mencionan ninguna marca ni app concreta.
  - Todo lo específico de una app va en su perfil, `profiles/<app>/`. Esa carpeta es el repositorio del catálogo y no se versiona en el motor.
- Reglas:
  - No inventar selectores. Salen de un levantamiento sobre la app real y de una calibración con `status: reviewed`.
  - El core (`core/`, `execution/`, `validation/`) no importa módulos funcionales. La lógica funcional va en `modules/<módulo>/`.
  - Nunca agregar acciones transaccionales. Toda acción nueva pasa por `ActionPolicy`. El agente no instala apps desde la tienda.
  - Nunca dar PASS sin evidencia. Los problemas de entorno son BLOCKED, no FAIL.
  - No escribir secretos ni datos personales en código, logs, reportes ni perfiles publicados. Usar `security/secrets.py` y `MASKER`.
- Para borrar `runs/` usar `find runs -mindepth 1 -delete` (zsh pide confirmación con `rm -rf runs/*`).
