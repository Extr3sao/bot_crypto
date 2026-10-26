# INDEPENDENT_VERIFICATION — RFC-TAP-AI-BOTS-003G

**Sesión verificada:** `reports/ai-bots/RFC-AI-BOTS-003G/session`
**Herramienta:** [ai_bots_003g_verify.py](../../../scripts/ai_bots_003g_verify.py)
**Resultado:** **25 PASS / 0 FAIL**, exit 0 · **imports de `trading_bot`: 0**
**Veredicto de independencia:** `INDEPENDENT_VERIFICATION_PENDING` — el verificador lo escribió
el mismo agente que construyó el carril (`BUILDER != VERIFIER` no se cumple). Lo que sigue es
verificación *de bytes*, no verificación por un segundo agente.

---

## 1. Qué hace y qué no hace

El verificador lee el JSONL crudo (`STREAM.jsonl`, `SUMMARY.json`, `cycles/*/ledger.jsonl`,
`market-1m/*.jsonl`, identidades de `RUN_META.json`) y **recalcula** cada número desde esos
bytes: no llama a `trading_bot`, no vuelve a ejecutar el carril y no acepta un valor porque el
resumen lo diga. El hash de runtime del manifiesto se compara con el `runtime_sha256` que el
propio stream declaró al arrancar, de modo que "ejecuté el código que probé" es comprobable.

**No** prueba que el carril sea correcto en general; prueba que **este artefacto** es coherente
consigo mismo y con los minutos de Binance que contiene. Un error de diseño compartido por el
carril y el verificador (misma lectura de un campo) sólo lo detectaría un segundo agente humano
o un verificador escrito desde la especificación, y eso está declarado como pendiente.

## 2. Los 25 checks

| # | check | resultado | qué comprueba |
| --- | --- | --- | --- |
| 1 | `stream_chain_intact` | PASS (11 filas) | `prev_sha256` de cada fila del stream |
| 2 | `session_is_paper` | PASS | `mode=PAPER`, `live_enabled=False` |
| 3 | `subbar_enabled_for_paper_only` | PASS | `subbar_entries=PAPER_ONLY` |
| 4 | `tested_runtime_equals_used_runtime` | PASS | sha256 de los ficheros ejecutados vs. declarados |
| 5 | `no_live_order_route_in_runtime` | PASS | ni endpoint de órdenes ni llamada de orden en el runtime |
| 6 | `every_stored_minute_is_closed` | PASS | ninguna vela en formación guardada |
| 7 | `minutes_strictly_increasing` | PASS | sin duplicados ni desorden |
| 8 | `a_cycle_was_executed` | PASS (8) | la sesión no es un arranque vacío |
| 9 | `data_time_le_decision_time` | PASS | ninguna decisión conoce el futuro |
| 10 | `declared_delay_is_inside_the_wait` | PASS | la espera incluye el retardo medido |
| 11 | `published_series_rebuilds_from_minutes` | PASS | digest 5 m recomputado por ciclo |
| 12 | `cycle_ledgers_are_chained` | PASS | cadenas `prev_sha256` de los ledgers |
| 13 | `subbar_fills_are_observed_prices` | PASS | precio de relleno = apertura 1 m observada ≥ respuesta |
| 14 | `entry_bar_range_is_post_fill` | PASS | rango reconstruido minuto a minuto, sólo posteriores |
| 15 | `at_least_one_subbar_fill` | PASS | 6 filas `FILL` en los ledgers acumulados, 1 en el último |
| 16 | `fills_have_an_approved_risk_gate` | PASS | cada relleno une una decisión aprobada |
| 17 | `close_pnl_identity_holds` | PASS | neto = bruto − comisiones − coste de ejecución |
| 18 | `no_past_decision_changed` | PASS | prefijo determinista ciclo a ciclo |
| 19 | `summary_net_matches_ledger` | PASS (0 = 0) | resumen contra ledger |
| 20 | `summary_fills_match_ledger` | PASS (1 = 1) | resumen contra ledger |
| 21 | `summary_closed_match_ledger` | PASS (0 = 0) | resumen contra ledger |
| 22 | `no_live_orders_recorded` | PASS | `live_orders=0` en todas las filas del stream |
| 23 | `no_live_mode_in_any_artifact` | PASS | ningún artefacto se autodeclara LIVE |
| 24 | `receipt_is_never_before_the_close` | PASS (552 minutos) | `received_at` ≥ cierre + retardo |
| 25 | `manifest_matches_the_minute_bytes` | PASS | sha256 de cada almacén vs. manifiesto |

Salida completa: [VERIFICATION.md](session/VERIFICATION.md) y
[VERIFICATION.json](session/VERIFICATION.json).

### Lectura del check 15

Cada `cycles/cycle-000N/ledger.jsonl` es el **ledger acumulado** hasta ese ciclo, no un delta.
Por eso la fila `FILL` de `pos-…-00000001` aparece en los ciclos 3, 4, 5, 6, 7 y 8 (6
apariciones) y el contador de rellenos sigue siendo **1**. Contar filas `FILL` como operaciones
sería un error de lectura; el verificador cuenta posiciones distintas (`position_id`) para el
resumen y por eso `summary_fills_match_ledger` compara 1 = 1.

## 3. Prueba de que el verificador no es vacuo

Se copió la sesión de humo a un directorio temporal, se mutó el byte concreto y se volvió a
ejecutar el verificador sobre la copia. Se re-sellaron las cadenas cuando la mutación lo exigía,
para que el fallo tuviera que venir del check semántico y no del hash.

| Mutación | Resultado | Check que la detecta |
| --- | --- | --- |
| `entry_price` del FILL +1 USDT y cadena del ciclo re-sellada | DETECTED | `subbar_fills_are_observed_prices` + `cycle_ledgers_are_chained` |
| Un minuto crudo del centro de la serie alterado | DETECTED | `published_series_rebuilds_from_minutes` + `manifest_matches_the_minute_bytes` |
| `decision_time` anterior a `data_time` | DETECTED | `data_time_le_decision_time` |
| `received_at` posterior al relleno | DETECTED | `subbar_fills_are_observed_prices` |

4/4 mutaciones detectadas. No se probó una quinta (por ejemplo `live_enabled=true`): se declara
como no ejecutada en vez de listarla como superada. El verificador **falla** cuando el artefacto
miente, que es la única propiedad que lo hace útil.

## 4. Lo que la verificación *no* cubre

1. **Independencia de autor.** Mismo agente constructor y verificador.
2. **Economía.** 1 relleno, 0 cierres: las identidades de PnL se comprueban sobre cero
   operaciones cerradas. `close_pnl_identity_holds` es trivialmente cierto en esta sesión.
3. **Coste total.** `costs_usdt` sólo agrega operaciones cerradas (003G-D5): la comisión de
   0,5 USDT de la posición abierta **no** aparece en ese campo, sí en el equity marcado. El
   verificador no lo marca como fallo porque el campo es coherente con su definición realizada;
   se declara en `RUN_REPORT.md` para que nadie lo lea como coste total.
4. **Proveedor real.** `paper-script`; `REAL_MODEL_CALLED=false`. Nada aquí mide un modelo.
5. **Mercado distinto.** Una sola ventana de 32 minutos, dos símbolos, un régimen.
