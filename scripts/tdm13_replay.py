"""RFC-TDM-013 — bounded replay of the TDM-12 pipeline from a clean clone.

What this proves, and what it refuses to prove: the replay re-runs the *builder's*
scripts unmodified in a separate clone, so it can show that the published numbers
come back, but it cannot by itself show that the pipeline is correct. Correctness
claims live in the independent verifier; this file only compares outputs.

A timeout or a non-zero exit is ``INCOMPLETE``, never ``PASS``. One justified
retry is allowed per phase; the retry is recorded.

Usage::

    python scripts/tdm13_replay.py --clone C:/path/to/clean-clone
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: ``TDM13_REPO`` points the comparison layer at a sandbox (negative controls).
REPO_ROOT = Path(os.environ.get("TDM13_REPO") or Path(__file__).resolve().parents[1]).resolve()
ART = REPO_ROOT / ".tdm13"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13"
MANIFEST = EVIDENCE / "DATASET_MANIFEST.json"
TARGET_COMMIT = "a96e9c80c608ed91943d1fab35db6fa1704111bb"

#: Fields that are demonstrably per-run bookkeeping, enumerated one by one. Every
#: other difference is treated as material.
EPHEMERAL_KEYS: tuple[str, ...] = (
    "generated_at_ms",
    "generated_at_utc",
    "elapsed_s",
    "run_id",
    "preflight",
    "verified_at",
    "cell metrics ready in",
)

#: Paths in the published manifest whose values the replay must reproduce.
REVIEW_CLAIMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("trades", ("ledger", "derived_trades")),
    ("gross_mean", ("ledger", "gross_mean")),
    ("net_mean", ("ledger", "net_mean")),
    ("day_clustered_ci95_gross", ("dependence", "day_clustered_ci95_gross")),
    ("net_upper_bound_by_method", ("dependence", "net_upper_bound_by_method")),
    ("per_asset", ("dependence", "per_asset")),
    ("lookahead_advantage_bps", ("controls", "lookahead_advantage_bps")),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip()


def strip_ephemeral(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_ephemeral(v) for k, v in value.items() if k not in EPHEMERAL_KEYS}
    if isinstance(value, list):
        return [strip_ephemeral(v) for v in value]
    return value


def deep_diff(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    """Every leaf where the two structures disagree, with its dotted path."""
    if type(left) is not type(right) and not (
        isinstance(left, int | float) and isinstance(right, int | float)
    ):
        return [{"path": path or "<root>", "committed": left, "replayed": right}]
    if isinstance(left, dict):
        out: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                out.append(
                    {
                        "path": f"{path}.{key}".lstrip("."),
                        "committed": left.get(key, "<absent>"),
                        "replayed": right.get(key, "<absent>"),
                    }
                )
            else:
                out += deep_diff(left[key], right[key], f"{path}.{key}".lstrip("."))
        return out
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": f"{path}.length", "committed": len(left), "replayed": len(right)}]
        out = []
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            out += deep_diff(a, b, f"{path}[{i}]")
        return out
    if left != right:
        return [{"path": path or "<root>", "committed": left, "replayed": right}]
    return []


def run_phase(
    name: str,
    script: str,
    clone: Path,
    python: str,
    timeout: float,
    log_dir: Path,
    retries: int = 1,
    extra_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    """One bounded phase: recorded command, exit code, duration, full logs."""
    attempts: list[dict[str, Any]] = []
    for attempt in range(retries + 1):
        log_path = log_dir / f"{name}.attempt{attempt + 1}.log"
        started = time.time()
        with log_path.open("w", encoding="utf-8") as handle:
            try:
                proc = subprocess.run(
                    [python, script, *extra_args],
                    cwd=clone,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
                exit_code: int | None = proc.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                exit_code = None
                timed_out = True
        duration = round(time.time() - started, 1)
        attempts.append(
            {
                "attempt": attempt + 1,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_seconds": duration,
                "log": str(log_path.relative_to(REPO_ROOT))
                if log_path.is_relative_to(REPO_ROOT)
                else str(log_path),
                "command": " ".join([Path(python).name, script, *extra_args]),
            }
        )
        if not timed_out and exit_code == 0:
            break
        if timed_out and attempt < retries:
            continue
        break
    last = attempts[-1]
    status = (
        "PASS"
        if last["exit_code"] == 0 and not last["timed_out"]
        else ("TIMEOUT" if last["timed_out"] else "FAIL")
    )
    print(f"  {name}: {status} ({last['duration_seconds']}s, attempts={len(attempts)})")
    return {"phase": name, "status": status, "attempts": attempts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clone", required=True)
    parser.add_argument("--target-commit", default=TARGET_COMMIT)
    parser.add_argument("--out", default=str(ART / "replay.json"))
    parser.add_argument("--review-timeout", type=float, default=900.0)
    parser.add_argument("--inventory-timeout", type=float, default=1800.0)
    parser.add_argument("--python", default=sys.executable)
    #: A second, justified attempt may reuse the review already computed in the
    #: same clone (the RFC allows one retry, not a new experiment).
    parser.add_argument("--reuse-review", action="store_true")
    parser.add_argument("--inventory-reuse", action="store_true")
    parser.add_argument("--attempt-note", default="")
    args = parser.parse_args(argv)

    clone = Path(args.clone).resolve()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir = REPO_ROOT / ".tdm13" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "rfc_id": "RFC-TDM-013",
        "phase": "WP-13B replay",
        "clone": str(clone),
        "target_commit": args.target_commit,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": sys.version.split()[0],
            "python_executable": args.python,
            "platform": platform.platform(),
        },
        "attempt_note": args.attempt_note,
        "phases": [],
        "comparisons": [],
        "differences": [],
        "status": "INCOMPLETE",
    }

    _, head = git("rev-parse", "HEAD", cwd=clone)
    _, dirty = git("status", "--porcelain", cwd=clone)
    tracked_dirty = [line for line in dirty.splitlines() if not line.startswith("??")]
    report["clone_state"] = {
        "head": head,
        "head_matches_target": head == args.target_commit,
        "tracked_dirty": tracked_dirty,
        "tracked_dirty_count": len(tracked_dirty),
    }
    if head != args.target_commit:
        report["status"] = "FAIL"
        report["differences"].append(
            {"path": "clone.head", "committed": args.target_commit, "replayed": head}
        )
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"clone HEAD {head[:8]} != target; refusing to replay")
        return 1

    # Inputs: the restored bytes must be the sealed bytes.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    input_rows: list[dict[str, Any]] = []
    for entry in manifest["datasets"]:
        restored = clone / entry["original_path"]
        actual = sha(restored) if restored.is_file() else None
        input_rows.append(
            {
                "dataset_id": entry["dataset_id"],
                "path": entry["original_path"],
                "restored": actual is not None,
                "sha256_match": actual == entry["sha256"],
            }
        )
    bad_inputs = [r for r in input_rows if not r["sha256_match"]]
    report["inputs"] = {
        "files": len(input_rows),
        "matching": len(input_rows) - len(bad_inputs),
        "failures": bad_inputs,
    }

    if bad_inputs:
        report["status"] = "FAIL"
        report["differences"] += [
            {
                "path": f"input:{f['dataset_id']}",
                "committed": "sealed sha256",
                "replayed": "mismatch",
            }
            for f in bad_inputs
        ]
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"{len(bad_inputs)} restored inputs do not match the sealed bundle")
        return 1

    regenerated_targets = ("CANDIDATE_REGISTRY.json", "DATA_WINDOW_REGISTRY.json")
    removed: list[str] = []
    for name in regenerated_targets:
        path = clone / "evidence" / "tdm" / "wp-tdm-12" / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    report["artifacts_removed_before_replay"] = removed

    if args.reuse_review and (clone / ".tdm12" / "review.json").is_file():
        report["phases"].append(
            {
                "phase": "review",
                "status": "REUSED",
                "attempts": [
                    {
                        "attempt": 1,
                        "exit_code": 0,
                        "timed_out": False,
                        "duration_seconds": 0.0,
                        "log": "(reused .tdm12/review.json from the first attempt)",
                        "command": "reused",
                    }
                ],
            }
        )
        print("  review: REUSED from the previous attempt")
    else:
        review = run_phase(
            "review", "scripts/tdm12_review.py", clone, args.python, args.review_timeout, log_dir
        )
        report["phases"].append(review)
    inventory = run_phase(
        "inventory",
        "scripts/tdm12_inventory.py",
        clone,
        args.python,
        args.inventory_timeout,
        log_dir,
        extra_args=("--reuse",) if args.inventory_reuse else (),
    )
    report["phases"].append(inventory)

    phases_ok = all(p["status"] in {"PASS", "REUSED"} for p in report["phases"])

    # Cross-artifact comparison: regenerated review -> published manifest metrics.
    replayed_review = clone / ".tdm12" / "review.json"
    published = json.loads(
        (clone / "evidence/tdm/wp-tdm-12/RUN_REPORT.json").read_text(encoding="utf-8")
    )
    if replayed_review.is_file():
        replayed = json.loads(replayed_review.read_text(encoding="utf-8"))
        published_metrics = published["metrics"]["tdm11_review"]
        for label, path in REVIEW_CLAIMS:
            expected = published_metrics.get(label)
            actual: Any = replayed
            for key in path:
                actual = (actual or {}).get(key) if isinstance(actual, dict) else None
            report["comparisons"].append(
                {
                    "artifact": "review.json",
                    "field": label,
                    "source": ".".join(path),
                    "committed": expected,
                    "replayed": actual,
                    "match": expected == actual,
                }
            )
        report["comparisons"].append(
            {
                "artifact": "review.json",
                "field": "independence_status",
                "source": "independence.status",
                "committed": published["independence_status"],
                "replayed": (replayed.get("independence") or {}).get("status"),
                "match": published["independence_status"]
                == (replayed.get("independence") or {}).get("status"),
            }
        )
    else:
        report["comparisons"].append(
            {
                "artifact": "review.json",
                "field": "<missing>",
                "committed": "produced by the pipeline",
                "replayed": None,
                "match": False,
            }
        )

    # Byte-level comparison of the regenerated evidence artefacts.
    for name in regenerated_targets:
        rel = f"evidence/tdm/wp-tdm-12/{name}"
        committed_proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=clone, capture_output=True, check=False
        )
        regenerated_path = clone / rel
        if committed_proc.returncode != 0 or not regenerated_path.is_file():
            report["comparisons"].append(
                {
                    "artifact": name,
                    "field": "<presence>",
                    "committed": committed_proc.returncode == 0,
                    "replayed": regenerated_path.is_file(),
                    "match": False,
                }
            )
            continue
        committed_doc = json.loads(committed_proc.stdout)
        regenerated_doc = json.loads(regenerated_path.read_text(encoding="utf-8"))
        diffs = deep_diff(strip_ephemeral(committed_doc), strip_ephemeral(regenerated_doc))
        report["comparisons"].append(
            {
                "artifact": name,
                "field": "<whole document, ephemeral keys removed>",
                "ephemeral_keys_removed": list(EPHEMERAL_KEYS),
                "difference_count": len(diffs),
                "differences": diffs[:20],
                "match": not diffs,
            }
        )
        report["differences"] += [
            {"path": f"{name}:{d['path']}", "committed": d["committed"], "replayed": d["replayed"]}
            for d in diffs
        ]

    mismatched = [c for c in report["comparisons"] if not c["match"]]
    if not phases_ok:
        report["status"] = "INCOMPLETE"
        report["incomplete_reason"] = [
            f"{p['phase']}: {p['status']}"
            for p in report["phases"]
            if p["status"] not in {"PASS", "REUSED"}
        ]
    elif mismatched:
        report["status"] = "FAIL"
        report["incomplete_reason"] = [f"{c['artifact']}:{c['field']}" for c in mismatched]
    else:
        report["status"] = "PASS"
        report["incomplete_reason"] = []

    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report["duration_seconds"] = round(
        sum(a["duration_seconds"] for p in report["phases"] for a in p["attempts"]), 1
    )
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"replay status={report['status']} comparisons="
        f"{len(report['comparisons']) - len(mismatched)}/{len(report['comparisons'])}"
    )
    for row in mismatched[:10]:
        print(f"  MISMATCH {row['artifact']}:{row['field']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
