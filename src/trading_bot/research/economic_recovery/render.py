"""RFC-EDGE-014 §6 — the deliverable set the brief names, rendered from the artefacts.

The brief enumerates an exact file name for every work package, and it asks for a
``PATH_MAP.md`` registering the authoritative equivalent whenever a name differs. This
module renders that set. Every figure is read from a JSON artefact the run already wrote,
so a markdown or CSV deliverable cannot drift from the record it summarises, and the
mapping back to the source is written next to it in ``PATH_MAP.md``.

Two rules the renderers obey. A CSV writes one row per record and never aggregates, so a
zero day and a zero-trade arm stay visible as rows. And a markdown file is rendered from
the same dictionary the JSON was rendered from, so a reader comparing the two is comparing
a rendering, not two independently maintained numbers.
"""

from __future__ import annotations

import csv
import io
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .evidence import REPO_ROOT, REPORTS

__all__ = [
    "DELIVERABLE_SOURCES",
    "build_manifest",
    "render_all",
    "write_environment_locks",
    "write_path_map",
]

#: Every named deliverable, and the JSON artefact it is rendered from.
DELIVERABLE_SOURCES: tuple[tuple[str, str], ...] = (
    ("runtime_authority_map.md", "RUNTIME_AUTHORITY_MAP.json"),
    ("TRADE_PATH_DIAGNOSIS.md", "TRADE_PATH_DIAGNOSIS.json"),
    ("MARKET_COST_RECONCILIATION.md", "MARKET_COST_RECONCILIATION.json"),
    ("FREQUENCY_DEFINITIONS.md", "FREQUENCY_DEFINITIONS.json"),
    ("CANDIDATE_EXPERIMENTS.md", "CANDIDATE_EXPERIMENTS.json"),
    ("REJECTED_CANDIDATES.md", "CANDIDATE_REGISTRY.json"),
    ("LICENSE_COMPATIBILITY.md", "CLONE_MANIFEST.json"),
    ("SECURITY_PREFLIGHT.md", "CLONE_MANIFEST.json"),
    ("BENCHMARK_PARITY_REPORT.md", "CLONE_MANIFEST.json"),
    ("INDEPENDENT_VERIFICATION.md", "INDEPENDENT_VERIFICATION.json"),
    ("PAPER_BLOCKED.md", "PAPER_GATE.json"),
    ("EDGE09R_PROVENANCE.md", "MARKET_COST_RECONCILIATION.json"),
    ("source_registry.md", "CLONE_MANIFEST.json"),
)


def _read(name: str) -> dict[str, Any]:
    path = REPORTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _write(name: str, text: str) -> Path:
    path = REPORTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")
    return "\n".join(out) + "\n"


def _csv_text(headers: list[str], rows: list[list[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if cell is None else cell for cell in row])
    return buffer.getvalue()


# ------------------------------------------------------------------ per-WP CSV evidence


def trade_funnel_csv() -> str:
    funnel = _read("TRADE_PATH_DIAGNOSIS.json")["funnel"]
    return _csv_text(
        ["stage", "count", "unit", "source", "field", "evidence_class"],
        [
            [s["stage"], s["count"], s["unit"], s["source"], s["field"], s["evidence_class"]]
            for s in funnel["stages"]
        ],
    )


def no_trade_cause_matrix_csv() -> str:
    reasons = _read("TRADE_PATH_DIAGNOSIS.json")["no_trade"]["by_reason"]
    rows = [
        [
            code,
            row["cycles"],
            row.get("decisions", 0),
            ";".join(row["raw_codes"].keys()) or "",
            row["explanation"],
        ]
        for code, row in reasons.items()
    ]
    return _csv_text(["reason_code", "cycles", "decisions", "raw_codes", "explanation"], rows)


def trade_frequency_by_day_csv() -> str:
    """One row per arm per UTC day, zero-trade days included."""
    payload = _read("CANDIDATE_EXPERIMENTS.json")
    rows: list[list[Any]] = []
    for name, result in payload["results"].items():
        if result.get("status") != "EXECUTED":
            continue
        measurement = result.get("measurement") or result.get("neutral")
        for day, count in sorted(measurement["trades_by_day"].items()):
            rows.append([name, day, count])
    return _csv_text(["arm", "utc_day", "trades"], rows)


def experiment_matrix_csv() -> str:
    payload = _read("CANDIDATE_EXPERIMENTS.json")
    rows = [
        [
            name,
            result.get("fill_class"),
            (result.get("measurement") or result.get("neutral") or {}).get("trades"),
            (result.get("measurement") or result.get("neutral") or {}).get("days_observed"),
            (result.get("measurement") or result.get("neutral") or {}).get("days_with_zero_trades"),
            (result.get("measurement") or result.get("neutral") or {}).get("mean_gross_bps"),
            (result.get("measurement") or result.get("neutral") or {}).get("mean_net_bps"),
            (result.get("measurement") or result.get("neutral") or {}).get("max_drawdown"),
            payload["oos_class"],
        ]
        for name, result in payload["results"].items()
    ]
    return _csv_text(
        [
            "arm",
            "fill_class",
            "trades",
            "days_observed",
            "days_with_zero_trades",
            "mean_gross_bps",
            "mean_net_bps",
            "max_drawdown",
            "oos_class",
        ],
        rows,
    )


def venue_cost_matrix_csv() -> str:
    scenarios = _read("MARKET_COST_RECONCILIATION.json")["per_scenario"]
    rows = [
        [
            name,
            row["venue"],
            row["product"],
            row["n"],
            row["mean_fee_bps"],
            row["mean_round_trip_bps"],
            row["fee_share_of_its_own_barrier"],
            row["components_sum_matches_round_trip"],
        ]
        for name, row in scenarios.items()
    ]
    return _csv_text(
        [
            "scenario",
            "venue",
            "product",
            "n_streams",
            "mean_fee_bps",
            "mean_round_trip_bps",
            "fee_share_of_own_barrier",
            "identity_holds",
        ],
        rows,
    )


def engine_diff_csv() -> str:
    """No external engine ran, so the diff is declared empty rather than fabricated."""
    payload = _read("CLONE_MANIFEST.json")
    plan = payload.get("parity_plan", {})
    rows = [
        [
            plan.get("neutral_strategy", {}).get("id"),
            "trading_agentic",
            "EXECUTED",
            "",
            "",
            "",
        ],
        [
            plan.get("neutral_strategy", {}).get("id"),
            "jesse(SRC-02)",
            "NOT_EXECUTED",
            "",
            "",
            "the pinned commit was fetched and its licence read, but no engine was installed or run",
        ],
    ]
    return _csv_text(
        ["neutral_strategy", "engine", "state", "equity_diff", "trade_count_diff", "note"], rows
    )


def sabotage_matrix_csv() -> str:
    cases = _read("INDEPENDENT_VERIFICATION.json")["sabotage"]["cases"]
    return _csv_text(
        ["id", "name", "kind", "detected", "detail"],
        [[c["id"], c["name"], c["kind"], c["detected"], c["detail"]] for c in cases],
    )


def gate_decisions_jsonl() -> str:
    payload = _read("PAPER_GATE.json")
    lines = [
        json.dumps(
            {
                "gate": gate["gate"],
                "decision": "BLOCKED",
                "evidence": gate["evidence"],
                "gates_relaxed": payload["gates_relaxed"],
                "risk_limits_changed": payload["risk_limits_changed"],
            },
            sort_keys=True,
        )
        for gate in payload["blocked_by"]
    ]
    return "\n".join(lines) + "\n"


def evidence_index_json() -> dict[str, Any]:
    entries = []
    for path in sorted(REPORTS.rglob("*")):
        if path.is_file() and path.name != "EVIDENCE_INDEX.json":
            entries.append(
                {
                    "name": str(path.relative_to(REPORTS)).replace("\\", "/"),
                    "bytes": path.stat().st_size,
                }
            )
    return {
        "schema_version": "EDGE14_EVIDENCE_INDEX_V1",
        "work_package": "WP-EDGE-14F",
        "n_files": len(entries),
        "files": entries,
        "note": "an index of what exists; the digests live in ARTIFACT_MANIFEST.json",
    }


def oos_holdout_manifest_json() -> dict[str, Any]:
    payload = _read("CANDIDATE_EXPERIMENTS.json")
    return {
        "schema_version": "EDGE14_OOS_HOLDOUT_MANIFEST_V1",
        "work_package": "WP-EDGE-14D",
        "oos_class": payload["oos_class"],
        "oos_is_fresh": payload["oos_is_fresh"],
        "corpora": payload["corpus_registry"]["corpora"],
        "consequence": payload["corpus_registry"]["consequence"],
        "data_manifest": payload["data_manifest"],
        "rule": (
            "an OOS is fresh only when its fingerprint covers data no selection step has "
            "touched; a temporal split inside a consumed corpus is descriptive only"
        ),
    }


def integrity_verification_json() -> dict[str, Any]:
    payload = _read("MARKET_COST_RECONCILIATION.json")
    return {
        "schema_version": "EDGE14_INTEGRITY_VERIFICATION_V1",
        "work_package": "WP-EDGE-14B",
        "primary_source": payload["primary_source"],
        "primary_source_sha256": payload["primary_source_sha256"],
        "primary_source_untouched": payload["primary_source_untouched"],
        "admission_claim": payload["admission_claim"],
        "cross_population_defect": payload["cross_population_defect"],
        "status_by_axis": payload["status_by_axis"],
        "verdict": payload["verdict"],
        "checked_by": "scripts/edge14_verify.py (independent arithmetic, own implementation)",
    }


# --------------------------------------------------------------------------- renderings


def _markdown(name: str) -> str:
    if name == "runtime_authority_map.md":
        payload = _read("RUNTIME_AUTHORITY_MAP.json")
        return (
            "# WP-EDGE-14A — runtime authority map\n\n"
            "*What is authoritative, what is only reachable, and what exists without an entrypoint.*\n\n"
            + _table(
                ["module", "classification", "present"],
                [[m["module"], m["classification"], m["present"]] for m in payload["modules"]],
            )
            + "\n## Authority chain\n\n"
            + " → ".join(payload["authority_chain"])
            + f"\n\n{payload['third_parties_are_not_runtime']}\n"
        )
    if name == "TRADE_PATH_DIAGNOSIS.md":
        payload = _read("TRADE_PATH_DIAGNOSIS.json")
        head = payload["funnel"]["headline"]
        return (
            "# WP-EDGE-14A — trade path diagnosis\n\n"
            f"*Window `{payload['window']['first_operation_utc']}` → "
            f"`{payload['window']['last_operation_utc']}` ({payload['window']['span_days']} days, "
            f"requested {payload['window']['requested_days']}).*\n\n"
            f"Live status **{payload['live_status']}**: {payload['live_status_basis']}\n\n"
            "## Funnel\n\n"
            + _table(
                ["stage", "count", "evidence class", "note"],
                [
                    [
                        s["stage"],
                        s["count"] if s["count"] is not None else "UNKNOWN",
                        s["evidence_class"],
                        s["note"],
                    ]
                    for s in payload["funnel"]["stages"]
                ],
            )
            + "\n## Headline\n\n"
            + _table(
                ["measure", "value"],
                [[k, v] for k, v in head.items()],
            )
            + f"\n{payload['absence_vs_zero']}\n\n{payload['smallest_honest_claim']}\n"
        )
    if name == "MARKET_COST_RECONCILIATION.md":
        payload = _read("MARKET_COST_RECONCILIATION.json")
        defect = payload["cross_population_defect"]
        adm = payload["admission_claim"]
        return (
            "# WP-EDGE-14B — market cost reconciliation\n\n"
            f"*Primary source `{payload['primary_source']}` "
            f"(`{payload['primary_source_sha256'][:16]}…`), untouched: "
            f"{payload['primary_source_untouched']}.*\n\n"
            f"**Verdict `{payload['verdict']}`.**\n\n"
            "## The legitimate same-population share\n\n"
            + _table(
                ["scenario", "n streams", "mean fee (bps)", "mean round trip (bps)", "share"],
                [
                    [
                        adm["scenario"],
                        adm["n_streams"],
                        adm["mean_fee_bps"],
                        adm["mean_round_trip_bps"],
                        f"{adm['fee_share_percent']}%",
                    ]
                ],
            )
            + "\n## The published ratio, reproduced and explained\n\n"
            + _table(
                ["side", "value (bps)", "population", "n"],
                [
                    [
                        "numerator",
                        defect["numerator"]["value_bps"],
                        defect["numerator"]["population"],
                        defect["numerator"]["n_schedules"],
                    ],
                    [
                        "denominator",
                        defect["denominator"]["value_bps"],
                        defect["denominator"]["population"],
                        defect["denominator"]["n_assets"],
                    ],
                ],
            )
            + f"\nReproduced `{defect['published_ratio']}` — matches the published 1.3863: "
            f"**{defect['matches_published_1_3863']}**.\n\n"
            f"Defect: `{defect['defect']}`. {defect['explanation']}\n\n"
            f"Correct statement: {defect['correct_statement']}\n\n"
            "## Per-scenario breakdowns\n\n"
            + _table(
                ["scenario", "mean fee", "mean round trip", "status"],
                [
                    [b["scenario_id"], b["entry_fee_bps"], b["round_trip_bps"], b["status"]]
                    for b in payload["breakdowns"]
                ],
            )
        )
    if name == "FREQUENCY_DEFINITIONS.md":
        payload = _read("FREQUENCY_DEFINITIONS.json")
        two = payload["the_two_numbers"]
        return (
            "# WP-EDGE-14B — frequency definitions\n\n"
            f"**Verdict `{payload['verdict']}`.**\n\n"
            "## The three numbers at 60 s, each with its rule\n\n"
            + _table(
                ["name", "window rule", "direction", "unit", "is the ACTIVE denominator"],
                [
                    [
                        d["name"],
                        d["window_rule"],
                        d["direction_filter"],
                        d["unit"],
                        d["is_the_active_denominator"],
                    ]
                    for d in payload["definitions"]
                ],
            )
            + "\n## The two published numbers\n\n"
            + _table(
                ["measure", "value per day"],
                [
                    [
                        "selector, long-only, overlapping",
                        two["selector_long_only_overlapping_per_day"],
                    ],
                    ["tape bound, non-overlapping", two["tape_bound_non_overlapping_per_day"]],
                ],
            )
            + f"\nSame metric: **{two['same_metric']}**. {two['why']}\n\n"
            f"The ACTIVE target ({payload['active_target']}/day) is measured against "
            f"`{payload['active_target_measured_against']}`.\n"
        )
    if name == "CANDIDATE_EXPERIMENTS.md":
        payload = _read("CANDIDATE_EXPERIMENTS.json")
        return (
            "# WP-EDGE-14D — candidate experiments\n\n"
            f"*Round trip charged per trade: `{payload['round_trip_cost_bps']}` bps. "
            f"OOS class `{payload['oos_class']}`, fresh: {payload['oos_is_fresh']}.*\n\n"
            f"**Verdict `{payload['verdict']}`.**\n\n"
            + _table(
                ["arm", "trades", "days", "zero days", "mean gross (bps)", "mean net (bps)"],
                [
                    [
                        name,
                        (r.get("measurement") or r.get("neutral"))["trades"],
                        (r.get("measurement") or r.get("neutral"))["days_observed"],
                        (r.get("measurement") or r.get("neutral"))["days_with_zero_trades"],
                        (r.get("measurement") or r.get("neutral"))["mean_gross_bps"],
                        (r.get("measurement") or r.get("neutral"))["mean_net_bps"],
                    ]
                    for name, r in payload["results"].items()
                ],
            )
            + f"\nArms net-positive: **{len(payload['net_positive_arms'])}**.\n\n"
            + "\n".join(f"- {limitation}" for limitation in payload["limitations"])
            + "\n"
        )
    if name == "REJECTED_CANDIDATES.md":
        payload = _read("CANDIDATE_REGISTRY.json")
        rejected = [c for c in payload["candidates"] if c["admission_status"] == "REJECTED"]
        retained = [c for c in payload["candidates"] if c["admission_status"] != "REJECTED"]
        return (
            "# WP-EDGE-14D — rejected candidates\n\n"
            f"{payload['n_rejected_duplicate']} of {payload['n_registered']} hypotheses were rejected as "
            "duplicates of families already in the tree. A duplicate is never renamed to look new.\n\n"
            "## Rejected\n\n"
            + _table(
                ["id", "family", "duplicated of", "reason"],
                [
                    [
                        c["candidate_id"],
                        c["family"],
                        ", ".join(c["duplicate_of"]),
                        c["duplicate_reason"],
                    ]
                    for c in rejected
                ],
            )
            + "\n## Retained\n\n"
            + _table(
                ["id", "family", "status", "hypothesis"],
                [
                    [c["candidate_id"], c["family"], c["admission_status"], c["hypothesis"]]
                    for c in retained
                ],
            )
        )
    if name == "LICENSE_COMPATIBILITY.md":
        payload = _read("CLONE_MANIFEST.json")
        preflight = payload["license_preflight"]
        return (
            "# WP-EDGE-14C — licence compatibility\n\n"
            f"{preflight['default_verdict']}\n\n"
            + _table(
                ["id", "repo", "declared", "classification", "may copy", "copy rule"],
                [
                    [
                        s["id"],
                        s["repo"],
                        s["declared_license"],
                        s["classification"],
                        s["may_copy_into_this_project"],
                        s["copy_rule"],
                    ]
                    for s in preflight["sources"]
                ],
            )
            + f"\nNot copyable: `{', '.join(preflight['not_copyable'])}`.\n"
        )
    if name == "SECURITY_PREFLIGHT.md":
        payload = _read("CLONE_MANIFEST.json")
        probe = payload["clone_probe"]
        pins = payload["pin_verification"]
        return (
            "# WP-EDGE-14C — security preflight\n\n"
            f"- clones live outside the checkout: `{probe['clone_root']}`\n"
            "- no credential was mounted, no engine was installed, nothing was imported\n"
            f"- network probe: `{probe['network_probe']['reason']}`\n"
            f"- pins resolved: {pins['n_pins_resolved']}/{pins['n_verified']}\n"
            "- a third-party engine cannot send an order or replace Risk or Execution\n"
        )
    if name == "BENCHMARK_PARITY_REPORT.md":
        payload = _read("CLONE_MANIFEST.json")
        plan = payload["parity_plan"]
        tolerance = plan["preregistered_tolerance"]
        return (
            "# WP-EDGE-14C — benchmark parity report\n\n"
            f"**State: pins verified, no engine executed.** {payload['clone_probe']['note']}\n\n"
            "## Neutral strategy\n\n"
            + _table(
                ["id", "rule", "why neutral"],
                [
                    [
                        plan["neutral_strategy"]["id"],
                        plan["neutral_strategy"]["rule"],
                        plan["neutral_strategy"]["why_neutral"],
                    ]
                ],
            )
            + "\n## Preregistered tolerance\n\n"
            + _table(
                ["measure", "max difference"],
                [
                    ["equity relative", tolerance["equity_relative_diff_max"]],
                    ["trade count", tolerance["trade_count_diff_max"]],
                    ["per-trade net bps", tolerance["per_trade_net_bps_diff_max"]],
                ],
            )
            + f"\nDeclared before the run: **{tolerance['declared_before_run']}**. "
            f"On exceed: {tolerance['on_exceed']}\n\n"
            "## Engine states\n\n"
            + _table(
                ["engine", "state"],
                [["trading_agentic", "EXECUTED"], ["jesse(SRC-02)", "NOT_EXECUTED (fetched only)"]],
            )
        )
    if name == "INDEPENDENT_VERIFICATION.md":
        payload = _read("INDEPENDENT_VERIFICATION.json")
        return (
            "# WP-EDGE-14F — independent verification\n\n"
            f"**{payload['verdict']}** — {payload['n_passed']}/{payload['n_checks']} checks, "
            f"{payload['n_sabotage_detected']}/{len(payload['sabotage']['cases'])} tamperings detected.\n\n"
            f"The builder's modules are not imported for decisive arithmetic: "
            f"`{payload['builder_imported_for_decisive_arithmetic']}`.\n\n"
            + _table(
                ["check", "result", "detail"],
                [
                    ["`" + c["name"] + "`", "PASS" if c["passed"] else "FAIL", c["detail"]]
                    for c in payload["checks"]
                ],
            )
            + "\n## Sabotage matrix\n\n"
            + _table(
                ["id", "tampering", "kind", "detected"],
                [
                    [c["id"], c["name"], c["kind"], c["detected"]]
                    for c in payload["sabotage"]["cases"]
                ],
            )
        )
    if name == "PAPER_BLOCKED.md":
        payload = _read("PAPER_GATE.json")
        return (
            "# WP-EDGE-14E — paper blocked\n\n"
            f"**{payload['status']}**\n\n"
            + _table(
                ["gate", "evidence"], [[g["gate"], g["evidence"]] for g in payload["blocked_by"]]
            )
            + f"\nGates relaxed: `{payload['gates_relaxed']}`. Risk limits changed: "
            f"**{payload['risk_limits_changed']}**. Forward days waived: {payload['forward_days_waived']}.\n\n"
            f"{payload['note']}\n"
        )
    if name == "EDGE09R_PROVENANCE.md":
        payload = _read("MARKET_COST_RECONCILIATION.json")
        return (
            "# WP-EDGE-14B — WP-EDGE-09 provenance\n\n"
            f"- primary artefact: `{payload['primary_source']}`\n"
            f"- sha256 at the time of this reading: `{payload['primary_source_sha256']}`\n"
            f"- the original was not edited: **{payload['primary_source_untouched']}**\n"
            "- the 1.3863 sentence is superseded by reference, and its bytes are preserved\n"
            f"- status by axis: `{payload['status_by_axis']}`\n\n"
            "Keeping the original and publishing the supersession is what makes the "
            "reconciliation auditable: a report that edited the document it audits would "
            "have destroyed the evidence that the defect existed.\n"
        )
    if name == "source_registry.md":
        payload = _read("CLONE_MANIFEST.json")
        pins = payload["pin_verification"]
        return (
            "# RFC-EDGE-014 — source registry\n\n"
            "Each source is pinned to a full SHA, and its licence is read from the licence "
            "file at that commit rather than from the brief's table.\n\n"
            + _table(
                ["id", "repo", "pinned sha", "pin resolves", "licence family from file", "rule"],
                [
                    [
                        v["id"],
                        v["repo"],
                        "`" + v["pinned_sha"] + "`",
                        v["pin_resolves"],
                        v["licence_family_from_file"],
                        v["licence_rule"],
                    ]
                    for v in pins["verified"]
                ],
            )
        )
    raise KeyError(name)


def write_environment_locks() -> list[str]:
    """Record the environment the measurements ran in, as manifests not binaries."""
    lock_dir = REPORTS / "ENVIRONMENT_LOCKS"
    lock_dir.mkdir(parents=True, exist_ok=True)
    written = []
    runtime = (
        f"python: {sys.version}\n"
        f"executable: {sys.executable}\n"
        f"platform: {platform.platform()}\n"
        f"machine: {platform.machine()}\n"
        f"processor: {platform.processor()}\n"
    )
    (lock_dir / "runtime.txt").write_text(runtime, encoding="utf-8")
    written.append("runtime.txt")

    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    (lock_dir / "pip_freeze.txt").write_text(
        freeze.stdout or f"pip freeze failed with exit {freeze.returncode}\n", encoding="utf-8"
    )
    written.append("pip_freeze.txt")

    pinned = "\n".join(
        f"{v['id']} {v['repo']} {v['pinned_sha']} licence_from_file={v['licence_family_from_file']}"
        for v in _read("CLONE_MANIFEST.json").get("pin_verification", {}).get("verified", [])
    )
    (lock_dir / "external_sources.txt").write_text(pinned + "\n", encoding="utf-8")
    written.append("external_sources.txt")
    return written


def write_path_map() -> str:
    """Register the authoritative path for every deliverable the brief names."""
    artifacts = sorted(p.name for p in REPORTS.iterdir() if p.is_file())
    rows = [
        ["BASELINE.json", "14A", "present as named"],
        ["runtime_authority_map.md", "14A", "rendered from RUNTIME_AUTHORITY_MAP.json"],
        ["TRADE_PATH_DIAGNOSIS.md / .json", "14A", "present as named"],
        ["TRADE_FUNNEL.csv", "14A", "present as named"],
        ["NO_TRADE_CAUSE_MATRIX.csv", "14A", "present as named"],
        ["EVIDENCE_INDEX.json", "14A", "present as named"],
        ["MARKET_COST_RECONCILIATION.md / .json", "14B", "present as named"],
        ["EDGE09R_PROVENANCE.md", "14B", "present as named"],
        ["VENUE_COST_MATRIX.csv", "14B", "present as named"],
        ["FREQUENCY_DEFINITIONS.md", "14B", "rendered from FREQUENCY_DEFINITIONS.json"],
        ["INTEGRITY_VERIFICATION.json", "14B", "present as named"],
        ["source_registry.md", "14C", "present as named"],
        ["CLONE_MANIFEST.json", "14C", "present as named"],
        ["LICENSE_COMPATIBILITY.md", "14C", "present as named"],
        ["SECURITY_PREFLIGHT.md", "14C", "present as named"],
        ["BENCHMARK_PARITY_REPORT.md", "14C", "present as named"],
        ["ENGINE_DIFF.csv", "14C", "present as named"],
        ["ENVIRONMENT_LOCKS/", "14C", "present as named"],
        ["CANDIDATE_SPECS/*.md", "14D", "present as named"],
        ["CANDIDATE_REGISTRY.json", "14D", "present as named"],
        ["EXPERIMENT_MATRIX.csv", "14D", "present as named"],
        ["CANDIDATE_EXPERIMENTS.md / .json", "14D", "present as named"],
        ["OOS_HOLDOUT_MANIFEST.json", "14D", "present as named"],
        ["TRADE_FREQUENCY_BY_DAY.csv", "14D/14E", "present as named"],
        ["REJECTED_CANDIDATES.md", "14D", "present as named"],
        ["PAPER_BLOCKED.md", "14E", "present as named (the gate blocked)"],
        ["GATE_DECISIONS.jsonl", "14E", "present as named"],
        ["INDEPENDENT_VERIFICATION.md / .json", "14F", "present as named"],
        ["SABOTAGE_MATRIX.csv", "14F", "present as named"],
        ["RUN_REPORT.md / .json", "14F", "present as named"],
        ["FINAL_REPORT.md", "14F", "present as named"],
        ["INFORME_EJECUTIVO.md", "14F", "present as named"],
        ["GIT_STATE.json", "14F", "present as named"],
    ]
    text = (
        "# RFC-EDGE-014 — PATH_MAP\n\n"
        "The brief enumerates an exact file name per work package and allows an "
        "authoritative equivalent registered here. An artefact this package writes from a "
        "JSON record is a *rendering* of that record, never an independent source: editing "
        "the markdown would not change the record, and re-rendering would overwrite it.\n\n"
        "**Authoritative root:** `reports/economic-recovery/RFC-EDGE-014/`\n\n"
        "**Code root:** `src/trading_bot/research/economic_recovery/` (the brief allows an "
        "authoritative equivalent for `research/economic-recovery/RFC-EDGE-014/`; the "
        "package lives under the existing research tree so it is importable and testable "
        "like every other work package in this repository).\n\n"
        "## Named deliverables\n\n"
        + _table(["named deliverable", "WP", "authoritative path"], rows)
        + "\n## Every file present at render time\n\n"
        + "\n".join(f"- `{name}`" for name in artifacts)
        + "\n"
    )
    return text


def build_manifest() -> dict[str, Any]:
    """Digest every artefact in the package, excluding the manifest itself.

    Hashing a file before rewriting it produces a table that describes a version of
    itself that no longer exists, so the manifest is written last and never lists itself.
    Because the renderers and the reports both run before this, the digests cover the
    markdown, the CSVs and the closure reports, not only the JSON payloads.
    """
    import hashlib

    # Two files cannot carry a stable digest here. The manifest cannot list itself, and
    # the verifier rewrites its own report every time it runs, so a digest taken now would
    # be stale the moment a reader re-ran the check. Both exclusions are declared rather
    # than left for a reader to notice.
    excluded = ("ARTIFACT_MANIFEST.json", "INDEPENDENT_VERIFICATION.json")
    entries: dict[str, str] = {}
    for path in sorted(REPORTS.rglob("*")):
        if not path.is_file() or path.name in excluded:
            continue
        relative = str(path.relative_to(REPORTS)).replace("\\", "/")
        entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {
        "schema_version": "EDGE14_ARTIFACT_MANIFEST_V1",
        "generated_at_utc": _now(),
        "n_artifacts": len(entries),
        "artifacts": entries,
        "excludes": list(excluded),
        "excludes_because": {
            "ARTIFACT_MANIFEST.json": "a manifest cannot digest itself",
            "INDEPENDENT_VERIFICATION.json": "the verifier rewrites it on every run, so its digest would always be stale",
        },
        "note": (
            "the manifest is written last and lists only files whose bytes are stable "
            "between a render and a read"
        ),
        "promotion": "NONE",
        "order_sent": False,
    }
    _write("ARTIFACT_MANIFEST.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_all() -> dict[str, str]:
    written: dict[str, str] = {}
    for name, _source in DELIVERABLE_SOURCES:
        written[name] = _write(name, _markdown(name)).name
    for name, text in (
        ("TRADE_FUNNEL.csv", trade_funnel_csv()),
        ("NO_TRADE_CAUSE_MATRIX.csv", no_trade_cause_matrix_csv()),
        ("TRADE_FREQUENCY_BY_DAY.csv", trade_frequency_by_day_csv()),
        ("EXPERIMENT_MATRIX.csv", experiment_matrix_csv()),
        ("VENUE_COST_MATRIX.csv", venue_cost_matrix_csv()),
        ("ENGINE_DIFF.csv", engine_diff_csv()),
        ("SABOTAGE_MATRIX.csv", sabotage_matrix_csv()),
        ("GATE_DECISIONS.jsonl", gate_decisions_jsonl()),
    ):
        written[name] = _write(name, text).name
    for name, payload in (
        ("EVIDENCE_INDEX.json", evidence_index_json()),
        ("OOS_HOLDOUT_MANIFEST.json", oos_holdout_manifest_json()),
        ("INTEGRITY_VERIFICATION.json", integrity_verification_json()),
    ):
        written[name] = _write(
            name, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
        ).name
    for name in write_environment_locks():
        written[f"ENVIRONMENT_LOCKS/{name}"] = name
    written["PATH_MAP.md"] = _write("PATH_MAP.md", write_path_map()).name
    return written
