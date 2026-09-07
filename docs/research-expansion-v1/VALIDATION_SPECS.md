# RESEARCH-EXPANSION-V1 — Validation Methodology Specs

These are **methodology improvements** (evaluation infrastructure), not alpha
strategies. They change how candidates are *judged*, never what is *traded*.
None of them may modify the frozen POC01 runtime, RiskManager, sizing, fees,
or slippage. They map to STRATEGY_CANDIDATE-03/04/05/06/08 in
`STRATEGY_CANDIDATES.md` and are the "SPEC" stage of the §23 pipeline.

---

## VALSPEC-001 — Purged / Embargoed Cross-Validation (STRATEGY_CANDIDATE-08)

**Problem.** K-fold CV shuffles time; overlapping 5m windows leak information
across folds, inflating ML-style validation scores.

**Spec.**
- Split the labeled sample into contiguous time blocks.
- For fold *i*: train on all blocks except *i*, **purge** from the training
  set any sample whose label horizon overlaps block *i*, and **embargo**
  `H_embargo` bars after block *i* ends (default: label horizon + 1 bar).
- Report per-fold net expectancy R and net PF; aggregate as mean ± std.
- Acceptance for any future ML candidate: min per-fold net expectancy R > 0
  AND worst-fold net PF > 1.0 AND fold dispersion (std/|mean|) < 1.0.

**Inputs.** Labeled datasets built ONLY from windows legally available to the
consuming checkpoint (legacy window is CONSUMED_DEVELOPMENT and stays
ineligible for training — fail-closed).

**Tests.** Synthetic dataset with a known leak: unpurged CV must show the
leak (score inflation) and purged CV must not; boundary conditions at
dataset edges; horizon=1 degenerate case.

---

## VALSPEC-002 — Walk-Forward Evaluation Harness (STRATEGY_CANDIDATE-05)

**Problem.** Single-split backtests hide parameter decay over time.

**Spec.**
- Anchored or rolling walk-forward: train window `W_tr`, test window
  `W_te = W_tr / 3`, step = `W_te`. No overlap between train and test.
- All parameters are frozen BEFORE the first fold (pre-registered config);
  the harness may NOT re-tune inside the loop. Re-tuning is a new
  HYPOTHESIS_ID under the EDGE-RESEARCH preregistration rules.
- Metrics per fold: N, net expectancy R, net PF, max DD; plus aggregate
  OOS-only curve (concatenated test windows, no in-sample mixing).
- Acceptance: OOS net expectancy R > 0 across >= 2/3 of folds AND aggregate
  OOS net PF > 1.0 AND no fold with N < 30 unless declared INSUFFICIENT_SAMPLE.

**Tests.** Deterministic fixture with a regime flip mid-series: an honest
harness must show the decay; boundary tests for W_tr/W_te/step consistency;
assert OOS curve timestamps are strictly increasing and disjoint.

---

## VALSPEC-003 — Meta-Labeling Experiment (STRATEGY_CANDIDATE-06)

**Problem.** Existing proposals carry false-positive rate; a learned
trade/no-trade filter could improve expectancy without touching sizing.

**Spec.**
- Primary signal: EXISTING runtime proposals (Momentum/Trend/Breakout/
  MeanReversion/Volatility) — never a new signal source.
- Meta-model: logistic regression / gradient boosting on features available
  PIT at proposal time (regime, vol bucket, session, time-since-loss,
  proposal confidence, counter-evidence count).
- Labels: outcome of the proposal evaluated under canonical PaperBroker
  accounting (net R), from **confirmation-window or later data only**.
  Discovery/legacy windows are excluded from training (fail-closed).
- Evaluation: purged CV (VALSPEC-001) + walk-forward (VALSPEC-002); report
  lift in net expectancy R vs unfiltered baseline with CIs.
- Authority: the meta-model outputs a FILTER FLAG consumed by evaluation
  tooling only. It MUST NOT enter DecisionEngine, RiskManager, or sizing.
  If ever promoted, promotion happens through a new checkpoint with its own
  gates, never silently.

**Tests.** Leakage probes (feature computed with future data must be
detected and rejected); label-availability guard (proposals without resolved
outcome are excluded, not imputed); baseline-parity test (filter off ==
current behavior).

---

## VALSPEC-004 — Freqtrade-Style Protection Gates (STRATEGY_CANDIDATE-03)

**Problem.** Post-loss sequences currently produce RISK_REJECT via
CONSECUTIVE_LOSS_COOLDOWN (observed 12/71 rejects in POC01); community
practice adds complementary guards.

**Spec.** Candidate gate patterns, each an OBSERVATIONAL experiment first:
- `cooldown_after_loss`: N minutes pause on a symbol after a losing close.
- `stop_duration_guard`: pause entries for T minutes after K consecutive
  losses on the same symbol (generalization of the existing cooldown).
- `max_drawdown_lock`: halt new entries when campaign drawdown exceeds a
  pre-registered threshold (already partially covered by RiskManager —
  spec only if a gap is demonstrated).

**Hard constraint.** Gates are PROPOSAL-level filters evaluated BEFORE
RiskManager; they never modify RiskManager, sizing, fees, or slippage. Any
adoption requires: pre-registered config, replay over the completed POC01
campaign data (shadow), and a dedicated checkpoint. They are NOT part of the
frozen POC01 window.

**Tests.** Shadow-replay parity (gate ON vs OFF trade sets differ only by
gated entries); zero-trade edge case; interaction test with
CONSECUTIVE_LOSS_COOLDOWN (no double-punishment loops).

---

## External-source check (§21 continuation)

Audited for orthogonal patterns this checkpoint: **none added**. The 12
registered sources already cover the orthogonal families identified
(paritharness, walk-forward, meta-labeling, protection gates, robustness
tooling). New source additions require a pattern not represented above;
collecting repositories for quantity is explicitly avoided.
