# T-NF-NOF1 · traza de comportamiento

`REA_EXECUTED = YES` sobre el artefacto del commit exacto. Lo observado y lo inferido van
separados, y lo que no se puede saber queda `UNKNOWN`.

## Observado por REA (`ev_4b2bf9c5c313530cc7e1e399d4cde5c175ecdd0018a9f608ee12782522ea9ade`)

- El dashboard del commit es **estático**: 2 ficheros JS + 1 HTML, 22 nodos y 27 aristas en
  el grafo de aplicación, **0 módulos** (no hay bundler en `public/`), 22 hallazgos, 0 fallos
  de parseo.
- No hay `import` de framework, ni entrypoint de aplicación compilada, ni mapa de módulos:
  REA no encuentra una "aplicación" en el sentido de un bundle, sólo dos scripts de página.
- REA parsea HTML y JS como texto inerte: **no ejecutó** ninguno de los dos.

## Observado por fuente (no REA)

| paso | fichero | hecho |
| --- | --- | --- |
| datos | `src/services/okxWebSocket.ts`, `gateClient.ts` | velas y ticker por websocket/REST |
| contexto | `src/services/multiTimeframeAnalysis.ts` | 6 timeframes (1m/3m/5m/15m/30m/1h) con `candleCount` fijo; EMA/RSI/ATR |
| payload al modelo | `src/agents/*.ts`, `src/tools/trading/*.ts` | **texto**: números + estructura, sin imagen |
| decisión | herramientas Voltagent (`execute`, `accountManagement`, …) | el LLM emite `symbol/side/leverage/amountUsdt` |
| riesgo | `src/config/riskParams.ts`, `tradeExecution.ts` | `MAX_POSITIONS=5`, `MAX_LEVERAGE=15`, ajuste por ATR; **drawdown desactivado** |
| ejecución | `gateClient.ts`, `okxClient.ts` | órdenes reales; testnet sólo por header |
| post-trade | `src/database/*`, `trailingStopMonitor.ts` | SQLite/libSQL, trailing stop, cierre parcial |

## `UNKNOWN` (y se queda así)

- Si esa cadena funciona hoy: el modelo por defecto (`deepseek/deepseek-v3.2-exp` vía
  OpenAI-compatible) no se invocó, no hay recibo.
- Qué devuelve el modelo ante un JSON inválido, un timeout o un rate limit: no hay test ni
  captura de ese escenario.
- Si el despliegue real de alguien usa exactamente este commit: no hay recibo de despliegue.

## Implicación para el RFC

El target queda `REA_TARGET_OBSERVED` en su superficie estática y `NOT_APPLICABLE_TECHNICALLY`
para la cadena de decisión, porque esa cadena es un servicio TypeScript que REA no ejecuta.
No se convierte una limitación de herramienta en una certificación.
