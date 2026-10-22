"""EDGE-01 H1 ablation tests (WP-EDGE-01).

The ablation is the frozen EDGE-INTRA-01 with its 1h trend filter removed, scored
on DEV only. Two properties make its verdict worth reading, and both are pinned
here rather than asserted in prose:

* removing the gate does not change which setups EXIST. Both arms evaluate the
  same bars and consider the same number of setups; they only resolve them
  differently. The earlier belief that every other refusal could only grow was
  falsified by the real artefacts — ``level_already_traded`` is candidate state,
  so the ablation can refuse a setup before the gate it removed — and the test
  asserts the invariant that is actually a theorem;
* the verdict is a pure function of the published gross, net and trade counts,
  read with a rule frozen before the run.

The independent verifier is also loaded here and made to (a) accept a synthetic
ablation and (b) break on every mutation, so the check that judges the ablation
is itself judged on data whose answer is known.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.edge01.campaign import (
    ABLATION,
    ABLATION_DECISION,
    CANDIDATE_SCOPES,
    ablation_verdict,
    write_ablation_artifacts,
)
from trading_bot.research.edge01.candidates import (
    FROZEN_PARAMS,
    ContextSeries,
    build_candidates,
    build_context,
)
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge01.features import (
    MARKET_REGIME_RULE,
    market_regime_at,
    market_regime_series,
)
from trading_bot.research.edge01.simulator import RiskPolicy, run_portfolio

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STEP = BAR_MS["15m"]
_HOUR = BAR_MS["1h"]
_DAY = BAR_MS["1d"]

#: The pre-registered intraday DEV window, stated here independently so the
#: synthetic fixture lands inside the window the verifier hard-codes.
_DEV_START = int(datetime(2024, 10, 1, tzinfo=UTC).timestamp() * 1000)
_DEV_END = int(datetime(2025, 6, 30, tzinfo=UTC).timestamp() * 1000)


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> Any:
    return _load_script("edge01_ablation_verify")


def _bar(ts: int, *, o: float, h: float, low: float, c: float, v: float = 10.0) -> OHLCVBar:
    return OHLCVBar(ts=ts, open=o, high=h, low=low, close=c, volume=v)


def _policy(**overrides: Any) -> RiskPolicy:
    values: dict[str, Any] = {
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 3,
        "max_total_exposure_pct": 25.0,
        "max_asset_exposure_pct": 10.0,
        "min_notional_usdt": 25.0,
        "max_notional_usdt": 500.0,
        "drawdown_halt_pct": 5.0,
        "max_consecutive_losses": 3,
        "consecutive_loss_cooldown_minutes": 120.0,
        "max_trades_per_day": 20,
        "start_equity": 10_000.0,
    }
    values.update(overrides)
    return RiskPolicy(**values)


def _breakout_series(start_ts: int, count: int = 160) -> list[OHLCVBar]:
    """Strictly rising 15m bars: every bar clears the prior 20-bar high.

    Volume alternates so the expansion filter passes on odd bars only, which keeps
    ``volume_filter_fail`` in the funnel and makes the two arms share a non-trivial
    population of setups.
    """
    out: list[OHLCVBar] = []
    price = 100.0
    for i in range(count):
        price += 0.25
        out.append(
            _bar(
                start_ts + i * _STEP,
                o=price - 0.05,
                h=price + 0.10,
                low=price - 0.20,
                c=price,
                v=40.0 if i % 2 else 10.0,
            )
        )
    return out


def _downtrend_context(anchor_ts: int, *, warmup_hours: int = 400, span_hours: int = 80) -> ContextSeries:
    """A 1h context that is DOWN and seeded long before the 15m bars start.

    The slow EMA needs 200 closed 1h bars before the gate can even be evaluated, so
    the series begins ``warmup_hours`` before the anchor rather than at it.
    """
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


def _considered(signals: list[dict[str, Any]], funnel: dict[str, int]) -> int:
    return len(signals) + sum(v for k, v in funnel.items() if k.startswith("candidate:"))


def _run(candidate: Any, bars: list[OHLCVBar], context: ContextSeries, *, start: int, end: int) -> Any:
    return run_portfolio(
        candidate=candidate,
        bars_by_asset={"BTC": bars},
        plane=cost_plane(size_usd=500.0, horizon_minutes=240.0),
        policy=_policy(),
        context=context,
        window_start_ts=start,
        window_end_ts=end,
    )


# --------------------------------------------------------------------------- #
# The gate is removed, and nothing else moves
# --------------------------------------------------------------------------- #


def test_the_ablation_removes_the_trend_gate_and_nothing_else() -> None:
    start = _DEV_START
    bars = _breakout_series(start)
    context = _downtrend_context(start)
    end = bars[-1].ts + _STEP
    candidates = build_candidates()
    base, ablation = candidates["edge_intra_01"], candidates["edge_intra_01_no_trend"]

    base_run = _run(base, bars, context, start=start, end=end)
    ab_run = _run(ablation, bars, context, start=start, end=end)
    base_funnel, ab_funnel = _funnel(base_run.refusals), _funnel(ab_run.refusals)

    # the gate itself: used by the base, gone from the ablation
    assert base_funnel.get("candidate:trend_filter_fail", 0) > 0
    assert ab_funnel.get("candidate:trend_filter_fail", 0) == 0

    # the population of setups is identical, only the resolution differs
    assert base.bars_evaluated == ablation.bars_evaluated
    assert base.warmup_bars == ablation.warmup_bars
    assert _considered(base_run.signals, base_funnel) == _considered(ab_run.signals, ab_funnel)
    assert _considered(base_run.signals, base_funnel) >= base_funnel["candidate:trend_filter_fail"]

    # the ablation cannot produce fewer signals than the base: every base signal
    # passed the gate, and the path after it is identical
    assert len(ab_run.signals) >= len(base_run.signals)


def test_the_switch_is_an_override_and_the_frozen_params_are_untouched() -> None:
    assert "use_trend_filter" not in FROZEN_PARAMS["edge_intra_01"]
    candidates = build_candidates()
    base, ablation = candidates["edge_intra_01"], candidates["edge_intra_01_no_trend"]
    assert base.params == FROZEN_PARAMS["edge_intra_01"]
    assert set(ablation.params) - set(base.params) == {"use_trend_filter"}
    assert {k: v for k, v in ablation.params.items() if k != "use_trend_filter"} == base.params
    assert ablation.id == base.id == "edge_intra_01"
    assert ablation.timeframe == base.timeframe == "15m"
    assert ablation.context_timeframe == base.context_timeframe == "1h"
    assert base.use_trend_filter is True
    assert ablation.use_trend_filter is False


def test_the_ablation_is_not_in_the_published_campaign_scope() -> None:
    """VAL and OOS stay unread: a post-hoc variant may not be scored there."""
    assert ABLATION["window"] == "DEV"
    assert ABLATION["ablation_candidate"] not in CANDIDATE_SCOPES
    assert ABLATION["base_candidate"] in CANDIDATE_SCOPES
    assert "edge_intra_01_no_trend" not in CANDIDATE_SCOPES


# --------------------------------------------------------------------------- #
# The verdict is the pre-registered rule, applied to published numbers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("base", "ablation", "expected"),
    (
        ({"trades": 50, "gross_usdt": -20.0}, {"trades": 200, "gross_usdt": -35.0, "net_usdt": -60.0},
         "BREAKOUT_IS_THE_CAUSE"),
        # exactly zero is not positive: the breakout still has to earn its edge
        ({"trades": 50, "gross_usdt": -20.0}, {"trades": 200, "gross_usdt": 0.0, "net_usdt": -50.0},
         "BREAKOUT_IS_THE_CAUSE"),
        ({"trades": 50, "gross_usdt": -20.0}, {"trades": 80, "gross_usdt": 15.0, "net_usdt": -30.0},
         "FILTER_SUPPRESSED_A_PRECOST_EDGE"),
        ({"trades": 50, "gross_usdt": -20.0}, {"trades": 80, "gross_usdt": 15.0, "net_usdt": 3.0},
         "FILTER_HARMS_EDGE"),
        # an unpowered arm never gets a direction
        ({"trades": 5, "gross_usdt": -20.0}, {"trades": 8, "gross_usdt": 15.0, "net_usdt": 3.0},
         "INCONCLUSIVE"),
        ({"trades": 50, "gross_usdt": -20.0}, {"trades": 4, "gross_usdt": -1.0, "net_usdt": -2.0},
         "INCONCLUSIVE"),
    ),
)
def test_the_verdict_is_the_frozen_rule(base: dict[str, Any], ablation: dict[str, Any], expected: str) -> None:
    verdict = ablation_verdict(base, ablation)
    assert verdict["verdict"] == expected
    assert verdict["reason"]
    assert verdict["rule"]["min_dev_trades"] == ABLATION_DECISION["min_dev_trades"]
    assert verdict["rule"]["gross_positive_usdt"] == ABLATION_DECISION["gross_positive_usdt"]


def test_the_frozen_rule_and_window_are_the_documented_ones() -> None:
    assert ABLATION["id"] == "ABL-EDGE01-H1"
    assert ABLATION["hypothesis"] == "H1"
    assert ABLATION["removed"] == "use_trend_filter"
    assert ABLATION["base_candidate"] == "edge_intra_01"
    assert ABLATION["ablation_candidate"] == "edge_intra_01_no_trend"
    assert ABLATION["split"] == "intraday"
    assert ABLATION["window"] == "DEV"
    assert ABLATION["scenario"] == "BASE"
    assert ABLATION_DECISION["min_dev_trades"] == 30
    assert ABLATION_DECISION["gross_positive_usdt"] == 0.0
    for label in (
        "BREAKOUT_IS_THE_CAUSE",
        "FILTER_SUPPRESSED_A_PRECOST_EDGE",
        "FILTER_HARMS_EDGE",
        "INCONCLUSIVE",
    ):
        assert label in ABLATION_DECISION["meaning"]


# --------------------------------------------------------------------------- #
# The artefacts, and the verifier that judges them
# --------------------------------------------------------------------------- #


def _benchmark_rows() -> tuple[list[Any], dict[str, Any]]:
    """A rising daily benchmark, long enough for the 200-day EMA and its slope."""
    bars = [_bar(_DEV_START - 250 * _DAY + i * _DAY, o=1.0, h=1.0, low=1.0, c=100.0 + i) for i in range(260)]
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
    start = _DEV_START
    bars = _breakout_series(start)
    context = _downtrend_context(start)
    # The declared window is the whole pre-registered DEV window and the simulated
    # window is that same window; the corpus is short, it is not a smaller window.
    end = _DEV_END
    candidates = build_candidates()
    planes = cost_plane(size_usd=1000.0, horizon_minutes=240.0)
    regime_rows, regime_meta = _benchmark_rows()
    arms: dict[str, Any] = {}
    for role, candidate_id in (("base", "edge_intra_01"), ("ablation", "edge_intra_01_no_trend")):
        candidate = candidates[candidate_id]
        run = _run(candidate, bars, context, start=start, end=end)
        for trade in run.trades:
            trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        trades = run.trades
        by_context: dict[str, dict[str, Any]] = {}
        for trade in trades:
            entry = by_context.setdefault(
                trade["market_context"], {"trades": 0, "net": 0.0, "win_rate": None}
            )
            entry["trades"] += 1
            entry["net"] = round(entry["net"] + trade["net"], 4)
        arms[role] = {
            "candidate_id": candidate_id,
            "params": dict(candidate.params),
            "use_trend_filter": candidate.use_trend_filter,
            "bars_evaluated": candidate.bars_evaluated,
            "warmup_bars": candidate.warmup_bars,
            "signal_count": len(run.signals),
            "refusals": _funnel(run.refusals),
            "trades": len(trades),
            "gross_usdt": round(sum(t["gross"] for t in trades), 4),
            "fees_usdt": round(sum(t["fees"] for t in trades), 4),
            "price_costs_usdt": round(sum(t["price_costs"] for t in trades), 4),
            "net_usdt": round(sum(t["net"] for t in trades), 4),
            "by_market_context": by_context,
            "_trade_rows": trades,
            "_refusal_rows": run.refusals,
            "_signal_rows": run.signals,
        }
    return {
        "run_id": "wp-edge-01-ablation-h1",
        "generated_at_utc": "2024-10-02T00:00:00+00:00",
        "git": {"head_commit": "0" * 40, "branch": "test", "worktree_dirty": False},
        "source_digest": {"combined_sha256": "a" * 64, "files": {}},
        "mode": "deterministic backtest over the local historical corpus, DEV window only",
        "entrypoint": "scripts/edge01_ablation.py",
        "verifier": "scripts/edge01_ablation_verify.py",
        "params_hash": "b" * 64,
        "ablation": {
            **ABLATION,
            "window_start_utc": datetime.fromtimestamp(_DEV_START / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(_DEV_END / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "assets": ["BTC", "ETH", "SOL"],
            "timeframe": "15m",
            "plane": planes.to_dict(),
            "risk_policy": _policy().to_dict(),
            "frozen_params": FROZEN_PARAMS["edge_intra_01"],
            "corpus_provenance": {},
            "market_context_meta": regime_meta,
        },
        "verdict": ablation_verdict(arms["base"], arms["ablation"]),
        "arms": arms,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
    }


def test_write_ablation_artifacts_publishes_the_five_files_with_digests(tmp_path: Path) -> None:
    written = write_ablation_artifacts(_synthetic_payload(), tmp_path)
    assert sorted(written) == [
        "ABLATION.json",
        "ABLATION.md",
        "ABLATION_REFUSALS.csv",
        "ABLATION_SIGNALS.csv",
        "ABLATION_TRADES.csv",
        "MARKET_CONTEXT.csv",
    ]
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0
    body = json.loads(written["ABLATION.json"].read_text(encoding="utf-8"))
    for name, entry in body["artifacts"].items():
        assert entry["sha256"] == hashlib.sha256(written[name].read_bytes()).hexdigest()
        assert entry["bytes"] == written[name].stat().st_size
    assert "ABLATION.json" not in body["artifacts"]
    text = written["ABLATION.json"].read_text(encoding="utf-8")
    assert "_trade_rows" not in text
    assert "_refusal_rows" not in text
    markdown = written["ABLATION.md"].read_text(encoding="utf-8")
    assert "antes de costes" in markdown
    assert "Embudo de rechazos" in markdown
    assert "SOLO DEV" in markdown


def test_the_independent_verifier_accepts_the_ablation_it_would_judge(tmp_path: Path, verifier: Any) -> None:
    write_ablation_artifacts(_synthetic_payload(), tmp_path)
    checks = verifier.run_checks(tmp_path)
    failures = [entry for entry in checks if not entry["ok"]]
    assert not failures, failures
    assert {entry["check"] for entry in checks} == {
        "ARTIFACTS_PRESENT",
        "WINDOW_IS_PREREGISTERED_DEV",
        "GROSS_BEFORE_COSTS_RECOMPUTED",
        "COST_SPLIT_IDENTITY",
        "FUNNEL_ARITHMETIC",
        "SIGNALS_ARITHMETIC",
        "ABLATION_ISOLATION",
        "MARKET_CONTEXT_ATTRIBUTION",
        "DECISION_RULE_FROZEN",
        "VERDICT_RECOMPUTED",
    }


def test_the_independent_verifier_breaks_on_every_mutation(tmp_path: Path, verifier: Any) -> None:
    write_ablation_artifacts(_synthetic_payload(), tmp_path)
    report = verifier.self_test(tmp_path)
    undetected = [m for m in report["mutations"] if not m["expected_check_failed"]]
    assert not undetected, undetected
    assert report["baseline_all_green"]
    assert len(report["mutations"]) >= 8


def test_the_verifier_refuses_a_directory_missing_an_artefact(tmp_path: Path, verifier: Any) -> None:
    write_ablation_artifacts(_synthetic_payload(), tmp_path)
    (tmp_path / "ABLATION_REFUSALS.csv").unlink()
    with pytest.raises(verifier.Fatal):
        verifier.run_checks(tmp_path)
