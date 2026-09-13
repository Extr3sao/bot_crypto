#!/usr/bin/env python
"""INDEPENDENT VERIFIER — DYNAMIC PIT NON-VACUOUS HARNESS.

Builds a verifier-authored synthetic OI series, establishes a NON-VACUOUS
baseline (decision is ELIGIBLE and produces a real trade signal at T, with a
sufficient rolling history), then proves:

  FUTURE mutations (strictly after T)  -> DECISION_ELIGIBILITY_AT_T,
                                          FEATURE_STATE_AT_T and
                                          SIGNAL_INPUT_AT_T are BYTE-IDENTICAL
  PAST   mutations (before T)          -> at least one of them CHANGES
                                           (this is what makes the future-invariance
                                            result non-vacuous rather than a
                                            harness that cannot detect anything)

Verifier-owned. No economics, no backtest, no execution.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

VERIFIER_ROOT = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                   check=True).stdout.decode().strip()).resolve()
sys.path.insert(0, str(VERIFIER_ROOT / "src"))

SYMBOL = "TSTUSDT"
SNAP_MS = 300_000
HOUR_MS = 3_600_000
SNAPS_PER_HOUR = 12
ROWS_PER_DAY = 288

# Decision time T: day 20 at 12:00:00Z (>= 338 hours of history available)
T_DAY = "2026-03-20"
T_HOUR_UTC = 12
T = datetime.fromisoformat(T_DAY + "T%02d:00:00+00:00" % T_HOUR_UTC)
T_MS = int(T.timestamp() * 1000)


def day_base_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def build_rows(oi_scale: float = 1.0):
    """Synthetic 5m OI rows, 2026-03-01 .. 2026-03-25.

    Hourly last-snapshot OI alternates +15/+5 so the rolling MAD is non-zero
    (5.0) and the rolling median is 10.0; the decision hour receives a large
    positive jump so robust_z is well above +1.0. A slow drift is applied
    within each hour so per-day files are not degenerate.
    """
    rows = []
    start = day_base_ms("2026-03-01")
    end = day_base_ms("2026-03-26")
    hour_index = 0
    ts = start
    while ts < end:
        hour_start = ts - (ts % HOUR_MS)
        if hour_start != getattr(build_rows, "_last_hour", None):
            build_rows._last_hour = hour_start  # type: ignore[attr-defined]
        # per-hour target OI level (last snapshot of the hour)
        h = hour_start // HOUR_MS
        step = 15 if (h % 2 == 0) else 5
        prev = 1000.0 + (h - 1) * 0 + 0.0
        # cumulative level: recompute from hour index deterministically
        level = 1000.0
        for k in range(1, (h - start // HOUR_MS) + 1):
            level += 15 if ((start // HOUR_MS + k) % 2 == 0) else 5
        # decision-hour spike
        if hour_start == T_MS - HOUR_MS:
            level += 4000.0
        frac = 1.0 - ((ts - hour_start) / HOUR_MS)  # 1.0 at hour start -> 0 at hour end
        oi = (level + 3.0 * frac) * oi_scale
        rows.append({
            "timestamp_ms": ts,
            "sum_open_interest": round(oi, 6),
            "sum_open_interest_value": round(oi * 50000.0, 6),
            "unit_semantics": "BASE_ASSET_UNITS",
            "source_file": "synthetic://verifier/%s-%s.zip" % (SYMBOL, "x"),
            "source_sha256": "0" * 64,
        })
        ts += SNAP_MS
        hour_index += 1
    return rows


def write_rows(root: pathlib.Path, rows):
    sym_dir = root / SYMBOL
    if sym_dir.exists():
        shutil.rmtree(sym_dir)
    sym_dir.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list] = {}
    for r in rows:
        day = datetime.fromtimestamp(r["timestamp_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(r)
    for day, rs in by_day.items():
        p = sym_dir / ("%s-oi-5m-%s.jsonl" % (SYMBOL, day))
        with p.open("w", encoding="utf-8", newline="\n") as fh:
            for r in sorted(rs, key=lambda x: x["timestamp_ms"]):
                fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    return by_day


def observe(data_dir: pathlib.Path):
    """Compute the three authority artifacts at T, plus the signal."""
    from trading_bot.research.oi_dataset_v2 import decision_eligibility_at_v2, oi_state_at_ms
    from trading_bot.research.h6.feature_engine import H6FeatureEngine, CompletedHourPrice
    from trading_bot.research.h6.feature_engine import ObservedOI, CompletedHourOI

    state = oi_state_at_ms(T_MS, SYMBOL, data_dir)            # SIGNAL_INPUT_AT_T
    elig = decision_eligibility_at_v2(T_MS, SYMBOL, data_dir)  # DECISION_ELIGIBILITY_AT_T

    # FEATURE_STATE_AT_T via the frozen engine, fed only causally-derived inputs
    snaps = [ObservedOI(oi_time=datetime.fromtimestamp(int(r["timestamp_ms"]) / 1000, tz=timezone.utc),
                        sum_open_interest=float(r["sum_open_interest"]),
                        sum_open_interest_value=float(r["sum_open_interest_value"]))
             for r in state]
    # NOTE (verifier finding FIND-PIT-01): the frozen helper
    # `trading_bot.research.h6.eligibility.build_completed_hour_oi` is BROKEN — it
    # calls `.start`/`.end` on the plain tuple returned by `_hour_close_boundaries`,
    # so it raises AttributeError for ANY non-empty snapshot input. This harness
    # therefore performs the identical completed-hour aggregation itself, inline,
    # rather than working around the bug by calling the broken public API.
    def _completed_hour(snaps_in, hour_close):
        # HALF-OPEN [hour_start, hour_close) — this matches the window semantics of
        # decision_eligibility_at_v2 (_snapshots_in_window_v2), and yields exactly 12
        # 5m snapshots for a grid-aligned hour. (The frozen helper used INCLUSIVE
        # bounds, which on a :00-aligned grid yields 13 -> snapshot_count != 12.)
        lo, hi = hour_close - timedelta(hours=1), hour_close
        within = [s for s in snaps_in if lo <= s.oi_time < hi]
        distinct = {s.oi_time: s for s in within}
        if not distinct:
            return CompletedHourOI(hour_close_time=hour_close, oi_last_snapshot=0.0, snapshot_count=0)
        last = sorted(distinct.values(), key=lambda s: s.oi_time)[-1]
        return CompletedHourOI(hour_close_time=hour_close,
                               oi_last_snapshot=last.sum_open_interest,
                               snapshot_count=len(distinct))

    cur = _completed_hour(snaps, T)
    prev = _completed_hour(snaps, T - timedelta(hours=1))

    # Build hourly aggregates directly from the causal snapshots (past only)
    by_hour: dict[datetime, list] = {}
    for s in snaps:
        if s.oi_time > T:
            continue
        hh = s.oi_time.replace(minute=0, second=0, microsecond=0)
        by_hour.setdefault(hh, []).append(s)
    hours_sorted = sorted(by_hour)
    changes: list[tuple[datetime, float]] = []
    for a, b in zip(hours_sorted, hours_sorted[1:]):
        last_a = sorted(by_hour[a], key=lambda s: s.oi_time)[-1]
        last_b = sorted(by_hour[b], key=lambda s: s.oi_time)[-1]
        changes.append((b, last_b.sum_open_interest - last_a.sum_open_interest))
    changes = [c for c in changes if c[0] < T]

    price = CompletedHourPrice(bucket_close_time=T, open=100.0, close=101.0)
    feat = H6FeatureEngine(symbol=SYMBOL).compute_feature_state(
        SYMBOL, T, price, cur, prev, changes)
    from trading_bot.research.h6.feature_engine import compute_signal
    sig = compute_signal(feat)

    def ser(o):
        try:
            import dataclasses
            if dataclasses.is_dataclass(o):
                return json.dumps(dataclasses.asdict(o), sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            pass
        return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)

    return {
        "signal_input_at_t": ser(state),
        "decision_eligibility_at_t": ser(elig),
        "feature_state_at_t": ser(feat),
        "signal": ser(sig),
        "raw": {
            "eligible": elig.get("eligible"),
            "reason": elig.get("reason"),
            "rolling_n": elig.get("rolling_n"),
            "n_current_snapshots": elig.get("n_current_snapshots"),
            "feature_eligible": getattr(feat, "decision_eligible", None),
            "robust_z_oi": getattr(feat, "robust_z_oi", None),
            "delta_oi": getattr(feat, "delta_oi", None),
            "signal": ser(sig),
            "causal_rows": len(state),
            "max_ts_le_T": max((int(r["timestamp_ms"]) for r in state), default=None),
        },
    }


def h(d: dict) -> dict:
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest()
            for k, v in d.items() if isinstance(v, str)}


def main():
    out = {
        "verifier_type": "INDEPENDENT_DYNAMIC_PIT_NONVACUOUS_HARNESS_V3",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audited_target_commit": "a5487164803fb601f87f2cd4c865929c30da274e",
        "symbol": SYMBOL,
        "decision_time_utc": T.isoformat(),
        "synthetic": True,
        "real_data_touched": False,
        "economics": {"H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False},
        "mutations": [],
    }

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v3_pit_"))
    try:
        base_rows = build_rows()
        write_rows(tmp, base_rows)
        base = observe(tmp)
        out["baseline"] = {"hashes": h({k: v for k, v in base.items() if isinstance(v, str)}),
                           **base["raw"]}

        # NON-VACUITY GATE ---------------------------------------------------
        nonvacuous = (
            base["raw"]["eligible"] is True
            and base["raw"]["feature_eligible"] is True
            and (base["raw"]["rolling_n"] or 0) >= 336
            and "NO_SIGNAL" not in str(base["raw"]["signal"])
            and (base["raw"]["robust_z_oi"] is not None and base["raw"]["robust_z_oi"] >= 1.0)
        )
        out["non_vacuity"] = {
            "baseline_eligible": base["raw"]["eligible"],
            "baseline_reason": base["raw"]["reason"],
            "baseline_rolling_n": base["raw"]["rolling_n"],
            "baseline_feature_eligible": base["raw"]["feature_eligible"],
            "baseline_robust_z_oi": base["raw"]["robust_z_oi"],
            "baseline_delta_oi": base["raw"]["delta_oi"],
            "baseline_signal": base["raw"]["signal"],
            "baseline_causal_rows": base["raw"]["causal_rows"],
            "max_causal_timestamp_le_T": base["raw"]["max_ts_le_T"] <= T_MS,
            "NON_VACUOUS": nonvacuous,
        }

        def check(name, rows, expect_change, mutate_desc):
            write_rows(tmp, rows)
            got = observe(tmp)
            bg, gg = h({k: v for k, v in base.items() if isinstance(v, str)}), \
                     h({k: v for k, v in got.items() if isinstance(v, str)})
            changed = {k: (bg[k] != gg[k]) for k in bg}
            ok = any(changed.values()) if expect_change else not any(changed.values())
            out["mutations"].append({
                "mutation": name, "description": mutate_desc,
                "expected": "CHANGED" if expect_change else "UNCHANGED",
                "per_artifact_changed": changed,
                "result": "PASS" if ok else "FAIL",
                "observed_eligible": got["raw"]["eligible"],
                "observed_signal": got["raw"]["signal"],
            })
            return got

        # FUTURE mutations ---------------------------------------------------
        fut = [dict(r) for r in base_rows]
        which = None
        for r in fut:
            if r["timestamp_ms"] > T_MS:
                r["sum_open_interest"] = float(r["sum_open_interest"]) * 3.0
                r["sum_open_interest_value"] = float(r["sum_open_interest_value"]) * 3.0
                which = r["timestamp_ms"]
                break
        check("future_row_value_mutation",
              fut, False,
              "a row strictly after T (%s) scaled x3" % which)

        fut2 = [dict(r) for r in base_rows]
        del fut2[-60:]
        fut2.append({
            "timestamp_ms": T_MS + 10 * HOUR_MS,
            "sum_open_interest": 9_999_999.0,
            "sum_open_interest_value": 9_999_999.0,
            "unit_semantics": "BASE_ASSET_UNITS",
            "source_file": "synthetic://verifier/added",
            "source_sha256": "0" * 64,
        })
        check("future_row_addition", fut2, False,
              "60 later rows removed and one row appended far after T")

        # PAST mutations (must be detectable -> proves harness sensitivity) --
        past = [dict(r) for r in base_rows]
        idx = None
        for i in range(len(past) - 1, -1, -1):
            if past[i]["timestamp_ms"] < T_MS - HOUR_MS:
                past[i]["sum_open_interest"] = float(past[i]["sum_open_interest"]) * 1.5
                idx = past[i]["timestamp_ms"]
                break
        check("past_row_value_mutation", past, True,
              "a row strictly before T (%s) scaled x1.5" % idx)

        pasteg = [dict(r) for r in base_rows]
        lo = T_MS - HOUR_MS
        pasteg = [r for r in pasteg if not (lo <= r["timestamp_ms"] < T_MS)]
        check("past_gap_before_T", pasteg, True,
              "current decision hour's 12 snapshots deleted (gap immediately before T)")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    future_muts = [m for m in out["mutations"] if m["expected"] == "UNCHANGED"]
    past_muts = [m for m in out["mutations"] if m["expected"] == "CHANGED"]
    out["summary"] = {
        "non_vacuous_baseline": nonvacuous,
        "future_mutations_all_invariant": all(m["result"] == "PASS" for m in future_muts),
        "past_mutations_all_detected": all(m["result"] == "PASS" for m in past_muts),
        "future_mutations": len(future_muts),
        "past_mutations": len(past_muts),
    }
    ok = (nonvacuous
          and out["summary"]["future_mutations_all_invariant"]
          and out["summary"]["past_mutations_all_detected"])
    out["DYNAMIC_PIT_NON_VACUOUS_HARNESS"] = "PASS" if ok else "FAIL"

    print(json.dumps(out, indent=2))
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("WROTE", dest, file=sys.stderr)


if __name__ == "__main__":
    main()
