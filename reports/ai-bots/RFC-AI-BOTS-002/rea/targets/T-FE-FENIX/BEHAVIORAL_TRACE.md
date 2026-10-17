# T-FE-FENIX · traza de comportamiento

Tres operaciones REA con exit 0 sobre artefactos **derivados del commit exacto**: el
`frontend/dist` se construyó aquí (`npm ci` 285 paquetes, `vite build` 2367 módulos, exit 0)
y se sirvió en loopback. Nada se descargó de un despliegue ajeno.

## Observado por REA

- Bundle: 1 módulo de 868 kB, 256.917 nodos AST, 35 hallazgos, 0 fallos de parseo,
  `completeness=complete` en la captura web.
- La aplicación arranca en `/login` sin backend: la superficie pública del commit es una
  pantalla de acceso. El dashboard con posiciones/alertas requiere sesión.
- REA declara explícitamente que el grafo está incompleto y que el bundle no se ejecutó.

## Observado por fuente (no REA)

| paso | fichero | hecho medido |
| --- | --- | --- |
| render | `src/charts/service.py` + `plotly_strategy.py` / `mpl_strategy.py` / `placeholder_strategy.py` | PNG en base64 con cadena de fallback y caché TTL por timeframe |
| frescura | `src/tools/chart_capture_scheduler.py` | `ChartSnapshot.is_valid(max_age_seconds)` sí existe… **en la caché** |
| consumo | `src/core/orchestrator/agents/visual.py` | toma `state["chart_image_b64"]`, etiqueta con `state["symbol"]`, envía `data:image/png;base64,…` |
| guarda de imagen | `visual.py` | **ninguna**: no comprueba edad, símbolo ni hash de la imagen que envía |
| fallback | `visual.py` | sin imagen ⇒ `HOLD` con `confidence 0.5` |
| reintentos | `visual.py` | backoff exponencial con feedback |
| riesgo | fuera del nodo visual | el nodo no toca tamaño ni apalancamiento |

## `UNKNOWN`

- Qué decide el modelo real: no hay credencial ni recibo, y `REAL_MODEL_CALLED=false`.
- Si el estado puede llegar con la imagen de otro símbolo: la caché está indexada por
  `symbol_timeframe`, pero el nodo no lo verifica; no se reprodujo el fallo, se leyó el código.
