# T-FE-FENIX · correlación fuente ↔ REA ↔ runtime

`REA_EVIDENCE_ID`: `ev_be8c7d74bb6ed79011e4d135ba011c7df95df4d50fcdfc4086223f8fb5931cc6`, `ev_fc2b6552ff6ca513ad2cfcf4563e44b5d50354c61453bb999a4088cb3116d5c8`, `ev_b3b1e8374c0403d7b7c2cd9c4af9dbb33144920f515de8cd95d647b4d73527a7` (artefactos construidos desde `bd7373d59bee48addea51989796df27f69193a34`).

## El pipeline visual, tal como está en el commit

1. `ChartService.generate(kline, symbol, timeframe)` → `ChartResult(image_b64, filepath, …)`
   con estrategia Plotly → mplfinance → placeholder y caché TTL por timeframe.
2. El scheduler guarda `ChartSnapshot` con `timestamp`, `symbol`, `timeframe`, y expone
   `is_valid(max_age_seconds)`.
3. `create_visual_agent_node` lee `state["chart_image_b64"]` — una cadena base64 sin
   metadatos adjuntos — y construye el prompt con `symbol` y `timeframe` **del estado**.
4. Envía `{{"type": "image_url", "image_url": {{"url": "data:image/png;base64,<img>"}}}}`.
5. Ante error: backoff y, agotado, `HOLD`.

## Divergencias con nuestro runtime

| invariante | FenixAI | nuestro lane | veredicto |
| --- | --- | --- | --- |
| imagen alterada ⇒ abortar | no hay hash de imagen | `INTEGRITY_FAILURE` ⇒ `return None` | **somos más estrictos** |
| respuesta tardía ⇒ no operar | no hay reloj de respuesta | `LATE_RESPONSE` bloquea | **somos más estrictos** |
| símbolo de la imagen = símbolo del prompt | por convención del estado | por `chart.fingerprint()` + hash | **somos más estrictos** |
| frescura | TTL en caché | ventana PIT + `window_fingerprint` | ambos, a distinto nivel |
| fallback sin imagen | `HOLD` 0.5 | `return None`, 0 decisiones | equivalente en efecto |
| reintentos | backoff + feedback | política del provider | equivalente |

Conclusión honesta: **no hay capacidad de FenixAI que nuestro runtime no tenga ya, y en los
tres invariantes críticos estamos por delante**. Lo que aporta es un caso de estudio de cómo
se degrada un pipeline visual cuando la imagen viaja como cadena suelta.
