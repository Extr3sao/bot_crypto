# RISK_SHADOW_VALIDATION — riesgo observable sin ejecutar nada

> Fase: RISK-IN-SHADOW. Código: `src/trading_bot/autonomous/runtime.py`
> (`_risk_review`), `contracts.py` (`RiskReview`, `RiskState`),
> `decision.py` (guarda advisory). Autoridad de riesgo reutilizada sin cambios:
> `src/trading_bot/risk/manager.py`.

## 1. El defecto que cierra esta fase

En el run real 003 (`reports/autonomous-paper/autonomous-paper-real-003/`) se
produjeron **5 decisiones SHADOW** y **7 NO_TRADE**, y en todas ellas el trace decía
`Risk: NOT_APPLICABLE`. El motor determinista de riesgo **no se había ejecutado
nunca**: sólo se consultaba cuando la intención podía generar una orden, y como
`PAPER_CANDIDATES = 0`, esa intención no existía.

Consecuencia: el riesgo era inobservable. No se podía afirmar ni negar que el sistema
hubiera respetado sus límites, porque no había veredicto que leer.

## 2. Diseño implementado

**Una sola autoridad.** No existe un `ShadowRiskManager`. El runtime tiene un único
`self._risk` (el `RiskManager` canónico que también usa el camino PAPER) y
`_risk_review` llama siempre a `self._risk.check_signal(signal)` cuando la decisión
lleva propuesta. Lo que cambia con el modo es la **vinculación** del veredicto:

| Modo de la intención | `binding` | Efecto del veredicto |
| --- | --- | --- |
| `TRADE_PAPER` | `true` | `PASS`/`ADJUST` autoriza; `VETO` bloquea |
| `SHADOW_TRADE` | `false` (advisory) | informativo: no autoriza ni bloquea |
| `NO_TRADE` con propuesta | `false` (advisory) | informativo: se registra aunque no haya trade |
| `NO_TRADE` sin propuesta | — | `NOT_APPLICABLE`, `evaluated=false` |

Un SHADOW con VETO **sigue siendo SHADOW**: no hay orden que vetar. Lo valioso es que
el trace dice *qué habría dicho* el motor.

## 3. Observabilidad obligatoria

Cada fila del run y cada trace llevan:

```text
risk_evaluated   bool   ¿se ejecutó realmente check_signal?
risk_result      enum   APPROVED | VETOED | NOT_APPLICABLE | NOT_EVALUATED
risk_rule        str    la regla que decidió (kill_switch, position_sizing, ...)
risk_reason      str    motivo del veto / del aprobado
risk_inputs      dict   los inputs exactos entregados al motor
advisory         bool   ¿es informativa?
binding          bool   ¿puede gobernar una orden?
```

`risk_inputs` incluye `decision_id`, `symbol`, `strategy_id`, `side`,
`entry_reference`, `horizon_minutes`, `requested_mode`, `advisory`,
`kill_switch_enabled`, `equity`, `open_positions`, `trades_today`,
`consecutive_losses` y — cuando el motor aprobó — `notional_usdt`, `quantity`,
`stop_loss_pct`, `take_profit_pct`. Un veredicto es reproducible desde el trace.

## 4. `NOT_EVALUATED` nunca es `PASS`

`RiskReview.state` se deriva así:

```text
verdict == VETO                     → VETOED
verdict in {PASS, ADJUST} and !evaluated → NOT_EVALUATED   ← la salvaguarda
verdict in {PASS, ADJUST} and evaluated  → APPROVED
verdict == NOT_APPLICABLE and !evaluated → NOT_APPLICABLE
```

Y `__post_init__` exige: una revisión evaluada nombra su regla, y `evaluated=True`
junto a `NOT_APPLICABLE` es un error de construcción. Un veredicto que nadie produjo
**no puede** leerse como aprobación.

## 5. Por qué el advisory no puede saltarse la puerta

La guarda está en el motor de decisión, no en el runtime:

```python
DecisionEngine._reject_advisory_risk_on_an_order(request)
```

Si un paquete **puede** producir una orden (candidato admitido para papel, gross > 0,
net > 0) y trae una revisión `advisory=True`, `decide()` lanza
`ValueError("advisory risk review cannot accompany an order-authorising packet")`.
Marcar la revisión como “informativa” no desactiva el riesgo: simplemente no compila
una decisión de ese tipo. Además `decide()` sólo bloquea con `VETO` **binding**
(`not request.risk.advisory`).

Defensa en profundidad adicional: el verifier exige `risk_reviewed` =
`risk_review.evaluated` para TRADE_PAPER, así que un TRADE_PAPER sin revisión real
falla la verificación ⇒ NO_TRADE.

## 6. Pruebas

| Test | Qué demuestra |
| --- | --- |
| `test_a_pass_nobody_produced_is_not_evaluated_never_approved` | un PASS sin ejecución se reporta `NOT_EVALUATED` |
| `test_an_evaluated_review_must_name_the_rule_it_applied` | no hay aprobación anónima |
| `test_a_veto_must_state_its_reason` | no hay veto mudo |
| `test_shadow_decision_is_risk_reviewed_advisory` | SHADOW lleva veredicto real, advisory, sin órdenes |
| `test_advisory_veto_does_not_block_a_shadow_decision` | kill switch ⇒ `VETOED` y SHADOW intacto |
| `test_no_proposal_is_not_applicable_and_not_evaluated` | sin propuesta: `NOT_APPLICABLE`, no evaluado |
| `test_rejected_candidate_keeps_its_advisory_risk_verdict` | un NO_TRADE_STRATEGIC puede llevar riesgo APPROVED: se ve que el bloqueo era el edge, no el riesgo |
| `test_admitted_and_unadmitted_paths_share_one_risk_engine` | el espía demuestra que se llama al **mismo** `check_signal` |
| `test_advisory_risk_can_never_sit_on_an_order_authorising_packet` | la guarda fail-closed |
| `test_advisory_risk_is_legal_where_no_order_can_follow` | advisory sólo donde no hay orden |
| `test_fixture_cost_gate_pass_reaches_risk_and_becomes_paper` | fixture controlado: cost gate → proposal → riesgo → 1 orden |

## 7. SHADOW ≠ EXECUTION

| Afirmación | Cómo se comprueba |
| --- | --- |
| SHADOW no crea órdenes | broker espía con `calls == 0`; `broker.positions == {}` |
| SHADOW no puede registrarse como ejecutado | `DecisionTrace.__post_init__` rechaza SHADOW con `order_created=True` |
| SHADOW no toca el portfolio | el runtime sólo llama al broker en la rama `TRADE_PAPER` |
| SHADOW no puede autorizar | `DecisionResult.order_authorised is False` en SHADOW |
| la única puerta a la orden es la regla 7 | `_execute_paper` re-afirma la admisión y vuelve a llamar al riesgo |

El fixture determinista (`tests/unit/autonomous/test_cost_gate_risk_fixture.py`) está
**separado** del run de mercado real y así está rotulado en su docstring: no es
evidencia de mercado, es evidencia de cableado.

## 8. Evidencia del run real 004

`reports/autonomous-paper/autonomous-paper-real-004/` — commit `ddaf14d`,
`environment = ccxt:binance`, activos BTC/ETH/SOL, timeframe 5m, 4 ciclos,
12 evaluaciones activo-ciclo, **0 ordenes** y **0 acciones de produccion**.

| Magnitud | Valor |
| --- | ---: |
| revisiones de riesgo | 12 |
| `risk_APPROVED` | 12 |
| `risk_VETOED` | 0 |
| `risk_NOT_APPLICABLE` | 0 |
| `risk_NOT_EVALUATED` | 0 |
| `risk_evaluated = true` | 12 / 12 |
| regla aplicada | `all_limits_pass` (12 / 12) |
| `advisory = true`, `binding = false` | 12 / 12 |
| notional calculado por el motor | 500.00 USDT |

Ejemplo real de un trace (BTC, ciclo 1):

```json
{"verdict": "PASS", "state": "APPROVED", "risk_evaluated": true,
 "risk_result": "APPROVED", "risk_rule": "all_limits_pass",
 "risk_reason": "risk_approved", "advisory": true, "binding": false,
 "source": "RiskManager.check_signal",
 "risk_inputs": {"symbol": "BTC/USDT", "strategy_id": "ema_crossover@5m",
   "side": "sell", "entry_reference": 82721.9, "horizon_minutes": 5.0,
   "requested_mode": "NO_TRADE", "advisory": true,
   "kill_switch_enabled": true, "equity": 10000.0, "open_positions": 0,
   "trades_today": 0, "consecutive_losses": 0, "blocked_by": null,
   "notional_usdt": 500.0, "quantity": 0.006044, "stop_loss_pct": 1.0,
   "take_profit_pct": 0.75}}
```

Lectura honesta de esa fila: el motor determinista **aprobo** un tamano de 500 USDT
para un candidato `ema_crossover@5m` en BTC, con el kill switch armado y 0 posiciones
abiertas, y **no se ejecuto nada**, porque el egde bruto esperado era negativo
(regla 6, `NO_GROSS_EDGE`). Antes de esta fase esa fila habria dicho
`NOT_APPLICABLE` y no se habria podido distinguir "el riesgo lo habria permitido pero
el egde no" de "el riesgo no se miro".

Comparacion: en el run 003 las 12 filas decian `Risk: NOT_APPLICABLE` (riesgo nunca
ejecutado). En el run 004 las 12 filas llevan veredicto real y evaluado.
