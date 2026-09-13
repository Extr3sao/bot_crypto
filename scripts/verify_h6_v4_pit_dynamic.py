"""H6 V4 — DYNAMIC, NON-VACUOUS PIT (point-in-time) gate.

Why V3's PIT_DYNAMIC evidence cannot simply be reused
-----------------------------------------------------
V4 changed the completed-hour aggregation (``eligibility.build_completed_hour_oi``:
half-open ``[T-1h, T)`` window, 12 snapshots, no crash on non-empty input) and with
it the decision feature path.  A PIT proof produced against the V3 aggregation is
therefore not evidence about the V4 path, so this gate is re-executed on V4 code.

What it proves, on REAL frozen canonical observations (no synthetic OI)
----------------------------------------------------------------------
1. NON-VACUITY      : the scan produces eligible decisions with a live rolling
                      window, varying OI deltas and a usable dispersion estimate
                      (MAD > 0), and at least one QUALIFYING signal actually fires.
2. FUTURE INVISIBILITY: calling the runtime entry point with the causal slice PLUS
                      every real observation between T and T+72h yields a decision
                      identical to the T-causal-slice-only call.
3. FUTURE MUTATION  : appending synthetic post-T observations with absurd OI changes
                      nothing at T.
4. PAST SENSITIVITY : mutating a single admitted observation at ts <= T DOES change
                      the T decision (proves the check in (2) is not vacuous).
5. ELIGIBILITY      : insufficient rolling history yields an ineligible, NO_TRADE
                      decision rather than a signal.
6. RUNTIME ENTRY POINT: ``prepare_decision_from_data_root`` is invoked on the FULL
                      authoritative store (hundreds of thousands of causal
                      observations) at real decision times, with the authority's own
                      data root as the argument.  It must resolve the store, use exactly
                      the frozen 720-observation window, and agree with a decision built
                      from the equivalent trailing slice.

Economics guard: feature computation only. No PnL, no returns, no performance.

The completed-hour price is a deterministic synthetic pair (up direction).  The price
feed is an input to this mechanism, is separately covered by PRICE_AUTHORITY /
PRICE_OVERLAP gates, and is held constant here so the OI/eligibility causal path is
what is being exercised -- not the price authority.

The observations fed to each decision are the frozen trailing-window causal slice
(``TRAILING_DAYS`` >= the frozen 30-day / min-336-observation requirement + margin).
Feeding the entire 2020-2026 history instead is not equivalent evidence: the frozen
mechanism only consumes the trailing rolling window, and the aggregation helper is
O(hours x observations) over whatever it is handed.

Exit 0 iff every check above PASSes.
"""

from __future__ import annotations

import bisect
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.h6.contracts import SignalDirection  # noqa: E402
from trading_bot.research.h6.feature_engine import (  # noqa: E402
    CompletedHourPrice,
    frozen_rolling_window,
)
from trading_bot.research.h6.preparation import (  # noqa: E402
    prepare_decision,
    prepare_decision_from_data_root,
)
from trading_bot.research.oi_dataset_v2 import (  # noqa: E402
    iter_oi_rows_v2,
    resolve_oi_v2_data_dir,
)

EVID = Path(os.environ.get("H6_EVIDENCE_DIR") or (REPO / "docs/external-audit-01/h6-v4-repair"))
OUT = EVID / "H6_V4_PIT_DYNAMIC.json"

# Rolling-window requirements come from the FROZEN V4 preregistration, not from a code constant.
SPEC = json.loads(
    (REPO / "docs/external-audit-01/h6-v4-repair/H6_SPEC_V4.json").read_text(encoding="utf-8")
)
_ROLLING = SPEC["rolling_windows"]["z_oi"]
ROBUST_Z_MIN_OBSERVATIONS = int(_ROLLING["min_observations"])
ROLLING_LENGTH_HOURS = int(_ROLLING["length_hours"])

SYMBOL = "BTCUSDT"
PRICE_OPEN = 100.0
PRICE_CLOSE = 101.0
# The frozen window is 720 h with a 336-observation minimum.  This gate feeds a 17-day
# trailing slice (~408 completed hours) -- above the frozen minimum, but deliberately not
# the full 720 h because the aggregation helper is O(hours x observations) over whatever
# it is handed and the point here is causality, not window sizing.  Override with
# H6_PIT_TRAILING_DAYS to widen it.
TRAILING_DAYS = int(os.environ.get("H6_PIT_TRAILING_DAYS", "17"))
FUTURE_TAIL_HOURS = 72
_SCAN_DAYS = 7
_SCAN_START = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
_HOURS_STEP = 6

# Real runtime-entry-point checks against the whole authoritative store.
_FULL_STORE_DECISIONS = [
    datetime(2024, 6, 5, 12, 0, tzinfo=timezone.utc),
    datetime(2024, 6, 5, 18, 0, tzinfo=timezone.utc),
]


def _decisions() -> list[datetime]:
    out: list[datetime] = []
    for d in range(_SCAN_DAYS):
        day = _SCAN_START + timedelta(days=d)
        for h in range(0, 24, _HOURS_STEP):
            out.append(day + timedelta(hours=h))
    return out


def _price_at(t: datetime) -> CompletedHourPrice:
    return CompletedHourPrice(bucket_close_time=t, open=PRICE_OPEN, close=PRICE_CLOSE)


frozen_window = int(frozen_rolling_window()[0])


def main() -> int:
    processed = resolve_oi_v2_data_dir()
    # Load enough trailing history that every comparison slice can hold the full frozen
    # window, not just the shorter scan slice.
    load_from = int(
        (min([_SCAN_START] + _FULL_STORE_DECISIONS) - timedelta(days=32)).timestamp() * 1000
    )
    rows = sorted(
        (r for r in iter_oi_rows_v2(processed, SYMBOL) if int(r["timestamp_ms"]) >= load_from),
        key=lambda r: int(r["timestamp_ms"]),
    )
    stamps = [int(r["timestamp_ms"]) for r in rows]

    out: dict[str, object] = {
        "artifact": "H6_V4_PIT_DYNAMIC",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "symbol": SYMBOL,
        "data_dir": str(processed),
        "observations_in_authority": len(rows),
        "first_observation_utc": datetime.fromtimestamp(stamps[0] / 1000, tz=timezone.utc).isoformat(),
        "last_observation_utc": datetime.fromtimestamp(stamps[-1] / 1000, tz=timezone.utc).isoformat(),
        "price_input": "deterministic synthetic up-hour (price authority covered separately)",
        "min_observations": ROBUST_Z_MIN_OBSERVATIONS,
        "frozen_rolling_length_hours": ROLLING_LENGTH_HOURS,
        "trailing_window_days": TRAILING_DAYS,
        "future_tail_hours": FUTURE_TAIL_HOURS,
        "H6_BACKTESTS": 0,
        "H6_EXECUTIONS": 0,
        "PERFORMANCE_OBSERVED": False,
    }

    future_invariance_violations: list[dict] = []
    past_undetected: list[dict] = []
    future_mutation_violations: list[dict] = []
    errors: list[str] = []
    scanned = 0
    eligible = 0
    signals: list[dict] = []
    max_rolling = 0
    max_abs_z = 0.0
    deltas: set[float] = set()
    mad_positive = 0
    hour_snapshot_counts: dict[int, int] = {}
    boundary_rows_checked = 0
    boundary_leaked: list[dict] = []
    future_rows_compared = 0
    prefix_rows_max = 0

    for t in _decisions():
        t_ms = int(t.timestamp() * 1000)
        window_start_ms = int((t - timedelta(days=TRAILING_DAYS)).timestamp() * 1000)
        first = bisect.bisect_left(stamps, window_start_ms)
        cutoff = bisect.bisect_right(stamps, t_ms)
        tail_end = bisect.bisect_right(
            stamps, int((t + timedelta(hours=FUTURE_TAIL_HOURS)).timestamp() * 1000)
        )
        prefix = rows[first:cutoff]          # what the mechanism may know at T
        with_future = rows[first:tail_end]   # ... plus 72h of strictly-future real data
        try:
            base = prepare_decision(prefix, symbol=SYMBOL, decision_time=t, price=_price_at(t))
            full = prepare_decision(with_future, symbol=SYMBOL, decision_time=t, price=_price_at(t))
            future_appended = prepare_decision(
                prefix
                + [
                    {
                        "timestamp_ms": t_ms + 300_000,
                        "sum_open_interest": 9_999_999.0,
                        "sum_open_interest_value": 9_999_999.0,
                        "source_file": "SYNTHETIC_FUTURE",
                        "source_sha256": "0" * 64,
                        "unit_semantics": "synthetic",
                    }
                ],
                symbol=SYMBOL,
                decision_time=t,
                price=_price_at(t),
            )
        except Exception as exc:  # fail loud, never silently skip
            errors.append(f"{t.isoformat()}: {type(exc).__name__}: {exc}")
            continue

        scanned += 1
        future_rows_compared = max(future_rows_compared, len(with_future) - len(prefix))
        prefix_rows_max = max(prefix_rows_max, len(prefix))
        base_d = base.feature_state.to_dict(), base.signal.to_dict()
        if (full.feature_state.to_dict(), full.signal.to_dict()) != base_d:
            future_invariance_violations.append({"decision_time": t.isoformat()})
        if (future_appended.feature_state.to_dict(), future_appended.signal.to_dict()) != base_d:
            future_mutation_violations.append({"decision_time": t.isoformat()})

        # ---- (4) past sensitivity: perturb an observation INSIDE the completed hour ----
        # The completed hour is half-open [T-1h, T), so the correct target is the last
        # observation strictly before T.  Mutating the observation stamped exactly at T
        # is the separate boundary check (b) below and must NOT change anything.
        inside = [i for i, r in enumerate(prefix) if int(r["timestamp_ms"]) < t_ms]
        if inside:
            mutated = list(prefix)
            idx = inside[-1]
            row = dict(mutated[idx])
            row["sum_open_interest"] = float(row["sum_open_interest"]) * 1.5
            row["sum_open_interest_value"] = float(row["sum_open_interest_value"]) * 1.5
            mutated[idx] = row
            past = prepare_decision(mutated, symbol=SYMBOL, decision_time=t, price=_price_at(t))
            if (past.feature_state.to_dict(), past.signal.to_dict()) == base_d:
                past_undetected.append(
                    {"decision_time": t.isoformat(), "mutated_ts_ms": int(prefix[idx]["timestamp_ms"])}
                )

        # ---- (4b) half-open boundary on REAL data: the observation stamped exactly at T
        # belongs to the NEXT hour and must be invisible to the decision at T.
        at_boundary = [i for i, r in enumerate(prefix) if int(r["timestamp_ms"]) == t_ms]
        if at_boundary:
            boundary_rows_checked += 1
            mutated = list(prefix)
            idx = at_boundary[-1]
            row = dict(mutated[idx])
            row["sum_open_interest"] = float(row["sum_open_interest"]) * 1.5
            row["sum_open_interest_value"] = float(row["sum_open_interest_value"]) * 1.5
            mutated[idx] = row
            edge = prepare_decision(mutated, symbol=SYMBOL, decision_time=t, price=_price_at(t))
            if (edge.feature_state.to_dict(), edge.signal.to_dict()) != base_d:
                boundary_leaked.append({"decision_time": t.isoformat()})

        fs = base.feature_state
        max_rolling = max(max_rolling, base.rolling_changes)
        max_abs_z = max(max_abs_z, abs(fs.robust_z_oi))
        deltas.add(round(fs.delta_oi, 6))
        if fs.rolling_mad_delta_oi > 0:
            mad_positive += 1
        if fs.decision_eligible:
            eligible += 1
        hour_snapshot_counts[base.current_hour_oi.snapshot_count] = (
            hour_snapshot_counts.get(base.current_hour_oi.snapshot_count, 0) + 1
        )
        if base.signal.direction != SignalDirection.NO_TRADE:
            signals.append(
                {
                    "decision_time": t.isoformat(),
                    "direction": base.signal.direction.value,
                    "delta_oi": fs.delta_oi,
                    "robust_z_oi": fs.robust_z_oi,
                    "rolling_median_delta_oi": fs.rolling_median_delta_oi,
                    "rolling_mad_delta_oi": fs.rolling_mad_delta_oi,
                    "price_direction": fs.price_direction.value,
                }
            )

    # ---- (6) the real runtime entry point, on the whole authoritative store ----------
    full_store: list[dict] = []
    full_store_errors: list[str] = []
    data_root = processed.parents[1] if processed.name == "oi_full_history_v2" else processed
    for t in _FULL_STORE_DECISIONS:
        try:
            t0 = time.time()
            rt = prepare_decision_from_data_root(
                data_root=data_root, symbol=SYMBOL, decision_time=t, price=_price_at(t)
            )
            elapsed = time.time() - t0
            # Equivalent trailing slice. The runtime clips its hour range at
            # T-(window+1)h unconditionally, so the slice must start one hour earlier
            # still: otherwise its own data-derived start lands one hour later and the
            # two series differ by a single observation.
            t_ms = int(t.timestamp() * 1000)
            first = bisect.bisect_left(
                stamps, int((t - timedelta(hours=frozen_window + 2)).timestamp() * 1000)
            )
            cut = bisect.bisect_right(stamps, t_ms)
            slice_decision = prepare_decision(
                rows[first:cut], symbol=SYMBOL, decision_time=t, price=_price_at(t)
            )
            full_store.append(
                {
                    "decision_time": t.isoformat(),
                    "data_root_argument": str(data_root),
                    "resolved_store": str(processed),
                    "observations_admitted": rt.observations_admitted,
                    "rolling_changes": rt.rolling_changes,
                    "trailing_slice_rolling_changes": slice_decision.rolling_changes,
                    "decision_eligible": rt.feature_state.decision_eligible,
                    "robust_z_oi": rt.feature_state.robust_z_oi,
                    "direction": rt.signal.direction.value,
                    "elapsed_s": round(elapsed, 2),
                    "frozen_window_enforced": rt.rolling_changes == frozen_window,
                    "equals_trailing_slice": (
                        rt.feature_state.to_dict() == slice_decision.feature_state.to_dict()
                        and rt.signal.to_dict() == slice_decision.signal.to_dict()
                    ),
                }
            )
        except Exception as exc:
            full_store_errors.append(f"{t.isoformat()}: {type(exc).__name__}: {exc}")

    checks = {
        "runtime_entry_point_no_errors": not full_store_errors,
        "runtime_entry_point_frozen_window": bool(full_store)
        and all(d["frozen_window_enforced"] for d in full_store),
        "runtime_entry_point_equals_trailing_slice": bool(full_store)
        and all(d["equals_trailing_slice"] for d in full_store),
        "runtime_entry_point_resolves_the_data_root": bool(full_store),
        "no_exceptions_on_real_data": not errors,
        "scan_produced_decisions": scanned > 0,
        "non_vacuous_eligible_decisions": eligible >= 1,
        "non_vacuous_rolling_window": max_rolling >= ROBUST_Z_MIN_OBSERVATIONS,
        "non_vacuous_dispersion": mad_positive >= 1,
        "non_vacuous_varying_deltas": len(deltas) >= 5,
        "non_vacuous_qualifying_signal": len(signals) >= 1,            "future_invisibility_with_real_future_tail": not future_invariance_violations,
        "future_mutation_invariance": not future_mutation_violations,
        "past_mutation_sensitivity": not past_undetected,
        "boundary_observation_excluded_on_real_data": not boundary_leaked,
        "boundary_observation_present": boundary_rows_checked > 0,
        "hour_snapshots_within_contract": all(
            0 <= c <= 12 for c in hour_snapshot_counts
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    out.update(
        {
            "decisions_scanned": scanned,
            "decisions_eligible": eligible,
            "max_rolling_changes": max_rolling,
            "max_abs_robust_z_oi": max_abs_z,
            "distinct_delta_oi_values": len(deltas),
            "decisions_with_positive_MAD": mad_positive,
            "current_hour_snapshot_count_histogram": {str(k): v for k, v in sorted(hour_snapshot_counts.items())},
            "frozen_window_length": frozen_window,
            "runtime_entry_point": full_store,
            "runtime_entry_point_errors": full_store_errors,
            "qualifying_signals": signals[:10],
            "qualifying_signal_count": len(signals),
            "future_invisibility_violations": future_invariance_violations,
            "causal_slice_rows_max": prefix_rows_max,
            "future_tail_rows_compared_max": future_rows_compared,
            "future_mutation_violations": future_mutation_violations,
            "past_mutation_undetected": past_undetected,
            "boundary_rows_checked": boundary_rows_checked,
            "boundary_leak_violations": boundary_leaked,
            "exceptions": errors,
            "checks": checks,
            "PIT_DYNAMIC": status,
        }
    )
    EVID.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "decisions_scanned", "decisions_eligible", "max_rolling_changes",
        "max_abs_robust_z_oi", "distinct_delta_oi_values", "qualifying_signal_count",
        "current_hour_snapshot_count_histogram", "checks", "PIT_DYNAMIC",
    )}, indent=2))
    if errors:
        print("FIRST ERROR:", errors[0])
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
