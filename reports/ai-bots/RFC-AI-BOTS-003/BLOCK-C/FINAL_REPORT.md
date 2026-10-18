# BLOCK-C — FINAL_REPORT

**WP-TAP-AI-BOTS-003C · orden causal de la apertura, paridad de riesgo en el hueco y frescura**
RFC-TAP-AI-BOTS-003 · baseline verificado `ffbc0cad593bbe3a8202a99d6c90fd9a499fda03`.

PAPER/SHADOW. Sin credenciales, sin exchange real, sin API de pago, sin cambios en
`config/risk.yaml`, sin tocar ficheros ajenos del árbol de trabajo.

---

## 1. El P0, y por qué era un P0

El Bloque B dejó escrito el defecto: en `VisionLane.run` los rellenos de entrada al OPEN se
ejecutaban **antes** de que el broker reconociese los stops que ese mismo OPEN ya había
cruzado, porque la comprobación protectora corría al CLOSE. Una posición que abría el hueco
de su stop seguía viva en el libro de riesgo mientras la misma apertura aprobaba riesgo
nuevo: la pérdida no se le contaba al motor que decide, ni a la ventana diaria o semanal, ni
a los slots, ni a la caja. No era un problema de precio: era un problema de **orden**.

Orden implementado, en el instante `ts`:

```
OPEN(ts):
  1. stops que la apertura observable cruzó, para posiciones preexistentes,
     a precio de apertura (OPEN_GAP), todos los símbolos antes de una sola aprobación;
  2. marcar el resto del libro con las aperturas observables; si un símbolo con
     posición no tiene apertura, vetar el riesgo nuevo de ese instante;
  3. aprobar y ejecutar entradas con la equidad que ese mismo OPEN produce;
CLOSE(ts + intervalo):
  4. sólo rango intrabar (incluida la vela de entrada), con el instante declarado
     como ventana BAR_WINDOW y precio en el nivel;
  5. marcar equidad y conciliar;
  6. decisiones nuevas, sólo con datos cerrados y disponibles.
```

Nunca se usa el HIGH/LOW de la vela para una puerta de apertura: lo que el OPEN hace
conocible se decide en el OPEN, y lo que sólo se sabe al cerrar se decide al cerrar.

## 2. Lo que cambió en el código (superficie real)

| Fichero | Δ | Qué |
| --- | --- | --- |
| [lane.py](../../../../src/trading_bot/vision/lane.py) | +368/−57 | fases del `run`, marca en la apertura, veto por valoración ambigua, huecos, cotización sólo desde fuente nombrada, fase y procedencia en cada fila |
| [broker.py](../../../../src/trading_bot/paper/broker.py) | +50/−12 | `stop_gapped` compartido y `exit_on_open_gap` (opt-in, política legada intacta) |
| [execution.py](../../../../src/trading_bot/vision/execution.py) | +60/−9 | `CoverageProof`, `QuoteFeed`, ventana de opinión estrictamente declarada |
| [test_open_phase_causality.py](../../../../tests/unit/vision/test_open_phase_causality.py) | +879 (nuevo) | C-01…C-12, reduce-only y simetría largo/corto contra el runtime real |
| [ai_bots_003c_capture.py](../../../../scripts/ai_bots_003c_capture.py) | +520 (nuevo) | constructor: cinco escenarios y los artefactos del bloque |
| [ai_bots_003c_verify.py](../../../../scripts/ai_bots_003c_verify.py) | +700 (nuevo) | verificador independiente, sin importar `trading_bot` |
| [ai_bots_003b_verify.py](../../../../scripts/ai_bots_003b_verify.py) | +30/−6 | vocabulario de resolución de instante (sin debilitar la regla, ver §5) |

`RiskManager` y `PaperBroker` son **los de producción** y siguen siendo uno solo: no hay
segundo motor de riesgo ni segundo broker. El default del broker para el hueco sigue siendo
`stop_price`; `open_on_gap` es una elección explícita del carril, y C-12 la fija con un
fixture bit-exacto.

## 3. Evidencia ejecutada (números literales)

```
RED antes de implementar     18 failed / 1 passed          exit 1   (commit ffbc0ca)
tests/unit/vision            160 passed                    exit 0
tests/unit/paper              73 passed                    exit 0
tests/unit/risk              147 passed                    exit 0
tests/unit/intelligence       28 passed                    exit 0
tests/unit/reports            51 passed                    exit 0
ruff (carril, broker, tests, verificadores)  All checks passed!   exit 0
mypy (15 ficheros)           Success: no issues found      exit 0
capture 5 escenarios         5 cadenas intactas            exit 0
003c verify × 5              120 comprobaciones / 0 fallos  exit 0
003c mutations × 5           53 aplicadas / 53 detectadas   exit 0   (12 omitidas por diseño)
BLOCK-B re-verificado        21/21 por bot + 10/10 mutaciones exit 0 (evidencia previa intacta)
```

El P0 tiene su recibo dentro de un solo instante, en el escenario declarado
`synthetic_gap_open` (mismo caso que C-01, ejecutado de punta a punta):

```
seq 108  DECISION          BTC/USDT   DECISION      (la última opinión antes del hueco)
seq 109  DECISION          ETH/USDT   DECISION      intent=OPEN_LONG
seq 110  CLOSE             BTC/USDT   OPEN_GAP      stop_loss · gap_price_source=bar_open · pnl −16.232058
seq 111  DECISION_OUTCOME  ETH/USDT   OPEN_ENTRY    risk_blocked_by=daily_loss_limit
```

La pérdida se registra **antes** de la fila que decide sobre el riesgo nuevo, en el mismo
`ts_ms`; el acumulado del día y de la semana que ve la puerta es el que incluye esa pérdida
(`risk_daily_pnl_after` y `risk_weekly_pnl_after` se recalculan desde las filas con el
calendario de la biblioteca estándar, y coinciden). En la corrida real con latencia, la
misma pérdida decide la propuesta del otro activo una hora después, que es lo que la
rejilla de 1 h permite.

## 4. Los tres invariantes del encargo

* **`FALSE_SUCCESS=0`** — cada cifra sale de un comando con su código de salida real
  ([TEST_COMMANDS.txt](evidence/TEST_COMMANDS.txt)); el RED está guardado con su commit y su
  stdout; dos fallos de mi propio verificador se encontraron y se corrigieron **porque la
  mutación no los detectaba** (§6), y lo que el verificador no puede ver se declara (§7).
* **`BUILDER != VERIFIER`** — [ai_bots_003c_verify.py](../../../../scripts/ai_bots_003c_verify.py)
  no importa un solo módulo del carril: reimplementa la cadena de hashes, el calendario UTC
  (día y semana), las identidades económicas y la direccionalidad del stop. Las mutaciones
  vuelven a **sellar** la cadena, así que lo que falla es la regla, nunca el hash.
* **`TEST_TARGET == RUNTIME_TARGET`** — los tests atacan `VisionLane.run` con el
  `RiskManager` de `config/risk.yaml` y el `PaperBroker` de producción; la corrida publicada
  usa el mismo camino.

## 5. Dos expectativas existentes que este bloque endureció (y por qué)

1. **`test_a_hole_in_the_data_never_becomes_a_price_before_the_answer`** (revisión
   *CONDITIONAL* del WP). Afirmaba `fills >= 1` atravesando un hueco, justificándose en que
   la cotización siguiente era posterior a la respuesta y estaba dentro de la ventana de la
   opinión. Ninguna de las dos cosas demuestra continuidad: ahora el hueco se etiqueta
   `DATA_GAP`, esa decisión no opera, y las decisiones cuyos datos **sí** son continuos
   siguen operando con la misma condición de cotización. El hueco se colocó donde
   importa (la barra de relleno esperada) para que el test no fuera vacuo.
2. **`test_the_bar_a_position_is_opened_on_is_checked_for_stops`** afirmaba
   `exit_ts_resolution == "bar"`. El vocabulario pasa a ser explícito —`OPEN_GAP`,
   `BAR_WINDOW`, `QUOTE`—, y el verificador de 003B acepta el conjunto declarado (nunca una
   etiqueta desconocida) manteniendo la identidad de la ventana. La evidencia publicada del
   Bloque B se re-verifica con él: 21/21 y 10/10 mutaciones por bot.

Ninguna de las dos se cambió en silencio, y ninguna debilita una afirmación: la primera
endurece (de "se puede rellenar" a "no se puede, salvo prueba independiente") y la segunda
sustituye una etiqueta por un vocabulario cerrado.

## 6. Mutaciones: lo que un verificador descubre de sí mismo

`M-01` (retrasar la liquidación del hueco hasta después de la entrada que debía vetar) no la
detectaba mi primera versión: comparaba `seq` de entradas que no llevaban `seq` (vive en la
línea de cadena, no en el objeto), así que la comparación era `0 < 0` y la regla era
decorativa. Lo encontró la mutación, no una lectura; el arreglo es que `rows_of` adjunta el
`seq` de la línea. `M-03` reveló un segundo matiz honesto: acreditar el hueco **en el nivel
del stop** no rompe la regla direccional ("no mejor que el nivel"), la rompe la regla que
fija el precio pagado a la **apertura observable**. Está escrito en el verificador y en el
informe de mutaciones, con las 13 definidas:

| Código | Defecto reintroducido | Regla que debe fallar |
| --- | --- | --- |
| M-01 | pérdida del hueco registrada después de la entrada | orden de fases en el instante |
| M-02 | ventana ancha para un instante que es exacto | instante exacto en la apertura |
| M-03 | stop del hueco acreditado en el nivel | precio = apertura observable |
| M-04 | corto acreditado 1 % mejor que su stop | direccionalidad (simetría) |
| M-05 | relleno con precio anterior a la respuesta | cotización en o después de la respuesta |
| M-06 | hueco "cubierto" por las propias velas del replay | fuente declarada del precio |
| M-07 | equidad de riesgo movida por otra cifra que el PnL | entrega al motor de riesgo |
| M-08 | ventana diaria manipulada | calendario reconstruido |
| M-09 | resolución inventada | vocabulario cerrado |
| M-10 | identidad neta rota | PnL = bruto − coste − comisiones |
| M-11 | decisión operable sin fila terminal | nada se pierde en silencio |
| M-12 | `position_id` duplicado | identidad única |
| M-13 | contador del resumen inflado | contadores = filas |

## 7. Limitaciones declaradas (no maquilladas)

* **`REAL_MODEL_CALLED=false` · `PROSPECTIVE_PAPER_VALIDATED=false`.** El proveedor es un
  guion determinista (`provider=replay` en cada fila `RUN`). Esto no es alpha, no es
  rentabilidad, no es latencia real y no es la aspiración de ≥3 operaciones al día.
* **El hueco de apertura no existe en este dataset.** 3000 barras horarias de UNI y AAVE: el
  mayor salto cierre→apertura es 0,30 %, y 0 de 426 entradas con stop del 2 % se detuvieron
  en una apertura. El camino queda probado por construcción (C-01/C-02/C-03 y el escenario
  declarado como sintético); la corrida real demuestra lo contrario, que en un mercado
  continuo el stop se cruza dentro de la vela y la ventana es la etiqueta honesta.
* **Con el stop canónico (0,5 %) las posiciones mueren en la vela en que nacen** (34 de 34
  cierres intrabar en las corridas reales). El escenario `real_900ms_wide_stop` (override
  declarado a 2 %) existe para que las posiciones sobrevivan; no cambia ninguna política del
  repo.
* **El ledger no es byte-idéntico entre corridas**: cada línea sella la hora de escritura.
  Lo que debe coincidir, y coincide, es la proyección económica.
* **El verificador no puede ver un dato que no está en el ledger**: si una fila mintiera
  coherentemente sobre `exit_reference_price` y `gap_open_price` a la vez, haría falta el
  dataset. Eso es material de 003E (colector con cotizaciones reales y digest por barra), no
  de este bloque.
* **La suite completa del repositorio no se ejecutó**: el árbol tiene ~180 ficheros ajenos
  modificados por trabajo concurrente. Se corrieron las suites afectadas (visión, paper,
  riesgo, intelligence, reports) más ruff y mypy sobre el alcance tocado.

## 8. Handoff

**003D (preparación offline de proveedor)** puede partir de aquí sin deuda de fontanería: el
contrato de datos PIT ya distingue `data_available_at`, respuesta, cotización observada y
relleno; el hueco tiene un camino fail-closed con una única puerta de evidencia
independiente (`QuoteFeed.prove_coverage`), y esa puerta es exactamente la que un colector
real debe satisfacer. **003E (colector prospectivo append-only)** hereda el hueco como
obligación: sin cotizaciones reales que prueben continuidad y disponibilidad, el carril
**no** opera, y eso ya no es una convención del informe: es una fila `DATA_GAP` con su
decisión cerrada.

Una sola llamada multimodal real sigue requiriendo clave configurada y autorización
explícita del usuario para servicio externo y coste; la suscripción del asistente de código
no es un derecho de inferencia.
