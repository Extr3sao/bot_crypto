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

## Lo que pasó de "leído" a "ejecutado"

| afirmación | antes | ahora |
| --- | --- | --- |
| el renderizador produce un PNG desde las velas dadas | fuente | **ejecutado**: 181.314 B, backend mplfinance |
| la cadena degrada cuando falta un backend | fuente | **ejecutado**: cae a PLACEHOLDER con `ok=True` |
| la caché no cruza símbolos | fuente | **ejecutado**: ETHUSDT no recibe la imagen de BTCUSDT |
| la frescura existe como primitiva | fuente | **ejecutado**: `is_valid()` es `False` a las 2 h |
| `max_age` permite exigir frescura | supuesto agradable | **refutado**: `max_age=0` aplica el TTL por defecto |

Ese último punto es un fallo real y reproducible en el commit fijado: `ttl = max_age or
TIMEFRAME_TTL.get(timeframe, 120)` trata `0` como "no especificado". Quien intente endurecer
la frescura pasando `max_age=0` obtiene lo contrario de lo que pide. Queda registrado como
divergencia en `RECONSTRUCTION_OBLIGATIONS.json`.

Nada de esto cambia la decisión (`DEFER`): el plano que importa —modelo real, coste,
economía— sigue sin ejecutarse.
