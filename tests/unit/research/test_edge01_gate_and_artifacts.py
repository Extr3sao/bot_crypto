"""EDGE-01 verdict and artefact tests (WP-EDGE-01).

The gate is where a research lane is allowed to lie to itself, so it is tested
branch by branch: a small sample must not become an admission, an unpowered
negative must not be sold as a rejection, and a powered negative must not be
softened into "more data needed". The artefact tests pin the contract of the
required outputs, including that private in-memory buffers never reach them and
that the benchmark coverage file is part of the published set.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from trading_bot.research.edge01 import campaign as campaign_module
from trading_bot.research.edge01.campaign import (
    ADMISSION_CRITERIA,
    DEFECTS_FIXED,
    LIMITATIONS,
    PAPER_STATUS,
    SPLITS,
    _gate,
    _git_state,
    _public,
    _summary,
    load_risk_policy,
    write_artifacts,
)
from trading_bot.research.edge01.data import REPO

MIN_TRADES = int(ADMISSION_CRITERIA["min_oos_trades"])


def metrics(
    *,
    net: float,
    trades: int,
    expectancy: float | None = None,
    share: float | None = None,
    regimes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "net_usdt": net,
        "trades": trades,
        "expectancy_usdt": expectancy if expectancy is not None else (net / trades if trades else 0.0),
        "largest_trade_share_of_net": share,
        "by_regime": {"UP": {"net": max(net, 0.0)}} if regimes is None else regimes,
    }


def splits(
    *,
    dev: float,
    val: float,
    oos: float,
    trades: int = MIN_TRADES,
    share: float | None = 0.3,
    stress: float = 1.0,
    regimes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "DEV": {"BASE": metrics(net=dev, trades=MIN_TRADES)},
        "VAL": {"BASE": metrics(net=val, trades=MIN_TRADES)},
        "OOS": {
            "BASE": metrics(net=oos, trades=trades, share=share, regimes=regimes),
            "2X_FEES": {"net_usdt": stress},
        },
    }


def verdict(**kwargs: Any) -> dict[str, Any]:
    return _gate(splits=splits(**kwargs), criteria=ADMISSION_CRITERIA)


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #


def test_all_criteria_met_is_the_only_admit() -> None:
    result = verdict(dev=100.0, val=50.0, oos=80.0, share=0.3, stress=40.0)
    assert result["verdict"] == "ADMIT"
    assert result["power"].startswith("powered")


def test_powered_negative_oos_is_rejected() -> None:
    result = verdict(dev=-10.0, val=10.0, oos=-50.0, stress=-60.0)
    assert result["verdict"] == "REJECT"
    assert result["power"].startswith("powered")
    assert any("oos net" in reason for reason in result["reasons"])


def test_small_negative_sample_is_insufficient_not_rejected() -> None:
    result = verdict(dev=90.0, val=60.0, oos=-5.0, trades=5, stress=-6.0)
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result["power"].startswith("underpowered")
    assert any("unpowered sample" in reason for reason in result["reasons"])


def test_small_sample_that_loses_in_every_window_is_rejected() -> None:
    result = verdict(dev=-10.0, val=-20.0, oos=-5.0, trades=5, stress=-6.0)
    assert result["verdict"] == "REJECT"
    assert result["power"].startswith("underpowered")
    assert any("negative in every window" in reason for reason in result["reasons"])


def test_one_trade_carrying_the_oos_net_is_never_admitted() -> None:
    result = verdict(dev=100.0, val=50.0, oos=80.0, share=0.8, stress=40.0)
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert any("largest single trade" in reason for reason in result["reasons"])


def test_no_cost_margin_is_never_admitted() -> None:
    result = verdict(dev=100.0, val=50.0, oos=80.0, share=0.3, stress=-10.0)
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert any("2x fees" in reason for reason in result["reasons"])


def test_a_loss_in_every_regime_is_never_admitted() -> None:
    result = verdict(
        dev=100.0,
        val=50.0,
        oos=80.0,
        share=0.3,
        stress=40.0,
        regimes={"UP": {"net": -1.0}, "DOWN": {"net": -2.0}},
    )
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert any("profitable regime" in reason for reason in result["reasons"])


def test_gate_evidence_is_serialisable_and_names_the_windows() -> None:
    result = verdict(dev=100.0, val=50.0, oos=80.0, share=0.3, stress=40.0)
    evidence = result["evidence"]
    assert evidence["window_net_usdt"] == {"DEV": 100.0, "VAL": 50.0, "OOS": 80.0}
    assert evidence["min_oos_trades"] == MIN_TRADES
    assert json.loads(json.dumps(result))["verdict"] == "ADMIT"


# --------------------------------------------------------------------------- #
# Pre-registration and configuration
# --------------------------------------------------------------------------- #


def test_splits_are_disjoint_and_ordered() -> None:
    for windows in SPLITS.values():
        dev, val, oos = windows["DEV"], windows["VAL"], windows["OOS"]
        assert dev["end"] < val["start"] <= val["end"] < oos["start"]
        assert oos["end"] > oos["start"]


def test_admission_criteria_are_the_documented_ones() -> None:
    for key in (
        "min_oos_trades",
        "require_oos_net_positive",
        "require_oos_expectancy_positive",
        "require_oos_cost_stress_positive",
        "max_single_trade_share_of_net",
        "require_min_positive_regimes",
    ):
        assert key in ADMISSION_CRITERIA
    assert ADMISSION_CRITERIA["min_oos_trades"] >= 30


def test_risk_policy_is_read_from_the_runtime_config() -> None:
    payload = yaml.safe_load((REPO / "config" / "risk.yaml").read_text(encoding="utf-8"))["risk"]
    policy = load_risk_policy()
    assert policy.max_notional_usdt == float(payload["max_order_notional_usdt"])
    assert policy.drawdown_halt_pct == float(payload["max_total_drawdown_pct"])
    assert policy.risk_per_trade_pct == float(payload["max_risk_per_trade_pct"])
    assert policy.min_notional_usdt == float(payload["min_order_notional_usdt"])


def test_defects_and_limitations_are_declared() -> None:
    ids = [defect["id"] for defect in DEFECTS_FIXED]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 5
    assert all(defect["evidence"] for defect in DEFECTS_FIXED)
    assert len(LIMITATIONS) >= 5
    assert PAPER_STATUS["integrated"] is False


# --------------------------------------------------------------------------- #
# Artefacts
# --------------------------------------------------------------------------- #


def test_public_drops_private_buffers_recursively() -> None:
    payload = {
        "net_usdt": 1.0,
        "_equity_curve": [(1, 2.0)],
        "trade_rows": [{"net": 1.0}],
        "buy_and_hold": {"BTC": {"return_pct": 3.0, "_bar_returns": [0.1] * 50}},
    }
    clean = _public(payload)
    assert json.loads(json.dumps(clean)) == {
        "net_usdt": 1.0,
        "buy_and_hold": {"BTC": {"return_pct": 3.0}},
    }


def _fake_metrics(net: float, trades: int) -> dict[str, Any]:
    return {
        **metrics(net=net, trades=trades, share=0.2),
        "gross_usdt": net * 0.5,
        "fees_usdt": 1.0,
        "price_costs_usdt": 0.5,
        "return_pct": net / 100.0,
        "win_rate_pct": 40.0,
        "profit_factor": 1.1,
        "max_drawdown_pct": 1.0,
        "sharpe_annualised": 0.5,
        "exposure_pct_of_time": 2.0,
        "total_cost_bps_per_trade": 23.0,
        "exit_reason_mix": {"stop_loss": 1, "target": 1},
        "candidate_refusals": {"candidate:no_setup": 3},
        "signals_printed": trades,
        "plane": {"scenario_id": "BASE", "round_trip_bps": 23.0},
        "buy_and_hold": {"BTC": {"return_pct": 1.5, "_bar_returns": [0.0] * 100}},
        "trade_rows": [{"net": net, "asset": "BTC"}],
        "_equity_curve": [(1_700_000_000_000, 10_000.0 + net)],
    }


def _fake_campaign() -> dict[str, Any]:
    provenance = {
        asset: {
            "symbol": asset,
            "timeframe": "15m",
            "bars": 100,
            "first_ts": 1,
            "last_ts": 2,
            "sources": ["data/raw/x.json"],
            "sha256": "a" * 64,
        }
        for asset in ("BTC", "ETH", "SOL")
    }
    split_windows = {
        "DEV": {"start_utc": "2024-10-01T00:00:00+00:00", "end_utc": "2025-06-30T00:00:00+00:00"},
        "VAL": {"start_utc": "2025-07-01T00:00:00+00:00", "end_utc": "2025-12-31T00:00:00+00:00"},
        "OOS": {"start_utc": "2026-01-01T00:00:00+00:00", "end_utc": "2026-10-07T00:00:00+00:00"},
    }
    gate = _gate(
        splits={
            "DEV": {"BASE": metrics(net=10.0, trades=40)},
            "VAL": {"BASE": metrics(net=20.0, trades=40)},
            "OOS": {
                "BASE": metrics(net=30.0, trades=40, share=0.2),
                "2X_FEES": {"net_usdt": 15.0},
            },
        },
        criteria=ADMISSION_CRITERIA,
    )
    return {
        "generated_at_utc": "2026-10-12T00:00:00+00:00",
        "params_hash": "b" * 64,
        "frozen_params": {"edge_intra_01": {"resistance_lookback": 20}},
        "splits": {"intraday": split_windows},
        "cost_scenarios": {"BASE": (1.0, 1.0)},
        "market_context": {
            "meta": {
                "benchmark": "BTC",
                "timeframe": "1d (aggregated from 1h shards)",
                "rule": "close vs EMA200 with the EMA's 20-day slope",
                "labels": ["BULL", "BEAR", "SIDEWAYS", "UNDEFINED"],
                "sources": ["reports/alpha-expansion-v1/data/BTCUSDT_2019.json"],
                "source_sha256": "c" * 64,
                "days": 1,
                "first_close_ms": 1_700_000_000_000,
                "last_close_ms": 1_700_086_400_000,
                "label_days": {"BULL": 1},
                "artefact": "MARKET_CONTEXT.csv",
            },
            "rows": [
                {
                    "close_ms": 1_700_086_400_000,
                    "iso_utc": "2023-11-15T00:00:00+00:00",
                    "label": "BULL",
                    "close": 36_000.0,
                    "ema_200": 30_000.0,
                    "ema_slope_20": 120.0,
                }
            ],
        },
        "admission_criteria": ADMISSION_CRITERIA,
        "risk_policy": load_risk_policy().to_dict(),
        "candidates": {
            "edge_intra_01": {
                "scope": {
                    "split": "intraday",
                    "timeframe": "15m",
                    "assets": ["BTC", "ETH", "SOL"],
                    "params_hash": "b" * 64,
                    "frozen_params": {"resistance_lookback": 20},
                    "provenance": provenance,
                },
                "splits": {
                    split: {
                        scenario: _fake_metrics(float(i), 3)
                        for i, scenario in enumerate(("BASE", "2X_FEES", "ADVERSE"), start=1)
                    }
                    for split in ("DEV", "VAL", "OOS")
                },
                "verdict": gate["verdict"],
                "verdict_reasons": gate["reasons"],
                "verdict_power": gate["power"],
                "verdict_evidence": gate["evidence"],
            }
        },
    }


def test_write_artifacts_publishes_every_required_file_with_an_integrity_inventory(
    tmp_path: Path,
) -> None:
    campaign = _fake_campaign()
    written = write_artifacts(campaign, tmp_path)
    assert sorted(written) == [
        "EQUITY_CURVE.csv",
        "MARKET_CONTEXT.csv",
        "RUN_REPORT.json",
        "RUN_REPORT.md",
        "STRATEGY_RESULTS.json",
        "STRATEGY_RESULTS.md",
        "TRADES.csv",
    ]
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0

    report = json.loads(written["RUN_REPORT.json"].read_text(encoding="utf-8"))
    assert report["mode"].startswith("deterministic backtest")
    assert len(report["git"]["source_sha256"]) == 64
    for name, entry in report["artifacts"].items():
        digest = hashlib.sha256(written[name].read_bytes()).hexdigest()
        assert entry["sha256"] == digest
        assert entry["bytes"] == written[name].stat().st_size
    assert "RUN_REPORT.json" not in report["artifacts"]
    assert report["paper_status"]["integrated"] is False
    assert report["defects_fixed_in_this_wp"]
    assert report["limitations"]


def test_published_json_carries_no_private_buffers(tmp_path: Path) -> None:
    written = write_artifacts(_fake_campaign(), tmp_path)
    results = json.loads(written["STRATEGY_RESULTS.json"].read_text(encoding="utf-8"))
    text = written["STRATEGY_RESULTS.json"].read_text(encoding="utf-8")
    assert "_bar_returns" not in text
    assert "trade_rows" not in text
    assert "_equity_curve" not in text
    entry = results["candidates"]["edge_intra_01"]
    assert entry["verdict"] in {"ADMIT", "REJECT", "INSUFFICIENT_EVIDENCE"}
    assert entry["verdict_power"]
    assert entry["verdict_evidence"]["window_net_usdt"]
    assert entry["provenance"]["BTC"]["sha256"]


def test_summary_is_json_safe_and_keeps_the_scope() -> None:
    summary = _summary(_fake_campaign())
    text = json.dumps(summary)
    assert "_equity_curve" not in text
    assert summary["candidates"]["edge_intra_01"]["provenance"]


def test_run_report_markdown_states_the_honesty_limits(tmp_path: Path) -> None:
    written = write_artifacts(_fake_campaign(), tmp_path)
    md = written["RUN_REPORT.md"].read_text(encoding="utf-8")
    for expected in (
        "PAPER",
        "Limitaciones",
        "Hipótesis",
        "Defectos",
        "Contexto de mercado",
        "MARKET_CONTEXT.csv",
        "edge01_verify.py",
        "sha256",
    ):
        assert expected in md
    assert "0 órdenes" in md


def test_verdict_of_a_gate_result_is_one_of_three_labels() -> None:
    for kwargs in (
        {"dev": 1.0, "val": 1.0, "oos": 1.0},
        {"dev": -1.0, "val": -1.0, "oos": -1.0},
        {"dev": 1.0, "val": 1.0, "oos": -1.0, "trades": 2},
    ):
        assert verdict(**kwargs)["verdict"] in {"ADMIT", "REJECT", "INSUFFICIENT_EVIDENCE"}


@pytest.mark.parametrize("key", ["head_commit", "branch", "worktree_dirty", "source_sha256"])
def test_git_state_reports_the_measurement_identity(key: str) -> None:
    assert key in _git_state()


def _write_source_tree(root: Path, *, crlf: bool) -> None:
    body = "x = 1\ny = 2\n"
    payload = (body.replace("\n", "\r\n") if crlf else body).encode()
    module_dir = root / "src" / "trading_bot" / "research" / "edge01"
    module_dir.mkdir(parents=True, exist_ok=True)
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (module_dir / "campaign.py").write_bytes(payload)
    (scripts / "edge01_run.py").write_bytes(payload)
    (scripts / "edge01_verify.py").write_bytes(payload)


def test_source_digest_identifies_the_code_not_the_checkout_line_endings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same code, two checkouts' line endings: one digest (DEF-EDGE01-08)."""

    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    _write_source_tree(lf, crlf=False)
    _write_source_tree(crlf, crlf=True)
    monkeypatch.setattr(campaign_module, "REPO", lf)
    first = campaign_module._git_state()
    monkeypatch.setattr(campaign_module, "REPO", crlf)
    second = campaign_module._git_state()
    assert first["source_sha256"] == second["source_sha256"]
    assert "CRLF folded to LF" in str(first["source_digest_rule"])


def test_source_digest_changes_when_the_code_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The digest is not a constant: different code must not digest the same."""

    tree = tmp_path / "tree"
    _write_source_tree(tree, crlf=False)
    monkeypatch.setattr(campaign_module, "REPO", tree)
    before = campaign_module._git_state()["source_sha256"]
    module = tree / "src" / "trading_bot" / "research" / "edge01" / "campaign.py"
    module.write_bytes(module.read_bytes() + b"z = 3\n")
    assert campaign_module._git_state()["source_sha256"] != before
