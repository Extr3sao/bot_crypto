"""EDGE-01 H2/H4 mechanism-experiment tests (WP-EDGE-01).

H1 asked what the intraday funnel refuses; H5 asked what the risk budget does with
what survives it. H2 and H4 ask two MECHANISM questions, each with its own DEV-only
experiment built on the same frozen pattern (declaration, pre-registered rule,
artefacts, independent verifier):

* H2 — is the intraday entry LATE relative to the level it breaks? A diagnostic:
  it changes no rule and splits the executed trades by their distance to the level.
* H4 — does a minimum ATR/close entry filter help EDGE-TREND-01? An ablation with a
  grid read off the DEV input distribution, selected on DEV and FROZEN, never
  promoted, never read on VAL/OOS.

This file pins the properties that make both readable rather than decorative: the
rules are functions of their frozen constants, the buckets are the declared edges
and nothing else, the ATR grid really is the declared percentile of the published
sample, an arm really is the frozen candidate plus one field, and the verifier that
judges the artefacts is itself judged by making it break on known mutations.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.edge01.campaign import (
    ENTRY_TIMING_H2,
    ENTRY_TIMING_H2_DECISION,
    VOL_FILTER_H4,
    VOL_FILTER_H4_DECISION,
    _atr_pct_sample,
    _bucket_labels,
    _bucket_stats,
    _distance_bucket,
    _join_signal_fills,
    _median,
    _metrics,
    _nearest_rank_percentile,
    _params_delta,
    entry_timing_verdict,
    load_risk_policy,
    vol_filter_grid,
    vol_filter_verdict,
    write_entry_timing_artifacts,
    write_vol_filter_artifacts,
)
from trading_bot.research.edge01.candidates import (
    FROZEN_PARAMS,
    PARAMS_HASH,
    TrendFollow,
    build_candidates,
    build_context,
)
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge01.features import (
    MARKET_REGIME_RULE,
    atr,
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

#: The candidate hash frozen before the campaign ran. H2 and H4 must not move it:
#: H4's gate is an optional field set by override, never a change to FROZEN_PARAMS.
FROZEN_PARAMS_HASH_PREFIX = "d073a2d6"


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> Any:
    return _load_script("edge01_mechanism_ablation_verify")


def _bar(ts: int, *, o: float, h: float, low: float, c: float, v: float = 10.0) -> OHLCVBar:
    return OHLCVBar(ts=ts, open=o, high=h, low=low, close=c, volume=v)


def _breakout_series(
    start_ts: int,
    *,
    cycles: int,
    ups: list[float],
    down: float,
    rise: int = 7,
    fall: int = 5,
    wick: float = 0.0015,
    v_rise: float = 60.0,
    v_fall: float = 12.0,
) -> list[OHLCVBar]:
    """Breakout run, pullback, repeat: a book the candidates can actually trade.

    The rise multiplier is cycled through ``ups`` so the breakouts arrive with
    different strength, and bars open at the previous close (no artificial gap).
    Prices stay in a range a real book has: the arithmetic of the position sizing
    assumes it, and a series that compounds to 1e10 tests the fixture, not the code.
    """

    out: list[OHLCVBar] = []
    price = 100.0
    ts = start_ts
    for cycle in range(cycles):
        up = ups[cycle % len(ups)]
        for _index in range(rise):
            previous = price
            price *= up
            out.append(_bar(ts, o=previous, h=price * (1 + wick), low=price * (1 - wick), c=price, v=v_rise))
            ts += _STEP
        for _index in range(fall):
            previous = price
            price *= down
            out.append(_bar(ts, o=previous, h=price * (1 + wick), low=price * (1 - wick), c=price, v=v_fall))
            ts += _STEP
    return out


def _downtrend_context(anchor_ts: int, *, warmup_hours: int = 400, span_hours: int = 400) -> Any:
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


# --------------------------------------------------------------------------- #
# The declarations: written down before the runs
# --------------------------------------------------------------------------- #


def test_h2_declares_a_diagnostic_that_changes_no_rule() -> None:
    assert ENTRY_TIMING_H2["id"] == "ABL-EDGE01-H2"
    assert ENTRY_TIMING_H2["kind"] == "diagnostic"
    assert ENTRY_TIMING_H2["changed_rule"] is None
    assert ENTRY_TIMING_H2["candidate"] == "edge_intra_01"
    assert ENTRY_TIMING_H2["split"] == "intraday"
    assert ENTRY_TIMING_H2["window"] == "DEV"
    assert ENTRY_TIMING_H2["scenario"] == "BASE"
    assert ENTRY_TIMING_H2["bucket_edges_atr"] == [0.25, 0.5, 1.0]
    assert ENTRY_TIMING_H2_DECISION["min_trades_per_side"] == 25
    for label in ("INCONCLUSIVE", "ENTRY_IS_LATE", "ENTRY_NOT_THE_PROBLEM"):
        assert label in ENTRY_TIMING_H2_DECISION["meaning"]


def test_h4_declares_its_grid_and_its_rule_before_the_arms_run() -> None:
    assert VOL_FILTER_H4["id"] == "ABL-EDGE01-H4"
    assert VOL_FILTER_H4["kind"] == "ablation"
    assert VOL_FILTER_H4["changed_field"] == "min_atr_pct"
    assert VOL_FILTER_H4["baseline_threshold_pct"] is None
    assert VOL_FILTER_H4["grid_percentiles"] == [25.0, 50.0, 75.0]
    assert "nearest rank" in str(VOL_FILTER_H4["percentile_rule"])
    assert VOL_FILTER_H4["split"] == "trend" and VOL_FILTER_H4["window"] == "DEV"
    assert VOL_FILTER_H4_DECISION["min_dev_trades"] == 30
    assert VOL_FILTER_H4_DECISION["min_improvement_usdt"] == 0.0
    assert VOL_FILTER_H4_DECISION["max_single_trade_share_of_net"] == 0.5
    for label in ("INCONCLUSIVE", "FILTER_NOT_JUSTIFIED_ON_DEV", "FILTER_FROZEN_FOR_VALIDATION"):
        assert label in VOL_FILTER_H4_DECISION["meaning"]
    # the filter must be refused by the rule when it does not earn its place
    assert "FILTER_NOT_JUSTIFIED_ON_DEV" in VOL_FILTER_H4_DECISION["rule"]


def test_the_mechanism_experiments_do_not_move_the_frozen_candidate() -> None:
    assert "min_atr_pct" not in FROZEN_PARAMS["edge_trend_01"]
    assert PARAMS_HASH.startswith(FROZEN_PARAMS_HASH_PREFIX)
    # the gate is an override, so the frozen rulesets stay the frozen rulesets
    candidate = TrendFollow("4h", {**FROZEN_PARAMS["edge_trend_01"], "min_atr_pct": 1.0})
    assert candidate.params["min_atr_pct"] == 1.0
    assert build_candidates()["edge_trend_01_4h"].params == FROZEN_PARAMS["edge_trend_01"]


# --------------------------------------------------------------------------- #
# The buckets: the declared edges, half-open on the upper edge
# --------------------------------------------------------------------------- #


def test_bucket_labels_come_from_the_edges() -> None:
    assert _bucket_labels([0.25, 0.5, 1.0]) == ["<0.25", "0.25-0.5", "0.5-1", ">=1"]


@pytest.mark.parametrize(
    ("distance", "expected"),
    (
        (-0.4, "<0.25"),
        (0.0, "<0.25"),
        (0.2499, "<0.25"),
        (0.25, "0.25-0.5"),
        (0.4999, "0.25-0.5"),
        (0.5, "0.5-1"),
        (1.0, ">=1"),
        (9.0, ">=1"),
    ),
)
def test_a_fill_lands_in_the_bucket_its_distance_is_in(distance: float, expected: str) -> None:
    assert _distance_bucket([0.25, 0.5, 1.0], distance) == expected


def test_every_fill_lands_in_exactly_one_bucket() -> None:
    edges = [float(edge) for edge in ENTRY_TIMING_H2["bucket_edges_atr"]]
    labels = _bucket_labels(edges)
    for distance in (-1.0, 0.0, 0.1, 0.25, 0.3, 0.5, 0.75, 1.0, 4.0):
        hits = [label for label in labels if _distance_bucket(edges, distance) == label]
        assert len(hits) == 1


# --------------------------------------------------------------------------- #
# The grid: nearest rank on the published sample, nothing else
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("values", "pct", "expected"),
    (
        ([1.0, 2.0, 3.0, 4.0], 25.0, 1.0),
        ([1.0, 2.0, 3.0, 4.0], 50.0, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 75.0, 3.0),
        ([1.0, 2.0, 3.0, 4.0], 100.0, 4.0),
        ([1.0, 2.0, 3.0], 50.0, 2.0),
        ([7.0], 25.0, 7.0),
    ),
)
def test_nearest_rank_is_the_declared_percentile(
    values: list[float], pct: float, expected: float
) -> None:
    assert _nearest_rank_percentile(values, pct) == expected


def test_the_grid_is_the_percentile_of_the_sample_it_was_read_from() -> None:
    sample = [float(i) for i in range(1, 101)]
    grid = vol_filter_grid(sample)
    assert grid["values_pct"] == {"p25": 25.0, "p50": 50.0, "p75": 75.0}
    assert grid["sample"]["bars_with_atr"] == 100
    assert grid["sample"]["min_atr_pct"] == 1.0
    assert grid["sample"]["max_atr_pct"] == 100.0
    assert grid["sample"]["median_atr_pct"] == _median(sample)


def test_the_atr_sample_reads_only_the_window_it_was_given() -> None:
    bars = [_bar(_DEV_START - 30 * _STEP + i * _STEP, o=1.0, h=1.0, low=1.0, c=100.0 + i) for i in range(40)]
    corpus = {"BTC": bars, "ETH": bars, "SOL": bars}
    inside = _atr_pct_sample(corpus, _DEV_START, _DEV_START + 5 * _STEP, 14)
    everything = _atr_pct_sample(corpus, _DEV_START - 60 * _STEP, _DEV_START + 60 * _STEP, 14)
    assert 0 < len(inside) < len(everything)
    # the first bars have no ATR yet: they are skipped, not counted as zero
    defined = sum(1 for index in range(len(bars)) if atr(bars, index, 14) is not None)
    assert 0 < defined < len(bars)
    assert len(everything) == 3 * defined
    assert all(value > 0 for value in everything)


def test_the_atr_sample_refuses_a_corpus_that_does_not_cover_the_assets() -> None:
    bars = [_bar(_DEV_START + i * _STEP, o=1.0, h=1.0, low=1.0, c=100.0) for i in range(40)]
    with pytest.raises(KeyError):
        _atr_pct_sample({"BTC": bars}, _DEV_START, _DEV_END, 14)


# --------------------------------------------------------------------------- #
# The gates: the frozen candidate plus one field, and nothing else
# --------------------------------------------------------------------------- #


def test_params_delta_names_exactly_the_added_field() -> None:
    base = dict(FROZEN_PARAMS["edge_trend_01"])
    arm = {**base, "min_atr_pct": 1.5}
    assert _params_delta(base, arm) == {"added": ["min_atr_pct"], "removed": [], "changed": []}
    assert _params_delta(base, dict(base)) == {"added": [], "removed": [], "changed": []}
    retuned = {**base, "trailing_atr": 2.0}
    assert _params_delta(base, retuned)["changed"] == ["trailing_atr"]


def test_the_volatility_gate_only_refuses_bars_below_its_own_threshold() -> None:
    bars = _breakout_series(_DEV_START, cycles=60, ups=[1.03], down=0.99)
    plane = cost_plane(size_usd=1000.0, horizon_minutes=1440.0)
    candidate = TrendFollow("4h", {**FROZEN_PARAMS["edge_trend_01"], "min_atr_pct": 5.0})
    refusals = []
    for index in range(len(bars)):
        outcome = candidate.on_bar(bars, index, None, plane)
        if outcome is not None and getattr(outcome, "reason", None) == "volatility_filter_fail":
            refusals.append(outcome)
    assert refusals, "the gate never fired: the fixture is not exercising it"
    for refusal in refusals:
        assert refusal.detail["atr_pct"] < refusal.detail["min_atr_pct"] == 5.0
    # an inert threshold cannot refuse anything the unfiltered candidate would take
    open_candidate = TrendFollow("4h", {**FROZEN_PARAMS["edge_trend_01"], "min_atr_pct": 0.0})
    assert not [
        index
        for index in range(len(bars))
        if getattr(open_candidate.on_bar(bars, index, None, plane), "reason", "") == "volatility_filter_fail"
    ]


# --------------------------------------------------------------------------- #
# The verdicts: the pre-registered rules, and nothing else
# --------------------------------------------------------------------------- #


def _h2_buckets(near: int, near_net: float, far: int, far_net: float) -> dict[str, Any]:
    labels = _bucket_labels([float(edge) for edge in ENTRY_TIMING_H2["bucket_edges_atr"]])

    def entry(count: int, net: float) -> dict[str, Any]:
        return {
            "trades": count,
            "net_usdt": round(net, 4),
            "gross_usdt": round(net, 4),
            "fees_usdt": 0.0,
            "price_costs_usdt": 0.0,
            "cost_usdt": 0.0,
            "expectancy_usdt": round(net / count, 4) if count else None,
            "win_rate_pct": None,
            "median_distance_atr": 0.1,
            "median_mfe_bps": None,
            "median_mae_bps": None,
            "median_duration_min": None,
            "by_market_context": {},
        }

    buckets: dict[str, Any] = {}
    buckets[labels[0]] = entry(near, near_net)
    for index, label in enumerate(labels[1:]):
        buckets[label] = entry(far if index == 0 else 0, far_net if index == 0 else 0.0)
    return buckets


@pytest.mark.parametrize(
    ("near", "near_net", "far", "far_net", "expected"),
    (
        # most fills are far, and the fills near the level pay better: late entry
        (54, -58.0, 236, -437.0, "ENTRY_IS_LATE"),
        # the fills near the level are the worse ones: lateness is not the cause
        (80, -900.0, 210, -400.0, "ENTRY_NOT_THE_PROBLEM"),
        # the near side carries the majority: the rule does not read it as late
        (200, -100.0, 90, -300.0, "ENTRY_NOT_THE_PROBLEM"),
        # under the sample floor on one side: nothing is claimed
        (10, -5.0, 280, -500.0, "INCONCLUSIVE"),
        (54, -58.0, 12, -40.0, "INCONCLUSIVE"),
    ),
)
def test_h2_verdict_is_the_frozen_rule(
    near: int, near_net: float, far: int, far_net: float, expected: str
) -> None:
    verdict = entry_timing_verdict([], _h2_buckets(near, near_net, far, far_net))
    assert verdict["verdict"] == expected
    assert verdict["reason"]
    assert verdict["near"]["trades"] == near
    assert verdict["far"]["trades"] == far
    assert verdict["rule"]["min_trades_per_side"] == ENTRY_TIMING_H2_DECISION["min_trades_per_side"]
    assert set(verdict["meaning"]) == {"INCONCLUSIVE", "ENTRY_IS_LATE", "ENTRY_NOT_THE_PROBLEM"}


def _arm(
    name: str,
    *,
    trades: int,
    net: float,
    threshold: float | None,
    share: float | None = None,
) -> dict[str, Any]:
    return {
        "role": name,
        "min_atr_pct": threshold,
        "trades": trades,
        "net_usdt": net,
        "largest_trade_share_of_net": share,
        "params": {**FROZEN_PARAMS["edge_trend_01"], **({"min_atr_pct": threshold} if threshold is not None else {})},
    }


def _h4_arms(*, baseline: dict[str, Any], **thresholds: dict[str, Any]) -> dict[str, Any]:
    return {"baseline": baseline, "p25": thresholds["p25"], "p50": thresholds["p50"], "p75": thresholds["p75"]}


def test_h4_verdict_refuses_a_filter_that_does_not_beat_the_baseline() -> None:
    arms = _h4_arms(
        baseline=_arm("baseline", trades=223, net=1921.18, threshold=None, share=0.07),
        p25=_arm("p25", trades=188, net=1595.54, threshold=1.55),
        p50=_arm("p50", trades=131, net=993.67, threshold=2.24),
        p75=_arm("p75", trades=58, net=499.98, threshold=3.33),
    )
    verdict = vol_filter_verdict(arms, {"values_pct": {"p25": 1.55, "p50": 2.24, "p75": 3.33}})
    assert verdict["verdict"] == "FILTER_NOT_JUSTIFIED_ON_DEV"
    assert verdict["frozen_threshold_pct"] is None
    assert verdict["ranking"] == ["baseline", "p25", "p50", "p75"]
    assert verdict["val_oos_read"] is False


def test_h4_verdict_freezes_a_threshold_that_earns_its_place() -> None:
    arms = _h4_arms(
        baseline=_arm("baseline", trades=223, net=1000.0, threshold=None, share=0.07),
        p25=_arm("p25", trades=200, net=1300.0, threshold=1.55, share=0.1),
        p50=_arm("p50", trades=140, net=900.0, threshold=2.24, share=0.1),
        p75=_arm("p75", trades=60, net=400.0, threshold=3.33, share=0.1),
    )
    verdict = vol_filter_verdict(arms, {"values_pct": {"p25": 1.55, "p50": 2.24, "p75": 3.33}})
    assert verdict["verdict"] == "FILTER_FROZEN_FOR_VALIDATION"
    assert verdict["frozen_threshold_pct"] == 1.55
    assert verdict["improvement_usdt"] == pytest.approx(300.0)
    assert verdict["winner"] == "p25"
    # frozen is not promoted: the next step is a NEW pre-registered run
    assert verdict["val_oos_read"] is False
    assert "VAL" in verdict["next_step"] and "OOS" in verdict["next_step"]


@pytest.mark.parametrize(
    ("arms", "expected"),
    (
        (
            # the winner's net sits in one trade: not evidence, a single trade
            _h4_arms(
                baseline=_arm("baseline", trades=223, net=1000.0, threshold=None),
                p25=_arm("p25", trades=200, net=1300.0, threshold=1.55, share=0.8),
                p50=_arm("p50", trades=140, net=900.0, threshold=2.24),
                p75=_arm("p75", trades=60, net=400.0, threshold=3.33),
            ),
            "FILTER_NOT_JUSTIFIED_ON_DEV",
        ),
        (
            # the "winner" only wins because everything else is worse than zero
            _h4_arms(
                baseline=_arm("baseline", trades=223, net=-100.0, threshold=None),
                p25=_arm("p25", trades=200, net=-50.0, threshold=1.55),
                p50=_arm("p50", trades=140, net=-900.0, threshold=2.24),
                p75=_arm("p75", trades=60, net=-400.0, threshold=3.33),
            ),
            "FILTER_NOT_JUSTIFIED_ON_DEV",
        ),
        (
            # the only arm that clears the floor is the baseline: the filter is out
            _h4_arms(
                baseline=_arm("baseline", trades=223, net=1000.0, threshold=None),
                p25=_arm("p25", trades=12, net=5000.0, threshold=1.55),
                p50=_arm("p50", trades=4, net=3000.0, threshold=2.24),
                p75=_arm("p75", trades=1, net=800.0, threshold=3.33),
            ),
            "FILTER_NOT_JUSTIFIED_ON_DEV",
        ),
        (
            # the baseline cannot even be read on DEV: nothing is claimed
            _h4_arms(
                baseline=_arm("baseline", trades=11, net=100.0, threshold=None),
                p25=_arm("p25", trades=9, net=90.0, threshold=1.55),
                p50=_arm("p50", trades=4, net=40.0, threshold=2.24),
                p75=_arm("p75", trades=1, net=8.0, threshold=3.33),
            ),
            "INCONCLUSIVE",
        ),
    ),
)
def test_h4_verdict_cannot_freeze_the_filter_without_evidence(
    arms: dict[str, Any], expected: str
) -> None:
    verdict = vol_filter_verdict(arms, {"values_pct": {"p25": 1.55, "p50": 2.24, "p75": 3.33}})
    assert verdict["verdict"] == expected
    if expected != "FILTER_FROZEN_FOR_VALIDATION":
        assert verdict["frozen_threshold_pct"] is None


# --------------------------------------------------------------------------- #
# The artefacts, and the verifier that judges them
# --------------------------------------------------------------------------- #


def _h2_payload() -> dict[str, Any]:
    start, end = _DEV_START, _DEV_END
    bars = _breakout_series(start, cycles=90, ups=[1.002, 1.004, 1.007], down=0.998)
    context = _downtrend_context(start)
    policy = load_risk_policy()
    plane = cost_plane(size_usd=1000.0, horizon_minutes=240.0)
    regime_rows, regime_meta = _benchmark_rows()
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
    edges = [float(edge) for edge in ENTRY_TIMING_H2["bucket_edges_atr"]]
    rows, unmatched = _join_signal_fills(run.trades, run.signals, edges)
    buckets = _bucket_stats(rows, edges)
    assert rows, "the fixture must trade: a payload with no fills tests nothing"
    assert sum(1 for label in buckets if buckets[label]["trades"]) > 1, (
        "the fixture must fill more than one distance bucket"
    )
    metrics = _metrics(
        trades=run.trades,
        equity_curve=run.equity_curve,
        start_equity=policy.start_equity,
        window_minutes=(end - start) / 60_000.0,
        timeframe="15m",
        n_assets=3,
    )
    arm = {
        "role": "diagnostic",
        "candidate_id": "edge_intra_01",
        "params": dict(candidate.params),
        "bars_evaluated": candidate.bars_evaluated,
        "warmup_bars": candidate.warmup_bars,
        "signal_count": len(run.signals),
        "joined_trades": len(rows),
        "unmatched_trades": len(unmatched),
        "refusals": _funnel(run.refusals),
        "_trade_rows": run.trades,
        "_refusal_rows": run.refusals,
        "_signal_rows": run.signals,
        "_joined_rows": rows,
        **metrics,
    }
    return {
        "run_id": "wp-edge-01-entry-timing-h2",
        "generated_at_utc": "2024-10-02T00:00:00+00:00",
        "git": {"head_commit": "0" * 40, "branch": "test", "worktree_dirty": False},
        "source_digest": {"combined_sha256": "a" * 64, "files": {}},
        "mode": "deterministic backtest over the local historical corpus, DEV window only",
        "entrypoint": "scripts/edge01_mechanism_ablation.py",
        "verifier": "scripts/edge01_mechanism_ablation_verify.py",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **ENTRY_TIMING_H2,
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "window_days": (end - start) / 86_400_000.0,
            "assets": ["BTC", "ETH", "SOL"],
            "plane": plane.to_dict(),
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": "c" * 64,
            "decision_rule": ENTRY_TIMING_H2_DECISION,
            "corpus_provenance": {},
        },
        "verdict": entry_timing_verdict(rows, buckets),
        "arms": {"diagnostic": arm},
        "buckets": buckets,
        "unmatched_trades": unmatched,
        "market_context": {"meta": regime_meta, "rows": [row.to_row() for row in regime_rows]},
        "limitations": ["synthetic fixture: DEV only, long side only"],
    }


def _funnel(refusals: list[dict[str, Any]]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for refusal in refusals:
        key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
        mix[key] = mix.get(key, 0) + 1
    return mix


def _h4_payload() -> dict[str, Any]:
    start, end = int(datetime(2019, 1, 1, tzinfo=UTC).timestamp() * 1000), int(
        datetime(2023, 12, 31, tzinfo=UTC).timestamp() * 1000
    )
    bars = _breakout_series(start, cycles=300, ups=[1.0008, 1.0018], down=0.9985)
    context = _downtrend_context(start, warmup_hours=400, span_hours=400)
    policy = load_risk_policy()
    plane = cost_plane(size_usd=1000.0, horizon_minutes=1440.0)
    regime_rows, regime_meta = _benchmark_rows()
    base_params = dict(FROZEN_PARAMS["edge_trend_01"])
    sample = _atr_pct_sample(
        {"BTC": bars, "ETH": bars, "SOL": bars}, start, end, int(base_params["atr_period"])
    )
    grid = vol_filter_grid(sample)
    arms: dict[str, Any] = {}
    for name, threshold in [("baseline", None), *grid["values_pct"].items()]:
        params = dict(base_params) if threshold is None else {**base_params, "min_atr_pct": float(threshold)}
        candidate = TrendFollow("4h", params)
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
        funnel = _funnel(run.refusals)
        metrics = _metrics(
            trades=run.trades,
            equity_curve=run.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=(end - start) / 60_000.0,
            timeframe="4h",
            n_assets=3,
        )
        held = sum(
            1
            for signal in run.signals
            if float((signal.get("evidence") or {}).get("atr_pct") or 0.0)
            < (float(threshold) if threshold is not None else 0.0)
        )
        arms[name] = {
            "role": name,
            "candidate_id": str(candidate.id),
            "min_atr_pct": None if threshold is None else float(threshold),
            "params": dict(candidate.params),
            "params_delta": _params_delta(base_params, dict(candidate.params)),
            "bars_evaluated": candidate.bars_evaluated,
            "warmup_bars": candidate.warmup_bars,
            "signal_count": len(run.signals),
            "vol_refusals": int(funnel.get("candidate:volatility_filter_fail", 0)),
            "signals_below_threshold": held,
            "refusals": funnel,
            "_trade_rows": run.trades,
            "_refusal_rows": run.refusals,
            "_signal_rows": run.signals,
            **metrics,
        }
        arms[name]["gross_per_trade_usdt"] = (
            round(metrics["gross_usdt"] / len(run.trades), 4) if run.trades else None
        )
    assert arms["baseline"]["trades"], "the fixture must trade: an empty book tests nothing"
    assert arms["p75"]["vol_refusals"], (
        "the fixture must make the gate fire: the grid is centred on its own sample"
    )
    return {
        "run_id": "wp-edge-01-volatility-filter-h4",
        "generated_at_utc": "2019-07-02T00:00:00+00:00",
        "git": {"head_commit": "0" * 40, "branch": "test", "worktree_dirty": False},
        "source_digest": {"combined_sha256": "a" * 64, "files": {}},
        "mode": "deterministic backtest over the local historical corpus, DEV window only",
        "entrypoint": "scripts/edge01_mechanism_ablation.py",
        "verifier": "scripts/edge01_mechanism_ablation_verify.py",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **VOL_FILTER_H4,
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "window_days": (end - start) / 86_400_000.0,
            "assets": ["BTC", "ETH", "SOL"],
            "frozen_params_baseline": base_params,
            "plane": plane.to_dict(),
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": "c" * 64,
            "decision_rule": VOL_FILTER_H4_DECISION,
            "corpus_provenance": {},
        },
        "verdict": vol_filter_verdict(arms, grid),
        "arms": arms,
        "grid": grid,
        "_atr_sample": sample,
        "market_context": {"meta": regime_meta, "rows": [row.to_row() for row in regime_rows]},
        "limitations": ["synthetic fixture: DEV only, long side only"],
    }


def test_write_entry_timing_artifacts_publishes_seven_files_with_digests(tmp_path: Path) -> None:
    written = write_entry_timing_artifacts(_h2_payload(), tmp_path)
    assert sorted(written) == [
        "ENTRY_TIMING.json",
        "ENTRY_TIMING.md",
        "ENTRY_TIMING_LEVELS.csv",
        "ENTRY_TIMING_REFUSALS.csv",
        "ENTRY_TIMING_SIGNALS.csv",
        "ENTRY_TIMING_TRADES.csv",
        "MARKET_CONTEXT.csv",
    ]
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0
    body = json.loads(written["ENTRY_TIMING.json"].read_text(encoding="utf-8"))
    for name, entry in body["artifacts"].items():
        assert entry["bytes"] == written[name].stat().st_size
    assert "ENTRY_TIMING.json" not in body["artifacts"]
    text = written["ENTRY_TIMING.json"].read_text(encoding="utf-8")
    assert "_joined_rows" not in text and "_trade_rows" not in text
    markdown = written["ENTRY_TIMING.md"].read_text(encoding="utf-8")
    assert "H2 (timing de entrada)" in markdown
    assert "Limites" in markdown
    assert "near" in markdown and "far" in markdown


def test_write_vol_filter_artifacts_publishes_seven_files_with_digests(tmp_path: Path) -> None:
    written = write_vol_filter_artifacts(_h4_payload(), tmp_path)
    assert sorted(written) == [
        "MARKET_CONTEXT.csv",
        "VOL_FILTER.json",
        "VOL_FILTER.md",
        "VOL_FILTER_ATR.csv",
        "VOL_FILTER_REFUSALS.csv",
        "VOL_FILTER_SIGNALS.csv",
        "VOL_FILTER_TRADES.csv",
    ]
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0
    body = json.loads(written["VOL_FILTER.json"].read_text(encoding="utf-8"))
    for name, entry in body["artifacts"].items():
        assert entry["bytes"] == written[name].stat().st_size
    assert "VOL_FILTER.json" not in body["artifacts"]
    markdown = written["VOL_FILTER.md"].read_text(encoding="utf-8")
    assert "H4 (filtro de volatilidad de entrada)" in markdown
    assert "VAL/OOS leidos: **False**" in markdown


@pytest.mark.parametrize("experiment", ["h2", "h4"])
def test_the_independent_verifier_accepts_the_run_it_would_judge(
    tmp_path: Path, verifier: Any, experiment: str
) -> None:
    payload = _h2_payload() if experiment == "h2" else _h4_payload()
    writer = write_entry_timing_artifacts if experiment == "h2" else write_vol_filter_artifacts
    writer(payload, tmp_path)
    checks = verifier.run_checks(tmp_path, verifier.SPECS[experiment])
    failures = [entry for entry in checks if not entry["ok"]]
    assert not failures, failures
    expected = {
        "ARTIFACTS_PRESENT",
        "WINDOW_IS_PREREGISTERED_DEV",
        "TRADE_SIGNAL_JOIN",
        "GROSS_BEFORE_COSTS_RECOMPUTED",
        "COST_SPLIT_IDENTITY",
        "FUNNEL_ARITHMETIC",
        "ARM_METRICS_RECOMPUTED",
        "MARKET_CONTEXT_ATTRIBUTION",
        "DECISION_RULE_FROZEN",
        "VERDICT_RECOMPUTED",
    } | (
        {"BUCKET_ARITHMETIC", "LEVEL_JOIN_RECOMPUTED", "FILL_IS_AFTER_THE_SIGNAL"}
        if experiment == "h2"
        else {"GRID_IS_DATASET_DERIVED", "ARMS_ONE_FIELD_APART", "GATE_SOUNDNESS", "SELECTION_MATCHES_THE_RUN"}
    )
    assert {entry["check"] for entry in checks} == expected


@pytest.mark.parametrize("experiment", ["h2", "h4"])
def test_the_independent_verifier_breaks_on_every_mutation(
    tmp_path: Path, verifier: Any, experiment: str
) -> None:
    payload = _h2_payload() if experiment == "h2" else _h4_payload()
    writer = write_entry_timing_artifacts if experiment == "h2" else write_vol_filter_artifacts
    writer(payload, tmp_path)
    report = verifier.self_test(tmp_path, verifier.SPECS[experiment])
    undetected = [m for m in report["mutations"] if not m["expected_check_failed"]]
    assert not undetected, undetected
    assert report["baseline_all_green"]
    assert len(report["mutations"]) >= 15


@pytest.mark.parametrize("experiment", ["h2", "h4"])
def test_the_verifier_refuses_a_directory_missing_an_artefact(
    tmp_path: Path, verifier: Any, experiment: str
) -> None:
    payload = _h2_payload() if experiment == "h2" else _h4_payload()
    writer = write_entry_timing_artifacts if experiment == "h2" else write_vol_filter_artifacts
    written = writer(payload, tmp_path)
    victim = "ENTRY_TIMING_LEVELS.csv" if experiment == "h2" else "VOL_FILTER_ATR.csv"
    assert written[victim].exists()
    written[victim].unlink()
    with pytest.raises(verifier.Fatal):
        verifier.run_checks(tmp_path, verifier.SPECS[experiment])
