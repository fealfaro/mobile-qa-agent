# Tasks: mobile-qa-agent

Leyenda: [x] hecho y verificado · [~] hecho, falta verificar en un dispositivo real · [ ] pendiente

## Fase 1: motor y primera ejecución real (Android)

- [x] 1.1 Toolchain: Java 21, Android command-line tools (adb, build-tools), Appium y driver uiautomator2.
- [x] 1.2 Core: modelo universal de casos, resultados, estados, contratos, registry y eventos.
- [x] 1.3 Gestión de dispositivos Android e iOS; `qa-agent doctor` y `qa-agent devices`.
- [x] 1.4 Driver Appium Android con `noReset`, screenshots (con respaldo `adb screencap`) e ids de WebView.
- [x] 1.5 Parser del árbol de accesibilidad, clasificador heurístico y explorador con scroll.
- [x] 1.6 Validadores genéricos y de pantalla principal; validación visual tolerante.
- [x] 1.7 Evidencias, enmascaramiento, reporte HTML e historial.
- [x] 1.8 Manejo de overlays que no están en el árbol de accesibilidad (detección visual y cierre calibrado).
- [x] 1.9 Primera suite real en un dispositivo físico: 6/6 casos y 20/20 validaciones PASS.

## Fase 2: consola web

- [x] 2.1 Consola local (`qa-agent web`): ficha de app y dispositivo, casos, ejecución en vivo con línea de tiempo, screenshots, observaciones e historial.

## Fase 3: white label y perfiles

- [x] 3.1 Quitar todas las referencias a una marca del código, la interfaz y la documentación; módulo `home_testing`.
- [x] 3.2 Perfiles por app (`profiles/<app>/`), perfil activo y suite genérica (`templates/suites/home.yaml`).
- [x] 3.3 Buscador de Google Play y App Store, con recuperación del id que falta en el resultado destacado.
- [x] 3.4 Creación de perfil desde la tienda, ficha de la segunda tienda y selección de perfil (API verificada).
- [x] 3.5 Estado de instalación y botón para abrir la ficha en la tienda del teléfono.
- [x] 3.6 Levantamiento compartido entre CLI y web, con eventos en vivo.
- [x] 3.7 Revisión y aprobación del borrador en la web, con bloqueos de la política (API verificada).
- [x] 3.8 Publicación del perfil en el catálogo público, con control de datos personales.
- [~] 3.9 Flujo completo de una app nueva en el dispositivo: búsqueda, instalación, levantamiento, revisión, pruebas y publicación.

## Siguientes

- [ ] 4.1 iOS: Xcode, driver xcuitest y firma de WebDriverAgent; calibración y suite en iPhone.
- [ ] 4.2 Comparar ejecuciones (`qa-agent compare A B`) y tendencias por app.
- [ ] 4.3 Detección de crashes en iOS.
- [ ] 4.4 Proveedor LLM para explicar fallos y clasificar componentes de baja confianza, con una política de datos definida.
- [ ] 4.5 Importadores de casos (Markdown, Excel, Jira) con salida en borrador.
- [ ] 4.6 Persistencia en PostgreSQL y ejecución en varios dispositivos.
