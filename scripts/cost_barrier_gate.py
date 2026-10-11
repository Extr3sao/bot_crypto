"""GOVERNANCE DRIFT GATE for the COST-BARRIER EXPLORER (WP-6) and its verifier.

The explorer's published numbers and the verifier's attestation are only worth
something while they keep reproducing from the inputs that are on disk today.
This gate is the standing check that they do. It:

* declares the inputs the two artefacts depend on - the admission ledger, the
  cost model and its executable module, the WP-3 audit and its producer, the
  market-horizon source, and the builder/verifier themselves;
* compares the declared inputs against the byte pins the explorer itself
  published, tolerating the two checkout conventions (LF/CRLF) so that a
  line-ending-only difference is reported as such and never as content drift;
* re-runs the builder and the verifier into a temporary directory, so the
  published artefacts are never touched, and compares every published number,
  verdict, horizon row and governance flag field by field;
* re-runs the verifier even in ``--check`` mode, so a clean checkout that lacks
  the locally generated market-horizon input still gets an independent
  recomputation of all 120 cost lines, 480 reachability sets and 24 verdicts;
* runs six self-controls against tampered copies, so a vacuous comparison
  cannot pass;
* exits non-zero, naming the exact differing fields, the moment a published
  number stops reproducing.

Modes:

* default - full reproduction. Requires every declared input to be present; a
  missing input is a visible failure, never a silent skip.
* ``--check`` - no builder run (the market-horizon input is gitignored by
  design and absent from a clean checkout). Everything else still runs,
  including the verifier.

Advisories (an input is absent where the mode tolerates it) do not fail the gate
unless ``--strict`` is passed. Content drift of a pinned input is never an
advisory: a cited input whose bytes changed means the artefacts must be
regenerated and re-verified.

Read-only with respect to the repository: writes nothing outside the temporary
directory and the optional ``--report`` path. It grants nothing: no promotion,
rentability or production claim is made or checked for truth here, only for
continued falsehood.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EXPLORER = "data/recovery/COST_BARRIER_EXPLORER.json"
VERIFICATION = "data/recovery/COST_BARRIER_VERIFICATION.json"
BUILDER = "scripts/cost_barrier_explorer.py"
VERIFIER = "scripts/cost_barrier_verify.py"

# (path, role, pinned in the explorer's own sources[])
DECLARED_INPUTS: tuple[tuple[str, str, bool], ...] = (
    (
        "config/strategy_admission.json",
        "admission ledger: the only source of 'may this run PAPER?'",
        True,
    ),
    (
        "src/trading_bot/research/microstructure/cost_model_v3.py",
        "the executable cost model every line is evaluated with",
        True,
    ),
    (
        "docs/COST_MODEL_V3.json",
        "cost-model document: venue scenarios and knowledge classes",
        True,
    ),
    (
        "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
        "WP-3 audit: the 24 cells and their zero-cost gross edge",
        True,
    ),
    (
        "reports/strategy-baseline/COST_BARRIER.json",
        "market-horizon source (generated locally; gitignored by design)",
        True,
    ),
    ("scripts/active_economic_audit.py", "producer of the audit", False),
    ("scripts/cost_barrier.py", "producer of the market-horizon report", False),
    (BUILDER, "builder of the explorer artefact", False),
    (VERIFIER, "independent verifier", False),
)

# The pin set is the artefact's own sources[]; it must equal the declared pinned
# paths or the two lists have silently diverged.
PINNED_PATHS: tuple[str, ...] = tuple(rel for rel, _role, pinned in DECLARED_INPUTS if pinned)

VOLATILE_EXPLORER = ("generated_at_utc", "payload_sha256", "head", "branch", "sources")
VOLATILE_VERIFICATION = ("generated_at_utc", "head", "subjects")

PIN_EXACT = "EXACT"
PIN_EOL = "EOL_ONLY"
PIN_DRIFT = "DRIFT"
PIN_NOT_PINNED = "NOT_PINNED"
PIN_ABSENT = "ABSENT"

DIFF_LIMIT = 40


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.exists() else None


def eol_candidates(data: bytes) -> dict[str, str]:
    """The three byte conventions a text file can legitimately arrive in.

    A checkout with ``core.autocrlf`` rewrites line endings but not content, so
    a pinned digest must be compared against the raw bytes, the LF form and the
    CRLF form - otherwise every Linux checkout would look like content drift.
    """
    lf = data.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return {"EXACT": sha256_bytes(data), "LF": sha256_bytes(lf), "CRLF": sha256_bytes(crlf)}


def pin_status(pin: str | None, data: bytes) -> str:
    if pin is None:
        return PIN_NOT_PINNED
    candidates = eol_candidates(data)
    if candidates["EXACT"] == pin:
        return PIN_EXACT
    if candidates["LF"] == pin or candidates["CRLF"] == pin:
        return PIN_EOL
    return PIN_DRIFT


def payload_hash(body: dict[str, Any], volatile: tuple[str, ...] = VOLATILE_EXPLORER) -> str:
    """Replicate the explorer's body hash without importing the builder.

    The gate must be able to say what the artefact claims its identity is; if it
    imported the builder to compute that, a broken builder would be its own
    witness.
    """
    stripped = {k: v for k, v in body.items() if k not in volatile}
    return hashlib.sha256(
        json.dumps(stripped, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def brief(value: Any, limit: int = 90) -> str:
    text = repr(value) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 3] + "..."


def diff_json(
    fresh: Any,
    committed: Any,
    exclude: tuple[str, ...] = (),
    path: str = "",
    out: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Field-level difference between a fresh document and the published one."""
    if out is None:
        out = []
    if len(out) >= DIFF_LIMIT:
        return out
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for key in sorted(set(fresh) | set(committed)):
            if path == "" and key in exclude:
                continue
            sub = f"{path}.{key}" if path else key
            if key not in fresh:
                out.append({"path": sub, "committed": brief(committed[key]), "fresh": "MISSING"})
            elif key not in committed:
                out.append({"path": sub, "committed": "MISSING", "fresh": brief(fresh[key])})
            else:
                diff_json(fresh[key], committed[key], exclude, sub, out)
    elif isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            out.append({
                "path": path,
                "committed": f"{len(committed)} entries",
                "fresh": f"{len(fresh)} entries",
            })
        else:
            for index, (a, b) in enumerate(zip(fresh, committed, strict=True)):
                diff_json(a, b, exclude, f"{path}[{index}]", out)
    elif fresh != committed:
        out.append({"path": path, "committed": brief(committed), "fresh": brief(fresh)})
    return out


def describe(differences: list[dict[str, Any]], limit: int = 5) -> str:
    if not differences:
        return "no differences"
    head = "; ".join(
        f"{row['path']}: {row['committed']} -> {row['fresh']}" for row in differences[:limit]
    )
    if len(differences) > limit:
        head += f"; (+{len(differences) - limit} more)"
    return head


def run_tool(argv: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )


def tail(text: str | None, limit: int = 400) -> str:
    if not text:
        return ""
    stripped = text.strip()
    return stripped if len(stripped) <= limit else "..." + stripped[-limit:]


# --------------------------------------------------------------------------- #
# structural and governance checks on the published documents
# --------------------------------------------------------------------------- #


def explorer_structural_failures(explorer: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    body = {k: v for k, v in explorer.items() if k not in VOLATILE_EXPLORER}
    recomputed = payload_hash(body)
    if explorer.get("payload_sha256") != recomputed:
        bad.append(
            f"payload_sha256 {explorer.get('payload_sha256')} != recomputed {recomputed}"
        )
    checks = explorer.get("checks") or []
    failed = [row for row in checks if row.get("result") != "PASS"]
    if explorer.get("checks_failed") != len(failed):
        bad.append(
            f"checks_failed {explorer.get('checks_failed')} does not match the check list "
            f"({len(failed)} non-PASS)"
        )
    if failed:
        bad.append(f"{len(failed)} artefact check(s) not PASS: {[row.get('check') for row in failed]}")
    return bad


def governance_failures(document: dict[str, Any]) -> list[str]:
    claims = document.get("claims") or {}
    bad: list[str] = []
    for flag in (
        "promotion_claimed",
        "rentable_claimed",
        "certified_claimed",
        "production_ready_claimed",
    ):
        if claims.get(flag) is not False:
            bad.append(f"claim {flag} is not false")
    if claims.get("authorization_state") != "NOT_AUTHORIZED":
        bad.append(f"authorization_state {claims.get('authorization_state')!r} is not NOT_AUTHORIZED")
    if claims.get("trades_authorized") != 0:
        bad.append(f"trades_authorized {claims.get('trades_authorized')!r} is not 0")
    if claims.get("false_success") != 0:
        bad.append(f"false_success {claims.get('false_success')!r} is not 0")
    return bad


def attestation_failures(verification: dict[str, Any], explorer: dict[str, Any]) -> list[str]:
    """Does the verification document actually attest THIS explorer artefact?"""
    bad: list[str] = []
    if verification.get("status") != "PASS":
        bad.append(f"status {verification.get('status')!r} is not PASS")
    if verification.get("checks_failed") != 0:
        bad.append(f"checks_failed {verification.get('checks_failed')!r} is not 0")
    if verification.get("controls_missed") != 0:
        bad.append(f"controls_missed {verification.get('controls_missed')!r} is not 0")
    if verification.get("false_success") != 0:
        bad.append(f"false_success {verification.get('false_success')!r} is not 0")
    if verification.get("builder_imported") is not False:
        bad.append("builder_imported is not false")
    subjects = [Path(str(item)).name for item in verification.get("subjects") or []]
    if Path(EXPLORER).name not in subjects:
        bad.append(f"subjects {verification.get('subjects')} do not name the explorer artefact")
    # Every mutation control reports the pair (stored self-hash, recomputed
    # hash of the mutated copy). The stored side must be exactly the explorer's
    # own payload hash on every control - that is what cross-pins the two
    # documents - and the recomputed side must include the explorer hash once
    # (the control that only replaces the self-hash) plus distinct mutations,
    # which proves the comparison was not a constant.
    signals = json.dumps(verification.get("controls") or [])
    pairs = re.findall(r"payload_sha256 ([0-9a-f]{64}) != recomputed ([0-9a-f]{64})", signals)
    explorer_hash = str(explorer.get("payload_sha256"))
    if len(pairs) < 2:
        bad.append(f"only {len(pairs)} mutation control(s) carry a stored-vs-recomputed hash pair")
        return bad
    body_mutations = [(s, r) for s, r in pairs if s == explorer_hash and r != explorer_hash]
    hash_mutations = [(s, r) for s, r in pairs if s != explorer_hash and r == explorer_hash]
    foreign = [pair for pair in pairs if pair not in body_mutations and pair not in hash_mutations]
    if not body_mutations:
        bad.append("no control demonstrates a body mutation caught by recomputation")
    if not hash_mutations:
        bad.append("no control demonstrates a self-hash tamper caught by recomputation")
    if foreign:
        bad.append(
            f"{len(foreign)} control signal(s) do not form a pair around the committed "
            f"hash {explorer_hash}: {foreign[:2]}"
        )
    if body_mutations and len({r for _, r in body_mutations}) != len(body_mutations):
        bad.append("the body-mutation controls recompute the same hash more than once")
    return bad


# --------------------------------------------------------------------------- #
# declared inputs
# --------------------------------------------------------------------------- #


def input_rows(explorer: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Compare every declared input with the pins the explorer published."""
    pins = {
        str(row.get("path")): row.get("sha256")
        for row in explorer.get("sources") or []
    }
    rows: list[dict[str, Any]] = []
    defects: list[str] = []
    for rel, role, pinned in DECLARED_INPUTS:
        path = ROOT / rel
        present = path.exists()
        data = path.read_bytes() if present else None
        pin = pins.get(rel) if pinned else None
        if pinned and pin is None:
            defects.append(
                f"{rel} is declared pinned but the artefact's sources[] carries no pin for it"
            )
        status = PIN_ABSENT if data is None else pin_status(pin, data)
        rows.append({
            "path": rel,
            "role": role,
            "pinned": pinned,
            "present": present,
            "pin_status": status,
            "pin": pin,
            "sha256_current": sha256_bytes(data) if data is not None else None,
        })
    extra = sorted(set(pins) - set(PINNED_PATHS))
    missing = sorted(set(PINNED_PATHS) - set(pins))
    if extra or missing:
        defects.append(
            f"published pin set and declared pin set diverge: extra={extra} missing={missing}"
        )
    return rows, defects


# --------------------------------------------------------------------------- #
# self-controls (prove the gate is not vacuous)
# --------------------------------------------------------------------------- #


def self_controls(
    explorer: dict[str, Any], verification: dict[str, Any]
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []

    def record(name: str, detected: bool, signal: str) -> None:
        controls.append({
            "control": name,
            "detected": bool(detected),
            "signal": signal if detected else "MISSED - the gate accepted a corrupted document",
        })

    numbered = deepcopy(explorer)
    numbered["cells"][0]["zero_cost_gross_bps"] += 5.0
    differences = diff_json(numbered, explorer, VOLATILE_EXPLORER)
    record(
        "G1 a published number changed and the self-hash recomputed honestly",
        bool(differences),
        describe(differences, limit=1) if differences else "",
    )

    flagged = deepcopy(explorer)
    flagged["claims"]["rentable_claimed"] = True
    bad = governance_failures(flagged)
    record(
        "G2 a governance flag flipped to a promotion claim",
        bool(bad),
        bad[0] if bad else "",
    )

    weakened = deepcopy(verification)
    weakened["status"] = "FAIL"
    bad = attestation_failures(weakened, explorer)
    record(
        "G3 the verification document's own verdict rewritten to FAIL",
        bool(bad),
        bad[0] if bad else "",
    )

    foreign = deepcopy(verification)
    foreign["controls"][0]["signal"] = "payload_sha256 " + "0" * 64 + " != recomputed " + "1" * 64
    bad = attestation_failures(foreign, explorer)
    record(
        "G4 a mutation signal re-pinned to a foreign artefact hash",
        bool(bad),
        bad[0] if bad else "",
    )

    record(
        "G5 a pinned input's content changed (same input, new bytes)",
        pin_status(sha256_bytes(b"alpha\n"), b"beta\n") == PIN_DRIFT,
        "content drift is classified DRIFT",
    )
    record(
        "G6 a pinned input arriving with the other line-ending convention",
        pin_status(sha256_bytes(b"alpha\r\nbeta\r\n"), b"alpha\nbeta\n") == PIN_EOL,
        "line-ending-only difference is classified EOL_ONLY, not DRIFT",
    )
    return controls


# --------------------------------------------------------------------------- #
# the gate itself
# --------------------------------------------------------------------------- #


def check(result: bool, name: str, detail: str) -> dict[str, Any]:
    return {"check": name, "result": "PASS" if result else "FAIL", "detail": detail}


def decide_status(failures: list[str], advisories: list[str], strict: bool) -> str:
    """A tolerated absence is an advisory; under --strict it is a failure."""
    if failures or (strict and advisories):
        return "FAIL"
    return "PASS_WITH_ADVISORIES" if advisories else "PASS"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    explorer_path = Path(args.explorer)
    verification_path = Path(args.verification)
    if not explorer_path.is_absolute():
        explorer_path = ROOT / explorer_path
    if not verification_path.is_absolute():
        verification_path = ROOT / verification_path

    full = not args.check
    checks: list[dict[str, Any]] = []
    advisories: list[str] = []
    failures: list[str] = []

    if not explorer_path.exists() or not verification_path.exists():
        missing = [str(p) for p in (explorer_path, verification_path) if not p.exists()]
        return {
            "artifact": "COST_BARRIER_DRIFT_GATE",
            "checked_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "full" if full else "check",
            "status": "FAIL",
            "checks": [check(False, "subjects:present", f"missing {missing}")],
            "failures": [f"missing subject(s) {missing}"],
            "advisories": [],
        }

    explorer_doc = read_json(explorer_path)
    verification_doc = read_json(verification_path)

    # --- 1. the published explorer's own integrity ------------------------- #
    structural = explorer_structural_failures(explorer_doc)
    checks.append(check(
        not structural,
        "artifact:explorer_self_hash_and_checks",
        "payload_sha256 recomputes from the stored body and 0 checks failed"
        if not structural
        else "; ".join(structural),
    ))

    # --- 2. governance posture --------------------------------------------- #
    governance = governance_failures(explorer_doc)
    checks.append(check(
        not governance,
        "artifact:explorer_governance_flags_unchanged",
        "promotion/rentable/certified/production_ready false; NOT_AUTHORIZED; 0 trades"
        if not governance
        else "; ".join(governance),
    ))

    # --- 3. the verification attests this explorer ------------------------- #
    attestation = attestation_failures(verification_doc, explorer_doc)
    checks.append(check(
        not attestation,
        "artifact:verification_attests_the_explorer",
        "status PASS, 0 failed checks, 0 missed controls, false_success 0, "
        "signals cross-pinned to the explorer's payload hash"
        if not attestation
        else "; ".join(attestation),
    ))

    # --- 4. declared inputs and their published pins ----------------------- #
    rows, defects = input_rows(explorer_doc)
    present = [row for row in rows if row["present"]]
    absent = [row for row in rows if not row["present"]]
    drifted = [row for row in rows if row["pin_status"] == PIN_DRIFT]
    eol_only = [row for row in rows if row["pin_status"] == PIN_EOL]
    exact = [row for row in rows if row["pin_status"] == PIN_EXACT]

    if absent:
        detail = "absent: " + ", ".join(row["path"] for row in absent)
        if full:
            checks.append(check(False, "inputs:declared_inputs_present", detail))
            failures.append(
                f"full reproduction requires every declared input; {detail}. "
                "Materialize the generated inputs (the market-horizon report is produced "
                "locally from reports/strategy-baseline/data/) and re-run."
            )
        else:
            checks.append(check(
                True,
                "inputs:declared_inputs_present",
                detail + " (tolerated in --check mode: no builder run is attempted)",
            ))
            advisories.append(
                "check mode: the builder was not re-run because "
                + ", ".join(row["path"] for row in absent)
                + " is absent from this checkout; the verifier still recomputes every "
                "published number from the primary sources"
            )
    else:
        checks.append(check(
            True, "inputs:declared_inputs_present", f"{len(rows)}/{len(rows)} declared inputs present"
        ))

    pin_detail = (
        f"{len(present)}/{len(rows)} present; pinned: {len(exact)} exact, {len(eol_only)} "
        f"line-ending-only, {len(drifted)} drifted"
    )
    checks.append(check(
        not drifted and not defects,
        "inputs:published_pins_match_the_declared_sources",
        pin_detail if not drifted and not defects
        else pin_detail + ("; " + "; ".join(
            [f"{row['path']} content drift (pin {str(row['pin'])[:16]}...)" for row in drifted]
            + defects
        )),
    ))
    for row in drifted:
        failures.append(
            f"cited input {row['path']} no longer matches the pin the explorer published "
            f"({str(row['pin'])[:16]}...): the artefact must be regenerated and re-verified"
        )
    for defect in defects:
        failures.append(defect)

    # --- 5. re-run the verifier -------------------------------------------- #
    with tempfile.TemporaryDirectory(prefix="cost_barrier_gate_") as tmp:
        tmp_dir = Path(tmp)
        watched = [explorer_path, verification_path] + [ROOT / row["path"] for row in rows]
        before = {str(path): sha256_file(path) for path in watched}

        verifier_out = tmp_dir / "COST_BARRIER_VERIFICATION.json"
        verifier_target: str | None = None
        fresh_explorer: dict[str, Any] | None = None
        if full:
            builder_out = tmp_dir / "COST_BARRIER_EXPLORER.json"
            built = run_tool([sys.executable, str(ROOT / BUILDER), "--out-dir", str(tmp_dir)])
            if built.returncode != 0:
                checks.append(check(
                    False,
                    "reproduce:builder_exit_zero",
                    f"exit {built.returncode}; stdout: {tail(built.stdout, 200)}; "
                    f"stderr: {tail(built.stderr, 200)}",
                ))
                failures.append(
                    f"the builder failed (exit {built.returncode}); its own checks did not pass, "
                    "so no reproduction claim can be made"
                )
                checks.append(check(
                    False,
                    "reproduce:explorer_rebuilds_identically",
                    "not attempted: the builder did not produce a fresh artefact",
                ))
            else:
                fresh_explorer = read_json(builder_out)
                verifier_target = str(builder_out)
                fresh_hash = payload_hash(fresh_explorer)
                committed_hash = str(explorer_doc.get("payload_sha256"))
                differences = [
                    row for row in diff_json(fresh_explorer, explorer_doc, VOLATILE_EXPLORER)
                    if row["path"] != "payload_sha256"
                ]
                reproduced = fresh_hash == committed_hash and not differences
                checks.append(check(
                    reproduced,
                    "reproduce:explorer_rebuilds_identically",
                    f"payload_sha256 {fresh_hash} matches the published artefact"
                    if reproduced
                    else f"payload_sha256 {fresh_hash} vs published {committed_hash}; "
                         f"{describe(differences)}",
                ))
                if not reproduced:
                    failures.append(
                        "a published number stopped reproducing: " + describe(differences, limit=8)
                    )
        else:
            verifier_target = str(explorer_path)

        if verifier_target is None:
            checks.append(check(
                False,
                "reproduce:verifier_passes",
                "not attempted: the builder did not produce a fresh artefact",
            ))
        else:
            verified = run_tool([
                sys.executable, str(ROOT / VERIFIER),
                "--explorer", verifier_target,
                "--out", str(verifier_out),
                "--json",
            ])
            if verified.returncode != 0 or not verifier_out.exists():
                checks.append(check(
                    False,
                    "reproduce:verifier_passes",
                    f"exit {verified.returncode}; stdout: {tail(verified.stdout, 200)}; "
                    f"stderr: {tail(verified.stderr, 200)}",
                ))
                failures.append(
                    f"the independent verifier failed (exit {verified.returncode}) against "
                    f"{verifier_target}"
                )
            else:
                fresh_verification = read_json(verifier_out)
                subject = fresh_explorer if fresh_explorer is not None else explorer_doc
                fresh_attestation = attestation_failures(fresh_verification, subject)
                checks.append(check(
                    not fresh_attestation,
                    "reproduce:verifier_passes",
                    f"verifier PASS on {Path(verifier_target).name}; "
                    f"{fresh_verification.get('controls_total')} mutation controls, "
                    f"{fresh_verification.get('controls_missed')} missed, "
                    f"false_success {fresh_verification.get('false_success')}"
                    if not fresh_attestation
                    else "; ".join(fresh_attestation),
                ))
                if fresh_attestation:
                    failures.append("the fresh verification did not attest the artefact: "
                                    + "; ".join(fresh_attestation))
                doc_diff = diff_json(
                    fresh_verification, verification_doc, VOLATILE_VERIFICATION
                )
                checks.append(check(
                    not doc_diff,
                    "reproduce:verification_document_unchanged",
                    "the fresh verification document equals the published one"
                    if not doc_diff
                    else describe(doc_diff),
                ))
                if doc_diff:
                    failures.append("the verification document drifted: " + describe(doc_diff, limit=8))

        after = {str(path): sha256_file(path) for path in watched}
        changed = [path for path in before if before[path] != after[path]]
        checks.append(check(
            not changed,
            "read_only:no_published_file_changed",
            "the gate and the tools it drives left every watched file byte-identical"
            if not changed
            else f"changed during the run: {changed}",
        ))
        if changed:
            failures.append(f"the gate modified files it must not touch: {changed}")

    # --- 6. self-controls --------------------------------------------------- #
    controls = self_controls(explorer_doc, verification_doc)
    missed = [row for row in controls if not row["detected"]]
    checks.append(check(
        not missed,
        "controls:self_controls_detect_tampering",
        f"{len(controls)}/{len(controls)} controls detected"
        if not missed
        else f"missed: {[row['control'] for row in missed]}",
    ))
    if missed:
        failures.append(f"the gate's own controls were missed: {[row['control'] for row in missed]}")

    checks_failed = sum(1 for row in checks if row["result"] != "PASS")
    if checks_failed:
        failures.append(f"{checks_failed} check(s) failed")

    report: dict[str, Any] = {
        "artifact": "COST_BARRIER_DRIFT_GATE",
        "work_package": "WP-6 governance follow-on: the explorer and its verifier must keep reproducing",
        "checked_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "branch": subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=False
        ).stdout.strip(),
        "mode": "full" if full else "check",
        "subjects": [str(explorer_path), str(verification_path)],
        "declared_inputs": rows,
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": checks_failed,
        "controls": controls,
        "controls_total": len(controls),
        "controls_missed": len(missed),
        "failures": failures,
        "advisories": advisories,
        "claims": {
            "promotion_claimed": False,
            "rentable_claimed": False,
            "certified_claimed": False,
            "production_ready_claimed": False,
            "authorization_state": "NOT_AUTHORIZED",
            "trades_authorized": 0,
            "false_success": 0,
        },
    }
    report["status"] = decide_status(failures, advisories, args.strict)
    report["gate_sha256"] = sha256_file(Path(__file__))
    return report


def render(report: dict[str, Any]) -> str:
    total = int(report.get("checks_total", 0))
    failed = int(report.get("checks_failed", 0))
    controls = int(report.get("controls_total", 0))
    missed = int(report.get("controls_missed", 0))
    lines = [
        f"cost-barrier drift gate: {report.get('status')} ({report.get('mode')} mode)",
        f"  head {report.get('head', '')}  branch {report.get('branch', '')}",
        f"  checks {total - failed}/{total} PASS",
        f"  controls {controls - missed}/{controls} detected",
    ]
    for row in report.get("checks") or []:
        lines.append(f"  [{row['result']}] {row['check']} - {row['detail']}")
    if report.get("advisories"):
        lines.append("  advisories:")
        lines.extend(f"    - {item}" for item in report["advisories"])
    if report.get("failures"):
        lines.append("  FAILURES:")
        lines.extend(f"    - {item}" for item in report["failures"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fast mode: validate the published artefacts, the pins and the "
                             "verifier; do not re-run the builder (which needs the locally "
                             "generated market-horizon input)")
    parser.add_argument("--explorer", default=EXPLORER,
                        help="explorer artefact under audit (default: the published one)")
    parser.add_argument("--verification", default=VERIFICATION,
                        help="verification document under audit (default: the published one)")
    parser.add_argument("--strict", action="store_true",
                        help="treat advisories (tolerated absences) as failures")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--report", default=None,
                        help="write the full report JSON to this path")
    args = parser.parse_args(argv)

    report = build_report(args)
    print(render(report))
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if report["status"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
