"""ADVERSARIAL VERIFICATION of the COST-BARRIER DRIFT GATE (WP-7D).

The gate claims that a published number which stops reproducing is visible, that
a cited input which changed is content drift, and that a check-only run never
becomes a full certification. Those are claims about an adversary, so they are
tested the way an adversary would: by mutating isolated copies of the artefacts,
the inputs, the producers and the CI wiring, and driving the gate against them.

Design rules kept from the rest of the lane:

* every mutation happens inside a throwaway sandbox built from the real files;
  the published artefacts and the real inputs are never touched (the sandbox has
  its own copies, and the gate is run with the sandbox as its root);
* detection is decided by the gate's own published state, not by this file's
  opinion of what it should have said: a mutation that leaves the tree green is
  recorded as EVADED, named, and reported - never smoothed over;
* the positive controls (line-ending-only differences, hostile environment
  variables) are held to the opposite expectation, so a gate that flagged
  everything would fail just as loudly;
* the same harness can be pointed at another revision of the gate
  (``--gate-source``), which is how the pre-hardening behaviour was measured
  rather than asserted. Both vocabularies are understood: the six-state contract
  added in WP-7 and the older PASS/PASS_WITH_ADVISORIES/FAIL, because the point
  of the baseline is to run the *old* code.

Read-only with respect to the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]

GATE = "scripts/cost_barrier_gate.py"
BUILDER = "scripts/cost_barrier_explorer.py"
VERIFIER = "scripts/cost_barrier_verify.py"
EXPLORER = "data/recovery/COST_BARRIER_EXPLORER.json"
VERIFICATION = "data/recovery/COST_BARRIER_VERIFICATION.json"
AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
LEDGER = "config/strategy_admission.json"
COST_V3 = "docs/COST_MODEL_V3.json"
COST_MODEL_MODULE = "src/trading_bot/research/microstructure/cost_model_v3.py"
MARKET_HORIZON = "reports/strategy-baseline/COST_BARRIER.json"
PRODUCER_PINS = "data/recovery/wp7/evidence/PRODUCER_PINS.json"
EVIDENCE_INPUT = "data/recovery/wp7/evidence/COST_BARRIER.json"
WORKFLOW = ".github/workflows/cost-barrier-gate.yml"
CERTIFIER = "scripts/cost_barrier_certify.py"

# The sandbox mirrors the layout the tools expect, so their ROOT resolves to it.
SANDBOX_FILES: tuple[str, ...] = (
    GATE,
    BUILDER,
    VERIFIER,
    "scripts/cost_barrier.py",
    "scripts/active_economic_audit.py",
    "scripts/cost_barrier_evidence.py",
    CERTIFIER,
    LEDGER,
    COST_V3,
    EXPLORER,
    VERIFICATION,
    AUDIT,
    MARKET_HORIZON,
    WORKFLOW,
)

# The cost model is imported through its package, and the package __init__ pulls
# in siblings of its own, so the same reachable set the real interpreter sees has
# to be present: copying only the module would make every full reproduction fail
# with an ImportError that has nothing to do with the attack.
SANDBOX_TREES: tuple[str, ...] = ("src/trading_bot",)

MUTATOR = Callable[[Path], None]
EXPLAIN = Callable[[Path], str]

RECONFIRM = ("FULL_REPRODUCTION_PASS", "CHECK_ONLY_PASS", "CHECK_ONLY_WITH_ADVISORIES")
CONTRACT = (
    "FULL_REPRODUCTION_PASS",
    "FULL_REPRODUCTION_FAIL",
    "CHECK_ONLY_PASS",
    "CHECK_ONLY_WITH_ADVISORIES",
    "BLOCKED_MISSING_INPUT",
    "INTEGRITY_FAILURE",
)

# Hostile knobs a reviewer might believe disable the gate. None of them may
# change a decision: that is the whole attack.
HOSTILE_ENV: dict[str, str] = {
    "COST_BARRIER_GATE_SKIP": "1",
    "COST_BARRIER_GATE_DISABLE": "1",
    "COST_BARRIER_GATE_MODE": "check",
    "COST_BARRIER_GATE_STRICT": "0",
    "SKIP_DRIFT_GATE": "1",
    "SKIP_ADVERSARIAL": "1",
    "CI_SKIP_TESTS": "1",
    "PYTEST_ADDOPTS": "--ignore=tests --no-header",
    "PYTHONDONTWRITEBYTECODE": "1",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.exists() else None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def payload_hash(body: dict[str, Any], volatile: tuple[str, ...]) -> str:
    """The artefact's own self-hash rule, reimplemented (never imported)."""
    stripped = {k: v for k, v in body.items() if k not in volatile}
    return hashlib.sha256(
        json.dumps(stripped, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


EXPLORER_VOLATILE = ("generated_at_utc", "payload_sha256", "head", "branch", "sources")
VERIFICATION_VOLATILE = ("generated_at_utc", "head", "subjects")


def rehash_explorer(doc: dict[str, Any]) -> None:
    doc["payload_sha256"] = payload_hash(doc, EXPLORER_VOLATILE)


def tail(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    stripped = text.strip()
    return stripped if len(stripped) <= limit else "..." + stripped[-limit:]


def run_tool(argv: list[str], cwd: Path, env: dict[str, str] | None = None,
             timeout: int = 600) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False, env=merged
    )


# --------------------------------------------------------------------------- #
# sandbox
# --------------------------------------------------------------------------- #


def build_sandbox(dest: Path, gate_source: Path | None) -> list[str]:
    """Copy the minimum tree the gate needs, and report what was unavailable."""
    missing: list[str] = []
    for rel in SANDBOX_FILES:
        source = ROOT / rel
        if not source.exists():
            missing.append(rel)
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for rel in SANDBOX_TREES:
        source = ROOT / rel
        if not source.exists():
            missing.append(rel)
            continue
        shutil.copytree(
            source,
            dest / rel,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            dirs_exist_ok=True,
        )
    evidence_dir = ROOT / "data" / "recovery" / "wp7" / "evidence"
    if evidence_dir.exists():
        for entry in sorted(evidence_dir.rglob("*")):
            if entry.is_file():
                target = dest / entry.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry, target)
    if gate_source is not None:
        target = dest / GATE
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gate_source, target)
    # A sandbox is not a git repository; drop the marker so the gate's
    # `git rev-parse` cannot accidentally resolve the outer checkout through a
    # parent directory.
    return missing


def tree_fingerprint(root: Path) -> str:
    """One digest over every file in a sandbox, so a no-op mutation cannot hide.

    A mutation that happens to equal the published value would leave the tree
    untouched and the gate green, and the run would be recorded as an escape when
    nothing was ever attacked. That is the harness's own way of being vacuous, so
    it is checked rather than assumed.
    """
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append(f"{path.relative_to(root).as_posix()}:{sha256_file(path)}")
    return sha256_bytes("\n".join(entries).encode("utf-8"))


def gate_run(
    sandbox: Path, *, check: bool, report: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    argv = [sys.executable, str(sandbox / GATE), "--report", str(report)]
    if check:
        argv.append("--check")
    argv.append("--json")
    completed = run_tool(argv, cwd=sandbox, env=env)
    document: dict[str, Any] | None = None
    if report.exists():
        try:
            document = read_json(report)
        except json.JSONDecodeError:
            document = None
    if document is None:
        document = {}
    return {
        "mode": "check" if check else "full",
        "exit_code": completed.returncode,
        "status": document.get("status"),
        "vocabulary": "contract" if document.get("status_contract") else "legacy",
        "checks_failed": document.get("checks_failed"),
        "failures": document.get("failures") or [],
        "integrity_failures": document.get("integrity_failures") or [],
        "certification": document.get("certification") or {},
        "stdout": tail(completed.stdout, 400),
        "stderr": tail(completed.stderr, 400),
    }


# --------------------------------------------------------------------------- #
# verdicts
# --------------------------------------------------------------------------- #


def is_flagged(observation: dict[str, Any]) -> bool:
    if observation["vocabulary"] == "contract":
        return observation.get("status") not in RECONFIRM
    return observation.get("exit_code") != 0


def verdict(expect: str, observation: dict[str, Any]) -> bool:
    """Did the run behave the way the contract requires for this expectation?"""
    status = observation.get("status")
    if expect == "FLAGGED":
        return is_flagged(observation)
    if expect == "CLEAN":
        if observation["vocabulary"] == "contract":
            return status == "FULL_REPRODUCTION_PASS" and observation["exit_code"] == 0
        return observation.get("exit_code") == 0
    if expect == "BLOCKED":
        if observation["vocabulary"] == "contract":
            return status == "BLOCKED_MISSING_INPUT"
        return observation.get("exit_code") != 0
    if expect == "PARTIAL":
        if observation["vocabulary"] == "contract":
            return (
                status in ("CHECK_ONLY_PASS", "CHECK_ONLY_WITH_ADVISORIES")
                and not (observation.get("certification") or {}).get(
                    "satisfies_full_certification", False
                )
            )
        return observation.get("exit_code") == 0
    raise ValueError(f"unknown expectation {expect}")


def evidence_of(observation: dict[str, Any]) -> str:
    """The strongest single sentence the gate itself produced about this run."""
    if observation.get("integrity_failures"):
        return str(observation["integrity_failures"][0])[:400]
    if observation.get("failures"):
        return str(observation["failures"][0])[:400]
    if observation.get("status"):
        return f"status {observation['status']} (exit {observation['exit_code']})"
    return str(observation.get("stderr") or observation.get("stdout") or "no output")


# --------------------------------------------------------------------------- #
# mutations
# --------------------------------------------------------------------------- #


def moved_cell(sandbox: Path) -> tuple[dict[str, Any], float, float]:
    """Move the first cell's published gross edge by +5 bps, whatever it was.

    Written as a delta rather than a literal on purpose: a literal that happens to
    equal the published value is not an attack, and this harness must not report
    one as detected.
    """
    path = sandbox / EXPLORER
    doc = read_json(path)
    before = float(doc["cells"][0]["zero_cost_gross_bps"])
    after = before + 5.0
    doc["cells"][0]["zero_cost_gross_bps"] = after
    return doc, before, after


def mutate_number_no_rehash(sandbox: Path) -> None:
    doc, _before, _after = moved_cell(sandbox)
    write_json(sandbox / EXPLORER, doc)


def number_no_rehash_detail(sandbox: Path) -> str:
    doc = read_json(sandbox / EXPLORER)
    return (
        f"cells[0].zero_cost_gross_bps moved to {doc['cells'][0]['zero_cost_gross_bps']}; "
        "payload_sha256 left as published"
    )


def mutate_number_honest_rehash(sandbox: Path) -> None:
    doc, _before, _after = moved_cell(sandbox)
    rehash_explorer(doc)
    write_json(sandbox / EXPLORER, doc)


def number_honest_detail(sandbox: Path) -> str:
    doc = read_json(sandbox / EXPLORER)
    return (
        f"cells[0].zero_cost_gross_bps moved to {doc['cells'][0]['zero_cost_gross_bps']} "
        "(+5 bps) with payload_sha256 recomputed honestly"
    )


def mutate_market_horizon_row(sandbox: Path) -> None:
    path = sandbox / EXPLORER
    doc = read_json(path)
    rows = doc["horizon"]["market_horizon"]["rows"]
    hit = next(row for row in rows if row["timeframe"] == "1h" and row["asset"] == "SOL")
    hit["hours_to_BASE"] = 99.0
    rehash_explorer(doc)
    write_json(path, doc)


def market_horizon_detail(sandbox: Path) -> str:
    return (
        "horizon.market_horizon.rows[1h/SOL].hours_to_BASE -> 99.0 with payload_sha256 "
        "recomputed honestly (the independent verifier never reads that source)"
    )


def mutate_cost_model(sandbox: Path) -> None:
    path = sandbox / COST_MODEL_MODULE
    text = path.read_text(encoding="utf-8")
    assert "5.0" in text, "the cost model no longer carries the expected fee literal"
    path.write_text(text.replace("5.0", "4.5", 1), encoding="utf-8")


def cost_model_detail(sandbox: Path) -> str:
    return "one fee literal in the executable cost model changed (5.0 -> 4.5)"


def mutate_ledger(sandbox: Path) -> None:
    path = sandbox / LEDGER
    doc = read_json(path)
    entries = doc.get("strategies") or doc.get("entries") or {}
    key = sorted(entries)[0]
    entries[key]["admitted_for_paper"] = True
    write_json(path, doc)


def ledger_detail(sandbox: Path) -> str:
    return "the first admission-ledger entry is marked admitted_for_paper"


def substitute_foreign_pin(sandbox: Path) -> None:
    path = sandbox / EXPLORER
    doc = read_json(path)
    audit_pin = next(r["sha256"] for r in doc["sources"] if r["path"] == AUDIT)
    for row in doc["sources"]:
        if row["path"] == LEDGER:
            row["sha256"] = audit_pin
    rehash_explorer(doc)
    write_json(path, doc)


def foreign_pin_detail(sandbox: Path) -> str:
    return (
        "the ledger's pin is replaced by a genuine digest belonging to another file "
        "(the WP-3 audit) - valid hash, wrong artefact"
    )


def remove_required_input(sandbox: Path) -> None:
    # On a checkout that never materialized the input the file is already gone,
    # and unlinking it would raise instead of measuring anything. Deleting what
    # is there is the mutation; whether it was there is the substrate's business.
    path = sandbox / MARKET_HORIZON
    if path.exists():
        path.unlink()


def remove_input_detail(sandbox: Path) -> str:
    return (
        f"{MARKET_HORIZON} removed: the gitignored input the reproduction needs is deleted, "
        "so a full reproduction must become impossible"
    )


def mutate_unpinned_producer(sandbox: Path) -> None:
    path = sandbox / "scripts/cost_barrier.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"BASE": 12.0', '"BASE": 11.0', 1), encoding="utf-8")


def unpinned_producer_detail(sandbox: Path) -> str:
    return (
        "scripts/cost_barrier.py (the market-horizon producer) edited: the BASE line "
        "12.0 -> 11.0. No published artefact changes, so nothing but a producer pin can see it"
    )


def mutate_builder_and_result(sandbox: Path) -> None:
    """Edit the builder, then let it regenerate its own artefact and attestation."""
    path = sandbox / BUILDER
    text = path.read_text(encoding="utf-8")
    assert "OPS_PER_DAY = 3.0" in text, "the builder no longer carries the expected literal"
    path.write_text(text.replace("OPS_PER_DAY = 3.0", "OPS_PER_DAY = 4.0", 1), encoding="utf-8")
    built = run_tool(
        [sys.executable, str(sandbox / BUILDER), "--out-dir", str(sandbox / "data" / "recovery")],
        cwd=sandbox,
    )
    assert built.returncode == 0, (
        f"the mutated builder failed: stdout={built.stdout[-300:]} stderr={built.stderr[-500:]}"
    )
    verified = run_tool(
        [
            sys.executable, str(sandbox / VERIFIER),
            "--explorer", str(sandbox / EXPLORER),
            "--out", str(sandbox / VERIFICATION),
        ],
        cwd=sandbox,
    )
    assert verified.returncode == 0, (
        "the verifier refused the regenerated artefact: "
        f"stdout={verified.stdout[-300:]} stderr={verified.stderr[-500:]}"
    )


def builder_and_result_detail(sandbox: Path) -> str:
    return (
        "the builder is edited (OPS_PER_DAY 3.0 -> 4.0) and then re-run so the published "
        "artefact and its verification document are regenerated from it: builder and result "
        "agree with each other, so only a producer pin can object"
    )


def mutate_published_verdict(sandbox: Path) -> None:
    path = sandbox / EXPLORER
    doc = read_json(path)
    section = doc["horizon"]["model_horizon"]
    assert section.get("verdict") == "HORIZON_INVARIANT_AT_ZERO_FUNDING", (
        "the artefact no longer publishes the horizon verdict this attack targets"
    )
    section["verdict"] = "HORIZON_DEPENDENT_AT_ZERO_FUNDING"
    rehash_explorer(doc)
    write_json(path, doc)


def published_verdict_detail(sandbox: Path) -> str:
    return (
        "the published horizon verdict is rewritten from HORIZON_INVARIANT_AT_ZERO_FUNDING to "
        "HORIZON_DEPENDENT_AT_ZERO_FUNDING with the self-hash recomputed"
    )


def doctor_negative_controls(sandbox: Path) -> None:
    """Rewrite the verifier's own control ledger so it looks like it detected everything."""
    explorer = read_json(sandbox / EXPLORER)
    path = sandbox / VERIFICATION
    doc = read_json(path)
    explorer_hash = str(explorer["payload_sha256"])
    forged = []
    for index, row in enumerate(doc.get("controls") or []):
        forged.append({
            **row,
            "detected": True,
            "signal": "payload_sha256 "
            + explorer_hash
            + " != recomputed "
            + sha256_bytes(f"forged-{index}".encode())[:64],
        })
    doc["controls"] = forged
    doc["controls_total"] = len(forged)
    doc["controls_missed"] = 0
    doc["false_success"] = 0
    write_json(path, doc)


def doctor_controls_detail(sandbox: Path) -> str:
    return "every negative control in the verification document rewritten to claim detection with a fabricated signal"


def eol_only_change(sandbox: Path) -> None:
    path = sandbox / MARKET_HORIZON
    data = path.read_bytes()
    path.write_bytes(data.replace(b"\r\n", b"\n"))


def eol_only_detail(sandbox: Path) -> str:
    return "the pinned market-horizon input re-encoded with LF line endings only (legitimate checkout difference)"


def content_and_eol_change(sandbox: Path) -> None:
    path = sandbox / MARKET_HORIZON
    doc = read_json(path)
    doc["1h"]["SOL"]["abs_ret_bps_median"] = 27.52
    path.write_bytes(json.dumps(doc, indent=2).replace("\n", "\r\n").encode("utf-8"))
    # ...and then hand it over the other way round, so both changes travel together.
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def content_and_eol_detail(sandbox: Path) -> str:
    return "one published median moved (27.51 -> 27.52) and the file re-encoded to LF in the same edit"


def disable_checks(sandbox: Path) -> None:
    """Every plausible off switch at once, on a tree whose number was already moved."""
    (sandbox / ".cost_barrier_gate.json").write_text(
        json.dumps({"skip": True, "mode": "check", "disable_checks": True}), encoding="utf-8"
    )
    (sandbox / "gate.skip").write_text("skip\n", encoding="utf-8")
    (sandbox / "pytest.ini").write_text("[pytest]\naddopts = --ignore=tests\n", encoding="utf-8")
    # ...and a real defect, so a run that does stand down is visible rather than
    # indistinguishable from a clean tree. The +5 bps move keeps the self-hash
    # honest, so detection has to come from re-derivation, not from arithmetic.
    mutate_number_honest_rehash(sandbox)


def disable_checks_detail(sandbox: Path) -> str:
    return (
        "a config file and a skip marker asking the gate to stand down with each hostile "
        "environment variable set, on a tree whose published number was already moved"
    )


def prune_workflow_filters(sandbox: Path) -> None:
    path = sandbox / WORKFLOW
    text = path.read_text(encoding="utf-8")
    assert COST_MODEL_MODULE in text, "the workflow no longer lists the cost model"
    lines = [line for line in text.splitlines(keepends=True) if COST_MODEL_MODULE not in line]
    path.write_text("".join(lines), encoding="utf-8")


def prune_workflow_detail(sandbox: Path) -> str:
    return (
        f"{COST_MODEL_MODULE} removed from both path filters, so a change to the executable "
        "cost model would no longer activate the workflow that is supposed to catch it"
    )


def relocate_dependency(sandbox: Path) -> None:
    """Move the cost model, rewire every citation, and leave the CI filters behind.

    A competent attacker keeps the tree coherent: the new module is where the
    code now looks for it, the artefact cites the new path with its real digest,
    and the producer manifest is re-pinned. The one thing that cannot be made
    coherent - unless someone also edits the workflow - is that CI no longer
    watches the file the artefacts actually depend on.
    """
    new_rel = "src/trading_bot/research/microstructure/costs/cost_model_v3.py"
    old = sandbox / COST_MODEL_MODULE
    new = sandbox / new_rel
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))
    (new.parent / "__init__.py").write_text("", encoding="utf-8")

    builder = sandbox / BUILDER
    text = builder.read_text(encoding="utf-8")
    text = text.replace(
        "from trading_bot.research.microstructure import cost_model_v3",
        "from trading_bot.research.microstructure.costs import cost_model_v3",
    ).replace(f'COST_MODEL_MODULE = "{COST_MODEL_MODULE}"', f'COST_MODEL_MODULE = "{new_rel}"')
    builder.write_text(text, encoding="utf-8")

    verifier = sandbox / VERIFIER
    verifier.write_text(
        verifier.read_text(encoding="utf-8").replace(
            "from trading_bot.research.microstructure import cost_model_v3",
            "from trading_bot.research.microstructure.costs import cost_model_v3",
        ),
        encoding="utf-8",
    )

    gate = sandbox / GATE
    gate.write_text(
        gate.read_text(encoding="utf-8").replace(f'"{COST_MODEL_MODULE}"', f'"{new_rel}"'),
        encoding="utf-8",
    )

    artifact = sandbox / EXPLORER
    doc = read_json(artifact)
    digest = sha256_file(new)
    for row in doc["sources"]:
        if row["path"] == COST_MODEL_MODULE:
            row["path"] = new_rel
            row["sha256"] = digest
    rehash_explorer(doc)
    write_json(artifact, doc)

    manifest_path = sandbox / PRODUCER_PINS
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        for row in manifest.get("producers") or []:
            if row.get("path") == BUILDER:
                row["sha256"] = sha256_file(builder)
        write_json(manifest_path, manifest)


def relocate_detail(sandbox: Path) -> str:
    return (
        "the executable cost model is moved to "
        "src/trading_bot/research/microstructure/costs/cost_model_v3.py and everything that "
        "cites it is rewired (explorer, verifier, the gate's declared inputs, the artefact's "
        "pin and the producer manifest) - but the workflow's path filters are not"
    )


def partial_run_dressed_as_full(sandbox: Path) -> None:
    """A check-only result is rewritten to claim the state that certifies."""
    path = sandbox / "check_only_report.json"
    gate_run(sandbox, check=True, report=path)
    doc = read_json(path)
    doc["status"] = "FULL_REPRODUCTION_PASS"
    doc["mode"] = "check"
    doc["certification"] = {
        **(doc.get("certification") or {}),
        "satisfies_full_certification": True,
        "is_partial": False,
    }
    write_json(path, doc)


def partial_dressed_detail(sandbox: Path) -> str:
    return (
        "a check-only report (mode=check, no builder run) rewritten to say "
        "FULL_REPRODUCTION_PASS with the certification flag flipped"
    )


# --------------------------------------------------------------------------- #
# the attack matrix
# --------------------------------------------------------------------------- #

ATTACKS: tuple[dict[str, Any], ...] = (
    {
        "attack_id": "A01",
        "title": "alter a published number without touching its hash",
        "requirement": "1",
        "input": EXPLORER,
        "mutate": mutate_number_no_rehash,
        "explain": number_no_rehash_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the artefact's own self-hash no longer recomputes, so no re-run is needed to see it",
    },
    {
        "attack_id": "A02",
        "title": "alter a published number and recompute its hash honestly",
        "requirement": "2",
        "input": EXPLORER,
        "mutate": mutate_number_honest_rehash,
        "explain": number_honest_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "self-consistency alone cannot help: the number has to survive re-derivation",
    },
    {
        "attack_id": "A03",
        "title": "alter the cost model",
        "requirement": "3",
        "input": COST_MODEL_MODULE,
        "mutate": mutate_cost_model,
        "explain": cost_model_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the artefact pins the executable module it evaluated, byte for byte",
    },
    {
        "attack_id": "A04",
        "title": "alter the admission ledger",
        "requirement": "4",
        "input": LEDGER,
        "mutate": mutate_ledger,
        "explain": ledger_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "same pin discipline as the cost model",
    },
    {
        "attack_id": "A05",
        "title": "substitute a pin for a valid one from another version",
        "requirement": "5",
        "input": EXPLORER,
        "mutate": substitute_foreign_pin,
        "explain": foreign_pin_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the pin is compared against the bytes of the file it cites, not against its shape",
    },
    {
        "attack_id": "A06",
        "title": "remove a required input",
        "requirement": "6",
        "input": MARKET_HORIZON,
        "mutate": remove_required_input,
        "explain": remove_input_detail,
        "expect": {"full": "BLOCKED", "check": "PARTIAL"},
        "how": "full mode refuses to claim a reproduction it cannot run; check mode says so and stays partial",
    },
    {
        "attack_id": "A07",
        "title": "alter an unpinned producer",
        "requirement": "7",
        "input": "scripts/cost_barrier.py",
        "mutate": mutate_unpinned_producer,
        "explain": unpinned_producer_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the producer digest manifest is what closes this; without it nothing in the tree changes",
    },
    {
        "attack_id": "A08",
        "title": "modify the builder and a published result together",
        "requirement": "8",
        "input": BUILDER,
        "mutate": mutate_builder_and_result,
        "explain": builder_and_result_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "a coherent lie passes every self-consistency check; the producer pin is the only witness",
    },
    {
        "attack_id": "A09",
        "title": "modify a published verdict",
        "requirement": "9",
        "input": EXPLORER,
        "mutate": mutate_published_verdict,
        "explain": published_verdict_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "verdicts are re-derived from the audit and the cost model by the independent verifier",
    },
    {
        "attack_id": "A10",
        "title": "manipulate the negative-control results",
        "requirement": "10",
        "input": VERIFICATION,
        "mutate": doctor_negative_controls,
        "explain": doctor_controls_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the gate re-runs the verifier, and a control ledger that no longer matches the "
               "fresh one is document drift",
    },
    {
        "attack_id": "A11",
        "title": "introduce a legitimate CRLF/LF difference",
        "requirement": "11",
        "input": MARKET_HORIZON,
        "mutate": eol_only_change,
        "explain": eol_only_detail,
        "expect": {"full": "CLEAN", "check": "PARTIAL"},
        "how": "positive control: a checkout convention is not drift, and must not be reported as one",
    },
    {
        "attack_id": "A12",
        "title": "combine a real content change with an end-of-line change",
        "requirement": "12",
        "input": MARKET_HORIZON,
        "mutate": content_and_eol_change,
        "explain": content_and_eol_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "end-of-line tolerance must not become a laundering service for content",
    },
    {
        "attack_id": "A13",
        "title": "disable the checks through configuration or environment",
        "requirement": "13",
        "input": "environment + config files",
        "mutate": disable_checks,
        "explain": disable_checks_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the tree also carries a moved number, so a run that stands down is visible; the "
               "hostile environment is applied to a mutation that is already flagged",
    },
    {
        "attack_id": "A14",
        "title": "alter dependency paths so CI stops activating",
        "requirement": "14",
        "input": COST_MODEL_MODULE,
        "mutate": relocate_dependency,
        "explain": relocate_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the gate checks that its activation contract still covers every declared input, "
               "and the relocated path is not in the filters",
    },
    {
        "attack_id": "A17",
        "title": "prune the CI path filters instead of the code",
        "requirement": "extra",
        "input": WORKFLOW,
        "mutate": prune_workflow_filters,
        "explain": prune_workflow_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "same activation contract, attacked from the workflow side",
    },
    {
        "attack_id": "A15",
        "title": "make a check-only result satisfy a full gate",
        "requirement": "15",
        "input": "the gate's own report",
        "mutate": partial_run_dressed_as_full,
        "explain": partial_dressed_detail,
        "expect": {"full": "CLEAN", "check": "PARTIAL"},
        "how": "the undressed run is partial by contract; the dressed one is kept as evidence and "
               "handed to the certifier, which must refuse it",
    },
    {
        "attack_id": "A16",
        "title": "alter a derived market-horizon number and recompute the hash honestly",
        "requirement": "extra",
        "input": EXPLORER,
        "mutate": mutate_market_horizon_row,
        "explain": market_horizon_detail,
        "expect": {"full": "FLAGGED", "check": "FLAGGED"},
        "how": "the section the independent verifier never reads is re-derived by the gate from "
               "the pinned source",
    },
)


# --------------------------------------------------------------------------- #
# A13/A14/A15 legs that need more than one gate run
# --------------------------------------------------------------------------- #


def env_invariance_leg(sandbox: Path, mutate: MUTATOR) -> dict[str, Any]:
    """Two-sided invariance: the environment may change neither verdict.

    Side one runs the *clean* sandbox under every hostile knob: a gate that invents
    a failure because it was asked to skip would be as broken as one that hides a
    real one. Side two applies the defect and runs it plain and hostile: the
    verdict must be the same in both, and flagged in both.
    """
    clean_hostile = gate_run(
        sandbox, check=False, report=sandbox / "a13_clean_hostile.json", env=HOSTILE_ENV
    )
    mutate(sandbox)
    plain = gate_run(sandbox, check=False, report=sandbox / "a13_plain.json")
    hostile = gate_run(
        sandbox, check=False, report=sandbox / "a13_hostile.json", env=HOSTILE_ENV
    )
    clean_not_flagged = not is_flagged(clean_hostile)
    flagged = is_flagged(plain) and is_flagged(hostile)
    same_verdict = plain.get("status", plain["exit_code"]) == hostile.get(
        "status", hostile["exit_code"]
    )
    return {
        "leg": "environment_and_config_change_no_verdict_in_either_direction",
        "clean_hostile": {
            "status": clean_hostile.get("status"),
            "exit_code": clean_hostile["exit_code"],
            "flagged": is_flagged(clean_hostile),
        },
        "plain": {"status": plain.get("status"), "exit_code": plain["exit_code"]},
        "hostile": {"status": hostile.get("status"), "exit_code": hostile["exit_code"]},
        "invariant": bool(clean_not_flagged and flagged and same_verdict),
        "evidence": (
            f"clean+hostile {clean_hostile.get('status')}/exit {clean_hostile['exit_code']}; "
            f"defective plain {plain.get('status')}/exit {plain['exit_code']} vs hostile "
            f"{hostile.get('status')}/exit {hostile['exit_code']}"
        ),
    }


def certifier_refusal_leg(sandbox: Path) -> dict[str, Any]:
    """A report that claims full reproduction while having run only --check is refused."""
    forced = sandbox / "a15_forced.json"
    doc = read_json(sandbox / "check_only_report.json")
    doc["status"] = "FULL_REPRODUCTION_PASS"
    doc["mode"] = "check"
    doc["exit_code"] = 0
    doc["certification"] = {
        **(doc.get("certification") or {}),
        "satisfies_full_certification": True,
        "is_partial": False,
    }
    write_json(forced, doc)
    certifier = sandbox / CERTIFIER
    if not certifier.exists():
        return {
            "leg": "the_certifier_refuses_a_partial_run_dressed_as_full",
            "refused": False,
            "evidence": f"{CERTIFIER} is not present in this revision, so the leg could not run",
            "skipped": False,
        }
    sys.path.insert(0, str(sandbox / "scripts"))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("cb_certify_probe", certifier)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        evaluate = cast(Any, module).evaluate
        outcome = evaluate(
            gate_report=doc,
            contract_tests={"exit_code": 1, "command": "not run"},
            adversarial={"escapes": ["A01"], "attacks_evaded": 1},
        )
    except Exception as exc:  # a leg that cannot run must fail the sweep, not vanish
        return {
            "leg": "the_certifier_refuses_a_partial_run_dressed_as_full",
            "refused": False,
            "evidence": f"the certifier could not be interrogated: {exc!r}",
            "skipped": False,
        }
    finally:
        sys.path.pop(0)
    refused = outcome.get("status") != "CERTIFIED" and not outcome.get(
        "satisfies_full_certification", False
    )
    return {
        "leg": "the_certifier_refuses_a_partial_run_dressed_as_full",
        "refused": bool(refused),
        "observed_status": outcome.get("status"),
        "reasons": outcome.get("reasons", [])[:4],
        "evidence": f"certifier verdict {outcome.get('status')} for a mode=check report claiming "
                    f"FULL_REPRODUCTION_PASS: {outcome.get('reasons', [])[:2]}",
        "skipped": False,
    }


# --------------------------------------------------------------------------- #
# the sweep
# --------------------------------------------------------------------------- #


def run_attack(
    attack: dict[str, Any],
    *,
    workdir: Path,
    gate_source: Path | None,
    sandbox_files_missing: list[str],
) -> dict[str, Any]:
    sandbox = workdir / attack["attack_id"]
    sandbox.mkdir(parents=True, exist_ok=True)
    build_sandbox(sandbox, gate_source)

    observations: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    pristine = tree_fingerprint(sandbox)

    if attack["attack_id"] == "A13":
        legs.append(env_invariance_leg(sandbox, attack["mutate"]))
    elif attack["attack_id"] == "A15":
        attack["mutate"](sandbox)
        legs.append(certifier_refusal_leg(sandbox))
    else:
        attack["mutate"](sandbox)

    # A mutation that left the tree exactly as it was is not an attack, and
    # reporting it as detected or escaped would both be wrong.
    mutated = tree_fingerprint(sandbox) != pristine
    detail = attack["explain"](sandbox)

    for mode, expect in attack["expect"].items():
        report = sandbox / f"gate_report_{mode}.json"
        observation = gate_run(sandbox, check=(mode == "check"), report=report)
        observation["expectation"] = expect
        observation["verdict"] = verdict(expect, observation)
        observations.append(observation)
        if attack["attack_id"] == "A15" and mode == "check":
            shutil.copyfile(report, sandbox / "check_only_report.json")

    detected = [row for row in observations if row["verdict"]]
    failed = [row for row in observations if not row["verdict"]]
    return {
        "attack_id": attack["attack_id"],
        "mutation_changed_the_tree": mutated,
        "title": attack["title"],
        "requirement": attack["requirement"],
        "input": attack["input"],
        "mutation": detail,
        "expected": {mode: expect for mode, expect in attack["expect"].items()},
        "observed": [
            {
                "mode": row["mode"],
                "vocabulary": row["vocabulary"],
                "status": row.get("status"),
                "exit_code": row["exit_code"],
                "checks_failed": row.get("checks_failed"),
                "expected": row["expectation"],
                "detected": row["verdict"],
            }
            for row in observations
        ],
        "legs": legs,
        "detected": mutated and not failed,
        "valid_mutation": mutated,
        "detected_in": [row["mode"] for row in detected],
        "missed_in": [row["mode"] for row in failed],
        "how": attack["how"],
        "evidence": "; ".join(
            f"[{row['mode']}] {evidence_of(row)}" for row in observations if row["verdict"]
        ) or "; ".join(f"[{row['mode']}] {evidence_of(row)}" for row in observations),
        "counter_evidence": (
            "; ".join(f"[{row['mode']}] {evidence_of(row)}" for row in failed) or ""
        ),
        "sandbox_missing_files": sandbox_files_missing,
    }


def run_all(
    *,
    workdir: Path,
    gate_source: Path | None,
    gate_label: str,
    only: str | None = None,
    keep: bool = False,
) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    probe = workdir / "_probe"
    probe.mkdir(parents=True, exist_ok=True)
    missing = build_sandbox(probe, gate_source)
    substrate = {
        "path": MARKET_HORIZON,
        # Ask the sandbox, not the declared file list: a name missing from that
        # list would otherwise be reported as a present substrate.
        "present": (probe / MARKET_HORIZON).exists(),
        "why": (
            "the market-horizon input is generated from cached bar datasets and is gitignored "
            "by design, so a clean checkout does not carry it. "
            "`scripts/cost_barrier_evidence.py --materialize` restores it from the "
            "digest-pinned evidence before this suite runs. Without it every "
            "full-reproduction attack degenerates into 'the gate was already blocked', so a "
            "detection rate measured here would be vacuous; the report says NOT_EVALUABLE "
            "rather than counting those degenerations as detection"
        ),
    }
    status = "EVALUATED" if substrate["present"] else "NOT_EVALUABLE"
    attacks = [a for a in ATTACKS if only is None or a["attack_id"] == only]
    rows = [
        run_attack(a, workdir=workdir, gate_source=gate_source, sandbox_files_missing=missing)
        for a in attacks
    ]
    evaded = [row for row in rows if not row["detected"] and row.get("valid_mutation", True)]
    invalid = [row for row in rows if not row.get("valid_mutation", True)]
    legs_failed = [
        f"{row['attack_id']}:{leg['leg']}"
        for row in rows
        for leg in row["legs"]
        if not leg.get("skipped") and not (leg.get("invariant", leg.get("refused")))
    ]
    return {
        "artifact": "COST_BARRIER_ADVERSARIAL_REPORT",
        "work_package": "WP-7D adversarial verification of the cost-barrier drift gate",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "substrate": substrate,
        "gate_under_test": {
            "label": gate_label,
            "path": GATE,
            "sha256": sha256_file(workdir / "_probe" / GATE),
            "revision": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
            ).stdout.strip(),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "attacks": rows,
        "attacks_total": len(rows),
        "attacks_detected": len(rows) - len(evaded) - len(invalid),
        "attacks_evaded": len(evaded),
        "attacks_invalid": len(invalid),
        "invalid_mutations": [
            {
                "attack_id": row["attack_id"],
                "title": row["title"],
                "why": "the mutation left the sandbox byte-identical, so nothing was attacked",
            }
            for row in invalid
        ],
        "escapes": [
            {
                "attack_id": row["attack_id"],
                "title": row["title"],
                "missed_in": row["missed_in"],
                "counter_evidence": row["counter_evidence"],
            }
            for row in evaded
        ],
        "legs_failed": legs_failed,
        "claims": {
            "promotion_claimed": False,
            "rentable_claimed": False,
            "certified_claimed": False,
            "production_ready_claimed": False,
            "authorization_state": "NOT_AUTHORIZED",
            "trades_authorized": 0,
            "false_success": 0,
        },
        "false_success": 0,
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        "# COST_BARRIER_ADVERSARIAL_REPORT",
        "",
        f"- gate under test: **{report['gate_under_test']['label']}** "
        f"(`sha256 {str(report['gate_under_test']['sha256'])[:16]}...`, revision "
        f"`{report['gate_under_test']['revision'][:12]}`)",
        f"- status: **{report.get('status', 'EVALUATED')}** (substrate "
        f"`{report.get('substrate', {}).get('path')}` "
        f"{'present' if report.get('substrate', {}).get('present') else 'ABSENT'})",
        f"- attacks: **{report['attacks_detected']}/{report['attacks_total']} detected**, "
        f"{report['attacks_evaded']} evaded, {report.get('attacks_invalid', 0)} invalid, "
        f"{len(report['legs_failed'])} leg(s) failed",
        f"- generated `{report['generated_at_utc']}` · python `{report['environment']['python']}` "
        f"· `{report['environment']['platform']}`",
        "",
    ]
    if report.get("status") == "NOT_EVALUABLE":
        lines += [
            "> **NOT EVALUABLE.** The substrate this suite attacks is absent from this "
            "checkout, so the counts below are not a detection rate: with no materialized "
            "input, attacks that should force a partial or failed reproduction cannot be "
            "distinguished from a gate that was blocked to begin with. "
            f"{report['substrate']['why']}.",
            "",
        ]
    lines += [
        "Each attack runs against a throwaway sandbox built from the real files; the published "
        "artefacts and inputs are never touched. `DETECTED` means the gate's own published state "
        "flagged the run for that mode; a mutation that leaves the tree green is recorded as an "
        "escape rather than smoothed over.",
        "",
        "| attack | requirement | input | expected | observed | detected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["attacks"]:
        expected = ", ".join(f"{mode}:{exp}" for mode, exp in row["expected"].items())
        observed = ", ".join(
            f"{o['mode']}:{o.get('status') or ('exit ' + str(o['exit_code']))}"
            for o in row["observed"]
        )
        lines.append(
            f"| {row['attack_id']} {row['title']} | {row['requirement']} | `{row['input']}` | "
            f"{expected} | {observed} | {'yes' if row['detected'] else '**NO**'} |"
        )
    lines += ["", "## Detail", ""]
    for row in report["attacks"]:
        lines.append(f"### {row['attack_id']} — {row['title']}")
        lines.append("")
        lines.append(f"- **input**: `{row['input']}`")
        lines.append(f"- **mutation**: {row['mutation']}")
        lines.append(f"- **expected**: {row['expected']}")
        lines.append(
            "- **observed**: "
            + "; ".join(
                f"`{o['mode']}` → `{o.get('status') or 'legacy'}` (exit {o['exit_code']}, "
                f"checks_failed {o.get('checks_failed')})"
                for o in row["observed"]
            )
        )
        lines.append(f"- **detected**: {'yes' if row['detected'] else '**NO**'}")
        lines.append(f"- **evidence**: {row['evidence'] or 'none'}")
        if row["counter_evidence"]:
            lines.append(f"- **counter-evidence (the miss)**: {row['counter_evidence']}")
        for leg in row["legs"]:
            lines.append(f"- **leg `{leg['leg']}`**: {leg['evidence']}")
        lines.append(f"- **why it should work**: {row['how']}")
        lines.append("")
    if report.get("invalid_mutations"):
        lines += ["## Invalid mutations (the harness attacked nothing; fix the attack)", ""]
        for row in report["invalid_mutations"]:
            lines.append(f"- **{row['attack_id']}** {row['title']} — {row['why']}")
        lines.append("")
    if report["escapes"]:
        lines += ["## Escapes (defects to fix before any capability is claimed)", ""]
        for escape in report["escapes"]:
            lines.append(
                f"- **{escape['attack_id']}** {escape['title']} — missed in "
                f"{escape['missed_in']}: {escape['counter_evidence']}"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gate-source", default=None,
                        help="install this file as scripts/cost_barrier_gate.py inside every "
                             "sandbox (used to measure a different revision of the gate)")
    parser.add_argument("--label", default="current working tree",
                        help="how to name the gate revision in the report")
    parser.add_argument("--only", default=None, help="run a single attack id (A01..A16)")
    parser.add_argument("--workdir", default=None,
                        help="keep sandboxes here instead of a temporary directory")
    parser.add_argument("--out", default=None, help="write the JSON report here")
    parser.add_argument("--report", default=None, help="write the Markdown report here")
    parser.add_argument("--json", action="store_true", help="print the JSON report")
    args = parser.parse_args(argv)

    gate_source = Path(args.gate_source).resolve() if args.gate_source else None
    temporary = args.workdir is None
    workdir = Path(tempfile.mkdtemp(prefix="cost_barrier_adversarial_")) if temporary \
        else Path(args.workdir).resolve()
    try:
        report = run_all(
            workdir=workdir,
            gate_source=gate_source,
            gate_label=args.label,
            only=args.only,
        )
    finally:
        if temporary:
            shutil.rmtree(workdir, ignore_errors=True)

    print(
        f"attacks detected {report['attacks_detected']}/{report['attacks_total']}, "
        f"escaped {report['attacks_evaded']}, legs failed {len(report['legs_failed'])}"
    )
    if report.get("status") == "NOT_EVALUABLE":
        print(
            f"  NOT EVALUABLE: {report['substrate']['path']} is absent from the sandbox, so "
            "materialize the evidence before reading any detection rate from this run"
        )
    for escape in report["escapes"]:
        print(f"  ESCAPE {escape['attack_id']} {escape['title']} (missed in {escape['missed_in']})")
    for row in report.get("invalid_mutations") or []:
        print(f"  INVALID {row['attack_id']} {row['title']} - {row['why']}")
    for leg in report["legs_failed"]:
        print(f"  LEG FAILED {leg}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.report:
        Path(args.report).write_text(render(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if (
        report.get("status") == "EVALUATED"
        and report["attacks_evaded"] == 0
        and report["attacks_invalid"] == 0
        and not report["legs_failed"]
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
