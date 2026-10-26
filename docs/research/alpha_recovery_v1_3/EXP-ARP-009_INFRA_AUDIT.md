# ARP-004 — EXP-ARP-009 INFRASTRUCTURE AUDIT (§25)

**Scope:** audit only — no trading experiment run, no implementation built.
**Target:** `src/trading_bot/research/cross_sectional.py::CrossSectionalEngine` (391 lines, "P19").

## Verdict: `INFRASTRUCTURE_BLOCKED`

## Findings

| audit axis | finding |
| --- | --- |
| **runtime reachability** | **Orphan.** Exported from `research/__init__.py`, but **zero callers** in `src/`, `scripts/`, `tests/`. The only `cross_sectional*` symbol in use is `cross_sectional_flow` — an unrelated microstructure helper. Not reachable from any runtime path. |
| **PIT correctness** | Window selection is PIT-safe: `[c for c in candles if c.timestamp <= timestamp][-lookback:]` never reads a future bar. **But** there is no assertion that a symbol's latest bar *equals* `timestamp`, and `AssetMetric.timestamp` is set to the *requested* time, not the bar's actual time — so a metric can be stamped fresher than the data it used. |
| **asset synchronization** | **Gap.** Each symbol independently contributes its most recent ≤`timestamp` bar. A lagging/missing symbol silently contributes a *staler* bar; cross-sectional ranks can therefore compare different real times. No staleness guard, no shared-timeframe assertion. |
| **ranking timestamp** | `CrossSectionalSnapshot.timestamp` = requested time; rankings themselves carry no per-asset as-of timestamp. |
| **survivorship** | Universe is supplied by the caller; there is no PIT universe-membership mechanism. Acceptable for a fixed 3-major set, a gap for anything else. |
| **dead code / defect** | `_assign_ranks(...)` is a **no-op** (documented as "frozen dataclass prevents in-place rank assignment"), so `AssetMetric.rank` and `AssetMetric.percentile` are **never populated** (always `None`). Rankings are only available via the separate `rankings` dict. |
| **tests** | **None.** No unit test, PIT test or determinism test references `CrossSectionalEngine`. |
| **thin-universe behaviour** | `select_quantile` uses `max(1, int(n × pct))`, so on a 3-asset universe a "top 20 %" selects exactly 1 asset. |

## Why `INFRASTRUCTURE_BLOCKED` (not `READY_FOR_EXPERIMENT`)

`EXP-ARP-009` needs a **PIT-verified, asset-synchronized ranking** to drive a
cross-sectional selection. The engine cannot currently guarantee that (no staleness
check, no-op rank assignment, no tests, no caller), and it is not wired into any path
that could consume the output. Building on it as-is would risk a silent PIT/synchrony
defect. This matches ARP-003's `INFRASTRUCTURE_PARTIAL` assessment; the additional
concrete defects here (no-op ranks, no as-of stamping, no tests) raise it to
`INFRASTRUCTURE_BLOCKED`.

## Minimum work before `EXP-ARP-009` could be authorized

1. A PIT unit test: `analyze` at `t` must ignore every bar `> t` (adversarial).
2. An asset-synchronization guard: require each symbol's latest bar to be at the
   analysis timestamp (or explicitly model/report staleness).
3. Population of `rank`/`percentile` (or removal of the dead fields) and a determinism
   test.
4. A thin PIT-safe ranking adapter with at least one caller in a tracked test.

This is deliberately **not** started here (§25: do not turn the audit into a large
implementation phase).
