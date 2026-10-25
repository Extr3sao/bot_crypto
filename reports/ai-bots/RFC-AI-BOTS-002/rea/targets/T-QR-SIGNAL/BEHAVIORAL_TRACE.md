# T-QR-SIGNAL · traza de comportamiento

Tres operaciones REA con exit 0 sobre el commit exacto, con la página servida en loopback
desde `src/dashboard/static`. Sin backend, sin claves, sin exchange.

## Observado por REA

- `analyze_javascript_application` (`ev_9b45318c072de54798bb93a37354c38ec82b2bccf31d3cd1fbf9be0898a16b99`): 17 ficheros relevantes, 14 JS parseados,
  15.628 nodos AST, 86 hallazgos, 79 nodos / 115 aristas. Sin fallos de parseo.
- `analyze_web_bundle` (`ev_b954b8b016f1736a766bc45627a3d21f600503c1d4294e7147133a7ce461c46c`): 14 scripts observados y 14 analizados, 0 fallos,
  5 observaciones, 0 `unknowns`, `completeness=complete`. Es un dashboard **sin bundler**:
  el navegador carga los módulos tal cual.
- `capture_web_screenshot` (`ev_ee6845ff71d389439559036e9c661edbaee90a518ac18bd29639ef72995417a3`): PNG de 387.430 B, sha256 `1d3d9745…`, viewport
  1262×804, `complete_within_window`.

## Qué significa

El dashboard de Semantic Signal es un cliente de lectura de su API: paneles de consola,
posición, estadísticas, noticias, `performance_chart`, `decision_pathways_panel`,
`post_mortem_panel` y un `websocket.js`. Es decir: **la interfaz muestra la decisión, no la
produce**. REA confirma la superficie, no la cadena.

## `UNKNOWN`

- Qué endpoints llama en producción y con qué payload (sin backend, no hay red que observar).
- Si el modelo recibe el PNG o no: se resuelve por fuente, no por captura.
- Comportamiento ante timeouts, cuotas o JSON inválido.
