"""WP-PAPER-REAL-DATA-001 — what the PAPER entrypoint actually reaches.

The question this answers is narrow and falsifiable: *does the canonical PAPER
entrypoint, or anything it imports, need the missing 15m corpus?* A static
answer is worth having precisely because the runtime's behaviour (a successful
cycle) is not evidence about its dependencies.

Method — no guessing, three explicit steps:

1. **Import closure.** Starting at ``scripts/autonomous_paper.py``, follow every
   ``import`` / ``from ... import`` edge — including relative imports, which is
   where a module can hide a dependency on a sibling that reads the corpus.
   Modules outside ``src/`` + ``scripts/`` (stdlib, third-party) are recorded as
   external and not expanded.
2. **Corpus dependence.** For each reached module, look for the markers that
   mean "this file will fail when ``data/raw/alpha003/price`` is absent": a
   literal ``alpha003``, the ``CORPUS_15M`` constant, ``load_15m``, or an
   ``_15m.json`` filename. Marker presence is reported verbatim so the reader
   can judge it; the verdict adds whether the module *reads a file* at all.
3. **Strategy reachability.** The runtime can only consider the strategies the
   admission ledger holds for its timeframe (``entries_for_timeframe``), and can
   only order for one the ledger admits (``admitted_for_paper``). Both facts are
   read from the committed ledger, never assumed.

Output: ``PAPER_REACHABILITY.json`` beside the run artefacts.

Usage::

    uv run python scripts/wp_prd001_paper_reachability.py --out <evidence>/raw
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
SCRIPTS = REPO_ROOT / "scripts"

ENTRYPOINT = SCRIPTS / "autonomous_paper.py"
CORPUS_MARKERS = ("alpha003", "CORPUS_15M", "load_15m", "_15m.json")
FILE_READ_MARKERS = ("read_text", "open(", "json.load", "Path(")


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or datetime.now(tz=UTC).timestamp(), tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def module_path(module: str) -> Path | None:
    """Resolve a dotted module to a file inside this repo, or ``None``."""
    parts = module.split(".")
    for root in (SRC, SCRIPTS, REPO_ROOT):
        candidate = root.joinpath(*parts).with_suffix(".py")
        if candidate.is_file():
            return candidate
        package = root.joinpath(*parts, "__init__.py")
        if package.is_file():
            return package
    return None


def module_name_of(path: Path) -> str:
    """Inverse of ``module_path`` for a repo file."""
    for root in (SRC, SCRIPTS):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if relative.name == "__init__.py":
            return ".".join(relative.parent.parts)
        return ".".join(relative.with_suffix("").parts)
    return path.stem


def _resolve_import(node: ast.AST, current: str, is_package: bool) -> list[str]:
    """Dotted names a single import statement refers to (relative ones folded in)."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    base = node.module or ""
    if not node.level:
        return [base] if base else []
    package_parts = current.split(".") if is_package else current.split(".")[:-1]
    up = node.level - 1
    if up > len(package_parts):
        return []
    anchor = package_parts[: len(package_parts) - up]
    target = ".".join([*anchor, base]) if base else ".".join(anchor)
    names = [target] if target else []
    # ``from . import x`` may point at a submodule, not an attribute.
    for alias in node.names:
        candidate = f"{target}.{alias.name}" if target else alias.name
        names.append(candidate)
    return [name for name in names if name]


def import_closure(entry: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Reach every repo module the entrypoint can import."""
    reached: dict[str, dict[str, Any]] = {}
    external: set[str] = set()
    queue: list[tuple[str, Path]] = [(module_name_of(entry), entry)]
    while queue:
        name, path = queue.pop()
        if name in reached:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - repo files must parse
            raise SystemExit(f"cannot parse {path}: {exc}") from exc
        text = path.read_text(encoding="utf-8")
        is_package = path.name == "__init__.py"
        imports: set[str] = set()
        for node in ast.walk(tree):
            for target in _resolve_import(node, name, is_package):
                imports.add(target)
        children: list[str] = []
        for target in sorted(imports):
            resolved = module_path(target)
            if resolved is None:
                # Try the parent package for ``from pkg import name``.
                parent = module_path(target.rsplit(".", 1)[0]) if "." in target else None
                if parent is not None:
                    children.append(module_name_of(parent))
                    queue.append((module_name_of(parent), parent))
                else:
                    external.add(target.split(".")[0])
                continue
            children.append(module_name_of(resolved))
            queue.append((module_name_of(resolved), resolved))
        reached[name] = {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "imports": sorted(set(children)),
            "corpus_markers": [m for m in CORPUS_MARKERS if m in text],
            "reads_files": [m for m in FILE_READ_MARKERS if m in text],
        }
    return reached, sorted(external)


def corpus_consumers(closure: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Modules that mention the lost corpus, with the strongest marker they carry."""
    rows: list[dict[str, Any]] = []
    for name, info in sorted(closure.items()):
        if not info["corpus_markers"]:
            continue
        opens = bool(info["reads_files"])
        rows.append(
            {
                "module": name,
                "path": info["path"],
                "markers": info["corpus_markers"],
                "opens_files": opens,
                "verdict": (
                    "WOULD_FAIL_WITHOUT_CORPUS" if opens else "NAMES_CORPUS_ONLY"
                ),
            }
        )
    return rows


def strategy_reachability(ledger_path: Path, timeframes: tuple[str, ...]) -> dict[str, Any]:
    """What the ledger lets the runtime consider, per timeframe — read, not assumed."""
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = {k: v for k, v in ledger.get("strategies", {}).items() if not k.startswith("_")}
    by_timeframe: dict[str, list[dict[str, Any]]] = {}
    for timeframe in timeframes:
        rows = []
        for strategy_id, entry in sorted(entries.items()):
            if entry.get("timeframe") != timeframe:
                continue
            gross = entry.get("expected_gross_edge_bps")
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "family": entry.get("family"),
                    "status": entry.get("status"),
                    "admitted_for_paper": bool(entry.get("admitted_for_paper")),
                    "expected_gross_edge_bps": gross,
                    "reachable_in_runtime": True,  # entries_for_timeframe() lists it
                    "can_authorise_order": bool(entry.get("admitted_for_paper")),
                    "decision_if_selected": (
                        "TRADE_PAPER"
                        if entry.get("admitted_for_paper") and (gross or 0) > 0
                        else "NO_GROSS_EDGE"
                        if (gross or 0) <= 0
                        else "SHADOW_OR_NOT_ADMITTED"
                    ),
                }
            )
        by_timeframe[timeframe] = rows
    return {
        "ledger": ledger_path.relative_to(REPO_ROOT).as_posix(),
        "paper_candidates_all_timeframes": sorted(
            sid for sid, e in entries.items() if e.get("admitted_for_paper")
        ),
        "by_timeframe": by_timeframe,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO_ROOT / "docs/agentic/paper_reald/WP-PAPER-REAL-DATA-001/raw"))
    parser.add_argument("--timeframes", default="1h,5m")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    timeframes = tuple(t.strip() for t in args.timeframes.split(",") if t.strip())

    closure, external = import_closure(ENTRYPOINT)
    consumers = corpus_consumers(closure)
    failing = [c for c in consumers if c["verdict"] == "WOULD_FAIL_WITHOUT_CORPUS"]

    payload = {
        "wp": "WP-PAPER-REAL-DATA-001",
        "generated_at": _iso(),
        "entrypoint": ENTRYPOINT.relative_to(REPO_ROOT).as_posix(),
        "method": {
            "imports": "AST closure from the entrypoint, relative imports resolved",
            "corpus_markers": list(CORPUS_MARKERS),
            "file_read_markers": list(FILE_READ_MARKERS),
            "runtime_reachability": (
                "a strategy is reachable iff the admission ledger holds an entry for the "
                "run's timeframe (StrategyRegistry.for_timeframe / entries_for_timeframe)"
            ),
        },
        "totals": {
            "repo_modules_reached": len(closure),
            "external_top_level_packages": len(external),
            "modules_naming_the_15m_corpus": len(consumers),
            "modules_that_would_fail_without_it": len(failing),
        },
        "external_packages": external,
        "corpus_consumers": consumers,
        "paper_path_depends_on_missing_corpus": bool(failing),
        "strategies": strategy_reachability(REPO_ROOT / "config/strategy_admission.json", timeframes),
        "runtime_data_sources": [
            {
                "provider": "ccxt",
                "route": "venue session via resolve_scanner_source",
                "needs_credentials": False,
                "yields_real_market_data": True,
                "usable_in_paper": False,
                "why": "Settings guard: paper requires universe.exchanges[].sandbox=true (testnet feed)",
            },
            {
                "provider": "fake",
                "route": "build_demo_fetcher",
                "needs_credentials": False,
                "yields_real_market_data": False,
                "usable_in_paper": True,
                "why": "deterministic provider for control runs only",
            },
            {
                "provider": "public-rest (injected)",
                "route": "scanner_factory injection (scripts/wp_prd001_campaign.py)",
                "needs_credentials": False,
                "yields_real_market_data": True,
                "usable_in_paper": True,
                "why": "read-only public klines/ticker/bookTicker; opens no venue session",
            },
        ],
    }
    path = out_dir / "PAPER_REACHABILITY.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[reach] modules={payload['totals']['repo_modules_reached']} "
        f"corpus_markers={payload['totals']['modules_naming_the_15m_corpus']} "
        f"would_fail={payload['totals']['modules_that_would_fail_without_it']}"
    )
    for tf, rows in payload["strategies"]["by_timeframe"].items():
        print(f"[reach] {tf}: " + ", ".join(f"{r['strategy_id']}={r['decision_if_selected']}" for r in rows))
    print(f"[reach] -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
