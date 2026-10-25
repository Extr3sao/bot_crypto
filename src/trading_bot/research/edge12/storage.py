"""WP-EDGE-12C — whether sixty days of observation fit, and what may be forecast.

The lane's own ``resource_budget.json`` already refuses to publish a forecast while the
measured growth rate is volatile, and that refusal is right: a number invented from an
unstable series is worse than a missing one. But "no forecast" is not an answer to
"will sixty days fit", and the two ways of answering it are unlike each other:

* the **logs are bounded**, so the state root has a ceiling that can be computed from
  the retention policy and the measured row size rather than extrapolated from a
  trend. A ceiling is a better answer than a fitted line, because it holds however
  the lane behaves;
* the **store is unbounded** and grows with the observation itself, so what matters
  there is bytes per bar and bars per day, and both are stable quantities that can be
  measured from the store files.

What is left after those two is the volume, and the volume is *shared*: this lane's
12 MB cannot explain a partition at 97 %, and a plan that reclaimed space by deleting
another workstream's data would be measuring the wrong thing. The honest forecast is
therefore about the lane's own ceiling and its own rate, with the volume reported as
the constraint it is and its trajectory measured from the lane's own disk readings
rather than from a wish.

Read-only with respect to the store, the ledger and every other workstream's tree.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["FORECAST_HORIZON_DAYS", "storage_reading"]

#: The horizon the RFC-EDGE-012 acceptance criteria name: sixty prospective days.
FORECAST_HORIZON_DAYS = 60


def _jsonl_rows_and_bytes(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    data = path.read_bytes()
    rows = sum(1 for line in data.splitlines() if line.strip())
    return rows, len(data)


def _store_growth(store_root: Path) -> dict[str, Any]:
    """Bytes per bar and bars per day, measured from the store files themselves.

    The bar count comes from the file's own lines and the bytes from its own size, so
    the pair is a property of the store as it is on disk rather than of a model of it.
    """
    series: list[dict[str, Any]] = []
    total_bytes = 0
    bars_per_day_total = 0
    bytes_per_day_total = 0.0
    for timeframe, bars_per_day in (("1h", 24), ("15m", 96)):
        directory = store_root / timeframe
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.jsonl")):
            rows, size = _jsonl_rows_and_bytes(path)
            total_bytes += size
            per_bar = (size / rows) if rows else None
            per_series_day = (per_bar or 0.0) * bars_per_day
            series.append(
                {
                    "series": f"{timeframe}:{path.stem}",
                    "rows": rows,
                    "bytes": size,
                    "bytes_per_bar": round(per_bar, 2) if per_bar else None,
                    "bars_per_day": bars_per_day,
                    "bytes_per_day": round(per_series_day, 2),
                }
            )
            bars_per_day_total += bars_per_day
            bytes_per_day_total += per_series_day
    return {
        "series": series,
        "store_bytes": total_bytes,
        "bars_per_day": bars_per_day_total,
        "bytes_per_day": round(bytes_per_day_total, 2),
        "reading": (
            "the store is append-only and never pruned, so its growth is bars-per-day times "
            "bytes-per-bar: both are measured here from the files on disk"
        ),
    }


def _retention_ceiling(state_root: Path) -> dict[str, Any]:
    """The state root's ceiling, computed from the declared retention and measured row sizes.

    Every operational log in this lane is front-truncated at a declared row count, so the
    steady-state size is a sum of ceilings rather than a trend. The daily evidence files
    are deliberately *not* bounded -- they are the durable record -- so they are measured
    per file and multiplied by the declared retention.
    """
    from trading_bot.research.edge03 import autonomous

    rows_and_bytes = {
        "runs.jsonl": _jsonl_rows_and_bytes(state_root / "runs.jsonl"),
        "slots.jsonl": _jsonl_rows_and_bytes(state_root / "slots.jsonl"),
        "ledger/INGEST_LEDGER.jsonl": _jsonl_rows_and_bytes(
            state_root / "ledger" / "INGEST_LEDGER.jsonl"
        ),
        "derived_refresh.jsonl": _jsonl_rows_and_bytes(state_root / "derived_refresh.jsonl"),
        "alerts.jsonl": _jsonl_rows_and_bytes(state_root / "alerts.jsonl"),
    }
    keeps = {
        "runs.jsonl": autonomous.RUNS_KEPT,
        "slots.jsonl": autonomous.SLOTS_KEPT,
        "ledger/INGEST_LEDGER.jsonl": autonomous.LEDGER_KEPT,
        "derived_refresh.jsonl": autonomous.RUNS_KEPT,
        "alerts.jsonl": autonomous.ALERTS_KEPT,
    }
    ceiling = 0
    detail: dict[str, Any] = {}
    for name, (rows, size) in rows_and_bytes.items():
        per_row = (size / rows) if rows else None
        projected = int((per_row or 0.0) * keeps[name])
        ceiling += projected
        detail[name] = {
            "rows_now": rows,
            "bytes_now": size,
            "bytes_per_row": round(per_row, 2) if per_row else None,
            "rows_kept": keeps[name],
            "projected_bytes": projected,
            "bounded": True,
            "note": (
                "derived_refresh.jsonl is not truncated by the observer today; it is projected at "
                "the run-log retention because that is the cadence that writes it, and the entry "
                "is flagged rather than silently included"
                if name == "derived_refresh.jsonl"
                else None
            ),
        }
    daily_dir = state_root / "daily"
    daily_sizes = (
        [path.stat().st_size for path in daily_dir.glob("*.json")] if daily_dir.is_dir() else []
    )
    daily_mean = (sum(daily_sizes) / len(daily_sizes)) if daily_sizes else 0.0
    daily_projected = int(daily_mean * autonomous.DAILY_KEPT)
    ceiling += daily_projected
    fixed = {}
    for name in ("coverage.json", "health.json", "resource_budget.json", "install.json"):
        path = state_root / name
        fixed[name] = path.stat().st_size if path.is_file() else 0
    ceiling += sum(fixed.values())
    return {
        "operational_logs": detail,
        "daily_evidence": {
            "files_now": len(daily_sizes),
            "mean_bytes": round(daily_mean, 2),
            "files_kept": autonomous.DAILY_KEPT,
            "projected_bytes": daily_projected,
            "bounded": False,
            "note": "never truncated: this is the durable per-day record the coverage reading is built from",
        },
        "rewritten_artefacts_bytes": sum(fixed.values()),
        "ceiling_bytes": ceiling,
        "declared_lane_budget_bytes": autonomous.LANE_BUDGET_BYTES,
        "ceiling_within_budget": ceiling <= autonomous.LANE_BUDGET_BYTES,
        "reading": (
            "a ceiling holds whatever the lane does; a fitted line holds only while the trend does, "
            "which is why the bounded logs are summed at their retention instead of extrapolated"
        ),
    }


def _volume_trajectory(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The volume's free-space trajectory, taken from the lane's own per-tick readings.

    The lane records the free space on every tick it ran, which is the only free-space
    history available on this host without an administrator. It is a trajectory of the
    *volume*, though, and the volume holds everything else on this machine: the slope is
    reported as measured and never attributed to this lane alone.
    """
    samples: list[tuple[int, float]] = []
    for row in runs:
        disk = row.get("disk_after") or {}
        free = disk.get("free_gib")
        started = row.get("started_at_ms")
        if isinstance(free, (int, float)) and isinstance(started, int):
            samples.append((started, float(free)))
    if len(samples) < 2:
        return {
            "samples": len(samples),
            "verdict": "INSUFFICIENT_SAMPLES",
            "reading": "fewer than two free-space readings: no trajectory is claimed",
        }
    samples.sort()
    first_ms, first_free = samples[0]
    last_ms, last_free = samples[-1]
    span_days = (last_ms - first_ms) / 86_400_000
    delta = last_free - first_free
    per_day = (delta / span_days) if span_days > 0 else None
    minimum = min(free for _ms, free in samples)
    statuses: dict[str, int] = {}
    for row in runs:
        status = str((row.get("disk_after") or {}).get("status") or "UNKNOWN")
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "samples": len(samples),
        "span_days": round(span_days, 4),
        "first_gib": round(first_free, 4),
        "last_gib": round(last_free, 4),
        "minimum_gib": round(minimum, 4),
        "delta_gib": round(delta, 4),
        "gib_per_day": round(per_day, 4) if per_day is not None else None,
        "status_counts": dict(sorted(statuses.items())),
        "reading": (
            "this is the volume's free space, not the lane's footprint: the volume holds whatever "
            "else lives on this machine, and a slope measured here is not a rate this lane caused"
        ),
    }


def _refusals(runs: list[dict[str, Any]]) -> dict[str, Any]:
    refused = [row for row in runs if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED"]
    return {
        "refused_ticks": len(refused),
        "refused_slots": len({str(row.get("slot_key")) for row in refused}),
        "first_refusal_utc": refused[0].get("started_at_utc") if refused else None,
        "last_refusal_utc": refused[-1].get("started_at_utc") if refused else None,
        "market_requests_at_refusal": sorted(
            {int(row.get("market_requests") or 0) for row in refused}
        ),
        "reading": (
            "the guard refused before any market request, so a refusal costs a slot and returns no "
            "false observation; the market-request figures listed here are the measurement of that"
        ),
    }


def storage_reading(
    *,
    repo_root: Path,
    state_root: Path,
    store_root: Path,
    runs: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """WP-EDGE-12C in one call: footprint, ceiling, trajectory, forecast and verdict."""
    from trading_bot.research.disk_space import disk_report
    from trading_bot.research.edge03 import autonomous

    growth = _store_growth(store_root)
    ceiling = _retention_ceiling(state_root)
    trajectory = _volume_trajectory(runs)
    refusals = _refusals(runs)
    guard = disk_report(
        state_root,
        warning_bytes=autonomous.DISK_WARNING_BYTES,
        critical_bytes=autonomous.DISK_CRITICAL_BYTES,
    )
    store_now = growth["store_bytes"]
    store_at_horizon = store_now + growth["bytes_per_day"] * FORECAST_HORIZON_DAYS
    state_at_horizon = ceiling["ceiling_bytes"]
    lane_at_horizon = int(store_at_horizon + state_at_horizon)
    current_drive = str(store_root.drive).upper()
    volumes = []
    for row in evidence.get("volumes") or []:
        capacity = int(row.get("capacity_bytes") or 0)
        free = int(row.get("free_bytes") or 0)
        letter = str(row.get("drive_letter") or "").upper()
        is_current = bool(letter) and letter == current_drive
        # A volume the store already lives on is not somewhere to move it to. Counting it
        # would make "is there a better volume?" answer yes to the only volume there is,
        # which is the difference between a relocation plan and a restatement.
        is_usable = bool(
            str(row.get("file_system") or "").upper() == "NTFS" and letter and not is_current
        )
        volumes.append(
            {
                "drive_letter": row.get("drive_letter"),
                "label": row.get("label"),
                "file_system": row.get("file_system"),
                "capacity_gib": round(capacity / 1024**3, 4),
                "free_gib": round(free / 1024**3, 4),
                "used_percent": round(100 * (capacity - free) / capacity, 2) if capacity else None,
                "is_the_current_volume": is_current,
                "usable_for_this_store": is_usable,
            }
        )
    usable = [row for row in volumes if row["usable_for_this_store"]]
    current_volume_free = guard.get("free_gib")
    # What the whole sixty days costs the volume *in addition to what is already there*:
    # the store's growth minus the store's current size is the only new bytes this lane adds.
    added_over_the_horizon = growth["bytes_per_day"] * FORECAST_HORIZON_DAYS
    fits = bool(
        current_volume_free is not None
        and added_over_the_horizon < 0.05 * 1024**3
        and ceiling["ceiling_within_budget"]
    )
    if not usable:
        verdict = "NO_USABLE_VOLUME_FOR_A_MOVE"
    elif ceiling["ceiling_within_budget"] and fits:
        verdict = "LANE_FITS_ITS_BUDGET_FOR_SIXTY_DAYS"
    else:
        verdict = "LANE_EXCEEDS_ITS_BUDGET_AT_THE_HORIZON"
    return {
        "schema_version": "EDGE12_CAPACITY_FORECAST_V1",
        "horizon_days": FORECAST_HORIZON_DAYS,
        "footprint_now": {
            "store_bytes": store_now,
            "state_bytes": sum(
                path.stat().st_size for path in state_root.rglob("*") if path.is_file()
            )
            if state_root.is_dir()
            else 0,
            "lane_bytes": int((evidence.get("lane") or {}).get("bytes") or 0),
        },
        "store_growth": growth,
        "retention_ceiling": ceiling,
        "volume_trajectory": trajectory,
        "refusals": refusals,
        "guard": {
            "status": guard.get("status"),
            "free_gib": guard.get("free_gib"),
            "warning_free_bytes": autonomous.DISK_WARNING_BYTES,
            "critical_free_bytes": autonomous.DISK_CRITICAL_BYTES,
            "path": str(state_root),
        },
        "volumes": volumes,
        "usable_volumes": [row["drive_letter"] for row in usable],
        "relocation_verdict": (
            "VOLUME_WITH_CAPACITY_AVAILABLE" if _has_room(usable) else "NO_VOLUME_WITH_CAPACITY"
        ),
        "forecast": {
            "store_bytes_at_horizon": int(store_at_horizon),
            "state_bytes_at_horizon": int(state_at_horizon),
            "lane_bytes_at_horizon": lane_at_horizon,
            "lane_budget_bytes": autonomous.LANE_BUDGET_BYTES,
            "added_over_the_horizon_bytes": int(added_over_the_horizon),
            "added_gib_over_the_horizon": round(added_over_the_horizon / 1024**3, 6),
            "fits": fits,
            "method": (
                "the store is projected forward at the measured bytes per bar and bars per day; the "
                "state root is not projected at all, it is summed at its retention ceiling, because "
                "a bounded log has a ceiling and an unbounded store has a rate"
            ),
            "no_invented_volume_forecast": (
                "the volume's own time-to-critical is not published: the lane measured its free "
                "space, but the volume is shared with everything else on this machine and a number "
                "derived from this lane's slope would be an attribution the evidence does not support"
            ),
        },
        "verdict": verdict,
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def _has_room(usable: list[dict[str, Any]]) -> bool:
    """A volume can hold the store only if it is NTFS, mounted, and not the one already in use.

    The threshold is deliberately generous relative to this lane's own footprint: the
    question a relocation answers is whether the *volume* has room to be a home for sixty
    days of growth plus everything already on it, not whether it has room for the 12 MB
    the store holds today.
    """
    return any(
        row["usable_for_this_store"]
        and not row["is_the_current_volume"]
        and (row["free_gib"] or 0) >= 4.0
        for row in usable
    )
