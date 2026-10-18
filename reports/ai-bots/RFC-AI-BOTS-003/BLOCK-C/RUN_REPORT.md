# BLOCK-C — RUN_REPORT

**WP-TAP-AI-BOTS-003C · Open-phase causal ordering, gap-risk parity and freshness**
RFC-TAP-AI-BOTS-003 · baseline `ffbc0cad593bbe3a8202a99d6c90fd9a499fda03` · rama
`agent/ai-bots/RFC-TAP-AI-BOTS-003`.

Todo lo de este bloque es **PAPER/SHADOW**: sin credenciales, sin llamadas a exchange real,
sin API de pago, sin cambios en `config/risk.yaml` y sin tocar los ficheros ajenos
modificados del árbol de trabajo.

## 1. Autoridad y estado real (003C.0)

| Comprobación | Comando | Resultado |
| --- | --- | --- |
| Rama y HEAD | `git rev-parse --abbrev-ref HEAD` · `git log --oneline -3` | `agent/ai-bots/RFC-TAP-AI-BOTS-003` @ `ffbc0ca` (baseline remoto confirmado) |
| Propiedad del árbol | `git status --porcelain \| wc -l` | 170–180 rutas ajenas modificadas, ninguna staged ni tocada por este bloque |
| RED antes de implementar | `pytest tests/unit/vision/test_open_phase_causality.py -q` | **18 failed / 1 passed**, exit 1, commit `ffbc0ca` — [RED_tests_003c.txt](evidence/RED_tests_003c.txt) |

El RED se capturó *antes* de tocar el carril; la única prueba que pasó entonces es la del
contrato de `schedule` (C-08 unitario), que es interfaz, no comportamiento.

## 2. Qué se ejecutó y con qué resultado

| Suite | Resultado literal | exit |
| --- | --- | --- |
| `pytest tests/unit/vision` | 160 passed in 155.72s | 0 |
| `pytest tests/unit/paper` | 73 passed in 2.20s | 0 |
| `pytest tests/unit/risk` | 147 passed in 11.67s | 0 |
| `pytest tests/unit/intelligence` | 28 passed in 4.90s | 0 |
| `pytest tests/unit/reports` | 51 passed in 9.22s | 0 |
| `ruff check` (carril, broker, tests de visión, verificadores) | All checks passed! | 0 |
| `mypy` (15 source files) | Success: no issues found | 0 |
| `scripts/ai_bots_003c_capture.py` | 5 escenarios, 5 cadenas intactas | 0 |
| `scripts/ai_bots_003c_verify.py` × 5 escenarios | **120 comprobaciones, 0 fallos** | 0 |
| `scripts/ai_bots_003c_verify.py --mutations` × 5 | **53 mutaciones aplicadas, 53 detectadas, 12 omitidas** | 0 |

La salida literal está en [TEST_COMMANDS.txt](evidence/TEST_COMMANDS.txt) y el detalle en
[WP_RUN_REPORT.json](WP_RUN_REPORT.json), [INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json)
y [MUTATION_REPORT.json](MUTATION_REPORT.json).

## 3. Qué produjo la corrida

Datos reales de Binance 1h ya capturados en el repo (`data/edge08/universe-1h`), dos activos
distintos, uno largo (`UNI/USDT`) y otro corto (`AAVE/USDT`), ventana que empieza en un lunes
00:00 UTC, cadencia 24 barras, ventana de 120 velas.

| Escenario | Latencia | Rellenos | Cierres | Salidas por hueco | PnL neto | Filas | Cadena |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `real_900ms` | 900 ms | 34 | 34 | 0 | −97.926767 | 210 | intacta |
| `real_900ms_wide_stop` | 900 ms | 34 | 34 | 0 | −34.247921 | 210 | intacta |
| `real_0ms` | 0 ms | 34 | 34 | 0 | −85.426764 | 210 | intacta |
| `real_900ms_hole` | 900 ms | 34 | 34 | 0 | −85.449238 | 210 | intacta |
| `synthetic_gap_open` (**declarado**) | 0 ms | 1 | 1 | **1** | −16.232058 | 246 | intacta |

Lecturas que no se esconden:

* **900 ms de latencia cuestan una vela de 1 h**: 50 eventos `requote:WAITING_FOR_QUOTE` en
  `real_900ms` frente a 0 con latencia cero. Es el precio de la honestidad del reloj, no un
  defecto nuevo.
* **El hueco de apertura no existe en estos datos.** Sobre 3000 barras horarias de UNI y AAVE
  el mayor salto cierre→apertura es de **0,30 %**, y en 426 entradas simuladas con stop del
  2 % **ninguna** se detuvo en una apertura. Por eso el escenario que lo ejercita es
  declaradamente sintético y el resto de la evidencia real no lo contiene.
* Las dos corridas reales con el stop canónico cierran casi todo en la vela de entrada: con
  un stop del 0,5 % y un rango horario típico mayor, la posición muere dentro de la barra en
  la que nace. `real_900ms_wide_stop` (override declarado a 2 %) existe para que las
  posiciones sobrevivan y la barra de entrada no decida el resultado por sí sola.

## 4. Artefactos

* [PIT_OPEN_EVENT_TRACE.jsonl](PIT_OPEN_EVENT_TRACE.jsonl) — 952 filas de evento con la
  **fase que el propio carril escribe**: 410 `DECISION`, 404 `OPEN_ENTRY`, 136 `INTRABAR`,
  1 `OPEN_GAP` y 1 `RUN_END`, en orden de `seq` dentro de cada instante.
* [DATA_COVERAGE_LEDGER.jsonl](DATA_COVERAGE_LEDGER.jsonl) — por símbolo y escenario: rejilla
  declarada, barras observadas, aperturas ausentes y las filas que reaccionaron a cada hueco.
* [RISK_NET_RECONCILIATION.json](RISK_NET_RECONCILIATION.json) — la reconciliación del
  carril y el rastro de riesgo de cada cierre.
* [CAPTURE.json](CAPTURE.json) — qué se corrió, con qué latencia, con qué overrides y con qué
  digest de dataset; declara `real_model_called=false`.
* `evidence/*_ledger.jsonl`, `evidence/*_summary.json` — la cadena real y el resumen de cada
  escenario.

## 5. Lo que NO se puede decir con esta evidencia

`REAL_MODEL_CALLED=false` y `PROSPECTIVE_PAPER_VALIDATED=false`. El proveedor es un guion
determinista (`provider=replay` en cada fila `RUN`): aquí se prueba **fontanería, orden
causal y contabilidad**, no alpha, ni rentabilidad, ni latencia de un proveedor real, ni la
aspiración de ≥3 operaciones al día. El PnL negativo de las corridas reales es información
sobre la fricción (34 idas y vueltas con 0,5 % de stop no pagan el coste), no una derrota.
