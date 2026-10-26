"""RFC-TDM-014A — ACC-04 probe: the published v1 artefact still reproduces.

The fix must not make history unrunnable. So this probe runs the *new* inventory
in ``v1`` mode and requires the result to equal the registry TDM-12 published,
field by field, and requires the published file itself to be untouched.

Metrics are reused from the cold run of the same clone (``--reuse``): this is a
compatibility probe, not a replay, and it says so in its report instead of
pretending to be a third cold execution. The fingerprint fields are recomputed
from scratch in ``v1`` mode, which is the part under test.

It also proves the guard: a ``v1`` row and a ``v2`` row are refused as comparable.

Usage::

    python scripts/tdm14a_v1_compat.py --clone <lf-clone> --run-a <run_lf.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / "evidence" / "tdm" / "wp-tdm-14a"
TDM12 = HERE / "evidence" / "tdm" / "wp-tdm-12"
HISTORICAL = (
    "CANDIDATE_REGISTRY.json",
    "CANDIDATE_REGISTRY.csv",
    "DATA_WINDOW_REGISTRY.json",
    "RUN_REPORT.json",
)
EPHEMERAL = ("generated_at_ms", "elapsed_s", "run_id", "preflight")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(cwd: Path, *args: str) -> tuple[int, bytes]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    return proc.returncode, proc.stdout


def strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in EPHEMERAL}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def deep_diff(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if type(left) is not type(right) and not (
        isinstance(left, int | float) and isinstance(right, int | float)
    ):
        return [{"path": path or "<root>", "published": left, "v1_rerun": right}]
    if isinstance(left, dict):
        out: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}".lstrip(".")
            if key not in left or key not in right:
                out.append(
                    {
                        "path": child,
                        "published": left.get(key, "<absent>"),
                        "v1_rerun": right.get(key, "<absent>"),
                    }
                )
            else:
                out += deep_diff(left[key], right[key], child)
        return out
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": f"{path}.length", "published": len(left), "v1_rerun": len(right)}]
        out = []
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            out += deep_diff(a, b, f"{path}[{i}]")
        return out
    return (
        [] if left == right else [{"path": path or "<root>", "published": left, "v1_rerun": right}]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clone", required=True)
    parser.add_argument("--run-a", default=str(EVIDENCE / "run_lf.json"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", default=str(EVIDENCE / "v1_compat.json"))
    args = parser.parse_args(argv)

    clone = Path(args.clone).resolve()
    out_dir = clone / ".compat-out"
    if out_dir.exists():
        import shutil

        shutil.rmtree(out_dir)
    started = time.time()
    command = [
        args.python,
        "scripts/tdm12_inventory.py",
        "--fingerprint-scheme",
        "v1",
        "--out-dir",
        str(out_dir),
        "--reuse",
    ]
    log = clone / ".replay-logs" / "compat" / "v1.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as handle:
        proc = subprocess.run(
            command, cwd=clone, stdout=handle, stderr=subprocess.STDOUT, check=False
        )
    duration = round(time.time() - started, 1)

    result: dict[str, Any] = {
        "artifact": "tdm14a-v1-compat-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scheme": "v1",
        "clone": str(clone),
        "command": " ".join(command[1:]),
        "exit_code": proc.returncode,
        "duration_seconds": duration,
        "log": str(log),
        "metric_reuse": "cell metrics reused from the cold run of this same clone; the fingerprint "
        "fields are recomputed from scratch in v1 mode",
        "status": "FAIL",
    }

    if proc.returncode != 0:
        result["reason"] = "v1 inventory failed"
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "FAIL", "reason": result["reason"]}))
        return 1

    published = json.loads((TDM12 / "CANDIDATE_REGISTRY.json").read_text(encoding="utf-8"))
    rerun = json.loads((out_dir / "CANDIDATE_REGISTRY.json").read_text(encoding="utf-8"))
    diffs = deep_diff(strip(published), strip(rerun))

    csv_published = (TDM12 / "CANDIDATE_REGISTRY.csv").read_bytes()
    csv_rerun = (out_dir / "CANDIDATE_REGISTRY.csv").read_bytes()
    window_published = json.loads((TDM12 / "DATA_WINDOW_REGISTRY.json").read_text(encoding="utf-8"))
    window_rerun = json.loads((out_dir / "DATA_WINDOW_REGISTRY.json").read_text(encoding="utf-8"))

    historical: dict[str, bool] = {}
    for name in HISTORICAL:
        rel = f"evidence/tdm/wp-tdm-12/{name}"
        code, blob = git(HERE, "cat-file", "blob", f"HEAD:{rel}")
        on_disk = (HERE / rel).read_bytes()
        historical[name] = code == 0 and sha256_bytes(blob) == sha256_bytes(on_disk)

    # The guard: a v1 identity must be refused as comparable to a v2 one.
    guard_cmd = [
        args.python,
        "-c",
        "import json,sys;sys.path.insert(0,'src');"
        "from trading_bot.research.source_fingerprint import read_fingerprint,"
        "assert_comparable,IncompatibleFingerprintScheme;"
        "v1=read_fingerprint({'parameter_hash':'9825f38950c5b975'});"
        "v2=read_fingerprint(json.load(open('evidence/tdm/wp-tdm-14a/.v2row.json')));"
        "assert_comparable(v1,v2);print('COMPARED')",
    ]
    v2_row = {
        "fingerprint_scheme": "v2",
        "source_fingerprint": "9825f38950c5b975" + "0" * 48,
        "source_relpath": "src/x.py",
        "source_commit": "0" * 40,
        "source_blob_oid": "0" * 40,
        "working_tree_clean_verified": True,
    }
    probe_row = HERE / "evidence" / "tdm" / "wp-tdm-14a" / ".v2row.json"
    probe_row.write_text(json.dumps(v2_row), encoding="utf-8")
    guard = subprocess.run(guard_cmd, cwd=HERE, capture_output=True, text=True, check=False)
    probe_row.unlink()
    guard_rejected = guard.returncode != 0 and "IncompatibleFingerprintScheme" in guard.stderr

    result.update(
        {
            "differences": diffs,
            "registry_rows": len(rerun.get("rows", [])),
            "published_rows": len(published.get("rows", [])),
            "csv_identical": csv_published == csv_rerun,
            # ``generated_at_ms`` is per-run bookkeeping; everything else must match.
            "window_registry_equal": strip(window_published) == strip(window_rerun),
            "historical_files_unmodified": historical,
            "v1_v2_comparison_rejected": guard_rejected,
            "guard_command_exit": guard.returncode,
            "guard_stderr": guard.stderr.strip().splitlines()[-1:] if guard.stderr else [],
            "status": "PASS"
            if not diffs
            and csv_published == csv_rerun
            and strip(window_published) == strip(window_rerun)
            and all(historical.values())
            and guard_rejected
            else "FAIL",
        }
    )
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "differences": len(diffs),
                "csv_identical": result["csv_identical"],
                "historical_intact": all(historical.values()),
                "v1_v2_rejected": guard_rejected,
            },
            indent=1,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
