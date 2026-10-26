# INDEPENDENT VERIFICATION — EXP-003M

**13/14 comprobaciones PASS**, 0 FAIL, 1 `NOT_EXECUTED`. Controles negativos detectados: **8/8**. `false_success=0`.

El verificador no importa el motor de fills: recalcula cada fracción con máscaras y sumas acumuladas, reconstruye los totales, el bootstrap y el veredicto desde los artefactos, y falla si el veredicto publicado no se deduce de los números.

| comprobación | estado | detalle |
| --- | --- | --- |
| `predecessor_seal` | `PASS` | {"listed": 70, "mismatched": [], "missing": []} |
| `signals_reconstruct` | `PASS` | {"max_abs_gap": 0.0, "problems": [], "signals": 47} |
| `tape_integrity` | `PASS` | {"pairs": 42, "problems": [], "rows": 680484} |
| `klines_provenance` | `PASS` | {"bars_compared": 60480, "bars_exact": 60480, "problems": []} |
| `tape_matches_bars` | `PASS` | {"problems": [], "signals_checked": 47} |
| `fills_recompute` | `PASS` | {"evaluations": 188, "max_fill_gap": 4.284256283071386e-11, "problems": []} |
| `economics_recompute` | `PASS` | {"problems": []} |
| `reproduction_of_003l` | `PASS` | {"deltas": {"fill_rate": 0.0, "gross_per_fill_usdt": 0.0, "net_per_fill_usdt": 0.0, "net_per_signal_usdt": 0.0}, "tolerance": 1e-08} |
| `holdout_closed` | `PASS` | {"files_scanned": 744210, "holdout": {"end_utc": "2026-08-20T00:00:00Z", "rule": "no tape, klines or derived statistic for this window may be downloaded, stored or summarised in this experiment; the verifier fails if any file under dataset/ or analysis/ covers it", "start_utc": "2026-08-06T00:00:00Z |
| `no_live_trading` | `PASS` | {"mode": "paper", "problems": [], "run_rows": 1} |
| `config_unchanged` | `PASS` | {"drifted": {}, "files": ["risk.yaml", "runtime.yaml", "vision.yaml"]} |
| `decision_consistency` | `PASS` | {"ceiling_ok": false, "consistent": true, "pessimistic_ok": false, "published": "REJECT", "signals": 47, "verdict": "REJECT"} |
| `seal` | `NOT_EXECUTED` | {"status": "NOT_SEALED"} |
| `online_sample` | `PASS` | {"problems": [], "sample": ["BTCUSDT-2026-06-22", "BTCUSDT-2026-07-13", "BTCUSDT-2026-08-03", "ETHUSDT-2026-07-09", "ETHUSDT-2026-07-30", "SOLUSDT-2026-07-09"], "verified": 6} |

## Controles negativos

| control | detectado | detalle |
| --- | --- | --- |
| `fill_before_latency` | sí | pos-paper-003l-5m-mean_reversion-real-00000001: fill moved before the order could arrive |
| `queue_ignored` | sí | 3 fills rewritten as if the queue were zero |
| `partial_forced_full` | sí | pos-paper-003l-5m-mean_reversion-real-00000113: partial fill forced to 100 % |
| `tape_byte_flip` | sí | BTCUSDT-2026-06-22: one byte flipped in the reduced tape |
| `missing_tape` | sí | BTCUSDT-2026-06-22: tape file deleted |
| `holdout_injection` | sí | one signal re-stamped inside the holdout window |
| `false_success` | sí | verdict replaced by PROMOTE while the economics are negative |
| `predecessor_tamper` | sí | clean seal PASS, tampered seal FAIL |

## Límites de esta verificación

- this verifier shares no fill code with the producer: fills are recomputed with masks and cumsum.
- a program checking a program is independent code, not an independent party.
- the queue position remains unobservable; no check here can turn an estimate into an observed fill.

Sin ejecutar: `seal`. Se declara, no se contabiliza como superado.

Esa comprobación es **el propio sello**, que en el momento de verificar todavía no existía. Después de sellar, `scripts/exp_003m_pipeline.py verify --online` la ejecuta y devuelve 13/13 PASS con 8/8 controles; ese resultado se imprime fuera del árbol sellado, porque escribir dentro de él invalidaría justo lo que verifica.
