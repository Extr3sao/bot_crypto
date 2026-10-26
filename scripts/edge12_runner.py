"""WP-EDGE-12B — evaluate the session-independent mechanisms, and write the operator set.

    python scripts/edge12_runner.py                  probe, preflight, decide, render
    python scripts/edge12_runner.py --preflight-only  render the preflight alone
    python scripts/edge12_runner.py --json            print the decision record

The probes register throwaway tasks under their own names, read them back from the
scheduler, run them on demand and delete them. **Nothing is applied to the live task**:
re-registering a running lane moves the phase a continuity reading measures, which makes
it an operator's deployment decision rather than a side effect of a certification.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.edge12 import evidence as ev
from trading_bot.research.edge12 import render, runner

TASK_NAME = "TradingAgentic-EDGE04-Forward"
PROPOSAL_FILENAME = "PROPOSED_DEFINITION.xml"
WP04R_PROPOSAL = (
    ev.REPO_ROOT
    / "reports"
    / "edge-recovery"
    / "WP-EDGE-04R"
    / "evidence"
    / "PROPOSED_FORWARD_TASK.xml"
)


def _registration_only(path: Path) -> str:
    """The carried-over registration, with this package's own witness path normalised out.

    The witness path points into the report directory of whichever work package rendered
    the definition, so comparing the raw bytes would answer "has another work package run?"
    instead of "has the host's registration moved?".
    """
    text = _read_definition(path)
    if not text:
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        if "witness" in line and "Arguments" in line:
            lines.append("      <Arguments>WITNESS_NORMALISED</Arguments>")
        else:
            lines.append(line)
    return "\n".join(lines)


def _read_definition(path: Path) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    return ""


def _runs(state_root: Path) -> list[dict[str, object]]:
    path = state_root / "runs.jsonl"
    rows: list[dict[str, object]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(ev.DEFAULT_REPORTS))
    parser.add_argument("--state-root", default=str(ev.DEFAULT_STATE_ROOT))
    parser.add_argument("--task-name", default=TASK_NAME)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="render the preflight and the decision from the stored probes, without re-probing",
    )
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    state_root = ev.repo_path(args.state_root)
    evidence_dir = reports / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    scratch = evidence_dir / "probe-scratch"

    from trading_bot.research.edge04r import session as session_probe

    host_evidence = ev.load_json(evidence_dir / "OS_EVIDENCE.json")
    if not host_evidence:
        from trading_bot.research.edge04r import os_evidence

        host_evidence = os_evidence.collect(task_name=args.task_name)
        ev.write_json(evidence_dir / "OS_EVIDENCE.json", host_evidence)

    witness_path = evidence_dir / "forward-witness.txt"
    proposal = session_probe.proposal_from_evidence(host_evidence, witness_path=witness_path)
    definition_path = evidence_dir / PROPOSAL_FILENAME
    # UTF-16 with a BOM, which is what `schtasks /xml` reads and what WP-EDGE-04R's
    # rehearsal committed: writing UTF-8 here would make the digests incomparable and the
    # apply command fail on the operator's machine rather than in this preflight.
    definition_path.write_text(str(proposal["xml"]), encoding="utf-16")

    # The definition is a function of the live registration, so it is also the check that
    # the live registration has not moved since WP-EDGE-04R rehearsed it. The comparison
    # normalises the witness path first: that path is this package's own report directory,
    # and a check that counted it would report "the host changed" every time a work package
    # number did.
    registered_now = _registration_only(definition_path)
    registered_then = _registration_only(WP04R_PROPOSAL)
    registration_unchanged = bool(
        registered_now and registered_then and registered_now == registered_then
    )
    committed_digest = ev.sha256_file(WP04R_PROPOSAL)
    current_digest = ev.sha256_file(definition_path)

    probes_path = evidence_dir / "RUNNER_PROBES.json"
    if args.preflight_only and probes_path.is_file():
        probes = ev.load_json(probes_path)
    else:
        probes = runner.mechanisms(
            repo_root=ev.REPO_ROOT,
            proposal_xml=str(proposal["xml"]),
            scratch=scratch,
            evidence=host_evidence,
            runs=_runs(state_root),
        )
        probes["registration_unchanged_since_wp_edge_04r"] = registration_unchanged
        probes["proposal_sha256_current"] = current_digest
        probes["proposal_sha256_rehearsed_by_wp_edge_04r"] = committed_digest
        ev.write_json(probes_path, probes)

    preflight = runner.preflight(
        repo_root=ev.REPO_ROOT,
        definition_path=definition_path,
        task_name=args.task_name,
        evidence=host_evidence,
        proposal={**proposal, "witness_path": str(witness_path)},
    )
    decision = runner.decide(probes=probes, preflight_row=preflight, evidence=host_evidence)
    decision["registration_unchanged_since_wp_edge_04r"] = registration_unchanged
    rollback = runner.rollback(
        task_name=args.task_name, evidence=host_evidence, definition_path=definition_path
    )
    handoff = runner.operator_handoff(
        decision=decision, rollback_row=rollback, proposal_path=definition_path
    )

    ev.write_json(reports / "RUNNER_PREFLIGHT.json", preflight)
    ev.write_json(evidence_dir / "RUNNER_DECISION.json", decision)
    (reports / "RUNNER_DECISION.md").write_text(
        render.runner_decision_md(
            decision=decision, probes=probes, preflight=preflight, evidence=host_evidence
        ),
        encoding="utf-8",
    )
    (reports / "OPERATOR_HANDOFF.md").write_text(
        render.operator_handoff_md(handoff), encoding="utf-8"
    )
    (reports / "ROLLBACK.md").write_text(render.rollback_md(rollback), encoding="utf-8")

    if args.json:
        print(
            json.dumps(
                {"decision": decision, "preflight": preflight},
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    print(f"selected          {decision['selected']}")
    print(f"S4U on this host  {decision['evaluations'][0]['verdict']}")
    print(f"available         {decision['available_without_new_privileges']}")
    print(f"blocked           {decision['blocked']}")
    print(
        f"preflight         {preflight['verdict']} ({len(preflight['blocking_failures'])} blocking)"
    )
    print(f"registration      unchanged since WP-EDGE-04R: {registration_unchanged}")
    print(f"probe leftovers   {probes['probe_tasks_left_behind'] or 'none'}")
    print(f"applied           {probes['applied_to_the_live_task']}")
    return 0 if preflight["verdict"] == "PREFLIGHT_PASS" else 5


if __name__ == "__main__":
    raise SystemExit(main())
