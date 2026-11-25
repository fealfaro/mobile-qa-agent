# Levantamiento y calibración

Los selectores de una app **no se escriben a mano ni se inventan**: salen de la app real.

1. **Levantamiento.** Desde la consola web ("Hacer levantamiento") o con `qa-agent inspect --app <app>`, el agente abre la app, recorre la pantalla principal con scroll (solo lectura) y genera `profiles/<app>/calibration/home-testing.<platform>.draft.yaml`.
2. **Revisión humana**, en la consola web ("Revisar") o editando el borrador:
   - La **firma** `screens.home` debe identificar la pantalla principal sin ambigüedad. No debe aparecer en el login ni en otras pantallas. Conviene evitar elementos comunes a todas las pantallas, como la barra superior o la inferior.
   - Los componentes **requeridos** son los que deben existir siempre. No marques los promocionales ni los que dependen del tipo de cliente.
   - La **navegación** se autoriza solo en elementos de consulta. La política impide autorizar elementos con palabras sensibles (comprar, pagar, suscribir, eliminar, cerrar sesión...).
   - **Overlays:** si un modal tapa la pantalla y no está en el árbol de accesibilidad, se agrega en `overlays` con su forma de detección y de cierre.
3. **Aprobación.** El resultado se guarda como `home-testing.<platform>.yaml` con `status: reviewed` y `calibrated_by`.

El runner ignora cualquier calibración sin `status: reviewed`. Sin calibración revisada, los casos que la necesitan quedan bloqueados y solo corren los genéricos.
