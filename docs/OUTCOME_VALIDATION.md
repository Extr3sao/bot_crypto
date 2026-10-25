# OUTCOME_VALIDATION — el contrato de resultado y su disponibilidad real

> Fase: BAR-CLOSE AVAILABILITY. Código: `src/trading_bot/autonomous/pit.py`,
> `outcomes.py`, `contracts.py` (`OutcomeRecord`). Artefacto real:
> `reports/autonomous-paper/autonomous-paper-real-004/outcomes.jsonl`.

## 1. Contrato registrado

Por cada decisión medible se persiste un `OutcomeRecord`
(`schema_version = outcome-record-v1`):

```text
decision_id · outcome_key · run_id · asset · symbol · strategy_id · mode · direction
decision_time_ms · market_time_ms · reference_price_time_ms · future_price_time_ms
horizon_minutes · entry_reference · outcome_price
gross_return_bps · estimated_cost_bps · net_hypothetical_bps
mfe_bps · mae_bps · direction_correct · data_complete · bars_observed · status
```

Alias explícitos: `future_price_time_ms == outcome_time_ms`
(`OutcomeRecord.future_price_time_ms`).

## 2. Regla temporal (dura, validada en el contrato)

```text
reference_price_time_ms <= decision_time_ms < outcome_time_ms
```

- `reference_price_time_ms`: **cierre** de la última barra que la decisión podía leer
  legítimamente. Es el instante en que el `entry_reference` fue observable.
- `outcome_time_ms` (`future_price_time_ms`): **cierre** de la primera barra cuyo
  cierre alcanza el final del horizonte. Es el instante en que el precio futuro fue
  observable.
- `market_time_ms <= decision_time_ms` también se valida.

`OutcomeRecord.__post_init__` lanza `ValueError` si cualquiera se viola. Un outcome no
puede, ni por construcción, contener información que la decisión pudiera ver.

## 3. Disponibilidad = cierre de la barra, no apertura

`pit.py` es la única declaración de la regla:

```text
infer_bar_interval_ms(bars)                 espaciado inferido de los datos (nunca declarado)
availability_ms(bar, interval)              bar.timestamp + interval  (su CIERRE)
closed_bar_slice(bars, decision_time)       barras cuyo CIERRE <= decision_time
```

Se aplica en tres sitios:

1. **porción PIT consumida** por la decisión (`runtime.run_cycle`): una barra en
   formación **no** entra en el contexto ni en la propuesta;
2. **`pit_slice_exact`** del verifier: re-deriva la misma porción desde el histórico
   crudo;
3. **evaluación del outcome**: el instante de resultado es el cierre.

Defecto corregido (DEF-AUTO-7): el evaluador elegía la primera barra con
`timestamp > decision_time` y fechaba el outcome con **su apertura**. Para un horizonte
de 5m eso significaba usar el cierre de la barra abierta en `T+5m`, es decir el precio
de `T+10m`, y rotularlo como el instante `T+5m`. Ahora:

- la barra elegida es la primera cuyo **cierre** alcanza `decision_time + horizonte`
  (la barra que **contiene** el final del horizonte);
- `outcome_time_ms` es ese cierre;
- `reference_price_time_ms` se calcula con la misma regla hacia atrás.

## 4. PENDING → RESOLVED, idempotente

- Si el horizonte **no** ha cerrado: `status = PENDING_OUTCOME`, `record = None`,
  nunca un número inventado, nunca `SUCCESS`/`FAIL`.
- Si ha cerrado: `status = RESOLVED` con el registro completo.

Idempotencia en dos capas:

1. `OutcomeKey = "<decision_id>@<horizonte>"` (p. ej. `150e1641fa4647d4-BTC@5m`).
   `DecisionTraceStore.append_outcome` detecta la clave ya persistida y **devuelve el
   registro almacenado sin escribir**; `outcome_keys()` expone el conjunto.
2. `resolve_pending(..., already_resolved=...)` salta lo ya resuelto, y el runtime
   mantiene además un `seen_keys` por ciclo, de modo que reprocesar el mismo ciclo no
   puede duplicar ni contar dos veces.

`StrategyPerformanceStore.update_from_outcome` es idempotente por `decision_id`
(`seen_decisions`): re-alimentar el mismo outcome no infla la muestra.

## 5. Qué mide un outcome

| Campo | Definición |
| --- | --- |
| `gross_return_bps` | movimiento de precio ajustado por dirección, en bps |
| `estimated_cost_bps` | el **mismo** coste que llevaba la propuesta (COST_MODEL_V3) |
| `net_hypothetical_bps` | `gross_return_bps − estimated_cost_bps` |
| `mfe_bps` | mejor excursión a favor dentro de la ventana |
| `mae_bps` | peor excursión en contra |
| `direction_correct` | ¿acertó el signo? |

Sólo se usan barras que **cierran** después del instante de decisión.

## 6. Pruebas

| Test | Qué demuestra |
| --- | --- |
| `test_bar_availability_is_its_close` | la disponibilidad es el cierre; sin intervalo, fallback conservador declarado |
| `test_the_forming_bar_is_not_usable_at_the_decision_time` | la barra en formación queda fuera |
| `test_outcome_contract_temporal_ordering` | `reference <= decision < future` en un caso real |
| `test_reference_price_time_is_a_close_never_an_open` | decisión un ms antes del cierre: sólo entra la barra ya cerrada |
| `test_outcome_instant_is_the_close_of_the_bar_not_its_open` | el instante es el cierre, no la apertura |
| `test_outcome_record_rejects_a_reference_time_in_the_future` | el contrato rechaza look-ahead |
| `test_outcome_is_pending_until_the_horizon_elapses` | PENDING honesto |
| `test_no_proposal_means_not_applicable` | sin hipótesis no hay outcome falso |
| `test_no_trade_hypothesis_is_evaluated_as_calibration` | un NO_TRADE con propuesta se evalúa, bajo su propio modo |
| `test_outcome_key_is_the_stable_decision_plus_horizon_identity` | la clave es estable y derivada |
| `test_appending_the_same_outcome_twice_creates_one_record` | idempotencia en el store |
| `test_pending_then_resolved_is_idempotent` | PENDING → RESOLVED exactamente una vez |
| `test_future_bars_are_never_used_for_a_past_decision` | sin barra cerrada posterior: PENDING, no invención |

## 7. NO_TRADE también es una predicción

Un `NO_TRADE_STRATEGIC` con propuesta se evalúa: mide si **evitar** la operación fue
correcto. Sus muestras se guardan bajo `mode = NO_TRADE`
(`no_trade_sample_size`) y no pueden reordenar la selección por sí solas
(`selection_priority == 0.0` con ese único tipo de muestra).

## 8. Evidencia del run real 004

`reports/autonomous-paper/autonomous-paper-real-004/outcomes.jsonl` — commit `ddaf14d`.
12 evaluaciones activo-ciclo, 12 hipotesis (todas con propuesta), 6 resultados
resueltos y 6 pendientes al cerrar el run (los dos ultimos ciclos no tenian horizonte
cerrado; no se invento ninguno).

| decision_id | estrategia | modo | ref_price_time | decision_time | future_price_time | gross bps | cost bps | net bps | acierto |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `150e1641fa4647d4-BTC` | ema_crossover@5m | NO_TRADE | 1790588100000 | 1790588109904 | 1790588700000 | +13.2855 | 22.7918 | -9.5063 | si |
| `150e1641fa4647d4-ETH` | ema_crossover@5m | NO_TRADE | 1790588100000 | 1790588109904 | 1790588700000 | +16.0800 | 22.8284 | -6.7484 | si |
| `150e1641fa4647d4-SOL` | ema_crossover@5m | NO_TRADE | 1790588100000 | 1790588109904 | 1790588700000 | +20.3476 | 23.6384 | -3.2907 | si |
| `6262cefd3cd9482c-BTC` | ema_crossover@5m | NO_TRADE | 1790588400000 | 1790588456755 | 1790589000000 | -13.6416 | 22.7918 | -36.4334 | no |
| `6262cefd3cd9482c-ETH` | ema_crossover@5m | NO_TRADE | 1790588400000 | 1790588456755 | 1790589000000 | -5.0745 | 22.8284 | -27.9029 | no |
| `6262cefd3cd9482c-SOL` | ema_crossover@5m | NO_TRADE | 1790588400000 | 1790588456755 | 1790589000000 | -0.0000 | 23.6391 | -23.6391 | no |

- **Contrato temporal verificado en los 6**: `reference_price_time (...100000 /
  ...400000) <= decision_time (...109904 / ...456755) < future_price_time (...700000 /
  ...000000)`.
- `outcome_key` unico en los 6 (`<decision_id>@5m`); ningun duplicado.
- El intervalo de barra se infirio del historico: `reference = decision - 9.9s` y
  `future = decision + 5m - 9.9s`, es decir exactamente la primera barra cuyo cierre
  alcanza el horizonte.
- `performance_updates = 6` y 3 celdas de rendimiento, todas con `sample_size = 2`,
  `no_trade_sample_size = 2`, `shadow/paper = 0`, escala `INSUFFICIENT_SAMPLE`.

### Que dicen (y que NO dicen) esos numeros

Los tres resultados del ciclo 1 tienen **movimiento bruto positivo** (+13.3, +16.1,
+20.3 bps) que **no** cubre el coste (~22.8-23.6 bps): la decision de no operar fue
correcta **despues de costes** y habria sido una perdida neta (-9.5, -6.7, -3.3 bps).
Los tres del ciclo 2 tuvieron movimiento negativo y evitarlo fue correcto en
cualquier caso.

Con `n = 2` por celda esto es **observacion**, no validacion: no se declara
rentabilidad, ni edge, ni causalidad. Lo que si demuestra es que el contrato de
outcome, la idempotencia y la separacion PENDING/RESOLVED funcionan sobre datos
reales, que es el objetivo de la fase.
