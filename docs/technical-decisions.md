# Decisiones técnicas (ADR resumidas)

| # | Decisión | Alternativas | Motivo |
|---|---|---|---|
| TD-01 | **Appium 4 + UiAutomator2 / XCUITest** como motor principal | Maestro, Espresso o XCUITest nativo | Un solo protocolo (WebDriver) para Android e iOS, sin acceso al código fuente de la app y con un árbol de accesibilidad completo. Maestro queda como alternativa detrás del contrato `MobileDriver`. |
| TD-02 | **Python 3.14** para la orquestación | TypeScript | Mejor ecosistema para IA y procesamiento de imágenes. TypeScript se reserva para integraciones futuras. |
| TD-03 | **Appium instalado globalmente con npm**; drivers en `~/.appium` | Appium en node_modules del proyecto | El proyecto está en iCloud Drive y `node_modules` ahí causa problemas de sincronización. |
| TD-04 | **Venv en `.venv.nosync`** (con un symlink `.venv`) | Venv normal | iCloud no sincroniza las carpetas `*.nosync`. |
| TD-05 | **Android SDK con `android-commandlinetools` de Homebrew** y sin Android Studio | Android Studio | Ocupa menos disco. El emulador es opcional (~10 GB); se recomienda un dispositivo físico. |
| TD-06 | **Persistencia en JSON** (`runs/index.json`) detrás de un repositorio | PostgreSQL desde el inicio | Evita infraestructura en el MVP. El contrato permite migrar sin cambiar a los consumidores. |
| TD-07 | **Sin selectores hardcodeados: calibración generada desde la app real y revisada por un humano** | Escribir los selectores a mano | Cumple la regla de no inventar selectores. Separa la lógica de cada app del motor y permite recalibrar por versión de app. |
| TD-08 | **8 validadores genéricos que no requieren calibración** | Solo validadores específicos | Permite validar la app real (más de 5 validaciones) desde la primera ejecución, antes de calibrar. |
| TD-09 | **Clasificador heurístico con confianza; IA solo para baja confianza (Sprint 4)** | Clasificar todo con un LLM | Es determinista, auditable y no tiene costo ni riesgo de PII. La IA no decide estados. |
| TD-10 | **Validación visual propia con Pillow** (rejilla y tolerancias) | Applitools, Percy u OpenCV | Una sola dependencia liviana, con reglas explícitas para las diferencias normales entre plataforma, resolución y versión. |
| TD-11 | **Problemas de entorno = BLOCKED, PASS sin evidencia = INCONCLUSIVE** | Tratarlos como FAIL | Distingue un defecto del producto de una falla de la infraestructura de prueba. |
| TD-12 | **Sesión con `noReset=true`, `autoLaunch=false` y sin `--relaxed-security` en Appium** | fullReset y relaxed security | Protege la sesión de la cuenta de prueba y aplica mínimo privilegio. Los comandos adb se ejecutan desde el agente, no desde Appium. |
| TD-13 | **Modos de sesión existing, manual y credentials** | Solo login automático | Las apps de telcos suelen pedir OTP por SMS. El modo manual mantiene a un humano en el circuito sin romper la automatización. |
| TD-14 | **Secretos en env, `.env` o el Llavero de macOS** | Archivo de configuración | No hay secretos en el repo. Cada valor resuelto se registra en el `Masker`. |
| TD-15 | **Playwright excluido del MVP** | — | La app bajo prueba es nativa o híbrida. Playwright solo se usaría para probar la consola web. |
| TD-17 | **Consola web con FastAPI + SSE + HTML/JS sin frameworks**, solo en 127.0.0.1 | React/Vue con build; WebSockets | Dos dependencias, sin paso de build. SSE basta porque el flujo es solo servidor → navegador. El runner emite eventos genéricos (`core/events.py`) y la web es solo una capa de presentación. |
| TD-18 | **White label: todo lo específico de una app vive en su perfil** (`profiles/<app>/`), nunca en el código | Configuración por app dentro del motor | El motor se comparte sin referencias a ninguna marca. Cada perfil se versiona y publica por separado. |
| TD-19 | **Catálogo de perfiles como repositorio git aparte**, montado en `profiles/` | Un repositorio por app; perfiles dentro del motor | Es fácil de clonar y compartir. Publicar es hacer commit y push del perfil, con un control previo de datos personales. |
| TD-20 | **Buscador: iTunes Search API (oficial) y `google-play-scraper` (no oficial) para Google Play** | APIs de pago; solo ingresar el package a mano | Google Play no tiene API pública de búsqueda. Si la librería falla, la consola muestra el error y nunca inventa ids. El primer resultado sin id se recupera de la página de búsqueda. |
| TD-21 | **La instalación la hace el usuario** (el agente solo abre la ficha de la tienda en el teléfono) | Instalar automáticamente desde la tienda | Instalar implica aceptar términos e iniciar sesión en la tienda: es una acción que el agente no debe tomar. "Instalar" está en la lista de denegación. |
| TD-16 | **Sin Maestro, PostgreSQL ni LLM en el MVP** | Incluirlos desde el inicio | Evita dependencias innecesarias. Cada uno tiene su punto de extensión definido. |

## Dependencias Python del MVP

`Appium-Python-Client`, `pydantic`, `PyYAML`, `Pillow` y `python-dotenv`. No hay ninguna otra.

## Riesgos abiertos

- **Detección de emulador o root por la app bajo prueba:** algunas apps (banca, telcos) se bloquean en emuladores. La mitigación es usar un dispositivo físico.
- **Login con OTP o por red móvil (sin SIM en el emulador):** la mitigación es `session.mode: manual`.
- **Contenido híbrido (WebView):** si la pantalla principal es web dentro de la app, puede requerir cambiar de contexto (`NATIVE_APP` / `WEBVIEW_*`). El clasificador lo detecta y lo marca.
- **Datos personales en screenshots:** `runs/` no se versiona. Antes de enviar imágenes a un LLM (Sprint 4) hay que definir una política.
