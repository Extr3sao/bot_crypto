# STRATEGY-DISCOVERY-V3 — registro de experimentos (§12)

Dataset fingerprint (todos los experimentos): `e44a7ab1933362096dfd6f5fd36fb560`
(84 ficheros: 3 activos × 7 ventanas × {5m, 15m, 30m, 1h} resamples
deterministas; periods W1-W7 = 2026-03-01..2026-09-24, paper day excluded).

Código: HEAD al momento de cada experimento. Motor: `multi_family_backtest.py`
(clases runtime reales, parity §14), `multi_tf_backtest.py` (import del mismo
motor), `cost_barrier.py` (análisis de costes), `resample_baseline_data.py`
(resample determinista verificado).

Anti-repetición: cualquier experimento futuro sobre estos datos debe
registrarse aquí antes de ejecutarse. Scenarios: BASE / 2X_COST /
STRESSED_SLIPPAGE / ZERO_COST (diagnóstico, nunca admission).

| experiment_id | candidate/hypothesis | commit | scope | cost_model | status | result | decision |
|---|---|---|---|---|---|---|---|
| E-V1-001..006 | 6 familias runtime (baseline V1) | 3271a97 | 5m, W1-W7, 3 assets | BASE/2X/STRESSED | done | 6/6 REJECT (PF<1 neto) | pre-registra la lección: gross<=0 en trend |
| E-V3-001 | cost_barrier (§5) | a910f8d+ | 4 TFs, 3 assets | 12/24/32 bps RT | done | ver COST_BARRIER.json | barrera 12 bps; TP 0.75% → break-even WR 41.6% |
| E-V3-002 | diag trend (D-01 precursor) | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | running→done | BASE gross −232.76 / 1288 trades; MFE 0.71% ≈ MAE 0.73% | NO_GROSS_EDGE confirmado (Filter 1) |
| E-V3-003 | diag momentum | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | running | — | — |
| E-V3-004 | diag breakout | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | running | — | — |
| E-V3-005 | diag mean_reversion | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | running | — | — |
| E-V3-006 | diag volatility | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | running | — | — |
| E-V3-007 | diag ema_crossover | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | running | — | — |
| E-V3-008 | D-01 timeframe audit (6 familias × 15m/30m/1h) | a910f8d+ | 3 TFs, BASE+ZERO | BASE/ZERO | running | — | — |
| E-V3-009..0NN | candidatas D-02..D-05 (post-registro, una por hipótesis) | TBD | por hipótesis | all | pending | — | — |

Experimentos NO ejecutados deliberadamente (§23/§24): grid-search de
parámetros de las 6 familias rechazadas; re-optimización de TP/SL por
backtest-search; indicadores adicionales sin hipótesis; cualquier re-segmentación
de regímenes post-hoc (D-05 fija las celdas antes de mirar resultados).
