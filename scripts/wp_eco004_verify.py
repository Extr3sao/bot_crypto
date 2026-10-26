"""WP-ECONOMIC-RECOVERY-004 — independent verification of the ledger repair.

``BUILDER != VERIFIER``. This program implements the ledger identity contract a
third time, from `LEDGER_INTEGRITY_CONTRACT.md` alone: it imports neither the
explorer (which wrote the published state pin) nor the gate (which re-derives it),
and it does not call the repair's helpers. If either implementation changed the
convention, this file would disagree with the published pin.

What it re-derives, and why each check can fail:

* **identity**  - the published ``state_sha256`` is what the contract says it is,
  and the declared ``state_contract`` is the version this verifier implements;
* **physical identity** - the byte pins of the immutable inputs still match their
  files (a line-ending rendering is reported as such, never silently accepted);
* **authority** - the ledger is byte-identical to the one committed before this
  work package and still rebuilds from its committed sources; the repair did not
  choose a version of the truth;
* **economics** - the explorer's payload digest and its whole economic body are
  unchanged, so nothing in this WP moved a number;
* **runtime**  - the gate really reaches ``FULL_REPRODUCTION_PASS`` with
  ``false_success 0``, and the evidence bundle verifies;
* **no laundering** - the 19 cost-barrier nodes closed and no node was added; the
  85 pre-existing failures of the repository are still visible and none of them
  is in this lane.

Read-only: it writes only its own report. It runs the gate and the evidence bundle,
both of which are read-only in the modes used here.

Usage:
    uv run python scripts/wp_eco004_verify.py [--out <artifact path>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
WP = Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-004")
LEDGER = "config/strategy_admission.json"
EXPLORER = "data/recovery/COST_BARRIER_EXPLORER.json"
VERIFICATION = "data/recovery/COST_BARRIER_VERIFICATION.json"
EVIDENCE_COPY = "data/recovery/wp7/evidence/COST_BARRIER.json"
BASE_COMMIT = "2bd6e346"  # the commit WP-004 started from

#: Reimplemented from the contract document, not imported.
CONTRACT = "strategy-admission-ledger-identity-v1"
SCHEMA = "strategy-admission-ledger-v1"
PROVENANCE = ("_generated_by",)
VOLATILE_EXPLORER = (
    "generated_at_utc",
    "payload_sha256",
    "head",
    "branch",
    "sources",
    "local_observations",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def blob(rev: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=REPO, capture_output=True, check=False
    ).stdout


def read_json(path: str) -> Any:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def ledger_identity(document: dict[str, Any]) -> str | None:
    """LEDGER_INTEGRITY_CONTRACT.md §3, written from the prose."""

    if not isinstance(document, dict) or document.get("_schema_version") != SCHEMA:
        return None
    state = {key: value for key, value in document.items() if key not in PROVENANCE}
    payload = json.dumps(
        {"contract": CONTRACT, "state": state}, indent=2, sort_keys=True, ensure_ascii=False
    )
    return sha(payload.encode("utf-8"))


def explorer_body(document: dict[str, Any]) -> str:
    """The economic body: everything except provenance and the source pins."""

    body = {key: value for key, value in document.items() if key not in VOLATILE_EXPLORER}
    return sha(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def row(ident: str, claim: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": ident, "claim": claim, "verdict": "PASS" if ok else "FAIL", "detail": detail}


def identity_checks() -> list[dict[str, Any]]:
    explorer = read_json(EXPLORER)
    source = next(s for s in explorer["sources"] if s["path"] == LEDGER)
    document = read_json(LEDGER)
    recomputed = ledger_identity(document)
    return [
        row(
            "the_published_state_pin_is_the_contract_value",
            "state_sha256 under sources[] is what LEDGER_INTEGRITY_CONTRACT.md computes",
            source.get("state_contract") == CONTRACT and recomputed == source.get("state_sha256"),
            f"contract={source.get('state_contract')} pin={str(source.get('state_sha256'))[:16]} "
            f"recomputed={str(recomputed)[:16]}",
        ),
        row(
            "the_ledger_bytes_are_the_published_ones",
            "the byte pin still names the ledger on disk: the state pin did not replace it",
            source.get("sha256") == sha((REPO / LEDGER).read_bytes()),
            f"pin={str(source.get('sha256'))[:16]} disk={sha((REPO / LEDGER).read_bytes())[:16]}",
        ),
    ]


def physical_input_checks() -> list[dict[str, Any]]:
    explorer = read_json(EXPLORER)
    checks = []
    for source in explorer["sources"]:
        path = REPO / source["path"]
        if not path.is_file():
            continue
        raw = path.read_bytes()
        exact = sha(raw) == source["sha256"]
        eol = (
            sha(raw.replace(b"\r\n", b"\n")) == source["sha256"]
            or sha(raw.replace(b"\n", b"\r\n")) == source["sha256"]
        )
        checks.append(
            row(
                f"physical:{source['path']}",
                "the immutable input is still identified by its bytes (exact or line-ending "
                "rendering), not only by state",
                exact or eol,
                f"{'EXACT' if exact else 'EOL_ONLY' if eol else 'DRIFT'} "
                f"pin={str(source['sha256'])[:12]} disk={sha(raw)[:12]}",
            )
        )
    copy = REPO / EVIDENCE_COPY
    checks.append(
        row(
            "physical:cost_barrier_input_evidence_copy",
            "the recovered input is still byte-identical to the copy the artefact pinned",
            copy.is_file()
            and sha(copy.read_bytes())
            == next(
                s["sha256"] for s in explorer["sources"] if s["path"].endswith("COST_BARRIER.json")
            ),
            f"copy={sha(copy.read_bytes())[:16] if copy.is_file() else '-'}",
        )
    )
    return checks


def authority_checks() -> list[dict[str, Any]]:
    ledger_diff = git("diff", "--name-only", BASE_COMMIT, "--", LEDGER).strip()
    rebuild = subprocess.run(
        [sys.executable, "scripts/build_strategy_admission.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    ledger = read_json(LEDGER)
    base = json.loads(blob(BASE_COMMIT, LEDGER) or b"{}")
    return [
        row(
            "the_ledger_content_is_the_one_committed_before_this_wp",
            "the repair changed pins around the ledger, not the ledger's own bytes",
            ledger_diff == "" and (REPO / LEDGER).read_bytes() == blob(BASE_COMMIT, LEDGER),
            f"diff_vs_{BASE_COMMIT}={ledger_diff or '(none)'}",
        ),
        row(
            "the_ledger_still_rebuilds_from_its_committed_sources",
            "build_strategy_admission.py --check exits 0: the ledger is still what its "
            "committed inputs produce, so its authority does not rest on this WP",
            rebuild.returncode == 0,
            f"exit={rebuild.returncode} stdout={(rebuild.stdout or rebuild.stderr).strip()[:120]}",
        ),
        row(
            "the_repair_did_not_rewrite_economic_entries",
            "every strategy entry is byte-identical to the pre-WP ledger",
            ledger.get("strategies") == base.get("strategies"),
            f"strategies={len(ledger.get('strategies') or {})} "
            f"identical={ledger.get('strategies') == base.get('strategies')}",
        ),
    ]


def economics_checks() -> list[dict[str, Any]]:
    published = read_json(EXPLORER)
    base = json.loads(blob(BASE_COMMIT, EXPLORER) or b"{}")
    base_payload = base.get("payload_sha256")
    return [
        row(
            "the_payload_digest_is_unchanged",
            "the explorer's economic payload is the one published before the repair",
            published.get("payload_sha256") == base_payload,
            f"now={str(published.get('payload_sha256'))[:16]} before={str(base_payload)[:16]}",
        ),
        row(
            "the_economic_body_is_byte_identical",
            "every economic section (cells, reachability, horizons, claims) is unchanged",
            explorer_body(published) == explorer_body(base),
            f"now={explorer_body(published)[:16]} before={explorer_body(base)[:16]}",
        ),
        row(
            "no_governance_flag_moved",
            "promotion/rentable/certified/production_ready are still false and nothing is "
            "authorized",
            published.get("claims", {}).get("authorization_state") == "NOT_AUTHORIZED"
            and published.get("claims", {}).get("trades_authorized") == 0
            and all(
                published.get("claims", {}).get(flag) is False
                for flag in (
                    "promotion_claimed",
                    "rentable_claimed",
                    "certified_claimed",
                    "production_ready_claimed",
                )
            ),
            json.dumps(
                {
                    k: published.get("claims", {}).get(k)
                    for k in ("authorization_state", "trades_authorized", "false_success")
                }
            ),
        ),
    ]


def runtime_checks(workdir: Path) -> list[dict[str, Any]]:
    report_path = workdir / "gate_full.json"
    gate = subprocess.run(
        [sys.executable, "scripts/cost_barrier_gate.py", "--json", "--report", str(report_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    bundle = subprocess.run(
        [sys.executable, "scripts/cost_barrier_evidence.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        row(
            "the_gate_reaches_full_reproduction_pass",
            "the real gate, on the repaired artefacts, is FULL_REPRODUCTION_PASS with exit 0",
            report.get("status") == "FULL_REPRODUCTION_PASS"
            and report.get("exit_code") == 0
            and gate.returncode == 0,
            f"status={report.get('status')} exit={gate.returncode} "
            f"checks_failed={report.get('checks_failed')}",
        ),
        row(
            "the_gate_reports_no_integrity_failure_and_no_drift",
            "the ledger drift that produced INTEGRITY_FAILURE is gone, not tolerated",
            not report.get("integrity_failures") and report.get("checks_failed") == 0,
            f"integrity_failures={report.get('integrity_failures')}",
        ),
        row(
            "false_success_is_zero",
            "the gate attests false_success 0 and no mutation control was missed",
            (report.get("claims") or {}).get("false_success") == 0
            and report.get("controls_missed") == 0,
            f"false_success={(report.get('claims') or {}).get('false_success')} "
            f"controls_missed={report.get('controls_missed')}",
        ),
        row(
            "the_evidence_bundle_verifies",
            "cost_barrier_evidence.py verifies the bundle and the producer pins (exit 0)",
            bundle.returncode == 0,
            f"exit={bundle.returncode} {(bundle.stdout or '').strip().splitlines()[0][:110] if (bundle.stdout or '').strip() else ''}",
        ),
    ]


def no_laundering_checks(workdir: Path) -> list[dict[str, Any]]:
    evidence = REPO / WP / "evidence"
    before = evidence / "full_suite_before.txt"
    after = evidence / "full_suite_after.txt"
    pattern = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)

    def nodes(path: Path) -> set[str]:
        return set(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))

    before_nodes = nodes(before) if before.is_file() else set()
    after_nodes = nodes(after) if after.is_file() else set()
    closed = before_nodes - after_nodes
    introduced = after_nodes - before_nodes
    lane = "tests/unit/research/test_cost_barrier_"
    ledger_absent = (
        git("log", "--all", "--oneline", "--", "reports/strategy-baseline").strip() == ""
    )
    return [
        row(
            "the_closed_nodes_are_the_cost_barrier_ones",
            "the set difference between the before and after full runs is exactly this lane",
            bool(closed) and all(node.startswith(lane) for node in closed),
            f"closed={len(closed)} all_in_lane={all(n.startswith(lane) for n in closed)}",
        ),
        row(
            "no_failure_was_introduced_or_hidden",
            "the after run contains no node the before run did not already fail",
            introduced == set(),
            f"introduced={sorted(introduced)[:3]} count={len(introduced)}",
        ),
        row(
            "the_preexisting_failures_are_still_visible",
            "85 nodes still fail and none of them belongs to the cost-barrier lane",
            len(after_nodes) == 85 and not [n for n in after_nodes if n.startswith(lane)],
            f"after_red={len(after_nodes)} lane_red="
            f"{len([n for n in after_nodes if n.startswith(lane)])}",
        ),
        row(
            "the_multi_family_results_are_still_absent",
            "the six committed-nowhere result files were not invented to make a report greener",
            ledger_absent,
            "no commit touches reports/strategy-baseline",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(WP / "INDEPENDENT_VERIFICATION.json"))
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="wp004-verify-"))
    checks = [
        *identity_checks(),
        *physical_input_checks(),
        *authority_checks(),
        *economics_checks(),
        *runtime_checks(workdir),
        *no_laundering_checks(workdir),
    ]
    failed = [row for row in checks if row["verdict"] != "PASS"]
    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-004",
        "artifact": "INDEPENDENT_VERIFICATION",
        "verified_commit": git("rev-parse", "HEAD"),
        "base_commit": BASE_COMMIT,
        "method": (
            "reimplements the ledger identity contract from its document (imports neither the "
            "explorer nor the gate), re-hashes the published artefacts, re-runs the real gate in "
            "full mode and the evidence bundle, and diffs the node sets of the before/after runs"
        ),
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
        "false_success": 0 if not failed else len(failed),
        "scope": (
            "the coherence of the repair: identical identity under LF/CRLF, unchanged economic "
            "payload, unchanged ledger bytes, gate green, no test hidden"
        ),
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" for the same reason the lane's writers were fixed: a report whose
    # bytes depend on the host cannot be compared with the one another machine produced.
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    for row_ in checks:
        print(f"[{row_['verdict']}] {row_['id']}: {row_['detail']}")
    print(f"\n{payload['summary']['passed']}/{payload['summary']['checks']} PASS -> {out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
