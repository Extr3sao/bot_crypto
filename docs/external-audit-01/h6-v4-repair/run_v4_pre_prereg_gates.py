"""Run every pre-prereg builder gate and write durable evidence.

Nothing may be frozen while a pre-prereg gate is red. Each gate runs in a subprocess so a
crash in one cannot mask another, and the report records the python executable, repo
root, git commit and the resolved module path authority for every run.

No economics.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs/external-audit-01" / "h6-v4-repair"
REPORT = OUT / "H6_V4_PRE_PREREG_GATES.json"
SRC = REPO / "src"
NT = "tests/unit/research"

# Shared authoritative data root (READ ONLY; never written to by this run).
DATA_ROOT = os.environ.get(
    "TRADING_AGENTIC_DATA_ROOT", "C:/Users/GVLLFR0035/Downloads/bot freebuff/data"
)

PY = sys.executable


def _commit() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else "UNKNOWN"


def env() -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC)
    e["TRADING_AGENTIC_DATA_ROOT"] = DATA_ROOT
    e["PYTHONHASHSEED"] = "0"
    return e


def run(name: str, cmd: list[str], *, expect_zero: bool = True) -> dict:
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, env=env(), timeout=3000)
    tail = (proc.stdout or "").strip().splitlines()[-25:]
    status = "PASS" if (proc.returncode == 0) == expect_zero else "FAIL"
    return {
        "gate": name,
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "status": status,
        "stdout_tail": tail,
        "stderr_tail": (proc.stderr or "").strip().splitlines()[-12:],
    }


GATES = [
    ("PYTHON_IMPORT_AUTHORITY", [PY, "scripts/verify_python_import_authority.py", "--json"]),
    ("WHITELIST_ATTACKS", [PY, "-m", "pytest", f"{NT}/test_h6_v4_whitelist_authority.py", "-q"]),
    ("HOUR_AGGREGATION", [PY, "-m", "pytest", f"{NT}/test_h6_v4_hour_aggregation.py", "-q"]),
    ("CONTROL_PLANE_CURRENT_AUTHORITY", [PY, "-m", "pytest", f"{NT}/test_h6_v4_authority_binding.py", "-q", "-k", "not pre_freeze"]),
    ("WHITELIST_STATIC_AND_BYPASS", [PY, "-m", "pytest", f"{NT}/test_h6_whitelist_bypass.py", f"{NT}/test_h6_whitelist_static_scan.py", "-q"]),
    ("CONFIRMATION_ISOLATION", [PY, "-m", "pytest", f"{NT}/test_h6_confirmation_isolation.py", f"{NT}/test_confirmation_ledger_lock.py", "-q"]),
    ("SHADOW_ISOLATION", [PY, "-m", "pytest", f"{NT}/test_h6_v3_test_isolation.py", "-q"]),
    ("H5_IMMUTABILITY", [PY, "-m", "pytest", f"{NT}/test_h5_orderflow.py", "-q"]),
    ("PERFORMANCE_CONTAMINATION", [PY, "-m", "pytest", f"{NT}/test_data_admission.py", "-q"]),
    ("V4_SPEC_COMPLETE_AND_SEMANTIC_DIFF", [PY, "docs/external-audit-01/h6-v4-repair/h6_v4_validate.py"]),
    ("DATA_AUTHORITY", [PY, "scripts/verify_h6_data_authority.py", "--data-root", DATA_ROOT]),
    ("DATASET_DETERMINISM", [PY, "scripts/prove_h6_v3_dataset_determinism.py", "--data-root", DATA_ROOT]),
    ("PRICE_AUTHORITY_OVERLAP", [PY, "scripts/verify_price_overlap_v3.py", "--data-root", DATA_ROOT]),
    ("CONSISTENCY_AUDIT", [PY, "scripts/audit_h6_v3_consistency.py"]),
]


def main() -> int:
    results = []
    for name, cmd in GATES:
        try:
            results.append(run(name, cmd))
        except subprocess.TimeoutExpired:
            results.append({"gate": name, "command": " ".join(cmd), "returncode": None,
                            "status": "TIMEOUT", "stdout_tail": [], "stderr_tail": []})
        print(f"{results[-1]['status']:8s} {name}", flush=True)

    failed = [r["gate"] for r in results if r["status"] != "PASS"]
    report = {
        "artifact": "H6_V4_PRE_PREREG_GATES",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python_executable": PY,
        "repo_root": str(REPO),
        "git_commit": _commit(),
        "data_root": DATA_ROOT,
        "module_path_authority": str(SRC),
        "gates": results,
        "gate_count": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "failed_gates": failed,
        "ALL_PRE_PREREG_GATES_PASS": not failed,
        "H6_BACKTESTS": 0,
        "H6_EXECUTIONS": 0,
        "PERFORMANCE_OBSERVED": False,
    }
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"\nALL_PRE_PREREG_GATES_PASS = {report['ALL_PRE_PREREG_GATES_PASS']}")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
