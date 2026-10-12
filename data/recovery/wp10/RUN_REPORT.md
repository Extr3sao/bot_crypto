# WP-10 — RUN REPORT

> `2026-10-12T06:26:44Z` · head `49ca773dc26d855d7c846e0d8ce0044c75b0d876` · branch `main` · modo `OFFLINE READ-ONLY — no network, no key, no order, no capital`

## 1. Qué se ejecutó y qué produjo

| artefacto | fase | veredicto |
| --- | --- | --- |
| `WP10_PHASE0_WP9_CLOSURE` | phase 0 — controlled close of WP-9 | PARTIAL/FAIL — exit 4; producers failed: disk-audit, readiness, verifier; artefacts that did not match the commit: WP9_ACTIVE_ECONOMIC_BLOCKERS.json; inputs the commit do |
| `WP10_BASELINE_ECONOMIC_AUDIT` | phase 1 — economic baseline | PARTIAL — the six headline numbers reproduce from primary sources with declared discrepancies, and two requested metrics do not exist in the record |
| `WP10_EXECUTION_COST_DISTRIBUTION` | E-1 — execution cost reality | {"e1": "PLANE_OVERSTATES_MICROSTRUCTURE", "checkpoints_reproduced": 1984, "checkpoints_mismatched": 0, "look_ahead_violations": 0, "false_success": 0} |
| `WP10_E1_DECISION` | E-1 — economic decision | PARTIAL — the plane's non-fee allowance is conservative at the median (measured, not asserted) and is not the binding constraint: the KNOWN fee legs alone exceed the best |
| `WP10_E2_PREREGISTRATION` | E-2 — forward drift entry screen | {"e2": "SPEC_ONLY", "gate": "CLOSED", "self_tests_passed": true, "authorized": false, "campaign_started": false} |
| `WP10_ACTIVE_RECOVERY_MATRIX` | phase 5 — ACTIVE recovery matrix | PARTIAL — the chain is populated and 0 families reach ADOPT; the obstacle is named per family, and for every family it is either an unresolvable edge or a cost gap |
| `WP10_OPEN_BLOCKERS` | phase 6 — open blockers | BLOCKED for the four operational items that need publication, a longer window, a bigger volume or an operator decision; OPEN for offline economic work on data already cap |
| `WP10_INDEPENDENT_VERIFICATION` | phase 7 — independent verification | PASS |

## 2. El registro de 24 estrategias, reconstruido

* estrategias: 24 (0 admitidas, 17 por falta de ventaja bruta, 7 por costes)
* mejor ventaja bruta: 8.912 bps
* planicie de admisión congelada: 23.353553 bps
* las seis cifras publicadas se reprodujeron: `True` con 3 discrepancias declaradas y 16 métricas que el registro no contiene

## 3. E-1 — lo que costó ejecutar de verdad

* estado: `PLANE_OVERSTATES_MICROSTRUCTURE`
* round trip medido (mediana de cuatro libros): 0.024697 bps frente a 3.353554 bps de la planicie
* fees KNOWN: 20.0 bps = 85.64 % de la planicie
* checkpoints reproducidos: 1984, violaciones de look-ahead: 0

## 4. La decisión económica

| planicie | bps | admitidas |
| --- | ---: | ---: |
| `frozen_admission` | 23.353553 | 0 |
| `measured` | 20.024697 | 0 |
| `measured_worst_tail` | 24.586320 | 0 |
| `baseline_arm` | 12.000000 | 0 |
| `discounted_fee_tier` | 15.024697 | 0 |

* mejor celda `volatility@30m`: haría falta un coste por lado de 4.443652 bps para admitirla, frente a los 10 bps publicados (7.5 con descuento de token)
* intervalo del 95 % de esa celda: ±12.009576 bps; celdas positivas: 7, de las cuales 1 tienen un intervalo que excluye el cero

## 5. Matriz ACTIVE y bloqueos

* familias: {'REJECT': 3, 'RESEARCH_MORE': 1, 'INSUFFICIENT_EVIDENCE': 2}
* capa de coste medida incorporada: `True`
* commits sin publicar: 256 (estado CI `BLOCKED`)
* horas de ventana que el volumen puede pagar: 88.69

## 6. Verificación independiente

* veredicto `PASS`: 53 controles de afirmación, 0 fallidos; 12 controles negativos, 0 no detectados; `false_success = 0`
* deriva de estado: `unpublished commits` (256 → 258) — commits were added by other lanes after the artefact was built; the artefact's own value reproduces at its own head
* deriva de estado: `free volume` (17.051 GB → 14.853 GB) — the host is shared and other lanes and agents wrote and read the volume between the measurement and this verification
* deriva de estado: `state-view pins` (data/st6/ST6_HEALTH_STATUS.json) — the pinned artefacts are live outputs of other lanes: an untracked file cannot be pinned at all, and a tracked one whose content moved was rewritten by its own lane after the view was taken

## 7. Gobernanza

* `live_trading`: DISABLED
* `trades_authorized`: 0
* `paper_promotion`: NOT_AUTHORIZED
* `strategies_admitted`: 0
* `strategies_reopened`: 0
* `thresholds_changed`: 0
* `cost_model_changed`: False
* `result_class`: RESEARCH_RESULT (cost measurement) — not BACKTEST, not REPLAY, not PAPER, not LIVE

## 8. Controles de este informe

* [x] every artefact the report folds exists
* [x] the register's six published headline numbers were rebuilt from primary sources
* [x] E-1 reports a measurement and not an assertion
* [x] the independent verifier passed with every control detected
* [x] nothing in WP-10 admits, promotes or reopens a strategy
* [x] the drift the verifier found is carried into the report rather than smoothed away

## 9. Próxima decisión

the decision WP-10 hands over: whether to (a) spend the next campaign on a new hypothesis that must clear the 20 bps round-trip fee floor at the current tier — 2.25x the best gross edge in the register — or (b) first change the fee tier the plane assumes, which is a governance and account decision with no measurement attached, or (c) capture order-level execution evidence, which is the only way maker execution can ever be priced and is the only measurement WP-10 could not make from what exists

