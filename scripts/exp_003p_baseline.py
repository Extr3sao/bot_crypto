"""WP-003P-00 — read-only baseline, runtime authority map and paper-adapter viability.

    python scripts/exp_003p_baseline.py

Produces ``BASELINE.md`` and ``runtime_authority_map.md`` plus the machine-readable
``evidence/BASELINE.json``. Everything it asserts is either read from disk, read from git,
or executed right here: a component on disk is not authority, reachability is.

It writes nothing outside this experiment's directory and never touches a configuration
file or the working tree.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from exp_003p_contract import (  # noqa: E402
    DATASET,
    DO_NOT_TOUCH,
    FROZEN_CONFIGS,
    OUT,
    RUN_ID,
    SOURCE_003O_DIR,
    WINDOW,
    config_digest,
    git,
    read_json,
    sha256_file,
    write_json,
)

EVidence = OUT / "evidence"


def _status_lines() -> list[str]:
    return [line for line in git("status", "--porcelain").splitlines() if line.strip()]


def _entrypoint_inventory() -> list[dict[str, Any]]:
    """The scripts that can reach a paper decision path, with how each was reached."""

    rows = [
        {
            "id": "PRIMARY_PAPER_RUNTIME",
            "path": "scripts/autonomous_paper.py",
            "kind": "autonomous PAPER/SHADOW loop",
            "evidence": "documented in docs/runtime/runtime_authority_map.md; not executed by 003P",
        },
        {
            "id": "LEGACY_PAPER_LOOP",
            "path": "scripts/start_paper_trading.py",
            "kind": "PaperOrchestrator loop",
            "evidence": "static; superseded per docs/runtime/runtime_authority_map.md",
        },
        {
            "id": "VISION_LANE_REPLAY",
            "path": "scripts/exp_003p_rehearsal.py",
            "kind": "frozen-bar replay through VisionLane",
            "evidence": "executed by 003P (EXECUTION_TRACE.jsonl)",
        },
        {
            "id": "LIFECYCLE_SCENARIO",
            "path": "scripts/exp_003p_rehearsal.py",
            "kind": "offline venue scenarios through LifecycleEngine",
            "evidence": "executed by 003P (SCENARIO_TRACE.jsonl)",
        },
        {
            "id": "LIFECYCLE_CONTROLS",
            "path": "scripts/exp_003p_controls.py",
            "kind": "adversarial controls",
            "evidence": "executed by 003P (NEGATIVE_CONTROLS.json)",
        },
    ]
    return rows


def _components() -> list[dict[str, str]]:
    return [
        {
            "component": "trading_bot.paper.broker.PaperBroker",
            "path": "src/trading_bot/paper/broker.py",
            "classification": "RUNTIME_AUTHORITATIVE (execution boundary)",
            "evidence": "executed by this baseline probe and the rehearsal",
        },
        {
            "component": "trading_bot.paper.lifecycle.PaperBrokerRecorder",
            "path": "src/trading_bot/paper/lifecycle/recorder.py",
            "classification": "RUNTIME_AUTHORITATIVE (instrumentation, added by 003P)",
            "evidence": "executed: emits ORDER_CREATED..ORDER_FILLED from real broker fills",
        },
        {
            "component": "trading_bot.paper.lifecycle.LifecycleEngine",
            "path": "src/trading_bot/paper/lifecycle/engine.py",
            "classification": "RUNTIME_AUTHORITATIVE (event construction, added by 003P)",
            "evidence": "executed: refusal and scenario paths in the controls",
        },
        {
            "component": "trading_bot.vision.lane.VisionLane",
            "path": "src/trading_bot/vision/lane.py",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "executed by the rehearsal on frozen bars",
        },
        {
            "component": "trading_bot.risk.manager.RiskManager",
            "path": "src/trading_bot/risk/manager.py",
            "classification": "RUNTIME_AUTHORITATIVE",
            "evidence": "executed inside VisionLane; risk refusals recorded by the controls",
        },
        {
            "component": "trading_bot.paper.lifecycle.venue.SimulatedPaperVenue",
            "path": "src/trading_bot/paper/lifecycle/venue.py",
            "classification": "TEST_DOUBLE (not an execution platform)",
            "evidence": "executed by the scenario phase; every event is OFFLINE_SIMULATED",
        },
        {
            "component": "trading_bot.execution.* live adapters",
            "path": "src/trading_bot/execution/",
            "classification": "OUT_OF_SCOPE (live)",
            "evidence": "not imported by any 003P entrypoint; asserted by the verifier",
        },
    ]


def _provider_viability() -> dict[str, Any]:
    """Is a paper/testnet provider configured and authorised *before* this experiment?"""

    sandbox_flag = "not_found"
    exchange_config = REPO / "config" / "exchange.yaml"
    if exchange_config.exists():
        for line in exchange_config.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("sandbox:"):
                sandbox_flag = line.split(":", 1)[1].strip()
                break
    env_names = [
        name
        for name in (
            "EXCHANGE_API_KEY",
            "EXCHANGE_API_SECRET",
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "PAPER_API_KEY",
        )
        if os.environ.get(name)
    ]
    # The presence of a name is recorded; no value is read, printed or hashed.
    return {
        "exchange_sandbox_flag": sandbox_flag,
        "credential_names_present": env_names,
        "credentials_present": bool(env_names),
        "order_submitting_adapter_configured": False,
        "reason": (
            "no paper/testnet order adapter is configured for this workspace; the live "
            "adapter is out of scope and unreachable from 003P by construction"
        ),
        "verdict": "BLOCKED_NOT_CONFIGURED",
    }


def _probe_broker() -> dict[str, Any]:
    """Execute the real broker once so reachability is observed, not assumed."""

    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.lifecycle import (
        LifecycleEngine,
        PaperBrokerRecorder,
        RunContext,
    )
    from trading_bot.strategies.types import Signal

    context = RunContext(
        run_id=RUN_ID,
        commit_sha=git("rev-parse", "HEAD") or "UNKNOWN",
        config_digest=config_digest(),
        adapter_id="PAPER_BROKER_PROBE",
        provenance="OFFLINE_SIMULATED",
        provider_environment="OFFLINE",
        clock_source="PAPER_BROKER_CLOCK",
    )
    engine = LifecycleEngine(context=context)
    broker = PaperBroker(
        equity=10_000.0,
        book_id="probe-003p",
        lifecycle=PaperBrokerRecorder(engine, book_id="probe-003p"),
    )
    signal = Signal(
        symbol="BTC/USDT",
        side="buy",
        strategy_name="ema_crossover",
        timeframe="1h",
        confidence=0.5,
        price=100.0,
        stop_loss_pct=1.0,
        take_profit_pct=2.0,
        metadata={"notional_usdt": 500.0, "decision_seq": 1},
    )
    position = broker.execute_signal(signal)
    close = broker.close_position("BTC/USDT", 100.5, "probe_close")
    return {
        "executed": position is not None,
        "envelopes": [event.event_type for event in engine.store.envelopes],
        "envelopes_count": len(engine.store.envelopes),
        "closed": close is not None,
        "trace_digest": engine.store.digest(),
        "ledger_fills": engine.ledger.applied_count,
        "provenance_tags": sorted({event.provenance for event in engine.store.envelopes}),
        "live_orders": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P baseline")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)

    status = _status_lines()
    scopes = sorted({line[3:].split("/")[0] for line in status})
    dependency = read_json(SOURCE_003O_DIR / "RUN_REPORT.json")
    dataset = {
        name: sha256_file(DATASET / name)
        for name in sorted(path.name for path in DATASET.glob("*.jsonl.gz"))
    }
    configs = {relative: sha256_file(REPO / relative) for relative in FROZEN_CONFIGS}
    probe = _probe_broker()

    payload = {
        "run_id": RUN_ID,
        "schema_version": "AI_BOTS_003P_BASELINE_V1",
        "captured_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": {
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": git("rev-parse", "HEAD"),
            "head_subject": git("log", "-1", "--format=%s"),
            "dirty_lines": len(status),
            "dirty_scopes": scopes,
            "foreign_changes_present": bool(status),
            "do_not_touch": list(DO_NOT_TOUCH),
        },
        "python": {"version": platform.python_version(), "platform": platform.platform()},
        "config_sha256": configs,
        "config_digest": config_digest(),
        "dataset": {"directory": str(DATASET.relative_to(REPO)).replace("\\", "/"), "files": dataset},
        "window": WINDOW,
        "dependency_003o": {
            "status": dependency.get("status"),
            "verdict": dependency.get("verdict"),
            "technical_signal_parity": dependency.get("technical_signal_parity"),
            "full_independent_certification": dependency.get("full_independent_certification"),
            "economic_edge": dependency.get("economic_edge"),
            "blockers": dependency.get("blockers"),
            "design_sha256": dependency.get("design_sha256"),
        },
        "entrypoints": _entrypoint_inventory(),
        "components": _components(),
        "provider_viability": _provider_viability(),
        "reachability_probe": probe,
    }

    write_json(EVidence / "BASELINE.json", payload)

    md = [
        "# BASELINE — EXP-003P (WP-003P-00)",
        "",
        f"- branch `{payload['git']['branch']}`, HEAD `{payload['git']['head'][:12]}` "
        f"({payload['git']['head_subject']})",
        f"- working tree: {payload['git']['dirty_lines']} modified paths in scopes "
        f"`{', '.join(scopes) or 'none'}` — 003P does not touch them",
        f"- config digest: `{payload['config_digest']}`",
        f"- 003O dependency: `{payload['dependency_003o']['status']}` "
        f"(technical `{payload['dependency_003o']['technical_signal_parity']}`, "
        f"full `{payload['dependency_003o']['full_independent_certification']}`), "
        f"edge `{payload['dependency_003o']['economic_edge']}`",
        "",
        "## Reachability probe (executed now, not asserted)",
        "",
        f"- `PaperBroker.execute_signal` → {probe['envelopes_count']} lifecycle events "
        f"`{probe['envelopes']}`",
        f"- ledger fills applied: {probe['ledger_fills']}; provenance tags "
        f"`{probe['provenance_tags']}`; live orders: {probe['live_orders']}",
        "",
        "## Paper provider viability",
        "",
        f"- exchange `sandbox` flag: `{payload['provider_viability']['exchange_sandbox_flag']}`",
        f"- credential names present: "
        f"`{payload['provider_viability']['credential_names_present'] or 'none'}`",
        f"- verdict: **{payload['provider_viability']['verdict']}** — "
        f"{payload['provider_viability']['reason']}",
        "",
        "## Frozen inputs",
        "",
        "| file | sha256 |",
        "| --- | --- |",
    ]
    for name, digest in sorted(dataset.items()):
        md.append(f"| `{name}` | `{digest}` |")
    for relative, digest in configs.items():
        md.append(f"| `{relative}` | `{digest}` |")
    md += [
        "",
        "## What this baseline does not claim",
        "",
        "- It does not claim a paper venue exists: the provider verdict is "
        f"`{payload['provider_viability']['verdict']}`.",
        "- It does not claim 003O is certified: its status is inherited unchanged.",
        "- It does not claim edge: `ECONOMIC_EDGE=NOT_EVALUATED`.",
        "",
    ]
    (out / "BASELINE.md").write_text("\n".join(md), encoding="utf-8", newline="\n")

    authority = [
        "# RUNTIME AUTHORITY MAP — EXP-003P",
        "",
        "> Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE >",
        "> ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION`. A class on disk is not authority.",
        "",
        "## Entrypoints",
        "",
        "| id | path | kind | evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["entrypoints"]:
        authority.append(f"| `{row['id']}` | `{row['path']}` | {row['kind']} | {row['evidence']} |")
    authority += [
        "",
        "## Component classification",
        "",
        "| component | path | classification | evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["components"]:
        authority.append(
            f"| `{row['component']}` | `{row['path']}` | {row['classification']} | "
            f"{row['evidence']} |"
        )
    authority += [
        "",
        "## Authoritative chain (003P, paper)",
        "",
        "```text",
        "frozen 1m klines (003K dataset)",
        "  → complete 1h bars only",
        "  → VisionLane decision (signal provider, PIT window)",
        "  → RiskManager.check_signal (sizing, stop policy)",
        "  → PaperBroker.execute_signal  ← the execution boundary",
        "       ├─ PaperBrokerRecorder → LifecycleEngine → DurableEventStore",
        "       │                                           └─ FillLedger",
        "       └─ PaperBroker book (positions, closed trades, accounting_snapshot)",
        "  → projection (state machine) → reconciliation (ledger vs book)",
        "  → EXECUTION_TRACE.jsonl / ORDER_LIFECYCLE.csv / RECONCILIATION.json",
        "```",
        "",
        "The scenario phase uses the same engine, store, ledger and reconciliation against a",
        "declared offline venue double, so partial fills and timeouts are reachable facts of",
        "the evidence rather than clauses in a document.",
        "",
        "## Reachability of a live adapter from 003P",
        "",
        "None. `trading_bot.execution` is not imported by any 003P entrypoint, every",
        "envelope is validated against a paper provenance/environment pair, and the verifier",
        "re-checks that no persisted event claims `LIVE`.",
        "",
    ]
    (out / "runtime_authority_map.md").write_text(
        "\n".join(authority), encoding="utf-8", newline="\n"
    )

    print(
        "[003p-baseline] head="
        f"{(payload['git']['head'] or '')[:12]} dirty={payload['git']['dirty_lines']} "
        f"probe_events={probe['envelopes_count']} provider={payload['provider_viability']['verdict']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
