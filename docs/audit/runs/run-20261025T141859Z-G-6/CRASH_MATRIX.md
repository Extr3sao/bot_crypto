# G-6 — Crash matrix

**Run:** `docs/audit/runs/run-20261025T141859Z-G-6`  
**Implementación:** `66e96e1685226508e4c03a1ea2771aecf878f5b5`  
**Plataforma:** Windows 10.0.26200 (Python 3.11)  
**Modo:** `PAPER_ONLY_SYNTHETIC_FIXTURE`  
**Ledger:** `docs/audit/fixtures/g6_paper_ledger.json` (`CONTROLLED_TEST_FIXTURE`)

Cada crash lanza un proceso worker real, espera su marker fsync y mata el árbol
del proceso con `taskkill /F /T` (Windows). El reinicio es un proceso nuevo que
abre el mismo fichero durable. No se usa una excepción para simular la muerte.

## 1. Matriz

| # | Escenario | Punto de crash | Worker / wrapper PID | Estado durable tras el kill | Reinicio | Resultado |
|---|---|---|---|---|---|---|
| 1 | `before_intent` | `before_intent_persist` | 38092 / 42292 | No existe fichero (0 B) | `CONSISTENT` | 1 orden nueva legítima, 1 posición; no había orden previa |
| 2 | `after_intent` | `after_intent_persist_before_order` | 5016 / 42200 | `PREPARED`, 1 intent, 0 posiciones, 699 B | `RECOVERED` | 1 intent `BLOCKED_UNKNOWN`, 0 órdenes, 0 posiciones |
| 3 | `after_order` | `after_order_record_before_accounting` | 40076 / 44496 | `FILLED`, 1 intent, 0 posiciones en el snapshot, 1.115 B | `RECOVERED` | 1 posición materializada, 0 órdenes, estado `ACCOUNTED` |
| 4 | `after_accounting` | `after_accounting_commit_before_cycle` | 32836 / 43640 | `ACCOUNTED`, 1 intent, 1 posición, 1.542 B | `RECOVERED` | 1 posición restaurada, 0 órdenes |
| 5 | `two_restarts` | (desde #4) | — | `ACCOUNTED`, 1 posición, 1.677 B | `RECOVERED` ×2 | 1 posición y 1 intent en ambos; 0 órdenes |
| 6 | `inconsistent` | (tamper #4) | — | `ACCOUNTED` sin `open_positions`, 1.388 B | `FATAL` (exit 2) | Se niega a arrancar; no toca el broker |
| 7 | `corrupt` | (JSON truncado) | — | 35 B ilegibles | `FATAL` (exit 2) | `.corrupt` conservado; no se inventa libro vacío |
| 8 | `recovery_close` | (desde #4, precio +10 %) | — | `ACCOUNTED`, 1 posición, 1.542 B | `RECOVERED` | 0 órdenes; 1 cierre `take_profit`; PnL +49,3900165 |
| 9 | `kill_switch` | (desde #8, marker activo) | — | `ACCOUNTED`, 0 posiciones, 1 cierre, 2.017 B → `CLOSED`, 1.879 B | `RECOVERED` | `hot_stop_blocked=1`, `risk_accepted=1`, 0 órdenes, 0 llamadas al broker |

## 2. Terminaciones forzadas

| Escenario | Kill | Exit kill | Exit worker | Marker |
|---|---|---|---|---|
| `before_intent` | `taskkill /F /T /PID 42292` | 0 | 1 | `before_intent_persist`, pid 38092 |
| `after_intent` | `taskkill /F /T /PID 42200` | 0 | 1 | `after_intent_persist_before_order`, pid 5016 |
| `after_order` | `taskkill /F /T /PID 44496` | 0 | 1 | `after_order_record_before_accounting`, pid 40076 |
| `after_accounting` | `taskkill /F /T /PID 43640` | 0 | 1 | `after_accounting_commit_before_cycle`, pid 32836 |

Los cuatro workers quedaron vivos en el punto exacto (el marker se escribe con
`fsync` antes de dormir) y murieron por una acción externa al proceso. Los
`returncode` no nulos y los logs de `taskkill` están en `evidence.json`.

## 3. Transiciones de estado

### 3.1 `before_intent` — nada durable

```text
market -> context -> router -> signal -> risk approved
                                             |
                                   [KILL before save]
                                             |
estado: no existe
restart: CONSISTENT -> 1 orden nueva (no había intención persistida)
```

No se puede hablar de duplicado: la primera orden nunca llegó a existir. El
reinicio abre exactamente una posición y el estado final tiene 1 posición,
1 intent y 0 cierres.

### 3.2 `after_intent` — intención sin resultado conocido

```text
intent cloid -> save PREPARED -> [KILL before broker]
restart: RECOVERED
  order PREPARED -> BLOCKED_UNKNOWN
  sent_intents = 1
  cycle: duplicate_intents=1, orders_created=0, execute_signal=0
```

El resultado del broker es desconocido. La política correcta es no reenviar:
el `cloid` permanece bloqueado y el rechazo es observable (`duplicate_intent`).

### 3.3 `after_order` — fill confirmado, contabilidad pre-fill

```text
intent -> save PREPARED -> broker fill -> save FILLED + position row
                                             | [KILL before accounting]
estado: open_positions=0, orders=[FILLED], fills_opened=0
restart: RECOVERED, materialized_orders=1
  -> position 1, fills_opened=1, order ACCOUNTED
  -> cycle: orders_created=0, duplicate_intents=1
```

La fila de posición es la prueba durable del fill. El reinicio la materializa
una sola vez; un segundo reinicio ve `ACCOUNTED` y no vuelve a hacerlo.

### 3.4 `after_accounting` — commit durable, ciclo sin confirmar

```text
... -> save ACCOUNTED (position 1, fills_opened=1)
                                             | [KILL before cycle return]
restart: RECOVERED
  restored_open_positions=1, restored_equity=10000.0
  cycle: orders_created=0, duplicate_intents=1
```

La posición confirmada y persistida no se pierde. La falta de confirmación del
ciclo superior no permite una segunda ejecución porque el intent ya está en el
ledger.

### 3.5 Dos reinicios

Ambos reinicios dan `RECOVERED`, 1 posición, 1 intent y 0 órdenes. El estado
queda en 1.677 B y `ACCOUNTED` en los dos casos: no hay crecimiento por
duplicación ni reapertura.

### 3.6 Estado inconsistente y corrupción

- `inconsistent`: se elimina `open_positions` dejando la orden `ACCOUNTED` con
  su fila de posición. `StartupReconcilerV4` detecta que no hay posición ni
  cierre que la respalde y devuelve `FATAL` (exit 2); no se ejecuta el ciclo.
- `corrupt`: JSON truncado. `PaperStateStore` conserva `.corrupt` y falla
  cerrado; no se arranca un libro vacío.

### 3.7 Cierre y kill switch

- `recovery_close`: posición restaurada, mismo lado en el ciclo (0 órdenes) y
  cierre posterior por `take_profit`. PnL neto `+49,3900164978`, equity
  `10.049,3900164978`, cinco identidades verdaderas.
- `kill_switch`: el libro restaurado ya tiene el cierre; un bar nuevo genera un
  intent nuevo, riesgo lo aprueba (`risk_accepted=1`) y el marker lo bloquea
  antes del broker (`hot_stop_blocked=1`, `execute_signal=0`, `orders_created=0`).

## 4. Invariantes comprobadas

- Ninguna ejecución de reinicio crea una orden para un `cloid` ya persistido.
- Ningún `PREPARED`/`FAILED` se reenvía.
- Un `FILLED` se materializa como máximo una vez.
- Una posición `ACCOUNTED` se restaura o se declara `FATAL`.
- Un cierre persistido convierte la orden en `CLOSED` y no se reintenta.
- Las cinco identidades contables son verdaderas en todos los resultados con
  contabilidad.
- Ninguna orden declarada sin una llamada real a `execute_signal`.
- No se crea ningún cliente de exchange ni se usan credenciales.
