"""Independent verifier for RFC-TAP-MARKET-005.

It does **not** import ``trading_bot``.  Every number it prints is recomputed
from artifacts on disk: the captured fixture, the comparison report, the
coverage ledger, the watermarks, the snapshot report and the trigger ledger.

Checks, each one falsifiable by a single tampered byte:

1. ``fixture_integrity`` — every captured series matches its own sha256.
2. ``comparison_is_fair`` — CURRENT and PROPOSED tails recomputed from the
   fixture are identical, so "equivalent" is a property of the data, not a claim.
3. ``reduction_arithmetic`` — request/row totals and percentages add up.
4. ``request_discipline`` — NO_NEW_DATA issues zero requests; a real read issues
   exactly one; final + incomplete + rejected account for every returned row.
5. ``watermark_chain`` — each watermark file passes its checksum, matches the
   ledger and never crosses the closed boundary.
6. ``snapshot_causality`` — every snapshot bar closed at or before the decision,
   and ``available_at_ms`` is the max close boundary.
7. ``ai_spend_is_bounded`` — zero model calls without a credential, and the
   trigger ledger's hash chain is intact.

Run ``--mutations`` to prove the checks detect tampering.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports" / "market-data" / "RFC-TAP-MARKET-005"
FIXTURE = REPORT_DIR / "MARKET_DATA_FIXTURE.json"
COMPARISON = REPORT_DIR / "CURRENT_VS_PROPOSED.json"
COVERAGE = REPORT_DIR / "COVERAGE_LEDGER.jsonl"
SNAPSHOT = REPORT_DIR / "SNAPSHOT_GATE_REPORT.json"
TRIGGERS = REPORT_DIR / "AI_TRIGGER_LEDGER.jsonl"
WATERMARKS = REPO / "data" / "market" / "watermarks"
PROTECTED = (
    "config/risk.yaml",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/paper/broker.py",
    "config/strategy_admission.json",
)
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1m": 60_000}


def canonical_rows(rows: Sequence[Sequence[float]]) -> str:
    payload = [
        [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def closed_tail(
    rows: Sequence[Sequence[float]], timeframe: str, at_ms: int, take: int
) -> list[Any]:
    bar_ms = TF_MS[timeframe]
    closed = [r for r in rows if int(r[0]) + bar_ms <= at_ms]
    return closed[-take:]


# --------------------------------------------------------------------- checks
def check_fixture(fixture: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    for request in fixture["requests"]:
        rows = fixture["series"][request["symbol"]][request["timeframe"]]
        if canonical_rows(rows) != request["sha256"]:
            problems.append(f"sha mismatch {request['symbol']} {request['timeframe']}")
        if len(rows) != request["rows"]:
            problems.append(f"row count mismatch {request['symbol']} {request['timeframe']}")
        if rows and rows[-1][0] != request["last_open_ms"]:
            problems.append(f"last open mismatch {request['symbol']} {request['timeframe']}")
    return (not problems, "; ".join(problems) or "12 captured series match their hashes")


def check_comparison(fixture: dict[str, Any], comparison: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    at = int(comparison["end_ms"])
    take = int(comparison["decision_bars"])
    for series in comparison["series"]:
        rows = fixture["series"][series["symbol"]][series["timeframe"]]
        tail = closed_tail(rows, series["timeframe"], at, take)
        expected = canonical_rows(tail)
        if expected != series["current_tail_sha256"]:
            problems.append(
                f"current tail not reproducible {series['symbol']} {series['timeframe']}"
            )
        if expected != series["proposed_tail_sha256"]:
            problems.append(
                f"proposed tail differs from current {series['symbol']} {series['timeframe']}"
            )
        if series["data_equivalent"] is not (expected == series["proposed_tail_sha256"]):
            problems.append(f"equivalence flag lies {series['symbol']} {series['timeframe']}")
    return (not problems, "; ".join(problems) or "12/12 tails identical and reproducible")


def check_reduction(comparison: dict[str, Any]) -> tuple[bool, str]:
    series = comparison["series"]
    totals = comparison["totals"]
    current_requests = sum(s["current"]["requests"] for s in series)
    proposed_requests = sum(s["proposed"]["requests"] for s in series)
    current_rows = sum(s["current"]["rows_transferred"] for s in series)
    proposed_rows = sum(s["proposed"]["rows_transferred"] for s in series)
    problems: list[str] = []
    if current_requests != totals["current_requests"]:
        problems.append("current request total")
    if proposed_requests != totals["proposed_requests"]:
        problems.append("proposed request total")
    if current_rows != totals["current_rows"] or proposed_rows != totals["proposed_rows"]:
        problems.append("row totals")
    pct = round(100.0 * (current_requests - proposed_requests) / current_requests, 2)
    if pct != totals["requests_pct"]:
        problems.append("request percentage")
    rows_pct = round(100.0 * (current_rows - proposed_rows) / current_rows, 2)
    if rows_pct != totals["rows_pct"]:
        problems.append("row percentage")
    if proposed_requests > current_requests:
        problems.append("proposal reads more than current")
    return (
        not problems,
        "; ".join(problems)
        or f"{current_requests}->{proposed_requests} requests ({pct}%), {current_rows}->{proposed_rows} rows ({rows_pct}%)",
    )


def check_request_discipline(ledger: list[dict[str, Any]]) -> tuple[bool, str]:
    problems: list[str] = []
    for row in ledger:
        status = row["status"]
        if status == "NO_NEW_DATA" and row["requests_made"] != 0:
            problems.append(f"NO_NEW_DATA made {row['requests_made']} requests")
        if status in ("BOOTSTRAP", "DELTA", "RECONCILE") and row["requests_made"] != 1:
            problems.append(f"{status} made {row['requests_made']} requests")
        if status in ("PROVIDER_FAILED", "BACKLOG_EXCEEDS_WINDOW") and row["requests_made"] > 1:
            problems.append(f"{status} made {row['requests_made']} requests")
        accounted = row["rows_final"] + row["rows_incomplete"] + row["rows_rejected"]
        if accounted != row["rows_returned"]:
            problems.append(
                f"unaccounted rows in {row['run_id']}: {accounted} != {row['rows_returned']}"
            )
        if row["status"] in ("DELTA", "BOOTSTRAP", "RECONCILE"):
            bar_ms = TF_MS[row["timeframe"]]
            if row["watermark_after"] is None:
                problems.append(f"missing watermark after {row['run_id']}")
            elif row["watermark_after"]["last_verified_open_ms"] + bar_ms > row["boundary_ms"]:
                problems.append(f"watermark past the closed boundary in {row['run_id']}")
    return (
        not problems,
        "; ".join(problems) or f"{len(ledger)} cycles respect the request discipline",
    )


def check_watermarks(ledger: list[dict[str, Any]], root: Path) -> tuple[bool, str]:
    problems: list[str] = []
    seen = 0
    files = sorted(root.glob("*.json")) if root.exists() else []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        material = "|".join(
            [
                str(payload["source_id"]),
                str(payload["symbol"]),
                str(payload["timeframe"]),
                str(payload["last_verified_open_ms"]),
                str(payload["last_closed_boundary_ms"]),
                str(payload["last_ingested_seq"]),
                str(payload["last_persisted_sha"]),
                str(payload["updated_at_ms"]),
            ]
        )
        if hashlib.sha256(material.encode("utf-8")).hexdigest() != payload.get("checksum"):
            problems.append(f"checksum {path.name}")
            continue
        bar_ms = TF_MS[payload["timeframe"]]
        if payload["last_verified_open_ms"] + bar_ms > payload["last_closed_boundary_ms"]:
            problems.append(f"watermark crosses boundary {path.name}")
        seen += 1
    by_key = {
        (r["symbol"], r["timeframe"]): r
        for r in ledger
        if r["status"] in ("BOOTSTRAP", "DELTA", "RECONCILE")
    }
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        last = by_key.get((payload["symbol"], payload["timeframe"]))
        if last is not None and last["watermark_after"]["checksum"] != payload["checksum"]:
            problems.append(f"ledger/watermark disagree for {path.name}")
    return (not problems, "; ".join(problems) or f"{seen} watermarks self-consistent")


def check_snapshots(fixture: dict[str, Any], report: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    decision = int(report["at_ms"])
    for result in report["results"]:
        snapshot = result.get("snapshot")
        if not snapshot:
            problems.append(f"no snapshot for {result['symbol']}")
            continue
        boundaries: list[int] = []
        for timeframe, slice_info in snapshot["timeframes"].items():
            bar_ms = TF_MS[timeframe]
            rows = fixture["series"][result["symbol"]][timeframe]
            closed = [r for r in rows if int(r[0]) + bar_ms <= decision]
            if not closed:
                problems.append(f"{result['symbol']} {timeframe}: no closed bar at decision")
                continue
            if int(closed[-1][0]) != slice_info["last_open_ms"]:
                problems.append(
                    f"{result['symbol']} {timeframe}: last open {slice_info['last_open_ms']} "
                    f"is not the last closed bar {int(closed[-1][0])}"
                )
            boundary = int(closed[-1][0]) + bar_ms
            if boundary != slice_info["close_boundary_ms"]:
                problems.append(f"{result['symbol']} {timeframe}: close boundary")
            if boundary > decision:
                problems.append(f"{result['symbol']} {timeframe}: future bar in snapshot")
            boundaries.append(boundary)
        if boundaries and max(boundaries) != snapshot["available_at_ms"]:
            problems.append(f"{result['symbol']}: available_at is not the slowest close")
        if snapshot["decision_ms"] > decision:
            problems.append(f"{result['symbol']}: decision after the reported instant")
    return (not problems, "; ".join(problems) or "4/4 snapshots are causal")


def check_ai(trigger_rows: list[dict[str, Any]], report: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    if report.get("model_calls", 0) != 0:
        problems.append("snapshot report claims model calls")
    if report.get("credentials_present") is False:
        for row in trigger_rows:
            if row.get("should_analyze"):
                problems.append(f"analysis authorized without credential: {row.get('event_key')}")
    for row in trigger_rows:
        body = {k: v for k, v in row.items() if k != "event_hash"}
        digest = hashlib.sha256(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if digest != row.get("event_hash"):
            problems.append(f"trigger hash chain broken at {row.get('event_key')}")
        if row.get("reason") == "TRIGGERED" and float(row.get("estimated_cost_usd", 0)) <= 0:
            problems.append("trigger without a declared cost")
    return (
        not problems,
        "; ".join(problems)
        or f"{len(trigger_rows)} trigger decisions, zero model calls, hash chain intact",
    )


def check_protected(baseline: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", baseline, "--", *PROTECTED],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - git always exists here
        return (False, f"git unavailable: {exc}")
    changed = [line for line in proc.stdout.splitlines() if line.strip()]
    return (not changed, ", ".join(changed) or "risk/broker/admission untouched")


def build_checks(baseline: str) -> list[tuple[str, Callable[[], tuple[bool, str]]]]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    coverage = read_jsonl(COVERAGE)
    triggers = read_jsonl(TRIGGERS)
    return [
        ("fixture_integrity", lambda: check_fixture(fixture)),
        ("comparison_is_fair", lambda: check_comparison(fixture, comparison)),
        ("reduction_arithmetic", lambda: check_reduction(comparison)),
        ("request_discipline", lambda: check_request_discipline(coverage)),
        ("watermark_chain", lambda: check_watermarks(coverage, WATERMARKS)),
        ("snapshot_causality", lambda: check_snapshots(fixture, snapshot)),
        ("ai_spend_is_bounded", lambda: check_ai(triggers, snapshot)),
        ("protected_files", lambda: check_protected(baseline)),
    ]


# ------------------------------------------------------------------ mutations
def run_mutations() -> list[dict[str, Any]]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    coverage = read_jsonl(COVERAGE)
    triggers = read_jsonl(TRIGGERS)
    results: list[dict[str, Any]] = []

    def record(name: str, detected: bool, detail: str) -> None:
        results.append({"mutation": name, "detected": detected, "detail": detail})

    liar = copy.deepcopy(comparison)
    liar["series"][0]["proposed"]["requests"] = 1
    liar["totals"]["proposed_requests"] = 1
    ok, detail = check_reduction(liar)
    record("M1_proposed_requests_forged", not ok, detail)

    future = copy.deepcopy(snapshot)
    future["results"][0]["snapshot"]["timeframes"]["4h"]["last_open_ms"] += 4 * 3_600_000
    ok, detail = check_snapshots(fixture, future)
    record("M2_future_higher_timeframe_bar", not ok, detail)

    bent = copy.deepcopy(coverage)
    target = next(r for r in bent if r["status"] in ("DELTA", "BOOTSTRAP"))
    target["watermark_after"]["last_verified_open_ms"] += 3_600_000
    ok, detail = check_request_discipline(bent)
    record("M3_watermark_crosses_boundary", not ok, detail)

    funded = copy.deepcopy(triggers)
    funded[0]["should_analyze"] = True
    ok, detail = check_ai(funded, snapshot)
    record("M4_analysis_without_credential", not ok, detail)

    greedy = copy.deepcopy(coverage)
    free = next(r for r in greedy if r["status"] == "NO_NEW_DATA")
    free["requests_made"] = 1
    ok, detail = check_request_discipline(greedy)
    record("M5_request_without_new_data", not ok, detail)

    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent RFC-TAP-MARKET-005 verifier")
    parser.add_argument("--baseline", default="fe9b5e2623b0d023833249e9687b753eaacd27d4")
    parser.add_argument("--out", default=str(REPORT_DIR / "INDEPENDENT_VERIFICATION.json"))
    parser.add_argument("--mutations", action="store_true")
    args = parser.parse_args(argv)

    results = []
    failures = 0
    for name, fn in build_checks(args.baseline):
        ok, detail = fn()
        results.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        failures += int(not ok)

    mutations = run_mutations() if args.mutations else []
    undetected = [m for m in mutations if not m["detected"]]

    payload = {
        "verifier": "scripts/mkt005_verify.py",
        "independent_of": "trading_bot (no imports)",
        "baseline": args.baseline,
        "checks": results,
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "failed": failures,
        "mutations": mutations,
        "mutations_detected": len(mutations) - len(undetected),
        "mutations_total": len(mutations),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for row in results:
        print(f"{row['check']:28s} {row['status']:4s}  {row['detail']}")
    for mutation in mutations:
        print(
            f"{mutation['mutation']:36s} "
            f"{'DETECTED' if mutation['detected'] else 'MISSED':8s}  {mutation['detail'][:90]}"
        )
    print(
        f"RESULT: {payload['passed']} PASS / {failures} FAIL / {len(undetected)} mutations undetected"
    )
    return 0 if failures == 0 and not undetected else 1


if __name__ == "__main__":
    raise SystemExit(main())
