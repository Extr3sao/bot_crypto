"""exp_003o_baseline — WP-003O-00: what the repository actually contains, by hash.

Nothing here runs a strategy. The phase answers one question per line — is this input the
one the protocol will name? — and writes the answer with the hash it checked. A mismatch is
recorded as ``BLOCKED`` in ``BASELINE_MANIFEST.json``; it is never rounded up to "probably
fine", and the comparison phases refuse to start on a blocked baseline.

Outputs
-------
``BASELINE_MANIFEST.json``      inputs, digests, governance flags, governance hashes.
``SOURCE_DEPENDENCY_MAP.md``    the import graph of the *original* producer, read from code.
``CELL_COVERAGE_MANIFEST.csv``  the 24 cells with expected evaluation counts and ``NOT_RUN``.

Usage
-----
``python scripts/exp_003o_baseline.py [--out DIR] [--json]``
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    HOLDOUT,
    LANE_A_WINDOW,
    OUT,
    PARTITIONS,
    REPO,
    SOURCE_003N,
    TIMEFRAME_MS,
    cell_inventory,
    sha256_file,
    utc_ms,
    write_json,
)

ROOT = REPO

DATASET = ROOT / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"

#: The modules that make up the frozen 003N signal producer. The map is derived from these
#: files' real imports; the list is the seed, not the answer.
PRODUCER_MODULES = (
    "scripts/exp_003n_screen.py",
    "src/trading_bot/vision/signal_sources.py",
    "src/trading_bot/research/families/ema_crossover_family.py",
    "src/trading_bot/research/families/momentum_family.py",
    "src/trading_bot/research/families/breakout_family.py",
    "src/trading_bot/research/families/mean_reversion_family.py",
    "src/trading_bot/research/families/trend_family.py",
    "src/trading_bot/research/families/volatility_family.py",
    "src/trading_bot/indicators/builtin.py",
    "src/trading_bot/research/economic_recovery/pit15.py",
    "src/trading_bot/research/economic_recovery/alpha15.py",
    "src/trading_bot/research/economic_recovery/experiments.py",
)

CONFIG_FILES = ("config/runtime.yaml", "config/risk.yaml", "config/vision.yaml")


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _imports(path: Path) -> list[str]:
    """Internal imports of one module, as written (relative imports resolved to a prefix)."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * int(node.level or 0)
            module = f"{prefix}{node.module or ''}".strip()
            names.append(module)
    return sorted({name for name in names if name})


def _seal_report() -> dict[str, Any]:
    sums = SOURCE_003N / "SHA256SUMS.txt"
    if not sums.exists():
        return {"state": "MISSING", "checked": 0, "failed": ["SHA256SUMS.txt"]}
    failed: list[str] = []
    checked = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        target = SOURCE_003N / name.strip()
        checked += 1
        if not target.exists() or sha256_file(target) != digest:
            failed.append(name.strip())
    return {"state": "OK" if not failed else "FAIL", "checked": checked, "failed": failed}


def _dataset_report(design: dict[str, Any]) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    ok = True
    for symbol, entry in sorted(design["dataset"]["symbols"].items()):
        path = DATASET / entry["file"]
        exists = path.exists()
        digest = sha256_file(path) if exists else None
        matched = digest == entry["sha256"] and exists and path.stat().st_size == entry["bytes"]
        ok = ok and matched
        entries[symbol] = {
            "file": entry["file"],
            "sha256_expected": entry["sha256"],
            "sha256_observed": digest,
            "bytes_expected": entry["bytes"],
            "bytes_observed": path.stat().st_size if exists else None,
            "matches": matched,
        }
    manifest = DATASET / "DATASET_MANIFEST.json"
    manifest_digest = sha256_file(manifest) if manifest.exists() else None
    return {
        "state": "OK" if ok else "FAIL",
        "manifest_sha256_expected": design["dataset"]["manifest_sha256"],
        "manifest_sha256_observed": manifest_digest,
        "manifest_matches": manifest_digest == design["dataset"]["manifest_sha256"],
        "symbols": entries,
    }


def _bars_per_timeframe() -> dict[str, dict[str, Any]]:
    """Bar counts and evaluation counts, derived from the minutes and the frozen windows."""

    counts: dict[str, dict[str, Any]] = {}
    holdout_ms = utc_ms(HOLDOUT[0])
    for name, interval in TIMEFRAME_MS.items():
        per = interval // 60_000
        # the research window ends where the holdout begins; complete groups only
        usable_minutes = (holdout_ms - utc_ms("2026-06-21T00:00:00Z")) // 60_000
        bars = usable_minutes // per
        counts[name] = {
            "interval_ms": interval,
            "minutes_per_bar": per,
            "research_minutes": usable_minutes,
            "bars": bars,
            "lane_a_evaluations": max(0, bars - (LANE_A_WINDOW - 1)),
        }
    return counts


def _cell_rows(bars: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in cell_inventory():
        per_cell = bars[cell["timeframe"]]
        #: ``warmup_bars`` counts the leading bars that are NOT_READY, so the evaluable
        #: window is everything from that index to the end of the series.
        expected = max(0, int(per_cell["bars"]) - int(cell["warmup_bars"])) * 3
        rows.append(
            {
                "cell_id": cell["cell_id"],
                "lane": cell["lane"],
                "family": cell["family"],
                "timeframe": cell["timeframe"],
                "symbols": 3,
                "warmup_bars": cell["warmup_bars"],
                "bars_per_symbol": per_cell["bars"],
                "expected_evaluations": expected,
                "observed_evaluations": None,
                "observed_signals": None,
                "state": "NOT_RUN",
                "parameter_hash": "",
            }
        )
    return rows


def _dependency_map() -> str:
    lines = [
        "# SOURCE DEPENDENCY MAP — EXP-003O",
        "",
        "Generated from the files' own AST, not from prose. Every row is what `ast.parse`",
        "found in the file named in the first column. A module that does not exist yet is",
        "listed as absent rather than guessed.",
        "",
        "## Producer chain (EXP-003N, frozen, read-only)",
        "",
        "| module | imports (as written) |",
        "| --- | --- |",
    ]
    for relative in PRODUCER_MODULES:
        path = ROOT / relative
        if not path.exists():
            lines.append(f"| `{relative}` | **absent from this checkout** |")
            continue
        imports = _imports(path)
        lines.append(f"| `{relative}` | {', '.join(f'`{name}`' for name in imports) or '(none)'} |")
    lines += [
        "",
        "## Independent rebuilder (EXP-003O)",
        "",
        "| module | imports (as written) |",
        "| --- | --- |",
    ]
    rebuilder = ROOT / "scripts" / "exp_003o_rebuilder.py"
    if rebuilder.exists():
        lines.append(
            f"| `scripts/exp_003o_rebuilder.py` | "
            f"{', '.join(f'`{name}`' for name in _imports(rebuilder))} |"
        )
    else:
        lines.append("| `scripts/exp_003o_rebuilder.py` | **not written yet at baseline time** |")
    lines.append("")
    return "\n".join(lines)


def build(out: Path) -> dict[str, Any]:
    design = json.loads((SOURCE_003N / "design" / "DESIGN.json").read_text(encoding="utf-8"))
    seal = _seal_report()
    dataset = _dataset_report(design)
    bars = _bars_per_timeframe()
    #: DESIGN names the files by basename; the checkout stores them under ``config/``.
    config = {
        name: {"sha256": sha256_file(ROOT / name) if (ROOT / name).exists() else None}
        for name in CONFIG_FILES
    }
    expected_config = design["invariants"]["config_sha256"]
    observed_by_basename = {Path(name).name: entry["sha256"] for name, entry in config.items()}
    config_ok = all(
        observed_by_basename.get(Path(name).name) == digest
        for name, digest in expected_config.items()
    )

    dirty = _git("status", "--porcelain").splitlines()
    manifest: dict[str, Any] = {
        "run_id": "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001",
        "schema_version": "AI_BOTS_003O_BASELINE_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_paths": len(dirty),
            "reported_003n_commits": {
                "design": design.get("commit"),
                "sealed_checkout": "6b0dac1",
            },
        },
        "source_003n": {
            "path": str(SOURCE_003N.relative_to(ROOT)).replace("\\", "/"),
            "read_only": True,
            "seal": seal,
            "design_sha256": sha256_file(SOURCE_003N / "design" / "DESIGN.json"),
            "screening_sha256": sha256_file(SOURCE_003N / "analysis" / "SCREENING.json"),
            "signals_sha256": sha256_file(SOURCE_003N / "analysis" / "SIGNALS.jsonl.gz"),
            "holdout_status": design["holdout"]["status"],
        },
        "dataset": dataset,
        "config": {"files": config, "matches_design_invariants": config_ok},
        "windows": {
            "holdout": {"start_utc": HOLDOUT[0], "end_utc": HOLDOUT[1], "opened": False},
            "partitions": {name: list(window) for name, window in PARTITIONS.items()},
            "bars": bars,
        },
        "cells": _cell_rows(bars),
        "governance": {
            "live_trading": "DISABLED",
            "orders_authorised": 0,
            "paper_promotion": "NOT_AUTHORIZED",
            "economic_edge": "NOT_EVALUATED",
        },
    }
    state = "OK"
    reasons: list[str] = []
    if seal["state"] != "OK":
        state = "BLOCKED"
        reasons.append(f"003N seal {seal['state']}: {seal['failed'][:3]}")
    if dataset["state"] != "OK":
        state = "BLOCKED"
        reasons.append("dataset digest mismatch")
    if not config_ok:
        state = "BLOCKED"
        reasons.append("config digests differ from DESIGN invariants")
    manifest["state"] = state
    manifest["blockers"] = reasons

    write_json(out / "BASELINE_MANIFEST.json", manifest)
    (out / "SOURCE_DEPENDENCY_MAP.md").write_text(_dependency_map(), encoding="utf-8", newline="\n")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(_cell_rows(bars)[0].keys()), lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(_cell_rows(bars))
    (out / "CELL_COVERAGE_MANIFEST.csv").write_text(
        buffer.getvalue(), encoding="utf-8", newline="\n"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O WP-00 baseline audit")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--json", action="store_true", help="print the manifest to stdout")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = build(out)
    seal = manifest["source_003n"]["seal"]
    print(
        f"[003o-baseline] state={manifest['state']} seal={seal['state']} "
        f"({seal['checked']} files) dataset={manifest['dataset']['state']} "
        f"config={manifest['config']['matches_design_invariants']} "
        f"cells={len(manifest['cells'])}"
    )
    for reason in manifest["blockers"]:
        print(f"[003o-baseline] BLOCKER — {reason}", file=sys.stderr)
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["state"] == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
