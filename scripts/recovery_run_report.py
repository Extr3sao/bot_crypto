"""RUN_REPORT generator for POST RFC-049 / ACTIVE RECOVERY.

Re-runs the work package's own commands, captures the real exit codes, hashes every
artefact it produces and writes ``data/recovery/RUN_REPORT.{json,md}``. Nothing is
asserted about a command that was not actually executed: a command that fails is
recorded as failed with its exit code, and the report is still written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "recovery"

COMMANDS: list[dict[str, str]] = [
    {"step": "campaign state view (WP-2)", "command": ".venv/Scripts/python.exe scripts/campaign_state_view.py"},
    {"step": "state view determinism", "command": ".venv/Scripts/python.exe scripts/campaign_state_view.py --check"},
    {"step": "ACTIVE economic audit (WP-3)", "command": ".venv/Scripts/python.exe scripts/active_economic_audit.py"},
    {"step": "audit determinism", "command": ".venv/Scripts/python.exe scripts/active_economic_audit.py --check"},
    {"step": "independent verification", "command": ".venv/Scripts/python.exe scripts/recovery_verify.py"},
    {"step": "new contract tests", "command": ".venv/Scripts/python.exe -m pytest tests/unit/research/test_active_recovery_wp.py -q"},
    {"step": "research suite (regression)", "command": ".venv/Scripts/python.exe -m pytest tests/unit/research -q"},
]

ARTIFACTS = [
    "data/recovery/CAMPAIGN_STATE_VIEW.json",
    "data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.md",
    "data/recovery/ACTIVE_RECOVERY_ROADMAP.md",
    "data/recovery/RFC049_POST_CLOSURE_REPORT.md",
    "data/recovery/INDEPENDENT_VERIFICATION.json",
    "data/recovery/FINAL_REPORT.md",
    "scripts/campaign_state_view.py",
    "scripts/active_economic_audit.py",
    "scripts/recovery_verify.py",
    "tests/unit/research/test_active_recovery_wp.py",
]


def sha256(rel: str) -> str | None:
    path = ROOT / rel
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def run(command: str) -> dict[str, Any]:
    """Run one documented command.

    The report records the canonical repo command (``.venv/Scripts/python.exe ...``),
    but it is executed through this interpreter's own absolute path because the shell
    on Windows does not resolve the forward-slash venv prefix.
    """
    executable = f'"{sys.executable}"'
    runnable = command.replace(".venv/Scripts/python.exe", executable, 1)
    completed = subprocess.run(runnable, cwd=ROOT, shell=True, capture_output=True, text=True)
    tail = "\n".join((completed.stdout or "").strip().splitlines()[-6:])
    if completed.returncode != 0 and not tail:
        tail = "\n".join((completed.stderr or "").strip().splitlines()[-6:])
    return {
        "command": command,
        "exit_code": completed.returncode,
        "result": "PASS" if completed.returncode == 0 else "FAIL",
        "output_tail": tail,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="re-run the commands before writing the report")
    args = parser.parse_args()

    placeholder = [{**entry, "exit_code": None, "result": "NOT_EXECUTED", "output_tail": "",
                    "executed": False} for entry in COMMANDS]

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    def assemble(steps: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "artifact": "ACTIVE_RECOVERY_RUN_REPORT",
            "work_package": "POST RFC-049 / ACTIVE RECOVERY (WP-1..WP-5)",
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head": head,
            "branch": branch,
            "mode": "OFFLINE — no keys, no orders, no capital, no live path; only read-only audits and tests",
            "wc1_commit": {
                "commit": "108c44d",
                "subject": "Close RFC-049 Discovery 2 and retire the sealed OOS opening unused",
                "files": 24,
                "scope": "this lane's RFC-049 closure artefacts only",
                "excluded_lanes": [
                    "data/st6/* (forward-regime lane)", "evidence/real_decisions/* (paper lane)",
                    "docs/source_registry.md", "root RUN_REPORT.json|md", "root FINAL_REPORT.md",
                    "scripts/cap004c_verify.py", "scripts/st6_scheduler_witness.py",
                ],
            },
            "steps": steps,
            "artifacts": [{"path": rel, "exists": (ROOT / rel).exists(), "sha256": sha256(rel)} for rel in ARTIFACTS],
            "checks_failed": sum(1 for step in steps if step["result"] == "FAIL"),
            "notes": [
                "a command not executed in this invocation is reported as NOT_EXECUTED, never as passing",
                "the research suite is a regression run over tests/unit/research; its count is in the output tail",
                "the report is written once before the commands run and rewritten with their real exit codes, so the "
                "verification step can see a complete deliverable set",
            ],
        }

    # write once now: the verification step inside COMMANDS requires the deliverable set to exist
    OUT.mkdir(parents=True, exist_ok=True)
    render(assemble(placeholder))

    steps: list[dict[str, Any]] = []
    if args.execute:
        for entry in COMMANDS:
            result = run(entry["command"])
            steps.append({**entry, **result, "executed": True})
            render(assemble(steps))          # progressive, so a later crash keeps the earlier results

    payload = assemble(steps or placeholder)
    render(payload)

    print(json.dumps({"steps": len(payload["steps"]),
                      "executed": sum(1 for s in payload["steps"] if s["executed"]),
                      "checks_failed": payload["checks_failed"]}, indent=2))
    return 1 if payload["checks_failed"] else 0


def render(payload: dict[str, Any]) -> None:
    (OUT / "RUN_REPORT.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    steps = payload["steps"]
    lines: list[str] = [
        "# RUN REPORT — POST RFC-049 / ACTIVE RECOVERY",
        "",
        f"- generated `{payload['generated_at_utc']}` · head `{payload['head'][:12]}` · branch `{payload['branch']}`",
        f"- mode: {payload['mode']}",
        f"- closure commit (WP-1): `{payload['wc1_commit']['commit']}` — {payload['wc1_commit']['subject']} "
        f"({payload['wc1_commit']['files']} files, this lane only)",
        "",
        "## Commands",
        "",
        "| step | command | exit | result |",
        "| --- | --- | ---: | --- |",
    ]
    for step in steps:
        lines.append(f"| {step['step']} | `{step['command']}` | {step['exit_code']} | **{step['result']}** |")
    lines += ["", "## Artefacts", "", "| path | exists | sha256 |", "| --- | --- | --- |"]
    for entry in payload["artifacts"]:
        lines.append(f"| `{entry['path']}` | {entry['exists']} | `{str(entry['sha256'])[:16]}` |")
    lines += ["", "## Notes", ""]
    lines += [f"- {note}" for note in payload["notes"]]
    lines.append("")
    (OUT / "RUN_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
