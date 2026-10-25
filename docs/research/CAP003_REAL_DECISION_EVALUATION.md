# CAP-003 — REAL DECISION OUTCOME & ALPHA EVALUATION (frozen contract)

CAP-002 proved the circuit: real Binance bars → causal `MarketSnapshot` →
frozen `MARKET_ANALYST_V1.0` → sealed real decision. It proved nothing about
edge, and it needed two things it did not have: a judge that is not the agent,
and enough decisions to say anything.

CAP-003 adds exactly those, and freezes what follows.

## The question

> Do `MARKET_ANALYST_V1.0` decisions carry **incremental economic value net of
> costs** versus trivial deterministic alternatives?

## Comparison set (CAP-003)

| sleeve | what it is |
| --- | --- |
| **A** | `MARKET_ANALYST_V1.0` — the analyst under test |
| **B** | deterministic rule: `close > SMA(200)` trend **and** `MACD(12,26,9)` momentum **and** `30 ≤ RSI(14) ≤ 70`; otherwise `NO_TRADE` |
| **C** | buy-and-hold over the identical window |
| **D** | random direction with the analyst's **own** `LONG`/`SHORT`/`NO_TRADE` distribution (exact permutation, frozen seed) |

Rule B uses only the repository's existing indicators and the frozen RFC-039
`SMA_WINDOW = 200`; no window, threshold or parameter is ever searched. D is a
distributional comparator, so it is assigned at scoring time and is never baked
into an immutable per-decision evaluation.

These labels are deliberately **distinct** from the CAP-001 evaluator labels
(`A_NO_TRADE` / `B_BUY_AND_HOLD` / `C_SIMPLE_TREND` / `D_PASSIVE_PORTFOLIO`);
the frozen CAP-001 evaluator is untouched.

## Who measures (never the agent)

`DecisionOutcomeEvaluator` is deterministic code. It receives a sealed
`DecisionRecord` plus real `OHLCV` and produces, per decision:

```
decision_id, decision_hash, snapshot_hash, asset, decision_time, horizon,
evaluation_time, observed_at, decision, confidence,
entry_price, entry_close_time, exit_price, exit_close_time, bars_used,
gross_return, costs, net_return, mfe, mae,
direction_correct, invalidation_hit, invalidation_rule,
outcome (WIN/LOSS/FLAT/NO_TRADE), evidence_hash,
evaluator, evaluator_version, source, outcome_hash
```

then `DecisionRecord + DecisionOutcome → DecisionPerformance`, which adds the
seal-time comparators and `evaluation_hash`.

Causality is enforced, not assumed:

* the entry is the close of the last bar that had **fully closed** at the
  decision time;
* the exit is the bar that closes exactly at `decision_time + horizon`;
* a bar after the horizon is ignored, and asking for an outcome before
  `decision_time + horizon` raises `HorizonNotMaturedError`.

## What the evaluator refuses to invent

* **Invalidation.** V1 emits a free-text invalidation, which is not
  machine-checkable. `invalidation_hit` is `None` with rule
  `NOT_MACHINE_CHECKABLE_TEXT_INVALIDATION`; a numeric `invalidation_price` is
  honoured by a price rule declared in code, never chosen after seeing results.
* **Costs.** Agent and active comparators share one `CostModel`
  (10 bps/side → 20 bps round trip, the frozen RFC-039 constant). `NO_TRADE`
  trades nothing and pays nothing.
* **`FLAT`** only when the net return is exactly zero; otherwise the sign decides.

## Reproducibility (required from here on)

A decision is campaign-legal only with complete provenance:

`analyst_id`, `prompt_version`, `prompt_digest`, `model`, `provider`,
`temperature`, `schema_version`, `feature_version`, `dataset`.

`temperature` is a string: a client that does not expose sampling parameters must
record `NOT_EXPOSED` rather than invent a number. CAP-002 artefacts are exempt
and therefore excluded from the campaign.

## Store

`evidence/real_decisions/{decisions,outcomes,evaluations}.jsonl`, append-only,
with the chain `snapshot_hash → decision_hash → outcome_hash → evaluation_hash`
and `replay(decision_id)`. See
[README](../../evidence/real_decisions/README.md).

## Campaign and verdict

* universe `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`; one decision per 4H cycle
  per asset; horizons `4H` / `24H` / `72H`;
* `MARKET_ANALYST_V1.0` stays **frozen** for the whole campaign — no prompt,
  schema or model change after seeing any outcome;
* `NO_TRADE` is a real decision and counts toward the sample;
* `ALPHA_SCORECARD` is reported at checkpoints 20 / 50 / 100, and it will not
  issue an edge verdict below **100** evaluable decisions;
* a positive preliminary verdict at ≥ 100 means *run out-of-sample and
  robustness work*, never a business or profitability claim.

`TRADES_AUTHORIZED = 0`. `G_TV_CONTEXT` stays `NOT_VERIFIED`.
`AGENTIC_DECISION_EDGE` stays `0` until realized evidence justifies otherwise.
