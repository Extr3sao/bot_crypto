# G-6 — Recovery report

**Run:** `run-20261025T141859Z-G-6`  
**Implementación:** `66e96e1685226508e4c03a1ea2771aecf878f5b5`  
**Veredicto:** `G6_VERIFIED` (17/17, `FALSE_SUCCESS=0`)  
**Alcance:** `PAPER_ONLY` · `LIVE_NO_GO` · `PRODUCTION_READY=false`

## 1. Contrato de durabilidad

El ciclo canónico no tenía una frontera durable entre la aprobación de riesgo y
el cierre de la sesión. G-6 introduce cuatro puntos, todos con la misma
escritura atómica del store existente:

| Punto | Documento durable | Semántica de recuperación |
|---|---|---|
| `before_intent_persist` | ninguno | No hubo intención; el reinicio puede operar desde cero. |
| `after_intent_persist_before_order` | `PREPARED` + cloid | Resultado desconocido; el cloid se bloquea y no se reenvía. |
| `after_order_record_before_accounting` | `FILLED` + fila de posición; contabilidad pre-fill | La posición se materializa una vez y se persiste como `ACCOUNTED`. |
| `after_accounting_commit_before_cycle` | `ACCOUNTED` + libro post-fill | Se restaura el libro; el intent ya está registrado y no se repite. |

La diferencia entre `FILLED` y `ACCOUNTED` es deliberada: `FILLED` prueba el
fill pero deja la contabilidad en el estado anterior; `ACCOUNTED` prueba que el
libro y el fill ya están juntos. Sin esa separación no se puede distinguir una
pérdida de fill de una pérdida de contabilidad.

## 2. Máquina de estados de una orden

```text
                 prepare
   (none) ─────────────────▶ PREPARED
                              │      │
                    fill ok   │      │ exception / uncertain
                              ▼      ▼
                           FILLED   FAILED
                              │
                    accounting save
                              ▼
                          ACCOUNTED
                              │
                     close persistido
                              ▼
                           CLOSED
```

- `PREPARED` y `FAILED` son estados **inciertos** y se convierten en
  `BLOCKED_UNKNOWN` en la recuperación. El cloid permanece en
  `sent_intents`.
- `NO_FILL` sólo se escribe cuando el broker devolvió `None` de forma
  confirmada; no crea posición ni conserva el intent.
- `FILLED` se materializa y se convierte en `ACCOUNTED`.
- `ACCOUNTED` se valida contra el libro. Si la posición ya no está, sólo se
  acepta si un `ClosedTrade` persistido nombra el mismo `position_id` o
  `entry_order_id`; entonces pasa a `CLOSED`. Cualquier otra ausencia es
  `FATAL`.
- `CLOSED` no se reejecuta.

## 3. Recuperación

`StartupReconcilerV4.reconcile()` conserva su orden:

1. `_restore_broker`: equity, fills, posiciones y trades; valida
   `equity == initial_equity + Σ pnl`.
2. `_restore_risk`: contadores y exposición restaurados antes de la primera
   decisión.
3. `_restore_intents`: cada cloid persiste en el guard.
4. `_restore_orders`: materializa `FILLED`, valida `ACCOUNTED`/`CLOSED` y
   bloquea `PREPARED`/`FAILED`.
5. `_sync_risk_book`: el riesgo ve las posiciones materializadas.
6. Persiste el resultado si cambió algún estado (`recovery_persisted`).

Un fallo en cualquiera de los pasos devuelve `FATAL`, no un estado parcial. Una
segunda muerte durante la persistencia deja el documento anterior intacto
(escritura atómica) y la siguiente recuperación repite la misma decisión.

## 4. Resultados de la matriz

### 4.1 Antes del intent

No existe fichero durable. El reinicio informa `CONSISTENT` y abre una posición
nueva con una orden. No hay duplicado porque no había una orden previa.

### 4.2 Intención sin resultado

Estado: `PREPARED`, 1 intent, 0 posiciones, 699 B. Reinicio:

- `RECOVERED`
- `blocked_intents = ["PAPER-6adfdf69995704ff54c0ec0fbcb87bb7"]`
- `materialized_orders = 0`
- `duplicate_intents = 1`, `orders_created = 0`, `execute_signal = 0`
- estado final `BLOCKED_UNKNOWN`

La decisión es conservadora por diseño: no se puede demostrar que el broker no
actuó. Se prefiere bloquear una oportunidad a duplicar una operación.

### 4.3 Fill sin contabilidad

Estado: `FILLED`, 1 intent, 0 posiciones en el snapshot, 0 fills contados,
1.115 B. Reinicio:

- `RECOVERED`, `materialized_orders = 1`, `recovery_persisted = true`
- 1 posición, `fills_opened = 1`
- `orders_created = 0`, `duplicate_intents = 1`
- estado final `ACCOUNTED`, 1.645 B

La fila de posición es exacta (incluye `position_id`, `entry_order_id`,
comisiones y precios); la materialización usa el broker real, no una copia
paralela.

### 4.4 Commit durable sin confirmación de ciclo

Estado: `ACCOUNTED`, 1 posición, 1.542 B. Reinicio:

- `RECOVERED`, `restored_open_positions = 1`, `restored_equity = 10000.0`
- `orders_created = 0`, `duplicate_intents = 1`
- 1 posición intacta

El ciclo superior no se confirma, pero el efecto económico sí. La ausencia de
confirmación no autoriza una segunda ejecución.

### 4.5 Dos reinicios

Dos procesos consecutivos sobre el mismo fichero: `RECOVERED` y `RECOVERED`,
1 posición, 1 intent, 0 órdenes nuevas en ambos. El estado permanece en 1.677 B
con `ACCOUNTED`. No hay crecimiento por duplicación.

### 4.6 Estado inconsistente y corrupción

- `ACCOUNTED` sin `open_positions` ni cierre: `FATAL`, exit 2, sin ciclo.
- JSON truncado: `FATAL`, exit 2, `.corrupt` conservado, sin libro vacío.

## 5. Contabilidad

En los resultados con contabilidad, `PaperBroker.accounting_snapshot` devuelve
las cinco identidades verdaderas:

1. `cash == initial_equity + Σ realized_pnl`
2. `ledger_equity == cash`
3. `equity_mark_to_market == cash + unrealized_gross - accrued_entry_commissions`
4. `closed_trade.pnl == gross_pnl - entry_commission - exit_commission`
5. `closed_trade.pnl == reference_gross_pnl - execution_cost - entry_commission - exit_commission`

En el cierre recuperado:

- PnL neto: `+49,3900164978`
- Equity: `10.049,3900164978`
- Identidad de ledger: `10000 + 49,3900164978 == 10049,3900164978`
- Posición cerrada: 1; posición abierta: 0

## 6. Kill switch

Con un marker `KILL_SWITCH` presente durante el reinicio:

- `reconciliation = RECOVERED`
- `risk_accepted = 1`
- `hot_stop_blocked = 1`
- `execute_signal = 0`
- `orders_created = 0`
- rechazo observable: `kill_switch_active:marker:G-6 recovery stop`

El libro restaurado (1 cierre) no se modifica y no se crea ninguna orden nueva.

## 7. Qué no demuestra

- No demuestra edge, rentabilidad ni calidad de datos: la serie es sintética.
- No demuestra recuperación ante corrupción física del disco; sólo ante un
  fichero truncado o un libro inconsistente.
- No demuestra un failover entre máquinas: el reinicio usa el mismo disco.
- No unifica `paper_cycle` y `autonomous.decision`.
- La verificación es de procedimiento separado, no de segunda persona.
