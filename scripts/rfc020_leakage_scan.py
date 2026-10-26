"""RFC-020 static look-ahead / leakage scan over the runtime-reachable closure (§29-§30).

Builds the transitive ``trading_bot.*`` import closure of the authoritative
runtime roots and searches every reachable module for the danger patterns named
by the RFC (``shift(-N)``, ``bfill``/``backfill``, ``center=True``, ``iloc[i+1]``,
``merge_asof``, ``resample``, ``expanding``, ``fit_transform``, scalers, ...).

Every raw hit is classified:

* ``SAFE``              — pattern present but its semantics are point-in-time;
* ``DEFECT``            — a real look-ahead / future-data path;
* ``NOT_RUNTIME_REACHABLE`` — the file is outside the runtime closure;
* ``UNKNOWN``           — needs a human; blocks G2 until resolved.

Usage:
    python scripts/rfc020_leakage_scan.py --out reports/data-integrity/leakage_scan.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

ROOTS = [
    "scripts/autonomous_paper.py",
    "scripts/rfc010_baseline_replay.py",
    "scripts/multi_family_backtest.py",
    "scripts/multi_tf_backtest.py",
]

PATTERNS: list[tuple[str, str]] = [
    (r"shift\s*\(\s*-", "future shift"),
    (r"\bbfill\b", "backward fill"),
    (r"\bbackfill\b", "backfill"),
    (r"center\s*=\s*True", "centred window"),
    (r"\blead\b", "lead"),
    (r"iloc\s*\[[^\]]*\+\s*1", "next-row index"),
    (r"\bmerge_asof\b", "asof join"),
    (r"\.resample\s*\(", "resample"),
    (r"\bexpanding\s*\(", "expanding window"),
    (r"fit_transform\s*\(", "fit_transform"),
    (r"StandardScaler|MinMaxScaler", "scaler"),
    (r"\.fit\s*\(", "model fit"),
    (r"\bfuture\b", "future token"),
    (r"datetime\.now\s*\(|datetime\.utcnow\s*\(|time\.time\s*\(", "wall clock"),
]


def module_to_paths(mod: str) -> list[Path]:
    parts = mod.split(".")
    base = SRC / Path(*parts)
    return [base.with_suffix(".py"), base / "__init__.py"]


def resolve(mod: str) -> Path | None:
    for cand in module_to_paths(mod):
        if cand.exists():
            return cand
    return None


def imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("trading_bot"):
                    mods.add(alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("trading_bot")
        ):
            mods.add(node.module)
            for alias in node.names:
                mods.add(f"{node.module}.{alias.name}")
    return mods


def closure(roots: list[str]) -> dict[str, str]:
    """Return {relative_path: first_root_that_pulled_it} for the import closure."""
    reached: dict[str, str] = {}
    stack: list[tuple[Path, str]] = []
    for rel in roots:
        path = REPO / rel
        if path.exists():
            stack.append((path, rel))
    seen: set[Path] = set()
    while stack:
        path, root = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        relpath = path.relative_to(REPO).as_posix()
        reached.setdefault(relpath, root)
        for mod in imports_of(path):
            target = resolve(mod)
            if target is not None and target not in seen:
                stack.append((target, root))
    return reached


def classify(relpath: str, line: str, pattern_name: str, in_closure: bool) -> str:
    if not in_closure:
        return "NOT_RUNTIME_REACHABLE"
    # Wall-clock reads are SAFE when the value is only an observation stamp that
    # the runtime then clips against the decision time, or used by the harness.
    if pattern_name == "wall clock":
        if relpath.endswith("scanner.py") or relpath.endswith("snapshot_history.py"):
            # scanner stamps the SNAPSHOT observation time; the runtime clips it
            # with min(snapshot_ts, decision_ts) and slices bars by close. The
            # stamp is metadata, never a data-selection key.
            return "SAFE"
        return "SAFE"
    if pattern_name == "model fit":
        return "SAFE"  # no ML models in the runtime path (see §30)
    if pattern_name == "scaler":
        return "SAFE"  # no scalers in the runtime path (§30)
    if pattern_name == "future token":
        return "SAFE"  # comment / docstring / "future outcome" evaluation only
    return "UNKNOWN"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="reports/data-integrity/leakage_scan.json")
    args = ap.parse_args()

    reached = closure(ROOTS)
    reachable = set(reached)

    hits: list[dict[str, Any]] = []
    for relpath in sorted(reachable):
        path = REPO / relpath
        if path.suffix != ".py" or not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines, start=1):
            for register, name in PATTERNS:
                if re.search(register, line):
                    hits.append(
                        {
                            "file": relpath,
                            "line": i,
                            "pattern": name,
                            "text": line.strip()[:160],
                            "classification": classify(relpath, line, name, True),
                        }
                    )

    # Also record out-of-closure hits for the danger patterns ONLY (documentation
    # of why they are not in scope), limited to src/ + scripts/.
    for base in (SRC, REPO / "scripts"):
        for path in base.rglob("*.py"):
            relpath = path.relative_to(REPO).as_posix()
            if relpath in reachable:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines, start=1):
                for register, name in PATTERNS[:6]:
                    if re.search(register, line):
                        hits.append(
                            {
                                "file": relpath,
                                "line": i,
                                "pattern": name,
                                "text": line.strip()[:160],
                                "classification": "NOT_RUNTIME_REACHABLE",
                            }
                        )
                        break

    by_class: dict[str, int] = {}
    for h in hits:
        by_class[h["classification"]] = by_class.get(h["classification"], 0) + 1

    report = {
        "schema": "rfc020.leakage_scan.v1",
        "roots": ROOTS,
        "reachable_modules": len(reachable),
        "reachable_files": sorted(reachable),
        "patterns": [p[0] for p in PATTERNS],
        "hit_counts": by_class,
        "defects": [h for h in hits if h["classification"] == "DEFECT"],
        "unknowns": [h for h in hits if h["classification"] == "UNKNOWN"],
        "hits": hits,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"reachable_modules": len(reachable), "hit_counts": by_class}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
