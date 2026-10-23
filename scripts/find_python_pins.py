#!/usr/bin/env python
"""List every Python file whose bytes a committed artefact pins by digest.

A formatter changes bytes. Where a committed record certifies the bytes of a producer
script, reformatting that script invalidates the record, and a test that compares the
two will fail for a reason that has nothing to do with logic. This scan makes that set
explicit so it can be exempted deliberately instead of discovered one red test at a time.

The rule is deliberately mechanical: walk the JSON artefacts, and treat any object that
carries a ``path`` ending in ``.py`` together with a digest-shaped key as a pin.

Usage::

    python scripts/find_python_pins.py --root . --json PYTHON_PINS.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DIGEST_KEYS = ("sha256", "sha256_lf", "sha256_crlf", "digest", "content_sha256", "hash")
SKIP_DIRS = (".git", ".tmp", "node_modules", ".venv")
MAX_BYTES = 8_000_000


def iter_json(root: Path) -> tuple[list[Path], int]:
    """Return the scannable JSON files and how many were skipped as unreadable."""
    paths: list[Path] = []
    skipped = 0
    for path in sorted(root.rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        if any(part in rel for part in SKIP_DIRS):
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                skipped += 1
                continue
        except OSError:
            skipped += 1
            continue
        paths.append(path)
    return paths, skipped


def collect_pins(payload: Any, artefact: str, pins: dict[str, list[str]]) -> None:
    """Depth-first walk collecting ``path``+digest pairs."""
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            target = node.get("path")
            if (
                isinstance(target, str)
                and target.endswith(".py")
                and any(key in node for key in DIGEST_KEYS)
            ):
                seen = pins.setdefault(target, [])
                if artefact not in seen:
                    seen.append(artefact)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List Python files pinned by artefacts.")
    parser.add_argument("--root", default=".", help="tree to scan (default: cwd)")
    parser.add_argument("--json", default=None, help="write the record here")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    paths, skipped = iter_json(root)
    pins: dict[str, list[str]] = {}
    scanned = 0
    unreadable = skipped
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        scanned += 1
        collect_pins(payload, path.relative_to(root).as_posix(), pins)

    record = {
        "schema": "wp00307-python-pins/1",
        "scanned_json_files": scanned,
        "unreadable_json_files": unreadable,
        "pinned_python_paths": dict(sorted(pins.items())),
    }
    print(f"scanned {scanned} json files ({unreadable} unreadable)")
    print(f"pinned python paths: {len(pins)}")
    for target in sorted(pins):
        print(f"  {target}  <- {len(pins[target])} artefact(s)")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        print(f"[find-python-pins] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
