# DECISION_TRACE_REPORT — qué demuestra el trace de decisión

> Fase: RISK-IN-SHADOW + BAR-CLOSE AVAILABILITY. Código:
> `src/trading_bot/autonomous/{contracts,trace,runtime}.py`.
> Artefacto real: `reports/autonomous-paper/autonomous-paper-real-004/traces.jsonl`
> (append-only, JSON Lines, un registro por decisión).

## 1. Qué se persiste, por decisión

Una fila por `(ciclo, activo)`. Cada registro (`DecisionTrace`,
`schema_version = decision-trace-v1`) contiene:

| Bloque | Campos |
| --- | --- |
| identidad | `run_id`, `decision_id`, `asset`, `symbol`, `sequence` |
| tiempo | `market_time_ms`, `decision_time_ms`, `created_at_ms` |
| contexto | `market_context`, `asset_context`, `regime` |
| candidatos | `strategies_considered[]` con `admission_status`, `admitted_for_paper`, `expected_gross_edge_bps`, `router_status`, `router_reason`, `emitted_alpha`, `selected` |
| decisión | `mode`, `reason`, `classification`, `no_trade_kind` |
| economía | `proposal` completo (gross/cost/net, desglose de coste, `edge_evidence`) o `null` |
| revisión multi-agente | `agent_messages[]` (`review_type`, `statement`, `evidence`, `counter_evidence`, `confidence`) |
| verificación | `verification` (verdict, checks, failures, versión del verifier) |
| **riesgo** | `risk.verdict`, `risk.state`, `risk_evaluated`, `risk_result`, `risk_rule`, `risk_reason`, `risk_inputs`, `risk.advisory`, `risk.binding` |
| shadow | `shadow` (contrato `ShadowTradeDecision`) o `null` |
| ejecución | `order_created`, `orders_created` |
| linaje | `cost_model_version`, `errors`, `prev_hash`, `trace_hash` |

## 2. Integridad: cadena de hashes

`trace_hash = sha256(canonical_json(trace sin trace_hash))` con claves ordenadas, y
`prev_hash` apunta al registro anterior (génesis = `genesis`). `verify_chain()`
recalcula cada hash y cada enlace y reporta el **primer** corte:

```json
{"ok": true, "records": 12, "broken_at": null, "detail": "hash chain intact"}
```

Consecuencias probadas:

- alterar el texto de una decisión se detecta (`test_store_detects_tampering`);
- reabrir el store **continúa** la cadena, no la reinicia
  (`test_store_resumes_the_chain_after_restart`);
- el hash es insensible al orden de claves pero sensible al contenido
  (`test_trace_hash_is_order_insensitive_but_content_sensitive`).

## 3. Invariantes que el contrato hace imposibles

`DecisionTrace.__post_init__` rechaza en construcción:

| Invariante | Efecto |
| --- | --- |
| `SHADOW_TRADE` + `order_created=True` | excepción |
| `NO_TRADE` + `order_created=True` | excepción |
| `decision_time_ms < market_time_ms` | excepción (look-ahead) |
| `SHADOW_TRADE` sin contrato `shadow` | excepción |
| `no_trade_kind` en un modo distinto de NO_TRADE | excepción |
| `no_trade_kind` fuera del enum `NoTradeKind` | excepción |
| `NO_TRADE_DATA` con propuesta | excepción (un problema de datos no puede llevar hipótesis de trade) |

Esto es lo que hace que un trace sea **evidencia** y no un log: no se puede escribir
uno que afirme algo imposible.

## 4. Qué NO está en el trace

- Nada de red, credenciales ni órdenes reales: el runtime no tiene ese camino
  (`--provider ccxt` es sólo lectura pública).
- Ningún número inventado: si el horizonte no ha cerrado, no hay `outcome`
  (`docs/OUTCOME_VALIDATION.md`) y el replay se marca `PARTIAL`.
- Ninguna afirmación de rentabilidad: el trace guarda la medida y su procedencia
  (`edge_evidence.evidence_class = HISTORICAL_ESTIMATE`), no una promesa.

## 5. Tests que lo sostienen

```
tests/unit/autonomous/test_trace_replay_outcomes.py   (cadena, tampering, replay)
tests/unit/autonomous/test_outcome_contract.py        (contrato de outcome)
tests/unit/autonomous/test_risk_observability.py      (campos de riesgo en el trace)
tests/unit/autonomous/test_runtime_integration.py     (trace por decisión)
```

## 6. Evidencia del run real 004

`reports/autonomous-paper/autonomous-paper-real-004/traces.jsonl` — commit `ddaf14d`,
`ccxt:binance`, BTC/ETH/SOL, 5m, 4 ciclos.

| Magnitud | Valor |
| --- | ---: |
| registros | 12 |
| `traces_persisted` | 12 (una por evaluacion activo-ciclo) |
| cadena de hashes | `{"ok": true, "records": 12, "broken_at": null, "detail": "hash chain intact"}` |
| `order_created` | `false` en los 12 |
| `orders_created` | 0 en los 12 |
| `cost_model_version` | `COST_MODEL_V3` en los 12 |
| `errors` | `[]` |
| decisiones con `proposal` (hipotesis medible) | 12 / 12 |
| `no_trade_kind` | `NO_TRADE_STRATEGIC` en los 12 |

Contenido real de un registro (recortado a las claves que importan):

```text
run_id/decision_id: 150e1641fa4647d4 / 150e1641fa4647d4-BTC
asset/symbol:       BTC / BTC/USDT   sequence: 1
market_time_ms:     1790588109904    decision_time_ms: 1790588109904
regime:             LOW_VOLATILITY
mode/reason:        NO_TRADE / gross_edge_not_positive:-4.5600bps
classification:     NO_GROSS_EDGE    no_trade_kind: NO_TRADE_STRATEGIC
candidatos:         mean_reversion@5m, breakout@5m, trend@5m, momentum@5m,
                    ema_crossover@5m (SELECTED, emitted_alpha=true), volatility@5m
propuesta:          gross -4.56 bps / cost 22.7918 bps / net -27.3518 bps
procedencia:        docs/STRATEGY_DISCOVERY_V3_RESULTS.json -
                    HISTORICAL_ESTIMATE - W1-W7 2026-03-01..2026-09-24 - 5m - 1725 trades
verification:       PASS
risk:               APPROVED (advisory, all_limits_pass)
order_created:      false
```

Los 12 registros describen el mismo patron estructural: solo `ema_crossover@5m`
emitio alpha en 11 de 12 evaluaciones (en la tercera, SOL, emitio `momentum@5m`), y
el prior de egde bruto de ese emisor es negativo, de modo que las reglas de decision
dictan NO_TRADE. El trace hace visible *por que* familia por familia
(`router_status`, `emitted_alpha`).

### Reproduccion del patron (experimento offline, datos publicos de solo lectura)

`OBSERVATION`: solo `ema_crossover@5m` emitio alpha en el run 004 (en el run 003
tambien emitieron `mean_reversion@5m` y `momentum@5m`).

`REPRODUCTION`: se volvieron a leer los ultimos tramos de 5m de BTC/USDT desde el
endpoint publico y se ejecutaron las seis familias en los **mismos** instantes de
decision del run, comparando la rebanada por APERTURA (comportamiento anterior) con la
rebanada por CIERRE (esta fase):

```text
cycle 1 decision_ts=1790588109904 bars_open=200 bars_close=199
    ema_crossover   open_emits=1 close_emits=1
cycle 2 ... ema_crossover   open_emits=1 close_emits=1
cycle 3 ... ema_crossover   open_emits=1 close_emits=1
cycle 4 ... ema_crossover   open_emits=1 close_emits=1
```

`ROOT CAUSE`: ninguna de las otras cinco familias emite senal en esta ventana de
mercado, ni con la rebanada antigua ni con la nueva. La ausencia de SHADOW en el run
004 **no** es un efecto de la correccion PIT: es que ningun candidato con egde bruto
positivo emitio alpha. `SHADOW_TRADE` exige `gross > 0`, y el unico emisor tiene prior
negativo.

`FIX`: ninguno — no hay defecto. Se documenta como propiedad de la ventana de
mercado, no como fallo del runtime. El camino SHADOW sigue ejercitado en el fixture
determinista y en el run real 003 (5 decisiones SHADOW).
