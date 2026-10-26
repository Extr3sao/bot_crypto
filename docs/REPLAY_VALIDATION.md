# REPLAY_VALIDATION — reconstrucción desde el registro, sin volver al mercado

> Fase: RISK-IN-SHADOW + BAR-CLOSE AVAILABILITY. Código:
> `src/trading_bot/autonomous/trace.py` (`DecisionTraceStore.replay`),
> `runtime.py` (`_replay_all`).

## 1. Qué reconstruye el replay

`replay(decision_id)` lee **sólo** el registro persistido. No consulta mercado, no
consulta la hora, no consulta el ledger en vivo. Devuelve:

```text
market_context          estado de mercado observado
asset_context           contexto validado del activo
regime                  régimen clasificado
strategies_considered   candidatos con su router_status / emitted_alpha / selected
candidate               estrategia seleccionada
timeframe               timeframe de la evidencia
proposal                propuesta completa (economía + procedencia del edge)
cost_estimate           desglose de coste COST_MODEL_V3 aplicado
agent_messages          revisiones multi-agente
evidence/counter_evidence
decision                {mode, reason, classification, no_trade_kind}
verification            veredicto del verifier y sus checks
risk                    revisión de riesgo completa (con risk_inputs)
shadow                  contrato shadow (si aplica)
execution_mode          TRADE_PAPER | SHADOW_TRADE | NO_TRADE
order_created
cost_model_version
outcome                 OutcomeRecord o null
```

Es decir: **contexto de mercado, candidato, estimación de coste, decisión, revisión de
riesgo, resultado shadow y outcome**.

## 2. Estados honestos

```text
FULL           todos los invariantes pasan Y existe el outcome resuelto
PARTIAL        la decisión se reconstruye entera, pero el horizonte aún no cerró
NOT_AVAILABLE  algún invariante falla (hash, PIT, round-trip, shadow) o falta el registro
```

`ReplayResult.status` se deriva, no se declara: `FULL` exige que el outcome exista.
Un replay parcial **no puede** presentarse como completo — el run report publica el
recuento por estado (`replay.statuses`).

## 3. Invariantes que re-comprueba

| Check | Qué verifica |
| --- | --- |
| `pit_ordering` | `decision_time_ms >= market_time_ms` |
| `trace_hash` | el cuerpo del registro sigue produciendo el hash almacenado |
| `shadow_purity` | `SHADOW_TRADE` nunca con `order_created` |
| `proposal_round_trip` | la propuesta reconstruida es idéntica a la persistida |
| `outcome_after_decision` | el outcome (si existe) es estrictamente posterior |

Un registro manipulado produce `NOT_AVAILABLE` con `trace_hash` en `failed_checks`
(`test_replay_status_is_not_available_when_an_invariant_fails`).

## 4. Evidencia a nivel de run

Al final de **todo** run acotado, `AutonomousRuntime._replay_all()` reproduce cada
traza persistida y agrega:

```json
{"attempted": N, "ok": N, "failed": 0,
 "statuses": {"FULL": a, "PARTIAL": b, "NOT_AVAILABLE": 0},
 "failures": [], "market_data_accessed": false}
```

Así REPLAY queda evidenciado sobre datos reales y no sólo en tests, y
`market_data_accessed=false` es la prueba de que la reconstrucción no volvió al mercado.

## 5. Pruebas

| Test | Qué demuestra |
| --- | --- |
| `test_replay_reconstructs_without_market_access` | reconstrucción desde el registro |
| `test_replay_reports_missing_decision` | decisión ausente ⇒ `KeyError` explícito |
| `test_replay_status_is_partial_without_an_outcome` | `PARTIAL` y reconstrucción completa (candidato, coste, riesgo, shadow) |
| `test_replay_status_is_full_once_the_outcome_exists` | `FULL` sólo con outcome |
| `test_replay_status_is_not_available_when_an_invariant_fails` | `NOT_AVAILABLE` con el check fallido nombrado |
| `test_pending_outcomes_are_counted_once_per_decision` | a nivel de run: `attempted == trazas`, `statuses` suma lo mismo, `FULL == resolved` |

## 6. Evidencia del run real 004

Al terminar el run, `_replay_all()` reprodujo las 12 trazas persistidas:

```json
{"attempted": 12, "ok": 12, "failed": 0,
 "statuses": {"FULL": 6, "PARTIAL": 6}, "market_data_accessed": false}
```

- `attempted == traces_persisted` (12): no se salto ninguna decision.
- `FULL = 6` = exactamente `outcomes_resolved` (6): solo se declara completo lo que
  tiene outcome.
- `PARTIAL = 6` = exactamente `outcomes_pending` (6): las dos ultimas rondas no
  tenian horizonte cerrado, y se reportan como parciales, no como completas.
- `NOT_AVAILABLE = 0`: ningun invariante fallo (hash, PIT, round-trip, shadow).
- `market_data_accessed = false`: la reconstruccion no volvio al mercado.
