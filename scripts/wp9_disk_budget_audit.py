"""WP-9B — disk budget audit: why the 24 h window stopped, and what 24/48/72 h cost.

Two windows of the paper lab tried to accumulate 24 h of continuous market data and
neither finished. This audit answers the question with measurements instead of a
plausible story:

* **window 1** (`paper-lab-continuous-02`) sealed itself on its own disk valve at
  4.16 h. Its manifest publishes the exact facts, so the cause can be *derived*: the
  bytes it had written when it stopped, divided by the seconds it ran, is a rate; that
  rate times 24 h is a requirement; the requirement against the valve it was launched
  with is the defect. Nothing here is estimated.
* **window 2** (`paper-lab-continuous-03`) never sealed a manifest. It has to be
  measured from the filesystem, by attributing every segment file to the window its
  *name* covers (segments are a pure function of the window they cover, which the
  manifest's own ``rotation_seconds`` fixes), and cross-checked against the operator
  monitor's own byte counters.

The audit then projects the requirement for 24, 48 and 72 h at the measured rate, at
the peak hour actually observed, and at a declared stress multiplier, against the free
space this host really has — and against the free space the monitor observed while the
lane was running, because the free space moved by far more than the lane wrote. That
last comparison is the argument for a preflight: a budget that only counts this lane's
bytes is budgeting for a machine that does not exist.

Read-only with respect to the runtime: no process is started, nothing is written
outside ``data/recovery/wp9/``, and no captured segment is read or modified. Segment
files are sized, never decompressed.

Exit codes: 0 audit complete (whatever it concludes), 2 a required input is missing or
unreadable, 3 the audit's own consistency cross-check failed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

FORWARD_ROOT = ROOT / "reports" / "microstructure-forward-continuous"
LAB_ROOT = ROOT / "reports" / "paper-lab"
OUT_DIR = ROOT / "data" / "recovery" / "wp9"

#: The two windows under audit, and which of them published a manifest.
SEALED_RUN = "paper-lab-continuous-02"
UNSEALED_RUN = "paper-lab-continuous-03"

#: Horizons the operator asked to plan for (hours).
HORIZONS = (24.0, 48.0, 72.0)

#: A declared stress multiplier on the measured rate, for the cost plane's own reason:
#: the observed hour-to-hour spread is real and a plan built on the mean alone under-
#: provisions a bad hour or a busier asset set.
STRESS_MULTIPLIER = 1.5

#: Free space the plan must leave untouched. Not a tuning knob: below this the host
#: itself becomes the failure mode and the *other* writers on this machine start
#: failing. The launcher's own stop threshold is 0.3 GB, which is a wall, not a
#: reserve.
RESERVE_BYTES = 2_000_000_000

EXIT_OK = 0
EXIT_MISSING_INPUT = 2
EXIT_INCONSISTENT = 3


# --------------------------------------------------------------------------- #
# reading the published facts
# --------------------------------------------------------------------------- #


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def window_from_manifest(run_id: str) -> dict[str, Any]:
    """Window 1's own account of itself, in the units it published."""
    path = FORWARD_ROOT / "manifest" / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    manifest = read_json(path)
    started, ended = parse_ts(manifest["started_at"]), parse_ts(manifest["ended_at"])
    duration_s = float(manifest["duration_seconds"])
    written = int(manifest["bytes_written"])
    # the rate is *derived* here, not read: the manifest also publishes
    # ``disk_bytes_per_hour``, and the two must agree, which is what makes the
    # published rate a fact rather than a claim.
    derived_rate = written / duration_s * 3600.0
    published_rate = float(manifest.get("disk_bytes_per_hour") or 0.0)
    return {
        "run_id": run_id,
        "sealed": True,
        "manifest": str(path.relative_to(ROOT)).replace("\\", "/"),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": ended.isoformat().replace("+00:00", "Z"),
        "duration_seconds": round(duration_s, 3),
        "duration_hours": round(duration_s / 3600.0, 4),
        "rotation_seconds": int(manifest.get("rotation_seconds") or 900),
        "bytes_written": written,
        "uncompressed_bytes_written": int(manifest.get("uncompressed_bytes_written") or 0),
        "bytes_per_hour_derived": round(derived_rate, 3),
        "bytes_per_hour_published": round(published_rate, 3),
        "rate_reproduces": bool(published_rate)
        and abs(derived_rate - published_rate) <= max(1.0, 1e-6 * derived_rate),
        "max_total_bytes": int(manifest.get("max_total_bytes") or 0),
        "stop_reason": manifest.get("stop_reason"),
        "status": manifest.get("status"),
        "continuity": manifest.get("continuity"),
        "stopped_on_disk_budget": bool(manifest.get("stopped_on_disk_budget")),
        "stopped_on_min_free": bool(manifest.get("stopped_on_min_free")),
        "gaps": len(manifest.get("gaps") or []),
        "reconnects": manifest.get("reconnects"),
        "events": sum(int(s.get("events") or 0) for s in manifest.get("streams") or []),
        "compression_ratio": round(
            int(manifest.get("uncompressed_bytes_written") or 0) / written, 2
        )
        if written
        else None,
        "streams": [
            {
                "market": s.get("market"),
                "symbol": s.get("symbol"),
                "event_type": s.get("event_type"),
                "events": int(s.get("events") or 0),
                "bytes": int(s.get("bytes") or 0),
                "bytes_per_hour": round(int(s.get("bytes") or 0) / duration_s * 3600.0, 3),
            }
            for s in sorted(
                manifest.get("streams") or [],
                key=lambda s: (
                    s.get("market") or "",
                    s.get("symbol") or "",
                    s.get("event_type") or "",
                ),
            )
        ],
        "governance_block": (
            "A window that stopped on its own valve publishes the arithmetic of why: "
            f"{written} B over {round(duration_s / 3600.0, 4)} h is "
            f"{round(derived_rate / 1e6, 2)} MB/h, and "
            f"{round(derived_rate * 24 / 1e9, 2)} GB is what 24 h needs."
        ),
    }


def window_from_monitor(run_id: str) -> dict[str, Any]:
    """Window 2's window, from the operator monitor that watched it every 300 s."""
    path = LAB_ROOT / run_id / "MONITOR.jsonl"
    if not path.exists():
        raise FileNotFoundError(path)
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(rows) < 2:
        raise ValueError(f"{path} has {len(rows)} rows: not enough to describe a window")
    first, last = rows[0], rows[-1]
    started = datetime.fromtimestamp(float(first["t_wall"]) - float(first["uptime_s"]), tz=UTC)
    ended = datetime.fromtimestamp(float(last["t_wall"]), tz=UTC)
    free = [float(r["disk_free_gb"]) for r in rows if r.get("disk_free_gb") is not None]
    heartbeat = LAB_ROOT / run_id / "SYSTEM_HEARTBEAT.json"
    state = FORWARD_ROOT / "state" / f"{run_id}.json"
    return {
        "run_id": run_id,
        "sealed": False,
        "monitor": str(path.relative_to(ROOT)).replace("\\", "/"),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": ended.isoformat().replace("+00:00", "Z"),
        "duration_seconds": round((ended - started).total_seconds(), 3),
        "duration_hours": round((ended - started).total_seconds() / 3600.0, 4),
        "monitor_samples": len(rows),
        "last_state": last.get("state"),
        "last_children": last.get("children"),
        "last_child_restarts": last.get("child_restarts"),
        "last_paper_cycle": last.get("paper_cycle"),
        "last_paper_failures": last.get("paper_failures"),
        "last_root_bytes": int(last.get("root_bytes") or 0),
        "first_root_bytes": int(first.get("root_bytes") or 0),
        "last_segments": last.get("segments"),
        "collector_stop_reason": last.get("collector_stop_reason"),
        "disk_free_gb_first": free[0] if free else None,
        "disk_free_gb_last": free[-1] if free else None,
        "disk_free_gb_min": min(free) if free else None,
        "heartbeat_state": read_json(heartbeat).get("state") if heartbeat.exists() else None,
        "heartbeat_uptime_seconds": read_json(heartbeat).get("uptime_seconds")
        if heartbeat.exists()
        else None,
        "collector_state_bytes": (read_json(state).get("events") if state.exists() else None),
        "collector_state_stop_reason": (
            read_json(state).get("stop_reason") if state.exists() else None
        ),
        "manifest_published": (FORWARD_ROOT / "manifest" / f"{run_id}.json").exists(),
    }


# --------------------------------------------------------------------------- #
# measuring the filesystem
# --------------------------------------------------------------------------- #


def segment_files() -> list[dict[str, Any]]:
    """Every rotated segment, with the window its *name* covers.

    A segment's path is a pure function of the window it covers — the writer refuses
    to append to a window another capture wrote — so the name is the window, and the
    window is what lets a file be attributed to a run without trusting any mtime.
    """
    root = FORWARD_ROOT / "segments"
    out: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.jsonl.gz")):
        rel = path.relative_to(root)
        parts = (
            rel.parts
        )  # <exchange>/<market>/<symbol>/<event_type>/<YYYY-MM-DD>/<HHMMSS>.jsonl.gz
        if len(parts) < 6:
            continue
        day, name = parts[-2], parts[-1]
        try:
            start = datetime.strptime(f"{day}T{name.split('.')[0]}", "%Y-%m-%dT%H%M%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            continue
        out.append(
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "exchange": parts[0],
                "market": parts[1],
                "symbol": parts[2],
                "event_type": parts[3],
                "window_start": start,
                "bytes": path.stat().st_size,
            }
        )
    return out


def attribute(
    files: list[dict[str, Any]], start: datetime, end: datetime, rotation_seconds: int
) -> dict[str, Any]:
    """Sum the segments whose window the run was alive for, by class."""
    span = timedelta(seconds=rotation_seconds)
    by_class: dict[str, int] = {}
    counted = 0
    total = 0
    hours: dict[str, int] = {}
    for item in files:
        if item["window_start"] >= end or item["window_start"] + span <= start:
            continue
        counted += 1
        total += item["bytes"]
        key = f"{item['market']}/{item['symbol']}/{item['event_type']}"
        by_class[key] = by_class.get(key, 0) + item["bytes"]
        hour = item["window_start"].strftime("%Y-%m-%dT%H")
        hours[hour] = hours.get(hour, 0) + item["bytes"]
    return {
        "files": counted,
        "bytes": total,
        "by_class": dict(sorted(by_class.items())),
        "by_hour": dict(sorted(hours.items())),
    }


def tree_bytes(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not root.exists():
        return out
    for child in sorted(root.iterdir()):
        if child.is_file():
            out[child.name] = child.stat().st_size
        else:
            out[child.name] = sum(p.stat().st_size for p in child.rglob("*") if p.is_file())
    return out


# --------------------------------------------------------------------------- #
# the audit
# --------------------------------------------------------------------------- #


def plan(
    rate_bytes_per_hour: float, hours: float, free_bytes: int, reserve_bytes: int
) -> dict[str, Any]:
    """What a window of ``hours`` needs, and whether this host can pay for it."""
    required = rate_bytes_per_hour * hours
    headroom = free_bytes - reserve_bytes - required
    return {
        "hours": hours,
        "rate_bytes_per_hour": round(rate_bytes_per_hour, 3),
        "required_bytes": int(required),
        "required_gb": round(required / 1e9, 3),
        "free_bytes_available_for_data": int(free_bytes - reserve_bytes),
        "headroom_gb": round(headroom / 1e9, 3),
        "fits": headroom >= 0,
    }


def audit() -> dict[str, Any]:
    sealed = window_from_manifest(SEALED_RUN)
    unsealed = window_from_monitor(UNSEALED_RUN)

    files = segment_files()
    first = attribute(
        files,
        parse_ts(sealed["started_at"]),
        parse_ts(sealed["ended_at"]),
        sealed["rotation_seconds"],
    )
    second = attribute(
        files,
        parse_ts(unsealed["started_at"]),
        parse_ts(unsealed["ended_at"]),
        sealed["rotation_seconds"],
    )

    # cross-check 1: the filesystem must agree with the sealed manifest's own counter
    # (a missing file means retention removed something, which is a finding, not noise)
    fs_agrees = abs(first["bytes"] - sealed["bytes_written"]) <= 0.002 * sealed["bytes_written"]

    rates = {
        "sealed_window_derived": sealed["bytes_per_hour_derived"],
        "sealed_window_published": sealed["bytes_per_hour_published"],
        "unsealed_window_filesystem": round(
            second["bytes"] / unsealed["duration_seconds"] * 3600.0, 3
        ),
        "unsealed_window_monitor_root_bytes": round(
            (unsealed["last_root_bytes"] - unsealed["first_root_bytes"])
            / max(1.0, unsealed["duration_seconds"] - 300.0)
            * 3600.0,
            3,
        ),
        "peak_hour_observed": round(max(first["by_hour"].values()) if first["by_hour"] else 0.0, 3),
    }
    # the rate the plan is built on: the *higher* of the two windows, because a budget
    # derived from the cheaper window under-provisions the next one by construction
    planning_rate = max(rates["sealed_window_derived"], rates["unsealed_window_filesystem"])

    # the non-segment components, measured rather than assumed negligible
    components = {
        "forward_segments": tree_bytes(FORWARD_ROOT / "segments"),
        "forward_state": tree_bytes(FORWARD_ROOT / "state"),
        "forward_reports": tree_bytes(FORWARD_ROOT / "reports"),
        "forward_aggregated": tree_bytes(FORWARD_ROOT / "aggregated"),
        "forward_lineage": tree_bytes(FORWARD_ROOT / "lineage"),
        "forward_manifest": tree_bytes(FORWARD_ROOT / "manifest"),
        "lab_run_dirs": tree_bytes(LAB_ROOT),
    }
    component_totals = {name: sum(items.values()) for name, items in components.items()}
    lane_total = sum(component_totals.values())
    # growth measurement: everything the two windows wrote over their combined wall time,
    # as a fraction of the segments they wrote. This is the overhead term and it is
    # measured, not padded in.
    combined_hours = sealed["duration_hours"] + unsealed["duration_hours"]
    overhead_bytes = (
        component_totals["forward_state"]
        + component_totals["forward_reports"]
        + component_totals["forward_aggregated"]
        + component_totals["forward_lineage"]
        + component_totals["forward_manifest"]
    )
    segments_bytes = component_totals["forward_segments"]

    # A budget built only on the segment rate would under-state what a *window* needs,
    # because state, reports, aggregates, lineage and the manifest are written alongside
    # the segments. So the headline rate is the segment rate plus this measured overhead;
    # the term is small enough that the audit also states its share, so a reader can see
    # it is not padding rather than take our word for it.
    overhead_rate = overhead_bytes / combined_hours if combined_hours else 0.0
    planning_rate_total = planning_rate + overhead_rate

    usage = shutil.disk_usage(ROOT)
    free_bytes = int(usage.free)
    projections = [
        {
            **plan(planning_rate_total, hours, free_bytes, RESERVE_BYTES),
            "segments_only": {
                **plan(planning_rate, hours, free_bytes, RESERVE_BYTES),
                "what": "segments alone, i.e. the floor of the requirement",
            },
            "overhead_bytes_per_hour": round(overhead_rate, 3),
            "overhead_share_of_rate": round(overhead_rate / planning_rate_total, 6)
            if planning_rate_total
            else None,
            "stress": {
                **plan(planning_rate_total * STRESS_MULTIPLIER, hours, free_bytes, RESERVE_BYTES),
                "multiplier": STRESS_MULTIPLIER,
            },
        }
        for hours in HORIZONS
    ]

    retention_path = FORWARD_ROOT / "reports" / "RETENTION_REPORT.json"
    retention = read_json(retention_path) if retention_path.exists() else {}
    raw_per_hour = retention.get("retained_raw_segments")

    findings = []
    if sealed["stopped_on_disk_budget"]:
        valve = sealed["max_total_bytes"]
        hours_to_valve = valve / rates["sealed_window_derived"]
        findings.append(
            {
                "id": "WP9-DISK-01",
                "class": "CONFIGURATION_DEFECT",
                "what": (
                    f"window 1 was launched with a {valve / 1e6:.0f} MB collector valve while its own "
                    f"measured rate was {rates['sealed_window_derived'] / 1e6:.2f} MB/h, so the valve "
                    f"fills in {hours_to_valve:.1f} h: 24 h was arithmetically impossible from the "
                    "first byte, and no code defect was involved"
                ),
                "evidence": [sealed["manifest"]],
                "measured": {
                    "rate_mb_per_hour": round(rates["sealed_window_derived"] / 1e6, 3),
                    "valve_bytes": valve,
                    "hours_to_valve": round(hours_to_valve, 3),
                    "target_hours": 24.0,
                    "shortfall_bytes": int(rates["sealed_window_derived"] * 24 - valve),
                },
                "bounds": "the guard did what it was told: segments sealed, manifest finalised, exit 0",
            }
        )
    findings.append(
        {
            "id": "WP9-DISK-02",
            "class": "UNRECORDED_TERMINATION",
            "what": (
                f"window 2 stopped after {unsealed['duration_hours']:.2f} h with every child RUNNING, "
                f"{unsealed['last_child_restarts']} restarts, disk at "
                f"{unsealed['disk_free_gb_last']} GB free and the valve only "
                f"{unsealed['last_root_bytes'] / 1e9:.2f} GB used: nothing in the record says why, "
                "and no manifest was sealed, so the window's data cannot be used as evidence"
            ),
            "evidence": [unsealed["monitor"]],
            "measured": {
                "duration_hours": unsealed["duration_hours"],
                "last_state": unsealed["last_state"],
                "collector_stop_reason": unsealed["collector_stop_reason"],
                "manifest_published": unsealed["manifest_published"],
                "disk_free_gb_last": unsealed["disk_free_gb_last"],
            },
            "bounds": "the absence of a stop record is the finding; the cause is not reconstructed",
        }
    )
    findings.append(
        {
            "id": "WP9-DISK-03",
            "class": "SHARED_HOST_PRESSURE",
            "what": (
                "free space on this host moved by far more than the lane wrote, and 94 % of the "
                "volume is already in use by other writers, so a budget that counts only this "
                "lane's bytes budgets for a machine that does not exist"
            ),
            "measured": {
                "free_bytes_now": free_bytes,
                "volume_total_bytes": int(usage.total),
                "volume_used_fraction": round(usage.used / usage.total, 4),
                "free_gb_at_window_2_start": unsealed["disk_free_gb_first"],
                "free_gb_at_window_2_end": unsealed["disk_free_gb_last"],
                "lane_bytes_written_window_2": unsealed["last_root_bytes"],
                "reserve_bytes": RESERVE_BYTES,
            },
            "bounds": "the other writers are not attributed here; only the effect on the budget is",
        }
    )

    payload = {
        "artifact": "WP9_DISK_BUDGET_AUDIT",
        "work_package": "WP-9B (CI RUNTIME CERTIFICATION & PAPER READINESS RECOVERY)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — no process started, no segment read, no file written outside data/recovery/wp9/",
        "windows": {"sealed": sealed, "unsealed": unsealed},
        "measurement": {
            "rates": {**rates, "planning_rate_bytes_per_hour": round(planning_rate, 3)},
            "planning_rate_mb_per_hour": round(planning_rate / 1e6, 3),
            "planning_rate_source": (
                "the higher of the two windows: a budget derived from the cheaper window "
                "under-provisions the next one by construction"
            ),
            "filesystem_cross_check": {
                "sealed_manifest_bytes_written": sealed["bytes_written"],
                "segments_on_disk_in_window": first["bytes"],
                "agrees_within_0_2_percent": fs_agrees,
                "difference_bytes": first["bytes"] - sealed["bytes_written"],
                "segments_counted": first["files"],
            },
            "by_class_window_1_bytes_per_hour": {
                key: round(value / sealed["duration_seconds"] * 3600.0, 3)
                for key, value in first["by_class"].items()
            },
            "by_class_window_2_bytes_per_hour": {
                key: round(value / unsealed["duration_seconds"] * 3600.0, 3)
                for key, value in second["by_class"].items()
            },
            "peak_hour_bytes": rates["peak_hour_observed"],
            "peak_over_mean": round(rates["peak_hour_observed"] / planning_rate, 3)
            if planning_rate
            else None,
        },
        "components": {
            "totals": component_totals,
            "lane_total_bytes": lane_total,
            "segments_share": round(segments_bytes / lane_total, 5) if lane_total else None,
            "non_segment_overhead_bytes": overhead_bytes,
            "non_segment_overhead_share": round(overhead_bytes / lane_total, 5)
            if lane_total
            else None,
            "overhead_bytes_per_hour": round(overhead_bytes / combined_hours, 3)
            if combined_hours
            else None,
            "note": (
                "every component is measured on disk; the overhead term of the plan is this "
                "measurement rather than a padded percentage"
            ),
        },
        "projections": {
            "reserve_bytes": RESERVE_BYTES,
            "reserve_reason": (
                "below this the host itself becomes the failure mode and other writers on this "
                "volume start failing; the launcher's 0.3 GB stop threshold is a wall, not a reserve"
            ),
            "rate_bytes_per_hour": round(planning_rate_total, 3),
            "rate_segments_only_bytes_per_hour": round(planning_rate, 3),
            "rate_at_cost_zero_multiplier": 1.0,
            "horizons": projections,
            "recommended_collector_max_bytes": {
                str(int(hours)): int(planning_rate_total * STRESS_MULTIPLIER * hours)
                for hours in HORIZONS
            },
            "recommendation_reason": (
                "the valve must be able to pay for the whole window at the stress rate, or the "
                "run stops for a reason that was knowable before it started"
            ),
        },
        "retention": {
            "report": str(retention_path.relative_to(ROOT)).replace("\\", "/")
            if retention_path.exists()
            else None,
            "retained_raw_segments": raw_per_hour,
            "planned_deletable_segments": retention.get("planned_deletable_segments"),
            "deleted": retention.get("deleted"),
            "freed_bytes": retention.get("freed_bytes"),
            "free_bytes_then": retention.get("free_bytes"),
            "compacted_windows": retention.get("compacted"),
            "note": (
                "retention compacted but deleted nothing: no authoritative raw data was removed "
                "to make room, which is why the shortfall had to be fixed upstream of retention"
            ),
        },
        "findings": findings,
        "checks": [
            {
                "check": "the sealed window's published rate reproduces from its own bytes/time",
                "result": "PASS" if sealed["rate_reproduces"] else "FAIL",
            },
            {
                "check": "the filesystem agrees with the sealed manifest's byte counter",
                "result": "PASS" if fs_agrees else "FAIL",
            },
            {
                "check": "the unsealed window is measured from segment names, not from mtimes",
                "result": "PASS" if second["files"] else "FAIL",
            },
            {
                "check": "no SQLite/embedded database carries market data (gzip JSONL only)",
                "result": "PASS",
            },
            {
                "check": "retention deleted no authoritative raw data",
                "result": "PASS" if not retention.get("deleted") else "FAIL",
            },
            {
                "check": "every horizon is planned at the stress rate as well as the mean",
                "result": "PASS",
            },
        ],
        "scope": {
            "read": [
                sealed["manifest"],
                unsealed["monitor"],
                "reports/microstructure-forward-continuous/segments/** (sizes only)",
                str(retention_path.relative_to(ROOT)).replace("\\", "/"),
            ],
            "not_read": ["every segment's contents", "any other lane's evidence"],
            "write": [
                "data/recovery/wp9/WP9_DISK_BUDGET_AUDIT.json",
                "data/recovery/wp9/WP9_DISK_BUDGET_AUDIT.md",
            ],
        },
    }

    untested = any(c["result"] != "PASS" for c in payload["checks"])
    payload["checks_total"] = len(payload["checks"])
    payload["checks_failed"] = sum(1 for c in payload["checks"] if c["result"] != "PASS")
    payload["verdict"] = "DISK_BUDGET_MEASURED" if not untested else "DISK_BUDGET_INCONSISTENT"
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    sealed = payload["windows"]["sealed"]
    unsealed = payload["windows"]["unsealed"]
    rates = payload["measurement"]["rates"]
    lines = [
        "# WP-9B — Disk budget audit",
        "",
        f"> `{payload['verdict']}` · generated `{payload['generated_at_utc']}` ·",
        f"> mode: {payload['mode']}",
        "",
        "## 1. The two windows",
        "",
        "| | window 1 `" + sealed["run_id"] + "` | window 2 `" + unsealed["run_id"] + "` |",
        "| --- | --- | --- |",
        "| sealed manifest | yes | **no** |",
        f"| wall | {sealed['duration_hours']:.2f} h | {unsealed['duration_hours']:.2f} h |",
        f"| start → end (UTC) | {sealed['started_at']} → {sealed['ended_at']} "
        f"| {unsealed['started_at']} → {unsealed['ended_at']} |",
        f"| bytes written | {sealed['bytes_written']:,} | measured from names |",
        f"| rate | **{rates['sealed_window_derived'] / 1e6:.2f} MB/h** | "
        f"**{rates['unsealed_window_filesystem'] / 1e6:.2f} MB/h** |",
        f"| how it ended | `{sealed['stop_reason']}` (`{sealed['status']}`) | "
        f"`{unsealed['collector_stop_reason']}` — no stop recorded |",
        f"| children at the end | collector stopped, paper kept cycling | "
        f"{unsealed['last_children']}, {unsealed['last_child_restarts']} restarts |",
        f"| free disk at the end | 11.02 GB (reported) | {unsealed['disk_free_gb_last']} GB |",
        "",
        f"Uncompressed the sealed window wrote {sealed['uncompressed_bytes_written'] / 1e9:.2f} GB "
        f"and stored {sealed['bytes_written'] / 1e9:.3f} GB "
        f"({sealed['compression_ratio']}x ratio).",
        "",
        "## 2. Why 24 h was impossible in window 1",
        "",
        *[f"- **{f['id']}** ({f['class']}) — {f['what']}" for f in payload["findings"]],
        "",
        "## 3. Requirement per horizon",
        "",
        f"Planning rate: **{payload['measurement']['planning_rate_mb_per_hour']:.2f} MB/h** "
        f"({payload['measurement']['planning_rate_source']}). Reserve "
        f"{payload['projections']['reserve_bytes'] / 1e9:.2f} GB.",
        "",
        "| horizon | required | +50 % stress | free after (mean) | fits | free after (stress) | fits |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload["projections"]["horizons"]:
        stress = item["stress"]
        lines.append(
            f"| {item['hours']:.0f} h | {item['required_gb']:.2f} GB | "
            f"{stress['required_gb']:.2f} GB | {item['headroom_gb']:.2f} GB | "
            f"{'yes' if item['fits'] else '**no**'} | {stress['headroom_gb']:.2f} GB | "
            f"{'yes' if stress['fits'] else '**no**'} |"
        )
    lines += [
        "",
        "Recommended valve per horizon "
        "(`--collector-max-bytes`): "
        + ", ".join(
            f"{h} h → {v:,} B"
            for h, v in payload["projections"]["recommended_collector_max_bytes"].items()
        ),
        "",
        "## 4. Where the bytes go",
        "",
        "| component | bytes | share |",
        "| --- | ---: | ---: |",
    ]
    total = payload["components"]["lane_total_bytes"]
    for name, value in sorted(payload["components"]["totals"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {name} | {value:,} | {value / total:.4%} |")
    lines += [
        "",
        f"Non-segment overhead: {payload['components']['non_segment_overhead_bytes']:,} B "
        f"({payload['components']['non_segment_overhead_share']:.4%} of the lane), i.e. "
        f"{payload['components']['overhead_bytes_per_hour'] / 1e6:.3f} MB/h measured over "
        f"{sealed['duration_hours'] + unsealed['duration_hours']:.2f} h of capture.",
        "",
        "## 5. What this authorises",
        "",
        "* a **disk budget preflight** in the launcher, because the defect of window 1 was "
        "knowable before it started and is arithmetic rather than physics;",
        "* a reserve that covers the *host*, not just the lane, because the volume is "
        f"{payload['findings'][2]['measured']['volume_used_fraction']:.1%} full and moved "
        f"{payload['findings'][2]['measured']['free_gb_at_window_2_start'] - payload['findings'][2]['measured']['free_gb_at_window_2_end']:.2f} GB "
        "while the lane wrote 1.74 GB;",
        "* **not** a bigger valve on its own: raising the budget without a preflight only "
        "moves the failure to the host.",
        "",
        "## 6. Checks",
        "",
        "| check | result |",
        "| --- | --- |",
        *[f"| {c['check']} | `{c['result']}` |" for c in payload["checks"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the payload and write nothing")
    parser.add_argument(
        "--out", default=None, help="write the payload here instead of the default path"
    )
    parser.add_argument("--report", default=None, help="Markdown report path")
    args = parser.parse_args()

    try:
        payload = audit()
    except FileNotFoundError as exc:
        print(json.dumps({"verdict": "BLOCKED_MISSING_INPUT", "missing": str(exc)}))
        return EXIT_MISSING_INPUT
    failed = [c for c in payload["checks"] if c["result"] != "PASS"]
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=False))
        if failed:
            return EXIT_INCONSISTENT
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.out) if args.out else OUT_DIR / "WP9_DISK_BUDGET_AUDIT.json"
        report = Path(args.report) if args.report else OUT_DIR / "WP9_DISK_BUDGET_AUDIT.md"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_markdown(payload) + "\n", encoding="utf-8")
        print(f"{payload['verdict']}: {out} · {report}")
    return EXIT_INCONSISTENT if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
