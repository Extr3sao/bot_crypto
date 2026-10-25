"""Audit the repository for launch sites that can open a console window.

The question is not "does this file use subprocess" — almost every evidence
script does, and a human running it from a terminal wants to see it. The question
is **which child can create a new console**, because that is the window the
operator sees when nobody is sitting in front of the machine:

* ``Popen`` leaves a process running beyond the call, so it is held to the
  strictest rule: it must go through :mod:`trading_bot.ops.windowless`;
* ``shell=True`` routes through ``cmd.exe``, which allocates a console of its own;
* a scheduled-task definition whose action is a console interpreter (or
  ``cmd.exe``) draws a window for the whole task, not just a flash.

``subprocess.run`` without the helper is reported as ``MEDIUM``: it is a real
window when the caller has no console, but it is bounded and every site is a
candidate for migration rather than a defect that must be fixed before this
report can be honest about the ones already fixed.

    .venv/Scripts/python.exe scripts/ops_background_audit.py [--json PATH] [--md PATH]

Exit code 0 when no ``HIGH`` finding remains, 1 when one does.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO = Path(__file__).resolve().parents[1]

#: The launchers automation actually starts, named so a regression is a failure
#: rather than a statistic.
AUTOMATION_ENTRYPOINTS: Final[tuple[str, ...]] = (
    "scripts/start_paper_lab.py",
    "scripts/start_paper_trading.py",
    "scripts/autonomous_paper.py",
    "scripts/cap004_supervisor.py",
    "scripts/wp9_runtime_rehearsal.py",
    "scripts/recovery_run_report.py",
    "scripts/windowless.py",
    "src/trading_bot/autonomous/supervisor.py",
)

#: A research probe registers a task to read its definition; it is not the
#: launcher this repository runs, and changing it would change the probe.
RESEARCH_PROBES: Final[tuple[str, ...]] = ("src/trading_bot/research/edge04r/session.py",)

#: The helper itself and this auditor contain the patterns they search for.
SELF_REFERENTIAL: Final[frozenset[str]] = frozenset(
    {"scripts/ops_background_audit.py", "src/trading_bot/ops/windowless.py"}
)

#: A verifier that must not import the runtime it audits (RFC-051 §5) cannot call
#: ``windowless``, so it hides its own children with the two Windows constants directly.
#: The exemption is not a blanket pass: the file must still contain both mechanisms, and
#: if either disappears the audit reports a HIGH finding instead of going quiet.
LOCAL_WINDOW_HIDING: Final[frozenset[str]] = frozenset({"scripts/exp004a_verify.py"})

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)

POPEN = re.compile(r"subprocess\.Popen\(")
RUN = re.compile(r"subprocess\.(?:run|call|check_output|check_call)\(")
SHELL_TRUE = re.compile(r"shell\s*=\s*True")
#: A task action that *is* a shell, as opposed to a template whose caller decides
#: the command (that template is checked through the resolved ``task_command()``).
CMD_EXE = re.compile(
    r"<Command>\s*(?:cmd(?:\.exe)?|powershell(?:\.exe)?|pwsh(?:\.exe)?)\s*</Command>",
    re.IGNORECASE,
)
WINDOWLESS_IMPORT = re.compile(r"from trading_bot\.ops import windowless|import .*windowless")
CREATE_NO_WINDOW = re.compile(r"CREATE_NO_WINDOW")
SW_HIDE = re.compile(r"SW_HIDE")


def hides_its_own_window(text: str) -> bool:
    """Both halves of the mechanism: no new console, and no inherited one shown."""

    return bool(CREATE_NO_WINDOW.search(text)) and bool(SW_HIDE.search(text))


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    code: str
    path: str
    line: int
    detail: str
    remedy: str


def _files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".cmd", ".bat", ".ps1"}:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - a path outside the scanned root
        return str(path)


def scan(root: Path | str = REPO) -> dict[str, Any]:
    """Return every launch site, classified. No network, no processes started."""
    base = Path(root)
    findings: list[Finding] = []
    counts = {"python": 0, "shell": 0, "bat": 0, "ps1": 0, "windowless_users": 0}

    for path in _files(base):
        rel = _relative(base, path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        uses_helper = bool(WINDOWLESS_IMPORT.search(text)) or rel in SELF_REFERENTIAL
        if rel in LOCAL_WINDOW_HIDING:
            if hides_its_own_window(text):
                uses_helper = True
            else:
                findings.append(
                    Finding(
                        "HIGH",
                        "DECLARED_LOCAL_HIDING_MISSING",
                        rel,
                        1,
                        "this file is exempted from the helper because it hides its own "
                        "window, and one of the two mechanisms is gone",
                        "restore CREATE_NO_WINDOW and a STARTUPINFO with SW_HIDE, or use the helper",
                    )
                )
        if uses_helper:
            counts["windowless_users"] += 1

        if path.suffix in {".cmd", ".bat"}:
            counts["bat"] += 1
            if "windowless.py" not in text:
                findings.append(
                    Finding(
                        "MEDIUM",
                        "BAT_WITHOUT_WINDOWLESS",
                        rel,
                        1,
                        "batch launcher starts a console interpreter directly",
                        "route automation through pythonw.exe scripts/windowless.py",
                    )
                )
            continue
        if path.suffix == ".ps1":
            counts["ps1"] += 1
            continue

        counts["python"] += 1
        if rel in SELF_REFERENTIAL:
            continue
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            if SHELL_TRUE.search(line):
                counts["shell"] += 1
                findings.append(
                    Finding(
                        "HIGH",
                        "SHELL_TRUE",
                        rel,
                        number,
                        "shell=True goes through cmd.exe, which allocates a console",
                        "pass an argv list to windowless.run()",
                    )
                )
            if POPEN.search(line) and not uses_helper:
                findings.append(
                    Finding(
                        "HIGH",
                        "POPEN_WITHOUT_WINDOWLESS",
                        rel,
                        number,
                        "Popen without CREATE_NO_WINDOW leaves a child that can draw a console",
                        "use trading_bot.ops.windowless.spawn()",
                    )
                )
            if RUN.search(line) and not uses_helper:
                findings.append(
                    Finding(
                        "MEDIUM",
                        "RUN_WITHOUT_WINDOWLESS",
                        rel,
                        number,
                        "subprocess without window suppression",
                        "use trading_bot.ops.windowless.run()",
                    )
                )

        if rel in RESEARCH_PROBES:
            for number, line in enumerate(lines, start=1):
                if CMD_EXE.search(line):
                    findings.append(
                        Finding(
                            "MEDIUM",
                            "RESEARCH_PROBE_CMD_ACTION",
                            rel,
                            number,
                            "a research probe's task definition uses cmd.exe as an action",
                            "left unchanged on purpose: it is a probe, not a launcher",
                        )
                    )
        elif CMD_EXE.search(text):
            findings.append(
                Finding(
                    "HIGH",
                    "SCHEDULED_TASK_CMD_ACTION",
                    rel,
                    1,
                    "a task definition registered by this repository uses cmd.exe",
                    "register pythonw.exe scripts/windowless.py as the action",
                )
            )

    unique = {(f.severity, f.code, f.path, f.line): f for f in findings}
    ordered = sorted(
        unique.values(), key=lambda f: (f.severity != "HIGH", f.severity, f.path, f.line)
    )
    by_severity: dict[str, int] = {}
    for finding in ordered:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    return {
        "schema_version": "windowless-audit-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "root": str(base),
        "platform": sys.platform,
        "scan_counts": counts,
        "automation_entrypoints": [
            {"path": rel, "present": (base / rel).exists()} for rel in AUTOMATION_ENTRYPOINTS
        ],
        "findings": [asdict(finding) for finding in ordered],
        "by_severity": by_severity,
        "high": by_severity.get("HIGH", 0),
        "verdict": "CLEAN" if by_severity.get("HIGH", 0) == 0 else "HIGH_FINDINGS",
        "scope_note": (
            "HIGH = a child that can outlive the call, a shell hop, or a scheduled-task "
            "action that owns a console for its whole life. MEDIUM = a bounded subprocess "
            "call that still needs the helper when its caller has no console; reported, "
            "not hidden, and not counted as fixed."
        ),
    }


def origin_report() -> dict[str, Any]:
    """Who started this process, and which ancestor owns the console."""
    script = REPO / "scripts" / "ops_window_origin.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        return {"status": "FAILED", "stderr": completed.stderr.strip()[-2000:]}
    try:
        loaded = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"status": "UNPARSEABLE", "error": str(exc)}
    return loaded if isinstance(loaded, dict) else {"status": "UNPARSEABLE"}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# WINDOWLESS EXECUTION AUDIT",
        "",
        f"- generated `{report['generated_at_utc']}` · `{report['platform']}`",
        f"- verdict **{report['verdict']}** · HIGH `{report.get('high', 0)}`",
        f"- scanned: {report['scan_counts']['python']} Python, {report['scan_counts']['bat']} batch, "
        f"{report['scan_counts']['ps1']} PowerShell; {report['scan_counts']['windowless_users']} files "
        "already use the helper",
        "",
        "| severity | count |",
        "| --- | ---: |",
    ]
    for severity in ("HIGH", "MEDIUM", "LOW", "INFO"):
        count = report["by_severity"].get(severity, 0)
        if count:
            lines.append(f"| {severity} | {count} |")
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("None.")
    else:
        lines += ["| severity | code | path:line | detail |", "| --- | --- | --- | --- |"]
        for finding in report["findings"]:
            lines.append(
                f"| {finding['severity']} | `{finding['code']}` | "
                f"`{finding['path']}:{finding['line']}` | {finding['detail']} |"
            )
    lines += ["", "## Scope", "", report["scope_note"], ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument("--origin", action="store_true", help="also record the parent chain")
    args = parser.parse_args(argv)

    report = scan(REPO)
    if args.origin:
        report["origin"] = origin_report()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "high": report["high"],
                "by_severity": report["by_severity"],
            },
            indent=2,
        )
    )
    return 0 if report["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
