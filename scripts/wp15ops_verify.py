"""Independent verification of the WP-TDM-015-OPS evidence.

    uv run python scripts/wp15ops_verify.py --run-id tdm15-ops-01 \
        --dashboard-url http://127.0.0.1:8793 --out evidence/tdm/wp-tdm-15-ops/VERIFY.json

Why this exists separately from ``wp15_evidence.py``: the evidence script
*collects*, and a collector that also grades its own homework is not a check. This
script re-derives every claim from the raw artefacts on disk — the window
manifests, the PAPER descriptor, the signal and analysis ledgers, the capture
manifest — and compares them with each other. It never reads
``OPS_EXECUTION.json``: if the two disagree, the artefacts win.

Each check is a sentence with the numbers that produced it, so a failure says what
is wrong instead of only that something is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "wp-tdm-015-ops-verify-v1"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc(ms: int | None = None) -> str:
    stamp = time.time() if ms is None else ms / 1000
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: str, **values: Any) -> None:
        self.items.append({"check": name, "ok": bool(ok), "detail": detail, **values})

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.items)

    @property
    def failed(self) -> list[str]:
        return [item["check"] for item in self.items if not item["ok"]]


def check_windows(checks: Checks, lab_root: Path) -> list[dict[str, Any]]:
    index = read_json(lab_root / "windows" / "INDEX.json")
    entries = [entry for entry in index.get("windows") or [] if isinstance(entry, dict)]
    windows_dir = lab_root / "windows"
    dirs = (
        sorted(path.name for path in windows_dir.iterdir() if path.is_dir())
        if windows_dir.exists()
        else []
    )
    checks.add(
        "window_index_matches_directories",
        len(entries) == len(dirs) and sorted(str(e.get("window_id")) for e in entries) == dirs,
        f"index lists {len(entries)} window(s), {len(dirs)} directory/directories exist",
        index=[str(entry.get("window_id")) for entry in entries],
        directories=dirs,
    )
    verified: list[dict[str, Any]] = []
    for entry in entries:
        window_dir = windows_dir / str(entry.get("window_id"))
        manifest = read_json(window_dir / "WINDOW_MANIFEST.json")
        files = [item for item in manifest.get("files") or [] if isinstance(item, dict)]
        bad: list[str] = []
        for item in files:
            path = window_dir / str(item.get("name"))
            if not path.exists() or sha256(path) != item.get("sha256"):
                bad.append(str(item.get("name")))
        checks.add(
            f"window_{entry.get('window_id')}_digests",
            bool(files) and not bad,
            f"{len(files)} archived file(s) re-hashed, {len(bad)} mismatch(es)",
            mismatched=bad,
        )
        # A restart must not fuse two windows into one journal (D-09): the closed
        # window's journal has to be a separate file with its own cycle numbers.
        journal = window_dir / "heartbeat.jsonl"
        cycles = [row.get("cycle") for row in read_jsonl(journal)] if journal.exists() else []
        duplicated = [cycle for cycle, count in Counter(cycles).items() if count > 1]
        checks.add(
            f"window_{entry.get('window_id')}_journal_not_duplicated",
            not duplicated,
            f"{len(cycles)} cycle row(s), duplicated cycle numbers: {duplicated or 'none'}",
            journal_lines=len(cycles),
        )
        paper = read_json(window_dir / "PAPER_RUN.json")
        has_provenance = all(
            paper.get(key) not in (None, [], "") for key in ("provider", "assets", "timeframe")
        )
        checks.add(
            f"window_{entry.get('window_id')}_paper_provenance",
            has_provenance,
            "archived PAPER descriptor carries provider/assets/timeframe"
            if has_provenance
            else "archived PAPER descriptor lost its provenance",
            provider=paper.get("provider"),
            environment=paper.get("environment"),
        )
        verified.append({"window_id": entry.get("window_id"), "journal_lines": len(cycles)})
    return verified


def check_descriptor(checks: Checks, paper_root: Path) -> dict[str, Any]:
    descriptor = read_json(paper_root / "PAPER_RUN.json")
    present = bool(descriptor)
    checks.add(
        "paper_descriptor_present",
        present,
        "PAPER_RUN.json exists" if present else "PAPER_RUN.json is missing",
    )
    if not present:
        return {}
    checks.add(
        "paper_descriptor_mode_is_paper",
        str(descriptor.get("mode")).lower() == "paper",
        f"mode={descriptor.get('mode')!r}",
    )
    if descriptor.get("state") == "STOPPED":
        missing = [
            key
            for key in ("provider", "environment", "assets", "timeframe")
            if descriptor.get(key) in (None, [], "")
        ]
        checks.add(
            "closed_descriptor_keeps_provenance",
            not missing,
            "a closed run still names its provider, environment, universe and timeframe"
            if not missing
            else f"closed descriptor is missing {missing}",
            missing=missing,
        )
    return descriptor


def check_signals(checks: Checks, paper_root: Path) -> dict[str, Any]:
    rows = read_jsonl(paper_root / "signals.jsonl")
    ids = [str(row.get("signal_id")) for row in rows if row.get("signal_id")]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    checks.add(
        "signal_ids_are_unique",
        bool(rows) and not duplicates,
        f"{len(rows)} signal row(s), {len(set(ids))} unique id(s)",
        duplicates=duplicates[:5],
    )
    stages = Counter(str(row.get("stage")) for row in rows)
    checks.add(
        "no_live_stage",
        stages.get("LIVE", 0) == 0,
        f"stages={dict(stages)}; LIVE rows must be zero because no live path exists",
    )
    stage_mismatch = [
        row.get("signal_id")
        for row in rows
        if str(row.get("stage")) == "SHADOW" and row.get("order_created") not in (False, None)
    ] + [
        row.get("signal_id")
        for row in rows
        if str(row.get("stage")) == "PAPER" and not row.get("order_created")
    ]
    checks.add(
        "stage_matches_order",
        not stage_mismatch,
        "no SHADOW row claims an order and no PAPER row lacks one"
        if not stage_mismatch
        else f"{len(stage_mismatch)} row(s) disagree with their stage",
        offenders=stage_mismatch[:5],
    )
    lookahead = [
        row.get("signal_id")
        for row in rows
        if isinstance(row.get("bar_close_time_ms"), int)
        and isinstance(row.get("decision_time_ms"), int)
        and row["bar_close_time_ms"] > row["decision_time_ms"]
    ]
    checks.add(
        "no_look_ahead",
        not lookahead,
        f"{len(lookahead)} signal(s) decided before their bar closed (must be 0)",
    )
    return {"rows": rows, "stages": dict(stages), "unique": len(set(ids))}


def check_analysis(checks: Checks, paper_root: Path, signal_ids: set[str]) -> dict[str, Any]:
    rows = read_jsonl(paper_root / "analysis.jsonl")
    statuses = Counter(str(row.get("status")) for row in rows)
    unknown = [row.get("signal_id") for row in rows if str(row.get("signal_id")) not in signal_ids]
    checks.add(
        "analysis_rows_point_at_real_signals",
        not unknown,
        f"{len(rows)} analysis row(s), {len(unknown)} reference a signal that does not exist",
        offenders=unknown[:5],
    )
    analysed = [row for row in rows if str(row.get("status")) == "ANALYZED"]
    incomplete = [
        row.get("analysis_id")
        for row in analysed
        if not (row.get("claim") and row.get("model"))
        or row.get("latency_ms") is None
        or (row.get("tokens_in") is None and row.get("tokens_out") is None)
    ]
    checks.add(
        "analysed_rows_carry_evidence",
        not incomplete,
        f"{len(analysed)} ANALYZED row(s); each must carry model, claim, latency and tokens",
        incomplete=incomplete[:5],
    )
    fake = [
        row.get("analysis_id")
        for row in rows
        if str(row.get("status")) == "NOT_CONFIGURED"
        and (row.get("error_code") != "PROVIDER_NOT_CONFIGURED" or row.get("claim"))
    ]
    checks.add(
        "not_configured_is_not_a_synthesis",
        not fake,
        "every NOT_CONFIGURED row says PROVIDER_NOT_CONFIGURED and claims nothing"
        if not fake
        else f"{len(fake)} NOT_CONFIGURED row(s) pretend to be analysis",
        offenders=fake[:5],
    )
    covered = {str(row.get("signal_id")) for row in rows if row.get("signal_id")}
    coverage = (len(covered) / len(signal_ids)) if signal_ids else 0.0
    checks.add(
        "analysis_coverage",
        not signal_ids or coverage >= 0.99,
        f"{len(covered)}/{len(signal_ids)} signals have an analysis row ({coverage:.1%})",
    )
    return {
        "rows": len(rows),
        "statuses": dict(statuses),
        "analysed": len(analysed),
        "covered": len(covered),
        "ai_verdict": "AI_REAL" if analysed else "AI_BLOCKED",
    }


def check_capture(checks: Checks, forward_root: Path, run_id: str) -> dict[str, Any]:
    manifest = read_json(forward_root / "manifest" / f"{run_id}.json")
    if not manifest:
        checks.add("capture_manifest_present", False, "no capture manifest for this run")
        return {}
    gaps = [gap for gap in manifest.get("gaps") or [] if isinstance(gap, dict)]
    classification = manifest.get("gaps_classification") or {}
    by_class = classification.get("by_class") or {}
    checks.add(
        "capture_gaps_are_classified",
        classification.get("total") == len(gaps)
        and sum(int(value) for value in by_class.values()) == len(gaps),
        f"{len(gaps)} gap(s) classified into {dict(by_class)}",
        total=classification.get("total"),
    )
    unrecoverable = int(by_class.get("UNRECOVERABLE", 0))
    continuity = manifest.get("continuity")
    checks.add(
        "continuity_matches_loss",
        (continuity == "INCOMPLETE_DATA") if unrecoverable else (continuity == "CONTINUOUS_DATA"),
        f"continuity={continuity!r} with {unrecoverable} unrecoverable gap(s)",
    )
    streams = [stream for stream in manifest.get("streams") or [] if isinstance(stream, dict)]
    # ``lossless`` describes the transport (a sequenced WS feed), not the outcome:
    # a lossless stream is exactly where loss is detectable. What must hold is that
    # the unrecovered part is a subset of the total gap time, and that loss never
    # appears on a stream that recorded no gap at all.
    inconsistent = [
        f"{stream.get('market')}/{stream.get('symbol')}/{stream.get('event_type')}"
        for stream in streams
        if float(stream.get("unrecovered_gap_seconds") or 0) > float(stream.get("gap_seconds") or 0)
        or (
            float(stream.get("unrecovered_gap_seconds") or 0) > 0
            and int(stream.get("gaps") or 0) == 0
        )
    ]
    checks.add(
        "stream_loss_is_a_subset_of_stream_gaps",
        not inconsistent,
        f"{len(streams)} stream(s); unrecovered loss exceeds total gap time on: "
        f"{inconsistent or 'none'}",
        offenders=inconsistent[:5],
    )
    return {
        "status": manifest.get("status"),
        "continuity": continuity,
        "gaps": len(gaps),
        "gaps_by_class": by_class,
        "segments": len(manifest.get("fingerprints") or []),
        "bytes": manifest.get("bytes_written"),
    }


def check_stop_report(checks: Checks, lab_root: Path) -> dict[str, Any]:
    report = read_json(lab_root / "LAB_RUN_REPORT.json")
    windows = read_json(lab_root / "windows" / "INDEX.json")
    entries = [entry for entry in windows.get("windows") or [] if isinstance(entry, dict)]
    print_report = report or {}
    if print_report:
        verdict = (print_report.get("stop_report") or {}).get("verdict")
        state = print_report.get("final_state")
        consistent = (state == "STOPPED" and verdict == "CLEAN") or (
            state == "FAILED" and verdict == "FAILED"
        )
        checks.add(
            "final_state_agrees_with_stop_verdict",
            consistent,
            f"final_state={state!r} with stop verdict {verdict!r}",
        )
        checks.add(
            "clean_stop_is_not_degraded",
            not (state in ("DEGRADED",) and verdict == "CLEAN"),
            f"final_state={state!r} (a clean stop must not report an operational fault)",
        )
    else:
        checks.add(
            "final_state_agrees_with_stop_verdict",
            bool(entries),
            "no live LAB_RUN_REPORT.json: the last closed window is the record"
            if entries
            else "no lab report and no archived window",
        )
    no_live = all(str(entry.get("stop_verdict")) in ("CLEAN", "FAILED") for entry in entries)
    checks.add(
        "windows_record_a_verdict",
        no_live,
        f"{len(entries)} archived window(s) each carry a stop verdict",
    )
    return {
        "final_state": print_report.get("final_state"),
        "stop_reason": print_report.get("stop_reason"),
        "stop_report": print_report.get("stop_report"),
        "archived_windows": len(entries),
    }


def check_dashboard(checks: Checks, url: str) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    ok = True
    for path in ("/healthz", "/api/status", "/api/signals?limit=5", "/api/analysis"):
        try:
            with urllib.request.urlopen(url.rstrip("/") + path, timeout=10) as response:
                body = response.read()
                status = response.status
        except (urllib.error.URLError, OSError) as exc:
            ok = False
            observed[path] = {"status": None, "error": str(exc)}
            continue
        entry: dict[str, Any] = {
            "status": status,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        if path.startswith("/api/"):
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            if path == "/api/status":
                entry["system_state"] = (payload.get("system") or {}).get("state")
                entry["running"] = (payload.get("system") or {}).get("running")
                entry["run_id"] = payload.get("run_id")
            if path == "/api/analysis":
                entry["store"] = payload.get("store") or payload.get("summary")
        observed[path] = entry
    served = all(entry.get("status") == 200 for entry in observed.values())
    checks.add(
        "dashboard_serves_read_only_views",
        served and ok,
        f"{sum(1 for e in observed.values() if e.get('status') == 200)}/{len(observed)} endpoint(s) returned 200",
    )
    status_state = (observed.get("/api/status") or {}).get("system_state")
    checks.add(
        "dashboard_state_is_a_known_state",
        status_state in ("HEALTHY", "DEGRADED", "FAILED", "STOPPED"),
        f"/api/status system.state={status_state!r}",
    )
    return {"url": url, "endpoints": observed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="tdm15-ops-01")
    parser.add_argument("--lab-root", default=None)
    parser.add_argument("--paper-root", default=None)
    parser.add_argument("--forward-root", default="reports/microstructure-forward-lab")
    parser.add_argument("--dashboard-url", default=None)
    parser.add_argument("--out", default="evidence/tdm/wp-tdm-15-ops/VERIFY.json")
    args = parser.parse_args(argv)

    lab_root = (
        Path(args.lab_root) if args.lab_root else REPO / "reports" / "paper-lab" / args.run_id
    )
    paper_root = (
        Path(args.paper_root)
        if args.paper_root
        else REPO / "reports" / "autonomous-paper" / args.run_id
    )
    forward_root = REPO / args.forward_root

    checks = Checks()
    windows = check_windows(checks, lab_root)
    descriptor = check_descriptor(checks, paper_root)
    signals = check_signals(checks, paper_root)
    signal_ids = {str(row.get("signal_id")) for row in signals["rows"] if row.get("signal_id")}
    analysis = check_analysis(checks, paper_root, signal_ids)
    capture = check_capture(checks, forward_root, args.run_id)
    lab = check_stop_report(checks, lab_root)
    dashboard = check_dashboard(checks, args.dashboard_url) if args.dashboard_url else None

    orders = int((descriptor.get("totals") or {}).get("orders_created") or 0)
    checks.add(
        "zero_orders_live_and_paper",
        orders == 0 and signals["stages"].get("LIVE", 0) == 0,
        f"orders_created={orders}, LIVE signals={signals['stages'].get('LIVE', 0)} "
        "(no strategy is admitted, so this is the expected number, not a success claim)",
    )

    payload = {
        "schema_version": SCHEMA,
        "generated_at_utc": utc(),
        "run_id": args.run_id,
        "commit": None,
        "ok": checks.ok,
        "failed": checks.failed,
        "counts": {
            "checks": len(checks.items),
            "passed": sum(1 for item in checks.items if item["ok"]),
            "failed": len(checks.failed),
        },
        "windows": windows,
        "paper": {
            "state": descriptor.get("state"),
            "provider": descriptor.get("provider"),
            "environment": descriptor.get("environment"),
            "orders_created": orders,
        },
        "signals": {
            "rows": len(signals["rows"]),
            "unique": signals["unique"],
            "stages": signals["stages"],
        },
        "analysis": analysis,
        "capture": capture,
        "lab": lab,
        "dashboard": dashboard,
        "checks": checks.items,
        "note": (
            "every check is recomputed from the artefacts of the run, not read from the "
            "evidence report; a disagreement here means the artefacts are what to believe"
        ),
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[verify] {payload['counts']['passed']}/{payload['counts']['checks']} checks passed"
        f" -> {out.relative_to(REPO)}"
    )
    for name in checks.failed:
        print(f"[verify] FAILED {name}")
    return 0 if checks.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
