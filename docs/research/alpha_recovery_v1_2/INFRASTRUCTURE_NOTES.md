# ARP-003 — INFRASTRUCTURE NOTES (§20 cross-sectional, §21 longer horizon)

## §20 — Cross-sectional infrastructure check

`EXP-ARP-009` / `H-XSEC-RELSTR-001` needs multi-asset **synchronized ranking**: at
one decision timestamp, rank a universe by a past-return metric and pick the
top/bottom.

**Finding:** the capability already exists, but orphaned.

- `src/trading_bot/research/cross_sectional.py::CrossSectionalEngine` (391 lines,
  "P19") already implements PIT-safe cross-sectional ranking, dispersion and
  quantile selection, and its docstring states the correct contract
  (*"cross-sectional analysis at time T uses ONLY data available at time T"*).
- It is exported from `research/__init__.py` and **has no caller** anywhere in
  `src/`, `scripts/` or `tests/`, and **no test**.

So the classification is **`INFRASTRUCTURE_PARTIAL`**, not
`INFRASTRUCTURE_BLOCKED`:

- the *minimum required capability* is small — a thin, PIT-safe adapter that (a)
  loads the three symbols' bars on a common clock, (b) calls
  `CrossSectionalEngine` at each decision timestamp using only returns observable
  at that timestamp, (c) returns a long/short selection with an explicit universe
  as-of rule;
- **but the engine is untested** and the project rule `NEG-012` / ARP-001 §32
  forbids adding untested code unilaterally. Wiring an untested 391-line engine is
  itself a code addition that must ship with its own PIT tests.

**Decision (this phase): do not build it.** `EXP-ARP-009` is pre-registered as
`EXPERIMENT_READY = PARTIAL`; the first implementation step is a PIT unit test for
`CrossSectionalEngine` plus a thin adapter. Budget: small (one file + one test).

Anti-leakage requirements the adapter must enforce (from §4): no future membership,
no future liquidity, no future ranking window; a ranking computed from a window
ending after the decision bar is a PIT violation.

## §21 — Longer-horizon data

The pre-registered experiments use 5m base bars for DEV/VALIDATION/OOS_LOCK and
higher horizons derived from them.

- An existing, correct derivation path exists:
  `scripts/resample_baseline_data.py` aggregates 5m → 15m/30m/1h by **complete UTC
  epoch buckets only** (`bucket = ts // tf_ms`; the trailing partial bucket of a
  window is dropped). This is PIT-safe: an HTF bar is emitted only once all its
  constituent 5m bars exist, so `data_time <= decision_time`.
- The frozen corpus already contains `*_5m_15m.json`, `*_5m_30m.json`,
  `*_5m_1h.json` variants for every window.
- **Do not use** `src/trading_bot/market_data/htf_pit.py::get_completed_htf_state_at`
  without fixing `DEF-HTF-PIT-001` (a seconds-vs-milliseconds availability bug). It
  is still ORPHAN (no `src/` caller). Deriving daily/multi-day bars privately from
  5m with the complete-bucket rule avoids the defect entirely.

**Forbidden** (all enforced in the manifests): incomplete HTF bars, future
aggregation, future close, fake availability timestamps.
