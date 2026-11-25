# Requirements: mobile-qa-agent

## Introducción

Plataforma white label de QA automatizado para apps móviles nativas e híbridas. Cualquier app se elige desde Google Play o App Store, se prepara con un levantamiento revisado por una persona y se prueba con casos reutilizables. Todas las pruebas son de lectura o de navegación no transaccional.

## Glosario

- **Perfil:** carpeta `profiles/<app>/` con la ficha de la app, su calibración y sus suites.
- **Catálogo:** repositorio público que agrupa perfiles.
- **Levantamiento:** recorrido de solo lectura de la app real, que genera una calibración borrador.
- **Calibración:** selectores reales de una pantalla. Solo se usa con `status: reviewed`.
- **Objetivo de navegación:** elemento no transaccional que una persona autorizó a pulsar.
- **Evidencia:** screenshot, page source enmascarado, log o JSON asociado a un resultado.

## Requisitos

### R1. Gestión de dispositivos
1. El agente DEBE listar los dispositivos Android (emulador y físico) e iOS (simulador y físico) con su id, modelo, tipo, estado y versión de SO.
2. SI falta el toolchain, ENTONCES el agente DEBE indicar qué falta y cómo instalarlo (`qa-agent doctor`).
3. Con varios dispositivos, el agente DEBE preferir los físicos y permitir elegir uno.
4. La ejecución es secuencial, con interfaces preparadas para varios dispositivos.

### R2. Selección de la app
1. El usuario DEBE poder buscar apps en Google Play y en App Store por nombre, y ver ícono, nombre, desarrollador, rating e id.
2. Al seleccionar una app sin perfil, el agente DEBE crear un perfil con la ficha de la tienda y la suite genérica.
3. SI la app ya tiene perfil, ENTONCES el agente DEBE reutilizarlo.
4. El usuario DEBE poder agregar al mismo perfil la ficha de la otra tienda.
5. El agente NO DEBE inventar ids: un resultado sin id confiable no se ofrece.

### R3. Instalación
1. El agente DEBE indicar si la app del perfil está instalada en el dispositivo, con su versión, build, peso y target SDK.
2. SI no está instalada, ENTONCES el agente DEBE avisar al usuario y ofrecer abrir la ficha de la tienda en el teléfono.
3. El agente NO DEBE instalar desde la tienda por su cuenta. DEBE detectar cuándo termina la instalación.
4. Instalar builds locales exige `--authorized` y que el archivo esté en `builds/`.

### R4. Levantamiento y calibración
1. El agente DEBE abrir la app sin borrar datos (`noReset`) y verificar que está en primer plano.
2. El agente DEBE recorrer la pantalla principal con scroll y clasificar sus componentes con un nivel de confianza.
3. El agente DEBE proponer una firma de pantalla, componentes y candidatos a navegación, marcando los bloqueados por la política.
4. Una persona DEBE revisar y aprobar el borrador antes de usarlo. La aprobación registra quién revisó.
5. Sin calibración revisada, los casos que la necesitan DEBEN quedar bloqueados y los genéricos DEBEN seguir ejecutándose.

### R5. Validaciones
1. **Validaciones genéricas:** app instalada, en primer plano, pantalla no vacía, sin crash ni ANR, carga completada, sin mensajes de error, elementos interactivos y cobertura de accesibilidad.
2. **Validaciones calibradas:** pantalla reconocida, tiempo de carga, componentes requeridos, texto esperado, componente habilitado, navegación con retorno y overlays accesibles.
3. **Validación visual tolerante** contra una baseline por app y clase de dispositivo.
4. Los estados posibles son PASS, FAIL, BLOCKED, INCONCLUSIVE y NOT_EXECUTED. Un PASS sin evidencia se degrada a INCONCLUSIVE. Los problemas de entorno son BLOCKED.

### R6. Modelo universal de casos
1. Cada caso incluye id, nombre, descripción, plataforma, prioridad, precondiciones, datos de prueba, pasos, resultados esperados, validaciones y política de evidencias.
2. El modelo es independiente de la app y se carga desde YAML o JSON mediante importadores intercambiables.

### R7. Evidencias, reportes y consola
1. Cada ejecución DEBE registrar el id, la app y su versión, el dispositivo y el SO, la fecha, la duración, el resultado por paso y por validación, las screenshots, los logs y los errores.
2. El agente DEBE generar `report.html` y un historial por app.
3. La consola web DEBE mostrar en vivo la línea de tiempo, las pantallas y las observaciones de ejecuciones y levantamientos.

### R8. Publicación de perfiles
1. El usuario DEBE poder publicar un perfil en el catálogo público, con confirmación explícita.
2. La publicación DEBE bloquearse si el perfil contiene datos personales detectables.
3. NUNCA se publican screenshots, evidencias ni baselines.

### R9. Seguridad
1. Los secretos se leen de variables de entorno, `.env` o el Llavero, y nunca se escriben en el código.
2. Los logs, page sources, eventos y reportes se enmascaran.
3. El agente DEBE bloquear las acciones transaccionales y los taps con palabras sensibles, tanto las de la lista por defecto como las del perfil.
4. La consola escucha solo en localhost y no permite rutas fuera de `runs/` ni de `profiles/`.

### R10. White label y extensibilidad
1. El código, la documentación y la interfaz NO DEBEN contener referencias a una marca o app concreta.
2. Agregar una app DEBE requerir solo un perfil. Agregar un módulo funcional DEBE requerir solo un paquete en `modules/`, sin modificar el core.

### R11. Inteligencia artificial (futuro)
1. La IA solo propone, explica o clasifica. Nunca ejecuta acciones ni cambia estados.
