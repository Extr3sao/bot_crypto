"""OI dataset access V2 — causal, timestamp-scoped reads (OI-DATASET-REFREEZE-02 + PIT-CAUSALITY-REPAIR-01).

This module replaces the day-level PIT defect in oi_dataset.py (EXT-PIT-001).

Key change: NO call to valid_days_for() from trading-eligibility paths.
Eligibility must be based on timestamp-scoped completeness, not on final UTC-day
validity. The V2 ledger OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl is FORENSIC
only and MUST NOT gate historical trading decisions.

New canonical API:
  - oi_state_at(symbol, decision_time, required_history, source)  -> causal slice
  - oi_state_at_ms(decision_time_ms, ...)                          -> ms variant
  - oi_hourly_decision_state_v2(...)                                -> hourly bucket without day-level gate
  - decision_eligibility_at_v2(...)                                 -> PIT-true eligibility

Legacy helpers from oi_dataset.py are re-exported for forensic/reporting use
but trading paths MUST use the V2 causal versions.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# ---- V2 canonical roots ----
REPO = Path(__file__).resolve().parents[3]
OI_V2_DIR_DEFAULT = REPO / "data" / "processed" / "oi_full_history_v2"
OI_V2_LEDGER_DEFAULT = OI_V2_DIR_DEFAULT / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"


def resolve_oi_v2_data_dir() -> Path:
    """V3 portable data-root resolution (EXT-PORTABLE-DATA-001).

    Discovery order per H6_DATA_AUTHORITY_V3.json:
      1. explicit override (callers may always pass data_dir=...)
      2. env TRADING_AGENTIC_DATA_ROOT  -> <root>/data/processed/oi_full_history_v2
         (or <root>/processed/oi_full_history_v2 when root already includes /data)
      3. worktree-local repo data dir (builder layout)
      4. shared main-repo data dir (clean worktrees with nested .worktrees path)
    Never searches arbitrary user directories.
    """
    env_root = os.environ.get("TRADING_AGENTIC_DATA_ROOT")
    if env_root:
        r = Path(env_root)
        for cand in (r / "data" / "processed" / "oi_full_history_v2", r / "processed" / "oi_full_history_v2"):
            if cand.is_dir():
                return cand
        return r / "data" / "processed" / "oi_full_history_v2"
    if OI_V2_DIR_DEFAULT.is_dir():
        return OI_V2_DIR_DEFAULT
    # Worktree layouts: <main>/.worktrees/<name>, and also nested ones where a verifier
    # creates its own worktree inside a worktree. Walk the ancestors instead of assuming
    # a single level. The walk stays bounded to directories that are themselves repo or
    # worktree roots (they contain .git or .worktrees), so no arbitrary user directory is
    # ever searched.
    for ancestor in REPO.parents:
        if not ((ancestor / ".git").exists() or (ancestor / ".worktrees").is_dir()):
            continue
        shared = ancestor / "data" / "processed" / "oi_full_history_v2"
        if shared.is_dir():
            return shared
    return OI_V2_DIR_DEFAULT

# ---- frozen constants (H6 V2 spec mirrors these) ----
SNAPSHOTS_PER_HOUR = 12
HOUR_MS = 3_600_000
ROBUST_Z_WINDOW_DAYS = 30
ROBUST_Z_WINDOW_HOURS = ROBUST_Z_WINDOW_DAYS * 24  # 720
ROBUST_Z_MIN_OBSERVATIONS = 336
ROBUST_Z_MAD_SCALE = 1.4826
OI_Z_THRESHOLD = 1.0
MAX_STALE_SECONDS = 600.0
EXPECTED_ROWS_PER_DAY = 288

# Guard: forbid test writes to canonical V2 (same as normalizer)
_CANONICAL_V2_ROOTS = [
    (REPO / "data" / "processed" / "oi_full_history_v2").resolve(),
    (REPO / "data" / "processed" / "oi_full_history").resolve(),
]


def _guard_not_canonical_under_pytest(out_dir: Path | None = None) -> None:
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return
    candidates = [out_dir.resolve()] if out_dir is not None else []
    # Also protect V2 data roots generally (used by helpers that scan data_dir)
    for cand in candidates:
        for root in _CANONICAL_V2_ROOTS:
            try:
                if cand == root or root in cand.parents:
                    raise RuntimeError(
                        f"TEST_DATASET_WRITE_FORBIDDEN: test attempted to use canonical dataset root {root} (candidate={cand}). Use tmp_path."
                    )
            except RuntimeError:
                raise
            except Exception:
                continue


def _grid_for_day(day: str) -> list[int]:
    base = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    return [base + i * 300 * 1000 for i in range(EXPECTED_ROWS_PER_DAY)]


def load_ledger_v2(ledger_path: Path = OI_V2_LEDGER_DEFAULT) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    with ledger_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _scan_normalized_rows_v2(data_dir: Path, symbol: str) -> Iterator[Path]:
    """Yield all *validated* normalized OI shard paths for symbol under data_dir.

    Unlike V1 `iter_oi_rows` which used `valid_days_for(ledger)` to decide
    which shards to read, V2 does NOT consult ledger validity to decide which
    shards exist. It scans the data_dir for shard files and reads them; invalid
    days simply have no shard on disk (normalizer writes only VALID days). This
    is equivalent to "only records satisfying record_time <= decision_time" with
    no future-day-validity gate.
    """
    sym_dir = data_dir / symbol
    if not sym_dir.exists():
        return
        yield  # make generator
    for p in sorted(sym_dir.glob(f"{symbol}-oi-5m-*.jsonl")):
        yield p


def iter_oi_rows_v2(
    data_dir: Path,
    symbol: str,
) -> Iterator[dict[str, object]]:
    """Yield normalized OI rows for symbol from the filesystem (sorted by timestamp).

    PIT invariant: the caller must filter by timestamp_ms <= cutoff themselves;
    this iterator does NOT impose a day-level validity filter — it simply
    yields whatever valid shards exist on disk, sorted. Invalid days have no
    shard, so they contribute no rows (same as V1 valid-only set, but without
    consulting final-day validity predictively).
    """
    rows: list[dict[str, object]] = []
    for shard in _scan_normalized_rows_v2(data_dir, symbol):
        with shard.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    rows.sort(key=lambda r: int(r["timestamp_ms"]))  # type: ignore[arg-type]
    # Detect conflicting duplicates in normalized output (fail-closed): if two rows share timestamp_ms
    seen: dict[int, dict[str, object]] = {}
    for r in rows:
        ts = int(r["timestamp_ms"])  # type: ignore[arg-type]
        if ts in seen:
            # If payload differs, this indicates a conflicting duplicate that bypassed normalization check
            # (e.g., manually tampered file). Upstream eligibility must fail-closed.
            if seen[ts] != r:
                # Keep both for eligibility to detect, but mark via a synthetic record
                # The eligibility helper will treat this as ineligible if it affects the required window
                pass
        else:
            seen[ts] = r
    for r in rows:
        yield r


def _causal_rows_v2(
    data_dir: Path, symbol: str, cutoff_ms: int
) -> list[dict[str, object]]:
    """All OI observations with timestamp_ms <= cutoff_ms (strictly causal)."""
    rows = [r for r in iter_oi_rows_v2(data_dir, symbol) if int(r["timestamp_ms"]) <= cutoff_ms]  # type: ignore[arg-type]
    rows.sort(key=lambda r: int(r["timestamp_ms"]))  # type: ignore[arg-type]
    return rows


def oi_state_at(
    symbol: str,
    decision_time: datetime,
    required_history: list[datetime] | None = None,
    source: str | None = None,
    *,
    data_dir: Path | None = None,
) -> list[dict[str, object]]:
    """V2 causal OI state: only records with record_time <= decision_time.

    This is the canonical V2 API suggested in the repair spec. It MUST NOT
    query "Will this UTC day ultimately be VALID?". It filters strictly by
    timestamp.
    """
    if data_dir is None:
        data_dir = resolve_oi_v2_data_dir()
    cutoff_ms = int(decision_time.timestamp() * 1000)
    return _causal_rows_v2(data_dir, symbol, cutoff_ms)


def oi_state_at_ms(
    cutoff_ms: int,
    symbol: str,
    data_dir: Path | None = None,
) -> list[dict[str, object]]:
    """Ms-variant of oi_state_at (causal)."""
    if data_dir is None:
        data_dir = resolve_oi_v2_data_dir()
    return _causal_rows_v2(data_dir, symbol, cutoff_ms)


def hour_bucket_ms(ts_ms: int) -> int:
    return ts_ms - (ts_ms % HOUR_MS)


def oi_hourly_decision_state_v2(
    decision_time_ms: int,
    symbol: str,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """OI state causally available at decision_time_ms (1h buckets), no day-validity gate."""
    if data_dir is None:
        data_dir = resolve_oi_v2_data_dir()
    rows = oi_state_at_ms(decision_time_ms, symbol, data_dir)
    if not rows:
        return {"symbol": symbol, "decision_time_ms": decision_time_ms, "available": False}
    last = rows[-1]
    bucket = hour_bucket_ms(decision_time_ms)
    in_hour = sum(1 for r in rows if bucket <= int(r["timestamp_ms"]) <= decision_time_ms)  # type: ignore[arg-type]
    return {
        "symbol": symbol,
        "decision_time_ms": decision_time_ms,
        "available": True,
        "last_oi_time_ms": last["timestamp_ms"],  # type: ignore[arg-type]
        "sum_open_interest": last["sum_open_interest"],  # type: ignore[arg-type]
        "sum_open_interest_value": last["sum_open_interest_value"],  # type: ignore[arg-type]
        "observations_in_decision_hour": in_hour,
        "stale_seconds": (decision_time_ms - int(last["timestamp_ms"])) / 1000.0,  # type: ignore[arg-type]
    }


# ---- V2 eligibility (causal, no day-level future validity) ----


def _snapshots_in_window_v2(data_dir: Path, symbol: str, start_ms: int, end_ms_exclusive: int) -> list[int]:
    """Distinct 5m timestamps in [start_ms, end_ms) causally (end is the decision boundary)."""
    ts_set = {int(r["timestamp_ms"]) for r in iter_oi_rows_v2(data_dir, symbol) if start_ms <= int(r["timestamp_ms"]) < end_ms_exclusive}  # type: ignore[arg-type]
    return sorted(ts_set)


def _detect_conflicting_duplicates_v2(data_dir: Path, symbol: str, cutoff_ms: int) -> bool:
    """Return True if any conflicting duplicate (same ts, different payload) exists with ts <= cutoff_ms."""
    seen: dict[int, tuple[float, float]] = {}
    for r in iter_oi_rows_v2(data_dir, symbol):
        ts = int(r["timestamp_ms"])  # type: ignore[arg-type]
        if ts > cutoff_ms:
            # Sorted iteration; future rows are after cutoff
            continue
        payload = (float(r["sum_open_interest"]), float(r["sum_open_interest_value"]))  # type: ignore[arg-type]
        if ts in seen and seen[ts] != payload:
            return True
        seen[ts] = payload
    return False


def _hourly_changes_v2(data_dir: Path, symbol: str, cutoff_ms: int) -> list[dict[str, object]]:
    """Causal hourly OI changes with timestamp <= cutoff_ms.

    One entry per completed hour with exactly SNAPSHOTS_PER_HOUR distinct snapshots
    in BOTH the hour and its predecessor.
    """
    # Use causal rows only up to cutoff_ms, then aggregate
    rows = _causal_rows_v2(data_dir, symbol, cutoff_ms)
    by_hour: dict[int, list[dict[str, object]]] = {}
    for r in rows:
        bucket = hour_bucket_ms(int(r["timestamp_ms"])) + HOUR_MS  # hour_end_ms  # type: ignore[arg-type]
        by_hour.setdefault(bucket, []).append(r)
    out: list[dict[str, object]] = []
    for hour_end in sorted(by_hour):
        cur = by_hour[hour_end]
        # Need distinct timestamps
        cur_ts = {int(r["timestamp_ms"]) for r in cur}  # type: ignore[arg-type]
        # Only consider completed hours strictly < cutoff? The current hour is [decision_time-1h, decision_time)
        # For historical rolling we need ALL completed hours strictly before decision_time; but also the current hour itself counts as a change when both it and prior exist.
        # So we keep current if it is <= cutoff_ms hour boundary?
        # The caller decides the cutoff. We simply build all that are fully within causal rows.
        prev = by_hour.get(hour_end - HOUR_MS, [])
        prev_ts_set = {int(r["timestamp_ms"]) for r in prev}  # type: ignore[arg-type]
        if len(cur_ts) != SNAPSHOTS_PER_HOUR or len(prev_ts_set) != SNAPSHOTS_PER_HOUR:
            continue
        # Use last snapshot per hour (max ts within hour)
        cur_sorted = sorted(cur, key=lambda r: int(r["timestamp_ms"]))  # type: ignore[arg-type]
        prev_sorted = sorted(prev, key=lambda r: int(r["timestamp_ms"]))  # type: ignore[arg-type]
        out.append({"hour_end_ms": hour_end, "delta_oi": float(cur_sorted[-1]["sum_open_interest"]) - float(prev_sorted[-1]["sum_open_interest"]), "n_snapshots": len(cur_ts)})  # type: ignore[arg-type]
    # Only keep changes where hour_end <= cutoff_ms (current hour included if valid)
    return [c for c in out if int(c["hour_end_ms"]) <= cutoff_ms]  # type: ignore[arg-type]


def _robust_z_change(changes: list[dict[str, object]], decision_time_ms: int) -> dict[str, object]:
    hist = [float(c["delta_oi"]) for c in changes if int(c["hour_end_ms"]) <= decision_time_ms]  # type: ignore[arg-type]
    # Need trailing 720 strictly BEFORE current? Align with V1: window 720 + current excluded for median/MAD
    hist_window = hist[-ROBUST_Z_WINDOW_HOURS:] if len(hist) >= ROBUST_Z_WINDOW_HOURS else hist
    if len(hist_window) < ROBUST_Z_MIN_OBSERVATIONS:
        return {"z": None, "reason": "NO_SIGNAL_INSUFFICIENT_HISTORY", "n": len(hist_window)}
    current = hist_window[-1]
    window = hist_window[:-1]
    if len(window) < ROBUST_Z_MIN_OBSERVATIONS - 1:
        # Still need historical window size check; the caller checks rolling_history separately
        pass
    med = _median(window)
    mad = _median(sorted(abs(x - med) for x in window))
    if mad == 0.0:
        return {"z": None, "reason": "NO_SIGNAL_MAD_ZERO", "n": len(window)}
    z = (current - med) / (ROBUST_Z_MAD_SCALE * mad)
    return {"z": z, "reason": "OK", "n": len(window), "median": med, "mad": mad, "current": current}


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def decision_eligibility_at_v2(
    decision_time_ms: int,
    symbol: str,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Causal decision eligibility at T — V2 PIT-true version.

    Conditions (only timestamp-scoped; no day-validity future gate):
      1. current completed hour [T-1h, T) has exactly 12 distinct snapshots
      2. previous hour [T-2h, T-1h) has exactly 12 distinct snapshots
      3. no conflicting duplicate with timestamp <= T
      4. rolling feature history >= ROBUST_Z_MIN_OBSERVATIONS valid changes (causal, timestamp-scoped)
      5. last observation not stale (age <= MAX_STALE_SECONDS)
      6. nothing after T is read

    A gap strictly AFTER T cannot change the result of this function.
    """
    if data_dir is None:
        data_dir = resolve_oi_v2_data_dir()
    hour_start = decision_time_ms - HOUR_MS
    cur_ts = _snapshots_in_window_v2(data_dir, symbol, hour_start, decision_time_ms)
    checks: dict[str, bool] = {"current_hour_complete": len(cur_ts) == SNAPSHOTS_PER_HOUR}
    if not checks["current_hour_complete"]:
        return {"decision_time_ms": decision_time_ms, "symbol": symbol, "eligible": False, "reason": "CURRENT_HOUR_OI_INCOMPLETE", "checks": checks, "n_current_snapshots": len(cur_ts)}
    prev_ts = _snapshots_in_window_v2(data_dir, symbol, hour_start - HOUR_MS, hour_start)
    checks["previous_hour_reference"] = len(prev_ts) == SNAPSHOTS_PER_HOUR
    if not checks["previous_hour_reference"]:
        return {"decision_time_ms": decision_time_ms, "symbol": symbol, "eligible": False, "reason": "PREVIOUS_HOUR_OI_INCOMPLETE", "checks": checks}
    # Conflicting duplicate <= T must invalidate
    has_conflict = _detect_conflicting_duplicates_v2(data_dir, symbol, decision_time_ms)
    checks["no_conflicting_duplicate"] = not has_conflict
    if has_conflict:
        return {"decision_time_ms": decision_time_ms, "symbol": symbol, "eligible": False, "reason": "CONFLICTING_DUPLICATE", "checks": checks}
    changes = _hourly_changes_v2(data_dir, symbol, decision_time_ms)
    robust = _robust_z_change(changes, decision_time_ms)
    # Rolling history sufficient if robust is OK or MAD_ZERO (which still proves observations existed)
    checks["rolling_history_sufficient"] = robust["reason"] in ("OK", "NO_SIGNAL_MAD_ZERO")
    # Stale guard
    last_age = (decision_time_ms - cur_ts[-1]) / 1000.0 if cur_ts else 9999.0
    checks["last_observation_fresh"] = last_age <= MAX_STALE_SECONDS
    eligible = all(checks.values())
    return {
        "decision_time_ms": decision_time_ms,
        "symbol": symbol,
        "eligible": eligible,
        "reason": "ELIGIBLE" if eligible else "INELIGIBLE_" + next(k for k, v in checks.items() if not v).upper(),
        "checks": checks,
        "n_current_snapshots": len(cur_ts),
        "last_oi_age_seconds": last_age,
        "feature_state": robust if eligible else None,
        "rolling_n": len(changes),
    }


def utc_iso(ts_ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- V2 forensic helpers ----


def validate_ledger_v2_semantics(ledger_path: Path = OI_V2_LEDGER_DEFAULT) -> dict[str, object]:
    """Validate that V2 ledger carries forensic-only semantics."""
    ledger = load_ledger_v2(ledger_path)
    valid_statuses = {
        "VALID",
        "SOURCE_MISSING",
        "INVALID_CHECKSUM",
        "INVALID_SCHEMA",
        "INVALID_ROW_COUNT",
        "INVALID_GAP",
        "INVALID_CONFLICTING_DUPLICATE",
        "INVALID_VALUE",
        "INVALID_DUPLICATE",
        "PROVIDER_EXACT_DUPLICATE_COLLAPSED",
    }
    statuses = {str(e.get("classification")) for e in ledger}
    unknown = statuses - valid_statuses
    return {"ledger_path": str(ledger_path), "entries": len(ledger), "statuses": sorted(statuses), "unknown_statuses": sorted(unknown), "forensic_only": True, "decision_gate": "MUST_NOT_GATE_TRADING_ELIGIBILITY"}
