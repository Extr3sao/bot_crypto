# BUSINESS REENTRY CHECKLIST

One page to decide in minutes whether a new source deserves a research
cycle. If any answer below is NO, the answer is **NO_ACTION**.

## 1. Is this a valid event? (RFC-044 §5-§6)

- Is it a new external publication/replication, a new structural
  mechanism, a material capital change, a material instrument/broker
  change, or new data that unlocks an already-supported hypothesis?
- If it is a new indicator, a different moving average/threshold/symbol,
  more agents, an LLM prediction, ML on old features, a renamed family,
  parameter tuning or a social-media claim alone -> **reject**.

## 2. Source quality (RFC-044 §11-§13)

- Grade the source: A peer-reviewed, B working paper/institutional,
  C implementation, D blog/social.
- C or D alone never opens research. Prefer >= 2 independent A/B sources.
- Did the effect SURVIVE post-publication, or is it WEAKENED/DECAYED/
  CONTRADICTORY/UNKNOWN? Prefer SURVIVES.

## 3. Duplicate check (RFC-044 §14)

- Is this economically the same family already in CANDIDATE_ARCHIVE?
  If yes -> SAME_FAMILY_REHASH -> **reject**.

## 4. Profitability first (RFC-044 §4/§34-§35)

- WHY COULD THIS MAKE MORE MONEY PER UNIT OF RISK THAN THE PASSIVE
  ALTERNATIVE? If there is no evidenced answer -> **reject** before code.
- What is the PRIMARY_PASSIVE_BENCHMARK (and RISK_MATCHED_BENCHMARK)?
- Is the claim RETURN/RISK relative to the benchmark *after costs*, not a
  raw return number?

## 5. Capital contract (RFC-044 §7-§8/§33)

- Can it be faithfully executed with 200 USDT (fractional, low minimum
  notional, low turnover, no mandatory leverage/short/borrow, low data
  cost)? If not, only a material capital change (trigger C) reopens it.

## 6. Critical gates (RFC-044 §18) — none can be compensated

- evidence >= 3, business plausibility >= 3, capital fit >= 4,
  tradability >= 4, data feasibility >= 3.

## 7. Cheap falsification (RFC-044 §15-§16)

- Write the FASTEST_KILL_TEST now, using only external evidence,
  arithmetic, product rules, cost estimates or data feasibility.
- No backtest is allowed at this stage.

## 8. Reentry gate (RFC-044 §22-§23)

- G_BUSINESS_REENTRY = PASS only if VALID_TRIGGER AND MATERIALLY_NEW AND
  STRONG_EVIDENCE AND PRODUCT_FIT AND CAPITAL_FIT AND TRADABILITY AND
  DATA_FEASIBLE AND BENCHMARK_CASE AND CHEAP_FALSIFICATION_DEFINED.
- The normal answer is FAIL, and at most ONE candidate is ever authorized.

## 9. Log the decision

- Record the review in REENTRY_DECISION_LEDGER (review_id, date,
  opportunity, trigger, decision, reason) and any evidence in
  REENTRY_EVIDENCE_REGISTRY.
