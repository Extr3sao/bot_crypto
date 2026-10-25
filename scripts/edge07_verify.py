#!/usr/bin/env python
"""WP-EDGE-07 — the independent verifier: re-derive the claims instead of trusting them.

    python scripts/edge07_verify.py            # verify, write VERIFICATION.json/.md
    python scripts/edge07_verify.py --self-test  # sabotage each check and require detection
    python scripts/edge07_verify.py --json       # print the payload, write nothing

What makes this a verifier rather than a summary:

* **it re-derives, it does not read a conclusion** — the verdicts are recomputed from the checks
  the artefacts themselves published, the holdout corpus digest is recomputed from the shards, the
  parameters' hash is recomputed from the registered parameters, and one of Track C's measured
  ceilings is recomputed from the raw bars. A report that says one thing and contains another fails
  here.
* **it verifies the recovery, not the intention** — free space against the runtime's floor, every
  path the reclaim history says was removed actually gone, the two scheduled ticks that observed
  after the reclaim counted from the lane's own run log, and a durable receipt for the cadence's
  re-read, which is the thing WP-EDGE-06 could not show.
* **it has its own saboteur** — ``--self-test`` mutates copies of the inputs in the six ways a
  careless run would, and requires the corresponding check to fail. A verifier that cannot fail is
  not evidence.

Read-only: it writes its own report and nothing else.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import shutil
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

WP = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07"
VALIDATION_JSON = WP / "validation" / "VALIDATION.json"
ACTIVE_JSON = WP / "active-research" / "ACTIVE_RESEARCH.json"
BARRIER_JSON = WP / "active-research" / "COST_BARRIER_ACTIVE.json"
PREREG_JSON = WP / "PREREGISTRATION.json"
ACTIVE_PREREG_JSON = WP / "active-research" / "PREREGISTRATION.json"
RECLAIM_JSON = WP / "STORAGE_RECLAIM.json"
RECLAIM_HISTORY = WP / "STORAGE_RECLAIM_HISTORY.jsonl"
RUNS = REPO_ROOT / "data" / "forward" / "edge04" / "runs.jsonl"
RECEIPTS = REPO_ROOT / "data" / "forward" / "edge04" / "derived_refresh.jsonl"
STORE = REPO_ROOT / "data" / "forward" / "edge03"
HOLDOUT_DIR = REPO_ROOT / "data" / "edge07" / "holdout-1h"
HOLDOUT_MANIFEST = HOLDOUT_DIR / "_FETCH_MANIFEST.json"
EVIDENCE_JSON = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06" / "SCHEDULER_EVIDENCE.json"

CRITICAL_FLOOR_BYTES = 2 * 1024**3
HEALTHY_FLOOR_BYTES = 5 * 1024**3
SLOT_CONSUMING = {"OBSERVED", "NO_NEW_DATA"}
SCHEMA_VERSION = "EDGE07_VERIFICATION_V1"

#: The instant the observer's durable receipt was committed. A scheduled tick before it could not
#: have written one, and a tick after it must have.
WIRING_REFERENCE = "2026-10-14T09:07:00Z"


def now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def params_hash(params: dict[str, Any]) -> str:
    from trading_bot.research.edge07.validation import params_hash as compute

    return compute(params)


# -- the checks: pure functions over (artefacts, live facts) --------------------------- #
def check_a1_floors(facts: dict[str, Any]) -> dict[str, Any]:
    free = facts["free_bytes"]
    return {
        "statement": "the volume is above the runtime's 2 GiB critical floor",
        "passed": free >= CRITICAL_FLOOR_BYTES,
        "detail": {
            "free_bytes": free,
            "free_gib": round(free / 1024**3, 3),
            "critical_floor_bytes": CRITICAL_FLOOR_BYTES,
            "healthy_floor_bytes": HEALTHY_FLOOR_BYTES,
            "clears_healthy_floor": free >= HEALTHY_FLOOR_BYTES,
        },
    }


def check_a2_reclaim_history(facts: dict[str, Any]) -> dict[str, Any]:
    history = facts["reclaim_history"]
    applied = [row for row in history if row.get("mode") == "applied"]
    removed = [path for row in applied for path in (row.get("paths") or [])]
    still_there = [path for path in removed if Path(path).exists()]
    return {
        "statement": "every path the reclaim recorded as removed is gone, and at least one sweep was applied",
        "passed": bool(applied) and not still_there,
        "detail": {
            "applied_runs": len(applied),
            "paths_recorded_as_removed": len(removed),
            "paths_that_still_exist": still_there[:5],
            "reclaimed_bytes_total": sum(int(row.get("reclaimed_bytes") or 0) for row in applied),
        },
    }


def check_a3_scheduled_ticks(facts: dict[str, Any]) -> dict[str, Any]:
    reclaim_instant = facts["reclaim_instant_utc"]
    observing = [
        row
        for row in facts["runs"]
        if row.get("mode") == "SCHEDULED"
        and row.get("outcome") in SLOT_CONSUMING
        and str(row.get("started_at_utc") or "") > reclaim_instant
    ]
    observing.sort(key=lambda row: str(row.get("started_at_utc")))
    return {
        "statement": "at least two real scheduled ticks observed after the reclaim",
        "passed": len(observing) >= 2,
        "detail": {
            "after": reclaim_instant,
            "count": len(observing),
            "ticks": [
                {
                    "slot_key": row.get("slot_key"),
                    "started_at_utc": row.get("started_at_utc"),
                    "new_bars": row.get("new_bars"),
                    "market_requests": row.get("market_requests"),
                }
                for row in observing[:6]
            ],
        },
    }


def check_a4_cadence_receipt(facts: dict[str, Any]) -> dict[str, Any]:
    receipts = facts["receipts"]
    by_run = {row.get("run_id"): row for row in receipts}
    due = [
        row
        for row in facts["runs"]
        if row.get("mode") == "SCHEDULED"
        and str(row.get("started_at_utc") or "") >= WIRING_REFERENCE
    ]
    missing: list[str] = []
    inconsistent: list[str] = []
    for run in due:
        receipt = by_run.get(run.get("run_id"))
        if receipt is None:
            missing.append(str(run.get("run_id")))
            continue
        expected = run.get("outcome") in SLOT_CONSUMING
        if bool(receipt.get("ran")) is not expected:
            inconsistent.append(str(run.get("run_id")))
    return {
        "statement": (
            "every scheduled tick after the wiring has a durable receipt, and its ran/not-ran "
            "follows the tick's own outcome"
        ),
        "passed": bool(due) and not missing and not inconsistent,
        "detail": {
            "wiring_reference": WIRING_REFERENCE,
            "scheduled_ticks_since": len(due),
            "receipts_on_file": len(receipts),
            "receipts_missing": missing,
            "receipts_inconsistent_with_the_tick": inconsistent,
            "last_receipt": receipts[-1] if receipts else None,
        },
    }


def check_a5_forward_data_intact(facts: dict[str, Any]) -> dict[str, Any]:
    """Append-only, proved against what was read before the reclaim: a record seen
    earlier must still be there.

    ``run_id`` names the *slot*, not the tick — a slot is attempted more than once
    (a manual invocation beside the scheduled one, a retry after a refusal, two
    attempts inside the same minute) and each attempt is its own record, so
    uniqueness of ``run_id`` is not a property of this log and asserting it would
    fail a healthy lane (DEF-EDGE07-02). The property that matters is that nothing
    is ever removed, reordered or replayed, so the check anchors on the slot
    records WP-EDGE-06 published *before* the reclaim ran: each must still be
    present exactly as written, the file must still be ordered by ``started_at_utc``,
    no two records may be identical (a replay would mint one), and the stored
    series must all still be there.
    """
    runs = facts["runs"]
    fingerprints = [
        (
            str(row.get("run_id")),
            str(row.get("started_at_utc")),
            str(row.get("mode")),
            str(row.get("outcome")),
        )
        for row in runs
    ]
    starts = [str(row.get("started_at_utc") or "") for row in runs]
    monotone = all(a <= b for a, b in itertools.pairwise(starts))
    replayed = len(fingerprints) - len(set(fingerprints))
    present = {
        (str(row.get("slot_key")), str(row.get("started_at_utc")), str(row.get("outcome")))
        for row in runs
    }
    earlier = facts["scheduler_evidence"].get("scheduled_slots_seen") or []
    vanished = sorted(
        str(row.get("slot_key"))
        for row in earlier
        if (str(row.get("slot_key")), str(row.get("started_at_utc")), str(row.get("outcome")))
        not in present
    )
    series = facts["store_series"]
    return {
        "statement": (
            "every scheduled slot WP-EDGE-06 published is still in the lane's log, in order, "
            "never replayed, and its store still holds every series"
        ),
        "passed": (
            bool(earlier)
            and not vanished
            and replayed == 0
            and monotone
            and len(series) >= 6
            and all(count > 0 for count in series.values())
        ),
        "detail": {
            "run_records": len(runs),
            "slots_anchored": len(earlier),
            "slots_vanished": vanished,
            "records_replayed": replayed,
            "started_at_non_decreasing": monotone,
            "store_series": series,
        },
    }


def check_b1_holdout_digest(facts: dict[str, Any]) -> dict[str, Any]:
    manifest = facts["holdout_manifest"]
    mismatched: list[str] = []
    for symbol, entry in sorted((manifest.get("symbols") or {}).items()):
        path = REPO_ROOT / str(entry.get("shard") or "")
        if not path.is_file() or sha256_file(path) != entry.get("sha256"):
            mismatched.append(symbol)
    return {
        "statement": "every holdout shard still hashes to the digest its manifest recorded",
        "passed": bool(manifest.get("symbols")) and not mismatched,
        "detail": {
            "symbols": sorted((manifest.get("symbols") or {}).keys()),
            "mismatched": mismatched,
            "corpus_digest": manifest.get("corpus_digest"),
            "gaps": (manifest.get("totals") or {}).get("gaps"),
        },
    }


def check_b2_params(facts: dict[str, Any]) -> dict[str, Any]:
    validation = facts["validation"]
    registered = facts["preregistration"]
    recomputed = params_hash(validation.get("params") or {})
    expected = (registered.get("primary_book") or {}).get("params_hash")
    return {
        "statement": "the parameters read on the new window are the registered bytes, and the run says so",
        "passed": recomputed == expected
        and bool(validation.get("params_hash_matches_the_registration")),
        "detail": {
            "recomputed": recomputed,
            "registered": expected,
            "recorded": validation.get("params_hash"),
            "matches_flag_on_the_artefact": validation.get("params_hash_matches_the_registration"),
        },
    }


def check_b3_instrument(facts: dict[str, Any]) -> dict[str, Any]:
    instrument = facts["validation"].get("instrument_check") or {}
    checks = instrument.get("checks") or []
    return {
        "statement": "the runner reproduced every published consulted-window figure it re-derived",
        "passed": bool(checks)
        and bool(instrument.get("all_equal"))
        and all(c["equal"] for c in checks),
        "detail": {
            "figures": len(checks),
            "unequal": [c for c in checks if not c["equal"]][:3],
        },
    }


def _recompute_trend_verdict(reading: dict[str, Any]) -> str:
    checks = {check["id"]: check for check in reading.get("checks") or []}
    failed = {cid for cid, check in checks.items() if not check["passed"]}
    powered = bool(checks.get("P1", {}).get("passed"))
    net_positive = bool(checks.get("P2", {}).get("passed"))
    cost_margin = bool(checks.get("P4", {}).get("passed"))
    concentrated = "P5" in failed
    if not failed:
        return "ADMIT_PAPER"
    if not powered and cost_margin and net_positive:
        return "INSUFFICIENT_EVIDENCE"
    if concentrated and net_positive:
        return "INSUFFICIENT_EVIDENCE"
    return "REJECT"


def check_b4_verdict_consistency(facts: dict[str, Any]) -> dict[str, Any]:
    reading = facts["validation"].get("reading") or {}
    recomputed = _recompute_trend_verdict(reading)
    return {
        "statement": "the trend verdict follows from its own checks by the registered mapping",
        "passed": recomputed == reading.get("verdict"),
        "detail": {
            "published": reading.get("verdict"),
            "recomputed": recomputed,
            "failed": reading.get("failed"),
        },
    }


def check_b5_no_promotion(facts: dict[str, Any]) -> dict[str, Any]:
    validation = facts["validation"]
    active = facts["active"]
    fields = {
        "validation.promotion": validation.get("promotion"),
        "validation.order_sent": validation.get("order_sent"),
        "validation.hypothetical": validation.get("hypothetical"),
        "active.promotion": active.get("promotion"),
        "active.order_sent": active.get("order_sent"),
        "active.hypothetical": active.get("hypothetical"),
    }
    ok = (
        fields["validation.promotion"] == "NONE"
        and fields["active.promotion"] == "NONE"
        and fields["validation.order_sent"] is False
        and fields["active.order_sent"] is False
        and fields["validation.hypothetical"] is True
        and fields["active.hypothetical"] is True
    )
    return {
        "statement": "nothing was promoted, no order was sent, every reading is hypothetical",
        "passed": ok,
        "detail": fields,
    }


def check_b6_window_disjoint(facts: dict[str, Any]) -> dict[str, Any]:
    manifest = facts["holdout_manifest"]
    new_start = int((manifest.get("requested_range_ms") or [0, 0])[0])
    frozen_last = max(
        (manifest.get("disjoint_from_frozen_corpora") or {})
        .get("frozen_last_bar_utc", {})
        .values(),
        default="",
    )
    frozen_last_ms = 0
    if frozen_last:
        frozen_last_ms = int(
            datetime.strptime(str(frozen_last), "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=UTC)
            .timestamp()
            * 1000
        )
    return {
        "statement": "the new window begins after the last bar of every frozen corpus",
        "passed": new_start > frozen_last_ms > 0,
        "detail": {
            "new_window_start_ms": new_start,
            "frozen_last_bar_ms": frozen_last_ms,
            "gap_hours": round((new_start - frozen_last_ms) / 3_600_000, 3)
            if frozen_last_ms
            else None,
        },
    }


def _recompute_active_verdict(reading: dict[str, Any]) -> str:
    checks = {check["id"]: check for check in reading.get("checks") or []}
    if not checks.get("C0", {}).get("passed"):
        return "REJECT_NO_GROSS_EDGE"
    if not reading.get("holdout_read"):
        return "INSUFFICIENT_EVIDENCE"
    failed = {cid for cid, check in checks.items() if not check["passed"]}
    if not failed:
        return "ADMIT_PAPER"
    trades = int((checks.get("C1") or {}).get("value") or 0)
    if trades < 30 and "C2" not in failed:
        return "INSUFFICIENT_EVIDENCE"
    if failed == {"C1"}:
        return "INSUFFICIENT_EVIDENCE"
    if "C5" in failed and (checks.get("C2") or {}).get("passed"):
        return "INSUFFICIENT_EVIDENCE"
    return "REJECT"


def check_c1_active_verdicts(facts: dict[str, Any]) -> dict[str, Any]:
    readings = facts["active"].get("readings") or {}
    mismatched = {
        book: {
            "published": reading.get("verdict"),
            "recomputed": _recompute_active_verdict(reading),
        }
        for book, reading in readings.items()
        if reading.get("verdict") != _recompute_active_verdict(reading)
    }
    screened_out_bound = all(
        (not reading.get("holdout_read"))
        or reading.get("verdict") in {"ADMIT_PAPER", "REJECT", "INSUFFICIENT_EVIDENCE"}
        for reading in readings.values()
    )
    return {
        "statement": "each ACTIVE verdict follows from its own checks, and a screened-out book read no independent window",
        "passed": bool(readings) and not mismatched and screened_out_bound,
        "detail": {
            "books": {book: reading.get("verdict") for book, reading in readings.items()},
            "mismatched": mismatched,
            "holdout_read_by_any_candidate": any(r.get("holdout_read") for r in readings.values()),
        },
    }


def check_c2_barrier_recomputation(facts: dict[str, Any]) -> dict[str, Any]:
    """Recompute one published ceiling figure from the raw bars the report was built on."""
    published = facts["barrier"]
    window = (published.get("per_asset") or {}).get("NEW_HOLDOUT") or {}
    target = (window.get("BTC") or [{}])[0]
    recorded = target.get("mean_absolute_move_bps")
    from trading_bot.research.edge01.data import load_1h

    bars = list(load_1h("BTC", corpus=HOLDOUT_DIR).bars)
    from trading_bot.research.edge07 import validation as V

    moves: list[float] = []
    for index in range(len(bars) - 2):
        entry = bars[index + 1]
        exit_bar = bars[index + 2]
        if entry.ts < V.NEW_HOLDOUT["start"] or entry.ts >= V.NEW_HOLDOUT["end"] or entry.open <= 0:
            continue
        moves.append(abs(exit_bar.open - entry.open) / entry.open * 10_000.0)
    recomputed = round(statistics.fmean(moves), 4) if moves else None
    return {
        "statement": "the published one-hour ceiling for BTC on the new window recomputes from the bars",
        "passed": recomputed is not None
        and recorded is not None
        and abs(recomputed - recorded) < 0.01,
        "detail": {"published": recorded, "recomputed": recomputed, "observations": len(moves)},
    }


CHECKS: tuple[tuple[str, Any], ...] = (
    ("A-1", check_a1_floors),
    ("A-2", check_a2_reclaim_history),
    ("A-3", check_a3_scheduled_ticks),
    ("A-4", check_a4_cadence_receipt),
    ("A-5", check_a5_forward_data_intact),
    ("B-1", check_b1_holdout_digest),
    ("B-2", check_b2_params),
    ("B-3", check_b3_instrument),
    ("B-4", check_b4_verdict_consistency),
    ("B-5", check_b5_no_promotion),
    ("B-6", check_b6_window_disjoint),
    ("C-1", check_c1_active_verdicts),
    ("C-2", check_c2_barrier_recomputation),
)

SABOTAGES: dict[str, Any] = {
    "A-1": lambda f: f.__setitem__("free_bytes", 1024),
    "A-2": lambda f: f["reclaim_history"].append(
        {"mode": "applied", "paths": [str(REPO_ROOT / "scripts" / "edge07_verify.py")]}
    ),
    "A-3": lambda f: f.__setitem__(
        "runs",
        [
            row
            for row in f["runs"]
            if not (row.get("mode") == "SCHEDULED" and row.get("outcome") in SLOT_CONSUMING)
        ],
    ),
    "A-4": lambda f: f.__setitem__("receipts", f["receipts"][:-1]),
    "A-5": lambda f: f["store_series"].__setitem__(next(iter(sorted(f["store_series"]))), 0),
    "B-1": lambda f: f["holdout_manifest"]["symbols"][
        next(iter(sorted(f["holdout_manifest"]["symbols"])))
    ].__setitem__("sha256", "0" * 64),
    "B-2": lambda f: f["validation"]["params"].__setitem__("target_atr", 2.0),
    "B-3": lambda f: f["validation"]["instrument_check"]["checks"][0].__setitem__("equal", False),
    "B-4": lambda f: f["validation"]["reading"].__setitem__("verdict", "ADMIT_PAPER"),
    "B-5": lambda f: f["validation"].__setitem__("promotion", "PAPER"),
    "B-6": lambda f: f["holdout_manifest"].__setitem__(
        "requested_range_ms", [1_600_000_000_000, 1_700_000_000_000]
    ),
    "C-1": lambda f: f["active"]["readings"][
        next(iter(sorted(f["active"]["readings"])))
    ].__setitem__("verdict", "ADMIT_PAPER"),
    "C-2": lambda f: f["barrier"]["per_asset"]["NEW_HOLDOUT"][
        next(iter(sorted(f["barrier"]["per_asset"]["NEW_HOLDOUT"])))
    ][0].__setitem__("mean_absolute_move_bps", 999.0),
    "A-6": lambda f: f.__setitem__(
        "runs",
        [
            row
            for row in f["runs"]
            if not (
                str(row.get("slot_key"))
                == str(f["scheduler_evidence"]["scheduled_slots_seen"][0]["slot_key"])
                and str(row.get("started_at_utc"))
                == str(f["scheduler_evidence"]["scheduled_slots_seen"][0]["started_at_utc"])
            )
        ],
    ),
}

#: Sabotages that exercise a branch of a check rather than being a claim of their own: the id
#: names the tamper, the value names the check that must notice it.
SABOTAGE_TARGETS: dict[str, str] = {"A-6": "A-5"}


def live_facts() -> dict[str, Any]:
    reclaim_history = read_jsonl(RECLAIM_HISTORY)
    applied = [row for row in reclaim_history if row.get("mode") == "applied"]
    store_series: dict[str, int] = {}
    if STORE.is_dir():
        for path in sorted(STORE.rglob("*.jsonl*")):
            try:
                key = str(path.relative_to(STORE)).replace("\\", "/")
                with path.open("rb") as handle:
                    store_series[key] = sum(1 for _ in handle)
            except OSError:
                continue
    return {
        "free_bytes": shutil.disk_usage(REPO_ROOT).free,
        "reclaim_history": reclaim_history,
        "reclaim_instant_utc": (applied[0].get("as_of_utc") if applied else "2026-10-14T08:44:00Z"),
        "reclaim_json": read_json(RECLAIM_JSON),
        "runs": read_jsonl(RUNS),
        "receipts": read_jsonl(RECEIPTS),
        "scheduler_evidence": read_json(EVIDENCE_JSON),
        "store_series": store_series,
        "holdout_manifest": read_json(HOLDOUT_MANIFEST),
        "validation": read_json(VALIDATION_JSON),
        "preregistration": read_json(PREREG_JSON),
        "active": read_json(ACTIVE_JSON),
        "active_preregistration": read_json(ACTIVE_PREREG_JSON),
        "barrier": read_json(BARRIER_JSON),
    }


def verify(facts: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for check_id, function in CHECKS:
        outcome = function(facts)
        results.append({"id": check_id, **outcome})
    passed = sum(1 for row in results if row["passed"])
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": now_utc(),
        "checks": results,
        "passed": passed,
        "total": len(results),
        "result": "PASS" if passed == len(results) else "FAIL",
        "failing": [row["id"] for row in results if not row["passed"]],
    }


def self_test(facts: dict[str, Any]) -> dict[str, Any]:
    baseline = verify(facts)
    detections: list[dict[str, Any]] = []
    for check_id, sabotage in SABOTAGES.items():
        mutated = copy.deepcopy(facts)
        sabotage(mutated)
        result = verify(mutated)
        target = SABOTAGE_TARGETS.get(check_id, check_id)
        detected = target in result["failing"]
        detections.append(
            {
                "check": check_id,
                "must_be_caught_by": target,
                "detected": detected,
                "detail": next(row for row in result["checks"] if row["id"] == target)["detail"],
            }
        )
    return {
        "baseline_result": baseline["result"],
        "sabotages": detections,
        "detected": sum(1 for row in detections if row["detected"]),
        "total": len(detections),
        "result": "PASS"
        if all(row["detected"] for row in detections) and baseline["result"] == "PASS"
        else "FAIL",
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-07 — independent verification",
        "",
        f"*Run at `{payload['as_of_utc']}`. Result: **{payload['result']}** "
        f"({payload['passed']}/{payload['total']} checks).*",
        "",
        "| # | Claim re-derived | Result | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["checks"]:
        detail = json.dumps(row["detail"], ensure_ascii=False)
        if len(detail) > 220:
            detail = detail[:217] + "…"
        lines.append(f"| {row['id']} | {row['statement']} | {row['passed']} | `{detail}` |")
    self_test_payload = payload.get("self_test")
    if self_test_payload:
        lines += [
            "",
            "## The verifier's own saboteur",
            "",
            f"{self_test_payload['detected']}/{self_test_payload['total']} sabotages detected "
            f"(baseline {self_test_payload['baseline_result']}).",
            "",
        ]
    lines += [
        "",
        "## What a PASS means, and what it does not",
        "",
        "- It means the artefacts this work package published agree with each other and with the",
        "  live facts they rest on: the floors, the reclaim history, the lane's own run log and its",
        "  receipt, the corpus digests, the registered parameters, the verdicts' own logic, and one",
        "  measured ceiling recomputed from the bars.",
        "- It does not mean the strategies make money. Two of the three books measured here are",
        "  rejected and nothing is promoted; a PASS on a rejection is the intended outcome.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=str(WP))
    options = parser.parse_args(argv)

    facts = live_facts()
    payload = verify(facts)
    if options.self_test:
        payload["self_test"] = self_test(facts)

    if options.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str))
        return 0 if payload["result"] == "PASS" else 1

    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "VERIFICATION.md").write_text(render(payload), encoding="utf-8")
    print("=" * 78)
    print("WP-EDGE-07 — INDEPENDENT VERIFICATION")
    print("=" * 78)
    for row in payload["checks"]:
        print(f"  {row['id']:<4} {'PASS' if row['passed'] else 'FAIL'}  {row['statement'][:88]}")
    print(f"result {payload['result']} ({payload['passed']}/{payload['total']})")
    if payload.get("self_test"):
        st = payload["self_test"]
        print(f"self-test {st['result']}: {st['detected']}/{st['total']} sabotages detected")
        for row in st["sabotages"]:
            if not row["detected"]:
                print(f"  MISSED {row['check']} {row['detail']}")
    print(f"wrote {(out / 'VERIFICATION.json').relative_to(REPO_ROOT)}")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
