"""WP-EDGE-04R — probe which session-independent mechanisms this host actually allows.

    python scripts/edge04r_session.py                 probe and render
    python scripts/edge04r_session.py --no-probe      render from the stored probes
    python scripts/edge04r_session.py --json          print the probe record

The probes register a throwaway task under their own name, read it back from the
scheduler, run it once, delete it, and attempt the two host changes an operator would
have to approve (an S4U registration and the Task Scheduler's operational log). Nothing
touches the live lane's registration, its state root or its slot ledger.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge04r import session  # noqa: E402

REPORTS = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-04R"
PROBE_FILENAME = "SESSION_INDEPENDENCE.json"
MARKDOWN_FILENAME = "SESSION_INDEPENDENCE.md"
AUDIT_FILENAME = "EDGE04R_CONTINUITY_AUDIT.json"
EVIDENCE_FILENAME = "OS_CONTINUITY_EVIDENCE.json"
LIVE_TASK = "TradingAgentic-EDGE04-Forward"


def _repo_path(value: str | Path) -> Path:
    """Resolve a declared path against the repository root, not against whatever the cwd is.

    The probes register a scheduled task whose working directory is the repository root,
    while the command that takes the reading can be launched from anywhere. A relative
    path taken from the caller's cwd therefore lands somewhere else inside the task: the
    witness is written where the task looked and the check reads where the caller looked,
    so a witness action that ran is reported as one that never did. Anchoring to
    ``REPO_ROOT`` makes both agree no matter which directory the reading is taken from.
    """
    candidate = Path(value)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _render(payload: dict[str, Any]) -> str:
    mechanisms = payload["classification"]["mechanisms"]
    proposal = payload["proposal"]
    rehearsal = next(
        row for row in payload["probes"] if row.get("mechanism") == "PROPOSED_DEFINITION"
    )
    lines = [
        "# WP-EDGE-04R — session independence: what this host allows",
        "",
        "Each mechanism below was **attempted**, not assumed: the probe's own output is in",
        f"`evidence/{PROBE_FILENAME}`. Verdicts are `VIABLE` (exercised here), `NEEDS_ELEVATION`,",
        "`NEEDS_CREDENTIALS`, `NOT_APPLICABLE`.",
        "",
        "| mechanism | verdict | what it needs |",
        "| --- | --- | --- |",
    ]
    for name in sorted(mechanisms):
        row = mechanisms[name]
        detail = str(row.get("detail") or "").replace("\n", " ")
        lines.append(f"| `{name}` | `{row.get('verdict')}` | {detail[:220]} |")
    lines += [
        "",
        f"Viable without new privileges: {', '.join(payload['classification']['viable']) or 'none'}.",
        f"Blocked: {', '.join(payload['classification']['blocked']) or 'none'}.",
        "",
        "## What each one buys, priced from the audit",
        "",
        f"* **Trigger loss in the measured window:** "
        f"{payload['recommendation']['no_session_triggers_lost']} triggers lost to an absent session, "
        f"{payload['recommendation']['unattributable_triggers_lost']} unattributable.",
        f"* **Worst measured recovery after a sign-in:** "
        f"{payload['recommendation']['worst_recovery_latency_seconds']} s.",
        f"* **Logon trigger:** {payload['recommendation']['what_the_logon_trigger_buys']}",
        f"* **S4U:** {payload['recommendation']['what_s4u_would_buy']}",
        f"* **Witness action:** {payload['recommendation']['what_the_witness_buys']}",
        "",
        "## The definition this package would apply, and what the rehearsal found",
        "",
        f"`evidence/{proposal['filename']}` — {proposal['bytes']} bytes, sha256 "
        f"`{proposal['sha256']}`. It is rendered from the lane's own registration, so applying it "
        "changes which instants can start and nothing about what the lane does when it starts:",
        "",
        "* carried over: "
        + ", ".join(
            f"{key}={value}"
            for key, value in proposal["carried_over_from_the_registration"].items()
            if value not in ("", None)
        ),
        "* added: " + "; ".join(proposal["added"]),
        "",
        "| rehearsal (`" + rehearsal["task_name"] + "`) | measured |",
        "| --- | --- |",
        f"| verdict | `{rehearsal['verdict']}` |",
        "| trigger kinds the scheduler reported back | "
        + ", ".join(rehearsal["trigger_kinds"])
        + " |",
        f"| actions, in the order they run | {rehearsal['action_count']} |",
        f"| witness line written before the long action | {rehearsal['witness_file_written']} |",
        f"| task deleted after the rehearsal | {rehearsal['deleted_after_the_probe']} |",
        f"| lines the rehearsal moved from the committed definition | "
        f"{rehearsal['lines_the_rehearsal_moved_from_the_proposal']} |",
        "",
        "The rehearsal registers a copy of the committed definition whose only difference is the "
        "action payload: running the lane's own action there would let a rehearsal write an "
        f"out-of-phase tick into the ledger this audit measures, so it carries "
        f"`{proposal['payload_overridden_for_the_rehearsal']['command']} "
        f"{proposal['payload_overridden_for_the_rehearsal']['arguments']}` instead. Everything "
        "else — both triggers, the principal, the settings, the order of the actions, the witness "
        "path — is the committed bytes.",
        "",
        "## What was not applied, and why",
        "",
        payload["recommendation"]["not_applied"],
        "",
        f"The command that would apply it, once an operator decides to: `{proposal['apply_command']}`"
        " — it re-registers the live task (in place, `/f`), so it stays an operator decision: "
        f"`{payload['recommendation']['apply_command']}`",
        "",
        "## The honest bound",
        "",
        payload["bound"],
        "",
        "Research only: public market data, no credentials, no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(REPORTS))
    parser.add_argument("--no-probe", action="store_true", help="render the stored probe record")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--task-name", default=LIVE_TASK)
    args = parser.parse_args(argv)

    reports = _repo_path(args.reports)
    probe_path = reports / "evidence" / PROBE_FILENAME
    evidence_path = reports / "evidence" / EVIDENCE_FILENAME
    audit_path = reports / "evidence" / AUDIT_FILENAME

    if args.no_probe:
        if not probe_path.is_file():
            print(f"no stored probe record at {probe_path}", file=sys.stderr)
            return 3
        payload = json.loads(probe_path.read_text(encoding="utf-8"))
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return 0
        print(f"mechanisms   {', '.join(sorted(payload['classification']['mechanisms']))}")
        print(f"viable       {', '.join(payload['classification']['viable']) or 'none'}")
        print(f"blocked      {', '.join(payload['classification']['blocked']) or 'none'}")
        return 0

    evidence = (
        json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
    if not audit:
        print(
            "the continuity audit is missing: run scripts/edge04r_continuity.py first",
            file=sys.stderr,
        )
        return 4

    scratch = reports / "evidence" / "probe-scratch"
    # The audit owns the count of triggers this window should have fired; the probes quote it
    # rather than restating it, so the two records cannot drift apart. The key is the audit's
    # own (``trigger_loss.expected``): naming a key the audit does not carry would silently
    # fall back to the unnumbered sentence and read as if the count were unavailable.
    window_instants = int((audit.get("trigger_loss") or {}).get("expected") or 0) or None
    # The definition an operator would apply, rendered from the lane's own frozen registration.
    # It is written in the form the scheduler consumes (the definition declares UTF-16), and the
    # rehearsal registers a copy of it whose only difference is the action payload: running the
    # lane's own action here would let a rehearsal write an out-of-phase tick into the ledger the
    # audit measures.
    witness = reports / "evidence" / "forward-witness.txt"
    proposal = session.proposal_from_evidence(evidence, witness_path=witness)
    rehearsal = session.proposal_from_evidence(
        evidence,
        witness_path=witness,
        command=session.INERT_COMMAND,
        arguments=session.INERT_ARGUMENTS,
    )
    proposal_path = reports / "evidence" / session.PROPOSAL_FILENAME
    proposal_path.write_text(proposal["xml"], encoding="utf-16")
    proposal["sha256"] = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    proposal["bytes"] = proposal_path.stat().st_size

    probes = [
        session.probe_logon_trigger_registration(scratch=scratch),
        session.probe_witness_action(scratch=scratch, window_instants=window_instants),
        session.probe_proposed_definition(
            proposal=proposal,
            rehearsal_xml=rehearsal["xml"],
            probe_name=f"{session.PROBE_TASK_NAME}-Proposal",
            witness=witness,
        ),
        session.probe_s4u_registration(scratch=scratch),
        session.probe_task_history_log(window_instants=window_instants),
    ]
    sleep_pairs = int(
        ((evidence.get("windows") or {}).get("counts") or {}).get("sleep_resume_pairs")
        or _count_sleep(evidence)
    )
    autologon = evidence.get("autologon") or {}
    classification = session.classify(probes, autologon=autologon, sleep_pairs=sleep_pairs)
    payload = {
        "schema_version": session.SESSION_SCHEMA_VERSION,
        "live_task_name": args.task_name,
        "probes": probes,
        "proposal": proposal,
        "classification": classification,
        "recommendation": session.recommendation(
            audit=audit, probes=classification, task_name=args.task_name
        ),
        "bound": (
            "No mechanism available to this work package removes the cost of the host being "
            "unavailable or of nobody being signed in. The measured window lost "
            f"{((audit.get('trigger_loss') or {}).get('causes') or {}).get('NO_SESSION', 0)} "
            "triggers to an absent session; the only two mechanisms that would have scheduled "
            "through it are an S4U task (needs the batch-logon right) and automatic logon (needs "
            "a stored password). Everything else recovers minutes around the edges."
        ),
        "hypothetical": True,
        "order_sent": False,
    }
    _write_json(probe_path, payload)
    (reports / MARKDOWN_FILENAME).write_text(_render(payload), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    print(f"viable       {', '.join(classification['viable']) or 'none'}")
    print(f"blocked      {', '.join(classification['blocked']) or 'none'}")
    for name, row in sorted(classification["mechanisms"].items()):
        print(f"  {name:<34} {row.get('verdict')}")
    return 0


def _count_sleep(evidence: dict[str, Any]) -> int:
    powers = evidence.get("power") or []
    return sum(1 for row in powers if int(row.get("id") or 0) == 42)


if __name__ == "__main__":
    raise SystemExit(main())
