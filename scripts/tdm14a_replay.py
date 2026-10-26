"""RFC-TDM-014A — WP-14C cold replay: regenerate everything, or say so.

The replay this RFC demands is stronger than the one TDM-13 could run. It requires
that *every* output of the pipeline be produced inside this execution:

* the sealed inputs are restored from the bundle and every digest is re-checked
  before anything runs;
* every replay output and cache is deleted in a scratch directory we own, and the
  run refuses to start if any of them is still there;
* no ``--reuse`` flag is ever passed: ``review`` recomputes the ledger, the
  dependence intervals and the controls, and ``inventory`` recomputes cell metrics
  from the sealed bars;
* a timeout kills the process tree (``taskkill /T`` on Windows), records
  ``TIMEOUT`` and never degrades to PASS.

A file that existed before the run cannot count as an output. So the harness
records, per output: the digest before (must be absent), the digest after, the
mtime, and whether the run id is embedded in the document.

Commands::

    python scripts/tdm14a_replay.py --clone <clone> --label LF \\
        --run-id tdm14a-... --out <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
MANIFEST_RELPATH = "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json"

#: What the pipeline must produce, and where. Nothing else counts as an output.
OUTPUT_SPEC: tuple[tuple[str, str], ...] = (
    ("review", ".tdm12/review.json"),
    ("cell_metrics", ".tdm12/cell_metrics.json"),
    ("registry_json", "{out}/CANDIDATE_REGISTRY.json"),
    ("registry_csv", "{out}/CANDIDATE_REGISTRY.csv"),
    ("window_registry", "{out}/DATA_WINDOW_REGISTRY.json"),
)

#: Scratch state no replay may inherit. Deleted, then proven absent.
WIPE: tuple[str, ...] = (".tdm12", ".replay-out")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def git(cwd: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def kill_tree(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Terminate the process and every child it started."""
    detail: dict[str, Any] = {"pid": proc.pid, "method": None, "returncode": None}
    if proc.poll() is not None:
        detail["method"] = "already-exited"
        detail["returncode"] = proc.returncode
        return detail
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        detail["method"] = "taskkill /F /T"
        detail["taskkill_exit"] = result.returncode
        detail["taskkill_output"] = (result.stdout or result.stderr).strip()[:400]
    else:
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            detail["method"] = "killpg SIGKILL"
        except OSError as exc:  # pragma: no cover - not the Windows path used here
            detail["method"] = f"killpg failed: {exc}"
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    detail["returncode"] = proc.returncode
    return detail


def run_phase(
    *,
    name: str,
    argv: list[str],
    cwd: Path,
    timeout: float,
    log_path: Path,
) -> dict[str, Any]:
    """One phase, one attempt, one log, one bounded wait."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_wall = utc_now()
    started = time.time()
    with log_path.open("wb") as handle:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        timed_out = False
        killed: dict[str, Any] | None = None
        try:
            exit_code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            killed = kill_tree(proc)
            exit_code = proc.returncode
    duration = round(time.time() - started, 1)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    status = "TIMEOUT" if timed_out else ("PASS" if exit_code == 0 else "FAIL")
    return {
        "phase": name,
        "command": " ".join(Path(a).name if i == 0 else a for i, a in enumerate(argv)),
        "argv": argv,
        "cwd": str(cwd),
        "timeout_seconds": timeout,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "killed_tree": killed,
        "duration_seconds": duration,
        "started_utc": started_wall,
        "finished_utc": utc_now(),
        "log": str(log_path),
        "log_sha256": sha256_file(log_path),
        "log_tail": log_text.strip().splitlines()[-6:],
        "status": status,
    }


def restore_inputs(clone: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Copy the sealed bundle into the clone and prove every digest on arrival."""
    rows: list[dict[str, Any]] = []
    bundle_root = clone
    for entry in manifest["datasets"]:
        source = bundle_root / entry["path"]
        destination = clone / entry["original_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        actual = sha256_file(destination)
        rows.append(
            {
                "dataset_id": entry["dataset_id"],
                "original_path": entry["original_path"],
                "sha256_declared": entry["sha256"],
                "sha256_restored": actual,
                "bytes": destination.stat().st_size,
                "match": actual == entry["sha256"],
            }
        )
    bad = [r for r in rows if not r["match"]]
    return {
        "files": len(rows),
        "matching": len(rows) - len(bad),
        "total_bytes": sum(r["bytes"] for r in rows),
        "failures": [r["dataset_id"] for r in bad],
        "status": "AVAILABLE" if not bad else "CORRUPTED",
        "rows": rows,
    }


def wipe(clone: Path) -> dict[str, Any]:
    """Remove replay state we own, then prove it is gone."""
    removed: list[str] = []
    for rel in WIPE:
        target = clone / rel
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(rel)
        elif target.is_file():
            target.unlink()
            removed.append(rel)
    leftovers = [rel for rel in WIPE if (clone / rel).exists()]
    return {"removed": removed, "leftovers": leftovers, "clean_before_run": not leftovers}


def snapshot_outputs(clone: Path, out_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name, template in OUTPUT_SPEC:
        rel = template.format(out=out_dir.relative_to(clone).as_posix())
        path = clone / rel
        rows.append(
            {
                "name": name,
                "path": rel,
                "exists_before": path.exists(),
                "sha256_before": sha256_file(path),
            }
        )
    return {row["name"]: row for row in rows}


def finalise_outputs(
    clone: Path, out_dir: Path, before: dict[str, Any], run_started: float, run_id: str
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name, template in OUTPUT_SPEC:
        rel = template.format(out=out_dir.relative_to(clone).as_posix())
        path = clone / rel
        exists = path.is_file()
        mtime = path.stat().st_mtime if exists else None
        row = {
            "name": name,
            "path": rel,
            "exists": exists,
            "bytes": path.stat().st_size if exists else 0,
            "sha256": sha256_file(path),
            "mtime_epoch": mtime,
            "generated_after_run_start": bool(mtime and mtime >= run_started - 2),
            "absent_before_run": not before[name]["exists_before"],
            "run_id_embedded": False,
        }
        if exists and path.suffix == ".json":
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                doc = None
            if isinstance(doc, dict):
                row["run_id_embedded"] = doc.get("run_id") == run_id
        rows.append(row)
    generated = [r for r in rows if r["exists"]]
    proven = [r for r in generated if r["generated_after_run_start"] and r["absent_before_run"]]
    return {
        "rows": rows,
        "outputs_expected": len(rows),
        "outputs_present": len(generated),
        "outputs_proven_generated": len(proven),
        "outputs_with_run_id": sum(1 for r in rows if r["run_id_embedded"]),
        "status": "PASS" if len(proven) == len(rows) else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clone", required=True)
    parser.add_argument("--label", required=True, help="run label, e.g. LF or CRLF")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True, help="report path (JSON)")
    parser.add_argument("--target-commit", default=None)
    parser.add_argument("--review-timeout", type=float, default=1800.0)
    parser.add_argument("--inventory-timeout", type=float, default=2400.0)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--inject-stale-state",
        action="store_true",
        help="plant a fake .tdm12/review.json and cell metrics before isolating, to prove "
        "the wipe removes them",
    )
    args = parser.parse_args(argv)

    clone = Path(args.clone).resolve()
    out_dir = clone / ".replay-out" / args.label.lower()
    log_dir = clone / ".replay-logs" / args.label.lower()
    report_path = Path(args.out)
    if not report_path.is_absolute():
        report_path = HERE / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)

    run_started = time.time()
    report: dict[str, Any] = {
        "rfc_id": "RFC-TDM-014A",
        "wp": "WP-14C",
        "run_id": args.run_id,
        "label": args.label,
        "clone": str(clone),
        "report_path": str(report_path),
        "started_utc": utc_now(),
        "environment": {
            "python": sys.version.split()[0],
            "python_executable": args.python,
            "platform": platform.platform(),
            "cwd_independent": str(HERE),
        },
        "phases": [],
        "status": "INCOMPLETE",
    }

    _, head = git(clone, "rev-parse", "HEAD")
    target = args.target_commit or head
    _, branch = git(clone, "rev-parse", "--abbrev-ref", "HEAD")
    diff_index = git(clone, "diff-index", "--quiet", "HEAD", "--")[0]
    diff_cached = git(clone, "diff-index", "--cached", "--quiet", "HEAD", "--")[0]
    _, untracked = git(clone, "ls-files", "--others", "--exclude-standard")
    _, autocrlf = git(clone, "config", "--get", "core.autocrlf")
    report["clone_state"] = {
        "head": head,
        "head_matches_target": head == target,
        "branch": branch,
        "target_commit": target,
        "worktree_content_matches_head": diff_index == 0,
        "index_matches_head": diff_cached == 0,
        "untracked_count": len(untracked.splitlines()),
        "core_autocrlf": autocrlf or None,
    }
    if head != target:
        report["status"] = "FAIL"
        report["failure"] = f"clone HEAD {head[:8]} != target {target[:8]}"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["failure"])
        return 1
    if diff_index != 0 or diff_cached != 0:
        report["status"] = "FAIL"
        report["failure"] = (
            "clone has local modifications; a replay from dirty sources proves nothing"
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["failure"])
        return 1

    manifest_path = clone / MANIFEST_RELPATH
    if not manifest_path.is_file():
        report["status"] = "BLOCKED"
        report["failure"] = f"missing sealed input manifest {MANIFEST_RELPATH}"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["failure"])
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report["inputs"] = restore_inputs(clone, manifest)
    report["inputs"]["manifest_sha256"] = sha256_file(manifest_path)
    if report["inputs"]["status"] != "AVAILABLE":
        report["status"] = "FAIL"
        report["failure"] = "restored inputs do not match the sealed bundle"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["failure"])
        return 1

    injected: dict[str, Any] | None = None
    if args.inject_stale_state:
        (clone / ".tdm12").mkdir(parents=True, exist_ok=True)
        poison = {
            "ledger": {"derived_trades": 999, "gross_mean": 999.0, "net_mean": 999.0},
            "dependence": {
                "day_clustered_ci95_gross": {"lo": 1.0, "hi": 2.0, "se": 0.5, "day_clusters": 3}
            },
            "controls": {"lookahead_advantage_bps": 999.0},
            "independence": {"status": "FORGED"},
            "generated_at_ms": 1,
            "run_id": "forged-run",
        }
        poison_path = clone / ".tdm12" / "review.json"
        poison_path.write_text(json.dumps(poison), encoding="utf-8")
        cells = clone / ".tdm12" / "cell_metrics.json"
        cells.write_text(json.dumps({"forged": {"hold": [], "dev": []}}), encoding="utf-8")
        injected = {
            "review.json": sha256_file(poison_path),
            "cell_metrics.json": sha256_file(cells),
        }
    report["injected_stale_state"] = injected

    report["isolation"] = wipe(clone)
    if not report["isolation"]["clean_before_run"]:
        report["status"] = "FAIL"
        report["failure"] = "could not isolate replay outputs"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["failure"])
        return 1

    before = snapshot_outputs(clone, out_dir)
    report["outputs_before"] = before

    report["phases"].append(
        run_phase(
            name="review",
            argv=[args.python, "scripts/tdm12_review.py"],
            cwd=clone,
            timeout=args.review_timeout,
            log_path=log_dir / "review.log",
        )
    )
    report["phases"].append(
        run_phase(
            name="inventory",
            argv=[
                args.python,
                "scripts/tdm12_inventory.py",
                "--fingerprint-scheme",
                "v2",
                "--source-commit",
                target,
                "--out-dir",
                str(out_dir),
                "--run-id",
                args.run_id,
            ],
            cwd=clone,
            timeout=args.inventory_timeout,
            log_path=log_dir / "inventory.log",
        )
    )

    report["outputs"] = finalise_outputs(clone, out_dir, before, run_started, args.run_id)
    report["cell_metrics_sha256"] = sha256_file(clone / ".tdm12" / "cell_metrics.json")
    report["review_sha256"] = sha256_file(clone / ".tdm12" / "review.json")

    phases_ok = all(p["status"] == "PASS" for p in report["phases"])
    outputs_ok = report["outputs"]["status"] == "PASS"
    if not phases_ok:
        report["status"] = "INCOMPLETE"
        report["failure"] = [
            f"{p['phase']}:{p['status']}" for p in report["phases"] if p["status"] != "PASS"
        ]
    elif not outputs_ok:
        report["status"] = "FAIL"
        report["failure"] = "outputs were not demonstrably generated by this run"
    else:
        report["status"] = "PASS"
        report["failure"] = None

    report["finished_utc"] = utc_now()
    report["duration_seconds"] = round(time.time() - run_started, 1)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "label": args.label,
                "status": report["status"],
                "phases": {p["phase"]: p["status"] for p in report["phases"]},
                "outputs": f"{report['outputs']['outputs_proven_generated']}"
                f"/{report['outputs']['outputs_expected']} proven",
                "duration_seconds": report["duration_seconds"],
            },
            indent=1,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
