# MICROSTRUCTURE_EXPERIMENTS_V1 — registro de experimentos (§52)

> Registro de cada experimento ejecutado en EXECUTION-COST &
> MICROSTRUCTURE-EDGE-V1. Datasets identificados por fingerprint sha256.

Fecha: 2026-09-26. Motor: `scripts/microstructure_experiments.py`.
Clasificación: `scripts/microstructure_admission.py`.

## 0. Fingerprints de datasets (sha256, 16 hex)

| dataset | fingerprint | bytes |
| --- | --- | ---: |
| KLINES_BTCUSDT_5m | a3daceac26dfcb7a | 11,069,325 |
| KLINES_ETHUSDT_5m | e5f21f8fb98a8315 | 10,932,893 |
| KLINES_SOLUSDT_5m | 5f8a99f92d9f4d53 | 10,515,299 |
| PREMIUM_BTCUSDT_5m | 529b8726648353a4 | 7,355,220 |
| PREMIUM_ETHUSDT_5m | e6ca3eac77a72be0 | 7,351,581 |
| PREMIUM_SOLUSDT_5m | 271376282557956e | 7,347,165 |
| FUNDING_BTCUSDT | 68d6577a2317b8ad | 85,024 |
| FUNDING_ETHUSDT | 253efdd78c5e3e42 | 84,423 |
| FUNDING_SOLUSDT | d1dc43f34970d918 | 83,358 |
| OPENINTEREST_BTCUSDT | d7a037974b30fa75 | 1,615,178 |
| OPENINTEREST_ETHUSDT | 930c58e335c83828 | 1,633,824 |
| OPENINTEREST_SOLUSDT | 665a415bddc7bf31 | 1,625,207 |

(En `reports/*`, gitignored; regenerables con
`scripts/fetch_microstructure_data.py`.)

## 1. Configuración común

- Intervalo base: **5m**. Splits: DEV = W1-W4 (mar-jun), VAL = W5-W6
  (jul-ago), OOS = W7 (sep 1-24).
- Cost model: `REALISTIC_RETAIL_COST_MODEL` = 23.5 bps RT. Stress 1.5X, 2X.
- Horizontes (label): 1, 5, 15, 30, 60 barras.
- Dirección: las hipótesis de flujo/lead-lag fijan su signo en **DEV** y lo
  aplican a todo; funding/premium ya se pre-registraron contrarias.

## 2. Experimentos

| experiment_id | hyp | signal | data | horizonte | coste | clasificación |
| --- | --- | --- | --- | ---: | ---: | --- |
| EXP-S-01 | M-01 | flow_imbalance_z ±2 | klines+flow | 5 | 23.5 | **COST_KILLED** |
| EXP-S-02 | M-02 | book imbalance | order book | — | — | **EXECUTION_MODEL_REQUIRED** |
| EXP-S-03 | M-03 | flow breakout | klines+flow | 5 | 23.5 | **COST_KILLED** |
| EXP-S-04 | M-04 | funding_z ±2 contrarian | funding | 30 | 23.5 | **NO_GROSS_EDGE** |
| EXP-S-05 | M-05 | premium_z ±2 contrarian | premium | 15 | 23.5 | **NO_GROSS_EDGE** |
| EXP-S-06-BTC | M-06 | price×OI celdas | OI (30d) | 15 | 23.5 | **NO_GROSS_EDGE** |
| EXP-S-06-ETH | M-06 | price×OI celdas | OI (30d) | 15 | 23.5 | **NO_GROSS_EDGE** |
| EXP-S-06-SOL | M-06 | price×OI celdas | OI (30d) | 15 | 23.5 | **NO_GROSS_EDGE** |
| EXP-S-07-BTC | M-07 | funding+OI+price | OI (30d) | 30 | 23.5 | **LIMITED_HISTORY** |
| EXP-S-07-ETH | M-07 | funding+OI+price | OI (30d) | 30 | 23.5 | **LIMITED_HISTORY** |
| EXP-S-07-SOL | M-07 | funding+OI+price | OI (30d) | 30 | 23.5 | **LIMITED_HISTORY** |
| EXP-S-08 | M-08 | BTC prev-bar -> ETH/SOL | klines | 1 | 23.5 | **NO_GROSS_EDGE** |

Total: **12 experimentos** (8 hipótesis M-01..M-08).

## 3. Filter 0 (information content)

Ejecutado sobre 11 features × 5 horizontes × 3 activos
(`reports/microstructure-v1/INFORMATION_CONTENT.json`). Resultado clave:
**|IC de Spearman| <= 0.06 en todas las celdas**. Los spreads decile-10 −
decile-1 sólo alcanzan ~24-31 bps en `funding_rate@h60` (ETH/SOL), con IC
~0.03-0.04 (prácticamente sin información lineal) y fuertemente
confundido con régimen alcista (funding alto coincide con tendencia). Todo lo
demás queda por debajo del coste.

Umbral Filter 0: `NO_INFORMATION` si |IC| < 0.01 **y** |spread| < 23.5 bps.

## 4. Early stopping (§53)

- S-04: DEV gross +1.03, VAL +3.02, **OOS −4.81** → no pasa Filter 3.
- S-05: DEV +2.28, **VAL −0.82**, **OOS −18.03** → no pasa Filter 1 agregado.
- S-08: gross −0.19 → NO_GROSS_EDGE inmediato.
- S-06: gross −1.8..−2.2 → NO_GROSS_EDGE inmediato.
- S-01/S-03: gross positivo pero <= 2.4 bps << 23.5 → COST_KILLED.

No se ejecutó walk-forward ni robustness de nada, porque ninguna línea superó
Filter 1/Filter 2 (§53).

## 5. Walk-forward

No aplicable: ninguna candidata superó cost survival, por lo que no hay nada
sobre lo que correr walk-forward (§39 "para cualquier candidata seria").
