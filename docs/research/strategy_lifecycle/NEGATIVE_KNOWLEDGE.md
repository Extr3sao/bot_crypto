# NEGATIVE_KNOWLEDGE — dynamic strategy ecosystem

Append-only record of what did NOT work or is NOT proven. Each entry names what
was tried, what was observed, and what must not be claimed.

## NEG-STRAT-001 — the preregistered promotion gate abstains at small evidence volume

- Tried: EXP-STRAT-DYNAMIC-001 with `minimum_samples=40`,
  `minimum_regime_samples=15`, `minimum_stability=0.5`, PF ≥ 1.0.
- Observed: 0 transitions; every family stayed `SHADOW`; the dynamic arm took 0
  trades on BTCUSDT W1..W7 (5m).
- Must not claim: that the dynamic architecture improves returns. At this
  evidence volume it merely abstains.
- Causes: per-(strategy, regime) samples are split across ≥3 regime cells, and
  the medium rolling window (50) exceeds the per-cell trade count; the family
  stream (~80–200 trades/window) never reaches 40 in one regime cell early
  enough.

## NEG-STRAT-002 — "dynamic net > static net" is not sufficient for PROMOTE

- Tried: comparing DEV+VAL net between arms.
- Observed: with the dynamic arm at 0 trades and the static arm at -74.92, the
  naive comparison says "improved".
- Must not claim: improvement from an abstaining arm. The experiment now forces
  `DO_NOT_PROMOTE` when the dynamic arm takes zero trades.

## NEG-STRAT-003 — a family-level performance store must not re-sort per insert

- Tried: sorting each context bucket on every `record`.
- Observed: O(n²) behaviour that hung a real multi-family run for >45 min.
- Fix: `bisect.insort` with a key. Recorded so the same mistake is not repeated.

## NEG-STRAT-004 — pre-existing defects NOT resolved here

- `DEF-HTF-PIT-001` (ms/s unit bug in `market_data/htf_pit.py`) remains ORPHAN;
  it has no `src/` caller, so it is not elevated, but it is not fixed.
- `DEF-MYPY-STRICT-001` (experimental driver typing error) remains open.
- The prior-phase untracked discovery modules remain untracked (not this
  phase's files to commit), which keeps the dependency-closure guard red on a
  full-suite run.
