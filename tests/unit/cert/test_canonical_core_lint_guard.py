"""DEBT-OP-001 — permanent canonical-core lint guard.

Operational debt closure (run RUN-OP-001, branch ops/debt-001-canonical-lint)
closed every auto-fixable ruff finding (F401 / I001 / RUF022 / RUF100 / UP045)
plus the full mypy debt on the canonical/shared core surface:

    paper/kill_switch.py           (canonical kill switch, runtime-consumed)
    paper/reconciliation.py        (canonical startup reconciliation)
    paper/expectations.py          (paper-orchestrator expectations)
    paper/validation.py            (paper trade validation)
    paper/startup_recovery.py      (startup position recovery)
    domain/events/__init__.py      (domain event exports)
    domain/events/journal.py       (event journal types)
    storage/event_store.py         (hash-chained event store)

This guard FAILS CLOSED if ruff is available and any finding appears whose
code is not in the documented residual set for that file.  The residual set
is deliberately limited to behavior-preserving-judgment classes:

    UP042 — (str, Enum) -> StrEnum conversion (changes ``str(member)`` repr)
    SIM102 — nested-if flattening (structural, left untouched in validation.py)

If ruff is unavailable the test SKIPS (environment gate), mirroring the
honesty contract of ``test_cert_env_isolation``: absence of the tool is
reported, never silently converted into PASS.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

CANONICAL_FILES: tuple[str, ...] = (
    "src/trading_bot/paper/kill_switch.py",
    "src/trading_bot/paper/reconciliation.py",
    "src/trading_bot/paper/expectations.py",
    "src/trading_bot/paper/validation.py",
    "src/trading_bot/paper/startup_recovery.py",
    "src/trading_bot/domain/events/__init__.py",
    "src/trading_bot/domain/events/journal.py",
    "src/trading_bot/storage/event_store.py",
)

# Documented residuals per file — anything else FAILS the guard.
DOCUMENTED_RESIDUALS: dict[str, set[str]] = {
    "src/trading_bot/domain/events/journal.py": {"UP042"},
    "src/trading_bot/paper/startup_recovery.py": {"UP042"},
    "src/trading_bot/paper/validation.py": {"SIM102"},
}


def _ruff() -> str | None:
    """Locate ruff: PATH first, then alongside the running interpreter."""
    found = shutil.which("ruff")
    if found:
        return found
    exe = Path(sys.executable).with_name(
        "ruff.exe" if sys.platform == "win32" else "ruff"
    )
    return str(exe) if exe.is_file() else None


@pytest.mark.skipif(
    _ruff() is None,
    reason="ruff not available in this environment (environment gate, not PASS)",
)
def test_canonical_core_has_no_unexpected_ruff_findings() -> None:
    """Canonical core surface must stay clean outside the documented residuals."""
    ruff = _ruff()
    assert ruff is not None
    proc = subprocess.run(
        [ruff, "check", "--output-format", "json", "--no-cache", *CANONICAL_FILES],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):  # ruff returns 1 when findings exist
        pytest.fail(f"ruff failed to run: rc={proc.returncode}\n{proc.stderr}")

    findings: list[str] = []
    for entry in json.loads(proc.stdout or "[]"):
        rel = Path(entry["filename"]).relative_to(REPO).as_posix()
        code = entry["code"]
        if code not in DOCUMENTED_RESIDUALS.get(rel, set()):
            findings.append(
                f"{rel}:{entry['location']['row']}:{entry['location']['column']} {code}"
            )

    assert not findings, (
        "Canonical core regressed beyond documented residuals "
        "(DEBT-OP-001):\n" + "\n".join(findings)
    )
