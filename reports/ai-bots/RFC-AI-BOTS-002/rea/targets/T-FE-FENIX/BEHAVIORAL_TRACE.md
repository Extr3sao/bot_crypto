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

## Ejecutado de verdad (no REA, instrumentado)

`instrumentation/fenix_chart_probe.py` corre el código del commit exacto con velas
sintéticas, offline y sin claves. Salida: `instrumentation/fenix_chart_probe.json`,
exit 0, `verdict = RENDER_AND_CACHE_REPRODUCED`.

| medido | valor |
| --- | --- |
| backend elegido | `MPLFINANCE` — `"mplfinance chart BTCUSDT 15m (100 candles)"` |
| PNG | 181.314 B, sha256 `96c7f41c…c61e`, cabecera PNG válida |
| determinismo | mismo PNG con las mismas velas, caché desactivada |
| caché por símbolo | BTCUSDT acierta; **ETHUSDT no reutiliza** la imagen |
| `get_cached(max_age=0)` | devuelve resultado: el cero se trata como "sin límite" |
| `ChartSnapshot.is_valid()` a las 2 h | `False` |
| payload al modelo | base64 desnudo; sin hash, sin símbolo, sin timestamp |

**Degradación observada, no deducida:** en la primera pasada, sin `mplfinance` instalado, el
servicio devolvió `ok=True` con backend `PLACEHOLDER` y descripción
`"Placeholder: No chart data available"`. Un consumidor que sólo mire `ok` manda al modelo un
cartel gris creyendo que manda un gráfico.
