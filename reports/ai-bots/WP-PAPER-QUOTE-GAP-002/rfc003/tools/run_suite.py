"""Re-run the 694-test set in five disjoint partitions, from a clean checkout.

Builder-side instrumentation, not runtime: it never imports ``trading_bot``. It drives
``pytest`` in a subprocess, keeps every raw log, and writes the identity of what ran so a
separate verifier can re-derive it without trusting this process.

The partitions are node-ID slices, not file groups: a file group would let a single test
module drift between two partitions and still look disjoint. Slicing also makes the
disjointness proof a set operation over the exact IDs pytest printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TARGETS = ["tests/unit/vision", "tests/unit/paper", "tests/unit/risk", "tests/unit/market_data"]
#: The shape the audited run reported. If collection drifts, the split adapts and the delta
#: is written to SUITE_IDENTITY.json instead of being papered over.
A5_SIZES = [310, 240, 92, 33, 19]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(cmd: list[str], cwd: Path) -> tuple[int, str, float]:
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return proc.returncode, proc.stdout + proc.stderr, time.perf_counter() - started


def collect(python: Path, checkout: Path) -> tuple[int, list[str], str]:
    code, output, _ = run([str(python), "-m", "pytest", "--collect-only", "-q", *TARGETS],
                          checkout)
    ids = [line.strip() for line in output.splitlines()
           if "::" in line and not line.startswith(("=", "FAILED", "ERROR"))]
    return code, ids, output


def sizes_for(total: int) -> list[int]:
    if total == sum(A5_SIZES):
        return A5_SIZES
    #: Proportional split keeping the same five buckets, remainder on the first ones.
    base = [total * s // sum(A5_SIZES) for s in A5_SIZES]
    for index in range(total - sum(base)):
        base[index % len(base)] += 1
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--skip-points", default="", help="comma-separated partition numbers to skip")
    args = parser.parse_args(argv)

    checkout = args.checkout.resolve()
    python = checkout / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = checkout / ".venv" / "bin" / "python"
    evidence: Path = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    skip = {int(x) for x in args.skip_points.split(",") if x.strip()}

    code, ids, raw = collect(python, checkout)
    (evidence / "collect.txt").write_text(raw, encoding="utf-8", newline="")
    total = len(ids)
    sizes = sizes_for(total)

    partitions: list[list[str]] = []
    cursor = 0
    for size in sizes:
        partitions.append(ids[cursor:cursor + size])
        cursor += size

    identity: dict[str, object] = {
        "schema": "SUITE_IDENTITY_V1",
        "collected": total,
        "collect_exit": code,
        "node_ids_sha256": sha256_text("\n".join(ids)),
        "collection_gap_vs_a5": total - sum(A5_SIZES),
        "sizes": sizes,
        "code_sha": run(["git", "rev-parse", "HEAD"], checkout)[1].strip(),
        "tree_sha": run(["git", "rev-parse", "HEAD^{tree}"], checkout)[1].strip(),
        "worktree_dirty": len([l for l in run(
            ["git", "status", "--porcelain=v2", "--untracked-files=all"], checkout)[1].splitlines()
            if l.strip()]),
        "python": str(python),
        "python_version": run([str(python), "-c", "import sys;print(sys.version)"], checkout)[1].strip(),
        "package_origin": run([str(python), "-c",
                               "import trading_bot;print(trading_bot.__file__)"], checkout)[1].strip(),
        "commands": [f"pytest {' '.join(TARGETS)} (collect-only)"],
        "parts": [],
    }

    #: Pairwise disjointness, proven before anything is executed.
    pairwise = {}
    for i in range(len(partitions)):
        for j in range(i + 1, len(partitions)):
            overlap = set(partitions[i]) & set(partitions[j])
            pairwise[f"{i + 1}v{j + 1}"] = len(overlap)
    union = set().union(*[set(p) for p in partitions])
    identity["disjointness"] = {
        "pairwise_overlap": pairwise,
        "union_size": len(union),
        "covers_collection": union == set(ids),
        "no_id_in_two_parts": all(v == 0 for v in pairwise.values()),
        "sum_of_parts": sum(len(p) for p in partitions),
    }

    for index, part in enumerate(partitions, start=1):
        if index in skip:
            continue
        #: Byte-identical command per partition except the IDs themselves.
        log_path = evidence / f"part-{index}.log"
        cmd = [str(python), "-m", "pytest", "-v", "-p", "no:warnings", "--tb=short", *part]
        env_note = "PYTHONPATH scrubbed"
        child_env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        started = time.perf_counter()
        #: Streamed to disk, not buffered: a partition of this suite takes minutes and a
        #: runner that only speaks at the end cannot be told apart from a hung one.
        with log_path.open("w", encoding="utf-8", newline="") as handle:
            proc = subprocess.run(cmd, cwd=checkout, env=child_env, stdout=handle,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                  errors="replace")
        elapsed = time.perf_counter() - started
        output = log_path.read_text(encoding="utf-8", errors="replace")
        passed = output.count(" PASSED")
        failed = output.count(" FAILED")
        errors = output.count(" ERROR")
        summary = [line for line in output.splitlines() if " passed" in line or " failed" in line]
        identity["parts"].append({
            "part": index,
            "size": len(part),
            "exit_code": proc.returncode,
            "seconds": round(elapsed, 1),
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "log": str(log_path.relative_to(evidence.parent)),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "log_bytes": log_path.stat().st_size,
            "node_ids_sha256": sha256_text("\n".join(part)),
            "command": "pytest -v -p no:warnings --tb=short <partition ids>",
            "env": env_note,
            "summary_line": summary[-1] if summary else None,
        })
        print(f"part {index}: {len(part)} ids, exit {proc.returncode}, "
              f"{passed} passed / {failed} failed / {errors} errors in {elapsed:.1f}s", flush=True)
        #: Persist after every partition: a 40-minute run that is killed must not lose the
        #: partitions that already finished and did pass.
        identity["totals"] = {
            "executed": sum(int(p2["size"]) for p2 in identity["parts"]),
            "passed": sum(int(p2["passed"]) for p2 in identity["parts"]),
            "failed": sum(int(p2["failed"]) for p2 in identity["parts"]),
            "errors": sum(int(p2["errors"]) for p2 in identity["parts"]),
            "exit_codes": [p2["exit_code"] for p2 in identity["parts"]],
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "complete": len(identity["parts"]) == len(partitions) - len(skip),
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(identity, indent=2, ensure_ascii=False) + chr(10),
                                 encoding="utf-8")

    (evidence / "requirements.frozen.txt").write_text(
        run([str(python), "-m", "pip", "freeze"], checkout)[1], encoding="utf-8", newline="")

    identity["totals"] = {
        "executed": sum(int(p["size"]) for p in identity["parts"]),
        "passed": sum(int(p["passed"]) for p in identity["parts"]),
        "failed": sum(int(p["failed"]) for p in identity["parts"]),
        "errors": sum(int(p["errors"]) for p in identity["parts"]),
        "exit_codes": [p["exit_code"] for p in identity["parts"]],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(identity, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(json.dumps(identity["totals"], indent=1))
    return 0 if all(p["exit_code"] == 0 for p in identity["parts"]) else 1


if __name__ == "__main__":
    sys.exit(main())
