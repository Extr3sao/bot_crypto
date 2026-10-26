# ARP-005 — CROSS-SECTIONAL ENGINE AUDIT (PATH B, §4)

Target: `src/trading_bot/research/cross_sectional.py` (`CrossSectionalEngine`,
`CrossSectionalSnapshot`, `QuantileSelection`, `AssetMetric`, `QuantileSide`).

## Classification: `ORPHAN`

| axis | finding |
| --- | --- |
| reachability | Exported from `research/__init__.py` but **zero callers** in `src/`, `scripts/`, `tests/` (only the unrelated `cross_sectional_flow` microstructure helper is used). Not on any runtime path. |
| PIT | Window filter `[c for c in candles if c.timestamp <= timestamp][-lookback:]` never reads a future bar. But no assertion that a symbol's latest bar *equals* `timestamp`, and `AssetMetric.timestamp` = the **requested** time, not the bar time. |
| synchronization | **Gap.** Each symbol contributes its most recent ≤`timestamp` bar; a lagging symbol silently contributes a staler bar → ranks compare different real times. No staleness guard. |
| ranking | `_assign_ranks(...)` is a documented **no-op** (frozen dataclass), so `AssetMetric.rank`/`percentile` are **never populated** (always `None`). Order only in the separate `rankings` dict. |
| survivorship | Universe supplied by caller; no PIT membership mechanism (acceptable only for a fixed 3-major set). |
| tests | **None** reference the engine. |
| thin universe | `select_quantile` uses `max(1, int(n × pct))` → on 3 assets a "top 20 %" selects exactly 1. |

## CLAIM / SOURCE / EVIDENCE / DECISION

- **CLAIM** — the legacy engine cannot guarantee a PIT-verified, asset-synchronized
  ranking, so `EXP-ARP-009` is blocked on it.
- **SOURCE** — `cross_sectional.py` (391 lines), grep for callers, the ARP-004
  `EXP-ARP-009_INFRA_AUDIT.md`.
- **EVIDENCE** — the findings table above (no-op rank assignment; no sync guard; no
  tests; no caller).
- **DECISION** — **`REIMPLEMENT_MINIMAL_PATTERN`** (do **not** `REPAIR_AND_ADOPT`).

Rationale for reimplementing rather than repairing: the legacy engine is an
unevaluated "P19" research artifact whose API (`AssetMetric.rank/percentile`) is
dead; adopting it would carry its dead fields and its untested contract into a live
experiment. A minimal purpose-built ranker is smaller, testable, and cannot regress
anything that imports the legacy module. The legacy engine is **left untouched**.

## The minimal replacement (`src/trading_bot/research/alpha_recovery/xsec.py`)

`CrossSectionalRanker.rank(bars_by_symbol, timestamp, lookback_days) -> RankedUniverse`
guarantees:

1. **asset synchronization + stale rejection** — a symbol participates only if its
   last closed bar is *exactly* at `timestamp`; otherwise it is listed in
   `stale_excluded`, never ranked on a stale bar;
2. **PIT-safe ranking** — only bars `<= timestamp` are read; the metric window ends at
   the decision bar; `as_of[symbol]` records the exact bar time used;
3. **missing-data handling** — a non-contiguous trailing window yields `None` and the
   symbol is excluded (never interpolated);
4. **deterministic ties** — ranking sorted by `(-value, symbol)`;
5. **no future data** — no future membership, returns or rank;
6. **reproducible** — pure function of the supplied bars; no clock, no RNG;
7. **contract tests** — `tests/unit/research/test_alpha_recovery_xsec.py` (PIT
   invariance, stale exclusion, contiguity rejection, tie determinism, portfolio
   determinism).

No external framework was copied.

## Outcome

`EXP-ARP-009` became executable and was run (see `DEV_RESULTS.md`). Result:
`INSUFFICIENT_EVIDENCE` (17 DEV rotations < the frozen 20) with negative gross
(−100.114 bps); no threshold was lowered.
