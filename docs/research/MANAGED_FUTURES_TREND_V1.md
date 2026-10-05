> SUPERSEDED BY RFC-041 (BUSINESS-FREEZE-2026-001).  This document is retained as
> history; the current canonical state is docs/research/ECONOMIC_STATE.json and
> docs/research/FINAL_BUSINESS_DECISION.md.

# RFC-036 — MANAGED FUTURES TREND FAITHFUL REPRODUCTION (P1)

CANDIDATE = **MF-TREND-001**
PRIMARY REPRODUCTION SOURCE = **S001** (Moskowitz, Ooi & Pedersen 2012),
corroborated by S002 / S029 (Hurst-Ooi-Pedersen) and S003 (Baltas-Kosowski).

REPRODUCTION FIDELITY = **CLOSE** (same signal, volatility scaling, monthly
rebalance and equal-weight multi-asset construction, on a shorter, differently
sourced sample with an explicit roll/cost layer the sources reported only gross).

## Data (no paid data used)

Free individual-futures-contract archive (TurtleTrader), one text file per
contract with `Date,Open,High,Low,Close,Volume,OpenInterest`. That grain lets us
identify an actually-tradable contract at every historical decision (§7/§10).

- 26 markets across 6 asset classes: EQUITY_INDEX (`sp`), GOVERNMENT_BOND_RATES
  (`us`,`ed`), FX (`ad`,`bp`,`cd`,`dx`,`jy`,`sf`), ENERGY (`cl`,`ho`), METALS
  (`gc`,`hg`,`pa`,`pl`,`si`), AGRICULTURE (`c`,`fc`,`jo`,`kc`,`lh`,`o`,`pb`,`s`,`sb`,`w`).
- Sample ≈ 1959–2000; strategy window **1985-01-01 .. 2000-03-31**.

## Frozen strategy

| item | value |
| --- | --- |
| Signal | sign(trailing 252-day excess return) |
| Vol estimator | 60-day realised vol |
| Position vol target | 40% per instrument |
| Portfolio vol target | 15% |
| Rebalance | monthly |
| Execution | signal through prior month-end (T); trade at first trading day of next month close (≥ T+1) |
| Roll policy | `PIT_VOLUME_FRONT_MONTHLY_V1` (trailing-20d volume, PIT) |
| Cost model | `MANAGED_FUTURES_COST_MODEL_V1` (frozen hash before discovery) |

## Splits

- DISCOVERY 1985-01-01 .. 1993-12-31
- VALIDATION 1994-01-01 .. 2000-03-31
- HOLDOUT = **FUTURE_ONLY** (no pristine historical holdout survives)

## Gates

| gate | result |
| --- | --- |
| G_MF_DATA | PASS |
| G_MF_REPRO | PASS |
| G_MF_1_DISCOVERY | PASS |
| G_MF_2_VALIDATION | PASS |
| G_MF_3_ROBUSTNESS | PASS |
| G_MF_4_HOLDOUT | NOT_RUN_FUTURE_ONLY |

## Results (headline capital $10M, fractional-contract replication)

- Discovery net: **+17,877,400** ≈ **+18.8%/yr**, net Sharpe ≈ **1.10**
- Validation net: **+12,701,700** ≈ **+19.8%/yr**, net Sharpe ≈ **1.14**, MaxDD ≈ **-25%**
- Gross exposure ≈ 6–7× notional, vol-targeted to ~15–17% annualised
- Cost stress (1.0×/1.5×/2.0×) and roll stress (1.0×/2.0×): still clearly positive
- Parameter stability (± one predeclared neighbour): positive, non-fragile

## Verification

- Independent verifier (builder ≠ verifier) reconstructs contract eligibility,
  roll schedule, signal, weights, traded contracts and PnL from raw data:
  **VERIFICATION = PASS**, discovery matches to <1e-6, validation within ~3%.
- FALSE_SUCCESS = **0** (all 12 triggers checked).

## PROJECT KPI

```
Executable validated edges = 1 / 1     (EXECUTABLE_VALIDATED_EDGE_COUNT 0 -> 1)
Robust edges               = 0 / 1
Paper candidates           = 0 / 1
Forward profitable         = 0
Live profitable            = 0
```

P2 FUTURES_CURVE_CARRY remains **AUTHORIZED_WAITING**; P2 data reuse = **HIGH**
(individual chains with multiple maturities preserved).

## Limitations

- CLOSE fidelity: shorter, differently-sourced sample than the source.
- Sample ends ~2000 → HOLDOUT = FUTURE_ONLY (a fresh forward window is required).
- Equity-index sleeve is a single market (`sp`); the archive lacks a second
  liquid equity index.
- Discrete integer contracts require a larger research capital to avoid zeroing
  high-notional markets.
- The free-archive licence is unclear; used for research only.

NEXT = **PAPER_CANDIDATE_CERTIFICATION** (no live capital).
