"""Who actually needs the lost 15m shards, and what can still run without them.

The question this answers is not "which files mention 15m" — half the tree mentions it — but
*which entrypoints cannot start a process* because three shards are absent.  Three things are
measured and kept apart:

* **needs** — every module that reads the alpha003 price directory, and which timeframe it
  reads from there.  ``edge01.data`` is the only reader; everything else is a caller.
* **reach** — the transitive closure from each entrypoint through the repository's own
  imports, so a script is charged for a dependency it inherits, not only one it names.
* **availability** — whether the corpus that closure needs is on disk right now, counted
  shard by shard, so "blocked" is a measurement and not a mood.

Reachability here is static: an entrypoint is *reachable* when its closure resolves, its
sources compile, and every corpus root it reads exists.  That deliberately does not execute
entrypoints — several of them start a runtime — so any operational claim in the report comes
from a separate, named run, never from this matrix.
"""

from __future__ import annotations

import argparse
import ast
import json
import py_compile
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

CORPUS_ALPHA003 = REPO / "data" / "raw" / "alpha003" / "price"
CORPUS_1H = REPO / "reports" / "alpha-expansion-v1" / "data"

#: Markers, in the order a reader should distrust them: a call is evidence, a path string is
#: only a hint that something nearby does the reading.
MARKERS = {
    #: A *call* to the 15m reader, the frozen instant constant, or a pin key.  Naming the
    #: ``CORPUS_15M`` path is not a read — that is ``names_corpus_15m`` below, and treating the
    #: two as one is how a report ends up calling its own verifier blocked while it runs green.
    #: Only two forms count: the reader call and a pin key.  A bare constant name is not
    #: evidence of a read — a docstring that mentions ``FROZEN_15M_END_MS`` once made the
    #: analyser call a script blocked that then ran and produced its evidence.
    "reads_15m": re.compile(r"(?<!def )\bload_15m\s*\(|\"15m:[A-Z]{2,5}\""),
    "names_corpus_15m": re.compile(r"\bCORPUS_15M\b"),
    "reads_1h": re.compile(r"\bload_1h\b|CORPUS_1H\b|alpha-expansion-v1"),
    "alpha003_path": re.compile(r"alpha003[\"/\\ ]*[\"/\\ ]*price|raw\"?\s*/\s*\"alpha003\""),
    #: A path string on its own is bookkeeping — three modules mention the directory only to
    #: declare what they must stay disjoint from.  It becomes a read when the same file also
    #: opens files, which is why the two markers are intersected below.
    "opens_files": re.compile(r"read_text|json\.load|\.glob\(|\.iterdir\(|open\("),
    #: ``if not root.is_dir(): continue`` turns a directory into an optional source.  Without
    #: this, a module that only declares what it must stay disjoint from is charged as if it
    #: could not start — the difference between a finding and a false alarm.
    "tolerates_absence": re.compile(r"is_dir\(\)|\.exists\(\)|\.is_file\(\)"),
    #: A module that *defines* the reader does not read anything until something calls it.
    #: Charging providers makes every importer of ``edge01.data`` look blocked, including the
    #: freeze CLI that demonstrably ran.
    "provides_corpus_reader": re.compile(r"^def (load_15m|load_1h)\s*\(", re.MULTILINE),
    "frozen_pin": re.compile(r"assert_frozen_corpus|FROZEN_SHARD_SHA256"),
}

#: Timeframes each container name asks the alpha003 directory for.
TIMEFRAME_OF_SHARD = re.compile(r"USDT_(?P<tf>1h|5m|15m)\.json")


def module_name(path: Path) -> str:
    rel = path.relative_to(REPO / "src")
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def local_imports(tree: ast.AST, module: str | None = None) -> set[str]:
    """Repository modules this file imports, however it spells the import.

    Relative imports (``from . import forward_plan``) are resolved against the importing
    module's package: without that, half of ``trading_bot`` looks dependency-free and an
    entrypoint that inherits a corpus reader is reported as reachable.
    """
    found: set[str] = set()
    package = (module or "").rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("trading_bot"))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative: go up (level - 1) packages
                parts = package.split(".") if package else []
                drop = node.level - 1
                parts = parts[: len(parts) - drop] if drop else parts
                base = ".".join([*parts, *([base] if base else [])])
            if not base.startswith("trading_bot"):
                continue
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def scan(path: Path, module: str | None = None) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    return {
        "path": str(path.relative_to(REPO)).replace("\\", "/"),
        "imports": sorted(local_imports(tree, module)),
        "markers": sorted(name for name, pattern in MARKERS.items() if pattern.search(text)),
        "has_main": "__main__" in text,
    }


def closure(start: str, graph: dict[str, dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for nxt in graph.get(node, {}).get("imports", []):
            if nxt in graph:
                stack.append(nxt)
            elif "." in nxt and nxt.rsplit(".", 1)[0] in graph:
                stack.append(nxt.rsplit(".", 1)[0])
    return seen


def availability() -> dict[str, Any]:
    def shards(root: Path, tf: str | None = None) -> dict[str, Any]:
        if not root.is_dir():
            return {"root": str(root), "exists": False, "shards": 0, "timeframes": {}}
        files = [p for p in root.glob("*.json") if not p.name.startswith("_")]
        by_tf: dict[str, int] = {}
        for item in files:
            match = TIMEFRAME_OF_SHARD.search(item.name)
            if match:
                by_tf[match.group("tf")] = by_tf.get(match.group("tf"), 0) + 1
        return {"root": str(root), "exists": True, "shards": len(files), "timeframes": by_tf}

    return {"alpha003_price": shards(CORPUS_ALPHA003), "one_hour": shards(CORPUS_1H)}


def compiles(path: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(path), cfile=str(Path(tmp) / "x.pyc"), doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="write the matrix JSON here")
    args = ap.parse_args(argv)

    graph: dict[str, dict[str, Any]] = {}
    for path in sorted((REPO / "src").rglob("*.py")):
        name = module_name(path)
        try:
            entry = scan(path, name)
        except (SyntaxError, UnicodeDecodeError):
            continue
        graph[name] = entry

    scripts: dict[str, dict[str, Any]] = {}
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.name == Path(__file__).name:
            # This analyser quotes every marker in its own source; scanning itself would put it
            # at the top of its own block list and teach a reader nothing.
            continue
        try:
            scripts[path.stem] = scan(path) | {"compiles": compiles(path)}
        except (SyntaxError, UnicodeDecodeError) as exc:  # a broken script is a finding, not a crash
            scripts[path.stem] = {"path": f"scripts/{path.name}", "error": repr(exc)}

    data = availability()
    default_1h = data["one_hour"]["exists"] and data["one_hour"]["shards"] > 0

    rows = []
    for name, info in sorted(scripts.items()):
        if "error" in info or not info.get("has_main"):
            continue
        # A script is not a node in the module graph: seed the closure with what it imports,
        # otherwise every entrypoint resolves to "no dependencies" and the matrix claims a
        # reachability it never measured.
        reached: set[str] = set()
        for imported in info.get("imports") or []:
            reached |= closure(imported, graph)
        merged = {name, *reached}
        markers = set(info["markers"])
        for module in reached:  # ``closure`` keeps attribute imports; only modules carry markers
            if module in graph:
                markers |= set(graph[module]["markers"])
        needs_15m = "reads_15m" in markers
        #: A module that builds a path into alpha003 and opens files there, without guarding on
        #: the directory existing, cannot start without it.  One that guards is only declaring
        #: an optional source.
        direct_readers = sorted(
            module
            for module in merged
            if module in graph
            and "alpha003_path" in graph[module]["markers"]
            and "opens_files" in graph[module]["markers"]
            and "provides_corpus_reader" not in graph[module]["markers"]
        )
        hard_readers = sorted(
            module for module in merged if module in graph and "reads_15m" in graph[module]["markers"]
        )
        # A script that calls the 15m reader itself is its own hard reader; the closure only
        # knows about modules, and charging a row for a dependency it cannot name is exactly
        # how a "blocked" verdict becomes unfalsifiable.
        if "reads_15m" in info["markers"]:
            hard_readers.append(f"scripts/{name}.py")
        unguarded = [
            module for module in direct_readers if "tolerates_absence" not in graph[module]["markers"]
        ]
        # A script that builds the corpus path itself is *reported*, not charged: whether it
        # guards the read is a property of one call site, and a matrix that cannot point at
        # the site has no business calling the entrypoint blocked (ST-6 is exactly this case —
        # it runs and marks the reference ``available: false``).
        self_reads_path = "alpha003_path" in info["markers"] and "opens_files" in info["markers"]
        needs_alpha003 = needs_15m or bool(unguarded)
        mentions_alpha003_only = "alpha003_path" in markers and not needs_alpha003
        reads_1h = "reads_1h" in markers
        if needs_alpha003:
            blocked = not data["alpha003_price"]["exists"]
            blocker = "ALPHA003_PRICE_ABSENT" if blocked else None
        elif reads_1h:
            blocked = not default_1h
            blocker = None if default_1h else "ONE_HOUR_CORPUS_ABSENT"
        else:
            blocked, blocker = False, None
        rows.append(
            {
                "entrypoint": f"scripts/{name}.py",
                "needs_15m": needs_15m,
                "needs_alpha003_price_dir": needs_alpha003,
                "reads_1h_corpus": reads_1h,
                "mentions_alpha003_without_reading_it": mentions_alpha003_only,
                "uses_frozen_pin": "frozen_pin" in markers,
                "hard_readers": hard_readers,
                "unguarded_directory_readers": unguarded,
                "reads_alpha003_path_directly": self_reads_path,
                #: Runs, but one of its inputs silently becomes ``available: false``; the
                #: verdict is neither READY nor BLOCKED, and saying which is the point.
                "degrades_without_alpha003": (
                    self_reads_path or bool(direct_readers)
                ) and not needs_alpha003,
                "modules_in_closure": len(reached),
                "corpus_on_disk": (
                    "ABSENT" if needs_alpha003 and not data["alpha003_price"]["exists"]
                    else "PRESENT" if needs_alpha003
                    else "NOT_REQUIRED"
                ),
                "statically_reachable": not blocked,
                "blocker": blocker,
            }
        )

    readers = [
        {"module": name, "markers": info["markers"], "path": info["path"]}
        for name, info in sorted(graph.items())
        if "reads_15m" in info["markers"] or "alpha003_path" in info["markers"]
    ]
    matrix = {
        "wp": "EDGE04-PROGRESS",
        "generated_by": "scripts/wp_edge04_deps.py",
        "availability": data,
        "readers_of_the_missing_directory": readers,
        "entrypoints": rows,
        "totals": {
            "entrypoints": len(rows),
            "need_15m": sum(1 for row in rows if row["needs_15m"]),
            "blocked_by_corpus": sum(1 for row in rows if not row["statically_reachable"]),
            "reachable_without_alpha003": sum(
                1 for row in rows if row["statically_reachable"] and not row["needs_alpha003_price_dir"]
            ),
        },
        "definition": (
            "statically_reachable = closure resolves, sources compile, and every corpus root the "
            "closure reads exists. Entrypoints are NOT executed here."
        ),
    }
    text = json.dumps(matrix, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")

    for row in rows:
        flag = "READY " if row["statically_reachable"] else "BLOCKED"
        print(
            f"{flag} {row['entrypoint']:52s} 15m={row['needs_15m']!s:5s} "
            f"alpha003={row['needs_alpha003_price_dir']!s:5s} "
            f"1h={row['reads_1h_corpus']!s:5s} {row['blocker'] or ''}"
        )
    print(f"\n{json.dumps(matrix['totals'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
