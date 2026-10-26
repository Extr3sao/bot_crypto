"""Scratch driver: run the RFC-TDM-013 pipeline, recording each real exit code.

Not part of the evidence: it only exists so RUN_REPORT.json can quote commands
with the exit status they actually returned instead of a remembered one.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".tdm13"
PY = r"C:/Users/GVLLFR0035/Downloads/bot freebuff/.venv/Scripts/python.exe"

STEPS: list[tuple[str, list[str]]] = [
    ("ruff check", [PY, "-m", "ruff", "check", "scripts/tdm13_independent_verify.py",
                    "scripts/tdm13_inputs.py", "scripts/tdm13_replay.py",
                    "scripts/tdm13_negative_controls.py", "scripts/tdm13_report.py",
                    "tests/unit/research/test_tdm13_independent_verify.py"]),
    ("ruff format --check", [PY, "-m", "ruff", "format", "--check",
                             "scripts/tdm13_independent_verify.py", "scripts/tdm13_inputs.py",
                             "scripts/tdm13_replay.py", "scripts/tdm13_negative_controls.py",
                             "scripts/tdm13_report.py",
                             "tests/unit/research/test_tdm13_independent_verify.py"]),
    ("pytest", [PY, "-m", "pytest", "tests/unit/research/test_tdm13_independent_verify.py", "-q"]),
    ("inputs verify", [PY, "scripts/tdm13_inputs.py", "verify"]),
    ("audit-git", [PY, "scripts/tdm13_independent_verify.py", "audit-git"]),
    ("audit-claims", [PY, "scripts/tdm13_independent_verify.py", "audit-claims"]),
    ("negative controls", [PY, "scripts/tdm13_negative_controls.py"]),
    ("verify", [PY, "scripts/tdm13_independent_verify.py", "verify"]),
]


def main() -> int:
    rows = []
    worst = 0
    for name, command in STEPS:
        started = time.time()
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        duration = round(time.time() - started, 1)
        label = " ".join(Path(c).name if c == PY else c for c in command[1:])
        rows.append(
            {
                "step": name,
                "command": label,
                "exit_code": proc.returncode,
                "duration_seconds": duration,
            }
        )
        if name == "pytest":
            (ART / "pytest.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
        print(f"[{proc.returncode}] {name} ({duration}s)")
        for line in tail:
            print(f"      {line}")
        worst = proc.returncode or worst
    (ART / "commands.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
    )
    print("pipeline exit:", worst)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
