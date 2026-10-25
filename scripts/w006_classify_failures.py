#!/usr/bin/env python3
"""Classify pre-existing test failures from a JUnit XML (WP-006).

The point of this script is not to make the suite green; it is to attach a cause to
every failure so that none can be dismissed as "pre-existing noise" without
evidence. Each failure is assigned one of:

MISSING_VERSIONED_ARTIFACT  the test asserts on a file no commit carries (the exact
                            path is checked with ``git ls-files``);
FIXTURE_INVENTORY_GAP       a test double raises ``StopIteration`` because the dataset
                            combination it iterates does not exist;
EVIDENCE_DIGEST_MISMATCH    a verification artifact records a digest that the bytes it
                            names no longer have;
UNTRIAGED_ASSERTION         a real assertion failure that this pass has not attributed:
                            reported with its own line, never reclassified as irrelevant.

``--baseline`` compares the failing nodeids against an earlier XML, which is how a
regression is told apart from a pre-existing failure.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

EVIDENCE_HINT = re.compile(r"(sha256|sha-256|digest|hash)", re.I)
HEX_MISMATCH = re.compile(r"[0-9a-f]{32,}")


def read_problems(xml_path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(xml_path)
    problems = []
    for tc in tree.iter("testcase"):
        for tag in ("failure", "error"):
            node = tc.find(tag)
            if node is None:
                continue
            problems.append({
                "nodeid": f"{tc.get('classname')}::{tc.get('name')}",
                "module": tc.get("classname") or "",
                "file": tc.get("file") or "",
                "kind": tag,
                "message": (node.get("message") or "").strip(),
                "text": node.text or "",
            })
            break
    return problems


def last_assertion_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("E ") or "AssertionError" in line:
            return line[:200]
    return lines[-1][:200] if lines else ""


def is_versioned(repo: Path, path: str) -> bool:
    result = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", path],
                            capture_output=True, text=True)
    return result.returncode == 0


def classify(problem: dict[str, Any], repo: Path) -> dict[str, Any]:
    text = problem["text"]
    node = dict(problem)
    missing = re.findall(r"No such file or directory: '([^']+)'", text)
    if missing:
        path = missing[0]
        rel = path
        try:
            rel = str(Path(path).resolve().relative_to(repo.resolve())).replace("\\", "/")
        except ValueError:
            pass
        node.update({"category": "MISSING_VERSIONED_ARTIFACT", "path": rel,
                     "versioned": is_versioned(repo, rel),
                     "cause": "the artifact this test asserts on is not in the repository"})
        return node
    if "StopIteration" in text and "next(" in text:
        node.update({"category": "FIXTURE_INVENTORY_GAP",
                     "cause": "a test double iterates a dataset combination that does not exist"})
        return node
    if EVIDENCE_HINT.search(text) and len(HEX_MISMATCH.findall(text)) >= 2:
        node.update({"category": "EVIDENCE_DIGEST_MISMATCH",
                     "cause": "recorded digest differs from the bytes it names"})
        return node
    node.update({"category": "UNTRIAGED_ASSERTION", "last_line": last_assertion_line(text),
                 "cause": "assertion failure not attributed in this pass"})
    return node


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--xml", type=Path, required=True)
    p.add_argument("--baseline", type=Path, default=None)
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--out-json", type=Path, required=True)
    p.add_argument("--out-md", type=Path, default=None)
    args = p.parse_args(argv)

    problems = [classify(pr, args.repo) for pr in read_problems(args.xml)]
    counts = Counter(pr["category"] for pr in problems)
    by_module = Counter(pr["module"] for pr in problems)

    comparison: dict[str, Any] = {}
    if args.baseline and args.baseline.is_file():
        before = {pr["nodeid"] for pr in read_problems(args.baseline)}
        after = {pr["nodeid"] for pr in problems}
        comparison = {"baseline": str(args.baseline), "before": len(before), "after": len(after),
                      "introduced": sorted(after - before), "fixed": sorted(before - after),
                      "identical_set": before == after}

    report = {
        "schema": "W006_FAILURE_CLASSIFICATION_V1",
        "xml": str(args.xml),
        "totals": {"problems": len(problems),
                   "failures": sum(1 for p in problems if p["kind"] == "failure"),
                   "errors": sum(1 for p in problems if p["kind"] == "error")},
        "by_category": dict(counts),
        "comparison": comparison,
        "problems": problems,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")

    if args.out_md:
        lines = ["# Clasificación de fallos preexistentes", "",
                 f"- XML: `{args.xml}`",
                 f"- Total: {report['totals']['problems']} "
                 f"({report['totals']['failures']} fallos, {report['totals']['errors']} errores)", ""]
        lines.append("| categoría | nº |")
        lines.append("| --- | --- |")
        for cat, n in counts.most_common():
            lines.append(f"| `{cat}` | {n} |")
        if comparison:
            lines += ["", "## Comparación con la línea base", "",
                      f"- antes: {comparison['before']}, después: {comparison['after']}, "
                      f"introducidos: {len(comparison['introduced'])}, "
                      f"corregidos: {len(comparison['fixed'])}"]
            for nodeid in comparison["introduced"]:
                lines.append(f"- INTRODUCIDO `{nodeid}`")
        for cat in ("MISSING_VERSIONED_ARTIFACT", "FIXTURE_INVENTORY_GAP",
                    "EVIDENCE_DIGEST_MISMATCH", "UNTRIAGED_ASSERTION"):
            sel = [p for p in problems if p["category"] == cat]
            if not sel:
                continue
            lines += ["", f"## {cat} ({len(sel)})", ""]
            if cat == "MISSING_VERSIONED_ARTIFACT":
                paths = Counter(p["path"] for p in sel)
                lines += ["| artefacto ausente | tests | versionado |", "| --- | --- | --- |"]
                for path, n in paths.most_common():
                    versioned = next(p["versioned"] for p in sel if p["path"] == path)
                    lines.append(f"| `{path}` | {n} | {versioned} |")
            else:
                lines += ["| test | detalle |", "| --- | --- |"]
                for p in sel[:40]:
                    detail = p.get("last_line") or p.get("cause") or p["message"][:120]
                    lines.append(f"| `{p['nodeid']}` | {detail[:150]} |")
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    for cat, n in counts.most_common():
        print(f"{cat:28s} {n:3d}")
    print(f"total {len(problems)} | modules {len(by_module)} -> {args.out_json}")
    if comparison:
        print(f"baseline: introduced={len(comparison['introduced'])} "
              f"fixed={len(comparison['fixed'])} identical={comparison['identical_set']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
