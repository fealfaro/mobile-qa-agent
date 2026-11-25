# mobile-qa-agent

Agente white label de QA automatizado para apps móviles nativas e híbridas. Usa Appium (UiAutomator2 y XCUITest).

Eliges la app desde un buscador de Google Play o App Store. El agente verifica que esté instalada en el teléfono, hace un **levantamiento** de su pantalla principal, que una persona revisa, y ejecuta casos de prueba con evidencias, reportes y una consola web en vivo.

Todas las pruebas son de lectura o de navegación no transaccional: la política de acciones bloquea compras, pagos, suscripciones, cierres de sesión y acciones similares.

- Spec: `.kiro/specs/mobile-qa-agent/` (requisitos, diseño y tareas)
- Arquitectura: `docs/architecture.md`
- Decisiones técnicas: `docs/technical-decisions.md`
- Cómo revisar un levantamiento: `docs/calibration.md`

## Requisitos

- Python 3.11 o superior
- Java 17 o 21 y Android SDK platform-tools (`adb`) y build-tools
- Node.js y Appium 2 o superior, con el driver uiautomator2:
  ```bash
  npm i -g appium && appium driver install uiautomator2
  ```
- iOS (opcional): Xcode completo y `appium driver install xcuitest`

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env
.venv/bin/qa-agent doctor          # verifica el toolchain
```

## Perfiles de app

Cada app tiene un **perfil** en `profiles/<app>/`:

```
profiles/<app>/
  profile.yaml                              ficha: ids Android/iOS, tiendas, modo de sesión, palabras bloqueadas
  calibration/home-testing.android.yaml     selectores revisados por una persona
  suites/home.yaml                          casos de prueba (copia de templates/suites/home.yaml)
```

Los perfiles se comparten en un catálogo público aparte. Para usar perfiles existentes:

```bash
git clone https://github.com/fealfaro/mobile-qa-app-profiles profiles
```

Una app nueva no necesita perfil previo: se crea desde el buscador de la consola web.

## Consola web

```bash
.venv/bin/qa-agent web             # http://127.0.0.1:8765 (solo localhost)
```

1. **Elegir app:** busca en Google Play o App Store y selecciona la app. Si no tiene perfil, se crea uno con la suite genérica.
2. **Instalación:** si la app no está en el teléfono, la consola lo indica y ofrece abrir la ficha en la tienda del teléfono. La instalación la haces tú, y la consola detecta sola cuando termina.
3. **Levantamiento:** el agente abre la app, recorre la pantalla principal con scroll y propone una calibración.
4. **Revisión:** eliges la firma de la pantalla, los componentes requeridos y los elementos que se pueden pulsar. La política impide autorizar elementos sensibles.
5. **Pruebas:** seleccionas casos y ejecutas. La consola muestra una línea de tiempo por paso, cada pantalla capturada y las observaciones en vivo.
6. **Publicar:** sube el perfil al catálogo público, después de un control automático de datos personales.

Mientras no haya levantamiento, solo se ejecutan los casos que no necesitan calibración: arranque sin crash, contenido inicial y accesibilidad.

## CLI

```bash
qa-agent profiles [--use <app>]      # lista perfiles y elige el activo
qa-agent devices                     # dispositivos, versión de SO e instalación de la app
qa-agent inspect [--app <app>]       # levantamiento (genera la calibración borrador)
qa-agent run [--app <app>] [--case HOME-001]
qa-agent history
qa-agent baseline approve <run_id>   # aprueba screenshots candidatas como baseline visual
```

## Seguridad y privacidad

- Usa solo cuentas de prueba autorizadas. No se permiten transacciones (`ActionPolicy`).
- Los secretos se leen de variables de entorno, `.env` o el Llavero de macOS:
  ```bash
  security add-generic-password -s mobile-qa-agent -a QA_PASSWORD -w '...'
  ```
- Los logs, page sources, eventos y reportes enmascaran secretos, documentos de identidad, teléfonos, emails y tarjetas.
- `runs/`, `baselines/`, `builds/`, `profiles/` y `.env` no se versionan en este repositorio. Las screenshots pueden mostrar datos de la cuenta.
- Para publicar un perfil, la consola pide confirmación y la publicación se bloquea si detecta datos personales.
