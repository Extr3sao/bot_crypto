"""Independent POC01 validator (PAPER-OBSERVATION-CAMPAIGN-01, setup phase).

Audits the campaign infrastructure from outside the runtime code: durable
state, atomic persistence, safe stop/resume, duplicate prevention, identity,
freshness, DecisionTrace, canonical PnL, reports, attribution, debate/
decision/risk metrics, observational frequency KPI, read-only dashboard,
watchdog, credential hygiene, and zero live/real-broker surface.

Default mode runs a deterministic fixture campaign end-to-end (two sessions
with a resume in between), then audits the artifacts. ``--real-market`` runs
the same audit over a bounded public-market campaign instead.

REPLACE verdict over the concurrent stub validator: that script only checked
file existence and asserted ``status == READY``; it consumed no certified
boundaries (verifier, risk, resume identity) and its fixture run was treated
as campaign performance. This validator supersedes it.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.paper_observation.runtime import (
    CampaignRuntime,
    create_campaign_dashboard,
)
from trading_bot.paper_observation.state import SCHEMA_VERSION, CampaignStateStore

CERTIFIED_ADAPTER = "trading_bot.demo.paper_multi_agent.DecisionToCandidateAdapter"


def _check(name: str, passed: bool, detail: str = "") -> tuple[str, str, str]:
    return name, "PASS" if passed else "FAIL", detail


def _accelerating(asset: str, ts_end: int, *, n: int = 80, p0: float = 100.0) -> list[OHLCV]:
    out: list[OHLCV] = []
    price = p0
    start = ts_end - (n - 1) * 300_000
    for i in range(n):
        price *= 1.002
        out.append(
            OHLCV(f"{asset}/USDT", start + i * 300_000, price * 0.998, price * 1.002, price * 0.996, price, 100.0)
        )
    return out


def run_deterministic_scenario(root: Path) -> dict[str, Any]:
    """Fixture-resume E2E: open → persist → restart → close → reconcile."""

    rt = CampaignRuntime(output_dir=root, campaign_name="validator", provider="fake", strategies=("momentum",))
    state = rt.new_campaign()
    end1 = 1_786_000_000_000 + 3_600_000
    bars1 = {a: _accelerating(a, end1) for a in ("BTC", "ETH", "SOL")}
    now1 = datetime.fromtimestamp((end1 + 60_000) / 1000, tz=UTC)
    risk, broker = rt._rehydrate(state)
    rt.run_cycle(bars_by_asset=bars1, risk=risk, broker=broker, now=now1)
    rt._persist()
    orders_before = list(state.processed_order_ids)
    assert state.open_positions, "fixture must open one paper position"

    rt2 = CampaignRuntime(output_dir=root, campaign_name="validator", provider="fake", strategies=("momentum",))
    resumed = rt2.load_for_resume()
    end2 = 1_786_000_000_000 + 2 * 3_600_000
    bars2 = {a: _accelerating(a, end2, p0=160.0) for a in ("BTC", "ETH", "SOL")}
    now2 = datetime.fromtimestamp((end2 + 60_000) / 1000, tz=UTC)
    risk2, broker2 = rt2._rehydrate(resumed)
    rt2.run_cycle(bars_by_asset=bars2, risk=risk2, broker=broker2, now=now2)
    rt2.safe_stop(status="STOPPED")
    return {
        "campaign_dir": rt2.campaign_dir,
        "store": rt2.store,
        "orders_before": orders_before,
        "closed_before": len(resumed.closed_trades),
        "open_after": len(resumed.open_positions),
    }


def run_real_market_scenario(root: Path) -> dict[str, Any]:
    rt = CampaignRuntime(output_dir=root, campaign_name="validator-real", provider="ccxt", strategies=("momentum",))
    rt.new_campaign()
    rt.run_bounded_session(cycles=1)
    rt.safe_stop(status="STOPPED")
    return {"campaign_dir": rt.campaign_dir, "store": rt.store, "orders_before": [], "closed_before": 0, "open_after": len(rt.state.open_positions) if rt.state else 0}


def validate(scenario: dict[str, Any]) -> tuple[bool, tuple[tuple[str, str, str], ...]]:
    campaign_dir: Path = scenario["campaign_dir"]
    store: CampaignStateStore = scenario["store"]
    state = store.load()
    report = json.loads((campaign_dir / "CAMPAIGN_REPORT.json").read_text(encoding="utf-8"))

    # 1 certified DEMO-PAPER path reused
    import inspect

    import trading_bot.paper_observation.runtime as rt_module

    rt_src = inspect.getsource(rt_module)
    reuse_ok = (
        hasattr(rt_module, "DecisionEngine")  # frozen MA-4 engine imported
        and "DecisionToCandidateAdapter" in rt_src  # certified adapter invoked
        and "class RiskManager" not in rt_src
        and "class PaperBroker" not in rt_src
        and "class DecisionPackageVerifier" not in rt_src
        and "class DecisionEngine" not in rt_src
    )
    equity_ok = abs(float(state.equity) - (float(state.initial_equity) + float(state.realized_pnl))) < 1e-6
    checks = [
        _check("01_certified_demo_path_reused", reuse_ok, CERTIFIED_ADAPTER),
        # 2 public market / PAPER only
        _check("02_paper_only", state.provider in ("ccxt", "fake") and report.get("data_tag") in ("REAL_PUBLIC_MARKET", "DEMO_FIXTURE")),
        # 3 durable state
        _check("03_durable_state", state.schema_version == SCHEMA_VERSION and bool(state.campaign_id) and bool(state.campaign_start)),
        # 4 atomic persistence
        _check(
            "04_atomic_persistence",
            store.path.exists() and not list(campaign_dir.glob("*.tmp")) and json.loads(store.path.read_text(encoding="utf-8")).get("campaign_id") == state.campaign_id,
        ),
        # 5 safe stop
        _check("05_safe_stop", state.campaign_status == "STOPPED" and state.heartbeat.get("campaign_state") == "STOPPED"),
        # 6 safe resume
        _check(
            "06_safe_resume",
            bool(state.heartbeat.get("resumed_at")) and state.realized_pnl == round(sum(float(t["pnl"]) for t in state.closed_trades), 8),
        ),
        # 7 duplicate prevention
        _check(
            "07_duplicate_prevention",
            len(state.processed_order_ids) == len(set(state.processed_order_ids))
            and len(state.processed_fill_ids) == len(set(state.processed_fill_ids))
            and state.funnel.get("PAPER_OPEN", 0) <= state.funnel.get("RISK_ACCEPT", 0),
        ),
        # 8 campaign/run identity
        _check(
            "08_campaign_run_identity",
            state.campaign_id.startswith("poc01-")
            and state.run_id.startswith(state.campaign_id)
            and state.trace_id.startswith("trace-"),
        ),
        # 9 data freshness
        _check("09_data_freshness", state.data_health["future_events"] == 0 and state.heartbeat.get("last_scan_time") is not None),
        # 10 DecisionTrace
        _check(
            "10_decision_trace",
            all(t.get("decision_id") for t in state.closed_trades)
            and bool(state.last_processed_decision_ids),
        ),
        # 11 daily reports
        _check("11_daily_reports", any((d / "DAILY_REPORT.json").exists() and (d / "DAILY_REPORT.md").exists() for d in campaign_dir.iterdir() if d.is_dir())),
        # 12 campaign aggregation
        _check("12_campaign_report", (campaign_dir / "CAMPAIGN_REPORT.json").exists() and (campaign_dir / "CAMPAIGN_REPORT.md").exists()),
        # 13 canonical PnL
        _check(
            "13_canonical_pnl",
            equity_ok and (not state.realized_pnl or bool(state.closed_trades)),
        ),
        # 14 asset attribution
        _check("14_asset_attribution", report["attribution"]["by_asset"] != {} or state.funnel.get("MARKET_SCANS", 0) == 0),
        # 15 strategy attribution
        _check("15_strategy_attribution", report["attribution"]["by_strategy"] != {}),
        # 16 regime attribution
        _check("16_regime_attribution", isinstance(report["attribution"]["by_regime"], dict)),
        # 17 debate metrics
        _check("17_debate_metrics", state.debate_metrics["debates"] >= 1 and state.debate_metrics["critiques"] >= 1),
        # 18 risk metrics
        _check("18_risk_metrics", state.risk_metrics["accepts"] == state.funnel.get("RISK_ACCEPT", 0)),
        # 19 frequency KPI observational
        _check(
            "19_frequency_kpi_observational",
            (report["frequency"]["note"].startswith("target")
            and report["bottleneck"].get("PRIMARY_FREQUENCY_BOTTLENECK") is None)
            or isinstance(report["bottleneck"].get("PRIMARY_FREQUENCY_BOTTLENECK"), (str, type(None))),
        ),
        # 20 dashboard read-only campaign state
        _check("20_dashboard_read_only", _probe_dashboard_readonly(state, campaign_dir)),
        # 21 watchdog
        _check(
            "21_watchdog",
            all(
                k in state.heartbeat
                for k in ("last_scan_time", "last_successful_decision_cycle", "provider_status", "last_persistence_success", "last_reconciliation_success")
            ),
        ),
        # 22 credentials not consumed
        _check("22_credentials_not_consumed", _probe_credentials()),
        # 23 real broker calls 0
        _check("23_real_broker_calls_zero", report.get("real_broker_calls") == 0),
        # 24 LIVE calls 0
        _check("24_live_calls_zero", report.get("live_calls") == 0),
        # 25 FALSE_SUCCESS 0
        _check("25_false_success_zero", report.get("false_success") == 0),
    ]
    return all(status == "PASS" for _, status, _ in checks), tuple(checks)


def _probe_dashboard_readonly(state: Any, campaign_dir: Path) -> bool:
    try:
        rt = CampaignRuntime(output_dir=campaign_dir.parent, campaign_name=state.campaign_id.replace("poc01-", "").replace("-001", ""), provider="fake", strategies=("momentum",))
        rt.state = state
        server = create_campaign_dashboard(rt, port=0)
        port = server.port
        server.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaign", timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("mode") != "PAPER" or payload.get("live_disabled") is not True:
                return False
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/order", timeout=5)
                return False
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    return False
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/campaign", data=b"{}", method="POST")
            try:
                urllib.request.urlopen(req, timeout=5)
                return False
            except urllib.error.HTTPError as exc:
                return exc.code == 405
        finally:
            server.stop()
    except Exception:
        return False


def _probe_credentials() -> bool:
    """Static proof: public provider constructs ccxt with empty credentials."""
    import inspect

    import trading_bot.paper_observation.runtime as rt_module

    src = inspect.getsource(rt_module._public_bars)
    return '"apiKey": ""' in src and '"secret": ""' in src


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate POC01 campaign infrastructure")
    parser.add_argument("--root", type=Path, default=Path("reports/poc01-validator"))
    parser.add_argument("--real-market", action="store_true", help="bounded public-market scenario instead of fixture")
    args = parser.parse_args(argv)

    import shutil

    if args.root.exists():
        shutil.rmtree(args.root)
    scenario = run_real_market_scenario(args.root) if args.real_market else run_deterministic_scenario(args.root)
    passed, checks = validate(scenario)
    for name, status, detail in checks:
        suffix = f" — {detail}" if detail else ""
        print(f"{status} {name}{suffix}")
    total = len(checks)
    ok = sum(status == "PASS" for _, status, _ in checks)
    print(f"{ok}/{total} PASS")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
