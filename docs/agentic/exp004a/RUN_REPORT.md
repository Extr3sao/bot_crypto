# RUN_REPORT — TAP-EXP-004A-FOUNDATION

**Generated:** 2026-10-21T07:59:18Z · **HEAD:** `d05f8de` · **Branch:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Economic executions:** 0 · **Live orders:** 0 · **Promotions:** 0 · **`FALSE_SUCCESS`:** 0

## 1. What this run proves

| Claim | Result |
| --- | --- |
| The system can accumulate prospectively observed days | **yes — 5 admitted** (1h lane) |
| The count can be sealed and re-verified from the bytes | **yes** — 234 attestations, 702 series digests, 0 error(s) |
| Cost can be measured, not just modelled | **yes at 200 USDT**; no at 500 USDT, where the tape never walked |
| Duplicate experiments are counted once | **yes — 3 independent windows from 4 claims** |
| `EXP-004A` is authorised | **no — gate exit 2** |

## 2. Admission by lane

A day is admissible only if every declared series holds 90 % of its calendar bars **and** every one of
those bars was stored inside its lag bound. The lanes differ because the series start on different days.

| Lane | Series | Intersection epoch | Settled days | Admitted | Remaining to 90 |
| --- | --- | --- | --- | --- | --- |
| `1h` | 3 | 2026-03-01 | 234 | **5** | 85 |
| `15m` | 3 | 2026-10-07 | 14 | **4** | 86 |
| `1h+15m` | 6 | 2026-10-07 | 14 | **4** | 86 |

Admitted days (1h lane): 2026-10-15, 2026-10-16, 2026-10-17, 2026-10-19, 2026-10-20.

### Sealed attestations

| Ledger | Records | Series checked | Verified | Errors |
| --- | --- | --- | --- | --- |
| `data\exp004a\admission_1h.jsonl` | 234 | 702 | yes | 0 |
| `data\exp004a\admission_1h+15m.jsonl` | 14 | 84 | yes | 0 |

## 3. The 235-day figure, decomposed

**Claim:** `data/forward/edge04/coverage.json (a derived file, regenerated on every observer tick)` reports **235** days.

| Quantity | Value |
| --- | --- |
| Days holding any 1h bar | 235 |
| Days complete enough to classify | 234 |
| Dense but backfilled | 229 |
| Prospectively observed, 1h only | **5** |
| Prospectively observed, 1h and 15m | **4** |

Why they differ:

1. 235 counts days with bars; 229 of them arrived after their own close, which makes them history rather than observation
2. the 1h lane admits 5 days; the 15m lane starts on 2026-10-07, so a day requiring both admits 4
3. on 2026-10-15 the 1h series has 22 of 24 bars inside the lag bound (0.9167, admitted) while the 15m series has 79 of 96 (0.8229, refused)
4. no day before a series' own freeze is a forward observation for that series: the 15m corpus ends at 2026-10-07T11:30Z, so 2026-03-01..2026-10-07 is out of sample for 15m and untouched only for 1h
5. EXP-004A requires 90 days; the 1h lane would need 85 more at its current rate and the joint lane 86

**Conclusion.** the 235-day figure is arithmetically correct and evidentially inert: it is a row count over a corpus that is 97.4 % backfilled, and it does not describe 235 days of anything an experiment may use.

## 4. Execution cost, measured

Tape: `data\st6\ST6_OBSERVATIONS.jsonl` — 900 quotes, 896 usable, 14 distinct days.

### At 200 USDT — the size the tape walked

| Asset | Observations | Median bps | p90 bps | Weakest component | Status |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | 224 | **20.001213** | 20.001228 | OBSERVED | MEASURED |
| ETHUSDT | 224 | **20.04082** | 20.04185 | OBSERVED | MEASURED |
| SOLUSDT | 224 | **20.941398** | 20.965018 | OBSERVED | MEASURED |

### At 500 USDT — never walked

| Asset | Median bps (lower bound) | Size status | Status |
| --- | --- | --- | --- |
| BTCUSDT | 20.001213 | DECLARED_SIZE_NOT_WALKED | DECLARED_SIZE_NOT_WALKED |
| ETHUSDT | 20.04082 | DECLARED_SIZE_NOT_WALKED | DECLARED_SIZE_NOT_WALKED |
| SOLUSDT | 20.941398 | DECLARED_SIZE_NOT_WALKED | DECLARED_SIZE_NOT_WALKED |

**Fee dominance.** at the size the tape walked, the round trip is the venue fee plus a spread of a few hundredths of a basis point: the 4.79 bps of spread and slippage the frozen model charges on BTC is not visible in the measurement, and that gap is the whole of the COST-CONFIRM question.

| Asset | Median at 200 USDT | Share of the round trip that is the 20 bps fee |
| --- | --- | --- |
| BTCUSDT | 20.001213 | 0.999939 |
| ETHUSDT | 20.04082 | 0.997963 |
| SOLUSDT | 20.941398 | 0.955046 |

**The frozen rule**, applied without adjustment: `INSUFFICIENT_EVIDENCE` at 200 USDT and `INSUFFICIENT_EVIDENCE` at 500 USDT. 13 days is below the frozen 60-day floor, and the 500 USDT size was never walked; the rule is reported for its arithmetic, not for its verdict.

## 5. Independence

4 experiment claims → **3 independent windows** (overstated by 1).

| Window | Experiments | Same bytes |
| --- | --- | --- |
| 2026-08-06/2026-08-20 | EXP-003J, EXP-003K | yes |

four experiment claims resolve to three independent windows; J and K in particular are one measurement, so a fifth negative result from that pair would be a recount rather than evidence.

## 6. The gate, on the real manifest

| Mode | Decision | Exit | Defects |
| --- | --- | --- | --- |
| `inspect` | INSPECTION_ONLY_NO_RUN | 3 | 0 |
| `authorize` | BLOCKED | 2 | 7 |

Authorize-mode defects:

- `CODE_COMMIT_NOT_ANCESTOR`
- `GIT_NOT_TRACKED:config/preregistrations/EXP-004A.datasets.json`
- `GIT_NOT_TRACKED:config/preregistrations/EXP-004A.json`
- `GIT_NOT_TRACKED:config/preregistrations/EXP-004A.prior_runs.json`
- `RUNTIME_CODE_DIRTY:src/trading_bot/research/execution_cost`
- `RUNTIME_CODE_DIRTY:src/trading_bot/research/prospective`
- `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`

## 7. Identifier

`discover_existing_runs('EXP-004A')` → `[]`. Spent: **False**. The report lives at `docs\agentic\exp004a`, outside `reports/ai-bots`, so producing it does not spend the identifier it prepares.

## 8. Reproduce

```bash
./.venv/Scripts/python.exe scripts/exp004a_foundation.py
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prospective_admission.py \
    tests/unit/research/test_execution_cost_measured.py \
    tests/unit/research/test_prereg_gate_two_phase.py \
    tests/unit/research/test_prereg_gate_escape.py -q
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate --repo . --experiment-id EXP-004A \
    --manifest config/preregistrations/EXP-004A.json \
    --registry config/preregistrations/EXP-004A.datasets.json --mode authorize
```

## 9. Final statement

the infrastructure can watch a day, prove afterwards that it watched it, and price a round trip at the size the tape actually walked. It cannot yet do the last of those at the declared notional, and it has 4 of the 90 days EXP-004A requires, so the experiment is prepared and not authorised.
