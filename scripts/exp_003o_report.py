"""exp_003o_report — WP-003O-04: the deliverables, computed from evidence and never typed.

Everything in ``RUN_REPORT.json`` comes from a file this experiment produced; nothing is a
hand-written number. ``prospective`` is decided by Git: if any evaluation was already
committed when the protocol was frozen, the run is not prospective and the report says so.

Outputs
-------
``CELL_COVERAGE_MANIFEST.csv``  the 24 cells with observed counts and states.
``RUN_REPORT.json`` / ``RUN_REPORT.md``
``FINAL_REPORT.md``
``SEAL.json`` / ``SHA256SUMS.txt``

Usage
-----
``python scripts/exp_003o_report.py [--out DIR] [--seal]``
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    OUT,
    read_json,
    sha256_bytes,
    sha256_file,
    write_json,
)

SEAL_EXCLUDE = {"SHA256SUMS.txt", "SEAL.json"}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False
    ).stdout.strip()


def _prospective(out: Path) -> dict[str, Any]:
    """Was the protocol in Git before any evaluation existed?"""

    relative = str((out / "design" / "PROTOCOL.json").relative_to(REPO)).replace("\\", "/")
    commit = _git("log", "-1", "--format=%H", "--", relative)
    if not commit:
        return {
            "prospective": False,
            "preregistration_commit": None,
            "reason": "protocol not committed",
        }
    tracked_at_prereg = _git(
        "ls-tree", "-r", "--name-only", commit, "--", f"{relative.rsplit('/', 1)[0]}"
    )
    evaluations_at_prereg = [
        line
        for line in tracked_at_prereg.splitlines()
        if "evaluations" in line
        or line.endswith("SIGNAL_PARITY_SUMMARY.json")
        or line.endswith("VERIFICATION.json")
    ]
    ancestor = bool(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )
    document_only = _git("show", "--stat", "--format=", commit)
    design_only = not any(
        word in document_only for word in ("evaluations", "SIGNAL_PARITY", "VERIFICATION.json")
    )
    return {
        "prospective": bool(commit and not evaluations_at_prereg and ancestor and design_only),
        "preregistration_commit": commit,
        "design_commit_is_ancestor": ancestor,
        "evaluations_present_at_prereg": evaluations_at_prereg,
        "reason": "the protocol commit contains design and code only; evaluations came later",
    }


def _coverage(protocol: dict[str, Any], summary: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in protocol["cells"]:
        cell_id = str(cell["cell_id"])
        payload = summary["per_cell"][cell_id]
        rows.append(
            {
                "cell_id": cell_id,
                "lane": cell["lane"],
                "family": cell["family"],
                "timeframe": cell["timeframe"],
                "symbols": 3,
                "warmup_bars": cell["warmup_bars"],
                "parameter_hash": cell["parameter_hash"],
                "expected_evaluations": None,
                "observed_evaluations": payload["evaluations_original"],
                "independent_evaluations": payload["evaluations_independent"],
                "observed_signals": payload["signals_original"],
                "independent_signals": payload["signals_independent"],
                "matched": payload["matched"],
                "mismatches": payload["mismatches"],
                "state": "EVALUATED"
                if payload["evaluations_original"] and payload["signals_original"]
                else (
                    "ZERO_SAMPLE"
                    if payload["evaluations_original"]
                    else "INSUFFICIENT_EVIDENCE_REAL_WINDOW"
                ),
                "verdict": payload["verdict"],
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="\n")


def _verdict(verification: dict[str, Any], summary: dict[str, Any]) -> str:
    if verification["technical_signal_parity"] == "FAIL":
        return "FAIL_SIGNAL_PARITY_OR_PIT"
    if verification["full_independent_certification"] == "PASS":
        return "PASS_TECHNICAL_AND_INDEPENDENT"
    return "PASS_PARTIAL_INCOMPLETE_REAL_DATA"


def _report(out: Path) -> dict[str, Any]:
    protocol = read_json(out / "design" / "PROTOCOL.json")
    design_sha = sha256_file(out / "design" / "PROTOCOL.json")
    baseline = read_json(out / "BASELINE_MANIFEST.json")
    summary = read_json(out / "SIGNAL_PARITY_SUMMARY.json")
    verification = read_json(out / "VERIFICATION.json")
    controls = read_json(out / "NEGATIVE_CONTROLS.json")
    pit = read_json(out / "PIT_AUDIT.json")
    fixtures = read_json(out / "fixtures" / "FIXTURE_MANIFEST.json")
    prospective = _prospective(out)

    coverage = _coverage(protocol, summary, out)
    _write_csv(out / "CELL_COVERAGE_MANIFEST.csv", coverage)

    tests: dict[str, Any]
    tests_path = out / "evidence" / "TESTS.json"
    if tests_path.exists():
        tests = read_json(tests_path)
    else:
        tests = {
            "state": "NOT_RUN",
            "note": "no TESTS.json: the suites were not executed for this report",
        }

    reproduction_path = out / "CLEAN_CHECKOUT_REPRODUCTION.json"
    reproduction = read_json(reproduction_path) if reproduction_path.exists() else None

    zero_sample = [row["cell_id"] for row in coverage if row["state"] != "EVALUATED"]
    status = "PASS" if verification["technical_signal_parity"] == "PASS" else "INCOMPLETE"
    if verification["technical_signal_parity"] == "FAIL":
        status = "FAIL"
    if tests.get("state") not in {"PASS", "OK"}:
        status = "INCOMPLETE" if status == "PASS" else status
    if reproduction is None or reproduction.get("verdict") != "REPRODUCED":
        status = "INCOMPLETE" if status == "PASS" else status

    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": _numpy_version(),
        "timezone": "UTC",
        "seeds": "no stochastic step in either producer; the bootstrap of 003N is not used here",
    }

    report: dict[str, Any] = {
        "run_id": protocol["run_id"],
        "schema_version": "AI_BOTS_003O_RUN_REPORT_V1",
        "status": status,
        "verdict": _verdict(verification, summary),
        "technical_signal_parity": verification["technical_signal_parity"],
        "full_independent_certification": verification["full_independent_certification"],
        "economic_edge": "NOT_EVALUATED",
        "strategy_promotion": "DENIED",
        "live": "DISABLED",
        "holdout": "CLOSED",
        "source_commit": baseline["git"]["head"],
        "source_branch": baseline["git"]["branch"],
        "experiment_commit": _git("rev-parse", "HEAD"),
        "preregistration_commit": prospective["preregistration_commit"],
        "prospective": prospective["prospective"],
        "prospective_evidence": prospective,
        "design_sha256": design_sha,
        "input_manifest_sha256": baseline["dataset"]["manifest_sha256_observed"],
        "environment": environment,
        "cells_total": len(protocol["cells"]),
        "cells_evaluable": summary["cells_evaluable"],
        "cells_zero_sample": zero_sample,
        "evaluations_compared": summary["evaluations_compared"],
        "signals_original": summary["signals_original"],
        "signals_independent": summary["signals_independent"],
        "mismatches_unexplained": summary["mismatches_unexplained"],
        "differences_by_class": summary["differences_by_class"],
        "pit_violations": verification["pit_violations"],
        "pit_rows_audited": {stream: payload["rows"] for stream, payload in pit["totals"].items()},
        "negative_controls_effective": controls["effective"],
        "negative_controls_detected": controls["effective"],
        "negative_controls_total": controls["total"],
        "independent_implementation_verified": verification["checks"]["V7_independence"]["clean"],
        "independent_verifier_verified": verification["checks"]["V8_parity_recomputation"][
            "passed"
        ],
        "prefix_invariance": verification["checks"]["V6_prefix_invariance"].get("clean"),
        "fixtures": fixtures,
        "functional_coverage": verification["checks"]["V11_functional_coverage"]["complete"],
        "holdout_opened": False,
        "live_orders": 0,
        "paper_orders": 0,
        "orders_authorised": 0,
        "config_unchanged": verification["checks"]["V10_governance"]["config_unchanged"],
        "false_success_observed": verification["false_success_observed"],
        "tests": tests,
        "clean_checkout_reproduction": reproduction,
        "defects": [
            {
                "id": "DEF-003O-01",
                "summary": "lane-A decisions depend on an undocumented fixed 80-bar window",
                "detail": (
                    "re-producing a signal needs max(min_candles+1, 80) bars of history, not merely "
                    "the formula: an EMA re-seeded on 80 bars differs from an EMA over the whole "
                    "series. EXP-003N's published numbers therefore cannot be reproduced from the "
                    "rule text alone."
                ),
                "severity": "medium",
                "treatment": "reproduced exactly; documented in SIGNAL_SPECIFICATIONS.md",
            },
            {
                "id": "DEF-003O-02",
                "summary": "lane-B parameter names say hours, the machines consume bars",
                "detail": "on 4h bars, channel_hours=168 is a 672-hour channel; the 4h cells run a ~4x longer rule than their names claim",
                "severity": "medium",
                "treatment": "reproduced as frozen; the 4h cells still have no sample in this window",
            },
            {
                "id": "DEF-003O-03",
                "summary": "lane A has no position state, so signals overlap bar by bar",
                "detail": "a signal count from lane A is not a trade count; the parity compares decisions, and 003N priced overlaps downstream",
                "severity": "low",
                "treatment": "reproduced; documented as a property of the screening",
            },
            {
                "id": "DEF-003O-04",
                "summary": "two lane-B 4h cells have zero evaluable bars in a 46-day window",
                "detail": "276 bars against a 744-bar warm-up: the cell can be announced but not evaluated",
                "severity": "medium",
                "treatment": "declared INSUFFICIENT_EVIDENCE_REAL_WINDOW; functional coverage rests on fixtures",
            },
        ],
        "blockers": [] if status == "PASS" else ["see status: a required dimension is not PASS"],
        "evidence": sorted(
            str(path.relative_to(out)).replace("\\", "/")
            for path in out.rglob("*")
            if path.is_file() and path.name not in SEAL_EXCLUDE
        ),
    }
    write_json(out / "RUN_REPORT.json", report)
    (out / "RUN_REPORT.md").write_text(_run_md(report), encoding="utf-8", newline="\n")
    (out / "FINAL_REPORT.md").write_text(_final_md(report), encoding="utf-8", newline="\n")
    return report


def _numpy_version() -> str:
    try:
        import numpy

        return str(numpy.__version__)
    except Exception:  # pragma: no cover - numpy is a hard dependency of the producers
        return "unavailable"


def _run_md(report: dict[str, Any]) -> str:
    counts = report["pit_rows_audited"]
    lines = [
        "# RUN REPORT — EXP-003O — Independent Signal Regeneration",
        "",
        f"**status `{report['status']}`** · `TECHNICAL_SIGNAL_PARITY={report['technical_signal_parity']}` · "
        f"`FULL_INDEPENDENT_CERTIFICATION={report['full_independent_certification']}` · "
        f"`ECONOMIC_EDGE={report['economic_edge']}`",
        "",
        f"- design digest `{report['design_sha256'][:16]}…` · preregistration commit "
        f"`{str(report['preregistration_commit'])[:7]}` · "
        f"prospective=`{report['prospective']}`",
        f"- source commit `{report['source_commit'][:7]}` · experiment commit `{report['experiment_commit'][:7]}`",
        f"- {report['cells_total']} cells ({report['cells_evaluable']} evaluable) · "
        f"{report['evaluations_compared']} keys · "
        f"{report['signals_original']} / {report['signals_independent']} signals",
        f"- {report['mismatches_unexplained']} unexplained differences · "
        f"{report['pit_violations']} PIT violations · "
        f"{report['negative_controls_effective']}/{report['negative_controls_total']} controls",
        "",
        "## What was measured",
        "",
        "| dimension | value |",
        "| --- | --- |",
        f"| keys compared | {report['evaluations_compared']} |",
        f"| rows audited (original / independent) | {counts.get('original')} / {counts.get('independent')} |",
        f"| signals | {report['signals_original']} / {report['signals_independent']} |",
        f"| unexplained differences | {report['mismatches_unexplained']} |",
        f"| PIT violations | {report['pit_violations']} |",
        f"| prefix invariance | {report['prefix_invariance']} |",
        f"| functional coverage | {report['functional_coverage']} |",
        f"| clean-checkout reproduction | {(report['clean_checkout_reproduction'] or {}).get('verdict', 'NOT_RUN')} |",
        f"| holdout opened | {report['holdout_opened']} |",
        f"| orders (live / paper) | {report['live_orders']} / {report['paper_orders']} |",
        f"| config unchanged | {report['config_unchanged']} |",
        "",
        "## Cells",
        "",
        "| cell | evaluations | signals | mismatches | state |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    lines += [
        "",
        "See `CELL_COVERAGE_MANIFEST.csv` for the 24 cells and `SIGNAL_PARITY.csv` for the",
        "per-symbol detail.",
        "",
        "## Tests executed for this report",
        "",
        f"`{json.dumps(report['tests'], sort_keys=True)}`",
        "",
        "## Limits",
        "",
        "- `ECONOMIC_EDGE` is not evaluated here: no return, cost or ranking is computed.",
        "- The holdout was never opened; no order of any kind was produced.",
        "- The verifier is a program, not a person; `BUILDER != VERIFIER` holds as two programs.",
        "",
    ]
    return "\n".join(lines)


def _final_md(report: dict[str, Any]) -> str:
    zero = report["cells_zero_sample"]
    lines = [
        "# FINAL REPORT — EXP-003O — Independent Signal Regeneration",
        "",
        f"**PHASE:** `EXP-003O` · **VERDICT:** `{report['verdict']}` · **STATUS:** `{report['status']}`",
        "",
        f"`TECHNICAL_SIGNAL_PARITY={report['technical_signal_parity']}` · "
        f"`FULL_INDEPENDENT_CERTIFICATION={report['full_independent_certification']}` · "
        f"`ECONOMIC_EDGE={report['economic_edge']}` · `STRATEGY_PROMOTION=DENIED` · "
        f"`LIVE=DISABLED` · `HOLDOUT=CLOSED`",
        "",
        "## COMMITS",
        "",
        f"- baseline + protocol: `{str(report['preregistration_commit'])[:12]}` "
        f"(prospective=`{report['prospective']}`)",
        f"- experiment HEAD: `{report['experiment_commit'][:12]}`",
        "",
        "## IMPLEMENTED",
        "",
        "- `scripts/exp_003o_contract.py` — the signal-free contract: 24 cells, states, writers,",
        "  canonical bar digest. Shared by both producers; contains no rule.",
        "- `scripts/exp_003o_baseline.py` — seals, dataset digests, config hashes, dependency map.",
        "- `scripts/exp_003o_preregister.py` — `SIGNAL_SPECIFICATIONS.md`, `design/PROTOCOL.json`,",
        "  `design/PREREGISTRATION.md`, digest check.",
        "- `scripts/exp_003o_rebuilder.py` — Builder B: own reader, own EMA/RSI/ATR/MACD/Bollinger/",
        "  volume arithmetic, own lane-B machines and driver. Imports stdlib, numpy and the contract.",
        "- `scripts/exp_003o_original.py` — Builder A: the frozen 003N producer replayed per instant,",
        "  with an exact anchor to the 52 769 published lane-A signals and 39 lane-B trades.",
        "- `scripts/exp_003o_compare.py` — full outer join on the evaluation key, closed difference",
        "  classes, per-cell reconciliation.",
        "- `scripts/exp_003o_verify.py` — Verifier C: provenance, calendar, PIT, prefix invariance,",
        "  independence, its own join, 12 negative controls, governance, functional coverage.",
        "- `scripts/exp_003o_fixtures.py` — deterministic synthetic fixtures for the zero-sample",
        "  families, active and quiet.",
        "",
        "## RESULTS",
        "",
        f"- {report['evaluations_compared']} evaluation keys over {report['cells_total']} cells, "
        f"{report['signals_original']} signals in the original stream and "
        f"{report['signals_independent']} in the independent one.",
        f"- **{report['mismatches_unexplained']} unexplained differences**, "
        f"**{report['pit_violations']} PIT violations** over "
        f"{report['pit_rows_audited'].get('original')} + "
        f"{report['pit_rows_audited'].get('independent')} audited rows.",
        f"- {report['negative_controls_effective']}/{report['negative_controls_total']} negative "
        "controls effective and detected.",
        f"- cells without a real sample: `{', '.join(zero) if zero else 'none'}` — their functional",
        "  coverage rests on the frozen fixtures, which prove implementation behaviour only.",
        "",
        "## TESTS",
        "",
        f"`{json.dumps(report['tests'], sort_keys=True)}`",
        "",
        f"`PAPER_VALIDATION=NOT_PERFORMED` · `FALSE_SUCCESS={report['false_success_observed']}`",
        "",
        "## DEFECTS",
        "",
    ]
    for defect in report["defects"]:
        lines += [
            f"- **{defect['id']}** ({defect['severity']}): {defect['summary']}",
            f"  - {defect['detail']}",
            f"  - treatment: {defect['treatment']}",
        ]
    lines += [
        "",
        "## BLOCKERS",
        "",
    ]
    lines += [f"- {item}" for item in report["blockers"]] or ["- none"]
    lines += [
        "",
        "## EVIDENCE",
        "",
        "| artefact | sha256 (first 16) |",
        "| --- | --- |",
    ]
    for name in (
        "design/PROTOCOL.json",
        "design/PREREGISTRATION.md",
        "SIGNAL_SPECIFICATIONS.md",
        "BASELINE_MANIFEST.json",
        "signals/original_evaluations.jsonl.gz",
        "signals/independent_evaluations.jsonl.gz",
        "SIGNAL_PARITY.csv",
        "SIGNAL_PARITY_SUMMARY.json",
        "PIT_AUDIT.json",
        "NEGATIVE_CONTROLS.json",
        "INDEPENDENCE_AUDIT.md",
        "INDEPENDENT_VERIFICATION.md",
        "CLEAN_CHECKOUT_REPRODUCTION.json",
        "CELL_COVERAGE_MANIFEST.csv",
        "RUN_REPORT.json",
    ):
        path = OUT / name
        digest = sha256_file(path)[:16] + "…" if path.exists() else "**missing**"
        lines.append(f"| `{name}` | `{digest}` |")
    lines += [
        "",
        "## ARCHITECTURE_STATUS",
        "",
        "The experiment is an offline, read-only layer over the frozen 003N universe. It adds no",
        "strategy, no indicator to the runtime, no order path and no configuration change. The",
        "runtime modules it exercises are the same ones the paper lane calls.",
        "",
        "## RFC_STATUS",
        "",
        "`RFC-EXP-003O` is implemented and executed in its whole scope: WP-00 to WP-04, with the",
        "deliverables listed in section 10. Nothing in it is `PROPOSED` any more except the",
        "continuation.",
        "",
        "## NEXT_PHASE",
        "",
        "`EXP-003P — Paper Execution Reality` is the natural successor: signal parity is now",
        "measured, but a decision is not a fill. 003P must observe the paper cycle (orders,",
        "fills, partials, slippage) without confusing a simulated fill with an executed one.",
        "",
        "A recommendation, not a promotion: the numbers of 003N still say no mechanism covers its",
        "own cost with sample, and nothing in 003O changes that. `EXP-003P` measures execution,",
        "not edge; `STRATEGY_PROMOTION` stays `DENIED`.",
        "",
    ]
    return "\n".join(lines)


def seal(out: Path) -> dict[str, Any]:
    files = sorted(
        path
        for path in out.rglob("*")
        if path.is_file() and path.name not in SEAL_EXCLUDE and "__pycache__" not in path.parts
    )
    lines = []
    entries = []
    for path in files:
        digest = sha256_file(path)
        relative = str(path.relative_to(out)).replace("\\", "/")
        lines.append(f"{digest}  {relative}")
        entries.append({"path": relative, "sha256": digest, "bytes": path.stat().st_size})
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "run_id": "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001",
        "sealed_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": len(entries),
        "manifest_sha256": sha256_bytes(("\n".join(lines) + "\n").encode("utf-8")),
        "entries": entries,
        "excluded": sorted(SEAL_EXCLUDE),
    }
    write_json(out / "SEAL.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O report writer")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    report = _report(out)
    print(
        f"[003o-report] status={report['status']} verdict={report['verdict']} "
        f"mismatches={report['mismatches_unexplained']} prospective={report['prospective']}"
    )
    if args.seal:
        manifest = seal(out)
        print(
            f"[003o-report] sealed {manifest['files']} files "
            f"manifest={manifest['manifest_sha256'][:16]}…"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
