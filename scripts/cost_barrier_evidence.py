"""EVIDENCE BUNDLE for the cost-barrier lane (WP-7B materialization, WP-7E pins).

Two integrity links that let a clean checkout - including a CI runner - reproduce
the published artefacts without the locally generated input and without trusting
whatever happens to be on disk.

1. **The market-horizon input.** ``reports/strategy-baseline/COST_BARRIER.json``
   is gitignored by design: it is a generated artifact, and regenerating it needs
   the cached bar datasets, which are not in the repository either. A clean
   checkout therefore cannot run the explorer's builder. What *is* admissible is
   a byte-identical evidence copy carried in the repository, because git is
   immutable-per-commit storage; this tool keeps it honest by requiring it to
   reproduce the digest the **published artefact itself** recorded when it was
   built (``sources[]`` in ``COST_BARRIER_EXPLORER.json``). The pin authority is
   therefore the artefact, not this file, not the capture machine.

2. **The producers.** The four scripts that build and verify the artefacts had no
   pin at all: they were watched only by CI triggers, so an edit to one of them
   left every digest in the tree unchanged. The manifest records their digests so
   that such an edit is a named failure instead of an invisible one.

Neither link is a signature. The authority of both is the commit that carries
them: a reviewer reads the diff, and CI re-runs the gate. Anyone able to rewrite
the artefacts, the evidence and the checker together defeats both - that is
stated as a limitation, not papered over (see
``data/recovery/wp7/COST_BARRIER_CI_DESIGN.md``).

Modes::

    python scripts/cost_barrier_evidence.py                # verify (no writes)
    python scripts/cost_barrier_evidence.py --materialize  # verify, then place the input
    python scripts/cost_barrier_evidence.py --capture      # author: record the evidence

Exit codes: 0 verified, 2 integrity failure, 3 blocked (bundle absent).

Read-only in the default and ``--capture`` modes with respect to anything but
the evidence bundle itself; ``--materialize`` writes only the gitignored input,
never a published artefact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EXPLORER = "data/recovery/COST_BARRIER_EXPLORER.json"
TARGET = "reports/strategy-baseline/COST_BARRIER.json"
EVIDENCE_DIR = "data/recovery/wp7/evidence"
EVIDENCE_INPUT = f"{EVIDENCE_DIR}/COST_BARRIER.json"
SIDECAR = f"{EVIDENCE_DIR}/INPUT_EVIDENCE.json"
PRODUCER_PINS = f"{EVIDENCE_DIR}/PRODUCER_PINS.json"

CHECKER = "scripts/cost_barrier_gate.py"

# The four producers that carry no published pin in the artefact. Must stay in
# step with the gate's own list; the gate reports a defect if the manifest and
# its declared producers diverge, so the two cannot drift apart silently.
PRODUCER_ROLES: dict[str, str] = {
    "scripts/active_economic_audit.py": "producer of the WP-3 audit (the 24 cells)",
    "scripts/cost_barrier.py": "producer of the market-horizon report (gitignored output)",
    "scripts/cost_barrier_explorer.py": "builder of the explorer artefact",
    "scripts/cost_barrier_verify.py": "independent verifier of the explorer artefact",
}

PIN_EXACT = "EXACT"
PIN_EOL = "EOL_ONLY"
PIN_DRIFT = "DRIFT"
PIN_ABSENT = "ABSENT"

EXIT_OK = 0
EXIT_INTEGRITY = 2
EXIT_BLOCKED = 3


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
    # newline="\n": these are evidence documents whose digests are pinned elsewhere. A
    # Windows capture must not rewrite every line of them, for the same reason the ledger
    # builder was fixed: the bytes are the evidence.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def eol_forms(data: bytes) -> dict[str, bytes]:
    lf = data.replace(b"\r\n", b"\n")
    return {"EXACT": data, "LF": lf, "CRLF": lf.replace(b"\n", b"\r\n")}


def eol_status(pin: str | None, data: bytes) -> str:
    if pin is None:
        return PIN_ABSENT
    forms = eol_forms(data)
    if sha256_bytes(forms["EXACT"]) == pin:
        return PIN_EXACT
    if sha256_bytes(forms["LF"]) == pin or sha256_bytes(forms["CRLF"]) == pin:
        return PIN_EOL
    return PIN_DRIFT


def pin_forms(path: Path) -> dict[str, Any]:
    """The digests a producer is pinned by, in every admissible byte convention.

    ``sha256`` is the digest of the bytes as they sat on the machine that wrote
    the manifest, and is *not* an authority: ``core.autocrlf`` rewrites line
    endings on checkout, so the same commit presents different bytes to a clean
    checkout than to the tree the pin was written in.  A rehearsal on a clean
    worktree proved exactly that, and three producers were flagged as changed
    for a difference no edit caused.  The authorities are therefore the LF and
    CRLF content forms, and a match means the file *is* that content in one of
    them - not merely that it normalises to it.
    """
    if not path.exists():
        return {"sha256": None, "sha256_lf": None, "sha256_crlf": None, "bytes": None}
    forms = eol_forms(path.read_bytes())
    return {
        "sha256": sha256_bytes(forms["EXACT"]),
        "sha256_lf": sha256_bytes(forms["LF"]),
        "sha256_crlf": sha256_bytes(forms["CRLF"]),
        "bytes": len(forms["EXACT"]),
    }


def admissible(status: str) -> bool:
    """A pin is satisfied by identical content in either line convention.

    Only ``PIN_DRIFT`` means the content moved.  ``PIN_EOL`` means the bytes
    differ by line endings alone, which is what a checkout does to a text file,
    so failing it would make the bundle unverifiable everywhere but on the
    machine that wrote it - the defect the rehearsal found.
    """
    return status in (PIN_EXACT, PIN_EOL)


def git_head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def published_pin(explorer: dict[str, Any], rel: str) -> str | None:
    for row in explorer.get("sources") or []:
        if str(row.get("path")) == rel:
            return str(row.get("sha256"))
    return None


def check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "result": "PASS" if ok else "FAIL", "detail": detail}


# --------------------------------------------------------------------------- #
# capture (authoring)
# --------------------------------------------------------------------------- #


def capture(mode: str) -> tuple[dict[str, Any], int]:
    target = ROOT / TARGET
    explorer_path = ROOT / EXPLORER
    failures: list[str] = []
    if not target.exists():
        return {
            "action": "capture",
            "head": git_head(),
            "status": "BLOCKED_MISSING_INPUT",
            "message": f"{TARGET} is not on this machine, so there is nothing to capture",
            "failures": [f"{TARGET} absent"],
        }, EXIT_BLOCKED
    if not explorer_path.exists():
        return {
            "action": "capture",
            "head": git_head(),
            "status": "BLOCKED_MISSING_INPUT",
            "message": f"{EXPLORER} is absent, so there is no pin authority to capture against",
            "failures": [f"{EXPLORER} absent"],
        }, EXIT_BLOCKED

    explorer = read_json(explorer_path)
    pin = published_pin(explorer, TARGET)
    data = target.read_bytes()
    status = eol_status(pin, data)
    checks = [
        check(
            "capture:the_published_artefact_pins_this_input",
            pin is not None,
            f"pin {str(pin)[:16]}... from sources[]" if pin else "the artefact cites no such input",
        ),
        check(
            "capture:the_local_input_reproduces_the_published_pin",
            status == PIN_EXACT,
            f"status {status} for sha256 {sha256_bytes(data)[:16]}...",
        ),
    ]
    if status != PIN_EXACT:
        failures.append(
            "the local input does not reproduce the digest the published artefact recorded "
            f"({status}); capturing it would create evidence for a revision nobody published"
        )
        return {
            "action": "capture",
            "head": git_head(),
            "status": "INTEGRITY_FAILURE",
            "checks": checks,
            "failures": failures,
        }, EXIT_INTEGRITY

    evidence_path = ROOT / EVIDENCE_INPUT
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, evidence_path)
    lf_form = eol_forms(data)["LF"]
    write_json(ROOT / SIDECAR, {
        "artifact": "COST_BARRIER_INPUT_EVIDENCE",
        "work_package": "WP-7B: byte-identical evidence copy of a gitignored generated input",
        "captured_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "captured_commit": git_head(),
        "source_path": TARGET,
        "evidence_path": EVIDENCE_INPUT,
        "reason": (
            f"{TARGET} is generated from cached bar datasets that are not committed, so it is "
            "gitignored by design and absent from a clean checkout. This copy is byte-identical "
            "to the file the published artefact was built from."
        ),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "sha256_lf": sha256_bytes(lf_form),
        "line_endings": "CRLF" if b"\r\n" in data else "LF",
        "pin_authority": {
            "artifact": EXPLORER,
            "path": TARGET,
            "sha256": pin,
            "payload_sha256": explorer.get("payload_sha256"),
            "how": (
                "the published explorer recorded this digest for this input when it was built; "
                "the copy is admissible only while it reproduces that digest"
            ),
        },
        "not_a_signature": (
            "integrity here is a digest chain anchored in the commit that carries it, not a "
            "signature: a party able to rewrite the artefact, this copy and the checker together "
            "defeats it, and that is stated as a limitation rather than hidden"
        ),
    })
    producers = [
        {"path": rel, "role": role, **pin_forms(ROOT / rel)}
        for rel, role in sorted(PRODUCER_ROLES.items())
    ]
    write_json(ROOT / PRODUCER_PINS, {
        "artifact": "COST_BARRIER_PRODUCER_PINS",
        "work_package": "WP-7E: give the four unpinned producers a digest of their own",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "scripts/cost_barrier_evidence.py --capture",
        "head": git_head(),
        "authority": (
            "the commit that carries this file; re-pinning is an explicit, reviewed act that "
            "must accompany regeneration and re-verification of the artefacts"
        ),
        "admissible_byte_conventions": (
            "a consumer must accept a watched producer whose bytes equal the pinned content in "
            "LF or CRLF form (sha256_lf / sha256_crlf); sha256 records the bytes of the tree "
            "that wrote this manifest and is informational only. A checkout with core.autocrlf "
            "rewrites line endings without touching content, so requiring the raw digest would "
            "fail every clean checkout for a difference no edit caused"
        ),
        "why_only_these_four": (
            "these are exactly the declared inputs that carry no published pin; the five pinned "
            "inputs already have an authority (the artefact's sources[]) and re-pinning them here "
            "would create a second, weaker one"
        ),
        "excluded": {
            CHECKER: (
                "the checker cannot pin itself: a digest the checker verifies against itself is "
                "vacuous, and presenting it as assurance would be worse than the gap it names"
            ),
            "data/recovery/wp7/evidence/**": (
                "the evidence bundle pins the producers, so it cannot be pinned by them without "
                "a cycle; its own integrity is checked against the artefact's published pins"
            ),
        },
        "producers": producers,
    })
    return {
        "action": "capture",
        "head": git_head(),
        "status": "CAPTURED",
        "checks": checks,
        "evidence": {
            "path": EVIDENCE_INPUT,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "pin_authority": pin,
        },
        "producer_pins": PRODUCER_PINS,
        "producers": [row["path"] for row in producers],
        "failures": failures,
    }, EXIT_OK


# --------------------------------------------------------------------------- #
# verification
# --------------------------------------------------------------------------- #


def verify(do_materialize: bool) -> tuple[dict[str, Any], int]:
    evidence_path = ROOT / EVIDENCE_INPUT
    sidecar_path = ROOT / SIDECAR
    manifest_path = ROOT / PRODUCER_PINS
    explorer_path = ROOT / EXPLORER

    absent = [
        rel for rel, path in (
            (EVIDENCE_INPUT, evidence_path),
            (SIDECAR, sidecar_path),
            (PRODUCER_PINS, manifest_path),
            (EXPLORER, explorer_path),
        ) if not path.exists()
    ]
    if absent:
        return {
            "action": "verify",
            "status": "BLOCKED_MISSING_INPUT",
            "message": (
                "the evidence bundle is incomplete: " + ", ".join(absent)
                + ". A full reproduction cannot be claimed without it."
            ),
            "failures": [f"{rel} absent" for rel in absent],
            "checks": [],
        }, EXIT_BLOCKED

    sidecar = read_json(sidecar_path)
    manifest = read_json(manifest_path)
    explorer = read_json(explorer_path)
    data = evidence_path.read_bytes()

    pin = published_pin(explorer, TARGET)
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    advisories: list[str] = []

    checks.append(check(
        "evidence:copy_matches_the_recorded_digest",
        sha256_bytes(data) == sidecar.get("sha256")
        or sha256_bytes(eol_forms(data)["LF"]) == sidecar.get("sha256_lf"),
        f"copy {sha256_bytes(data)[:16]}... vs recorded {str(sidecar.get('sha256'))[:16]}...",
    ))
    if checks[-1]["result"] != "PASS":
        failures.append(
            f"{EVIDENCE_INPUT} no longer matches the digest recorded when it was captured: the "
            "evidence itself has drifted"
        )

    recorded_pin = (sidecar.get("pin_authority") or {}).get("sha256")
    checks.append(check(
        "evidence:the_artefact_pin_is_unchanged_since_capture",
        recorded_pin is not None and recorded_pin == pin,
        f"recorded {str(recorded_pin)[:16]}... vs published {str(pin)[:16]}...",
    ))
    if checks[-1]["result"] == "FAIL":
        failures.append(
            "the pin the artefact publishes for this input is not the one the evidence was "
            "captured against: the artefact was regenerated, so the evidence must be re-captured"
        )

    status = eol_status(pin, data)
    checks.append(check(
        "evidence:the_copy_reproduces_the_published_pin",
        status in (PIN_EXACT, PIN_EOL),
        f"{status} for the copy against pin {str(pin)[:16]}...",
    ))
    if checks[-1]["result"] == "FAIL":
        failures.append(
            f"{EVIDENCE_INPUT} does not reproduce the digest the published artefact recorded "
            f"({status}): a clean checkout would reproduce a different input than the one that "
            "was published from"
        )

    payload = (sidecar.get("pin_authority") or {}).get("payload_sha256")
    checks.append(check(
        "evidence:captured_against_the_published_artefact_revision",
        payload is not None and payload == explorer.get("payload_sha256"),
        f"captured for payload {str(payload)[:16]}... vs published "
        f"{str(explorer.get('payload_sha256'))[:16]}...",
    ))
    if checks[-1]["result"] == "FAIL":
        failures.append(
            "the evidence bundle was captured against a different revision of the explorer "
            "artefact than the one published"
        )

    rows = []
    for rel in sorted(PRODUCER_ROLES):
        entry = next(
            (row for row in manifest.get("producers") or [] if row.get("path") == rel), None
        )
        present = (ROOT / rel).exists()
        current = sha256_file(ROOT / rel)
        recorded = (entry or {}).get("sha256")
        row_status = PIN_ABSENT if not present else eol_status(recorded, (ROOT / rel).read_bytes())
        rows.append({
            "path": rel,
            "present": present,
            "recorded": recorded,
            "recorded_lf": (entry or {}).get("sha256_lf"),
            "current": current,
            "pin_status": row_status,
        })
    # Only DRIFT (or a vanished producer) is a failure: EOL_ONLY is a checkout
    # artefact, and the gate's producer matrix draws the same distinction.
    drifted = [row for row in rows if not admissible(str(row["pin_status"]))]
    eol_only = [row for row in rows if row["pin_status"] == PIN_EOL]
    extra = sorted(
        str(row.get("path")) for row in manifest.get("producers") or []
        if str(row.get("path")) not in PRODUCER_ROLES
    )
    checks.append(check(
        "evidence:producer_digests_match_the_manifest",
        not drifted and not extra,
        f"{len(rows) - len(drifted)}/{len(rows)} producer(s) match "
        f"({sum(1 for r in rows if r['pin_status'] == PIN_EXACT)} exact, "
        f"{len(eol_only)} line-ending-only)"
        if not drifted and not extra
        else "drifted/absent: " + ", ".join(
            f"{row['path']} ({row['pin_status']})" for row in drifted
        ) + (f"; unlisted: {extra}" if extra else ""),
    ))
    if drifted:
        failures.append(
            "watched producer(s) changed since the manifest was written: "
            + ", ".join(str(row["path"]) for row in drifted)
            + " - regenerate, re-verify and re-pin in the same commit"
        )
    if eol_only:
        advisories.append(
            "line-ending-only difference, accepted: "
            + ", ".join(f"{row['path']} ({row['pin_status']})" for row in eol_only)
            + ". The content is the pinned content; git rewrote the bytes on checkout"
        )

    checks.append(check(
        "evidence:the_checker_is_not_pinned_by_the_bundle",
        CHECKER not in {str(row.get("path")) for row in manifest.get("producers") or []},
        f"{CHECKER} is excluded by design; the checker cannot vouch for itself",
    ))
    if checks[-1]["result"] == "FAIL":
        failures.append(f"{PRODUCER_PINS} pins {CHECKER}, which is vacuous assurance")

    target = ROOT / TARGET
    placement: dict[str, Any] = {"target": TARGET, "materialized": False}
    if do_materialize and not failures:
        if target.exists():
            same_content = (
                sha256_bytes(eol_forms(target.read_bytes())["LF"]) == sha256_bytes(eol_forms(data)["LF"])
            )
            placement.update({
                "materialized": False,
                "action": "already_present",
                "target_sha256": sha256_file(target),
                "same_content": same_content,
            })
            if not same_content:
                failures.append(
                    f"{TARGET} exists with different content: refusing to overwrite an input this "
                    "machine already has"
                )
                checks.append(check(
                    "materialize:existing_input_not_overwritten", False, "content differs"
                ))
            else:
                checks.append(check(
                    "materialize:existing_input_left_untouched", True,
                    "the existing input is byte-equivalent; nothing was written",
                ))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            placement.update({
                "materialized": True,
                "action": "written",
                "bytes": len(data),
                "target_sha256": sha256_file(target),
            })
            checks.append(check(
                "materialize:input_placed_at_its_canonical_path",
                sha256_file(target) == sha256_bytes(data),
                f"{TARGET} now carries sha256 {str(sha256_file(target))[:16]}...",
            ))

    status_value = "VERIFIED" if not failures else "INTEGRITY_FAILURE"
    report = {
        "artifact": "COST_BARRIER_EVIDENCE_BUNDLE",
        "work_package": "WP-7B materialization + WP-7E producer pins",
        "checked_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": git_head(),
        "action": "materialize" if do_materialize else "verify",
        "status": status_value,
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for row in checks if row["result"] != "PASS"),
        "input": {
            "evidence_path": EVIDENCE_INPUT,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "pin_authority": pin,
            "pin_status": status,
            "recorded_sha256": sidecar.get("sha256"),
            "captured_commit": sidecar.get("captured_commit"),
        },
        "producers": rows,
        "placement": placement,
        "failures": failures,
        "advisories": advisories,
        "exit_code": EXIT_OK if not failures else EXIT_INTEGRITY,
    }
    return report, (EXIT_OK if not failures else EXIT_INTEGRITY)


def render(report: dict[str, Any]) -> str:
    lines = [
        f"cost-barrier evidence bundle: {report.get('status')} ({report.get('action')})",
        f"  head {report.get('head', '')}",
    ]
    if report.get("message"):
        lines.append(f"  {report['message']}")
    for row in report.get("checks") or []:
        lines.append(f"  [{row['result']}] {row['check']} - {row['detail']}")
    if report.get("placement"):
        lines.append(f"  placement: {report['placement']}")
    if report.get("advisories"):
        lines.append("  ADVISORIES:")
        lines.extend(f"    - {item}" for item in report["advisories"])
    if report.get("failures"):
        lines.append("  FAILURES:")
        lines.extend(f"    - {item}" for item in report["failures"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", action="store_true",
                        help="record the evidence copy and the producer pins (authoring; needs "
                             "the gitignored input on this machine)")
    parser.add_argument("--materialize", action="store_true",
                        help="after verifying, place the input at its canonical path if absent")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--report", default=None, help="write the report JSON to this path")
    args = parser.parse_args(argv)

    if args.capture:
        report, code = capture("capture")
    else:
        report, code = verify(args.materialize)
    print(render(report))
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
