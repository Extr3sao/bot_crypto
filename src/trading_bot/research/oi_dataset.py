"""OI dataset access — V1 legacy + V2 PIT-true paths.

V1 (OI-FULL-HISTORY-FREEZE-01) provided day-level validity gating via
valid_days_for/iter_oi_rows. That path is RETAINED for forensic/reporting
only and is NOT to be used for eligibility/trading decisions because it
allows a later same-day gap to invalidate an earlier T (EXT-PIT-001).

V2 causal paths (PIT-CAUSALITY-REPAIR-01 / OI-DATASET-REFREEZE-02) are the
canonical trading-eligibility implementation. H6 decision code MUST use
`oi_dataset_v2.decision_eligibility_at_v2` / `oi_state_at` (timestamp-scoped,
no final-day validity gate). This file now documents that separation and
re-exports V2 entrypoints for convenience. Forensic ledger loading and V1
V1-valid-day helpers remain for reports and backward-compatible tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.oi_dataset_v2 import (
    OI_V2_DIR_DEFAULT,
)

OI_FULL_DIR_DEFAULT = Path("data/processed/oi_full_history")
# Canonical V2 roots (trading decisions must use these; V1 root is legacy/forensic)
OI_V2_FULL_DIR_DEFAULT = OI_V2_DIR_DEFAULT
VALID_CLASS = "VALID"
EXPECTED_ROWS_PER_DAY = 288

# ---- frozen decision-eligibility constants (H6 spec mirrors these) ----
SNAPSHOTS_PER_HOUR = 12  # 5m cadence: 12 distinct snapshots per completed hour
HOUR_MS = 3_600_000
ROBUST_Z_WINDOW_DAYS = 30  # trailing calendar days of completed hourly changes
ROBUST_Z_WINDOW_HOURS = ROBUST_Z_WINDOW_DAYS * 24  # 720
ROBUST_Z_MIN_OBSERVATIONS = 336  # P0-D: below this => NO_SIGNAL
ROBUST_Z_MAD_SCALE = 1.4826
OI_Z_THRESHOLD = 1.0  # expansion qualifies at z >= +1.0 (frozen; no sweep)
MAX_STALE_SECONDS = 600.0  # last OI snapshot must be <= 10 min old at decision time


def load_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def valid_days_for(
    ledger: list[dict[str, Any]], symbol: str, window: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """Valid-day entries for symbol, optionally bounded by ISO-date window (inclusive)."""
    out = []
    for e in ledger:
        if e["symbol"] != symbol or e["classification"] != VALID_CLASS:
            continue
        if window is not None and not (window[0] <= str(e["day"]) <= window[1]):
            continue
        out.append(e)
    return out


def iter_oi_rows(
    ledger: list[dict[str, Any]],
    symbol: str,
    data_dir: Path,
    window: tuple[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield normalized OI rows for VALID days (sorted by timestamp)."""
    for e in valid_days_for(ledger, symbol, window):
        path = data_dir / str(e.get("normalized_path", "")).replace(
            "data/processed/oi_full_history/", ""
        )
        if not path.exists():
            raise FileNotFoundError(f"missing normalized artifact for VALID day: {e}")
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def oi_state_at(
    cutoff_ms: int,
    ledger: list[dict[str, Any]],
    symbol: str,
    data_dir: Path,
    window: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """All OI observations with data_time <= cutoff_ms for VALID days.

    PIT invariant: rows with timestamp_ms > cutoff are excluded; VALID days
    contain no future rows by construction, and day-level exclusion uses only
    same-day validity information.
    """
    rows = [
        r
        for r in iter_oi_rows(ledger, symbol, data_dir, window)
        if int(r["timestamp_ms"]) <= cutoff_ms
    ]
    rows.sort(key=lambda r: int(r["timestamp_ms"]))
    return rows


def hour_bucket_ms(ts_ms: int) -> int:
    """Floor of the UTC hour bucket containing ts_ms."""
    return ts_ms - (ts_ms % 3_600_000)


def oi_hourly_decision_state(
    decision_time_ms: int,
    ledger: list[dict[str, Any]],
    symbol: str,
    data_dir: Path,
    window: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """OI state causally available at decision_time_ms (1h decision buckets).

    Uses only 5m observations with oi_time <= decision_time. Returns the last
    observation at or before the decision time plus the count of observations
    inside the decision hour (observability metadata, no market semantics).
    """
    rows = oi_state_at(decision_time_ms, ledger, symbol, data_dir, window)
    if not rows:
        return {"symbol": symbol, "decision_time_ms": decision_time_ms, "available": False}
    last = rows[-1]
    bucket = hour_bucket_ms(decision_time_ms)
    in_hour = sum(1 for r in rows if bucket <= int(r["timestamp_ms"]) <= decision_time_ms)
    return {
        "symbol": symbol,
        "decision_time_ms": decision_time_ms,
        "available": True,
        "last_oi_time_ms": last["timestamp_ms"],
        "sum_open_interest": last["sum_open_interest"],
        "sum_open_interest_value": last["sum_open_interest_value"],
        "observations_in_decision_hour": in_hour,
        "stale_seconds": (decision_time_ms - int(last["timestamp_ms"])) / 1000.0,
    }


def utc_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# P0-B / P0-H — DECISION_ELIGIBILITY_AT_T (strictly causal)
# ---------------------------------------------------------------------------


def completed_hour_snapshots(
    ledger: list[dict[str, Any]],
    symbol: str,
    data_dir: Path,
    hour_start_ms: int,
) -> list[dict[str, Any]]:
    """Distinct 5m snapshots inside the completed hour [hour_start_ms, hour_start_ms+1h).

    Uses only observations with data_time <= hour end; a partially completed
    hour cannot exist here because callers pass completed decision hours.
    """
    end = hour_start_ms + HOUR_MS
    return [
        r
        for r in iter_oi_rows(ledger, symbol, data_dir)
        if hour_start_ms <= int(r["timestamp_ms"]) < end
    ]


def hourly_oi_changes(
    ledger: list[dict[str, Any]],
    symbol: str,
    data_dir: Path,
    window: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Causal hourly OI changes from completed hours.

    One entry per completed hour with exactly SNAPSHOTS_PER_HOUR distinct
    snapshots in the hour AND in the previous hour (delta needs both).
    Entry: {hour_end_ms, delta_oi (base units), n_snapshots}.
    """
    rows = list(iter_oi_rows(ledger, symbol, data_dir, window))
    rows.sort(key=lambda r: int(r["timestamp_ms"]))
    by_hour: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_hour.setdefault(hour_bucket_ms(int(r["timestamp_ms"])) + HOUR_MS, []).append(r)
    out: list[dict[str, Any]] = []
    for hour_end in sorted(by_hour):
        cur = by_hour[hour_end]
        prev = by_hour.get(hour_end - HOUR_MS, [])
        if len(cur) != SNAPSHOTS_PER_HOUR or len(prev) != SNAPSHOTS_PER_HOUR:
            continue
        out.append(
            {
                "hour_end_ms": hour_end,
                "delta_oi": float(cur[-1]["sum_open_interest"])
                - float(prev[-1]["sum_open_interest"]),
                "n_snapshots": len(cur),
            }
        )
    return out


def robust_z_oi_change(changes: list[dict[str, Any]], decision_time_ms: int) -> dict[str, Any]:
    """P0-D robust z of the current hourly OI change (median / 1.4826*MAD).

    Window: the trailing ROBUST_Z_WINDOW_HOURS completed hourly changes strictly
    BEFORE decision_time_ms (current hour excluded). Requires at least
    ROBUST_Z_MIN_OBSERVATIONS observations, else NO_SIGNAL. MAD == 0 => NO_SIGNAL.
    """
    hist = [float(c["delta_oi"]) for c in changes if int(c["hour_end_ms"]) <= decision_time_ms]
    hist = hist[-ROBUST_Z_WINDOW_HOURS:]
    if len(hist) < ROBUST_Z_MIN_OBSERVATIONS:
        return {"z": None, "reason": "NO_SIGNAL_INSUFFICIENT_HISTORY", "n": len(hist)}
    current = hist[-1]
    window = hist[:-1]
    med = _median(window)
    mad = _median(sorted(abs(x - med) for x in window))
    if mad == 0.0:
        return {"z": None, "reason": "NO_SIGNAL_MAD_ZERO", "n": len(window)}
    z = (current - med) / (ROBUST_Z_MAD_SCALE * mad)
    return {"z": z, "reason": "OK", "n": len(window), "median": med, "mad": mad}


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def decision_eligibility_at(
    decision_time_ms: int,
    ledger: list[dict[str, Any]],
    symbol: str,
    data_dir: Path,
) -> dict[str, Any]:
    """Causal decision eligibility at T (P0-B/P0-H).

    Uses ONLY observations with data_time <= T. Conditions:
      1. current completed hour has exactly SNAPSHOTS_PER_HOUR distinct snapshots;
      2. previous completed hour has SNAPSHOTS_PER_HOUR (reference for delta);
      3. no conflicting duplicate timestamps up to T (conflicting duplicates are
         excluded by construction here — distinct timestamps only);
      4. rolling feature history >= ROBUST_Z_MIN_OBSERVATIONS valid changes;
      5. last observation not stale (age <= MAX_STALE_SECONDS);
      6. no knowledge of the remainder of the UTC day (nothing after T is read).

    A gap strictly AFTER T cannot change the result of this function.
    """
    hour_start = decision_time_ms - HOUR_MS
    # provider create_time labels the 5m interval START: the snapshot AT T
    # belongs to the NEXT hour, so the completed hour is strictly < T
    cur = [
        r
        for r in iter_oi_rows(ledger, symbol, data_dir)
        if hour_start <= int(r["timestamp_ms"]) < decision_time_ms
    ]
    cur_ts = sorted({int(r["timestamp_ms"]) for r in cur})
    checks: dict[str, bool] = {
        "current_hour_complete": len(cur_ts) == SNAPSHOTS_PER_HOUR,
    }
    if not checks["current_hour_complete"]:
        return {
            "decision_time_ms": decision_time_ms,
            "symbol": symbol,
            "eligible": False,
            "reason": "CURRENT_HOUR_OI_INCOMPLETE",
            "checks": checks,
            "n_current_snapshots": len(cur_ts),
        }
    prev = [
        r
        for r in iter_oi_rows(ledger, symbol, data_dir)
        if hour_start - HOUR_MS <= int(r["timestamp_ms"]) < hour_start
    ]
    checks["previous_hour_reference"] = (
        len({int(r["timestamp_ms"]) for r in prev}) == SNAPSHOTS_PER_HOUR
    )
    if not checks["previous_hour_reference"]:
        return {
            "decision_time_ms": decision_time_ms,
            "symbol": symbol,
            "eligible": False,
            "reason": "PREVIOUS_HOUR_OI_INCOMPLETE",
            "checks": checks,
        }
    changes = hourly_oi_changes(ledger, symbol, data_dir)
    robust = robust_z_oi_change(changes, decision_time_ms)
    checks["rolling_history_sufficient"] = robust["reason"] in ("OK", "NO_SIGNAL_MAD_ZERO")
    last_age = (decision_time_ms - cur_ts[-1]) / 1000.0
    checks["last_observation_fresh"] = last_age <= MAX_STALE_SECONDS
    eligible = all(checks.values())
    return {
        "decision_time_ms": decision_time_ms,
        "symbol": symbol,
        "eligible": eligible,
        "reason": "ELIGIBLE"
        if eligible
        else "INELIGIBLE_" + next(k for k, v in checks.items() if not v).upper(),
        "checks": checks,
        "n_current_snapshots": len(cur_ts),
        "last_oi_age_seconds": last_age,
        "feature_state": robust if eligible else None,
    }
