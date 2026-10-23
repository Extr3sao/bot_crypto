"""WP-OBS-STRAT-01 §6/§32 — observability read-model projection tests.

Two layers:

* a **synthetic** fixture tree (``tmp_path``) so every projection is asserted on
  data we control exactly — including the missing/unknown cases, which the real
  corpus cannot reliably exercise; and
* a **real-data** smoke test against the repository's own run artifacts, skipped
  when they are absent.

The synthetic layer is the one that proves the projection never invents ``0``:
when a datum is absent it must appear as ``NOT_AVAILABLE`` / ``UNKNOWN``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.observability import (  # noqa: E402
    INSUFFICIENT_SAMPLE,
    NOT_AVAILABLE,
    UNKNOWN,
    StrategyEcosystemObservatory,
    build_agent_topology,
)

RUN_ID = "synthetic-run-01"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")


def _admission() -> dict[str, Any]:
    return {
        "config_hash": "deadbeef",
        "strategies": {
            "momentum_v1": {
                "family": "momentum",
                "timeframe": "5m",
                "status": "ADMITTED",
                "admitted_for_paper": True,
                "expected_gross_edge_bps": 12.0,
                "source_doc": "docs/research/x.md",
                "rationale": "because",
            },
            "breakout_v1": {
                "family": "breakout",
                "timeframe": "5m",
                "status": "RESEARCH_ONLY",
                "admitted_for_paper": False,
                "expected_gross_edge_bps": 4.0,
            },
        },
    }


def _trace(
    decision_id: str, ts: int, *, proposed: bool, order: bool, kind: str | None
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "created_at_ms": ts,
        "decision_time_ms": ts,
        "asset": "BTCUSDT",
        "mode": "SHADOW",
        "regime": "TREND_UP",
        "no_trade_kind": kind,
        "order_created": order,
        "trace_hash": f"hash-{decision_id}",
        "risk": {"verdict": "APPROVED" if order else "NO_ACTION"},
        "verification": {"verdict": "PASS"},
        "proposal": {"strategy_id": "momentum_v1", "direction": "LONG"} if proposed else {},
        "strategies_considered": [
            {
                "strategy_id": "momentum_v1",
                "emitted_alpha": True,
                "selected": True,
                "lifecycle_verdict": "ACTIVE",
                "router_status": "SELECTED",
            },
            {
                "strategy_id": "breakout_v1",
                "emitted_alpha": False,
                "selected": False,
                "lifecycle_verdict": "PAUSED",
                "router_status": "REGIME_MISMATCH",
            },
        ],
        "agent_messages": [
            {
                "agent_id": "risk-adversary",
                "review_type": "RISK_WARNING",
                "statement": "sized ok",
                "confidence": 0.6,
                "timestamp_ms": ts,
            },
        ],
    }


@pytest.fixture()
def synthetic(tmp_path: Path) -> StrategyEcosystemObservatory:
    _write(tmp_path / "config" / "strategy_admission.json", _admission())
    run_dir = tmp_path / "reports" / "autonomous-paper" / RUN_ID
    _write(
        run_dir / "PAPER_RUN.json",
        {
            "state": "STOPPED",
            "cycles": 3,
            "stop_reason": "STOP file",
            "totals": {
                "paper_trades": 0,
                "outcomes_resolved": 1,
                "runtime_failures": 0,
                "risk_VETOED": 1,
            },
        },
    )
    _write(
        run_dir / "heartbeat.json",
        {
            "run_id": RUN_ID,
            "timestamp_ms": 1_700_000_000_000,
            "errors": [],
            "assets": ["BTCUSDT"],
            "timeframe": "5m",
        },
    )
    _write_jsonl(
        run_dir / "traces.jsonl",
        [
            _trace("d1", 1_700_000_000_000, proposed=True, order=False, kind="NO_TRADE_STRATEGIC"),
            _trace("d2", 1_700_000_060_000, proposed=True, order=False, kind="NO_TRADE_STRATEGIC"),
            _trace("d3", 1_700_000_120_000, proposed=False, order=False, kind=None),
        ],
    )
    _write_jsonl(
        run_dir / "routing_comparisons.jsonl",
        [
            {
                "asset": "BTCUSDT",
                "legacy": {"selected": ["momentum_v1"]},
                "lifecycle": {"selected": ["momentum_v1"], "rejected": {}},
                "portfolio_rejected": {},
            },
            {
                "asset": "ETHUSDT",
                "legacy": {"selected": ["momentum_v1"]},
                "lifecycle": {"selected": [], "rejected": {"momentum_v1": "REGIME_MISMATCH"}},
                "portfolio_rejected": {"breakout_v1": "OVEREXPOSURE"},
            },
        ],
    )
    _write(
        run_dir / "performance.json",
        {
            "cells": {
                "c1": {
                    "strategy_id": "momentum_v1",
                    "regime": "TREND_UP",
                    "samples": [
                        {"net_bps": 10.0, "gross_bps": 20.0},
                        {"net_bps": -5.0, "gross_bps": 5.0},
                    ],
                },
                "c2": {
                    "strategy_id": "momentum_v1",
                    "regime": "RANGE",
                    "samples": [{"net_bps": 3.0, "gross_bps": 8.0}],
                },
            }
        },
    )
    # tempo stale-ish but deterministic: pin the clock to the heartbeat for FRESH
    return StrategyEcosystemObservatory(repo_root=tmp_path, now_ms=1_700_000_120_500)


# ------------------------------------------------------------------ empty tree


def test_empty_tree_reports_unknown_not_zero(tmp_path: Path) -> None:
    obs = StrategyEcosystemObservatory(repo_root=tmp_path, now_ms=1_700_000_000_000)
    system = obs.system_view()
    assert system["runtime"]["run_id"] == NOT_AVAILABLE
    assert system["runtime"]["state"] == UNKNOWN
    assert system["freshness"]["status"] == UNKNOWN
    assert system["totals"]["paper_trades"] == NOT_AVAILABLE
    assert system["read_only"] is True
    assert system["live_control"] is False
    assert system["false_success"] == 0
    assert obs.current_run() is None
    assert obs.list_runs() == []


# ---------------------------------------------------------------- system view


def test_system_view_is_read_only_and_carries_totals(
    synthetic: StrategyEcosystemObservatory,
) -> None:
    system = synthetic.system_view()
    assert system["environment"] == "PAPER"
    assert system["execution_mode"] == "PAPER"
    assert system["live_trading_enabled"] is False
    assert system["read_only"] is True
    assert system["routing_mode"] == "SHADOW"
    assert system["campaign"] == RUN_ID
    assert system["totals"]["strategies_total"] == 2
    assert system["totals"]["decisions"] == 3
    assert system["totals"]["signals"] == 3  # momentum emits alpha on all 3 traces
    assert system["totals"]["proposals"] == 2
    assert system["totals"]["no_trade"] == 3
    assert system["false_success"] == 0


def test_freshness_fresh_vs_stale(tmp_path: Path) -> None:
    _write(tmp_path / "config" / "strategy_admission.json", _admission())
    run_dir = tmp_path / "reports" / "autonomous-paper" / RUN_ID
    _write(run_dir / "PAPER_RUN.json", {"state": "RUNNING", "totals": {}})
    _write(run_dir / "heartbeat.json", {"timestamp_ms": 1_000_000})
    _write_jsonl(run_dir / "traces.jsonl", [])
    fresh = StrategyEcosystemObservatory(repo_root=tmp_path, now_ms=1_000_000 + 60_000)
    stale = StrategyEcosystemObservatory(repo_root=tmp_path, now_ms=1_000_000 + 10_000_000)
    assert fresh.system_view()["freshness"]["status"] == "FRESH"
    assert stale.system_view()["freshness"]["status"] == "STALE"


# ------------------------------------------------------------------ strategies


def test_strategies_view_reflects_registry(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.strategies_view()
    assert view["count"] == 2
    by_id = {r["strategy_id"]: r for r in view["strategies"]}
    assert set(by_id) == {"momentum_v1", "breakout_v1"}
    mom = by_id["momentum_v1"]
    assert mom["signals"] == 3
    assert mom["proposals"] == 2
    assert mom["lifecycle"] == "ACTIVE"
    assert mom["agent"] == "NO_AGENT"
    # 3 samples < MIN_SAMPLES -> INSUFFICIENT_SAMPLE, still surfaced
    assert mom["trades"] == 3
    br = by_id["breakout_v1"]
    assert br["admitted_for_paper"] is False
    assert br["lifecycle"] == "PAUSED"


def test_strategy_detail_and_404(synthetic: StrategyEcosystemObservatory) -> None:
    detail = synthetic.strategy_detail("momentum_v1")
    assert detail is not None
    assert detail["identity"]["family"] == "momentum"
    assert detail["identity"]["agent_type"] == "NO_AGENT"
    assert detail["state"]["execution_mode"] == "PAPER"
    assert detail["evidence"]["run_id"] == RUN_ID
    perf = detail["performance"]["overall"]
    assert perf["sample_count"] == 3  # 2 TREND_UP + 1 RANGE sample
    assert perf["total_net_bps"] == pytest.approx(8.0)
    assert synthetic.strategy_detail("does-not-exist") is None


def test_performance_insufficient_sample_is_labelled(
    synthetic: StrategyEcosystemObservatory,
) -> None:
    detail = synthetic.strategy_detail("momentum_v1")
    assert detail is not None
    assert detail["performance"]["overall"]["status"] == INSUFFICIENT_SAMPLE


# ---------------------------------------------------------------------- funnel


def test_funnel_counts_real_stages_and_unknowns(synthetic: StrategyEcosystemObservatory) -> None:
    funnel = synthetic.strategy_funnel("momentum_v1")
    stages = {s["stage"]: s["count"] for s in funnel["stages"]}
    assert stages["OBSERVATIONS"] == 3
    assert stages["SIGNALS"] == 3
    assert stages["LIFECYCLE_ELIGIBLE"] == 3  # ACTIVE verdict on every trace
    assert stages["ROUTER_SELECTED"] == 3
    assert stages["PROPOSAL"] == 2
    # decision-level stages are honestly NOT_AVAILABLE, never 0
    assert stages["EXECUTED"] == NOT_AVAILABLE
    assert funnel["rejections"]["rejected_by_router"] == 0  # momentum is always selected
    assert synthetic.strategy_funnel("breakout_v1")["rejections"]["rejected_by_router"] == 3
    assert funnel["router_status"] == {"SELECTED": 3}
    assert synthetic.strategy_funnel("breakout_v1")["router_status"] == {"REGIME_MISMATCH": 3}


# --------------------------------------------------------------------- topology


def test_topology_answer_is_no_and_lists_no_agent(synthetic: StrategyEcosystemObservatory) -> None:
    topo = synthetic.topology()
    assert topo.are_strategies_governed_by_independent_agents == "NO"
    assert topo.dedicated_agent_strategies == ()
    assert set(topo.no_agent_strategies) == {"momentum_v1", "breakout_v1"}
    d = topo.to_dict()
    assert d["dedicated_agent_count"] == 0
    assert d["no_agent_count"] == 2
    assert "execute_order" in d["forbidden_actions"]


def test_build_topology_without_agents_still_classifies_no_agent(tmp_path: Path) -> None:
    report = build_agent_topology(
        {"s1": {"family": "momentum", "timeframe": "5m"}}, agent_capabilities=()
    )
    assert report.are_strategies_governed_by_independent_agents == "NO"
    assert report.entries[0].agent_type == "NO_AGENT"
    assert report.entries[0].runtime_implementation.endswith("MomentumFamily")


def test_family_runtime_implementation_unknown_family() -> None:
    from trading_bot.observability.topology import family_runtime_implementation

    assert family_runtime_implementation("nope") == "UNKNOWN"
    assert "MomentumFamily" in family_runtime_implementation("momentum")


# ----------------------------------------------------------------------- agents


def test_agents_view_lists_shared_reviewers_only(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.agents_view()
    assert view["governance"] == "NO"
    ids = {a["agent_id"] for a in view["agents"]}
    assert ids == {
        "data-integrity",
        "cost-economics",
        "evidence-provenance",
        "regime-alignment",
        "risk-adversary",
    }
    for agent in view["agents"]:
        assert agent["scope"] == "DECISION_LAYER_SHARED"
        assert agent["independent_state"] is False
        assert "execute_order" in agent["forbidden_actions"]
    activity = synthetic.agent_activity("risk-adversary")
    assert activity is not None
    assert activity["count"] == 3
    assert all(m["message_type"] == "RISK_WARNING" for m in activity["messages"])
    assert synthetic.agent_activity("no-such-agent") is None


# ---------------------------------------------------------------------- routing


def test_routing_view_matrix_and_agreement(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.routing_view()
    assert view["available"] is True
    assert view["total"] == 2
    assert view["agreement_rate"] == pytest.approx(0.5)
    assert view["matrix"]["legacy_selects__lifecycle_selects"] == 1
    assert view["matrix"]["legacy_selects__lifecycle_rejects"] == 1
    assert view["rejections_by_reason"] == {"REGIME_MISMATCH": 1}


# -------------------------------------------------------------------- portfolio


def test_portfolio_view_reports_rejections(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.portfolio_view()
    assert view["portfolio_rejected"] == {"breakout_v1": "OVEREXPOSURE"}
    assert view["arbitration_events"] == 2


# ------------------------------------------------------------------------- risk


def test_risk_view_is_deterministic_and_separate(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.risk_view()
    assert view["status"] == "DETERMINISTIC"
    assert view["authority"] == "DETERMINISTIC"
    assert view["verdicts"] == {"NO_ACTION": 3}
    assert view["risk_vetoed"] == 1
    assert view["open_risk"] == NOT_AVAILABLE


# ------------------------------------------------------------------- executions


def test_executions_view_empty_is_honest(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.executions_view()
    assert view["execution_mode"] == "PAPER"
    assert view["executed"] == 0
    assert view["executions"] == []


# ----------------------------------------------------------------------- traces


def test_traces_view_and_detail_timeline(synthetic: StrategyEcosystemObservatory) -> None:
    view = synthetic.traces_view()
    assert view["count"] == 3
    detail = synthetic.trace_detail("d1")
    assert detail is not None
    assert detail["decision_id"] == "d1"
    assert [s["stage"] for s in detail["timeline"]][:3] == [
        "MarketContext",
        "AssetContext",
        "Strategies",
    ]
    assert synthetic.trace_detail("missing") is None


# -------------------------------------------------------------------- campaigns


def test_campaigns_view_missing_root_is_empty(tmp_path: Path) -> None:
    obs = StrategyEcosystemObservatory(repo_root=tmp_path)
    assert obs.campaigns_view()["count"] == 0


def test_campaigns_view_reads_analysis(tmp_path: Path) -> None:
    campaign = tmp_path / "reports" / "paper-strategy-lifecycle-shadow-99"
    campaign.mkdir(parents=True)
    (campaign / "CAMPAIGN_CONFIG.md").write_text("# cfg\n", encoding="utf-8")
    _write(campaign / "ANALYSIS.json", {"agreement_rate": 0.42, "cycles_with_comparisons": 3})
    view = StrategyEcosystemObservatory(repo_root=tmp_path).campaigns_view()
    assert view["count"] == 1
    assert view["campaigns"][0]["agreement_rate"] == 0.42


# --------------------------------------------------------------------- snapshot


def test_snapshot_aggregates_all_views(synthetic: StrategyEcosystemObservatory) -> None:
    snap = synthetic.snapshot()
    for key in (
        "system",
        "strategies",
        "agents",
        "lifecycle",
        "routing",
        "portfolio",
        "risk",
        "executions",
        "campaigns",
        "topology",
        "freshness",
    ):
        assert key in snap
    assert snap["system"]["read_only"] is True


# -------------------------------------------------------------------- real data


def _has_real_run() -> bool:
    return (REPO / "reports" / "autonomous-paper").exists()


@pytest.mark.skipif(not _has_real_run(), reason="no real run artifacts present")
def test_real_registry_and_topology_are_consistent() -> None:
    obs = StrategyEcosystemObservatory(repo_root=REPO)
    strategies = obs.admission_strategies()
    assert len(strategies) == 24
    view = obs.strategies_view()
    assert view["count"] == 24
    topo = obs.topology()
    assert topo.are_strategies_governed_by_independent_agents == "NO"
    assert len(topo.no_agent_strategies) == 24
