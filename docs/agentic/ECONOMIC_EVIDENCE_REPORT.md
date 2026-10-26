# ECONOMIC_EVIDENCE_REPORT — what the numbers actually establish

**Date:** 2026-10-21 · **Scope:** the economic chain `EXP-003J/K/L/M/N`, the `WP-EDGE` family, the `ALPHA`
family, and the `ECONOMIC-001` cost gate.
**Rule observed:** a number is *re-derived* only when this session recomputed it. Everything else is marked
**reported**.

---

## 1. The claim under audit

The repository's own standing position, before this mission:

> no strategy has been shown to earn more than its round trip; `PROFITABILITY_VERIFIED=false`;
> `TRADES_AUTHORIZED=0`; the discovery campaign is `FAILED`.

That is an unusual claim to audit, because it is a *negative* and the temptation is to accept it lazily. It was
audited by asking the opposite question: **is there any experiment in this checkout whose numbers, if they
survived independent recomputation, would overturn that claim?** The answer is no, and §2 is the reason the
one experiment that could have been quoted as "verified" actually is verified.

## 2. `EXP-003N` — independent reproduction of the verifier

### 2.1 The first attempt refuses, correctly

```
$ ./.venv/Scripts/python.exe scripts/exp_003n_verify.py --negative-controls
[003n-verify] REFUSED — SEAL.json exists; a sealed experiment is not re-verified in place
exit 4
```

The verifier refuses to run against the sealed tree. That is a property, not a problem: a verifier that can
rewrite the artefact it verifies is not a verifier. The reproduction therefore runs against a **copy** with the
seal excluded, and against a **clean worktree** so the code is `HEAD`, not this dirty working tree.

### 2.2 The authoritative run — clean worktree at `277d1df`

```bash
git worktree add --detach "$TMP/003n-head" 277d1df
# dataset bytes are outside Git by design: copy the three frozen files in
cp reports/ai-bots/EXP-003K-CANDIDATE-001/dataset/* "$TMP/003n-head/reports/ai-bots/EXP-003K-CANDIDATE-001/dataset/"
cp -r reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 "$TMP/003n-head/reportcopy"
rm -f "$TMP/003n-head/reportcopy/SEAL.json"          # the copy, never the original
cd "$TMP/003n-head"
./.venv/Scripts/python.exe scripts/exp_003n_verify.py --negative-controls \
    --out "$TMP/003n-head/reportcopy" --json-out "$TMP/003n-head/clean_verify.json"
```

Result — **re-derived**, exit `0`:

```
[003n-verify] PASS V1_dataset_provenance: 3 files, drifted=[]
[003n-verify] PASS V2_config_frozen: 3 config digests
[003n-verify] PASS V3_design_binding: design sha256 a0776fa3fbe6d2e1…
[003n-verify] PASS V4_holdout_closed: 0 rows at or after 2026-08-06T00:00:00Z; partitions inside=True
[003n-verify] PASS V5_forward_returns_recomputed: 6692 values compared from raw bars, 0 mismatched
[003n-verify] PASS V6_means_consistent: 72 symbol cells, 0 inconsistencies
[003n-verify] PASS V7_multiple_testing: 1 surviving cells; builder=1
[003n-verify] PASS V8_cost_subtracted: costs={'BTCUSDT': 24.786, 'ETHUSDT': 24.786, 'SOLUSDT': 27.31}, 0 defects
[003n-verify] PASS V9_closed_trade_view: 24 cells priced; unpriced=0; censored=0
[003n-verify] PASS V10_no_promotion: paper/live authorisation untouched
[003n-verify] PASS V11_verdict_from_numbers: 0 advanced candidates
[003n-verify] PASS V12_runtime_paper: mode=paper live_enabled=False
[003n-verify] DETECTED tampered_forward_return: breakout/1h/BTCUSDT shifted by +50 bps
[003n-verify] DETECTED holdout_injection: a row at 2026-08-10T00:00:00Z is outside every allowed partition
[003n-verify] DETECTED cost_omitted: 6 cells would pass a zero-cost gate and fail the real one
[003n-verify] DETECTED false_success: a negative-net cell relabelled ADVANCE is contradicted by its own number
[003n-verify] DETECTED multiple_testing_inoperative: q=1.0 keeps 84 vs 1 at q=0.1
[003n-verify] DETECTED dataset_byte_append: an appended byte changes the digest the design froze
[003n-verify] DETECTED sample_gate_inflated: the smallest IS cell has 0 signals; the gate is 20
[003n-verify] DETECTED verdict_contradicts_gates: 0 cells claim a state their gates deny
[003n-verify] DETECTED cost_below_floor: min round trip 24.7864 bps vs floor 20.0 bps
[003n-verify] DETECTED closed_trade_recomputed: 35 closed trades recomputed here, 0 mismatched
[003n-verify] 12/12 checks, 10/10 controls, verdict=PASS
```

**Field-identical to the published artefact — re-derived:**

```
checks identical   : True
controls identical : True
summary            : {'checks': 12, 'controls': 10, 'controls_detected': 10,
                      'failed': 0, 'false_success': 0, 'passed': 12}
verdict            : PASS
```

### 2.3 What this does and does not prove

| Proven | Not proven |
| --- | --- |
| the published `VERIFICATION.json` is reproducible from `HEAD` + the frozen bytes | that the verifier is a **person**; `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON` stands |
| the ten negative controls fire, so the checks are not vacuous | that the *screening* programme was correct — only that its output is internally consistent |
| no row, signal or statistic exists at or after `2026-08-06` in N's own outputs | that the window was never read by anything else: **it was, by `EXP-003K`** |
| the 24 cells are priced, uncensored, and none is `ADVANCE` | that the rejection generalises beyond BTC/ETH/SOL over 46 days |

The reproduction was performed twice — once in the dirty working tree, once from a detached worktree at
`277d1df` — and both produced the same twelve checks and ten controls. Only the second is quoted as evidence.

## 3. What `EXP-003N` measured

Partitions (frozen in `design/DESIGN.json`, re-read today): `IS 2026-06-21→07-11`, `VAL 07-11→07-26`,
`TEST 07-26→08-06`, holdout `08-06→08-20` **CLOSED**. Universe: 6 families × 3 assets × 3 timeframes, 24
symbol cells, **114** statistical tests at BH q = 0.10, sample gate 50/20/15.

| Outcome | Count |
| --- | --- |
| `REJECT` | **13** |
| `INSUFFICIENT_EVIDENCE` | **10** |
| `EXPERIMENT` | **1** |
| `ADVANCE` | **0** |

The single BH survivor, `lane_a::trend::4h::48` (p = 9.999e-05 against a threshold of 8.77e-04), is also the
`EXPERIMENT` verdict — and its numbers are the most important in the repository:

| Statistic | Value |
| --- | --- |
| IS mean forward return | **+10.52 bps** |
| VAL mean forward return | **+14.80 bps** |
| Full round trip (BTC/ETH) | **27.31 bps** |
| Net per signal at VAL | **−12.51 bps** |
| Closed-trade mean, full net | **−186.68 bps** over 140 trades |

A statistically detectable signal exists, and it is worth **roughly half of what it costs to trade it.**
Everything else in the repository is consistent with this one line.

## 4. The cost barrier, measured across four independent families

| Experiment | Best gross measured | Toll | Gross / toll | Net |
| --- | --- | --- | --- | --- |
| `EXP-003N` trend 4h | 14.80 bps (VAL) | 27.31 bps | **0.54×** | −12.51 bps/signal |
| `ALPHA-003` lead-lag L1 15m | 1.87 bps | ~23.6 bps | **0.08×** | −21.93 bps |
| `ALPHA-002` TSMOM + flow | −0.39 bps | ~23.8 bps | **< 0** | −24.18 bps |
| `NEG-A1-04` cross-sectional reversal | +15.71 bps | 23.56 bps | **0.67×** | negative |
| `EXP-003M` maker fill, 5m/mean_reversion | +0.2669 USDT/fill | 0.75 USDT/fill fee | **0.36×** | −0.4831 USDT/fill |

Five measurements, four families, two independent cost models, one conclusion: **the gross edge sits between
0.08× and 0.67× of the toll.** No cell in this repository has ever shown gross ≥ toll.

`ECONOMIC-001` explains why the horizon cannot rescue it. Median absolute move against a frozen 23.8 bps toll:

| Horizon | Median \|move\| | × toll | Sufficient |
| --- | --- | --- | --- |
| 5m (scalping) | 8.59 bps | 0.36× | false |
| 1h (intraday) | 29.38 bps | 1.23× | false |
| 4h (mean reversion) | 60.47 bps | 2.54× | false |

At 4h the *market* moves 2.54× the toll, but the *signals* tested capture 0.54× of it. The gap is not in the
market; it is in the predictability, and it is large.

## 5. Robustness: what was actually stress-tested

| Technique | Where | Result |
| --- | --- | --- |
| moving-block bootstrap, 10 000 rounds, declared seed | 003J (175 OOS), 003L, 003M | all lower bounds negative |
| multiple-testing correction | 003N BH q=0.10 over 114 tests; ALPHA-001 BH+Holm over 106 variants | 1 survivor (N); 0 survivors (ALPHA-001) |
| cost stress 1.5× / 2.0× | 003L — **re-prices a fixed trade set** rather than re-running it | declared as a limitation, not an independent measurement |
| fill-model stress (touch vs tape vs queue sweep) | 003M, 4 scenarios | net negative in all four |
| embargo between partitions | 003K 24 bars, 003N partitions | enforced, not merely declared |
| walk-forward / rolling re-estimation | **nowhere** | **absent from the entire repository** |
| per-config drawdown limit enforcement in the verdict | reported (2.0–5.1 %) but **not a rejection criterion** | weak |
| regime coverage of the rejections | 003L reports `by_regime: {"unknown": 339}` | effectively **unmeasured** |

The two absences are material. Every rejection here rests on a single fixed parameterisation measured once;
none has been re-estimated on a rolling basis, and none reports per-regime behaviour because the regime label
is `unknown` in the one place it was attempted.

## 6. Evidence integrity

| Experiment | Sealed | In Git | Verifier runs from a clean checkout |
| --- | --- | --- | --- |
| `EXP-003M` | ✅ `SEAL.json` | ✅ | reported (13 checks, 8/8 controls) |
| `EXP-003N` | ✅ `SEAL.json`, `sha256sum -c` **29/29** | ✅ 31 files | ✅ **re-derived by this mission** |
| `EXP-003K`, `EXP-003L` | `SHA256SUMS.txt` present | ✅ | reported |
| `EXP-003J` | `SHA256SUMS.txt` present | ❌ **untracked** | reported (PASS) |
| `WP-EDGE-07` | `VERIFICATION.json` + sabotage suite | ✅ | reported (13/13, 14/14 sabotages) |
| `ECONOMIC-001` | `EVIDENCE_CLOSURE.json` + history hash | ✅ | reported `builder_equals_verifier: false` |

`EXP-003J` is the weak link: a complete, verified, negative run that a clean checkout cannot see. It does not
change any conclusion — it is a *negative* — but it is exactly the failure mode that made `EXP-003N` look
unpublished at `cd3fc31`.

## 7. Spent windows — the ledger that must not be forgotten

| Window | Read by | Consequence |
| --- | --- | --- |
| `2026-06-21 → 2026-08-06` | 003K research, 003L, 003M, 003N IS/VAL/TEST | spent for discovery; every cell on it is known |
| `2026-08-06 → 2026-08-20` | **003K OOS (control + real)**, although 003N left it `CLOSED` | spent; **cannot** be a confirmatory holdout |
| `2026-08-20 → 2026-10-18` | 003J / 003K real arm (175 OOS closes) | spent |
| `2026-03-01 → 2026-10-14` | WP-EDGE-07 `NEW_HOLDOUT` | spent |
| 2021 → 2026, 7 alts, 1h | WP-EDGE-08 | spent |
| `2026-10-08 → 2026-10-22` (ST-6) | **no economic decision has used it** | **unspent**, but quote snapshots only |

## 8. What the evidence does **not** support

- **It does not prove no edge exists in crypto spot.** It proves that no configuration tested here, on these
  three assets, at 5m/1h/4h/daily, in these windows, cleared costs. Those are four dimensions of restriction.
- **It does not statistically reject every family.** `NEG-A1-07` (order flow) was never measured — it failed on
  data availability. `NEG-A1-06` (carry) failed a gate whose reopen condition is a new data window.
- **It does not license a smaller claim either.** A single `ADVANCE`-free screen over 114 tests is not
  evidence of profit; it is evidence of absence of measured profit.
- **The rejections are not independent.** `003J` ≡ `003K`'s real arm (same 505 closes, same −225.401044), and
  `003L`/`003M`/`003N` share the same three dataset files. Counting five experiments is counting one dataset
  family five times.

## 9. Verdict

**`EXP-003N` is verified, closed, and negative — and this mission reproduced that verdict from a clean
checkout rather than quoting it.** The economic position of the repository is unchanged and now better
evidenced: gross edges of 0.08×–0.67× the round trip, in four independent families, with one BH-surviving cell
at half the toll.

The binding constraint is cost. Any hypothesis whose expected gross move is not a multiple of ~25 bps is dead
before it is coded, and no amount of indicator work changes that arithmetic.
