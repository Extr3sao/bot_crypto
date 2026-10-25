# RFC-049 DISCOVERY 2 — RUN REPORT

| | |
| --- | --- |
| **phase** | B — DISCOVERY 2 / DEV-VAL (authorized offline scope only) |
| **head start** | `2d113a0ae82f38123eabe0385ab47bb7991b15ad` (branch `main`) |
| **mode** | OFFLINE RESEARCH — read-only frozen inputs; no keys, no orders, no capital, no process started |
| **authorization** | ADR-0025 + [CAMPAIGN_AUTHORIZATION.json](CAMPAIGN_AUTHORIZATION.json) — scope `OFFLINE_DEV_VAL_ONLY` |
| **sealed OOS** | **CLOSED** (opens only at its gate: 20 closed round trips or 24 months after the freeze) |
| **FALSE_SUCCESS** | **0** |

## Steps, commands and real exit codes

| step | command | exit | result |
| --- | --- | ---: | --- |
| RFC-049B verifier re-run | `python scripts/rfc049b_verify.py` | 0 | PASS 66/0, 12 controls, FALSE_SUCCESS 0; only its own artifact updated (DEF-01 correction) |
| DEV/VAL engine | `python scripts/rfc049c_engine.py --trades` | 0 | 28 checks, 0 failed; RFC-049B counts reproduced exactly; PIT violations 0 |
| independent verifier | `python scripts/rfc049c_verify.py` | 0 | **PASS 37/37; 8/8 negative controls DETECTED; FALSE_SUCCESS 0** |
| filter ablation | `python scripts/rfc049c_ablation.py` | 0 | base reproduces the engine's trend comparator; **NOT_ADOPTED** |
| ACTIVE audit | `python scripts/rfc049c_active_audit.py` | 0 | 24 strategies, 0 admitted; 0 executed operations |
| tests | `python -m pytest tests/unit/research -q` | 0 | **1703 passed** (incl. 15 new contract tests) |

## What the experiment measured (RESEARCH_EXPOSED; non-confirmatory)

Round-trip cost: **23.353553391 bps** (COST_MODEL_V3 at 200 USDT; 1.5x stress 35.030330086).

| candidate | asset | partition | trips | net sum (bps) | compounded | LCB 95% (bps) | max DD | vs B&H (bps) | vs 200d trend (bps) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H-049-001 | BTC | development | 14 | +39,427.5 | +1,035% | +659.0 | 51.4% | +2,377 | +48,860 |
| H-049-001 | BTC | validation | 9 | +623.5 | −1.1% | **−619.9** | **27.9%** | **−9,788** | **−761** |
| H-049-001 | ETH | validation | 9 | −2,409.6 | −35.1% | −1,329.7 | 50.0% | −5,759 | −2,971 |
| H-049-002 | BTC | development | 26 | +40,175.6 | +1,286% | +380.3 | 14.4% | +27,450 | +73,933 |
| H-049-002 | BTC | validation | 22 | +1,632.4 | +3.9% | **−293.6** | **35.2%** | **−9,281** | **−254** |
| H-049-002 | ETH | validation | 22 | −1,968.9 | −36.1% | −599.2 | 52.2% | −5,865 | −3,077 |

Both candidates are **`CANDIDATE_REJECTED`** at the DEV/VAL stage: on the validation
partition the bootstrap LCB is negative, the drawdown exceeds the frozen 25% limit, and
neither candidate beats buy-and-hold or the 200-day trend baseline; H-049-001 is also
sign-unstable and its live single-trade concentration breaches the 40% limit. The
development-era result (2019–2023) is large and survives the 1.5x cost stress, but the
effect decays to nothing once BTC matures (2024–2026) — exactly the trend-proxy collapse
the frozen specs name as a known failure mode.

## Eligibility (FASE 2)

At the measured turnover, the sealed OOS gate is unreachable inside its 24-month window:
H-049-001 expects **5.9** round trips (81.0 months to 20), H-049-002 expects **12.4**
(38.8 months to 20). Promotion as independent strategies is **stopped** for both; the
20-trip floor was not lowered and no threshold moved.

## Filter ablation (FASE 4 — diagnostic)

Gating the declared 200-day trend machine with the liquidity states **reduced** net results
in most partitions (e.g. base+both: −26,614 bps development, −1,606 bps validation) while
reshaping most base trades; drawdown improved only for base+both development (−6.6 pp).
**Nothing is adopted**, and the adoption question itself is blocked: no ACTIVE strategy
exists today to filter, and adoption would require forward reproducibility per the
operator's rule.

## ACTIVE pipeline (FASE 5)

24 strategies (17 `NO_GROSS_EDGE`, 7 `COST_KILLED`), **0 admitted**, 0 paper-executable on
5m/15m/1h, 0 executed operations; best measured family gross edge 8.91 bps/trade against
the 23.353553391 bps round trip. The objective of 3 operations/day is assessed
**NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE** — it would cost ~255.7% of stake per
year in round trips before any edge. No operation is generated to satisfy a quota. The
operator label `R6 P2 QUALITY` does not exist as a repository artifact; the low-frequency
liquidity line stays separate and untouched.

## Controls not executed (recorded, not hidden)

- **Sealed OOS opening** — closed by contract; with both candidates rejected the opening
  is moot. Resolved after this run by ADR-0026: **`CANCELLED_NOT_OPENED`** — retired unused,
  never read (see [CAMPAIGN_CLOSURE.md](CAMPAIGN_CLOSURE.md)).
- **Paper promotion / live trading** — never in scope; `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`.
- **Macro primary-source refetch** — performed by RFC-049B; Phase B consumes frozen snapshots.

## Defects

- `RFC049C-DEF-01` — RFC-049B's committed `INDEPENDENT_VERIFICATION.json` carried two stale
  `FINAL_ADMISSION_REPORT` hashes (recorded before its own stamp rewrote the files);
  corrected by the re-run. Bookkeeping only, no economic or PIT consequence.

## Success labels (kept distinct)

`IMPLEMENTED`: engine/verifier/ablation/audit/tests · `TESTED`: 1703 passed ·
`EXECUTED`: DEV/VAL + robustness + ablation + audit (offline) ·
`VERIFIED`: 37/37, controls 8/8, FALSE_SUCCESS 0 ·
**`CERTIFIED`: nothing — certification requires the sealed OOS, which is closed.**

## Campaign closure (after this run)

ADR-0026 declares the terminal state `DISCOVERY_CAMPAIGN_FAILED` (ST-2) and resolves the sealed
OOS opening as `CANCELLED_NOT_OPENED`; `NEXT_CAMPAIGN` returns to `NOT_AUTHORIZED` and the
hypothesis budget is `EXHAUSTED_NO_REFILL`. The record, the candidate-by-candidate rejection
reasons and the inspection accounting are in
[CAMPAIGN_CLOSURE.md](CAMPAIGN_CLOSURE.md) / [CAMPAIGN_CLOSURE.json](CAMPAIGN_CLOSURE.json).
Nothing above this line changed: the run is reproduced exactly as executed.
