# Roadmap vinculado — RFC-TAP-MARKET-005

**Estado:** PROPOSED (ningún WP ejecutado en este documento). Afecta al Excel master en rama `project/roadmap-trading-agentic`.

| Orden | WP | Resultado esperado | Estado | Gate |
|---|---|---|---|---|
| 0 | 005A process/scheduler authority | Descargas fotografiadas atribuidas (o honestamente UNKNOWN) con PID/task/run_id y consumidor | PENDIENTE | READ-ONLY, sin apagar tasks |
| 1 | 005B baseline | Nº requests, bytes, cobertura y origen sin LLM real | PENDIENTE | misma ventana, mismas series |
| 2 | 005C bootstrap + incremental | Watermarks, delta, idempotencia y correcciones | PENDIENTE | datos cerrados y PIT |
| 3 | 005D snapshot/bridge | `MarketSnapshot` causal consumible por PAPER/SHADOW | PENDIENTE | TEST_TARGET==RUNTIME_TARGET |
| 4 | 005E event-driven IA (offline) | Cada dato se observa muchas veces; el LLM solo al evento/coste permitido | PENDIENTE | 0 paid calls, 0 request IDs fake |
| 5 | 005F redundancy matrix | `KEEP/OPTIMIZE/MERGE/DISABLE_CANDIDATE` por productor y consumidor | PENDIENTE | no desactivar ninguna tarea |
| 6 | 005G independent verification | Mutaciones, análisis comparativo y reporte | PENDIENTE | BUILDER!=VERIFIER |
| 7 | 005H optional paper activation | Proceso sin ventanas y pipeline paper supervisado | BLOQUEADO | cambio de scheduler requiere aprobación |

## Prioridades del roadmap general

1. **P0 DATA:** Resolver origen de `fetch_ohlcv` y reducir descargas completas repetidas **sin perder ninguna vela final ni PIT**.
2. **P0 INFERENCE:** `AI-BOTS-003D` provider offline readiness / coste/receipt; ninguna llamada LLM hasta permiso y credenciales.
3. **P0 PAPER:** `AI-BOTS-003E` captura prospectiva y 1m/quotes; diferenciar collectors de research.
4. **P0 ECONOMICS:** desbloquear `StrategyAdmission` con OOS y pruebas netas robustas. En EDGE-017F todas las replays netas seguían negativas.
5. **P1 AGENT:** `AI-BOTS-004` crítico investigador, SHADOW/REA+upstream Python; no bloquear PAPER antes de medir valor.
6. **P1 OPS:** `TAP-062` (Freebuff popup externo) y `TAP-063` (tarea programada sin activar) se mantienen como bloqueos separados.

El usuario no tiene que aprobar los WPs técnicos offline. Se requiere permiso para modificar Task Scheduler, credenciales, APIs de pago, live trading, riesgo/fin de semana o destrucción.

**Control de estado:** DATA_FRESH ≠ MODEL_CALLED ≠ PAPER_PROSPECTIVE ≠ EDGE_PROFITABLE. Un cambio que reduce HTTP requests es mejora operacional, no estrategia rentable.
