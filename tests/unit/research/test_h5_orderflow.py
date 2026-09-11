"""H5-ORDERFLOW-IMBALANCE-CONTINUATION-01 — unit tests (frozen prereg contracts).

Pins: OFI/participation formulas and PIT windows, entry/exit/stop/cooldown
conventions, future-mutation invariant, absolute cost semantics
(DEF-RESEARCH-COST-001), B4 classification gates, and ledger STARTED-before-
evaluation + crash/recovery injection on the exact H5 flow shape (fixtures
only — never the real economic run).
"""

from __future__ import annotations

import numpy as np
import pytest

from trading_bot.research.execution_ledger import ResearchExecutionLedger
from trading_bot.research.h5_orderflow import (
    ATR_PERIOD,
    COOLDOWN_BARS,
    COST_RT_BPS,
    HOLD_BARS,
    LOOKBACK_BARS,
    P_GATE,
    WARMUP,
    Z_ENTRY,
    atr14,
    classify,
    close_time,
    compute_features,
    cost_scenario_net_r,
    simulate_h5,
    summarize,
)

SEED = 20260910


def _rng_bars(n: int, seed: int = 7) -> dict[str, np.ndarray]:
    """Deterministic OHLCV+flow bars: 1h grid, mild trend, positive volumes."""
    rng = np.random.default_rng(seed)
    ts = 1_578_368_000_000 + np.arange(n, dtype=np.int64) * 3_600_000
    cl = 100.0 + np.cumsum(rng.normal(0.0, 0.2, n))
    op = np.roll(cl, 1)
    op[0] = 100.0
    spread = np.abs(rng.normal(0.3, 0.1, n)) + 0.05
    hi = np.maximum(op, cl) + spread
    lo = np.minimum(op, cl) - spread
    vol = 1000.0 + rng.random(n) * 500.0
    ntr = 100.0 + rng.random(n) * 100.0
    return {
        "ts": ts,
        "op": op,
        "hi": hi,
        "lo": lo,
        "cl": cl,
        "volume": vol,
        "ntrades": ntr,
        "taker_buy": vol * 0.5,  # flat flow: OFI = 0 exactly everywhere
    }


def _dislocate(bars: dict[str, np.ndarray], t: int, side: int) -> None:
    """Engineer one qualifying decision bar: OFI = ±1 at 10x participation.

    With a flat-OFI baseline the trailing window holds 335 zeros + one ±1,
    so zOFI ≈ ±18 (>= 2.5) and P ≈ 9.7 (>= 1.5) — deterministic.
    """
    bars["taker_buy"][t] = bars["volume"][t] if side > 0 else 0.0
    bars["ntrades"][t] = 1000.0


# ---------------------------------------------------------------------------
# Features (Track D)
# ---------------------------------------------------------------------------


def test_ofi_formula_exact():
    vol = np.array([100.0, 100.0, 0.0])
    tbv = np.array([100.0, 40.0, 50.0])
    ofi = compute_features(vol, np.full(3, 10.0), tbv)["ofi"]
    assert ofi[0] == 1.0  # all taker-buy
    assert ofi[1] == pytest.approx(2 * 0.4 - 1.0)  # (2*tbv/vol)-1
    assert np.isnan(ofi[2])  # volume == 0 -> NaN -> NO_SIGNAL


def test_zofi_and_participation_trailing_window():
    bars = _rng_bars(LOOKBACK_BARS + 60)
    rng = np.random.default_rng(5)
    # varied flow so the trailing window has non-degenerate std
    share = 0.5 + 0.4 * np.sin(np.arange(bars["volume"].shape[0]) / 17.0) + 0.05 * rng.standard_normal(bars["volume"].shape[0])
    bars["taker_buy"] = np.clip(bars["volume"] * share, 0.0, bars["volume"])
    feat = compute_features(bars["volume"], bars["ntrades"], bars["taker_buy"])
    t = LOOKBACK_BARS + 40
    ofi = 2.0 * bars["taker_buy"] / bars["volume"] - 1.0
    w = ofi[t - LOOKBACK_BARS + 1 : t + 1]
    mean, std = w.mean(), w.std()  # population (ddof=0)
    assert feat["zofi"][t] == pytest.approx((ofi[t] - mean) / std)
    p_norm = bars["ntrades"][t - LOOKBACK_BARS + 1 : t + 1].mean()
    assert feat["part"][t] == pytest.approx(bars["ntrades"][t] / p_norm)
    # first valid index == WARMUP
    assert np.isfinite(feat["zofi"][WARMUP])
    assert not np.isfinite(feat["zofi"][WARMUP - 1]) or WARMUP == 0
    # degenerate window (std == 0) -> NaN -> NO_SIGNAL (engine contract)
    flat = _rng_bars(LOOKBACK_BARS + 60)
    ffeat = compute_features(flat["volume"], flat["ntrades"], flat["taker_buy"])
    assert np.all(np.isnan(ffeat["zofi"][WARMUP:]))


# ---------------------------------------------------------------------------
# Simulation conventions (Track D1/D2)
# ---------------------------------------------------------------------------


def test_entry_uses_next_bar_open_and_frozen_thresholds():
    n = LOOKBACK_BARS + HOLD_BARS + 20
    bars = _rng_bars(n)
    t = LOOKBACK_BARS + 5
    _dislocate(bars, t, side=+1)  # OFI = +1 -> LONG
    trades, skipped, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST",
    )
    hits = [tr for tr in trades if tr.decision_index == t]
    assert len(hits) == 1
    tr = hits[0]
    assert tr.direction == "LONG"
    assert tr.entry_index == t + 1  # decision after bar t complete -> open[t+1]
    assert tr.entry_ts == bars["ts"][t + 1]
    assert tr.entry_price == pytest.approx(bars["op"][t + 1])
    assert skipped >= 0 and tr.zofi >= Z_ENTRY and tr.part >= P_GATE


def test_short_direction_from_negative_flow():
    n = LOOKBACK_BARS + HOLD_BARS + 20
    bars = _rng_bars(n)
    t = LOOKBACK_BARS + 5
    _dislocate(bars, t, side=-1)  # OFI = -1 -> SHORT
    trades, _, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST",
    )
    hits = [tr for tr in trades if tr.decision_index == t]
    assert len(hits) == 1 and hits[0].direction == "SHORT"
    assert hits[0].stop_price == pytest.approx(hits[0].entry_price + hits[0].atr)


def test_time_exit_and_stop_pessimistic_convention():
    n = LOOKBACK_BARS + HOLD_BARS + 20
    bars = _rng_bars(n)
    t = LOOKBACK_BARS + 5
    _dislocate(bars, t, side=+1)
    trades, _, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST",
    )
    tr = [x for x in trades if x.decision_index == t][0]
    if tr.exit_index == t + HOLD_BARS:
        # no stop touched: time exit at close of bar t+12
        assert tr.exit_price == pytest.approx(bars["cl"][t + HOLD_BARS])
        assert tr.gross_r == pytest.approx((tr.exit_price - tr.entry_price) / tr.atr)
    else:
        # stop touched: pessimistic fill at the stop price
        assert tr.exit_price == pytest.approx(tr.stop_price)
        assert tr.gross_r == pytest.approx(-1.0)


def test_incomplete_tail_skipped_and_counted():
    n = LOOKBACK_BARS + HOLD_BARS - 2  # cannot complete the frozen horizon
    bars = _rng_bars(n)
    _dislocate(bars, n - 2, side=+1)  # decision bar with impossible horizon
    trades, skipped, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST",
    )
    assert all(tr.exit_index <= n - 1 for tr in trades)
    assert all(tr.decision_index != n - 2 for tr in trades)  # skipped, not traded


def test_atr_matches_h1_convention():
    bars = _rng_bars(60)
    end = 50
    a = atr14(bars["hi"], bars["lo"], bars["cl"], end)
    trs = []
    for i in range(end - ATR_PERIOD + 2, end + 1):
        trs.append(
            max(
                bars["hi"][i] - bars["lo"][i],
                abs(bars["hi"][i] - bars["cl"][i - 1]),
                abs(bars["lo"][i] - bars["cl"][i - 1]),
            )
        )
    assert a == pytest.approx(sum(trs) / len(trs))
    assert close_time(1_578_368_000_000) == 1_578_368_000_000 + 3_600_000 - 1


# ---------------------------------------------------------------------------
# Future-mutation invariant (Track E)
# ---------------------------------------------------------------------------


def test_future_mutation_byte_identical_up_to_T():
    n = LOOKBACK_BARS + 400
    bars = _rng_bars(n)
    T = n // 2
    f1 = compute_features(bars["volume"], bars["ntrades"], bars["taker_buy"])
    v2, nt2, tb2 = bars["volume"].copy(), bars["ntrades"].copy(), bars["taker_buy"].copy()
    v2[T + 1 :] *= 3.0
    tb2[T + 1 :] *= 0.5
    nt2[T + 1 :] *= 7.0
    f2 = compute_features(v2, nt2, tb2)
    for k in ("ofi", "zofi", "part"):
        assert np.array_equal(f1[k][: T + 1], f2[k][: T + 1], equal_nan=True), k
    # full pipeline: features are the ONLY trade-decision input up to T
    sim1, _, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST", feat=f1,
    )
    # mutate OHLC after T as well; decisions <= T must not move
    hi2, lo2, cl2, op2 = bars["hi"].copy(), bars["lo"].copy(), bars["cl"].copy(), bars["op"].copy()
    hi2[T + 1 :] *= 1.4
    lo2[T + 1 :] *= 0.6
    cl2[T + 1 :] *= 1.1
    op2[T + 1 :] *= 1.1
    sim2, _, _ = simulate_h5(
        bars["ts"], op2, hi2, lo2, cl2, v2, nt2, tb2, "TEST", feat=f2,
    )
    fields = ("decision_index", "decision_ts", "direction", "entry_index", "zofi", "part")
    d1 = [tuple(getattr(x, f) for f in fields) for x in sim1 if x.decision_index <= T]
    d2 = [tuple(getattr(x, f) for f in fields) for x in sim2 if x.decision_index <= T]
    assert d1 == d2


# ---------------------------------------------------------------------------
# Cost engine (Track F) — DEF-RESEARCH-COST-001 cannot recur
# ---------------------------------------------------------------------------


def test_cost_scenarios_absolute_monotone_identical_trade_set():
    bars = _rng_bars(LOOKBACK_BARS + 800, seed=11)
    # deterministic dislocations every 97 bars, alternating side (>> cooldown)
    for k, t in enumerate(range(LOOKBACK_BARS, LOOKBACK_BARS + 800 - HOLD_BARS - 2, 97)):
        _dislocate(bars, t, side=+1 if k % 2 == 0 else -1)
    trades, _, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST",
    )
    assert len(trades) >= 5, "fixture must generate trades"
    table = []
    for bps in (0.0, 5.0, 10.0, 20.0, 40.0):
        net = cost_scenario_net_r(trades, bps)
        cost = [t.gross_r - r for t, r in zip(trades, net)]
        table.append(
            {
                "bps": bps,
                "N": len(net),
                "gross": float(np.mean([t.gross_r for t in trades])),
                "cost": float(np.mean(cost)) if cost else 0.0,
                "net": float(np.mean(net)),
            }
        )
        assert all(c >= 0.0 for c in cost), f"negative cost at {bps} bps"
        if bps > 0:
            # net == gross - (bps/10000)/risk_frac exactly (absolute anchoring)
            expect = float(
                np.mean([t.gross_r - (bps / 10_000.0) / t.risk_frac for t in trades])
            )
            assert table[-1]["net"] == pytest.approx(expect, abs=1e-12)
    # 0 bps == gross exactly
    assert table[0]["net"] == pytest.approx(table[0]["gross"], abs=1e-12)
    assert table[0]["cost"] == pytest.approx(0.0, abs=1e-15)
    # monotone non-increasing
    for a, b in zip(table, table[1:]):
        assert b["net"] <= a["net"] + 1e-12
    # trade set identical (pure recomputation over the same frozen list)
    assert all(row["N"] == table[0]["N"] for row in table)
    # base-case net_r equals the 10 bps absolute formula
    base_net = [t.net_r for t in trades]
    base_abs = [t.gross_r - (COST_RT_BPS / 10_000.0) / t.risk_frac for t in trades]
    assert base_net == pytest.approx(base_abs, abs=1e-15)


# ---------------------------------------------------------------------------
# Classification gates (Track M)
# ---------------------------------------------------------------------------


def test_classify_frozen_gates():
    good = {
        "N": 50,
        "net_expectancy_R": 0.1,
        "PF_net": 1.3,
        "P_Sharpe_gt_0": 0.95,
        "permutation_p": 0.01,
        "halves": [1, 1],
        "thirds": [1, 1, 1],
        "walk_forward_last_third_net_R": 0.05,
    }
    assert classify(good, [25, 25], [50]) == "DISCOVERY_PASS"
    fail = dict(good, net_expectancy_R=-0.1)
    assert classify(fail, [25, 25], [50]) == "DISCOVERY_FAIL"
    assert classify(dict(good, N=29), [15, 15], [50]) == "INSUFFICIENT_SAMPLE"
    assert classify(good, [14, 25], [50]) == "INSUFFICIENT_SAMPLE"
    assert classify(good, [25, 25], [9]) == "INSUFFICIENT_SAMPLE"
    assert classify(dict(good, halves=[1, -1]), [25, 25], [50]) == "DISCOVERY_FAIL"


def test_summarize_shape_and_frozen_seed_path():
    bars = _rng_bars(LOOKBACK_BARS + 600, seed=13)
    for k, t in enumerate(range(LOOKBACK_BARS, LOOKBACK_BARS + 600 - HOLD_BARS - 2, 97)):
        _dislocate(bars, t, side=+1 if k % 2 == 0 else -1)
    trades, _, _ = simulate_h5(
        bars["ts"], bars["op"], bars["hi"], bars["lo"], bars["cl"],
        bars["volume"], bars["ntrades"], bars["taker_buy"], "TEST",
    )
    assert trades
    m = summarize(trades)
    assert m["N"] == len(trades)
    for k in (
        "gross_expectancy_R", "net_expectancy_R", "PF_gross", "PF_net", "Sharpe",
        "Sharpe_CI95", "P_Sharpe_gt_0", "permutation_p", "wins", "losses",
        "max_drawdown_R", "MC_DD95_R", "cost_drag_R", "halves", "thirds",
        "walk_forward_last_third_net_R", "mean_holding_bars",
    ):
        assert k in m
    assert m["cost_drag_R"] == pytest.approx(m["gross_expectancy_R"] - m["net_expectancy_R"])
    assert m["mean_holding_bars"] <= HOLD_BARS


# ---------------------------------------------------------------------------
# Ledger flow (Track I) — fixtures only
# ---------------------------------------------------------------------------


def test_ledger_started_before_evaluation_and_crash_recovery(tmp_path):
    led = ResearchExecutionLedger(tmp_path, "H5-TEST-EXP")

    # attempt 1: crash AFTER start_attempt (durably persisted), before results
    verdict = led.acquire()
    assert verdict == "ACQUIRED"
    rec1 = led.start_attempt(
        spec_sha256="deadbeef", dataset_sha256="cafe", prereg_commit="c426b35"
    )
    ledger_lines = tmp_path.joinpath("research_execution_ledger.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert ledger_lines, "STARTED must be on disk before any economic work"
    assert "STARTED" in ledger_lines[-1]
    led.finish_failed(rec1.attempt_id, "injected crash after STARTED")
    led.release()  # simulate the crashed process exiting (OS frees the lock)

    # attempt 2: recovery of the same experiment identity
    verdict = led.acquire()
    assert verdict == "ACQUIRED"  # FAILED attempt does not consume the identity
    rec2 = led.start_attempt(
        spec_sha256="deadbeef",
        dataset_sha256="cafe",
        prereg_commit="c426b35",
        recovery_of_attempt_id=rec1.attempt_id,
    )
    assert rec2.attempt_index == rec1.attempt_index + 1
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    led.finish_completed(rec2.attempt_id, tmp_path / "result.json")
    led.release()

    s = led.experiment_summary()
    assert s["economic_experiments"] == 1
    assert s["execution_attempts"] == 2
    assert s["failed_attempts"] == 1
    assert s["completed_executions"] == 1
    # third acquire is refused: identity consumed
    assert led.acquire() == "ALREADY_CONSUMED"


def test_ledger_concurrent_authority(tmp_path):
    a = ResearchExecutionLedger(tmp_path, "H5-TEST-CONC")
    b = ResearchExecutionLedger(tmp_path, "H5-TEST-CONC")
    assert a.acquire() == "ACQUIRED"
    assert b.acquire() == "ALREADY_RUNNING"
    a.release()
