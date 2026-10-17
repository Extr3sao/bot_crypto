# Instrumentación offline del pipeline de gráfico de FenixAI

**Clase de evidencia: `INSTRUMENTED_EXECUTION_NOT_REA`.** REA no ejecuta Python; esto es la
prueba complementaria que la RFC pide para el plano que REA no alcanza, etiquetada como tal
para que nadie la confunda con evidencia REA.

## Qué se ejecutó

`fenix_chart_probe.py` importa **el código del commit exacto**
(`bd7373d59bee48addea51989796df27f69193a34`) y llama a su `ChartService` con 120 velas
sintéticas generadas de forma determinista. Sin red, sin claves, sin exchange, sin órdenes,
sin tocar riesgo.

| paso | resultado medido |
| --- | --- |
| import de `src.charts.service` | ok |
| `generate()` BTCUSDT/15m | ok — backend `MPLFINANCE`, 378,5 ms, `"mplfinance chart BTCUSDT 15m (100 candles)"` |
| PNG | 181.314 bytes, `sha256 96c7f41c928e6b1810015ebf745783823b35fb6eacf5eb614a07ec4b7bebc61e`, cabecera PNG válida |
| determinismo con las mismas velas | **mismo PNG** (cache desactivada) |
| caché por símbolo | BTCUSDT acierta; ETHUSDT **no** hereda la imagen |
| `get_cached(max_age=0)` | **devuelve resultado** en vez de `None` |
| `ChartSnapshot.is_valid()` con snapshot de 2 h | `False` (el contenedor sabe envejecer) |
| payload al modelo | base64 desnudo: sin hash, sin símbolo, sin timestamp |

## Entorno, declarado

`python -m venv --system-site-packages` en el sandbox, con `mplfinance 0.12.10b0`,
`apscheduler` y los `pandas 3.0.6` / `matplotlib 3.11.2` del entorno del proyecto.
**No es su entorno**: no se reclama identidad de bytes con su CI. `plotly` no está instalado,
así que la cadena **degradó** — y esa degradación fue observada: sin `mplfinance`, el servicio
cae a `RenderBackend.PLACEHOLDER` con `"Placeholder: No chart data available"` (probado en la
primera pasada). Dos de los tres backends quedan por tanto ejercitados.

## Qué prueba

1. El renderizador del commit exacto **funciona offline** y produce un PNG real a partir de
   las velas que se le pasan.
2. El servicio **degrada** a placeholder sin errores visibles en el resultado: `ok=True`.
   Quien consuma `ChartResult.ok` sin mirar `backend` está enviando al modelo un cartel gris.
3. La caché está indexada por `symbol_timeframe`: no cruza símbolos.
4. **`max_age=0` no significa "recién hecho"**: `ttl = max_age or TIMEFRAME_TTL[...]` trata el
   cero como ausente y aplica el TTL por defecto. Su control de frescura no se puede endurecer
   por esa vía.
5. La imagen viaja al modelo como base64 desnudo, sin hash, símbolo ni reloj.

## Qué no prueba

- **No se llamó a ningún modelo**: la ruta del proveedor no se ejecutó.
- No se usó su backend Python completo (LangGraph, claves, servicios).
- No se ejecutó nada del exchange, ni del riesgo, ni del ejecutor.
- No se reclama equivalencia de bytes con su build de producción.

## Reproducir

```bash
# sandbox con el checkout exacto en PROBE_TARGET_ROOT
cd "$PROBE_TARGET_ROOT"
"$PROBE_PYTHON" fenix_chart_probe.py bd7373d59bee48addea51989796df27f69193a34 out.json
```

Salida esperada: `verdict = RENDER_AND_CACHE_REPRODUCED`, exit 0.
