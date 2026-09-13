"""H6 V4 — dashboard repeat 20x and TWO full hermetic runs, with durable evidence.

Both hermetic runs use the V4 worktree code (module authority is recorded in each
result). Every skip is captured so it can be reviewed individually.

No economics.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs/external-audit-01" / "h6-v4-repair"
PY = sys.executable
SRC = REPO / "src"
DASHBOARD_TEST = "tests/unit/paper_dashboard/test_server.py::test_non_get_methods_are_405"


def _commit() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else "UNKNOWN"


def _env(*, hermetic: bool = False) -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC)
    e["PYTHONHASHSEED"] = "0"
    e["TZ"] = "UTC"
    # Re-verification outputs stay in this checkpoint's evidence dir.
    e["H6_EVIDENCE_DIR"] = str(OUT)
    if not hermetic:
        e["TRADING_AGENTIC_DATA_ROOT"] = e.get(
            "TRADING_AGENTIC_DATA_ROOT", "C:/Users/GVLLFR0035/Downloads/bot freebuff/data"
        )
    return e


def _module_authority() -> dict:
    code = (
        "import json,trading_bot,importlib;"
        "mods=['trading_bot.research.h6','trading_bot.research.h6.whitelist',"
        "'trading_bot.research.h6.feature_authority','trading_bot.research.h6.preparation'];"
        "print(json.dumps({'trading_bot':trading_bot.__file__,"
        "'modules':{m:importlib.import_module(m).__file__ for m in mods}}))"
    )
    out = subprocess.run([PY, "-c", code], cwd=str(REPO), capture_output=True, text=True, env=_env())
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": out.stderr.strip()[-500:]}


def dashboard_repeat_20() -> dict:
    runs = []
    started = datetime.now(timezone.utc)
    t0 = time.time()
    for i in range(1, 21):
        s = time.time()
        p = subprocess.run(
            [PY, "-m", "pytest", "-p", "no:cacheprovider", "-q", DASHBOARD_TEST],
            cwd=str(REPO), capture_output=True, text=True, env=_env(),
        )
        tail = (p.stdout or "").strip().splitlines()[-3:]
        runs.append({
            "run": i, "exit_code": p.returncode, "pass": p.returncode == 0,
            "duration_s": round(time.time() - s, 2), "tail": tail,
        })
        print(f"  dashboard run {i:2d}: {'PASS' if p.returncode == 0 else 'FAIL'}", flush=True)
    result = {
        "artifact": "H6_V4_DASHBOARD_REPEAT_20",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "test": DASHBOARD_TEST,
        "commit": _commit(),
        "python_executable": PY,
        "module_authority": _module_authority(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform, "tz": "UTC"},
        "started_utc": started.isoformat(),
        "total_duration_s": round(time.time() - t0, 2),
        "runs": runs,
        "pass_count": sum(1 for r in runs if r["pass"]),
        "DASHBOARD_REPEAT_20": "PASS" if all(r["pass"] for r in runs) else "FAIL",
        "H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False,
    }
    (OUT / "DASHBOARD_REPEAT_20_RESULT.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def hermetic(run_no: int) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.time()
    p = subprocess.run(
        [PY, "scripts/run_regression_hermetic.py", "-p", "no:cacheprovider", "-q"],
        cwd=str(REPO), capture_output=True, text=True, env=_env(hermetic=True),
    )
    stdout = p.stdout or ""
    lines = stdout.strip().splitlines()
    passed = failed = skipped = None
    for line in reversed(lines):
        if " passed" in line or " failed" in line or " error" in line:
            import re

            m_pass = re.search(r"(\d+) passed", line)
            m_fail = re.search(r"(\d+) failed", line)
            m_skip = re.search(r"(\d+) skipped", line)
            if m_pass or m_fail:
                passed = int(m_pass.group(1)) if m_pass else 0
                failed = int(m_fail.group(1)) if m_fail else 0
                skipped = int(m_skip.group(1)) if m_skip else 0
                break
    skip_lines = [ln for ln in lines if ln.startswith("SKIPPED")]
    result = {
        "artifact": f"H6_V4_FULL_HERMETIC_{run_no}",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "proof": f"FULL_HERMETIC_RESULT_{run_no}",
        "command": "python scripts/run_regression_hermetic.py -p no:cacheprovider -q (host env stripped)",
        "commit": _commit(),
        "python_executable": PY,
        "module_authority": _module_authority(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform, "tz": "UTC"},
        "started_utc": started.isoformat(),
        "duration_s": round(time.time() - t0, 2),
        "exit_code": p.returncode,
        "passed": passed, "failed": failed, "skipped": skipped,
        "skips": skip_lines,
        "stdout_tail": lines[-20:],
        "stderr_tail": (p.stderr or "").strip().splitlines()[-10:],
        "status": "PASS" if p.returncode == 0 else "FAIL",
        "H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False,
    }
    (OUT / f"FULL_HERMETIC_RESULT_{run_no}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def main() -> int:
    print("=== DASHBOARD REPEAT 20 ===")
    dash = dashboard_repeat_20()
    print(f"  -> {dash['DASHBOARD_REPEAT_20']} ({dash['pass_count']}/20)")
    print("=== FULL HERMETIC RUN 1 ===")
    h1 = hermetic(1)
    print(f"  -> {h1['status']} passed={h1['passed']} failed={h1['failed']} skipped={h1['skipped']}")
    print("=== FULL HERMETIC RUN 2 ===")
    h2 = hermetic(2)
    print(f"  -> {h2['status']} passed={h2['passed']} failed={h2['failed']} skipped={h2['skipped']}")
    print()
    print("DASHBOARD_REPEAT_20 =", dash["DASHBOARD_REPEAT_20"])
    print("FULL_HERMETIC_1     =", h1["status"])
    print("FULL_HERMETIC_2     =", h2["status"])
    print("SKIPS               =", len(h1["skips"]), len(h2["skips"]))
    ok = dash["DASHBOARD_REPEAT_20"] == "PASS" and h1["status"] == "PASS" and h2["status"] == "PASS"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
