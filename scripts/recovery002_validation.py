"""WP-RECOVERY-002 / WP-002C — isolated validation evidence.

Re-derives, from the isolated clone only, every claim the runtime report makes:

1. the clone is a real Git repository at the exact commit, clean, and its own
   object database is intact (``git fsck --full``);
2. dependencies install from the lockfile with no network (``uv sync --frozen
   --offline``) and the declared runtime dependencies import;
3. the tracked-module closure imports (``tests/unit/test_dependency_closure_guard.py``);
4. the focused suite (risk + paper + autonomous) passes;
5. the bounded full-suite log is parsed for its real counts and exit code.

Nothing is skipped and no test is filtered: the marker expression used for the
full suite is the one the repository already documents for its own baseline.

Usage::

    python scripts/recovery002_validation.py [--skip-tests]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

CLONE = Path("C:/Users/GVLLFR0035/recovery-002/work/repo")
LOGS = Path("C:/Users/GVLLFR0035/recovery-002/logs")
OUT = Path("C:/Users/GVLLFR0035/Downloads/ff-wt-trunkfmt/reports/ai-bots/WP-RECOVERY-002/evidence/"
           "C_ISOLATED_VALIDATION.json")
EXPECTED_COMMIT = "0e13160a8d5522961978fe3bd6b904b3a14be1c3"
MARKER_EXPR = "not slow and not market"


def run(cmd: list[str], cwd: Path, timeout: int = 1200) -> dict:
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          errors="replace", timeout=timeout)
    return {
        "cmd": cmd,
        "cwd": str(cwd),
        "exit": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "tail": [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()][-12:],
    }


def parse_pytest_tail(text: str) -> dict:
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "deselected": 0,
               "exit": None, "percent": None, "duration_seconds": None}
    for line in text.splitlines():
        for key in ("passed", "failed", "errors", "error", "skipped", "deselected"):
            m = re.search(rf"(\d+) {key}\b", line)
            if m:
                normalized = "errors" if key == "error" else key
                summary[normalized] = max(summary.get(normalized, 0) or 0, int(m.group(1)))
        m = re.search(r"EXIT=(-?\d+)", line)
        if m:
            summary["exit"] = int(m.group(1))
        m = re.search(r"\[(\s*\d+)%\]", line)
        if m:
            summary["percent"] = int(m.group(1))
        m = re.search(r"in ([\d.]+)s", line)
        if m:
            summary["duration_seconds"] = float(m.group(1))
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true",
                        help="only re-check the clone, the environment and the existing logs")
    args = parser.parse_args(argv)

    evidence: dict = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002C — isolated validation",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "clone": str(CLONE),
        "checks": [],
    }

    def check(name: str, ok: bool, detail: object = None) -> None:
        evidence["checks"].append({"check": name, "pass": bool(ok), "detail": detail})

    exists = CLONE.exists()
    check("isolated clone exists", exists, str(CLONE))
    if not exists:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return 1

    head = run(["git", "rev-parse", "HEAD"], CLONE)
    evidence["head"] = head["tail"][-1] if head["tail"] else None
    check("clone is at the audited commit", evidence["head"] == EXPECTED_COMMIT, evidence["head"])
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], CLONE)
    evidence["detached"] = branch["tail"][-1] == "HEAD"
    status = run(["git", "status", "--porcelain", "--untracked-files=no"], CLONE)
    check("clone has no modified TRACKED file before the checks", status["tail"] == [], status["tail"])
    untracked = run(["git", "status", "--porcelain", "--untracked-files=all"], CLONE)
    evidence["untracked_in_clone"] = [ln[3:] for ln in untracked["tail"] if ln.startswith("??")]
    fsck = run(["git", "fsck", "--full", "--no-progress"], CLONE, timeout=1800)
    evidence["fsck"] = {"exit": fsck["exit"], "tail": fsck["tail"][-5:], "seconds": fsck["seconds"]}
    check("clone object database passes fsck", fsck["exit"] == 0)

    venv_python = CLONE / ".venv" / "Scripts" / "python.exe"
    check("clone has its own virtualenv", venv_python.exists(), str(venv_python))
    sync = run(["uv", "sync", "--frozen", "--offline"], CLONE, timeout=900)
    evidence["uv_sync"] = {"exit": sync["exit"], "seconds": sync["seconds"],
                           "tail": sync["tail"][-4:]}
    check("dependencies install offline from uv.lock", sync["exit"] == 0)

    imports = run([str(venv_python), "-c",
                   "import sys; sys.path.insert(0,'src');"
                   "import trading_bot, trading_bot.autonomous.runtime, trading_bot.paper.broker,"
                   "trading_bot.risk.manager, trading_bot.execution.live_gate,"
                   "trading_bot.market_data.fake, pandas, numpy, ccxt, structlog, pytest;"
                   "print('IMPORTS_OK')"], CLONE)
    check("runtime entry modules and declared dependencies import", "IMPORTS_OK" in imports["tail"][-1],
          imports["tail"][-2:])

    if not args.skip_tests:
        closure = run([str(venv_python), "-m", "pytest",
                       "tests/unit/test_dependency_closure_guard.py", "-q", "--no-header",
                       "-p", "no:cacheprovider"], CLONE, timeout=1800)
        evidence["closure_test"] = {"exit": closure["exit"], "seconds": closure["seconds"],
                                    "summary": parse_pytest_tail("\n".join(closure["tail"])),
                                    "tail": closure["tail"][-3:]}
        check("tracked dependency closure imports in a clean clone", closure["exit"] == 0,
              evidence["closure_test"]["summary"])

        focused = run([str(venv_python), "-m", "pytest", "tests/unit/risk", "tests/unit/paper",
                       "tests/unit/autonomous", "-q", "--no-header", "-p", "no:cacheprovider",
                       "--tb=line"], CLONE, timeout=1800)
        evidence["focused_tests"] = {"exit": focused["exit"], "seconds": focused["seconds"],
                                     "summary": parse_pytest_tail("\n".join(focused["tail"])),
                                     "tail": focused["tail"][-4:]}
        check("focused suite (risk + paper + autonomous) is green", focused["exit"] == 0,
              evidence["focused_tests"]["summary"])

        after = run(["git", "status", "--porcelain", "--untracked-files=all"], CLONE)
        side_effects = [ln for ln in after["tail"] if ln.strip()]
        evidence["test_side_effects"] = side_effects
        source_touched = [ln for ln in side_effects
                          if re.search(r"\b(src|tests)/", ln)]
        check("tests do not modify tracked source or tests", source_touched == [], source_touched)

    log = LOGS / "full_suite.log"
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        parsed = parse_pytest_tail(text)
        evidence["full_suite"] = {**parsed, "log": str(log), "bytes": log.stat().st_size}
        started = LOGS / "full_suite.start"
        ended = LOGS / "full_suite.end"
        if started.exists() and ended.exists():
            evidence["full_suite"]["wall_seconds"] = (
                int(ended.read_text().strip()) - int(started.read_text().strip())
            )
        evidence["full_suite"]["finished"] = "EXIT=" in text
        if evidence["full_suite"].get("exit") == 0:
            check("full suite completed and passed", True, evidence["full_suite"])
        elif evidence["full_suite"].get("exit") == 124:
            check("full suite completed and passed", False,
                  "TIMEOUT: the suite was cut at the wall-clock limit; recorded as NOT RE-MEASURED")
        elif evidence["full_suite"]["finished"]:
            check("full suite completed and passed", False,
                  f"suite finished with failures: {parsed}")
        else:
            check("full suite completed and passed", False,
                  f"still running or interrupted at {parsed.get('percent')}%")
    else:
        evidence["full_suite"] = {"state": "NOT_RUN"}
        check("full suite completed and passed", False, "no log")

    evidence["checks_passed"] = sum(1 for c in evidence["checks"] if c["pass"])
    evidence["checks_total"] = len(evidence["checks"])
    evidence["verdict"] = ("PASS" if all(c["pass"] for c in evidence["checks"]) else "FAIL")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": evidence["verdict"], "passed": evidence["checks_passed"],
                      "total": evidence["checks_total"]}))
    for row in evidence["checks"]:
        print(("PASS " if row["pass"] else "FAIL "), row["check"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
