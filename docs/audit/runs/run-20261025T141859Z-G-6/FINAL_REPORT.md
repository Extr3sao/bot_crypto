# G-6 — Final report

**Estado:** CLOSED  
**Veredicto independiente:** `G6_VERIFIED`  
**Checks:** 17/17  
**`FALSE_SUCCESS`:** 0  
**Implementación:** `66e96e1685226508e4c03a1ea2771aecf878f5b5`  
**Evidencia:** `docs/audit/runs/run-20261025T141859Z-G-6`  
**Alcance:** `PAPER_ONLY` · `LIVE_NO_GO` · `PRODUCTION_READY=false`

## 1. Qué se ha demostrado

El runtime PAPER puede ser terminado de forma abrupta y externa dentro de un
ciclo, y un proceso nuevo puede recuperar el libro desde el fichero durable sin
duplicar órdenes, intents ni posiciones.

Los cuatro límites críticos se han ejercitado con `taskkill /F /T` sobre un
worker real:

1. antes de persistir el intent;
2. después del intent y antes de llamar al broker;
3. después de registrar el fill y antes de completar la contabilidad;
4. después del commit durable y antes de confirmar el ciclo.

Resultado: 4/4 terminaciones forzadas, 0 órdenes duplicadas, 0 posiciones
duplicadas, 1 intent PREPARED bloqueado sin reenvío, 1 fill FILLED materializado
exactamente una vez y 1 posición ACCOUNTED restaurada.

## 2. Criterios de aceptación

| ID | Criterio | Resultado | Evidencia |
|---|---|---|---|
| ACC-G6-01 | Cuatro crashes reales con PID, marker y kill forzado | PASS | `FOUR_REAL_FORCED_TERMINATIONS` |
| ACC-G6-02 | Crash antes del intent: nada durable | PASS | `BEFORE_INTENT_NOTHING_DURABLE` |
| ACC-G6-03 | Intent PREPARED bloqueado, sin reenvío | PASS | `PREPARED_INTENT_BLOCKED_NOT_RESENT` |
| ACC-G6-04 | Fill FILLED materializado una vez | PASS | `FILLED_ORDER_MATERIALIZED_ONCE` |
| ACC-G6-05 | Libro ACCOUNTED restaurado sin orden nueva | PASS | `ACCOUNTED_BOOK_RESTORED_WITHOUT_NEW_ORDER` |
| ACC-G6-06 | Dos reinicios idempotentes | PASS | `TWO_RESTARTS_IDEMPOTENT` |
| ACC-G6-07 | Estado inconsistente/corrupto -> FATAL | PASS | `INCONSISTENT_STATE_FAILS_CLOSED`, `CORRUPT_STATE_FAILS_CLOSED` |
| ACC-G6-08 | Kill switch bloquea el broker durante la recuperación | PASS | `KILL_SWITCH_DURING_RECOVERY_BLOCKS_BROKER` |
| ACC-G6-09 | Posición recuperada se cierra exactamente una vez | PASS | `RECOVERED_POSITION_CLOSES_EXACTLY_ONCE` |
| ACC-G6-10 | Cinco identidades contables | PASS | `FIVE_ACCOUNTING_IDENTITIES` |
| ACC-G6-11 | Sin falso éxito; hot_stop intacto | PASS | `NO_ORDER_CLAIMED_WITHOUT_BROKER_CALL`, `HOT_STOP_UNCHANGED` |
| ACC-G6-12 | Verificador limpio y replay determinista | PASS | `DETERMINISTIC_REPLAY` |

## 3. Números

| Métrica | Valor |
|---|---:|
| Escenarios de crash | 9 |
| Terminaciones forzadas | 4 |
| Órdenes duplicadas | 0 |
| Posiciones duplicadas | 0 |
| Intents reenviados | 0 |
| Idents contables verdaderas | 5/5 |
| Checks del verificador | 17/17 |
| Falsos éxitos | 0 |
| Tests G-6 (paper recovery) | 16 passed |
| Foco paper/E2E/app/cert | 521 passed |
| G-5 + live gate/hot stop | 79 passed |
| Regresión amplia | 840 passed, 2 failed preexistentes |

## 4. Cambios

- `src/trading_bot/paper/durable_broker.py`: persiste `PREPARED`, `FILLED` y
  `ACCOUNTED` en el mismo store atómico.
- `src/trading_bot/paper/crash_injection.py`: puntos de parada deterministas,
  inertes en producción salvo variables de entorno del arnés.
- `src/trading_bot/paper/paper_state_store.py`: campo `orders` aditivo; los
  documentos antiguos cargan sin órdenes.
- `src/trading_bot/paper/paper_runtime_state.py`: snapshot con ledger de
  órdenes y overrides de intents.
- `src/trading_bot/paper/reconciliation_v4.py`: materializa `FILLED`, valida
  `ACCOUNTED`/`CLOSED`, bloquea `PREPARED`/`FAILED`, sincroniza el libro de
  riesgo y persiste la decisión de recuperación.
- `scripts/start_paper_trading.py`: usa `DurablePaperBroker` y adopta el ledger
  reconciliado.
- `scripts/audit/g6_crash_worker.py`, `g6_crash_e2e.py`, `verify_g6.py`:
  arnés, matriz y verificador.
- Tests: 3 nuevos casos en `tests/unit/paper/test_paper_recovery.py`.

## 5. Lo que no se ha demostrado

- Edge, rentabilidad o calidad de datos: la serie es sintética y el ledger es
  un fixture controlado.
- Fallo físico de disco o failover entre máquinas.
- Unificación de los dos motores de decisión.
- Conversión del launcher autónomo `scripts/autonomous_paper.py` al broker
  durable: conserva su persistencia por sesión y queda fuera de esta medición.
- Que los fallos ajenos de `test_futures_independent_verifier.py` y
  `test_vision_panel.py` estén resueltos: siguen en la baseline.

## 6. Estado de G-5

El commit de código de G-5 es `05b361f7`. El commit definitivo de su evidencia
es `12267039` (sustituye al `180e02b3` enmendado; el código no cambió). El
verificador de G-6 comprueba su presencia y el manifiesto de 33 entradas.

## 7. Siguiente objetivo

Activar estrategias elegibles en el runtime PAPER con datos de mercado reales y
trazables, manteniendo `PAPER_ONLY`, `LIVE_NO_GO` y `PRODUCTION_READY=false`.
