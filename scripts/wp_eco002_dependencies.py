"""WP-ECONOMIC-RECOVERY-002 — the files a clean checkout does not have.

The previous work package attributed 21 test failures to "unversioned
`reports/**`". This script answers that with the failures themselves: it parses
the traceback transcript of a run inside a fresh clone, groups every
``FileNotFoundError`` by the file it names and the test that asked for it, and
then classifies each one by asking git whether HEAD carries it and by asking the
ignore rules who was supposed to produce it.

The classification is deliberately narrow — three answers only:

``REGENERABLE_BY_A_COMMITTED_PRODUCER``
    a gitignored output of a script that is in the repository; it can be rebuilt
    from a clean checkout only with the inputs that script needs (market data,
    network), so its absence is a data dependency, not a code defect.
``HOST_RUNTIME_EVIDENCE``
    written by the running layer on this machine; it cannot be regenerated from
    a clone at all, only accumulated by running.
``NEVER_COMMITTED_DELIVERABLE``
    a document the repository's own tests require and HEAD does not carry: the
    deliverable was never committed, which no amount of re-running fixes.

Reads ``parts/clone_dependency_tracebacks.txt``; writes
``DECLARED_DEPENDENCIES.json``.

Usage:
    uv run python scripts/wp_eco002_dependencies.py [--out <evidence dir>]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-002")
TRANSCRIPT = Path("parts/clone_dependency_tracebacks.txt")

# `--tb=line` prints one line per failure: `<file>:<line>: <Error>: <detail>`. The file may be an
# absolute Windows path, whose drive colon is why the file part cannot be matched greedily
# without forbidding `:`.
LINE_RE = re.compile(
    r"^(?P<test>.+?\.py):(?P<line>\d+): (?P<error>[A-Za-z_]+(?:Error|Exit)): (?P<detail>.*)$"
)
PATH_RE = re.compile(r"No such file or directory: '([^']+)'")
ASSERT_PATH_RE = re.compile(r"(missing[^\n]*?|absent[^\n]*?)((?:reports|data|docs)/[^\s'\"\],]+)")

CLASSIFICATIONS = {
    "reports/profitability_gate035/": (
        "REGENERABLE_BY_A_COMMITTED_PRODUCER",
        "scripts/profitability_gate035.py (gitignored output of the profitability search)",
    ),
    "reports/rfc035/search_round_3/": (
        "REGENERABLE_BY_A_COMMITTED_PRODUCER",
        "the RFC-035 search round producers (gitignored output)",
    ),
    "reports/strategy-baseline/": (
        "REGENERABLE_BY_A_COMMITTED_PRODUCER",
        "scripts/multi_family_backtest.py (gitignored output; the cost-barrier builder reads it)",
    ),
    "data/raw/": (
        "REGENERABLE_BY_A_COMMITTED_PRODUCER",
        "the market-data collector: raw prices are gitignored by design",
    ),
    "data/st6/": (
        "HOST_RUNTIME_EVIDENCE",
        "scripts/st6_forward_regime.py / st6_health_check.py, on this host only",
    ),
    "reports/rfc046/": (
        "NEVER_COMMITTED_DELIVERABLE",
        "an RFC-046 deliverable that the tests require and HEAD does not carry",
    ),
    "docs/research/work_packages/": (
        "NEVER_COMMITTED_DELIVERABLE",
        "a researched work-package document the tests require and HEAD does not carry",
    ),
}


#: Paths a test requires with `Path.is_file()` rather than by opening them, so the transcript
#: records an `assert False` instead of naming the file. Verified against HEAD below like the rest.
INSPECTED_REQUIREMENTS = (
    "docs/research/work_packages/WP-HTF-PIT-001_htf_availability_unit_fix.md",
    "reports/rfc046/IMPACT_ASSESSMENT.md",
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def relative(path: str) -> str:
    """Strip the temporary clone prefix and tidy the separators.

    The transcript mixes formats: absolute Windows paths from a ``FileNotFoundError``,
    repository-relative paths from an assertion, and JSON escapes in between. Everything is
    reduced to one repository-relative path so the same file groups once.
    """

    marker = re.search(r"repo[\\/](.+)$", path)
    cleaned = (marker.group(1) if marker else path).replace("\\", "/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    return cleaned.lstrip("/").rstrip(".,'\"")


def classify(rel_path: str) -> tuple[str, str]:
    for prefix, (kind, producer) in CLASSIFICATIONS.items():
        if rel_path.startswith(prefix):
            return kind, producer
    return "UNCLASSIFIED", "no producer known"


def parse_transcript(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        match = LINE_RE.match(raw.strip())
        if not match:
            continue
        detail = match.group("detail")
        named = PATH_RE.findall(detail)
        if not named:
            nestled = ASSERT_PATH_RE.findall(detail)
            named = [path for _, path in nestled]
        for path in named:
            rel_path = relative(path)
            if "/" not in rel_path:
                continue
            kind, producer = classify(rel_path)
            rows.append(
                {
                    "path": rel_path,
                    "test": match.group("test").replace("\\", "/"),
                    "error": match.group("error"),
                    "classification": kind,
                    "producer": producer,
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    out_dir = REPO_ROOT / args.out
    transcript = out_dir / TRANSCRIPT
    if not transcript.is_file():
        raise SystemExit(f"missing {transcript}; run the clone traceback phase first")

    rows = parse_transcript(transcript.read_text(encoding="utf-8", errors="replace"))
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = grouped.setdefault(
            row["path"],
            {
                "path": row["path"],
                "classification": row["classification"],
                "producer": row["producer"],
                "named_by": set(),
                "mentions": 0,
            },
        )
        entry["named_by"].add(row["test"])
        entry["mentions"] += 1

    for path in INSPECTED_REQUIREMENTS:
        grouped.setdefault(
            path,
            {
                "path": path,
                "classification": classify(path)[0],
                "producer": classify(path)[1],
                "named_by": set(),
                "mentions": 0,
            },
        )

    for entry in grouped.values():
        entry["named_by"] = sorted(entry["named_by"])
        entry["tracked_at_head"] = bool(
            git("ls-tree", "-r", "--name-only", "HEAD", "--", entry["path"])
        )
        entry["present_in_working_tree"] = (REPO_ROOT / entry["path"]).is_file()
        entry["ignored"] = bool(git("check-ignore", entry["path"]))

    by_class: dict[str, list[str]] = collections.defaultdict(list)
    for entry in grouped.values():
        by_class[entry["classification"]].append(entry["path"])

    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-002",
        "artefact": "DECLARED_DEPENDENCIES",
        "commit": git("rev-parse", "HEAD"),
        "source_transcript": (args.out / TRANSCRIPT).as_posix(),
        "method": (
            "a fresh `git clone` of this commit ran the eight test files that carry most of the "
            "pre-existing failures with `--tb=line`; every FileNotFoundError and every "
            '"missing <path>" assertion was grouped by the path it names'
        ),
        "summary": {
            "distinct_missing_paths": len(grouped),
            "mentions": sum(entry["mentions"] for entry in grouped.values()),
            "by_classification": {kind: sorted(paths) for kind, paths in by_class.items()},
            "tracked_at_head": sorted(
                path for path, entry in grouped.items() if entry["tracked_at_head"]
            ),
        },
        "dependencies": sorted(
            grouped.values(), key=lambda entry: (-entry["mentions"], entry["path"])
        ),
        "notes": [
            "no `reports/**` path is required by any of the 21 nodes the previous work package "
            "attributed to the clean checkout: those 21 now pass in a fresh clone (see "
            "REPRODUCIBILITY_COMPARISON.json). The `reports/**` dependencies below belong to the "
            "pre-existing failures that fail in both trees.",
            "a dependency that is a HOST_RUNTIME_EVIDENCE file cannot be satisfied by committing "
            "it: doing so would ship a machine's log as if it were evidence, and running the "
            "tests would then rewrite a tracked file.",
        ],
    }
    (out_dir / "DECLARED_DEPENDENCIES.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    print(f"distinct missing paths: {len(grouped)}; mentions: {payload['summary']['mentions']}")
    for kind, paths in payload["summary"]["by_classification"].items():
        print(f"  {kind}: {len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
