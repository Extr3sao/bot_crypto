"""ARC-01 primary discovery -- unit / contract / PIT / accounting / exactly-once tests.

All tests run on synthetic fixtures; none of them reads the certified authorities or
computes a real economic result. They exist to freeze the implementation *before* the
single authorized economic execution.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
from pathlib import Path

import pytest

from trading_bot.backtesting import stat_validation as sv
from trading_bot.research.arc01 import arc01_discovery as disc
from trading_bot.research.arc01 import arc01_synthetic as syn
from trading_bot.research.arc01 import prereg_reference as ref
from trading_bot.research.arc01.arc01_authority import FundingSeries, Series

HOUR = disc.HOUR_MS
DAY = 86_400_000
BASE = syn.SYNTHETIC_BASE_MS


# --------------------------------------------------------------------------- helpers
def _funding(asset: str, obs: list[tuple[int, float]], interval: int = 8) -> FundingSeries:
    obs = sorted(obs, key=lambda x: x[0])
    return FundingSeries(
        asset,
        tuple(int(t) for t, _ in obs),
        tuple(float(r) for _, r in obs),
        tuple(interval for _ in obs),
        "synthetic",
        "synthetic://funding",
        len(obs),
    )


def _price(asset: str, t0: int, t1: int, base: float = 100.0, step: float = 0.25) -> Series:
    ts: list[int] = []
    vals: list[float] = []
    t = t0
    i = 0
    while t <= t1:
        ts.append(t)
        vals.append(base * (1.0 + step * math.sin(i * 0.11)))
        t += HOUR
        i += 1
    return Series(asset, tuple(ts), tuple(vals), "synthetic", "synthetic://price", len(ts))


def _oi(asset: str, t0: int, t1: int, growth_per_day: float = 0.02) -> Series:
    ts: list[int] = []
    vals: list[float] = []
    t = t0
    while t <= t1:
        day = (t - t0) / DAY
        ts.append(t)
        vals.append(50_000.0 * (1.0 + growth_per_day * day))
        t += 300_000
    return Series(asset, tuple(ts), tuple(vals), "synthetic", "synthetic://oi", len(ts))


def _randomized_case(rnd: random.Random) -> tuple[int, FundingSeries, Series, Series, int, int]:
    T = 1_700_000_000_000 + rnd.randrange(0, 900_000_000_000)
    n = rnd.choice([1, 30, 89, 90, 91, 150, 250])
    obs = [(T - rnd.randrange(0, 70 * DAY), round(rnd.uniform(-0.01, 0.01), 8)) for _ in range(n)]
    obs.append((T, round(rnd.uniform(-0.05, 0.05), 8)))
    fs = _funding("BTCUSDT", obs)
    start = T - 400 * HOUR
    end = T + 400 * HOUR
    price = _price("BTCUSDT", start, end)
    oi = _oi("BTCUSDT", start - DAY, end, growth_per_day=rnd.choice([0.02, -0.01, 0.0]))
    return T, fs, oi, price, start, end


# ------------------------------------------------------- parity with the verified ref
def test_engine_matches_verified_prereg_reference_on_randomized_fixtures() -> None:
    rnd = random.Random(20260915)
    checked = 0
    for _ in range(400):
        T, fs, oi, price, start, end = _randomized_case(rnd)
        position_open = rnd.random() < 0.25
        mine = disc.decide_at(
            asset="BTCUSDT",
            decision_time_ms=T,
            funding=fs,
            oi=oi,
            price=price,
            position_open=position_open,
            window_start_ms=start,
            window_end_ms=end,
        )
        idx = price.first_index_strictly_after(T)
        entry_time = price.t[idx] if idx is not None else None
        exit_time = entry_time + disc.HOLDING_MS if entry_time is not None else None
        theirs = ref.evaluate_decision(
            decision_time_ms=T,
            funding_observations=list(zip(fs.t, fs.rate)),
            oi_now=oi.last_at_or_before(T),
            oi_ref=oi.last_at_or_before(T - disc.OI_LOOKBACK_MS),
            position_open=position_open,
            exit_bar_open_time_ms=exit_time,
            entry_bar_open_time_ms=entry_time,
            common_window_start_ms=start,
            common_window_end_ms=end,
        )
        assert mine.result == theirs["result"], (T, mine.result, theirs["result"])
        assert mine.reason == theirs["reason"], (T, mine.reason, theirs["reason"])
        assert mine.emitted == theirs["emitted"]
        assert mine.z_funding == theirs["z_funding"]
        checked += 1
    assert checked == 400


def test_pre_sliced_funding_window_is_equivalent_to_full_scan() -> None:
    rnd = random.Random(7)
    for _ in range(50):
        obs = [(BASE - rnd.randrange(0, 200 * DAY), round(rnd.uniform(-0.01, 0.01), 8)) for _ in range(300)]
        obs.append((BASE, 0.004))
        fs = _funding("BTCUSDT", obs)
        T = BASE
        full = ref.funding_extreme(list(zip(fs.t, fs.rate)), T)
        sliced = ref.funding_extreme(fs.window_slice(T - disc.FUNDING_LOOKBACK_MS, T), T)
        assert full == sliced


# ------------------------------------------------------------------- boundary rules
def test_bisect_window_slice_matches_naive_filter() -> None:
    rnd = random.Random(99)
    for _ in range(40):
        n = rnd.choice([0, 1, 5, 200, 1000])
        obs = [(BASE + rnd.randrange(-10**11, 10**11), round(rnd.uniform(-0.01, 0.01), 8)) for _ in range(n)]
        fs = _funding("BTCUSDT", obs)
        lo = BASE - rnd.randrange(0, 10**11)
        hi = BASE + rnd.randrange(0, 10**11)
        naive = [(ts, r) for ts, r in zip(fs.t, fs.rate) if lo <= ts <= hi]
        assert fs.window_slice(lo, hi) == naive
        naive_settle = [r for ts, r in zip(fs.t, fs.rate) if lo < ts <= hi]
        assert fs.settlements_between(lo, hi) == naive_settle


def test_inclusive_threshold_boundaries() -> None:
    assert ref.decide_direction(2.0) == ref.SHORT
    assert ref.decide_direction(-2.0) == ref.LONG
    assert ref.decide_direction(1.9999999999) is None
    assert ref.decide_direction(-1.9999999999) is None
    assert ref.decide_direction(None) is None
    assert ref.decide_direction(1e9) == ref.SHORT
    assert ref.decide_direction(-1e9) == ref.LONG


def test_synthetic_spikes_produce_contrarian_directions() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    trades, funnel = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    assert trades, "synthetic fixture must produce trades"
    for t in trades:
        if t.direction == ref.SHORT:
            assert t.funding_z >= disc.FUNDING_Z_POSITIVE_THRESHOLD
        else:
            assert t.funding_z <= disc.FUNDING_Z_NEGATIVE_THRESHOLD
        assert t.oi_change_24h > 0.0


def test_mad_zero_falls_back_to_sample_stdev_and_degenerate_fails_closed() -> None:
    obs = [(BASE - i * 8 * HOUR, 0.0001) for i in range(90, -1, -1)]
    fs = _funding("BTCUSDT", obs)
    res = ref.funding_extreme(fs.window_slice(BASE - disc.FUNDING_LOOKBACK_MS, BASE), BASE)
    assert res["mad_fallback_used"] is True
    assert res["status"] == "SCALE_NONPOSITIVE"
    assert res["scale"] == 0.0

    obs2 = [(BASE - i * 8 * HOUR, 0.0001 if i % 2 else -0.0001) for i in range(90, -1, -1)]
    fs2 = _funding("BTCUSDT", obs2)
    res2 = ref.funding_extreme(fs2.window_slice(BASE - disc.FUNDING_LOOKBACK_MS, BASE), BASE)
    assert res2["status"] == "OK"
    assert res2["scale"] > 0.0


def test_insufficient_funding_history_precedence() -> None:
    obs = [(BASE - i * 8 * HOUR, 0.001) for i in range(89, -1, -1)]  # 90 obs, min is 90 -> OK
    fs = _funding("BTCUSDT", obs)
    res = ref.funding_extreme(fs.window_slice(BASE - disc.FUNDING_LOOKBACK_MS, BASE), BASE)
    assert res["observations"] == 90 and res["status"] != "INSUFFICIENT_FUNDING_HISTORY"
    obs_short = obs[1:]
    fs2 = _funding("BTCUSDT", obs_short)
    res2 = ref.funding_extreme(fs2.window_slice(BASE - disc.FUNDING_LOOKBACK_MS, BASE), BASE)
    assert res2["status"] == "INSUFFICIENT_FUNDING_HISTORY"


# ------------------------------------------------------------------------- PIT tests
def test_entry_is_first_bar_strictly_after_decision_including_hour_aligned() -> None:
    T = BASE  # exactly on an hour boundary
    price = _price("BTCUSDT", T - 10 * HOUR, T + 200 * HOUR)
    fs = _funding("BTCUSDT", [(T - i * 8 * HOUR, 0.0001 + 0.00001 * (i % 7)) for i in range(200, -1, -1)] + [(T, 0.01)])
    oi = _oi("BTCUSDT", T - 30 * HOUR, T + 200 * HOUR)
    d = disc.decide_at(asset="BTCUSDT", decision_time_ms=T, funding=fs, oi=oi, price=price, position_open=False, window_start_ms=T - 100 * HOUR, window_end_ms=T + 190 * HOUR)
    assert d.entry_time_ms == T + HOUR, "same-bar entry is forbidden on hour-aligned settlements"
    assert d.entry_time_ms > d.decision_time_ms

    T_jitter = BASE + 4  # provider millisecond jitter, as in the certified authority
    fs_j = _funding("BTCUSDT", [(T_jitter - i * 8 * HOUR, 0.0001 + 0.00001 * (i % 7)) for i in range(200, -1, -1)] + [(T_jitter, 0.01)])
    d_j = disc.decide_at(asset="BTCUSDT", decision_time_ms=T_jitter, funding=fs_j, oi=oi, price=price, position_open=False, window_start_ms=T - 100 * HOUR, window_end_ms=T + 190 * HOUR)
    assert d_j.entry_time_ms == T + HOUR


def test_exit_is_exactly_entry_plus_72h_and_forward_guard_censors_tail() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    trades, funnel = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    for t in trades:
        assert t.exit_time_ms == t.entry_time_ms + 72 * HOUR
        assert t.exit_time_ms <= end
        assert t.oi_staleness_now_ms <= disc.OI_MAX_STALENESS_MS
        assert t.oi_staleness_reference_ms <= disc.OI_MAX_STALENESS_MS
    assert funnel["forward_price_unavailable"] > 0, "the frozen forward-data guard must censor the window tail"
    assert all(t.entry_time_ms >= start for t in trades)


def test_future_mutation_after_t_never_changes_a_decision() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    trades, _ = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    assert trades
    fs = funding["BTCUSDT"]
    os_ = oi["BTCUSDT"]
    for t in trades[:20]:
        T = t.decision_time_ms
        mutated_f = FundingSeries(fs.asset, fs.t, tuple(r * 3 if ts > T else r for ts, r in zip(fs.t, fs.rate)), fs.interval_hours, fs.sha256, fs.source_path, fs.rows)
        mutated_o = Series(os_.asset, os_.t, tuple(v * 5 if ts > T else v for ts, v in zip(os_.t, os_.v)), os_.sha256, os_.path, os_.rows)
        a = disc.decide_at(asset="BTCUSDT", decision_time_ms=T, funding=fs, oi=os_, price=price["BTCUSDT"], position_open=False, window_start_ms=start, window_end_ms=end)
        b = disc.decide_at(asset="BTCUSDT", decision_time_ms=T, funding=mutated_f, oi=mutated_o, price=price["BTCUSDT"], position_open=False, window_start_ms=start, window_end_ms=end)
        assert (a.result, a.reason, a.z_funding, a.oi_change_24h) == (b.result, b.reason, b.z_funding, b.oi_change_24h)


def test_past_eligible_mutation_changes_the_feature_state() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    trades, _ = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    t = trades[5]
    T = t.decision_time_ms
    fs = funding["BTCUSDT"]
    # mutate an eligible funding observation strictly inside the trailing 60d window
    target = next(ts for ts in fs.t if T - disc.FUNDING_LOOKBACK_MS < ts < T)
    mutated = FundingSeries(
        fs.asset,
        fs.t,
        tuple(0.02 if ts == target else r for ts, r in zip(fs.t, fs.rate)),
        fs.interval_hours,
        fs.sha256,
        fs.source_path,
        fs.rows,
    )
    a = disc.decide_at(asset="BTCUSDT", decision_time_ms=T, funding=fs, oi=oi["BTCUSDT"], price=price["BTCUSDT"], position_open=False, window_start_ms=start, window_end_ms=end)
    b = disc.decide_at(asset="BTCUSDT", decision_time_ms=T, funding=mutated, oi=oi["BTCUSDT"], price=price["BTCUSDT"], position_open=False, window_start_ms=start, window_end_ms=end)
    assert a.z_funding != b.z_funding


# ------------------------------------------------------------------- accounting tests
def test_funding_cashflow_sign_semantics_match_binance_usdm() -> None:
    # positive funding: LONG pays, SHORT receives
    assert ref.funding_cashflow_return(1, [0.0001, 0.0002]) == pytest.approx(-0.0003)
    assert ref.funding_cashflow_return(-1, [0.0001, 0.0002]) == pytest.approx(0.0003)
    # negative funding: LONG receives, SHORT pays
    assert ref.funding_cashflow_return(1, [-0.0001]) == pytest.approx(0.0001)
    assert ref.funding_cashflow_return(-1, [-0.0001]) == pytest.approx(-0.0001)


def test_cashflow_window_is_strictly_after_entry_and_matches_certified_settlements() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    trades, _ = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    fs = funding["BTCUSDT"]
    assert trades
    for t in trades:
        settlements = [ts for ts in fs.t if t.entry_time_ms < ts <= t.exit_time_ms]
        assert len(settlements) == t.funding_settlements_applied
        # information window ends at decision_time < entry_time: no overlap, no double counting
        assert all(ts <= t.decision_time_ms for ts in fs.t if t.decision_time_ms - disc.FUNDING_LOOKBACK_MS <= ts <= t.decision_time_ms)
        assert t.funding_time_ms < t.entry_time_ms
    assert max(t.funding_settlements_applied for t in trades) <= 10  # 8h cadence over 72h


def test_net_decomposition_and_identical_cost_scenario_trade_set() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    trades, _ = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    assert trades
    for t in trades:
        for bps, attr in ((0, t.net_return_0bps), (10, t.net_return_10bps), (20, t.net_return_20bps), (40, t.net_return_40bps)):
            assert (t.gross_return + t.funding_cashflow - bps / 10_000.0) == attr
        assert t.net_return_ex_funding_10bps == t.gross_return - 0.0010
        assert t.net_return_10bps == t.net_return_ex_funding_10bps + t.funding_cashflow
    # the same list is evaluated at every scenario (no signal regeneration)
    for bps in disc.COST_SCENARIOS_BPS:
        assert len(disc.nets_at(trades, bps)) == len(trades)


# ---------------------------------------------------------------- statistical gates
def test_sharpe_replication_matches_project_statistical_authority() -> None:
    rnd = random.Random(11)
    for _ in range(30):
        xs = [rnd.uniform(-0.05, 0.06) for _ in range(rnd.choice([2, 5, 120, 733]))]
        assert disc.annualized_sharpe(xs) == pytest.approx(disc.replicate_annualized_sharpe(xs), rel=1e-12, abs=1e-12)
    n = 200
    xs = [0.001] * n
    assert disc.annualized_sharpe(xs) == 0.0  # zero variance fails closed


def test_rng_draw_sequence_and_percentile_index_match_stat_validation() -> None:
    rnd = random.Random(3)
    returns = tuple(rnd.gauss(0.001, 0.01) for _ in range(137))
    resamples, seed, confidence = 400, 20260915, 0.95
    # replicate sv.bootstrap_sharpe_ci using THIS module's draw pattern and index formula
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        sample = tuple(returns[rng.randrange(len(returns))] for _ in range(len(returns)))
        stats.append(sv._sharpe(sample, periods_per_year=365))
    stats.sort()
    alpha = (1.0 - confidence) / 2.0
    lower_idx = max(0, math.floor(alpha * len(stats)))
    upper_idx = min(len(stats) - 1, math.ceil((1.0 - alpha) * len(stats)) - 1)
    authoritative = sv.bootstrap_sharpe_ci(returns, resamples=resamples, confidence=confidence, seed=seed)
    assert stats[lower_idx] == authoritative.ci_lower
    assert stats[upper_idx] == authoritative.ci_upper

    # permutation draw pattern: one random() per element, < 0.5 flips the sign
    rng = random.Random(seed)
    observed = sv._sharpe(returns, periods_per_year=365)
    exceed = 0
    for _ in range(resamples):
        flipped = tuple(r * (1 if rng.random() < 0.5 else -1) for r in returns)
        if sv._sharpe(flipped, periods_per_year=365) >= observed:
            exceed += 1
    assert (exceed / resamples) == sv.permutation_significance(returns, permutations=resamples, seed=seed).p_value


def test_mean_bootstrap_and_permutation_are_seeded_and_deterministic() -> None:
    xs = [0.004, -0.002, 0.006, 0.001, -0.003, 0.005, 0.002, -0.001, 0.007, 0.003]
    a = disc.bootstrap_mean_ci(xs, resamples=500)
    b = disc.bootstrap_mean_ci(xs, resamples=500)
    assert a == b
    assert a["lower"] < a["upper"]
    p1 = disc.permutation_p_value(xs, draws=500)
    p2 = disc.permutation_p_value(xs, draws=500)
    assert p1 == p2
    assert 0.0 <= p1["p_value"] <= 1.0
    assert disc.bootstrap_mean_ci([0.001] * 10)["degenerate"] is True
    assert disc.permutation_p_value([0.001] * 10)["p_value"] == 1.0


def test_all_critical_gates_present_and_scored() -> None:
    funding, oi, price = syn.synthetic_authorities()
    start, end = syn.synthetic_window()
    trades = []
    for a in disc.ASSETS:
        tr, _ = disc.run_variant(variant="PRIMARY", funding=funding[a], oi=oi[a], price=price[a], start_ms=start, end_ms=end)
        trades.extend(tr)
    gates = disc.evaluate_gates(trades, window_start_ms=start, window_end_ms=end)
    for name in (
        "G1_SAMPLE",
        "G2_NET_EXPECTANCY",
        "G3_NET_EXPECTANCY_EX_FUNDING",
        "G4_PROFIT_FACTOR",
        "G5_SHARPE",
        "G6_BOOTSTRAP_CI",
        "G7_PERMUTATION",
        "G8_TEMPORAL_STABILITY",
        "G9_ASSET_STABILITY",
        "G10_CONCENTRATION",
        "G11_COST_SENSITIVITY",
    ):
        assert name in gates and isinstance(gates[name]["pass"], bool)
    assert gates["ALL_CRITICAL_GATES_PASS"] == (len(gates["failed_gates"]) == 0)
    # G10 fails closed when total net PnL is not positive
    flat = [t for t in trades[:1]]
    g = disc.evaluate_gates(flat, window_start_ms=start, window_end_ms=end)
    assert g["G10_CONCENTRATION"]["pass"] is False
    assert g["G1_SAMPLE"]["pass"] is False


def test_gate_evaluation_is_deterministic_under_repeated_calls() -> None:
    funding, oi, price = syn.synthetic_authorities()
    start, end = syn.synthetic_window()
    trades = []
    for a in disc.ASSETS:
        tr, _ = disc.run_variant(variant="PRIMARY", funding=funding[a], oi=oi[a], price=price[a], start_ms=start, end_ms=end)
        trades.extend(tr)
    g1 = disc.evaluate_gates(trades, window_start_ms=start, window_end_ms=end)
    g2 = disc.evaluate_gates(trades, window_start_ms=start, window_end_ms=end)
    assert json.dumps(g1, sort_keys=True, default=str) == json.dumps(g2, sort_keys=True, default=str)


def test_equal_count_vs_equal_duration_buckets_are_both_deterministic() -> None:
    funding, oi, price = syn.synthetic_authorities()
    start, end = syn.synthetic_window()
    trades = []
    for a in disc.ASSETS:
        tr, _ = disc.run_variant(variant="PRIMARY", funding=funding[a], oi=oi[a], price=price[a], start_ms=start, end_ms=end)
        trades.extend(tr)
    halves = disc.equal_count_buckets(trades, 2)
    assert sum(len(b) for b in halves) == len(trades)
    assert len(halves[0]) + len(halves[1]) == len(trades)
    quart = disc.equal_count_buckets(trades, 4)
    assert sum(len(b) for b in quart) == len(trades)
    dur = disc.equal_duration_buckets(trades, 4, start, end)
    assert sum(len(b) for b in dur) == len(trades)


# -------------------------------------------------------------------- policy tests
def test_no_overlapping_positions_and_reentry_only_after_exit() -> None:
    funding, oi, price = syn.synthetic_authorities()
    start, end = syn.synthetic_window()
    for a in disc.ASSETS:
        trades, funnel = disc.run_variant(variant="PRIMARY", funding=funding[a], oi=oi[a], price=price[a], start_ms=start, end_ms=end)
        ordered = sorted(trades, key=lambda t: t.entry_time_ms)
        for prev, nxt in zip(ordered, ordered[1:]):
            assert nxt.entry_time_ms > prev.exit_time_ms, "positions must never overlap on the same asset"
        if funnel["position_already_open"] > 0:
            assert len(trades) < funnel["funding_settlements_evaluated"]


def test_no_signal_precedence_first_match_is_deterministic() -> None:
    T = BASE
    funding = _funding("BTCUSDT", [(T - i * 8 * HOUR, 0.0001) for i in range(89, -1, -1)])
    oi = _oi("BTCUSDT", T - 30 * HOUR, T + 200 * HOUR, growth_per_day=0.02)
    price = _price("BTCUSDT", T - 10 * HOUR, T + 200 * HOUR)
    d = disc.decide_at(
        asset="BTCUSDT",
        decision_time_ms=T,
        funding=funding,
        oi=oi,
        price=price,
        position_open=True,
        window_start_ms=T + 10 * HOUR,  # forces OUTSIDE_COMMON_WINDOW
        window_end_ms=T + 100 * HOUR,
    )
    assert d.reason == "OUTSIDE_COMMON_WINDOW"
    assert d.emitted is False


def test_oi_leg_disabled_removes_only_the_crowding_confirmation() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    with_oi, f_with = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    without, f_without = disc.run_variant(variant="OI_CONTROL", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end, oi_leg=False)
    assert len(without) >= len(with_oi)
    assert f_without["oi_not_expanding"] == 0
    assert f_without["oi_missing_or_stale"] == 0
    assert f_with["oi_not_expanding"] > 0


def test_direction_control_reverses_only_the_direction() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    primary, _ = disc.run_variant(variant="PRIMARY", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end)
    reversed_, _ = disc.run_variant(variant="DIRECTION_CONTROL", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end, direction_mode="REVERSED")
    assert len(primary) == len(reversed_)
    for a, b in zip(primary, reversed_):
        assert a.entry_time_ms == b.entry_time_ms
        assert a.exit_time_ms == b.exit_time_ms
        assert a.direction != b.direction
        assert a.gross_return == pytest.approx(-b.gross_return)
        assert a.funding_cashflow == pytest.approx(-b.funding_cashflow)


def test_null_control_direction_is_deterministic_and_frozen_seeded() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    null1, _ = disc.run_variant(variant="NULL_CONTROL", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end, direction_mode="NULL")
    null2, _ = disc.run_variant(variant="NULL_CONTROL", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end, direction_mode="NULL")
    assert [t.direction for t in null1] == [t.direction for t in null2]
    for t in null1:
        assert t.direction == ref.null_direction("BTCUSDT", t.decision_time_ms, ref.NULL_SEED)


def test_timing_control_shifts_decision_instants_by_exactly_8h() -> None:
    funding, oi, price = syn.synthetic_authorities(assets=("BTCUSDT",))
    start, end = syn.synthetic_window()
    plus, _ = disc.run_variant(variant="TIMING_CONTROL_PLUS_8H", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end, shift_ms=8 * HOUR)
    minus, _ = disc.run_variant(variant="TIMING_CONTROL_MINUS_8H", funding=funding["BTCUSDT"], oi=oi["BTCUSDT"], price=price["BTCUSDT"], start_ms=start, end_ms=end, shift_ms=-8 * HOUR)
    instants_plus = {t.decision_time_ms for t in plus}
    base_instants = set(disc.decision_instants(funding["BTCUSDT"], start_ms=start, end_ms=end))
    for T in instants_plus:
        assert (T - 8 * HOUR) in base_instants
    assert instants_plus != {t.decision_time_ms for t in minus}


# ------------------------------------------------------------------- full pipeline
def test_full_pipeline_smoke_with_reconciliation() -> None:
    funding, oi, price = syn.synthetic_authorities()
    start, end = syn.synthetic_window()
    trades = []
    funnels = []
    for a in disc.ASSETS:
        tr, fn = disc.run_variant(variant="PRIMARY", funding=funding[a], oi=oi[a], price=price[a], start_ms=start, end_ms=end)
        trades.extend(tr)
        funnels.append(fn)
    merged = disc.merge_funnels(funnels)
    evaluated = merged["funding_settlements_evaluated"]
    skipped = sum(merged[k] for k in disc.FUNNEL_KEYS if k not in ("funding_settlements_evaluated", "executed_trades", "long_signals", "short_signals"))
    assert evaluated == merged["executed_trades"] + skipped
    assert merged["long_signals"] + merged["short_signals"] == merged["executed_trades"] == len(trades)
    assert set(merged) == set(disc.FUNNEL_KEYS)
    summary = disc.summarize_trades(trades)
    assert summary["pooled"]["n"] == len(trades)
    assert disc.cost_curve(trades)["scenarios"]["10bps"]["n"] == len(trades)
    assert "max_drawdown_diagnostic_only" in disc.diagnostics(trades, window_start_ms=start, window_end_ms=end)


# ----------------------------------------------------------------- exactly-once
@pytest.fixture()
def runner_module(tmp_path: Path):
    path = Path(__file__).resolve().parents[3] / "scripts" / "run_arc01_primary_discovery.py"
    spec = importlib.util.spec_from_file_location("arc01_runner_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT_DIR = tmp_path
    module.LEDGER_PATH = tmp_path / "EXPERIMENT_LEDGER.jsonl"
    return module


def test_exactly_once_ledger_lifecycle_and_replay_rejection(runner_module) -> None:
    m = runner_module
    assert m.read_ledger() == []
    m.append_ledger("REGISTERED", {"experiment_id": m.EXPERIMENT_ID})
    events = m.read_ledger()
    assert [e["event"] for e in events] == ["REGISTERED"]
    m.assert_not_consumed(events)  # STARTED-only state may resume
    m.append_ledger("STARTED", {"execution_implementation_commit": "x"})
    m.assert_not_consumed(m.read_ledger())
    m.append_ledger("COMPLETED", {"final_status": "DISCOVERY_FAIL"})
    with pytest.raises(m.InfrastructureFailure):
        m.assert_not_consumed(m.read_ledger())
    # append-only: sequence numbers increase monotonically
    seqs = [e["seq"] for e in m.read_ledger()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_runner_frozen_constants_match_prereg(runner_module) -> None:
    m = runner_module
    result = m.check_frozen_constants()
    assert result["status"] == "PASS", result["failed"]
    assert m.check_prereg_drift()["PREREG_DRIFT"] == 0


def test_import_authority_resolves_inside_this_worktree(runner_module) -> None:
    import trading_bot

    resolved = Path(trading_bot.__file__).resolve()
    assert "arc01-primary-discovery-01" in str(resolved), resolved
