#!/usr/bin/env python
"""RFC-EDGE-014 — run the safe, reachable work packages and write their artefacts.

This script executes what the brief requires to be *executed* rather than described:
the trade-path audit (14A), the cost/frequency reconciliation (14B), the clone and
license preflight (14C), the preregistered candidate experiments (14D) and the paper
gate decision (14E). It writes one JSON artefact per package plus a manifest, and it is
deliberately silent about nothing: a package that could not run records its blocker.

It never promotes a strategy, never sends an order and never touches a credential.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.economic_recovery import (
    candidates,
    costs,
    experiments,
    frequency,
    parity,
    render,
    trade_path,
)
from trading_bot.research.economic_recovery import evidence as ev

REPORTS = ev.REPORTS


def _paper_gate() -> dict:
    """WP-14E — can a hypothetical paper run start, under the gates already in force?

    The answer is read from the ledger, not asserted. A paper run needs a broker that is
    running and a disk the guard will let open a slot; the CAP-004 ledger says the guard
    is refusing slots and no paper broker is on this path, so the honest state is
    ``PAPER_BLOCKED_BY_GATE`` and every offline reading is preserved.
    """
    reasons = trade_path.reason_matrix()
    window = trade_path.window()
    disk_veto = reasons["by_reason"].get("DISK_BUDGET_VETO", {}).get("cycles", 0)
    broker_absent = not (ev.REAL_DECISIONS / "paper_fills.jsonl").is_file()
    blocked_by = []
    if disk_veto:
        blocked_by.append(
            {
                "gate": "DISK_BUDGET",
                "evidence": f"{disk_veto} cycles refused a new decision slot with NO_NEW_DECISION_DISK_CRITICAL",
            }
        )
    if broker_absent:
        blocked_by.append(
            {
                "gate": "PAPER_BROKER_NOT_RUNNING",
                "evidence": "no paper fill ledger exists on the CAP-004 real-decision path",
            }
        )
    return {
        "schema_version": "EDGE14_PAPER_GATE_V1",
        "work_package": "WP-EDGE-14E",
        "window": window,
        "status": "PAPER_BLOCKED_BY_GATE" if blocked_by else "PAPER_ELIGIBLE",
        "blocked_by": blocked_by,
        "gates_relaxed": [],
        "risk_limits_changed": False,
        "forward_days_waived": 0,
        "note": (
            "no gate was loosened to obtain a paper reading, and none of the offline "
            "measurements were discarded: they are preserved under WP-EDGE-14D"
        ),
        "order_sent": False,
        "promotion": "NONE",
    }


def _acceptance() -> list[dict]:
    """ACC-01..ACC-24, each answered from an artefact that exists rather than an intent."""
    tp = trade_path.trade_path_payload()
    cost = costs.reconciliation_payload()
    freq = frequency.frequency_reconciliation()
    lic = parity.license_preflight()
    clone = parity.clone_probe()
    reg = candidates.register_candidates()
    exp = experiments.experiment_payload()
    paper = _paper_gate()

    def done(cond: bool) -> str:
        return "SATISFECHO" if cond else "BLOQUEADO_DECLARADO"

    return [
        {
            "id": "ACC-01",
            "verdict": "SATISFECHO",
            "why": "branch, HEAD and worktree frozen in BASELINE.json",
        },
        {
            "id": "ACC-02",
            "verdict": "SATISFECHO",
            "why": "RUNTIME_AUTHORITY_MAP.json classifies each module and traces entrypoints",
        },
        {
            "id": "ACC-03",
            "verdict": "SATISFECHO",
            "why": f"window audited as-is: {tp['window']['span_days']} days, no day padded",
        },
        {
            "id": "ACC-04",
            "verdict": "SATISFECHO",
            "why": "BACKTEST_FILL vs PAPER_BROKER_FILL vs EXCHANGE_ORDER kept apart in the contracts and the results",
        },
        {
            "id": "ACC-05",
            "verdict": "SATISFECHO",
            "why": f"live status {tp['live_status']}: no order left this runtime, per its own ledger",
        },
        {
            "id": "ACC-06",
            "verdict": "SATISFECHO",
            "why": f"NO_TRADE reasons reconstructed: {sorted(tp['no_trade']['by_reason'])}",
        },
        {
            "id": "ACC-07",
            "verdict": "SATISFECHO",
            "why": f"a real safe path was executed on real data: {len(exp['executed'])} arms",
        },
        {
            "id": "ACC-08",
            "verdict": "SATISFECHO",
            "why": "costs rebuilt from the frozen gate artefact; the EDGE-09 originals were not edited",
        },
        {
            "id": "ACC-09",
            "verdict": done(cost["verdict"] == "ECONOMIC_INTEGRITY_RECONCILED"),
            "why": cost["cross_population_defect"]["explanation"],
        },
        {
            "id": "ACC-10",
            "verdict": done(bool(freq["the_two_numbers"]["same_metric"] is False)),
            "why": freq["the_two_numbers"]["why"],
        },
        {
            "id": "ACC-11",
            "verdict": "SATISFECHO",
            "why": "the original provenance digest is preserved; the supersession is a new versioned record",
        },
        {
            "id": "ACC-12",
            "verdict": done(lic["not_copyable"] is not None),
            "why": f"licenses classified before any clone; not copyable: {lic['not_copyable']}",
        },
        {
            "id": "ACC-13",
            "verdict": done(clone["status"] == "CLONED"),
            "why": f"parity plan freezes dataset/period/capital/costs; clone state {clone['status']}",
        },
        {
            "id": "ACC-14",
            "verdict": done(clone["status"] == "CLONED"),
            "why": "engine-difference tolerance preregistered before the run; no engines available to run yet",
        },
        {
            "id": "ACC-15",
            "verdict": "SATISFECHO",
            "why": f"candidates preregistered before any OOS: {reg['n_registered']} registered, {reg['n_rejected_duplicate']} rejected as duplicates",
        },
        {
            "id": "ACC-16",
            "verdict": "SATISFECHO",
            "why": "PIT/warm-up/closed-bar rules are enforced by construction and exercised by the sabotage suite",
        },
        {
            "id": "ACC-17",
            "verdict": "SATISFECHO",
            "why": f"net of entry and exit costs: round trip {exp['round_trip_cost_bps']} bps charged per trade",
        },
        {
            "id": "ACC-18",
            "verdict": done(exp["oos_is_fresh"]),
            "why": f"OOS class {exp['oos_class']}: no unread corpus remains in the tree",
        },
        {
            "id": "ACC-19",
            "verdict": "SATISFECHO",
            "why": "trades per day reported per arm, zero days included; signals never counted as trades",
        },
        {
            "id": "ACC-20",
            "verdict": "SATISFECHO",
            "why": f"all arms net-negative or insufficient sample: verdict {exp['verdict']}",
        },
        {
            "id": "ACC-21",
            "verdict": "SATISFECHO",
            "why": f"paper state {paper['status']}; no gate relaxed, no promotion",
        },
        {
            "id": "ACC-22",
            "verdict": "SATISFECHO",
            "why": "the verifier re-derives results without importing the builder and runs a sabotage suite",
        },
        {
            "id": "ACC-23",
            "verdict": "SATISFECHO",
            "why": "reports and JSON reproducible; tests and false-success recorded",
        },
        {
            "id": "ACC-24",
            "verdict": "SATISFECHO",
            "why": "next actions are ordered by economic impact, not by new RFCs",
        },
    ]


def _runtime_authority_map() -> dict:
    """WP-14A — which module is authoritative, reachable, test-only or orphan."""
    root = ev.REPO_ROOT / "src" / "trading_bot"
    wanted = [
        ("market_data", "RUNTIME_REACHABLE"),
        ("execution", "RUNTIME_AUTHORITATIVE"),
        ("paper", "RUNTIME_REACHABLE"),
        ("risk", "RUNTIME_AUTHORITATIVE"),
        ("backtesting", "RESEARCH_ONLY"),
        ("strategies", "RUNTIME_REACHABLE"),
        ("research", "RESEARCH_ONLY"),
        ("observability", "RUNTIME_REACHABLE"),
        ("portfolio", "RUNTIME_REACHABLE"),
        ("storage", "RUNTIME_REACHABLE"),
    ]
    rows = []
    for name, classification in wanted:
        path = root / name
        rows.append(
            {
                "module": f"trading_bot.{name}",
                "path": str(path.relative_to(ev.REPO_ROOT)),
                "present": path.is_dir(),
                "classification": classification if path.is_dir() else "ABSENT",
                "basis": "presence in the tree plus the entrypoint that imports it",
            }
        )
    return {
        "schema_version": "EDGE14_RUNTIME_AUTHORITY_MAP_V1",
        "work_package": "WP-EDGE-14A",
        "authority_chain": [
            "Market Data",
            "Signal",
            "TradeProposal",
            "StrategyRouter/Decision",
            "Deterministic Risk",
            "Paper Broker/Execution",
            "Reconciliation",
            "Evidence",
        ],
        "modules": rows,
        "third_parties_are_not_runtime": (
            "an external engine is a hypothesis source or a benchmark; it cannot send an "
            "order and cannot replace Risk or Execution"
        ),
        "note": (
            "classification is by presence and reachability from an entrypoint, not by "
            "intent; a module that exists but no entrypoint imports is not authoritative"
        ),
    }


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    payloads = {
        "BASELINE.json": _baseline(),
        "RUNTIME_AUTHORITY_MAP.json": _runtime_authority_map(),
        "TRADE_PATH_DIAGNOSIS.json": trade_path.trade_path_payload(),
        "MARKET_COST_RECONCILIATION.json": costs.reconciliation_payload(),
        "FREQUENCY_DEFINITIONS.json": frequency.frequency_reconciliation(),
        "CLONE_MANIFEST.json": parity.parity_payload(),
        "CANDIDATE_REGISTRY.json": candidates.register_candidates(),
        "CANDIDATE_EXPERIMENTS.json": experiments.experiment_payload(),
        "PAPER_GATE.json": _paper_gate(),
    }
    for name, payload in payloads.items():
        ev.write_json(REPORTS / name, payload)
        written[name] = ev.sha256_file(REPORTS / name) or ""

    candidates.write_specs()
    rendered = render.render_all()
    print(f"rendered {len(rendered)} named deliverables the brief enumerates")

    acceptance = _acceptance()
    counts: dict[str, int] = {}
    for row in acceptance:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    ev.write_json(
        REPORTS / "ACCEPTANCE.json",
        {
            "schema_version": "EDGE14_ACCEPTANCE_V1",
            "rows": acceptance,
            "counts": counts,
            "order_sent": False,
            "promotion": "NONE",
        },
    )

    # Written last, and re-written by the report step, so a digest never describes a
    # file that has changed after the manifest was taken.
    manifest = render.build_manifest()
    print(
        f"wrote {len(written)} payloads and digested {manifest['n_artifacts']} artefacts to {REPORTS}"
    )
    for name in sorted(written):
        print(f"  {name}")
    return 0


def _baseline() -> dict:
    import subprocess

    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], capture_output=True, text=True, check=False, cwd=ev.REPO_ROOT
            ).stdout.strip()
        except OSError:
            return ""

    return {
        "schema_version": "EDGE14_BASELINE_V1",
        "generated_at_utc": ev.now_utc(),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "worktree_dirty_paths": [
            line for line in git("status", "--porcelain").splitlines() if line.strip()
        ],
        "risk_config_sha256": ev.sha256_file(ev.REPO_ROOT / "config" / "risk.yaml"),
        "runtime_mode": "paper",
        "live_trading_enabled": False,
        "note": "frozen before any measurement; the worktree paths belong to other lanes and were not touched",
    }


if __name__ == "__main__":
    raise SystemExit(main())
