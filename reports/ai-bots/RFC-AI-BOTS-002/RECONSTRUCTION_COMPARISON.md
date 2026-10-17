# RECONSTRUCTION_COMPARISON — qué se comparó, con qué, y qué salió

Regla: un caso comparado no es una equivalencia. Se declara el veredicto por caso, y
`NOT_COMPARABLE` es un resultado, no un fracaso.

Implementación comparada: la que ya existe (`BOT-VIS-01`, `BOT-CTX-01`,
`src/trading_bot/vision/`, `RiskManager`). **No se reimplementó ningún bot en esta
iteración.**

## Matriz de casos

| caso | original observado | nuestro runtime | veredicto |
| --- | --- | --- | --- |
| gráfico generado desde el mismo contexto que se analiza | qrak: `analysis_engine` genera el PNG con `self.context` | `vision/chart.py` + `window_fingerprint` | `EQUIVALENT_ON_TESTED_CASES` (nosotros además con hash) |
| imagen alterada / ajena | FenixAI: base64 en `state`, sin hash ni símbolo ligado | `INTEGRITY_FAILURE` ⇒ 0 propuestas, 0 fills | `DIVERGENT_WE_ARE_STRICTER` |
| respuesta del modelo más tarde que la apertura | no existe guarda en ninguno de los dos | `LATE_RESPONSE` bloquea el fill | `NOT_COMPARABLE` (no hay contraparte) |
| modelo fija tamaño/apalancamiento | nof1: `execute(leverage, amountUsdt)` desde el LLM | prohibido por contrato; `RiskManager` decide | `DIVERGENT_BY_DESIGN` |
| risk recorta tamaño | qrak: `_resolve_position_size_pct` + `position_size_clamp` | `RiskManager` (sin cambios) | `EQUIVALENT_ON_TESTED_CASES` |
| guardas de drawdown | nof1: declaradas y **comentadas** | activas y testeadas | `DIVERGENT_WE_ARE_STRICTER` |
| contexto multi-timeframe | nof1: 6 timeframes, velas fijas | `BOT-CTX-01` agrega un TF superior | `NOT_COMPARABLE` hasta medir con el mismo reloj |
| sin modelo con visión ⇒ sin gráfico | qrak: `supports_image_analysis` | ruta sin provider de imagen | `EQUIVALENT_ON_TESTED_CASES` |
| comparación de corridas | ninguno de los dos la tiene | `NOT_COMPARABLE` como estado principal | `UNIQUE_TO_OURS` |

## Lo que no se comparó, y por qué

- **Rentabilidad**: ningún target se ejecutó con datos reales ni con LLM real. `NO_ECONOMIC_EDGE_FOUND`
  sigue siendo el estado honesto; no hay serie que medir.
- **Manejo de JSON inválido / timeout / rate limit**: se leyó el código de reintentos
  (FenixAI tiene backoff con feedback), pero no hay captura de esos escenarios. `UNKNOWN`.
- **TradingAgents y FortuneMal**: sin superficie REA o sin licencia. `NOT_COMPARABLE`.

## Conclusión

De los tres targets investigados esta sesión, **ninguno aporta una capacidad que nuestro
runtime no tenga**, y en los tres invariantes críticos (integridad de imagen, latencia de
respuesta, autoridad de tamaño) el nuestro es igual o más estricto. Eso es un resultado
negativo útil: evita adopciones cosméticas.
