# WP-TAP-AI-BOTS-003B — el motor de ejecución paper causal

**RFC:** RFC-TAP-AI-BOTS-003 (bloque B) · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Baseline:** `2921f6d` · **Motor:** `96957a2`
**Estado:** `PASS_WITH_DECLARED_LIMITS` · `FALSE_SUCCESS=0` · `BUILDER != VERIFIER` · `TEST_TARGET == RUNTIME_TARGET`

---

## 1. El defecto que quedaba después del reloj

El bloque A arregló **cuándo** se forma la opinión: el cierre de la vela, no su apertura.
Al hacerlo dejó a la vista —y sin resolver— lo que venía después: el carril exigía pagar
la apertura de una vela que **ya había abierto antes de que el proveedor respondiera**.

La cuenta es corta y no admite interpretación: si la decisión se forma en `close(i)` y ese
instante es exactamente `open(i+1)`, entonces una respuesta que tarda 900 ms llega
*después* de que `open(i+1)` existiera. El carril lo llamaba «respuesta tardía» y tiraba la
orden. El resultado, con un proveedor real, era:

```
cualquier latencia > 0  ->  NO_TRADE  ->  cero operaciones, para siempre
```

Eso no era prudencia: era un motor sin precio. El bloque A lo dejó escrito como consecuencia
honesta («cualquier latencia real descarta el fill»). Este bloque la convierte en lo que
debía ser: **una espera de una vela**.

```
antes:  papel de 0 operaciones con latencia real
ahora:  14 operaciones con 900 ms declarados, cada una pagando un precio que existía
        en o después de la respuesta
```

## 2. Los cinco defectos, con RED antes de tocar código

Escribí primero [test_causal_execution.py](../../../../tests/unit/vision/test_causal_execution.py):
**9 fallos y 1 pase vacuo** antes de implementar. El pase vacuo también se corrigió (un
bucle sobre cero cierres no prueba ningún orden): ahora exige que haya cierres.

| # | defecto | RED que lo reproduce | arreglo |
|---|---|---|---|
| B-01 | no existe cotización posterior a la respuesta | `test_a_sub_bar_latency_still_reaches_a_fill` — `fills == 0` | `vision/execution.py`: `schedule()` devuelve `WAIT` / `FILL` / `EXPIRED`; el relleno paga la primera apertura de vela `>= received_at_ms` |
| B-02 | se podría inventar un precio dentro de una vela | `test_a_price_inside_a_bar_is_refused_as_insufficient_resolution` | `quote_at()` **lanza** `InsufficientResolution` para cualquier instante estrictamente dentro de una vela; sólo la apertura es cotización |
| B-03 | la vela de entrada nunca se comprueba contra el stop | `test_the_bar_a_position_is_opened_on_is_checked_for_stops` — cero `stop_loss` en un escenario donde el único pincho está en esa vela | el bucle ahora hace **entradas primero** y examina el rango después; el cierre se sella al final de la vela, que es cuando el rango es un hecho |
| B-04 | un hueco a través del stop se rellenaba en el nivel del stop | `test_a_gap_through_the_stop_fills_at_the_gap_not_at_the_stop` | `PaperBroker.check_positions_ohlc(gap_policy="open_on_gap")` rellena en la apertura; el objetivo **no** se acredita mejor que su nivel; el valor por defecto sigue siendo el histórico |
| B-05 | no había reconciliación neta | `test_the_run_reconciles_cash_pnl_costs_and_the_risk_engine` | `summary.reconciliation` con cinco identidades + `summary.execution` con la procedencia de cada cotización |

Dos propiedades más que el motor garantiza ahora y que antes no existían en ninguna fila:

* cada `FILL` declara `quote_ts_ms`, `quote_source`, `quote_lag_ms`, `received_at_ms`,
  `decision_bar_index`, `fill_bar_index` y los niveles de stop/objetivo que el broker
  realmente guarda;
* cada `CLOSE` declara la ventana en la que ocurrió (`exit_ts_lower_bound_ms`,
  `exit_ts_upper_bound_ms`, `exit_ts_resolution="bar"`) y la cotización que la abrió.

## 3. Dos expectativas que este bloque sustituye (dicho en voz alta)

No se puede arreglar B-01 y conservar a la vez dos tests que afirmaban lo contrario. Los
cambié, y esto es lo que cambió y por qué:

| test | antes | ahora | por qué |
|---|---|---|---|
| `test_causal_clock.py::test_a_latency_below_the_timeframe_no_longer_buys_the_next_open` | `fills == 0` con 60 s | rellena en la primera cotización posterior; **ningún** relleno puede pagar un precio anterior a la respuesta | el cero era el síntoma de B-01. El defecto del bloque A —comprar la apertura anterior— sigue prohibido y ahora se comprueba en cada fila |
| `test_guards_and_controls.py::test_a_decision_is_dropped_when_the_next_bar_is_missing` | `STALE_EXECUTION` cuando falta la vela siguiente | `test_a_hole_in_the_data_never_becomes_a_price_before_the_answer`: rellena declarando la espera y sigue prohibiendo cualquier precio anterior a la respuesta | una regla por **índice** no distingue un hueco de una latencia real, y con latencia real descartaba todo. La protección PIT es la ventana de la opinión, no la adyacencia |

`STALE_EXECUTION` desaparece como código. Lo que lo hacía necesario —no operar con un precio
que la opinión no describe— lo cumple ahora `max_opinion_age_ms` (una vela por defecto), que
es una condición sobre el tiempo, no sobre la posición en la lista.

## 4. Verificación

Todo lo de abajo se ejecutó; los códigos de salida son los reales.

```text
pytest tests/unit/vision/test_causal_execution.py     9 failed / 1 passed  ->  10 passed
pytest tests/unit/vision tests/unit/paper
       tests/unit/reports tests/unit/intelligence      293 passed          exit 0
ruff (visión, broker, runner, verificador, tests)      All checks passed   exit 0
mypy  (visión, broker, runner, verificador)            no issues           exit 0
ai_bots_003b_verify.py  BOT-VIS-01                     21 PASS / 0 FAIL    exit 0
ai_bots_003b_verify.py  BOT-CTX-01                     21 PASS / 0 FAIL    exit 0
ai_bots_003b_verify.py --mutations  (ambos bots)       10 / 10 detectadas  exit 0
ai_bots_rea_verify.py                                  73 PASS / 0 FAIL    exit 0
ai_bots_run.py --mode live  (sin clave)                BLOCKED             exit 2
```

### Independencia de raíces (LF y CRLF)

`git archive HEAD` extraído dos veces; una raíz normalizada a LF y otra a CRLF (2 719
ficheros cada una). En **cada** raíz: replay paper completo + verificación independiente.

```text
raíz LF   run exit 0 · verify VIS exit 0 · verify CTX exit 0
raíz CRLF run exit 0 · verify VIS exit 0 · verify CTX exit 0
```

| Comparación | Resultado |
|---|---|
| contenido económico del ledger, LF vs CRLF vs repo | **idéntico** (96 filas por bot) |
| `VERIFICATION.json` por raíz | **byte-idéntico** entre raíces |
| verificador del archivo LF sobre los artefactos publicados | **byte-idéntico** al `INDEPENDENT_VERIFICATION.json` del repo |
| ledger byte a byte | **difiere**: cada línea sella `recorded_at_utc` |

Esa última fila es una limitación declarada, no un fallo: la hora de escritura es un hecho
del run, no del dato. Por eso el ledger **no** se compara por bytes; se compara por
contenido económico (todo igual) y la cadena de hashes se recalcula sobre el JSON
canónico, que es independiente del fin de línea del fichero.

## 5. Qué dicen los números del paper

BOT-VIS-01 y BOT-CTX-01, datos reales de Binance 1h ya capturados, 40 llamadas, 900 ms de
latencia declarada:

| | BOT-VIS-01 | BOT-CTX-01 |
|---|---:|---:|
| llamadas | 40 | 40 |
| rellenos | 14 | 14 |
| cierres | 14 (8 stop / 6 objetivo) | 14 (8 stop / 6 objetivo) |
| bruto de referencia | +6.6951 | +6.6951 |
| costes | −22.3751 | −22.3751 |
| **neto** | **−15.6801** | **−15.6801** |
| equidad final | 9 984.3199 | 9 984.3199 |
| espera por cotización | 3 599 100 ms (1 h − 900 ms) | igual |

Dos observaciones que no conviene maquillar:

1. **Los dos bots son idénticos porque el guion mock ignora el prompt.** Demuestra
   fontanería, no que los agentes sean equivalentes. `model_status = MOCK_TEST` en las 40
   llamadas de cada uno.
2. **Los costes multiplican por tres el bruto.** 22.38 USDT de comisiones, spread y
   slippage contra 6.70 de movimiento. Con esta cadencia (24 velas) y este tamaño, la
   fricción se come el resultado antes de que el modelo aporte nada. Eso es información,
   no una derrota: es exactamente lo que un motor causal honesto tenía que dejar ver.

## 6. Lo que sigue sin poder afirmarse

- `REAL_MODEL_CALLED = false`. No hay clave ni autorización de gasto; el modo `live` sale
  con código 2 y `BLOCKED — MISSING_CREDENTIAL`.
- El replay histórico **no** es evidencia prospectiva. Nada de esto mide edge.
- La latencia es un parámetro **declarado**, no una medición de red.
- La suite completa del repositorio no se ejecutó: hay 171 ficheros ajenos modificados que
  no he tocado ni staged.
- En una rejilla de 1 h, 900 ms de latencia cuestan una vela entera de retraso. Es el
  límite de resolución de los datos, no un defecto del motor; un feed con cotizaciones
  sub-vela lo reduciría sin cambiar una línea del carril, porque `Quote.source` ya nombra
  de dónde vino el precio.

## 7. Siguiente paso

`WP-TAP-AI-BOTS-003C/D`: proveedor offline listo (`NO_KEY => BLOCKED`) y colector
prospectivo con hash. La llamada real multimodal sigue siendo `BLOCKED_MODEL_API` hasta
que exista clave y aprobación de coste.
