# INDEPENDENT VERIFICATION — EXP-003N

**Veredicto: `PASS`** · 12/12 comprobaciones · 10/10 controles negativos detectados · `false_success=0`

Verificador: `scripts/exp_003n_verify.py (shares no code with the builders)` — un programa distinto, no una persona
(`INDEPENDENT_VERIFIER=PROGRAM_NOT_PERSON`). Relee el dataset con su propio parser,
re-agrega las barras con su propia aritmética y recalcula un cierre desde las barras.

## Comprobaciones

| # | comprobación | estado | detalle |
| ---: | --- | --- | --- |
| 1 | `V1_dataset_provenance` | **PASS** | 3 files, drifted=[] |
| 2 | `V2_config_frozen` | **PASS** | 3 config digests |
| 3 | `V3_design_binding` | **PASS** | design sha256 a0776fa3fbe6d2e1… |
| 4 | `V4_holdout_closed` | **PASS** | 0 rows at or after 2026-08-06T00:00:00Z; partitions inside=True |
| 5 | `V5_forward_returns_recomputed` | **PASS** | 6692 values compared from raw bars, 0 mismatched |
| 6 | `V6_means_consistent` | **PASS** | 72 symbol cells, 0 inconsistencies |
| 7 | `V7_multiple_testing` | **PASS** | 1 surviving cells; builder=1 |
| 8 | `V8_cost_subtracted` | **PASS** | costs={'BTCUSDT': 24.786, 'ETHUSDT': 24.786, 'SOLUSDT': 27.31}, 0 defects |
| 9 | `V9_closed_trade_view` | **PASS** | 24 cells priced; unpriced=0; censored=0 |
| 10 | `V10_no_promotion` | **PASS** | paper/live authorisation untouched |
| 11 | `V11_verdict_from_numbers` | **PASS** | 0 advanced candidates |
| 12 | `V12_runtime_paper` | **PASS** | mode=paper live_enabled=False |

## Controles negativos

Cada control muta una copia en memoria o en un directorio temporal y comprueba que la
comprobación a la que apunta lo detecta. Un control que no puede fallar no es evidencia.

| control | detectado | detalle |
| --- | --- | --- |
| `tampered_forward_return` | sí | breakout/1h/BTCUSDT shifted by +50 bps |
| `holdout_injection` | sí | a row at 2026-08-10T00:00:00Z is outside every allowed partition |
| `cost_omitted` | sí | 6 cells would pass a zero-cost gate and fail the real one: ['momentum/1h', 'breakout/1h', 'mean_reversion/5m'] |
| `false_success` | sí | a negative-net cell relabelled ADVANCE is contradicted by its own number |
| `multiple_testing_inoperative` | sí | q=1.0 keeps 84 vs 1 at q=0.1 |
| `dataset_byte_append` | sí | an appended byte changes the digest the design froze |
| `sample_gate_inflated` | sí | the smallest IS cell has 0 signals; the gate is 20 |
| `verdict_contradicts_gates` | sí | 0 cells claim a state their gates deny |
| `cost_below_floor` | sí | min round trip 24.7864 bps vs floor 20.0 bps |
| `closed_trade_recomputed` | sí | 35 closed trades recomputed here, 0 mismatched; 35 change when the fees are removed: [] |

## Qué no demuestra esta verificación

- No convierte la evidencia en observada: no se envió ninguna orden y ningún fill es real.
- No es una revisión humana: `BUILDER != VERIFIER` se cumple como dos programas, y así se
  declara en lugar de presentarse como una auditoría externa.
- No juzga si el dataset es el mercado: juzga si los números publicados se derivan de él.
- **No regenera las señales.** Toma los timestamps de señal publicados y recalcula desde
  las barras el retorno forward, el coste, las puertas y el veredicto. Un look-ahead dentro
  de la ventana PIT de una familia no lo detectaría este programa: esa parte la cubren
  `tests/unit/reports/test_exp_003n_screen.py` y los tests de familia, que **no** son
  independientes del constructor. Es el hueco de independencia que queda declarado.
