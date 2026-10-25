#!/usr/bin/env python3
"""Read-only, fail-closed preflight for WP-ECONOMIC-RECOVERY-005.

It records what a checkout *has*: HEAD, Git status, SHA-256 of the governance
inputs and of the family modules, presence and shape of datasets, and presence
and shape of multi-family results. It runs no backtest, fetches nothing, edits
no ledger and changes no admission or PAPER permission.

Two things it deliberately refuses to do:

* report PASS. Provenance, point-in-time discipline, actual execution, cost
  parity and economic admission are outside the evidential authority of a
  presence/shape scan, so the strongest result it can print is
  ``REQUIRES_RUNTIME_EXECUTION_AND_INDEPENDENT_VERIFICATION``.
* accept a result file as evidence of execution. ``scripts/multi_family_backtest.py``
  writes ``MULTI_FAMILY_RESULTS*.json`` even when its dataset glob matched
  nothing, so an all-zero aggregate is a *finding* (``ZERO_TRADE_RESULT``), not
  a result. Presence is never treated as execution.

Artifact convention (read from the entrypoint, not assumed): a full run writes a
single aggregate ``MULTI_FAMILY_RESULTS.json`` keyed by family; a run scoped with
``FAM=<family>`` writes ``MULTI_FAMILY_RESULTS_<family>.json`` per family. Both
are accepted, but the six families must all be covered by real (non-zero-trade)
content either way.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

FAMILIES = ("ema_crossover", "momentum", "breakout", "trend", "mean_reversion", "volatility")
LEDGER = "config/strategy_admission.json"
COST = "data/recovery/COST_BARRIER_EXPLORER.json"
AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
ENTRY = "scripts/multi_family_backtest.py"
FAMILY_DIR = "src/trading_bot/research/families"
FAMILY_MODULE = FAMILY_DIR + "/{family}_family.py"
DATA_DIR = "reports/strategy-baseline/data"
# WP-006 moved the canonical bars to a manifest; when it exists it is the truth and
# the legacy directory is only a fallback, otherwise the preflight would report
# NO_DATASETS while a validated dataset sits in the repository.
MANIFEST = "data/economic/w006/MANIFEST.json"
RESULT_DIR = "reports/strategy-baseline"
AGGREGATE = RESULT_DIR + "/MULTI_FAMILY_RESULTS.json"
RESULT_PREFIX = "MULTI_FAMILY_RESULTS_"
SCENARIOS = ("BASE", "2X_COST", "STRESSED_SLIPPAGE", "ZERO_COST")
# The entrypoint's own dev/val/oos split is inferred from dataset filename
# prefixes; anything else contributes to `totals` only. Recorded, not repaired.
WINDOW_PREFIXES = ("W1", "W2", "W3", "W4", "W5", "W6", "W7")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root: Path, *args: str) -> dict[str, Any]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20,
                           check=False)
        return {"returncode": p.returncode, "stdout": p.stdout.strip(),
                "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:  # git may be absent
        return {"returncode": None, "stdout": "", "stderr": str(e)}


def file_detail(root: Path, relative: str) -> dict[str, Any]:
    p = root / relative
    if not p.is_file():
        return {"path": relative, "status": "ABSENT", "sha256": None}
    return {"path": relative, "status": "PRESENT", "sha256": sha256(p),
            "bytes": p.stat().st_size}


def json_detail(root: Path, relative: str) -> dict[str, Any]:
    d = file_detail(root, relative)
    if d["status"] != "PRESENT":
        return d
    try:
        obj = json.loads((root / relative).read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as e:
        d.update({"json": "INVALID", "error": str(e)})
        return d
    d["json"] = "VALID"
    if relative == LEDGER:
        strategies = obj.get("strategies") if isinstance(obj, dict) else None
        d["strategy_count"] = len(strategies) if isinstance(strategies, dict) else None
        d["admitted_for_paper"] = (sum(1 for x in strategies.values()
                                       if isinstance(x, dict) and x.get("admitted_for_paper") is True)
                                   if isinstance(strategies, dict) else None)
        d["schema_version"] = obj.get("_schema_version") if isinstance(obj, dict) else None
    return d


def check_dataset(path: Path) -> dict[str, Any]:
    """Basic OHLCV shape only. It cannot establish provenance, coverage or PIT."""
    d: dict[str, Any] = {"path": path.name, "status": "PRESENT", "sha256": sha256(path),
                         "bytes": path.stat().st_size}
    try:
        bars = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(bars, list) or not bars:
            raise ValueError("dataset must contain a nonempty list of bars")
        prev: int | None = None
        for i, b in enumerate(bars):
            if not isinstance(b, dict) or not all(
                    k in b for k in ("ts", "open", "high", "low", "close", "volume")):
                raise ValueError(f"bar[{i}] missing OHLCV field")
            ts = b["ts"]
            if not isinstance(ts, int) or (prev is not None and ts <= prev):
                raise ValueError(f"bar[{i}] timestamp not strictly ascending UTC milliseconds")
            prev = ts
            op, hi, lo, cl, volume = (float(b[k]) for k in ("open", "high", "low", "close", "volume"))
            if not all(math.isfinite(v) for v in (op, hi, lo, cl, volume)):
                raise ValueError(f"bar[{i}] non-finite numeric value")
            if not (lo > 0 and lo <= op <= hi and lo <= cl <= hi and volume >= 0):
                raise ValueError(f"bar[{i}] inconsistent OHLCV")
        d.update({"validation": "BASIC_SCHEMA_PASS", "bars": len(bars),
                  "start_ts_ms": bars[0]["ts"], "end_ts_ms": bars[-1]["ts"],
                  "window_prefix_recognised": any(path.stem.startswith(w) for w in WINDOW_PREFIXES)})
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError) as e:
        d.update({"validation": "INVALID", "error": str(e)})
    return d


def _trade_counts(payload: Any) -> dict[str, int]:
    """Per-family trade counts from any published artifact shape. Missing => 0.

    The engine publishes ``{... "results": {family: {scenario: {totals: {...}}}}}``
    since WP-006; older aggregates were keyed by family at the top level. Reading the
    envelope as if it were a family would report six nonexistent families, which is a
    false blocker and just as bad as a false pass.
    """
    out: dict[str, int] = {}
    if isinstance(payload, dict):
        nested = payload.get("results")
        body = nested if isinstance(nested, dict) else payload
        for fam, scenarios in body.items():
            total = 0
            if isinstance(scenarios, dict):
                for block in scenarios.values():
                    if isinstance(block, dict):
                        totals = block.get("totals")
                        if isinstance(totals, dict) and isinstance(totals.get("trades"), int):
                            total += totals["trades"]
            out[str(fam)] = total
    return out


def read_result(path: Path, root: Path) -> dict[str, Any]:
    d: dict[str, Any] = {"path": str(path.relative_to(root)).replace(os.sep, "/"),
                         "status": "PRESENT", "sha256": sha256(path),
                         "bytes": path.stat().st_size}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as e:
        d.update({"json": "INVALID", "error": str(e)})
        return d
    d["json"] = "VALID"
    counts = _trade_counts(payload)
    d["families"] = sorted(counts)
    d["trades_by_family"] = counts
    d["zero_trade_families"] = sorted(f for f, n in counts.items() if n <= 0)
    d["empty"] = not bool(payload)
    return d


def result_artifacts(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Locate result artifacts anywhere in the tree, and the canonical ones."""
    found: list[Path] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for name in files:
            if name.startswith("MULTI_FAMILY_RESULTS") and name.endswith(".json"):
                found.append(Path(base) / name)
    artifacts = [read_result(p, root) for p in sorted(found)]
    covered: set[str] = set()
    zero: set[str] = set()
    for a in artifacts:
        for fam in a.get("families", []):
            covered.add(fam)
            if a["trades_by_family"].get(fam, 0) <= 0:
                zero.add(fam)
    return artifacts, {
        "aggregate_present": (root / AGGREGATE).is_file(),
        "families_covered": sorted(f for f in covered if f in FAMILIES),
        "families_missing": sorted(f for f in FAMILIES if f not in covered),
        "families_with_zero_trades": sorted(f for f in zero if f in FAMILIES),
    }


def build_observation(root: Path, with_git: bool = True) -> dict[str, Any]:
    """Pure function of the tree: no writes, no clock, no subprocess if with_git=False."""
    head = git(root, "rev-parse", "HEAD") if with_git else {"returncode": None, "stdout": ""}
    branch = git(root, "branch", "--show-current") if with_git else {"returncode": None, "stdout": ""}
    status = (git(root, "status", "--porcelain=v2", "--branch", "--untracked-files=all")
              if with_git else {"returncode": None, "stdout": ""})

    files = {rel: (json_detail(root, rel) if rel.endswith(".json") else file_detail(root, rel))
             for rel in (LEDGER, COST, AUDIT, ENTRY)}
    for fam in FAMILIES:
        rel = FAMILY_MODULE.format(family=fam)
        files[rel] = file_detail(root, rel)

    manifest_path = root / MANIFEST
    datasets: list[dict[str, Any]] = []
    datasets_source = DATA_DIR
    if manifest_path.is_file():
        datasets_source = MANIFEST
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8")).get("datasets") or {}
        except (ValueError, UnicodeError, OSError):
            entries = {}
        for symbol, entry in sorted(entries.items()):
            path = manifest_path.parent / entry["path"]
            detail = check_dataset(path) if path.is_file() else {
                "path": entry["path"], "status": "ABSENT", "validation": "INVALID"}
            detail["symbol"] = symbol
            digest_ok = path.is_file() and sha256(path) == entry.get("sha256")
            detail["manifest_digest_match"] = digest_ok
            if not digest_ok:
                detail["validation"] = "INVALID"
                detail["error"] = "digest does not match the manifest"
            datasets.append(detail)
    else:
        data_dir = root / DATA_DIR
        datasets = [check_dataset(p) for p in sorted(data_dir.glob("*.json"))] if data_dir.is_dir() else []
    artifacts, coverage = result_artifacts(root)

    blockers: list[str] = []
    if with_git and (head["returncode"] != 0 or status["returncode"] != 0):
        blockers.append("NO_VERIFIABLE_GIT_WORKTREE")
    if files[ENTRY]["status"] != "PRESENT":
        blockers.append("ENTRYPOINT_MISSING")
    missing_modules = [f for f in FAMILIES if files[FAMILY_MODULE.format(family=f)]["status"] != "PRESENT"]
    if missing_modules:
        blockers.append("FAMILY_MODULE_MISSING:" + ",".join(missing_modules))
    if not datasets:
        blockers.append("NO_DATASETS_IN_CANONICAL_INPUT_PATH")
    if datasets_source == MANIFEST and not manifest_path.is_file():
        blockers.append("MANIFEST_MISSING")
    if any(d.get("validation") != "BASIC_SCHEMA_PASS" for d in datasets):
        blockers.append("INVALID_DATASET_SCHEMA")
    if not artifacts:
        blockers.append("NO_MULTI_FAMILY_RESULTS")
    else:
        if any(a.get("json") != "VALID" for a in artifacts):
            blockers.append("INVALID_RESULT_JSON")
        if coverage["families_missing"]:
            blockers.append("RESULT_FAMILY_COVERAGE_INCOMPLETE:" + ",".join(coverage["families_missing"]))
        if coverage["families_with_zero_trades"]:
            blockers.append("ZERO_TRADE_RESULT:" + ",".join(coverage["families_with_zero_trades"]))
    for rel in (LEDGER, COST):
        if files[rel]["status"] != "PRESENT":
            blockers.append("GOVERNANCE_INPUT_MISSING:" + rel)
        elif files[rel].get("json") == "INVALID":
            blockers.append("GOVERNANCE_INPUT_INVALID:" + rel)

    return {
        "schema": "WP005_PREFLIGHT_V1",
        "mode": "READ_ONLY_OFFLINE",
        "repo": str(root),
        "git": {"head": head, "branch": branch, "status": status},
        "inputs": files,
        "entrypoint_contract": {
            "aggregate_output": AGGREGATE,
            "per_family_output": RESULT_DIR + "/" + RESULT_PREFIX + "<family>.json",
            "scenarios": list(SCENARIOS),
            "note": "the entrypoint writes its JSON even when no dataset matched; "
                    "presence is not execution",
        },
        "datasets_source": datasets_source,
        "datasets": datasets,
        "multi_family_results": artifacts,
        "result_coverage": coverage,
        "blockers": sorted(set(blockers)),
        "economic_execution": "NOT_RUN",
        "independent_economic_verification": "NOT_RUN",
        "economic_result": "INCONCLUSIVE",
        "paper": "NOT_AUTHORIZED",
        "false_success_observed": 0,
        "false_success_global_certification": "NOT_ASSESSED",
        "warning": "File presence and basic OHLCV shape cannot establish historical provenance, "
                   "point-in-time discipline, actual backtest execution, cost parity or economic "
                   "admission.",
    }


def render_markdown(observation: dict[str, Any]) -> str:
    status = "BLOCKED" if observation["blockers"] else "REQUIRES_RUNTIME_EXECUTION_AND_INDEPENDENT_VERIFICATION"
    head = observation["git"]["head"]
    head_line = head["stdout"] if head.get("returncode") == 0 and head.get("stdout") else "UNAVAILABLE"
    blocked = observation["blockers"]
    lines = [
        "# WP-005 — Preflight observation",
        "",
        f"- Estado: `{status}`",
        f"- HEAD observado: `{head_line}`",
        f"- Rama: `{observation['git']['branch'].get('stdout') or 'UNAVAILABLE'}`",
        f"- Datasets validados desde `{observation['datasets_source']}`: {len(observation['datasets'])}",
        f"- Artefactos `MULTI_FAMILY_RESULTS*.json`: {len(observation['multi_family_results'])}",
        f"- Familias cubiertas por algún artefacto de resultados: "
        f"{len(observation['result_coverage']['families_covered'])}/{len(FAMILIES)}",
        "- Experimentos económicos ejecutados por este programa: **0**",
        "- PAPER: `NOT_AUTHORIZED`",
        "",
        "## Bloqueos",
        "",
    ]
    lines.extend([f"- `{b}`" for b in blocked])
    if not blocked:
        lines.append("- Sin bloqueos de presencia detectados; aún faltan ejecución y verificación "
                     "independiente.")
    lines += [
        "",
        "## Qué no demuestra este informe",
        "",
        "Un fichero de resultados presente no demuestra ejecución (el entrypoint escribe su JSON "
        "aunque el glob de datasets no case con nada). Un dataset con esquema OHLCV válido no "
        "demuestra procedencia, cobertura, huecos ni PIT. Un resultado con operaciones no demuestra "
        "paridad de costes ni admisión económica.",
        "",
        "## Referencia",
        "",
        "Ver `WP005_PREFLIGHT_OBSERVATION.json` para SHA-256, estado Git y validación de cada archivo.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", type=Path, required=True, help="Checkout/worktree to observe (read-only)")
    p.add_argument("--out", type=Path, required=True,
                   help="Directory outside the repo for the observation artifacts")
    args = p.parse_args(argv)
    root = args.repo.resolve()
    out = args.out.resolve()
    # An external output keeps the baseline tree exactly as observed; a report
    # written inside the repo would change the status it is reporting on.
    if root == out or root in out.parents:
        print("ERROR: --out must be outside --repo (the observation must not change the tree "
              "it observes)", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"ERROR: --repo is not a directory: {root}", file=sys.stderr)
        return 2

    observation = build_observation(root, with_git=True)
    observation["observed_at_utc"] = datetime.now(timezone.utc).isoformat()

    out.mkdir(parents=True, exist_ok=True)
    (out / "WP005_PREFLIGHT_OBSERVATION.json").write_text(
        json.dumps(observation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (out / "WP005_PREFLIGHT_OBSERVATION.md").write_text(
        render_markdown(observation) + "\n", encoding="utf-8", newline="\n")

    status = "BLOCKED" if observation["blockers"] else "REQUIRES_RUNTIME_EXECUTION_AND_INDEPENDENT_VERIFICATION"
    print(f"{status} | HEAD={observation['git']['head'].get('stdout') or 'UNAVAILABLE'} | "
          f"datasets={len(observation['datasets'])} | "
          f"results={len(observation['multi_family_results'])} | "
          f"blockers={len(observation['blockers'])}")
    return 2 if observation["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
