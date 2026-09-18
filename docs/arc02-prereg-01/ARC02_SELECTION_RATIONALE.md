# ARC02_SELECTION_RATIONALE.md

> Why each frozen number and rule was chosen, what was deliberately NOT chosen, and the
> evidence basis of every decision. Every choice below is justified by mechanism, statistical
> convention, data cadence or project governance — **never** by returns. No economic
> observation exists for ARC-02 at the time of writing.

## 1. Starting point: the prior ARC-02 definition

The historical candidate design lives (uncommitted, untracked) at
`docs/arc02-candidate-design-01/`:

| Artifact | Status |
| --- | --- |
| `ARC02_DRAFT_SPEC.json` | `DRAFT_NOT_PREREGISTERED` |
| `ARC02_DRAFT_MANIFEST.json` | `DRAFT_NOT_FROZEN`, `data_authority: PENDING` |
| `ARC02_DATA_MANIFEST_V1.json` | 2024-only partitions, dataset `2a91ed26…ceed` |
| `07_ARC02_PIT_CONTRACT.md` | narrative sketch |
| `FINAL_REPORT.md` | `BLOCKED_ARC02_DATA_AUTHORITY` |

`git log --all --grep=ARC02/ARC-02 -i` returns **nothing**: no committed ARC-02 economic
definition exists. The draft is therefore classified `DRAFT_ONLY` (not
`FROZEN_PREVIOUSLY`), and the spec below re-freezes the definitions explicitly, recording
every deviation from the draft. No contradiction had to be resolved from performance,
because no prior committed authority existed.

## 2. Data: reuse first, and full common history over a convenient window

An audit of every price authority in the repository found the certified **ARC-03 5m Binance
USD-M kline authority** (`ARC03-DATA-001`: 237 CHECKSUM-verified archives, 701,280 rows for
BTC/ETH and 627,180 for SOL, 2020-09-14 → 2026-08-31, independently verified PIT battery
28/28). ARC-02 needs exactly BTC/ETH/SOL 5m OHLCV.

* classification **REUSABLE**, proved by partition SHA256 equality, not asserted;
* the 2024-only draft inventory was classified **REUSABLE_WITH_LIMITATION** and then
  **superseded**: §10 of the mission forbids using a convenient 2024-only window when a
  broader official authority is reusable without contamination;
* result: **full common causal history, zero downloads, zero credentials, zero cost**.

The window start `2020-09-14T07:00:00Z` is the SOLUSDT admission date — a provider-availability
fact, not an economic choice. Span `2177.7083333333335` days is a frozen constant used by G5.

## 3. Field projection instead of the whole authority

ARC-02 consumes a projection carrying only `t, ct, o, c`. `h`, `l`, `v`, `qv`, `n`, `tb`, `tq`
are physically dropped, which makes the structural separation from H5 (taker-flow) and ARC-03
(volume record) *impossible to violate* rather than merely promised.

## 4. Shock definition

| Field | Frozen value | Basis |
| --- | --- | --- |
| return | `ln(c_t / c_{t-1})` | scale-free; symmetric; the natural transmission statistic |
| lookback | 288 bars | exactly one day of 5m slots — the shortest lookback spanning an intraday cycle |
| minimum observations | 288 (all) | the project's fail-closed convention: no partial window, no synthesis. **Deviates from the draft's 144** |
| location | NONE (zero by construction) | avoids a second estimated parameter with no mechanism justification |
| scale | median of the 288 trailing absolute returns | heavy-tailed returns: a variance-based scale would be inflated by a single outlier and would suppress the very events the mechanism is about |
| even-count median | mean of the two central order statistics | lookback is even; the convention is stated rather than inherited from a library |
| threshold | `|z| > 3.0` (STRICT) | extreme-value convention for a robust standardised deviation, fixed ex ante; equality is not a shock |
| zero scale | `NO_SIGNAL / LEADER_SCALE_ZERO` | fail closed; a zero scale carries no information |
| missing history | `NO_SIGNAL / LEADER_HISTORY_INCOMPLETE` | fail closed |

The draft's `lookback 288` and `threshold 3.0` are adopted; its `minimum_observations 144` is
superseded because partial-window admission would make the scale window — and therefore the
signal — depend on incidental data availability.

## 5. Follower underreaction

Frozen: `SAME_SIGN(t) AND |r_f(t)| < 0.5 * |r_btc(t)|`, strict. The draft's `0.5` is adopted.
Rationale: the claim is that the follower *has not yet* repriced proportionally; half the
leader's move is the minimal statement of that, and a follower that kept up (ratio ≥ 1) or is
at exactly half is not underreacting. Boundaries are strict on both the shock and the ratio
because inclusive boundaries would admit the degenerate "follower matched the leader" case.

Zero follower return ⇒ `NO_SIGNAL / FOLLOWER_NO_SAME_SIGN_RESPONSE` (a zero return has no
sign, so it cannot express same-direction continuation). Counter-moving follower ⇒
`NO_SIGNAL`, never a reversal trade.

## 6. Decision slot, entry, exit

* **Alignment:** the leader and follower bars must share the same `bar_open_time_ms`; a
  mismatch is a `BAR_ALIGNMENT_FAILURE` (fail closed).
* **Decision time:** `max(leader close, follower close)` — the first instant at which the
  complete signal is knowable.
* **Entry:** the OPEN of the next 5m bar of the traded follower. Never the signal bar.
* **Exit:** the OPEN of the bar 5 minutes later. **Deviates from the draft's "exit at that
  bar's close"**, which mixes an open-anchored entry with a close-anchored exit. The project's
  certified execution convention identifies the exit bar by clock arithmetic from the entry
  anchor only, so an open→open hold of 1 bar is used. Hold length is unchanged (one 5m bar);
  only the price basis is made consistent.
* **Stop / cooldown / take-profit:** NONE. Nothing in the mechanism justifies a stop, and a
  stop would need a volatility parameter that the mechanism does not define.
* **Overlap:** SKIP. **Re-entry:** only after the previous exit. **Concurrency:** ≤ 1 per
  follower, ≤ 2 overall; the leader is never traded.

## 7. Costs and funding

* `PRIMARY_ROUND_TRIP_COST_BPS = 10` (ARC-01/ARC-03 house standard, plus 0/20/40 scenarios on
  the IDENTICAL trade set). Adopted from the ARU queue text ("10bps").
* Funding: **frozen and charged**, deviating from the draft's `EXCLUDED_WITH_LIMITATION`. The
  holding period is 5 minutes and BTC/ETH settle every 8h (≈1 in 480 slots), with SOLUSDT on a
  2h/4h schedule in 2022-11, so a hold can straddle a settlement. Funding is never a signal;
  it is a cashflow over `(entry, exit]` only, and G3 (ex-funding expectancy) guarantees ARC-02
  cannot pass merely by collecting carry.

## 8. Statistical gates: the ARC-03 standard, with ONE structural adaptation

G1–G11 are adopted from `ARC03_STATISTICAL_GATES.json`, with every convention stated in full.
The single adaptation is **G9**: ARC-01/ARC-03 froze a "≥ 2 of 3 assets positive" rule for a
three-traded-asset experiment. ARC-02 trades exactly **two** followers, where a majority rule is
degenerate (1-of-2 would admit exactly the single-asset effect the ARU kill rule forbids), so
G9 requires **BOTH** followers to be positive. Concentration is likewise adapted: with two
followers the equal split is 0.50, so ARC-03's 0.60 bar is not mechanically transferable and
`max_follower_share ≤ 0.70` is frozen (refusing an edge that is in substance one follower while
admitting a legitimate 60/40 split). Month (0.40) and single-trade (0.25) bars are unchanged.

## 9. Controls

Four executable, deterministic falsification controls — DIRECTION, TIMING (+1 bar, the only
causal direction), LEADER (leader series displaced 288 bars, destroying contemporaneous leader
information while leaving every follower execution semantic identical), NULL (seeded sign flip,
`random.Random(20260915)`, never `hash()`). Their executability and causality are proved by
structural PIT checks on synthetic fixtures; they are NOT executed economically at this stage.

## 10. Robustness

Frozen, never executed, and incapable of choosing a replacement primary cell: time splits,
follower splits, regimes, cost curve, and explicit *neighbourhoods* around the frozen lookback
(144/288/576/864), threshold (2.5/3.0/3.5/4.0), ratio (0.33/0.50/0.67/0.80) and holding
(1/3/6/12), plus leave-one-follower-out, walk-forward with no refitting, and concentration.

## 11. What was deliberately NOT done

* no parameter sweep, no performance-ranked anything, no signal-vs-return analysis;
* no signal generation on real data (not even a structural count);
* no use of ARC-01/ARC-03/H1/H3/H5/H6 outcomes to choose any ARC-02 number;
* no modification of H1/H3/H5/H6/ARC-01/ARC-03 or any protected runtime component;
* no auto-merge of unrelated worktrees.
