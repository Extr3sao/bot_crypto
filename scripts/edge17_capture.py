"""edge17_capture — coverage, continuity and the storage the collector really costs.

WP-EDGE-017/P0.1-P0.2. Three defects are answered here, each from measurement:

1. **coverage.** WP-EDGE-016 reported ``captured_bars_per_symbol`` as 0 or 1 by
   reducing the slice to ``{symbol: last_timestamp}``; a symbol holding thirty
   bars was indistinguishable from one holding a single bar. The ladder below is
   built per ``(symbol, hour)`` and its totals are recomputed from that ladder.
2. **independence.** The slice is what the collector writes. The ledger is a
   separate append-only record of what each capture attempt saw, so coverage can
   be re-derived from the ledger and compared with the slice instead of trusting
   one file to describe itself.
3. **storage.** The guard was fed the 240 MB/h fallback measured from a
   different capture lane, and refused a window the collector never needed. The
   byte rate here is measured from this collector's own artifacts — bytes per
   bar, bytes per ledger line, the manifest rewrite — and handed to the existing
   ``plan_window`` with its reserves, stress multiplier and limits untouched.

    python scripts/edge17_capture.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.disk_budget import (
    DECLARED_FALLBACK_BYTES_PER_HOUR,
    DEFAULT_RESERVE_BYTES,
    DEFAULT_STRESS_MULTIPLIER,
    free_bytes,
    plan_window,
)
from trading_bot.research.oos_capture import (
    PERIOD_MS_1H,
    coverage_ladder,
    expected_closed_opens,
    read_slice,
    row_key,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-017"
OUT_15 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"
SLICE = OUT_15 / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"
LEDGER = OUT_15 / "scratch" / "OOS_CAPTURE_LEDGER.jsonl"
MANIFEST = OUT_15 / "OOS_CAPTURE_MANIFEST_V2.json"
PREREG = OUT_15 / "OOS_PREREGISTRATION_V2.json"
LANE_COVERAGE = OUT / "experimental_paper" / "COVERAGE_LEDGER.jsonl"

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
WINDOW_HOURS = 24.0
VALVE_BYTES = 64 * 1024 * 1024


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _longest_run(
    opens: list[int], present: set[int], period_ms: int = PERIOD_MS_1H
) -> dict[str, Any]:
    """Longest run of consecutive expected hours that actually reached a stage."""
    best = 0
    current = 0
    best_start: int | None = None
    start: int | None = None
    for open_ms in opens:
        if open_ms in present:
            if current == 0:
                start = open_ms
            current += 1
            if current > best:
                best = current
                best_start = start
        else:
            current = 0
            start = None
    return {
        "hours": best,
        "from_ms": best_start,
        "from_utc": _utc(best_start) if best_start is not None else None,
        "to_utc": _utc(best_start + (best - 1) * period_ms) if best_start is not None else None,
    }


def measure_storage(*, now_ms: int) -> dict[str, Any]:
    """The collector's real bytes, and what the existing guard says about them."""
    slice_bytes = SLICE.stat().st_size if SLICE.is_file() else 0
    slice_rows = len(read_slice(SLICE))
    ledger_bytes = LEDGER.stat().st_size if LEDGER.is_file() else 0
    ledger_lines = len(_rows(LEDGER))
    manifest_bytes = MANIFEST.stat().st_size if MANIFEST.is_file() else 0

    bytes_per_bar = slice_bytes / slice_rows if slice_rows else 0.0
    bytes_per_ledger_line = ledger_bytes / ledger_lines if ledger_lines else 0.0
    # one bar per symbol per closed hour, three symbols; the ledger grows by one
    # line per symbol per run; the manifest is rewritten (not appended) once per run
    rate = bytes_per_bar * len(SYMBOLS)
    overhead = bytes_per_ledger_line * len(SYMBOLS) + manifest_bytes
    peak = 2 * slice_bytes  # the atomic write holds the old and the new file at once

    plan = plan_window(
        hours=WINDOW_HOURS,
        collector_max_bytes=VALVE_BYTES,
        free=free_bytes(REPO),
        rate_bytes_per_hour=rate,
        rate_source=(
            "measured from this collector's own slice, ledger and manifest at the commit that "
            "produced this report; not the 240 MB/h cross-lane fallback"
        ),
        overhead_bytes_per_hour=overhead,
    )
    return {
        "schema_version": "EDGE17_STORAGE_MEASUREMENT_V1",
        "measured_at_utc": _utc(now_ms),
        "slice": {
            "path": SLICE.relative_to(REPO).as_posix(),
            "bytes": slice_bytes,
            "rows": slice_rows,
            "bytes_per_row": round(bytes_per_bar, 3),
        },
        "ledger": {
            "path": LEDGER.relative_to(REPO).as_posix(),
            "bytes": ledger_bytes,
            "lines": ledger_lines,
            "bytes_per_line": round(bytes_per_ledger_line, 3),
        },
        "manifest": {"bytes": manifest_bytes, "rewritten_per_run": True},
        "rate_bytes_per_hour": round(rate, 3),
        "overhead_bytes_per_hour": round(overhead, 3),
        "effective_bytes_per_hour": round(rate + overhead, 3),
        "peak_transient_bytes_during_atomic_write": peak,
        "declared_fallback_bytes_per_hour": DECLARED_FALLBACK_BYTES_PER_HOUR,
        "fallback_overstatement_factor": round(
            DECLARED_FALLBACK_BYTES_PER_HOUR / (rate + overhead), 1
        )
        if rate + overhead
        else None,
        "guard_inputs_unchanged": {
            "stress_multiplier": DEFAULT_STRESS_MULTIPLIER,
            "reserve_bytes": DEFAULT_RESERVE_BYTES,
            "collector_max_bytes": VALVE_BYTES,
            "hours": WINDOW_HOURS,
            "note": "the guard's own defaults; this package changed no reserve, multiplier or limit",
        },
        "guard_plan": plan.as_dict(),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    prereg = _load(PREREG) or {}
    freeze_ms = int(prereg.get("frozen_at_epoch_ms", 0))
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    expected = expected_closed_opens(freeze_ms, now_ms)
    slice_rows = read_slice(SLICE)
    lane_rows = _rows(LANE_COVERAGE)

    ladder, totals = coverage_ladder(
        symbols=SYMBOLS, expected_opens=expected, slice_rows=slice_rows, lane_rows=lane_rows
    )

    ledger_rows = _rows(LEDGER)
    ledger_keys: set[tuple[str, int]] = set()
    #: first instant the ledger recorded each bar, so a backfilled hour is not
    #: confused with one that was captured at its close
    first_seen_ms: dict[tuple[str, int], int] = {}
    for entry in ledger_rows:
        seen_at = int(entry.get("capture_started_unix_ns", 0)) // 1_000_000
        for symbol, payload in (entry.get("symbols") or {}).items():
            for open_ms in payload.get("opens", []):
                key = (str(symbol), int(open_ms))
                ledger_keys.add(key)
                previous = first_seen_ms.get(key)
                if previous is None or seen_at < previous:
                    first_seen_ms[key] = seen_at
    slice_keys = {row_key(row) for row in slice_rows}

    # WP-EDGE-017F/P1: every ladder row carries its provenance, not just a stage.
    # A bar is "received at close" only if the collector saw it inside the first
    # hour after it closed; anything later is a recovery, and anything never seen
    # is absent. A bar first seen before its close would be an integrity failure.
    for row in ladder:
        key = (str(row["symbol"]), int(row["open_ms"]))
        seen_at = first_seen_ms.get(key)
        if seen_at is None:
            row["capture_class"] = "ABSENT"
            row["first_seen_utc"] = None
            row["capture_lag_hours"] = None
            continue
        lag_ms = seen_at - (int(row["open_ms"]) + PERIOD_MS_1H)
        row["capture_class"] = (
            "FIRST_SEEN_BEFORE_CLOSE"
            if lag_ms < 0
            else "RECEIVED_AT_CLOSE"
            if lag_ms < PERIOD_MS_1H
            else "RECOVERED_LATER"
        )
        row["first_seen_utc"] = _utc(seen_at)
        row["capture_lag_hours"] = round(lag_ms / PERIOD_MS_1H, 3)

    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol in SYMBOLS:
        opens = [row["open_ms"] for row in ladder if row["symbol"] == symbol]
        observed = {
            row["open_ms"] for row in ladder if row["symbol"] == symbol and not row["missing"]
        }
        evaluated = {
            row["open_ms"]
            for row in ladder
            if row["symbol"] == symbol and "EVALUATED" in row["stages"]
        }
        missing = [row["open_ms"] for row in ladder if row["symbol"] == symbol and row["missing"]]
        lags = [
            first_seen_ms[(symbol, open_ms)] - (open_ms + PERIOD_MS_1H)
            for open_ms in observed
            if (symbol, open_ms) in first_seen_ms
        ]
        classes = [row["capture_class"] for row in ladder if row["symbol"] == symbol]
        per_symbol[symbol] = {
            "captured_bars": sum(1 for row in slice_rows if row["symbol"] == symbol),
            "received_at_close": classes.count("RECEIVED_AT_CLOSE"),
            "recovered_later": classes.count("RECOVERED_LATER"),
            "absent": classes.count("ABSENT"),
            "first_seen_before_close": classes.count("FIRST_SEEN_BEFORE_CLOSE"),
            "captured_at_close_or_within_one_hour": sum(
                1 for lag in lags if 0 <= lag < PERIOD_MS_1H
            ),
            "captured_by_backfill_later": sum(1 for lag in lags if lag >= PERIOD_MS_1H),
            "max_capture_lag_hours": round(max(lags) / PERIOD_MS_1H, 3) if lags else None,
            "expected_closed_bars": len(opens),
            "observed": len(observed),
            "evaluated": len(evaluated),
            "missing": len(missing),
            "missing_opens_utc": [_utc(open_ms) for open_ms in missing][:24],
            "longest_consecutive_observed": _longest_run(opens, observed),
            "longest_consecutive_evaluated": _longest_run(opens, evaluated),
        }

    first_capture = ledger_rows[0].get("captured_at_utc") if ledger_rows else None
    integrity: dict[str, Any] = {
        "capture_provenance": {
            "reading": (
                "a bar whose first ledger record is later than its close was recovered by the "
                "append-only collector, not observed live at that hour; both are post-freeze "
                "data the protocol never saw, but only the first is live capture"
            ),
            "classes": ["RECEIVED_AT_CLOSE", "RECOVERED_LATER", "ABSENT"],
            "rule": (
                "RECEIVED_AT_CLOSE: first ledger record within [close, close + 1h); "
                "RECOVERED_LATER: first record at or after close + 1h; ABSENT: never recorded. "
                "FIRST_SEEN_BEFORE_CLOSE is an integrity failure and is counted separately."
            ),
            "received_at_close_total": sum(
                bucket["received_at_close"] for bucket in per_symbol.values()
            ),
            "recovered_later_total": sum(
                bucket["recovered_later"] for bucket in per_symbol.values()
            ),
            "absent_total": sum(bucket["absent"] for bucket in per_symbol.values()),
            "first_seen_before_close_total": sum(
                bucket["first_seen_before_close"] for bucket in per_symbol.values()
            ),
            "backfilled_total": sum(
                bucket["captured_by_backfill_later"] for bucket in per_symbol.values()
            ),
        },
        "schema_version": "EDGE17_CAPTURE_INTEGRITY_V1",
        "generated_at_utc": _utc(now_ms),
        "freeze_utc": prereg.get("frozen_at_utc"),
        "slice": {
            "path": SLICE.relative_to(REPO).as_posix(),
            "rows": len(slice_rows),
            "unique_keys": len(slice_keys),
            "duplicates": len(slice_rows) - len(slice_keys),
            "sha256_manifest": (_load(MANIFEST) or {})
            .get("append_only", {})
            .get("slice_sha256_after"),
        },
        "ledger": {
            "path": LEDGER.relative_to(REPO).as_posix(),
            "lines": len(ledger_rows),
            "first_capture_utc": first_capture,
            "keys_recorded": len(ledger_keys),
            "slice_is_subset_of_ledger": slice_keys <= ledger_keys,
            "ledger_only_keys": len(ledger_keys - slice_keys),
            "reading": (
                "the ledger is written by the collector as a separate append-only file; a slice "
                "row the ledger never recorded is evidence the slice was not produced by this "
                "collector"
            ),
        },
        "expected_closed_bars_per_symbol": len(expected),
        "expected_opens_utc": [_utc(open_ms) for open_ms in expected],
        "totals": totals,
        "per_symbol": per_symbol,
        "identity": {
            "rule": "expected == observed + missing, per symbol and in total",
            "holds": totals["identity_holds"],
            "per_symbol_holds": all(
                bucket["expected"] == bucket["observed"] + bucket["missing"]
                for bucket in totals["per_symbol"].values()
            ),
        },
        "classification_rule": (
            "a bar no collector observed is MISSING_NO_COLLECTOR; it is never a quiet market. "
            "An observed bar with no proposal is NO_SIGNAL, which is a decision."
        ),
        "ladder": ladder,
    }
    (OUT / "CAPTURE_INTEGRITY.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    storage = measure_storage(now_ms=now_ms)
    (OUT / "STORAGE_MEASUREMENT.json").write_text(
        json.dumps(storage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    plan = storage["guard_plan"]
    decision: dict[str, Any] = {
        "schema_version": "EDGE17_SCHEDULER_DECISION_V1",
        "disk_guard_state_for_this_collector": plan["state"],
        "measured_rate_mb_per_hour": round(storage["effective_bytes_per_hour"] / 1e6, 6),
        "fallback_rate_mb_per_hour": DECLARED_FALLBACK_BYTES_PER_HOUR / 1e6,
        "reading": (
            "on the measured rate the guard no longer blocks this collector: WP-EDGE-016's "
            "CAPTURE_BLOCKED_DISK was a misdiagnosis produced by pricing a 3-symbol hourly "
            "JSONL writer with another lane's 240 MB/h corpus reader. The host is still 99% "
            "full; that is a separate fact about the volume, not about this collector."
        ),
        "still_blocked_by": [
            "no scheduler is authorized: creating a Windows scheduled task needs administrator "
            "privileges, which this package does not have and did not attempt",
            "a GitHub cron cannot run it: the working copy and the holdout are local",
        ],
        "delivered_instead": (
            "manual collector, append-only, resumable and idempotent: "
            "scripts/edge15_oos_preregistration.py --capture"
        ),
        "status": "PROSPECTIVE_CAPTURE_MANUAL_NOT_SCHEDULED",
        "disk_is_no_longer_the_reason": plan["state"]
        not in ("INSUFFICIENT_FREE_SPACE", "INCOHERENT_BUDGET"),
    }
    (OUT / "SCHEDULER_DECISION.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# WP-EDGE-017 — prospective coverage and continuity",
        "",
        f"*as of {_utc(now_ms)}, freeze {prereg.get('frozen_at_utc')}*",
        "",
        "## The numbers, per symbol",
        "",
        "| symbol | captured bars | expected closed | observed | evaluated | missing | "
        "longest observed run | longest evaluated run |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for symbol, bucket in per_symbol.items():
        lines.append(
            f"| {symbol} | {bucket['captured_bars']} | {bucket['expected_closed_bars']} | "
            f"{bucket['observed']} | {bucket['evaluated']} | {bucket['missing']} | "
            f"{bucket['longest_consecutive_observed']['hours']} h | "
            f"{bucket['longest_consecutive_evaluated']['hours']} h |"
        )
    lines += [
        "",
        f"**Identity** `expected = observed + missing`: "
        f"{'holds' if integrity['identity']['holds'] and integrity['identity']['per_symbol_holds'] else 'FAILS'}.",
        "",
        "## Why the missing hours are missing",
        "",
        "The collector is manual. Every hour between the freeze and the first manual run is",
        "`MISSING_NO_COLLECTOR`; those bars were never observed by anything in this project,",
        "so they are missing evidence and not quiet market time. The ledger records the",
        "first capture at",
        f"`{first_capture}`, and the slice is a subset of what the ledger recorded:",
        f"`{integrity['ledger']['slice_is_subset_of_ledger']}`.",
        "",
        "## What the collector costs",
        "",
        f"- measured: **{storage['effective_bytes_per_hour']:.1f} B/h** "
        f"({storage['effective_bytes_per_hour'] / 1e6:.6f} MB/h) for three symbols, hourly;",
        f"- the 240 MB/h declared fallback overstates it by "
        f"**{storage['fallback_overstatement_factor']}x**;",
        f"- the existing guard, with its own reserve and 1.5x stress, returns "
        f"**{plan['state']}** for a 24 h window and a 64 MiB valve;",
        f"- peak transient cost of the atomic write: "
        f"{storage['peak_transient_bytes_during_atomic_write']} B (old and new file).",
        "",
        f"Disk is **{'no longer' if decision['disk_is_no_longer_the_reason'] else 'still'}** "
        "the reason capture is not automated.",
        "",
        "## Runbook",
        "",
        "```bash",
        'cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture',
        "# appends only new closed bars; re-running is byte-identical when nothing new closed",
        "```",
        "",
    ]
    (OUT / "PROSPECTIVE_COVERAGE.md").write_text("\n".join(lines), encoding="utf-8")

    print(
        f"[17a] expected {len(expected)}/symbol, observed {totals['observed_symbol_bars']}, "
        f"evaluated {totals['evaluated_symbol_bars']}, missing {totals['expected_symbol_bars'] - totals['observed_symbol_bars']}"
    )
    print(f"[17a] measured {storage['effective_bytes_per_hour']:.1f} B/h, guard {plan['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
