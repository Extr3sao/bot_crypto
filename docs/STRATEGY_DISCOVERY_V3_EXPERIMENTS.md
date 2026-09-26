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
| E-V3-003 | diag momentum | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | done | ZERO gross −237.89$ (PF 0.94, 2526 trades) | NO_GROSS_EDGE (única asimetría MFE>MAE +6.5 bps, bajo barrera) |
| E-V3-004 | diag breakout | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | done | ZERO gross −10.19$ (PF 0.997, 2426 trades) | NO_GROSS_EDGE (breakeven exacto) |
| E-V3-005 | diag mean_reversion | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | done | ZERO gross +236.92$ (PF 1.057, 3190 trades, +1.49 bps) | COST_KILLED — único edge real del universo |
| E-V3-006 | diag volatility | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | done | ZERO gross −123.12$ (PF 0.87, 520 trades) | NO_GROSS_EDGE |
| E-V3-007 | diag ema_crossover | a910f8d+ | 5m, 4 scenarios, MFE/MAE | all | done | ZERO gross −393.37$ (PF 0.805, 1725 trades) | NO_GROSS_EDGE (el peor) |
| E-V3-008 | D-01 timeframe audit (6 familias × 15m/30m/1h) | a910f8d+ | 3 TFs, BASE+ZERO | BASE/ZERO | done | techo +8.91 bps (volatility@30m); no-monótono; 1h vuelve a negativo | REJECT Filter 2 (COST_KILLED) |
| E-V3-009 | D-02_vol_z_rev | a910f8d+ | 15m, 4 scenarios | all | done | ZERO gross −11.51$ (31 trades) | REJECT Filter 1 |
| E-V3-010 | D-03_squeeze_breakout | a910f8d+ | 30m, 4 scenarios | all | done | 0 señales en todo el dataset | INTESTABLE (no re-tuning post-hoc) |
| E-V3-011 | D-04_rel_momo | a910f8d+ | 1h, 4 scenarios | all | done | ZERO gross −12.12$ (191 trades, PF 0.95) | REJECT Filter 1 |
| E-V3-012 | D-05 régimen PIT (12 celdas) | a910f8d+ | {trend,mean_rev,vol}×{15m,30m}×{HIGH,LOW} | ZERO | done | 0/12 celdas pasan gate; 11/12 sign-flip DEV↔VAL | REJECT (REGIME_FRAGILE) |

Errata operativa: los 5 diagnósticos de familias lanzados a las ~09:05
corrieron mientras el resampleo 15m/30m/1h se escribía en data/ y su glob
habría mezclado TFs; fueron abortados y relanzados tras fijar el glob del
motor a 5m-only (commit del patch). El diagnóstico trend (08:33) evaluó el
glob una vez antes del resampleo: verificado 5m puro (trades/PF idénticos
al baseline V1). D-03 registró 0 señales en todo el dataset (especificación
pre-registrada demasiado estricta): intestable sin re-especificar; NO se
re-ajustan parámetros post-hoc (§23).

Experimentos NO ejecutados deliberadamente (§23/§24): grid-search de
parámetros de las 6 familias rechazadas; re-optimización de TP/SL por
backtest-search; indicadores adicionales sin hipótesis; cualquier re-segmentación
de regímenes post-hoc (D-05 fija las celdas antes de mirar resultados).
