# RFC-TAP-AI-BOTS-003H — Accounting Integrity & PAPER Readiness

**Estado:** implementado y medido; veredicto en
`reports/ai-bots/RFC-AI-BOTS-003H/FINAL_REPORT.md`.
**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Base medida al abrir:** `fe9b5e2` · **Modo:** PAPER/SHADOW · **LIVE: no habilitado, sin ruta de
orden** · `config/risk.yaml` leído, nunca escrito.

> **Alcance.** Este WP no añade arquitectura, agentes ni estrategias. Corrige un defecto
> contable medido en 003G (D5), cierra los huecos de validación que 003G dejó abiertos y ejecuta
> un smoke PAPER real con el código congelado. La evidencia de 003G **no se toca**: se conserva
> byte a byte y sus verificadores siguen ejecutándose sobre ella.

---

## 1. Problema (todo medido, con su ruta)

| # | Defecto / pregunta | Evidencia de partida |
| - | --- | --- |
| P1 | `costs_usdt` publicaba 0 con una posición abierta que ya debía 0,5 USDT; el equity marcado era 9 998,371187 | `lane.py` `_summary` sumaba `broker.closed_trades`; `broker.accrued_entry_commissions()` existía y no se usaba |
| P2 | La fila `FILL` no llevaba la comisión, así que la acusación no era reconstruible desde el ledger | claves de la fila `FILL` en `session/cycles/cycle-0008/ledger.jsonl` |
| P3 | El resumen de sesión no publicaba ningún término contable | `session/SUMMARY.json` de 003G |
| P4 | `test_runtime_artifacts_are_untouched_by_serving` fallaba con un escritor concurrente | reproducido: 1 test fallido, 7 844 artefactos idénticos salvo el fichero ajeno |
| P5 | La sesión publicada declaraba `duration_s=2400` con `--max-cycles 8`; la de 50 minutos es otra | `session/SESSION_START.json` vs `session-aborted-aggregation/SESSION_START.json` |

## 2. Objetivo

Que un lector de una sesión PAPER —humano o verificador— no tenga que adivinar si el coste que
lee incluye una posición que sigue viva, y que la afirmación sea reconstruible desde los bytes
crudos.

## 3. Contrato contable `paper-accounting/2`

`costs_usdt` **mantiene su significado** (coste realizado de operaciones cerradas). Los términos
nuevos se publican a su lado, cada uno con su definición dentro del propio artefacto
(`summary.accounting.meanings`), y el esquema va versionado.

| Campo | Significado |
| --- | --- |
| `costs_usdt` | realizado: `execution + entry + exit` de operaciones **cerradas** (sin cambios) |
| `costs_realised_usdt` | el mismo valor, nombrado para emparejarlo con el total |
| `entry_commissions_realised_usdt` / `exit_commissions_realised_usdt` / `execution_costs_realised_usdt` | las tres patas del coste realizado |
| `entry_commissions_accrued_open_usdt` | comisiones de entrada de posiciones **abiertas**: debidas, retenidas ya del equity marcado |
| `costs_total_usdt` | `costs_usdt + entry_commissions_accrued_open_usdt` |
| `pnl_realised_usdt` | neto de operaciones cerradas |
| `pnl_unrealised_usdt` | posición abierta marcada al último cierre observable, **neta** de la comisión devengada |
| `pnl_total_usdt` | `pnl_realised_usdt + pnl_unrealised_usdt` |
| `marked_equity_usdt` | `initial_equity + pnl_total_usdt` |

Identidades nuevas en `summary.reconciliation.identities` (todas booleanas, todas exigidas):

- `total_costs_equal_realised_plus_accrued`
- `realised_costs_equal_closed_trade_legs`
- `marked_equity_rebuilds_from_open_position`
- `total_pnl_moves_the_marked_book`
- `open_positions_are_disjoint_from_closed_trades`

**Sin doble conteo por construcción:** el broker hace `pop` de la posición al cerrar, así que una
posición está abierta (comisión devengada) o cerrada (comisión realizada), nunca las dos; la
disjunción se comprueba por `position_id` y además por identidad.

Además, la fila `FILL` publica `entry_commission_usdt`, `commission_bps` y `price_bps_per_side`,
de modo que un verificador externo puede reconstruir el devengo desde el ledger sin leer el
resumen (P2).

## 4. Integridad de datos

| Garantía | Dónde | Test / check |
| --- | --- | --- |
| Una vela en formación no se guarda | `MinuteBar.from_kline` + reloj del venue | `test_a_minute_that_closes_after_the_venue_clock_is_never_stored` |
| Una vela recién cerrada espera `settle_ms` | `MinuteCollector._parse_page(require_settled=True)` | `test_settle_defers_a_just_closed_minute_until_it_can_no_longer_move` |
| Una vela revisada bloquea y no reescribe | `MinuteStore.append` + `DUPLICATE_CONFLICT` | `test_a_revised_closed_minute_blocks_and_never_rewrites_the_store` |
| Los cuatro instantes y sus dos esperas | `MinuteBar` (`delivery_latency_ms`) y `execution.schedule` (`lag_ms`) | `test_the_four_instants_are_ordered_and_the_two_waits_are_additive`, `test_the_quote_wait_is_measured_from_the_answer_not_from_the_close` |
| Sin precio posterior no hay relleno | `execution.schedule` → `WAIT` | `test_a_quote_from_before_the_answer_waits_instead_of_filling` |
| Huecos, duplicados, desorden, stale, skew | `MinuteCollector` | suite `tests/unit/market_data` (134 + 6 nuevos) |
| Point-in-time en la decisión | `prospective` (`data_time + delay + settle ≤ decision_time`) | suite `tests/unit/vision/test_prospective_session.py` |

Ninguna protección se relaja para conseguir rellenos: el relleno sigue exigiendo un precio
**observado** en o después de la respuesta.

## 5. Regresiones

- Se reproduce P4 con evidencia y se corrige **aislando el sujeto**: el test hashea un árbol
  propio (`tmp_path`) porque la propiedad es «el dashboard no escribe lo que sirve», no «nadie
  escribe en `reports/`». Reproducción: 1 fallido con 7 844 artefactos idénticos salvo el
  fichero del escritor ajeno. Tras el arreglo: 14/14 con el escritor concurrente activo.
- Suites afectadas y regresión ancha: ver `RUN_REPORT.md` §2 con exit codes reales.
- Un fallo persistente se reporta como FAIL/PARTIAL, nunca como PASS.

## 6. Smoke PAPER

Sesión real con el código congelado (`logs/rfc003h/freeze.json`), sin LIVE, 10 ciclos sobre
Binance Spot 1 m. Los términos contables se recalculan desde el ledger y los minutos crudos con
`scripts/ai_bots_003h_verify.py`, que no importa `trading_bot`.

## 7. Puertas

| Puerta | Umbral | Medición |
| --- | --- | --- |
| H1 contabilidad | `costs_total = costs_usdt + devengado`; equity marcado reconstruible desde el minuto crudo | verificador 003H checks 26-30 |
| H2 doble conteo | 0 posiciones abiertas y cerradas a la vez | check 30 |
| H3 instantes | `received ≤ quote_ts`, `quote_lag = quote_ts − received`, `opinion_age = quote_ts − decision_ts` | check 31 |
| H4 settle | 0 minutos en vivo guardados antes de `close + settle_ms` | check 32 |
| H5 proyección | el resumen de sesión no contradice el ledger | check 33 |
| H6 regresión | 0 fallos nuevos en las suites tocadas | `RUN_REPORT.md` §2 |
| H7 LIVE | 0 órdenes y 0 rutas de orden | checks 5 y 23 de 003G |
| H8 economía | ≥ 30 cierres para juzgar | `INSUFFICIENT_SAMPLE` si no llega |

## 8. Reglas de evidencia

- `FALSE_SUCCESS=0`: cada cifra sale de un comando con su exit code; lo no ejecutado se declara
  pendiente.
- `BUILDER != VERIFIER`: el verificador de bytes no sustituye una revisión por un tercero; sin
  ella el estado es `INDEPENDENT_VERIFICATION_PENDING`.
- La evidencia de 003G se conserva inmutable. Su verificador sigue recomputando la sesión
  publicada y pasa **24/25**: el check que falla es `tested_runtime_equals_used_runtime`,
  porque 003H cambió `lane.py` y `prospective.py` después de aquella sesión. El drift está
  medido y declarado en `reports/ai-bots/RFC-AI-BOTS-003H/STATE_AUDIT.md` §6.1, con los
  hashes originales que la propia sesión guardó en `SESSION_START.json`.
- Nada de otro WP se reatribuye; los ficheros ajenos sucios en el árbol no se tocan.

## 9. Criterio de terminación

`PASS` sólo con: contabilidad que cuadra contra los bytes crudos, gates H1-H5 y H7 en verde,
H6 sin fallos nuevos y evidencia reproducible. Si falta la revisión de un tercero o la muestra
económica, el resultado es `PARTIAL` con el blocker explícito.
