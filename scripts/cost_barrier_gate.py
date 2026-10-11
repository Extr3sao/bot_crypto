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

WP-7 additions, in the same spirit:

* a **state contract** of six outcomes (``FULL_REPRODUCTION_PASS``,
  ``FULL_REPRODUCTION_FAIL``, ``CHECK_ONLY_PASS``,
  ``CHECK_ONLY_WITH_ADVISORIES``, ``BLOCKED_MISSING_INPUT``,
  ``INTEGRITY_FAILURE``). Only a full reproduction satisfies a full-certification
  requirement; a ``--check`` run is useful evidence and never a substitute, so no
  partial result can promote a strategy or certify an economic result;
* the **producers** that were previously only watched by CI triggers now carry a
  digest pin of their own, so an edit to the code that builds or verifies the
  artefacts is a named failure instead of an invisible one;
* the market-horizon section is **re-derived here** from the pinned source, which
  closes the case of a derived number edited with its self-hash recomputed
  honestly - the independent verifier never reads that source, so without this
  the section was attested only by full reproduction;
* every report names the commit and the environment that produced it.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import platform
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
# WP-7 state contract
# --------------------------------------------------------------------------- #

# The six outcomes a run can end in. They are deliberately not a boolean: a
# check-only run on a clean checkout, a run that cannot start because an input
# was never materialized and a run that found a tampered artefact are three
# different facts, and collapsing them into one "FAIL" is how a partial
# verification ends up being cited as a full one.
FULL_REPRODUCTION_PASS = "FULL_REPRODUCTION_PASS"
FULL_REPRODUCTION_FAIL = "FULL_REPRODUCTION_FAIL"
CHECK_ONLY_PASS = "CHECK_ONLY_PASS"
CHECK_ONLY_WITH_ADVISORIES = "CHECK_ONLY_WITH_ADVISORIES"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
INTEGRITY_FAILURE = "INTEGRITY_FAILURE"

STATUS_CONTRACT: tuple[str, ...] = (
    FULL_REPRODUCTION_PASS,
    FULL_REPRODUCTION_FAIL,
    CHECK_ONLY_PASS,
    CHECK_ONLY_WITH_ADVISORIES,
    BLOCKED_MISSING_INPUT,
    INTEGRITY_FAILURE,
)

# Only this one satisfies a full-certification requirement.
FULL_CERTIFICATION_STATUSES: tuple[str, ...] = (FULL_REPRODUCTION_PASS,)

# One distinct exit code per state, so a shell cannot mistake a partial run for
# a certification: 0 full reproduction, 2 partial (check-only), 3 blocked on a
# missing required input, 4 the reproduction diverged, 5 integrity failure.
EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_BLOCKED = 3
EXIT_REPRODUCTION_FAIL = 4
EXIT_INTEGRITY_FAILURE = 5

EXIT_CODES: dict[str, int] = {
    FULL_REPRODUCTION_PASS: EXIT_OK,
    CHECK_ONLY_PASS: EXIT_PARTIAL,
    CHECK_ONLY_WITH_ADVISORIES: EXIT_PARTIAL,
    BLOCKED_MISSING_INPUT: EXIT_BLOCKED,
    FULL_REPRODUCTION_FAIL: EXIT_REPRODUCTION_FAIL,
    INTEGRITY_FAILURE: EXIT_INTEGRITY_FAILURE,
}

# Check severities. "integrity" means the published evidence contradicts itself,
# a cited input or a watched producer, and no amount of re-running would explain
# it; "reproduction" means the fresh run diverged; "blocked" means a required
# input was never materialized, which is not the same as a failed reproduction.
SEVERITY_INTEGRITY = "integrity"
SEVERITY_REPRODUCTION = "reproduction"
SEVERITY_BLOCKED = "blocked"

# --------------------------------------------------------------------------- #
# WP-7E provenance: the producers that were only watched by triggers
# --------------------------------------------------------------------------- #

EVIDENCE_DIR = "data/recovery/wp7/evidence"
PRODUCER_PINS_PATH = f"{EVIDENCE_DIR}/PRODUCER_PINS.json"

# The four declared inputs with no published pin are the producers themselves:
# the audit builder, the market-horizon producer, the artefact builder and the
# independent verifier. Derived from DECLARED_INPUTS so the two lists cannot
# drift apart.
PRODUCERS: tuple[str, ...] = tuple(
    rel for rel, _role, pinned in DECLARED_INPUTS if not pinned
)

# The gate is not in the manifest, by construction and by check: a pin the
# checker verifies against itself is vacuous, and pretending otherwise would be
# exactly the kind of false assurance this file exists to prevent.
CHECKER = "scripts/cost_barrier_gate.py"

# --------------------------------------------------------------------------- #
# the market-horizon section: re-derived here, from the pinned source alone
# --------------------------------------------------------------------------- #

MARKET_HORIZON_SOURCE = "reports/strategy-baseline/COST_BARRIER.json"
MARKET_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "30m", "1h")
MARKET_FIELDS: tuple[str, ...] = (
    "bars",
    "abs_ret_bps_median",
    "bars_to_BASE",
    "hours_to_BASE",
    "bars_to_2X_COST",
    "hours_to_2X_COST",
    "bars_to_STRESSED",
    "hours_to_STRESSED",
)

# --------------------------------------------------------------------------- #
# WP-7D: the activation contract - the workflow that has to run this gate
# --------------------------------------------------------------------------- #

WORKFLOW_PATH = ".github/workflows/cost-barrier-gate.yml"

# Everything that must be able to activate the gate: the declared inputs, the
# tools on both sides of it, the evidence bundle and the tests that hold it to
# its word. If any of these can change without the workflow firing, the gate is
# decorative for that path - a dependency moved under a path nobody watches is
# the cheapest way to neuter a CI check, and it leaves no trace in any digest.
CI_WATCHED: tuple[str, ...] = tuple(sorted({
    *(rel for rel, _role, _pinned in DECLARED_INPUTS),
    MARKET_HORIZON_SOURCE,
    PRODUCER_PINS_PATH,
    "data/recovery/wp7/evidence/COST_BARRIER.json",
    "data/recovery/wp7/evidence/INPUT_EVIDENCE.json",
    CHECKER,
    "scripts/cost_barrier_evidence.py",
    "scripts/cost_barrier_adversarial.py",
    "scripts/cost_barrier_certify.py",
    WORKFLOW_PATH,
    "tests/unit/research/test_cost_barrier_gate.py",
    "tests/unit/research/test_cost_barrier_adversarial.py",
    "tests/unit/research/test_cost_barrier_ci_parity.py",
}))


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
# WP-7E producer pins: the code that builds and verifies the artefacts
# --------------------------------------------------------------------------- #


def load_producer_pins() -> tuple[dict[str, Any] | None, list[str]]:
    path = ROOT / PRODUCER_PINS_PATH
    if not path.exists():
        return None, [
            f"the producer pin manifest {PRODUCER_PINS_PATH} is missing, so the code that "
            f"builds and verifies the artefacts cannot be held to a digest"
        ]
    try:
        manifest = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{PRODUCER_PINS_PATH} cannot be read as JSON: {exc}"]
    if not isinstance(manifest, dict):
        return None, [f"{PRODUCER_PINS_PATH} is not a JSON object"]
    return manifest, []


def producer_rows(manifest: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Compare the four watched producers against the digests the manifest pins."""
    pins = {
        str(row.get("path")): row.get("sha256")
        for row in (manifest or {}).get("producers") or []
    }
    rows: list[dict[str, Any]] = []
    defects: list[str] = []
    for rel in PRODUCERS:
        pin = pins.get(rel)
        path = ROOT / rel
        present = path.exists()
        data = path.read_bytes() if present else None
        if pin is None:
            defects.append(
                f"{rel} is a watched producer but {PRODUCER_PINS_PATH} carries no pin for it"
            )
        status = PIN_ABSENT if data is None else pin_status(pin, data)
        rows.append({
            "path": rel,
            "present": present,
            "pin_status": status,
            "pin": pin,
            "sha256_current": sha256_bytes(data) if data is not None else None,
        })
    extra = sorted(set(pins) - set(PRODUCERS))
    if extra:
        defects.append(
            f"{PRODUCER_PINS_PATH} pins path(s) that are not watched producers: {extra}"
        )
    if CHECKER in pins:
        defects.append(
            f"{PRODUCER_PINS_PATH} pins {CHECKER}: a pin the checker verifies against itself "
            "is vacuous and must not be presented as assurance"
        )
    return rows, defects


# --------------------------------------------------------------------------- #
# the market-horizon section, re-derived from the pinned source
# --------------------------------------------------------------------------- #


def market_horizon_rows(barrier: dict[str, Any]) -> list[dict[str, Any]]:
    """Recompute the rows the artefact should carry for the pinned source.

    Deliberately a second implementation of a small, fully specified mapping, in
    the same spirit as the verifier: the gate must be able to contradict the
    artefact without asking the artefact's own builder what the answer is.
    """
    rows: list[dict[str, Any]] = []
    for timeframe in MARKET_TIMEFRAMES:
        for asset, row in sorted((barrier.get(timeframe) or {}).items()):
            rows.append({
                "timeframe": timeframe,
                "asset": asset,
                **{field: row.get(field) for field in MARKET_FIELDS},
            })
    return rows


def market_horizon_failures(explorer: dict[str, Any], barrier: dict[str, Any]) -> list[str]:
    section = ((explorer.get("horizon") or {}).get("market_horizon")) or {}
    bad: list[str] = []
    published = section.get("published_lines_bps")
    declared = (barrier.get("meta") or {}).get("cost_model_bps_rt")
    if published != declared:
        bad.append(
            f"horizon.market_horizon.published_lines_bps {published!r} != "
            f"meta.cost_model_bps_rt {declared!r} in {MARKET_HORIZON_SOURCE}"
        )
    derived = market_horizon_rows(barrier)
    rows = section.get("rows")
    if not isinstance(rows, list):
        bad.append("horizon.market_horizon.rows is missing from the artefact")
        return bad
    if len(rows) != len(derived):
        bad.append(
            f"horizon.market_horizon carries {len(rows)} row(s) but the pinned source "
            f"defines {len(derived)} (timeframes x assets)"
        )
        return bad
    for index, (got, want) in enumerate(zip(rows, derived, strict=True)):
        for field in ("timeframe", "asset", *MARKET_FIELDS):
            if got.get(field) != want[field]:
                bad.append(
                    f"horizon.market_horizon.rows[{index}].{field}: {got.get(field)!r} != "
                    f"{want[field]!r} from {MARKET_HORIZON_SOURCE}"
                )
    return bad


# --------------------------------------------------------------------------- #
# the activation contract: can CI still see this gate's dependencies?
# --------------------------------------------------------------------------- #


def workflow_filters(text: str) -> dict[str, list[str]]:
    """Read the ``paths:`` lists out of our own workflow, without a YAML dependency.

    PyYAML is not a runtime dependency of this gate, and a gate that cannot read
    its own activation contract because a parser is missing has failed in a way
    nobody notices. The file is ours and its shape is fixed - ``push:`` and
    ``pull_request:``, each with a two-space ``paths:`` block - so it is scanned
    directly, and the ``paths:`` blocks are asserted below. If the shape is not
    there, this returns nothing and the caller fails closed rather than passing.
    """
    out: dict[str, list[str]] = {}
    trigger: str | None = None
    in_paths = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 2 and stripped.endswith(":"):
            name = stripped[:-1]
            trigger = name if name in ("push", "pull_request") else None
            in_paths = False
            continue
        if trigger is not None and indent == 4 and stripped == "paths:":
            in_paths = True
            out.setdefault(trigger, [])
            continue
        if trigger is not None and in_paths and indent >= 6 and stripped.startswith("- "):
            out[trigger].append(stripped[2:].strip().strip("\"'"))
            continue
        if in_paths and indent <= 4:
            in_paths = False
    return out


def workflow_coverage_failures() -> tuple[list[str], dict[str, list[str]]]:
    path = ROOT / WORKFLOW_PATH
    if not path.exists():
        return [f"{WORKFLOW_PATH} is absent: nothing in CI would ever run this gate"], {}
    text = path.read_text(encoding="utf-8")
    # Keyword checks read the workflow as code, not as prose: a comment that
    # claims the gate runs is not an invocation, and a comment that mentions
    # continue-on-error is not a softened step.
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    filters = workflow_filters(text)
    bad: list[str] = []
    for trigger in ("push", "pull_request"):
        patterns = filters.get(trigger)
        if not patterns:
            bad.append(
                f"{WORKFLOW_PATH} carries no readable `{trigger}: paths:` list, so the gate "
                "cannot prove it would fire"
            )
            continue
        missing = [
            rel for rel in CI_WATCHED
            if not any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)
        ]
        if missing:
            bad.append(
                f"a change to {missing} would not activate the workflow on {trigger}"
            )
    push, pull = filters.get("push"), filters.get("pull_request")
    if push and pull and set(push) != set(pull):
        bad.append(
            f"the push and pull_request filters differ: {sorted(set(push) ^ set(pull))}"
        )
    if "cost_barrier_gate.py" not in code:
        bad.append("the workflow does not invoke scripts/cost_barrier_gate.py")
    if "cost_barrier_evidence.py" not in code or "--materialize" not in code:
        bad.append(
            "the workflow does not materialize the declared inputs before running the gate"
        )
    if "continue-on-error" in code:
        bad.append(
            "the workflow softens a step with continue-on-error, so a failure could pass "
            "unnoticed"
        )
    return bad, filters


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


def check(
    result: bool, name: str, detail: str, severity: str = SEVERITY_INTEGRITY
) -> dict[str, Any]:
    return {
        "check": name,
        "result": "PASS" if result else "FAIL",
        "detail": detail,
        "severity": severity,
    }


def classify(checks: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    """Split failed checks into (integrity, reproduction, blocked) by severity."""
    integrity: list[str] = []
    reproduction: list[str] = []
    blocked: list[str] = []
    for row in checks:
        if row.get("result") == "PASS":
            continue
        bucket = {
            SEVERITY_INTEGRITY: integrity,
            SEVERITY_REPRODUCTION: reproduction,
            SEVERITY_BLOCKED: blocked,
        }[str(row.get("severity"))]
        bucket.append(f"{row['check']}: {row['detail']}")
    return integrity, reproduction, blocked


def decide_status(
    *,
    mode: str,
    integrity: list[str],
    reproduction: list[str],
    blocked: list[str],
    advisories: list[str],
    strict: bool = False,
) -> str:
    """Map the run's evidence onto the six-state contract.

    Precedence is deliberate and tested: an artefact that contradicts itself or
    its own inputs is an integrity failure whatever mode ran, a run that could
    not start for want of a required input is blocked rather than failed, and
    only a full reproduction in which nothing diverged reaches the one state
    that may satisfy a certification requirement. ``--strict`` escalates an
    advisory absence, but never into a pass and never silently.
    """
    if integrity:
        return INTEGRITY_FAILURE
    if blocked:
        return BLOCKED_MISSING_INPUT
    if strict and advisories:
        return FULL_REPRODUCTION_FAIL if mode == "full" else INTEGRITY_FAILURE
    if reproduction:
        return FULL_REPRODUCTION_FAIL if mode == "full" else INTEGRITY_FAILURE
    if mode == "check":
        return CHECK_ONLY_WITH_ADVISORIES if advisories else CHECK_ONLY_PASS
    return FULL_REPRODUCTION_PASS


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
        status = INTEGRITY_FAILURE
        return {
            "artifact": "COST_BARRIER_DRIFT_GATE",
            "checked_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head": git_value("rev-parse", "HEAD"),
            "branch": git_value("rev-parse", "--abbrev-ref", "HEAD"),
            "environment": environment_block(),
            "mode": "full" if full else "check",
            "status_contract": list(STATUS_CONTRACT),
            "status": status,
            "checks": [
                check(False, "subjects:present", f"missing {missing}", SEVERITY_INTEGRITY)
            ],
            "checks_total": 1,
            "checks_failed": 1,
            "integrity_failures": [f"missing subject(s) {missing}"],
            "reproduction_failures": [],
            "blocked": [],
            "failures": [f"missing subject(s) {missing}"],
            "advisories": [],
            "certification": certification_block(status),
            "exit_code": exit_code(status),
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
            checks.append(check(
                False, "inputs:declared_inputs_present", detail, SEVERITY_BLOCKED
            ))
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

    # --- 4b. the producers that were previously only watched by triggers ---- #
    manifest, manifest_defects = load_producer_pins()
    producer_matrix, producer_defects = producer_rows(manifest)
    producer_drift = [row for row in producer_matrix if row["pin_status"] == PIN_DRIFT]
    producer_missing = [row for row in producer_matrix if not row["present"]]
    producer_defects = manifest_defects + producer_defects
    producers_ok = not producer_drift and not producer_missing and not producer_defects
    checks.append(check(
        producers_ok,
        "producers:digests_match_the_pinned_manifest",
        f"{len(producer_matrix)}/{len(producer_matrix)} producer(s) match the pin recorded in "
        f"{PRODUCER_PINS_PATH} ({sum(1 for r in producer_matrix if r['pin_status'] == PIN_EXACT)} "
        f"exact, {sum(1 for r in producer_matrix if r['pin_status'] == PIN_EOL)} line-ending-only)"
        if producers_ok
        else "; ".join(
            [f"{row['path']} drifted from the pinned producer digest" for row in producer_drift]
            + [f"{row['path']} is missing" for row in producer_missing]
            + producer_defects
        ),
    ))
    for row in producer_drift:
        failures.append(
            f"watched producer {row['path']} no longer matches the digest recorded in "
            f"{PRODUCER_PINS_PATH}: the producer changed, so the artefacts must be "
            "regenerated and re-verified and the manifest re-pinned in the same commit"
        )
    for row in producer_missing:
        failures.append(f"watched producer {row['path']} is absent from this tree")
    for defect in producer_defects:
        failures.append(defect)

    # --- 4c. the market-horizon section, re-derived from the pinned source -- #
    barrier_path = ROOT / MARKET_HORIZON_SOURCE
    if barrier_path.exists():
        try:
            barrier = read_json(barrier_path)
        except json.JSONDecodeError as exc:
            barrier = None
            horizon_failures = [f"{MARKET_HORIZON_SOURCE} is not readable as JSON: {exc}"]
        else:
            horizon_failures = market_horizon_failures(explorer_doc, barrier)
        checks.append(check(
            not horizon_failures,
            "source:market_horizon_rows_match_the_pinned_source",
            f"every market-horizon row and the published lines reproduce from "
            f"{MARKET_HORIZON_SOURCE} ({len(market_horizon_rows(barrier or {}))} rows)"
            if not horizon_failures
            else "; ".join(horizon_failures[:5]),
        ))
        for item in horizon_failures:
            failures.append(
                f"the published market-horizon section does not come from the pinned source: {item}"
            )

    # --- 4d. the activation contract --------------------------------------- #
    ci_failures, ci_filters = workflow_coverage_failures()
    checks.append(check(
        not ci_failures,
        "ci:activation_contract_covers_every_declared_input",
        f"{len(CI_WATCHED)} watched path(s) covered by both triggers; the gate and the "
        "materializer are invoked and no step is softened"
        if not ci_failures
        else "; ".join(ci_failures),
    ))
    for item in ci_failures:
        failures.append(f"the CI activation contract is broken: {item}")

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
                    SEVERITY_REPRODUCTION,
                ))
                failures.append(
                    f"the builder failed (exit {built.returncode}); its own checks did not pass, "
                    "so no reproduction claim can be made"
                )
                checks.append(check(
                    False,
                    "reproduce:explorer_rebuilds_identically",
                    "not attempted: the builder did not produce a fresh artefact",
                    SEVERITY_REPRODUCTION,
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
                    SEVERITY_REPRODUCTION,
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
                SEVERITY_REPRODUCTION,
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

    integrity_failures, reproduction_failures, blocked_checks = classify(checks)
    status = decide_status(
        mode="full" if full else "check",
        integrity=integrity_failures,
        reproduction=reproduction_failures,
        blocked=blocked_checks,
        advisories=advisories,
        strict=args.strict,
    )

    report: dict[str, Any] = {
        "artifact": "COST_BARRIER_DRIFT_GATE",
        "work_package": (
            "WP-6 governance follow-on (reproduction on every input change) + WP-7 "
            "(state contract, producer pins, market-horizon re-derivation, certification)"
        ),
        "checked_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": git_value("rev-parse", "HEAD"),
        "branch": git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "environment": environment_block(),
        "mode": "full" if full else "check",
        "status_contract": list(STATUS_CONTRACT),
        "subjects": [str(explorer_path), str(verification_path)],
        "declared_inputs": rows,
        "producer_pins": PRODUCER_PINS_PATH,
        "producers": producer_matrix,
        "ci_activation": {
            "workflow": WORKFLOW_PATH,
            "watched_paths": list(CI_WATCHED),
            "filters": ci_filters,
        },
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": checks_failed,
        "controls": controls,
        "controls_total": len(controls),
        "controls_missed": len(missed),
        "integrity_failures": integrity_failures,
        "reproduction_failures": reproduction_failures,
        "blocked": blocked_checks,
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
    report["status"] = status
    report["certification"] = certification_block(status)
    report["exit_code"] = exit_code(status)
    report["gate_sha256"] = sha256_file(Path(__file__))
    return report


def certification_block(status: str) -> dict[str, Any]:
    """What this run does and does not entitle anyone to say.

    Only ``FULL_REPRODUCTION_PASS`` satisfies a full-certification requirement.
    Everything else is evidence of a narrower kind, and the block says so
    explicitly so that no downstream reader has to infer it from an exit code.
    """
    return {
        "status": status,
        "requires": FULL_REPRODUCTION_PASS,
        "satisfies_full_certification": status in FULL_CERTIFICATION_STATUSES,
        "is_partial": status not in FULL_CERTIFICATION_STATUSES,
        "partial_result_may_certify_economic_results": False,
        "partial_result_may_promote_strategies": False,
        "note": (
            "a check-only run re-verifies the published numbers but never re-runs the "
            "builder; it is useful evidence on a clean checkout and is never a substitute "
            "for a full reproduction"
        ),
    }


def exit_code(status: str) -> int:
    """One distinct exit code per contract state - a partial run is not a pass."""
    return EXIT_CODES[status]


def environment_block() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable": sys.executable,
    }


def git_value(*argv: str) -> str:
    out = subprocess.run(
        ["git", *argv], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def render(report: dict[str, Any]) -> str:
    total = int(report.get("checks_total", 0))
    failed = int(report.get("checks_failed", 0))
    controls = int(report.get("controls_total", 0))
    missed = int(report.get("controls_missed", 0))
    lines = [
        f"cost-barrier drift gate: {report.get('status')} ({report.get('mode')} mode) "
        f"exit {report.get('exit_code')}",
        f"  head {report.get('head', '')}  branch {report.get('branch', '')}",
        f"  checks {total - failed}/{total} PASS",
        f"  controls {controls - missed}/{controls} detected",
    ]
    certification = report.get("certification") or {}
    if certification:
        lines.append(
            "  full certification satisfied: "
            f"{certification.get('satisfies_full_certification')}"
            + (" (partial run)" if certification.get("is_partial") else "")
        )
    for row in report.get("checks") or []:
        lines.append(f"  [{row['result']}] {row['check']} - {row['detail']}")
    if report.get("advisories"):
        lines.append("  advisories:")
        lines.extend(f"    - {item}" for item in report["advisories"])
    if report.get("failures"):
        lines.append("  FAILURES:")
        lines.extend(f"    - {item}" for item in report["failures"])
    if report.get("integrity_failures"):
        lines.append("  INTEGRITY_FAILURE (no re-run could explain these):")
        lines.extend(f"    - {item}" for item in report["integrity_failures"])
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
    return exit_code(str(report["status"]))


if __name__ == "__main__":
    sys.exit(main())
