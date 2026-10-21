"""verify_paper_e2e — the independent verifier for WP-003-03.

It does not produce evidence; it judges the bundle ``paper_e2e_lab.py`` wrote.
The separation is the point: the lab may be wrong, and a verifier that shares
its functions would be wrong in the same way.

    python scripts/verify_paper_e2e.py \
        --lab reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/PAPER_E2E_LAB.json \
        --bundle reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303 \
        --repo . --evidence-sha <commit> --negative-controls \
        --json /tmp/wp00303_verification.json

Exit code: 0 PASS, 1 FAIL, 2 PARTIAL (a check could not be evaluated, e.g. no
evidence commit given).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

RUNTIME_FILES = (
    "src/trading_bot/autonomous/runtime.py",
    "src/trading_bot/autonomous/decision.py",
    "src/trading_bot/autonomous/verifier.py",
    "src/trading_bot/autonomous/agents.py",
    "src/trading_bot/autonomous/admission_ledger.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/paper/paper_state_store.py",
    "src/trading_bot/paper/reconciliation_v4.py",
    "src/trading_bot/paper/snapshot_history.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/scanner/scanner.py",
    "src/trading_bot/execution/isolation.py",
    "src/trading_bot/execution/idempotency.py",
)

E2E_MODES = ("E2E-COMMITTED", "E2E-SCENARIO", "E2E-RESTART")
ABUSE_MODES = (
    "ABUSE-CONNECTOR-ORDER",
    "ABUSE-FUTURES-ORDER",
    "ABUSE-APP-ORDER",
    "ABUSE-DELEGATION",
    "ABUSE-RECONNECT",
    "ABUSE-RETRY",
    "ABUSE-NO-CREDENTIALS",
    "ABUSE-POLICY-WEAKEN",
)
SYNC_STATUSES = {"LOCAL_COMMITTED", "REMOTE_BRANCH_SYNCED", "MAIN_SYNCED", "GITHUB_BLOCKED"}
REFUSAL_OUTCOMES = {"REFUSED", "DENIED"}
MANIFEST_EXCLUDED = {"EVIDENCE_MANIFEST.json", "VERIFICATION.json"}
SYNC_EXCLUDED = {"VERIFICATION.json", "EVIDENCE_MANIFEST.json"}


Check = Callable[[dict[str, Any], dict[str, Any]], tuple[bool, str]]


class _Blocked(Exception):
    """A check that cannot be evaluated (missing input), never a PASS."""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _bundle_files(bundle: Path) -> list[str]:
    return sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and not path.name.endswith(".tmp")
    )


# -- checks --------------------------------------------------------------------


def check_lab_shape(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    scenarios = bundle.get("scenarios") or {}
    abuse = bundle.get("abuse") or {}
    missing = [mode for mode in E2E_MODES if mode not in scenarios]
    missing += [mode for mode in ABUSE_MODES if mode not in abuse]
    failed = [
        name
        for name, payload in list(scenarios.items()) + list(abuse.items())
        if (payload or {}).get("status") != "OK"
    ]
    bad_rc = [
        name
        for name, payload in list(scenarios.items()) + list(abuse.items())
        if (payload or {}).get("returncode") not in (0, None)
    ]
    ok = not missing and not failed and not bad_rc
    return ok, (
        "all scenarios present, completed and exited 0"
        if ok
        else f"missing={missing} failed={failed} bad_rc={bad_rc}"
    )


def check_runtime_identity(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    recorded = bundle.get("runtime_sha256") or {}
    repo = context.get("repo")
    if repo is None:
        raise _Blocked("no repository given: runtime identity not checked")
    current = {rel: _sha(repo / rel) for rel in RUNTIME_FILES}
    if not recorded:
        return False, "no runtime hashes recorded"
    missing = [rel for rel in RUNTIME_FILES if rel not in recorded]
    mismatched = [rel for rel in RUNTIME_FILES if recorded.get(rel) != current[rel]]
    ok = not missing and not mismatched
    return ok, (
        f"{len(RUNTIME_FILES)} runtime files hashed and unchanged"
        if ok
        else f"missing={missing} mismatched={mismatched}"
    )


def check_dataset_identity(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    repo = context.get("repo")
    dataset = bundle.get("dataset") or {}
    symbols = dataset.get("symbols") or {}
    if not symbols:
        return False, "no dataset recorded"
    problems: list[str] = []
    if repo is not None:
        for symbol, row in symbols.items():
            path = repo / str(row.get("file") or "")
            if not path.exists():
                problems.append(f"{symbol}: missing {row.get('file')}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row.get("sha256"):
                problems.append(f"{symbol}: sha256 {digest[:12]} != recorded")
            manifest_digest = str(row.get("manifest_sha256") or "")
            if not manifest_digest or row.get("sha256") != manifest_digest:
                problems.append(f"{symbol}: does not match the fetch manifest")
            if not row.get("matches_manifest"):
                problems.append(f"{symbol}: matches_manifest is false")
    else:
        problems = [
            f"{symbol}: matches_manifest is false"
            for symbol, row in symbols.items()
            if not row.get("matches_manifest")
        ]
    ok = not problems
    return ok, (
        f"{len(symbols)} recorded series match the fetch manifest"
        if ok
        else "; ".join(problems[:4])
    )


def check_committed_no_trade(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    payload = (bundle.get("scenarios") or {}).get("E2E-COMMITTED") or {}
    decisions = payload.get("decisions") or {}
    rows = decisions.get("rows") or []
    orders = int((payload.get("executions") or {}).get("count") or 0)
    fills = payload.get("fills") or {}
    trading = [row for row in rows if row.get("mode") in {"TRADE_PAPER"}]
    shadow = [row for row in rows if row.get("mode") == "SHADOW_TRADE"]
    ledger = payload.get("ledger") or {}
    reasons = [row.get("reason") for row in rows if row.get("mode") == "NO_TRADE"]
    ok = (
        orders == 0
        and int(fills.get("opened") or 0) == 0
        and int(fills.get("closed") or 0) == 0
        and not trading
        and len(rows) > 0
        and ledger.get("ledger_kind") == "committed"
        and all(bool(row.get("no_trade_kind")) for row in rows if row.get("mode") == "NO_TRADE")
        and all(bool(reason) for reason in reasons)
    )
    return ok, (
        f"orders=0 fills=0 decisions={len(rows)} trade_decisions=0 shadow={len(shadow)} "
        f"admitted_for_paper={ledger.get('paper_candidates')}"
    )


def check_scenario_reached_broker(
    bundle: dict[str, Any], context: dict[str, Any]
) -> tuple[bool, str]:
    payload = (bundle.get("scenarios") or {}).get("E2E-SCENARIO") or {}
    decisions = payload.get("decisions") or {}
    rows = decisions.get("rows") or []
    trades = [row for row in rows if row.get("mode") == "TRADE_PAPER"]
    orders = int((payload.get("executions") or {}).get("count") or 0)
    fills = payload.get("fills") or {}
    closed = fills.get("closed_trades") or []
    ledger = payload.get("ledger") or {}
    scenario_ledger = payload.get("scenario_ledger") or {}
    ok = (
        orders > 0
        and int(fills.get("opened") or 0) > 0
        and len(trades) > 0
        and len(closed) > 0
        and ledger.get("ledger_kind") == "scenario"
        and scenario_ledger.get("_scenario") is True
    )
    return ok, (
        f"orders={orders} trade_decisions={len(trades)} fills_opened={fills.get('opened')} "
        f"fills_closed={fills.get('closed')} closed_trades={len(closed)} "
        f"scenario_ledger={scenario_ledger.get('_scenario')}"
    )


def check_no_orphan_fills(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    payload = (bundle.get("scenarios") or {}).get("E2E-SCENARIO") or {}
    rows = (payload.get("decisions") or {}).get("rows") or []
    executions = (payload.get("executions") or {}).get("rows") or []
    ordered = {row["decision_id"] for row in rows if row.get("order_created")}
    orphan = [row for row in executions if row.get("decision_id") not in ordered]
    unexecuted = [
        row for row in rows if row.get("mode") == "TRADE_PAPER" and not row.get("order_created")
    ]
    unexplained = [row for row in unexecuted if not row.get("errors")]
    cloids = [row.get("cloid") for row in executions]
    duplicated = {value for value in cloids if cloids.count(value) > 1}
    ok = not orphan and not unexplained and not duplicated
    return ok, (
        f"executions={len(executions)} orders_recorded={len(ordered)} "
        f"unexecuted_with_reason={len(unexecuted)} orphan={len(orphan)} "
        f"duplicate_cloids={len(duplicated)}"
    )


def check_accounting(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    payload = (bundle.get("scenarios") or {}).get("E2E-SCENARIO") or {}
    accounting = payload.get("accounting") or {}
    identities = accounting.get("identities") or {}
    closed = (payload.get("fills") or {}).get("closed_trades") or []
    commissions = sum(
        float(row.get("entry_commission") or 0.0) + float(row.get("exit_commission") or 0.0)
        for row in closed
    )
    realised = sum(float(row.get("pnl") or 0.0) for row in closed)
    reported = float(accounting.get("realised_pnl") or 0.0)
    fees_positive = all(float(row.get("total_cost_usdt") or 0.0) > 0 for row in closed)
    ok = (
        bool(identities)
        and all(identities.values())
        and commissions > 0
        and fees_positive
        and abs(realised - reported) <= 1e-6
    )
    return ok, (
        f"identities={sum(1 for value in identities.values() if value)}/{len(identities)} "
        f"commissions={commissions:.6f} realised={reported:.6f} recomputed={realised:.6f}"
    )


def check_risk_before_order(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    payload = (bundle.get("scenarios") or {}).get("E2E-SCENARIO") or {}
    rows = (payload.get("decisions") or {}).get("rows") or []
    problems: list[str] = []
    for row in rows:
        if row.get("order_created") and row.get("risk_state") != "APPROVED":
            problems.append(f"{row.get('decision_id')}: order with risk={row.get('risk_state')}")
        if row.get("mode") == "NO_TRADE" and row.get("order_created"):
            problems.append(f"{row.get('decision_id')}: NO_TRADE created an order")
        # An approved review with no order is legitimate only when the decision
        # engine refused on economics; it must still name a classification.
        if (
            row.get("mode") == "NO_TRADE"
            and row.get("risk_state") == "APPROVED"
            and not row.get("classification")
        ):
            problems.append(f"{row.get('decision_id')}: approved review, no classification")
    approved_orders = sum(
        1 for row in rows if row.get("order_created") and row.get("risk_state") == "APPROVED"
    )
    ok = not problems
    return ok, (
        f"orders_after_approved_risk={approved_orders} violations=0"
        if ok
        else "; ".join(problems[:3])
    )


def check_restart(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    payload = (bundle.get("scenarios") or {}).get("E2E-RESTART") or {}
    restart = payload.get("restart") or {}
    reconciliation = restart.get("reconciliation") or {}
    persisted = restart.get("persisted") or {}
    recovered = restart.get("recovered") or {}
    phase1 = set(restart.get("phase1_cloids") or [])
    phase2_rows = (payload.get("executions") or {}).get("rows") or []
    phase2 = {row.get("cloid") for row in phase2_rows}
    duplicated = phase1 & phase2
    status = reconciliation.get("status")
    ok = (
        status in {"CONSISTENT", "RECOVERED", "DUPLICATE_SUPPRESSED"}
        and not duplicated
        and int(recovered.get("closed_trades") or 0) == int(persisted.get("closed_trades") or 0)
        and int(recovered.get("fills_opened") or 0) == int(persisted.get("fills_opened") or 0)
        and int(recovered.get("intents") or 0) >= int(persisted.get("intents") or 0)
        and abs(float(restart.get("equity_delta") or 0.0)) < 1e-9
    )
    return ok, (
        f"status={status} persisted_intents={persisted.get('intents')} "
        f"recovered_intents={recovered.get('intents')} duplicated_cloids={len(duplicated)} "
        f"equity_delta={restart.get('equity_delta')}"
    )


def check_error_path(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    probe = ((bundle.get("scenarios") or {}).get("E2E-COMMITTED") or {}).get("error_probe") or {}
    orders = int(probe.get("orders_created") or 0)
    fills = int(probe.get("broker_fills_opened") or 0)
    executions = probe.get("executions") or []
    decisions = probe.get("decisions") or {}
    trading = (decisions.get("by_mode") or {}).get("TRADE_PAPER", 0)
    ok = (
        orders == 0
        and fills == 0
        and not executions
        and trading == 0
        and int(decisions.get("count") or 0) > 0
    )
    return ok, (
        f"cycles={probe.get('cycles_completed')} orders={orders} fills={fills} "
        f"executions={len(executions)} trade_decisions={trading} "
        f"decisions={decisions.get('count')} errors={len(probe.get('cycle_errors') or [])}"
    )


def check_network(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    scenarios = bundle.get("scenarios") or {}
    for name in E2E_MODES:
        payload = scenarios.get(name) or {}
        if payload.get("network_log"):
            problems.append(f"{name}: {len(payload.get('network_log') or [])} audited events")
        isolation = payload.get("isolation") or {}
        policy = isolation.get("policy") or {}
        if not isolation.get("installed"):
            problems.append(f"{name}: isolation not installed")
        if policy.get("mode") != "paper":
            problems.append(f"{name}: policy mode {policy.get('mode')!r}")
        for key in ("external_network", "loopback_network", "order_routes"):
            if policy.get(key):
                problems.append(f"{name}: policy allows {key}")
        attempts = isolation.get("attempts") or []
        denied = [row for row in attempts if row.get("decision") in {"DENY"}]
        if denied:
            problems.append(f"{name}: {len(denied)} denied attempt(s) during the run")
    claims = bundle.get("claims") or {}
    if claims.get("LIVE_ORDERS") != "NONE":
        problems.append(f"claims.LIVE_ORDERS={claims.get('LIVE_ORDERS')!r}")
    ok = not problems
    return ok, (
        "no audited network event; strict paper policy in every child"
        if ok
        else "; ".join(problems[:4])
    )


def check_abuse(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    abuse = bundle.get("abuse") or {}
    problems: list[str] = []
    if set(abuse) != set(ABUSE_MODES):
        problems.append(f"scenarios={sorted(set(ABUSE_MODES) - set(abuse))}")
    refusals = 0
    for mode in ABUSE_MODES:
        payload = abuse.get(mode) or {}
        order_attempts = payload.get("order_attempts") or {}
        guard_attempts = payload.get("guard_attempts") or {}
        if not order_attempts:
            problems.append(f"{mode}: no order attempt recorded")
        for group, attempts in (("order", order_attempts), ("guard", guard_attempts)):
            for name, outcome in attempts.items():
                if not isinstance(outcome, dict):
                    problems.append(f"{mode}.{name}: malformed attempt")
                    continue
                if outcome.get("outcome") not in REFUSAL_OUTCOMES:
                    problems.append(f"{mode}.{name}={outcome.get('outcome')}")
                else:
                    refusals += 1
                if group == "order" and outcome.get("venue_calls"):
                    problems.append(f"{mode}.{name}: venue calls recorded")
        if payload.get("venue_calls"):
            problems.append(f"{mode}: venue saw {payload.get('venue_calls')}")
        if int(payload.get("http_calls") or 0) > 0:
            problems.append(f"{mode}: {payload.get('http_calls')} HTTP calls")
    ok = not problems
    return ok, (
        f"{refusals} refusals across {len(abuse)} scenarios; zero venue calls"
        if ok
        else "; ".join(problems[:5])
    )


def check_pit(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    total = 0
    for name in E2E_MODES:
        rows = ((bundle.get("scenarios") or {}).get(name) or {}).get("decisions", {}).get(
            "rows"
        ) or []
        for row in rows:
            total += 1
            if int(row.get("decision_time_ms") or 0) < int(row.get("market_time_ms") or 0):
                problems.append(f"{name}:{row.get('decision_id')}")
    ok = total > 0 and not problems
    return ok, (
        f"{total} decisions satisfy decision_time >= market_time"
        if ok
        else f"violations={problems[:3]} total={total}"
    )


def check_reproducible(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    repeat = context.get("repeat")
    digests = {
        name: ((bundle.get("scenarios") or {}).get(name) or {}).get("economic_digest")
        for name in E2E_MODES
    }
    missing = [name for name, digest in digests.items() if not digest or len(str(digest)) != 64]
    if repeat is None:
        if missing:
            return False, f"missing digests: {missing}"
        raise _Blocked("no repeat run given: determinism not checked across runs")
    repeat_digests = {
        name: ((repeat.get("scenarios") or {}).get(name) or {}).get("economic_digest")
        for name in E2E_MODES
    }
    different = [name for name in E2E_MODES if digests.get(name) != repeat_digests.get(name)]
    ok = not missing and not different
    return ok, (
        "economic digests identical across two independent runs"
        if ok
        else f"missing={missing} different={different}"
    )


def check_evidence_in_commit(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    repo = context.get("repo")
    sha = context.get("evidence_sha")
    bundle_dir = context.get("bundle_dir")
    if repo is None or bundle_dir is None:
        raise _Blocked("no repository or bundle path: evidence commit not checked")
    if not sha:
        raise _Blocked("no evidence commit given: evidence commit not checked")
    import subprocess

    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", sha], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        return False, f"git ls-tree {sha} failed: {proc.stderr.strip()[:200]}"
    tracked = set(proc.stdout.splitlines())
    prefix = bundle_dir.resolve().relative_to(repo.resolve()).as_posix()
    files = _bundle_files(bundle_dir)
    absent = [
        name
        for name in files
        if name not in MANIFEST_EXCLUDED and f"{prefix}/{name}" not in tracked
    ]
    ok = not absent
    return ok, (
        f"{len(files)} evidence files, all inside {sha[:8]}"
        if ok
        else f"{len(absent)} not in the commit: {absent[:4]}"
    )


def check_manifest(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    bundle_dir = context.get("bundle_dir")
    if bundle_dir is None:
        raise _Blocked("no bundle path: manifest not checked")
    manifest_path = bundle_dir / "EVIDENCE_MANIFEST.json"
    if not manifest_path.exists():
        return False, "EVIDENCE_MANIFEST.json is missing"
    manifest = _read_json(manifest_path)
    files = _bundle_files(bundle_dir)
    expected = [name for name in files if name not in MANIFEST_EXCLUDED]
    entries = manifest.get("files") or {}
    absent = [name for name in expected if name not in entries]
    wrong = [
        name for name in expected if name in entries and _sha(bundle_dir / name) != entries[name]
    ]
    stale = [name for name in entries if name not in expected]
    ok = not absent and not wrong and not stale
    return ok, (
        f"{len(expected)} files hashed, manifest complete"
        if ok
        else f"absent={absent[:3]} wrong={wrong[:3]} stale={stale[:3]}"
    )


def check_reports(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    reports_dir = context.get("reports_dir")
    if reports_dir is None:
        raise _Blocked("no reports directory: reports not checked")
    run_report_path = reports_dir / "RUN_REPORT.json"
    final_report_path = reports_dir / "FINAL_REPORT.json"
    if not run_report_path.exists() or not final_report_path.exists():
        return False, "RUN_REPORT.json or FINAL_REPORT.json missing"
    run_report = _read_json(run_report_path)
    final_report = _read_json(final_report_path)
    scenario = (bundle.get("scenarios") or {}).get("E2E-SCENARIO") or {}
    committed = (bundle.get("scenarios") or {}).get("E2E-COMMITTED") or {}
    expected = {
        "scenario_orders": int((scenario.get("executions") or {}).get("count") or 0),
        "scenario_fills_closed": int((scenario.get("fills") or {}).get("closed") or 0),
        "committed_orders": int((committed.get("executions") or {}).get("count") or 0),
        "decisions": int((scenario.get("decisions") or {}).get("count") or 0),
    }
    paper = run_report.get("paper") or {}
    mismatched = [key for key, value in expected.items() if int(paper.get(key, -1)) != int(value)]
    dimensions = final_report.get("dimensions") or {}
    required = {
        "IMPLEMENTATION_STATUS",
        "TEST_STATUS",
        "RUNTIME_VALIDATION",
        "NETWORK_ISOLATION",
        "EXTERNAL_ORDER_PREVENTION",
        "INDEPENDENT_VERIFICATION",
        "PAPER_VALIDATION",
        "GITHUB_SYNC",
        "FALSE_SUCCESS",
    }
    missing = sorted(required - set(dimensions))
    status_only = [
        name
        for name, value in dimensions.items()
        if str(value.get("result", "")).startswith("PASS") and not value.get("basis")
    ]
    ok = not mismatched and not missing and not status_only
    return ok, (
        f"reports match the lab ({expected}); 9 separated dimensions present"
        if ok
        else f"mismatched={mismatched} missing_dims={missing} unsupported={status_only}"
    )


def check_github_sync(bundle: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    sync = context.get("github_sync")
    if sync is None:
        raise _Blocked("no GITHUB_SYNC.json: remote state not checked")
    required = {
        "repository",
        "local_branch",
        "remote_branch",
        "local_head_sha",
        "remote_head_sha",
        "default_branch_sha",
        "commits_pending",
        "push_result",
        "sync_status",
        "verification_timestamp",
    }
    missing = sorted(required - set(sync))
    if missing:
        return False, f"missing keys: {missing}"
    status = sync.get("sync_status")
    if status not in SYNC_STATUSES:
        return False, f"sync_status={status!r} not one of {sorted(SYNC_STATUSES)}"
    local = str(sync.get("local_head_sha") or "")
    remote = str(sync.get("remote_head_sha") or "")
    default = str(sync.get("default_branch_sha") or "")
    if len(local) != 40:
        return False, "local_head_sha is not a 40-character sha"
    if "github.com" not in str(sync.get("repository")):
        return False, f"repository {sync.get('repository')!r} is not a GitHub URL"
    if status in {"REMOTE_BRANCH_SYNCED", "MAIN_SYNCED"}:
        if remote and remote != local:
            return False, f"claims {status} but remote {remote[:8]} != local {local[:8]}"
        if not remote:
            return False, f"claims {status} without a remote sha"
    if status == "MAIN_SYNCED" and default != local:
        return False, f"claims MAIN_SYNCED but default branch is {default[:8]}"
    if status in {"LOCAL_COMMITTED", "GITHUB_BLOCKED"} and str(sync.get("main_synced")) not in {
        "NO",
        "false",
        "False",
    }:
        return False, "not synced but main_synced is not NO"
    if not str(sync.get("verification_timestamp") or "").endswith("Z"):
        return False, "verification_timestamp is not UTC ISO-8601"
    return True, (
        f"{status}: local={local[:8]} remote={remote[:8] or '-'} "
        f"default={default[:8] or '-'} pending={sync.get('commits_pending')}"
    )


CHECKS: tuple[tuple[str, Check], ...] = (
    ("lab_shape", check_lab_shape),
    ("runtime_identity", check_runtime_identity),
    ("dataset_identity", check_dataset_identity),
    ("committed_ledger_no_trade", check_committed_no_trade),
    ("scenario_reached_broker", check_scenario_reached_broker),
    ("no_orphan_fills", check_no_orphan_fills),
    ("accounting_identities", check_accounting),
    ("risk_before_order", check_risk_before_order),
    ("restart_reconciled", check_restart),
    ("error_path_closed", check_error_path),
    ("no_external_network", check_network),
    ("abuse_battery", check_abuse),
    ("pit_holds", check_pit),
    ("reproducible_evidence", check_reproducible),
    ("evidence_in_commit", check_evidence_in_commit),
    ("manifest_covers", check_manifest),
    ("reports_consistent", check_reports),
    ("github_sync_consistent", check_github_sync),
)


def verify(bundle: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for name, function in CHECKS:
        try:
            ok, detail = function(bundle, context)
        except _Blocked as exc:
            results.append({"check": name, "ok": False, "blocked": True, "detail": str(exc)})
            continue
        except Exception as exc:  # a broken check is a failure, never a pass
            results.append(
                {
                    "check": name,
                    "ok": False,
                    "blocked": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        results.append({"check": name, "ok": bool(ok), "blocked": False, "detail": str(detail)})
    failed = [row for row in results if not row["ok"]]
    blocked = [row for row in failed if row.get("blocked")]
    if not failed:
        verdict = "PASS"
    elif blocked and len(blocked) == len(failed):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return {
        "schema": "wp00303-verification/1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "checks": results,
        "failed": [row["check"] for row in failed],
        "blocked": [row["check"] for row in blocked],
        "unsupported_pass_count": 0 if verdict == "PASS" else len(failed),
    }


# -- negative controls ---------------------------------------------------------


def _mutations() -> dict[str, Callable[[dict[str, Any], dict[str, Any]], None]]:
    def invent_an_order(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        committed = lab["scenarios"]["E2E-COMMITTED"]
        committed["executions"]["count"] = 1
        committed["executions"]["rows"] = [
            {"symbol": "BTC/USDT", "decision_id": "invented", "cloid": "invented"}
        ]

    def flip_committed_to_trade(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        row = lab["scenarios"]["E2E-COMMITTED"]["decisions"]["rows"][0]
        row["mode"] = "TRADE_PAPER"
        row["no_trade_kind"] = None

    def move_a_cent(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        accounting = lab["scenarios"]["E2E-SCENARIO"]["accounting"]
        accounting["ledger_equity"] = float(accounting["ledger_equity"]) + 0.01
        accounting["identities"]["ledger_equity_equals_initial_plus_realised"] = False

    def orphan_fill(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        scenario = lab["scenarios"]["E2E-SCENARIO"]
        scenario["executions"]["rows"].append(
            {"symbol": "ETH/USDT", "decision_id": "not-a-decision", "cloid": "orphan"}
        )
        scenario["executions"]["count"] = len(scenario["executions"]["rows"])

    def zero_the_fees(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        for row in lab["scenarios"]["E2E-SCENARIO"]["fills"]["closed_trades"]:
            row["entry_commission"] = 0.0
            row["exit_commission"] = 0.0

    def duplicate_after_restart(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        restart = lab["scenarios"]["E2E-RESTART"]["restart"]
        restart["phase2_cloids"] = list(restart["phase1_cloids"])
        restart["reconciliation"]["status"] = "MISMATCH"

    def sneak_a_connection(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        lab["scenarios"]["E2E-SCENARIO"]["network_log"].append(
            {"event": "socket.connect", "host": "api.binance.com", "decision": "DENY"}
        )

    def falsify_the_dataset(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        lab["dataset"]["symbols"]["BTC/USDT"]["sha256"] = "0" * 64

    def claim_a_sync_that_did_not_happen(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        ctx["github_sync"] = {
            "repository": "https://github.com/Extr3sao/bot_crypto.git",
            "local_branch": "wp/isolation-005",
            "remote_branch": "wp/isolation-005",
            "local_head_sha": "0" * 40,
            "remote_head_sha": "1" * 40,
            "default_branch_sha": "2" * 40,
            "commits_pending": 1,
            "push_result": "ok",
            "sync_status": "REMOTE_BRANCH_SYNCED",
            "verification_timestamp": "2026-01-01T00:00:00Z",
            "main_synced": "NO",
        }

    def allow_an_order_in_the_error_path(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        probe = lab["scenarios"]["E2E-COMMITTED"]["error_probe"]
        probe["orders_created"] = 1
        probe["executions"] = [{"decision_id": "error-path-order"}]

    def accept_a_blocked_check(lab: dict[str, Any], ctx: dict[str, Any]) -> None:
        ctx["evidence_sha"] = ""

    return {
        "NEG-01-invented-order": invent_an_order,
        "NEG-02-committed-turned-trade": flip_committed_to_trade,
        "NEG-03-equity-moved-a-cent": move_a_cent,
        "NEG-04-orphan-fill": orphan_fill,
        "NEG-05-fees-zeroed": zero_the_fees,
        "NEG-06-restart-duplicated": duplicate_after_restart,
        "NEG-07-external-connection": sneak_a_connection,
        "NEG-08-dataset-falsified": falsify_the_dataset,
        "NEG-09-unsynced-remote-claimed": claim_a_sync_that_did_not_happen,
        "NEG-10-error-path-ordered": allow_an_order_in_the_error_path,
        "NEG-11-blocked-check-as-pass": accept_a_blocked_check,
    }


def negative_controls(bundle: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, mutate in _mutations().items():
        mutated = copy.deepcopy(bundle)
        mutated_context = dict(context)
        mutate(mutated, mutated_context)
        outcome = verify(mutated, mutated_context)
        caught = outcome["verdict"] != "PASS"
        results.append(
            {
                "id": name.split("-")[1],
                "mutation": name,
                "rejected": caught,
                "rejected_by": outcome["failed"],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent verifier for WP-003-03.")
    parser.add_argument("--lab", required=True, help="PAPER_E2E_LAB.json")
    parser.add_argument("--bundle", required=True, help="evidence directory (reports/.../wp00303)")
    parser.add_argument("--repo", default="", help="git repository to check the commit against")
    parser.add_argument("--evidence-sha", default="", help="evidence commit")
    parser.add_argument("--repeat", default="", help="a second lab JSON from an independent run")
    parser.add_argument("--github-sync", default="", help="GITHUB_SYNC.json")
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--json", required=True, help="where to write the verdict")
    args = parser.parse_args()

    lab_path = Path(args.lab).resolve()
    bundle_dir = Path(args.bundle).resolve()
    if not lab_path.exists():
        print(f"missing lab report: {lab_path}")
        return 3
    bundle = _read_json(lab_path)
    context: dict[str, Any] = {
        "repo": Path(args.repo).resolve() if args.repo else None,
        "bundle_dir": bundle_dir,
        "reports_dir": bundle_dir,
        "evidence_sha": args.evidence_sha or None,
        "repeat": _read_json(Path(args.repeat).resolve()) if args.repeat else None,
        "github_sync": (
            _read_json(Path(args.github_sync).resolve())
            if args.github_sync and Path(args.github_sync).resolve().exists()
            else None
        ),
    }

    outcome = verify(bundle, context)
    if args.negative_controls:
        controls = negative_controls(bundle, context)
        outcome["negative_controls"] = controls
        outcome["negative_controls_rejected"] = sum(1 for row in controls if row["rejected"])
        outcome["negative_controls_total"] = len(controls)
        if outcome["negative_controls_rejected"] != len(controls):
            outcome["verdict"] = "FAIL"
            outcome["unsupported_pass_count"] += sum(1 for row in controls if not row["rejected"])
    Path(args.json).resolve().parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(outcome, indent=1, sort_keys=True), encoding="utf-8")

    for row in outcome["checks"]:
        mark = "ok  " if row["ok"] else ("BLK " if row.get("blocked") else "FAIL")
        print(f"{mark} {row['check']:28} {row['detail'][:120]}")
    for row in outcome.get("negative_controls") or []:
        print(f"{'ok  ' if row['rejected'] else 'FAIL'} {row['mutation']:36} {row['rejected_by']}")
    print(f"\nverdict: {outcome['verdict']}")
    if outcome["verdict"] == "PASS":
        return 0
    return 1 if outcome["verdict"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
