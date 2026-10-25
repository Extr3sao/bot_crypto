"""EDGE-01 H5 risk-budget tests (WP-EDGE-01).

H1 left the extra intraday signals refused by the risk layer rather than by the
entry rules. H5 changes exactly one field of the risk budget — the 5% drawdown
halt is made inert — and asks whether that halt was the ceiling on intraday
participation and whether the trades it refused were worth taking.

Two properties make the comparison trustworthy, and this file pins them:

* the variant really is ONE field apart, and the base really is
  ``config/risk.yaml`` read verbatim (checked against the file, not against a
  copy of its numbers);
* a risk budget cannot change what the candidate prints. The simulator asks the
  candidate for a setup on every bar, so signals and candidate-level refusals must
  be identical in both arms; only the risk layer may move. Without that, a
  difference in the results could be a different candidate, corpus or window.

The independent verifier is loaded here and made to (a) accept a synthetic run and
(b) break on every mutation, so the check that judges the experiment is itself
judged on data whose answer is known.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from trading_bot.research.edge01.campaign import (
    RISK_ABLATION,
    RISK_ABLATION_DECISION,
    risk_ablation_verdict,
    risk_budgets,
    write_risk_ablation_artifacts,
)
from trading_bot.research.edge01.candidates import ContextSeries, build_candidates, build_context
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge01.features import (
    MARKET_REGIME_RULE,
    market_regime_at,
    market_regime_series,
)
from trading_bot.research.edge01.simulator import run_portfolio

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STEP = BAR_MS["15m"]
_HOUR = BAR_MS["1h"]
_DAY = BAR_MS["1d"]
_DEV_START = int(datetime(2024, 10, 1, tzinfo=UTC).timestamp() * 1000)
_DEV_END = int(datetime(2025, 6, 30, tzinfo=UTC).timestamp() * 1000)

#: Where the config the base arm claims to read lives, relative to the repo root.
RISK_CONFIG_REL = "config/risk.yaml"

#: config/risk.yaml key -> RiskPolicy field. The mapping the runner relies on.
CONFIG_FIELD_MAP = {
    "risk_per_trade_pct": "max_risk_per_trade_pct",
    "max_open_positions": "max_open_positions",
    "max_total_exposure_pct": "max_total_exposure_pct",
    "max_asset_exposure_pct": "max_asset_exposure_pct",
    "min_notional_usdt": "min_order_notional_usdt",
    "max_notional_usdt": "max_order_notional_usdt",
    "drawdown_halt_pct": "max_total_drawdown_pct",
    "max_consecutive_losses": "max_consecutive_losses",
    "consecutive_loss_cooldown_minutes": "consecutive_loss_cooldown_minutes",
    "max_trades_per_day": "max_trades_per_day",
}


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> Any:
    return _load_script("edge01_risk_ablation_verify")


def _bar(ts: int, *, o: float, h: float, low: float, c: float, v: float = 10.0) -> OHLCVBar:
    return OHLCVBar(ts=ts, open=o, high=h, low=low, close=c, volume=v)


def _sawtooth_series(
    start_ts: int, *, cycles: int = 40, rise: int = 6, fall: int = 6, up: float = 1.025, down: float = 0.985
) -> list[OHLCVBar]:
    """Breakout then reversal, repeated: every cycle fills a long and then stops it out.

    A series that only rises never draws the account down far enough for the REAL
    5% halt to fire (that needs roughly twenty consecutive stop-outs at 0.25% risk),
    and a series that only falls never breaks a level. The sawtooth does both, so the
    fixture exercises the halt under the runtime's own budget rather than a rigged one.
    """
    out: list[OHLCVBar] = []
    price = 100.0
    ts = start_ts
    for _ in range(cycles):
        for _step in range(rise):
            price *= up
            out.append(_bar(ts, o=price * 0.998, h=price * 1.001, low=price * 0.997, c=price, v=60.0))
            ts += _STEP
        for _step in range(fall):
            price *= down
            out.append(_bar(ts, o=price * 1.001, h=price * 1.002, low=price * 0.995, c=price, v=8.0))
            ts += _STEP
    return out


def _downtrend_context(anchor_ts: int, *, warmup_hours: int = 400, span_hours: int = 80) -> ContextSeries:
    bars: list[OHLCVBar] = []
    price = 400.0
    for i in range(warmup_hours + span_hours):
        price -= 0.05
        bars.append(
            _bar(
                anchor_ts - warmup_hours * _HOUR + i * _HOUR,
                o=price + 0.02,
                h=price + 0.05,
                low=price - 0.08,
                c=price,
            )
        )
    return build_context(bars, timeframe="1h", fast=50, slow=200)


def _funnel(refusals: list[dict[str, Any]]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for refusal in refusals:
        key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
        mix[key] = mix.get(key, 0) + 1
    return mix


def _candidate_key(signal: dict[str, Any]) -> tuple[Any, ...]:
    return (signal["symbol"], signal["bar_index"], signal["decision_ts"], signal["regime"])


# --------------------------------------------------------------------------- #
# The budgets: one field apart, and the base is the runtime's config itself
# --------------------------------------------------------------------------- #


def test_the_base_budget_is_config_risk_yaml_read_verbatim() -> None:
    config = yaml.safe_load((_REPO_ROOT / RISK_CONFIG_REL).read_text(encoding="utf-8"))["risk"]
    base = risk_budgets()["base"]
    published = base.to_dict()
    for field, config_key in CONFIG_FIELD_MAP.items():
        assert published[field] == config[config_key], f"{field} != {config_key} in {RISK_CONFIG_REL}"
    assert published["start_equity"] == 10_000.0  # the measurement's starting capital


def test_the_variant_is_the_base_with_exactly_one_field_replaced() -> None:
    budgets = risk_budgets()
    base, variant = budgets["base"].to_dict(), budgets["variant"].to_dict()
    changed = sorted(k for k in base if base[k] != variant[k])
    assert changed == [RISK_ABLATION["changed_field"]] == ["drawdown_halt_pct"]
    assert variant["drawdown_halt_pct"] == RISK_ABLATION["inert_halt_pct"] == 100.0
    # a halt at 100% of peak equity is unreachable, so it cannot fire
    assert variant["drawdown_halt_pct"] > 100.0 - 1e-9
    # removing it must not silence any other limit
    assert budgets["variant"].max_trades_per_day == budgets["base"].max_trades_per_day
    assert budgets["variant"].max_open_positions == budgets["base"].max_open_positions


def test_the_experiment_is_dev_only_and_reads_one_config() -> None:
    assert RISK_ABLATION["window"] == "DEV"
    assert RISK_ABLATION["split"] == "intraday"
    assert RISK_ABLATION["scenario"] == "BASE"
    assert RISK_ABLATION["candidate"] == "edge_intra_01"
    assert RISK_ABLATION["id"] == "ABL-EDGE01-H5"
    assert RISK_ABLATION_DECISION["min_extra_trades"] == 20
    assert RISK_ABLATION_DECISION["marginal_net_positive_usdt"] == 0.0
    for label in (
        "INCONCLUSIVE",
        "RISK_NOT_BINDING_ON_PROFITABILITY",
        "RISK_BUDGET_WAS_THE_CONSTRAINT",
        "FREQUENCY_VIABLE",
    ):
        assert label in RISK_ABLATION_DECISION["meaning"]


# --------------------------------------------------------------------------- #
# The invariant: a risk budget cannot change what the candidate prints
# --------------------------------------------------------------------------- #


def test_the_risk_budget_cannot_change_the_candidate_layer() -> None:
    start = _DEV_START
    bars = _sawtooth_series(start)
    context = _downtrend_context(start)
    # The 1h gate would refuse every setup on a downtrend context and there would be
    # no equity path to speak of, so the H1 ablation candidate prints the setups here.
    candidate_id = "edge_intra_01_no_trend"
    budgets = risk_budgets()

    runs = {}
    for role in ("base", "variant"):
        policy = budgets[role]
        candidate = build_candidates()[candidate_id]
        runs[role] = (
            run_portfolio(
                candidate=candidate,
                bars_by_asset={"BTC": bars},
                plane=cost_plane(size_usd=500.0, horizon_minutes=240.0),
                policy=policy,
                context=context,
                window_start_ts=start,
                window_end_ts=_DEV_END,
            ),
            candidate,
        )

    base_run, base_candidate = runs["base"]
    variant_run, variant_candidate = runs["variant"]

    # the intervention happened, under the runtime's own 5% halt, not a rigged one
    assert budgets["base"].drawdown_halt_pct == 5.0
    assert _funnel(base_run.refusals).get("risk:risk_drawdown_halt", 0) > 0
    assert _funnel(variant_run.refusals).get("risk:risk_drawdown_halt", 0) == 0
    assert len(variant_run.trades) > len(base_run.trades)

    # ...and only in the risk layer
    assert [_candidate_key(s) for s in base_run.signals] == [
        _candidate_key(s) for s in variant_run.signals
    ]
    base_candidate_funnel = {k: v for k, v in _funnel(base_run.refusals).items() if k.startswith("candidate:")}
    variant_candidate_funnel = {
        k: v for k, v in _funnel(variant_run.refusals).items() if k.startswith("candidate:")
    }
    assert base_candidate_funnel == variant_candidate_funnel
    assert base_candidate.bars_evaluated == variant_candidate.bars_evaluated
    assert base_candidate.warmup_bars == variant_candidate.warmup_bars


# --------------------------------------------------------------------------- #
# The verdict is the pre-registered rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("base", "variant", "expected"),
    (
        # the halt blocked real trades, and they lost: the budget is not the problem
        (
            {"trades": 290, "net_usdt": -496.0, "gross_usdt": -151.0},
            {"trades": 670, "net_usdt": -892.0, "gross_usdt": -96.0},
            "RISK_NOT_BINDING_ON_PROFITABILITY",
        ),
        # the halt is inert but nothing more executes: unpowered, no direction
        (
            {"trades": 290, "net_usdt": -496.0, "gross_usdt": -151.0},
            {"trades": 300, "net_usdt": -500.0, "gross_usdt": -150.0},
            "INCONCLUSIVE",
        ),
        # the extra trades pay, but the whole thing still loses
        (
            {"trades": 290, "net_usdt": -496.0, "gross_usdt": -151.0},
            {"trades": 670, "net_usdt": -100.0, "gross_usdt": 200.0},
            "RISK_BUDGET_WAS_THE_CONSTRAINT",
        ),
        # the extra trades pay AND the account ends up: a hypothesis to re-test
        (
            {"trades": 290, "net_usdt": -496.0, "gross_usdt": -151.0},
            {"trades": 670, "net_usdt": 250.0, "gross_usdt": 600.0},
            "FREQUENCY_VIABLE",
        ),
        # exactly zero marginal net is not positive
        (
            {"trades": 290, "net_usdt": -496.0, "gross_usdt": -151.0},
            {"trades": 400, "net_usdt": -496.0, "gross_usdt": -100.0},
            "RISK_NOT_BINDING_ON_PROFITABILITY",
        ),
    ),
)
def test_the_verdict_is_the_frozen_rule(
    base: dict[str, Any], variant: dict[str, Any], expected: str
) -> None:
    base.setdefault("max_drawdown_pct", 5.0)
    variant.setdefault("max_drawdown_pct", 9.0)
    verdict = risk_ablation_verdict(base, variant)
    assert verdict["verdict"] == expected
    assert verdict["reason"]
    assert verdict["extra_trades"] == variant["trades"] - base["trades"]
    assert verdict["marginal_net_usdt"] == pytest.approx(variant["net_usdt"] - base["net_usdt"])
    assert verdict["rule"]["min_extra_trades"] == RISK_ABLATION_DECISION["min_extra_trades"]


# --------------------------------------------------------------------------- #
# The artefacts, and the verifier that judges them
# --------------------------------------------------------------------------- #


def _benchmark_rows() -> tuple[list[Any], dict[str, Any]]:
    bars = [
        _bar(_DEV_START - 250 * _DAY + i * _DAY, o=1.0, h=1.0, low=1.0, c=100.0 + i)
        for i in range(260)
    ]
    rows = market_regime_series(bars)
    labels = sorted({row.label for row in rows})
    meta = {
        "benchmark": "BTC",
        "rule": MARKET_REGIME_RULE,
        "labels": ["BULL", "BEAR", "SIDEWAYS", "UNDEFINED"],
        "days": len(rows),
        "last_close_ms": rows[-1].close_ms,
        "label_days": {label: sum(1 for r in rows if r.label == label) for label in labels},
    }
    return rows, meta


def _synthetic_payload() -> dict[str, Any]:
    import hashlib

    start = _DEV_START
    bars = _sawtooth_series(start)
    context = _downtrend_context(start)
    end = _DEV_END
    budgets = risk_budgets()
    plane = cost_plane(size_usd=1000.0, horizon_minutes=240.0)
    regime_rows, regime_meta = _benchmark_rows()
    arms: dict[str, Any] = {}
    for role, policy in budgets.items():
        candidate = build_candidates()["edge_intra_01_no_trend"]
        run = run_portfolio(
            candidate=candidate,
            bars_by_asset={"BTC": bars},
            plane=plane,
            policy=policy,
            context=context,
            window_start_ts=start,
            window_end_ts=end,
        )
        for trade in run.trades:
            trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        halt = [r for r in run.refusals if r.get("reason") == "risk_drawdown_halt"]
        trades = run.trades
        peak = policy.start_equity
        max_dd = 0.0
        for _ts, equity in run.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100.0)
        by_context: dict[str, dict[str, Any]] = {}
        for trade in trades:
            entry = by_context.setdefault(
                trade["market_context"], {"trades": 0, "net": 0.0, "win_rate": None}
            )
            entry["trades"] += 1
            entry["net"] = round(entry["net"] + trade["net"], 4)
        count = len(trades)
        arms[role] = {
            "candidate_id": "edge_intra_01",
            "policy": policy.to_dict(),
            "bars_evaluated": candidate.bars_evaluated,
            "warmup_bars": candidate.warmup_bars,
            "signal_count": len(run.signals),
            "refusals": _funnel(run.refusals),
            "halt_refusals": len(halt),
            "halt_days": len({int(r["decision_ts"]) // 86_400_000 for r in halt}),
            "halt_days_pct_of_window": 0.0,
            "trades": count,
            "gross_usdt": round(sum(t["gross"] for t in trades), 4),
            "gross_per_trade_usdt": round(sum(t["gross"] for t in trades) / count, 4) if count else None,
            "fees_usdt": round(sum(t["fees"] for t in trades), 4),
            "price_costs_usdt": round(sum(t["price_costs"] for t in trades), 4),
            "net_usdt": round(sum(t["net"] for t in trades), 4),
            "expectancy_usdt": round(sum(t["net"] for t in trades) / count, 4) if count else None,
            "max_drawdown_pct": round(max_dd, 4),
            "exposure_pct_of_time": round(
                sum(t["duration_min"] for t in trades)
                / ((end - start) / 60_000.0 * 3)
                * 100.0,
                4,
            ),
            "by_market_context": by_context,
            "_trade_rows": trades,
            "_refusal_rows": run.refusals,
            "_signal_rows": run.signals,
        }
    return {
        "run_id": "wp-edge-01-risk-ablation-h5",
        "generated_at_utc": "2024-10-02T00:00:00+00:00",
        "git": {"head_commit": "0" * 40, "branch": "test", "worktree_dirty": False},
        "source_digest": {"combined_sha256": "a" * 64, "files": {}},
        "mode": "deterministic backtest over the local historical corpus, DEV window only",
        "entrypoint": "scripts/edge01_risk_ablation.py",
        "verifier": "scripts/edge01_risk_ablation_verify.py",
        "params_hash": "b" * 64,
        "risk_ablation": {
            **RISK_ABLATION,
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "window_days": (end - start) / 86_400_000.0,
            "assets": ["BTC", "ETH", "SOL"],
            "timeframe": "15m",
            "plane": plane.to_dict(),
            "risk_config_path": RISK_CONFIG_REL,
            "risk_config_sha256": hashlib.sha256(
                (_REPO_ROOT / RISK_CONFIG_REL).read_bytes()
            ).hexdigest(),
            "risk_config_used_verbatim_for_base": True,
            "runtime_untouched": "research instrument only",
            "corpus_provenance": {},
        },
        "verdict": risk_ablation_verdict(arms["base"], arms["variant"]),
        "arms": arms,
        "market_context": {"meta": regime_meta, "rows": [row.to_row() for row in regime_rows]},
    }


def test_write_risk_ablation_artifacts_publishes_six_files_with_digests(tmp_path: Path) -> None:
    written = write_risk_ablation_artifacts(_synthetic_payload(), tmp_path)
    assert sorted(written) == [
        "MARKET_CONTEXT.csv",
        "RISK_ABLATION.json",
        "RISK_ABLATION.md",
        "RISK_REFUSALS.csv",
        "RISK_SIGNALS.csv",
        "RISK_TRADES.csv",
    ]
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0
    body = json.loads(written["RISK_ABLATION.json"].read_text(encoding="utf-8"))
    for name, entry in body["artifacts"].items():
        assert entry["bytes"] == written[name].stat().st_size
    assert "RISK_ABLATION.json" not in body["artifacts"]
    text = written["RISK_ABLATION.json"].read_text(encoding="utf-8")
    assert "_trade_rows" not in text and "_signal_rows" not in text
    markdown = written["RISK_ABLATION.md"].read_text(encoding="utf-8")
    assert "SOLO DEV" in markdown
    assert "Los dos presupuestos" in markdown
    assert "Lectura marginal" in markdown
    assert "instrumento de investigacion" in markdown


def test_the_independent_verifier_accepts_the_run_it_would_judge(tmp_path: Path, verifier: Any) -> None:
    write_risk_ablation_artifacts(_synthetic_payload(), tmp_path)
    checks = verifier.run_checks(tmp_path)
    failures = [entry for entry in checks if not entry["ok"]]
    assert not failures, failures
    assert {entry["check"] for entry in checks} == {
        "ARTIFACTS_PRESENT",
        "WINDOW_IS_PREREGISTERED_DEV",
        "BUDGET_IS_ONE_FIELD_APART",
        "HALT_IS_INERT_IN_VARIANT",
        "CANDIDATE_LAYER_IDENTICAL",
        "GROSS_BEFORE_COSTS_RECOMPUTED",
        "COST_SPLIT_IDENTITY",
        "FUNNEL_ARITHMETIC",
        "FUNNEL_SPLIT_BY_LAYER",
        "MARGINAL_ARITHMETIC",
        "MARKET_CONTEXT_ATTRIBUTION",
        "DECISION_RULE_FROZEN",
        "VERDICT_RECOMPUTED",
    }


def test_the_independent_verifier_breaks_on_every_mutation(tmp_path: Path, verifier: Any) -> None:
    write_risk_ablation_artifacts(_synthetic_payload(), tmp_path)
    report = verifier.self_test(tmp_path)
    undetected = [m for m in report["mutations"] if not m["expected_check_failed"]]
    assert not undetected, undetected
    assert report["baseline_all_green"]
    assert len(report["mutations"]) >= 12


def test_the_verifier_refuses_a_directory_missing_an_artefact(tmp_path: Path, verifier: Any) -> None:
    write_risk_ablation_artifacts(_synthetic_payload(), tmp_path)
    (tmp_path / "RISK_TRADES.csv").unlink()
    with pytest.raises(verifier.Fatal):
        verifier.run_checks(tmp_path)
