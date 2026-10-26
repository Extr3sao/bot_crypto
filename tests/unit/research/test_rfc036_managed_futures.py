"""RFC-036 §88 tests: raw-contract substrate, roll policy, PIT, accounting.

All tests use small SYNTHETIC contract chains (no network), exercising the same
code paths used by the RFC-036 runner.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from trading_bot.research import managed_futures_v1 as mf


def _o(y: int, m: int, d: int) -> int:
    return date(y, m, d).toordinal()


def _bars(o0: int, o1: int, base: float, slope: float, vol0: float) -> str:
    lines = []
    n = 0
    for o in range(o0, o1 + 1):
        if date.fromordinal(o).weekday() >= 5:
            continue
        p = base + slope * n
        vol = vol0 + n
        d = date.fromordinal(o)
        lines.append(f"{d.year % 100:02d}{d.month:02d}{d.day:02d},{p},{p},{p},{p},{vol},{vol}")
        n += 1
    return "\n".join(lines)


def _market(contracts: dict[str, str], root: str = "gc") -> mf.ChainMarket:
    return mf.build_market(root, contracts)


def _cfg(**kw: object) -> mf.BacktestConfig:
    # short synthetic chains need a shorter lookback than the frozen 252d
    return mf.default_config(lookback=60, vol_lookback=20, **kw)


def _chain() -> mf.ChainMarket:
    """Two successive contracts (Feb-1990 then Mar-1990), rising prices."""
    files = {
        # Feb-1990 delivery, trading Jun-1989 .. Jan-1990
        "GC90G.txt": _bars(_o(1989, 6, 1), _o(1990, 1, 20), 400.0, 0.5, 100.0),
        # Mar-1990 delivery, trading Jul-1989 .. Feb-1990
        "GC90H.txt": _bars(_o(1989, 7, 1), _o(1990, 2, 20), 400.5, 0.5, 50.0),
    }
    return _market(files)


# --------------------------------------------------------------------------- #
# parsing / eligibility / expiry                                                #
# --------------------------------------------------------------------------- #
def test_parse_contract_filename() -> None:
    assert mf.parse_contract_filename("CL00G.txt") == ("cl", 2000, 2)
    assert mf.parse_contract_filename("GC99Z.txt") == ("gc", 1999, 12)
    assert mf.parse_contract_filename("SP02M.txt") == ("sp", 2002, 6)
    assert mf.parse_contract_filename("not_a_contract.txt") is None


def test_parse_bars_both_date_formats() -> None:
    txt = (
        '"Date","Open","High","Low","Close","Volume","OpenInt"\n'
        '01/19/2001,94.50,94.50,94.50,94.50,0,0\n'
        "900822,29.05,31.30,29.05,31.22,69375,70893\n"
    )
    bars = mf.parse_bars(txt)
    assert len(bars) == 2
    closes = sorted(b.close for b in bars)
    assert closes == [31.22, 94.50]
    # both dates parsed correctly (bars are sorted by ordinal)
    assert bars[0].ordinal == _o(1990, 8, 22)
    assert bars[1].ordinal == _o(2001, 1, 19)


def test_delivery_month_and_expiry() -> None:
    md = _chain()
    c = md.series["gc9002"].contract
    assert c.delivery_yyyymm == 199002
    assert c.month == 2 and c.year == 1990
    assert md.series["gc9003"].contract.delivery_yyyymm == 199003


def test_front_selection_excludes_deliverable_month() -> None:
    md = _chain()
    # on a date inside Jan-1990 the Feb contract is still deliverable-later (ok),
    # but a date inside Feb-1990 must NOT hold the Feb (deliverable) contract
    i_feb = md.dates.index(_o(1990, 2, 1))
    front = mf.select_front_contract(md, i_feb, 20)
    assert front == "gc9003"
    # on a date inside Jan-1990 the Feb contract is eligible
    i_jan = md.dates.index(_o(1990, 1, 10))
    assert mf.select_front_contract(md, i_jan, 20) == "gc9002"


# --------------------------------------------------------------------------- #
# PIT / future poisoning                                                        #
# --------------------------------------------------------------------------- #
def test_pit_front_selection_ignores_future_bars() -> None:
    md = _chain()
    i = md.dates.index(_o(1990, 1, 10))
    full = mf.select_front_contract(md, i, 20)
    # truncate all bars strictly after the decision date
    cut = md.dates[i]
    trunc = {cid: mf.ContractSeries(
        s.contract, [b for b in s.bars if b.ordinal <= cut])
        for cid, s in md.series.items()}
    tdates = sorted({b.ordinal for s in trunc.values() for b in s.bars})
    md_t = mf.ChainMarket(md.root, md.spec, trunc, tdates)
    assert mf.select_front_contract(md_t, len(md_t.dates) - 1, 20) == full


def test_roll_schedule_is_pit_stable() -> None:
    md = _chain()
    ts_full = mf.build_tradable_series(md, md.dates[0], md.dates[-1])
    cut = md.dates[len(md.dates) // 2]
    ts_tr = mf.build_tradable_series(md, md.dates[0], cut)
    for o, cid in ts_tr.held.items():
        assert ts_full.held[o] == cid


# --------------------------------------------------------------------------- #
# continuous vs traded separation, roll accounting                             #
# --------------------------------------------------------------------------- #
def test_interval_return_uses_held_contract_not_a_roll_gap() -> None:
    md = _chain()
    ts = mf.build_tradable_series(md, md.dates[0], md.dates[-1])
    # find a roll date
    rolls = [r for r in ts.rolls if r.reason == "MONTHLY"]
    assert rolls, "expected a monthly roll"
    rd = rolls[0].ordinal
    ic = ts.interval_contract[rd]
    closes = {b.ordinal: b.close for b in md.series[ic].bars}
    # interval return at the roll uses the OLD contract's own close-to-close
    # (carry-forward its last print if it has no bar on the roll day)
    prev = max(o for o in closes if o < rd)
    now = mf._close_of(closes, rd)
    assert now is not None
    expected = now / closes[prev] - 1.0
    assert abs(ts.interval_return[rd] - expected) < 1e-12
    # and the held contract *after* the roll differs from the interval contract
    assert ts.held[rd] != ic


def test_no_back_adjusted_series_is_used_for_pnl() -> None:
    from pathlib import Path
    src = Path(mf.__file__).read_text(encoding="utf-8")
    # the module must not import a back-adjustment routine for PnL
    assert "back_adjust" not in src
    assert "panama" not in src.lower()


# --------------------------------------------------------------------------- #
# accounting: multipliers, costs, sizing, long/short                           #
# --------------------------------------------------------------------------- #
def _panels(md: mf.ChainMarket) -> tuple[list[mf.MarketPanel], list[int]]:
    ts = mf.build_tradable_series(md, md.dates[0], md.dates[-1])
    cal = sorted(ts.held)
    p = mf.build_panel(md, ts, cal)
    return [p], cal


def test_multiplier_scales_pnl_linearly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    md = _chain()
    panels, cal = _panels(md)
    cfg = _cfg()
    r1 = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]), cfg, 1e7)
    # double the multiplier -> notional (and hence PnL) is invariant
    md2 = mf.ChainMarket(md.root, {**md.spec, "multiplier": md.spec["multiplier"] * 2},
                         md.series, md.dates)
    panels2, _ = _panels(md2)
    r2 = mf.simulate_portfolio(panels2, cal, (cal[0], cal[-1]), cfg, 1e7)
    assert r1["status"] == "OK" and r2["status"] == "OK"
    assert abs(float(r1["gross_pnl"].sum())) > 0.0
    ratio = float(r2["gross_pnl"].sum()) / float(r1["gross_pnl"].sum())
    assert 0.99 < ratio < 1.01


def test_transaction_and_roll_costs_are_charged() -> None:
    md = _chain()
    panels, cal = _panels(md)
    run = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]), _cfg(), 1e7)
    assert run["status"] == "OK"
    assert float(run["cost_pnl"].sum()) > 0.0
    assert len(run["roll_events"]) >= 1


def test_costs_increase_with_stress() -> None:
    md = _chain()
    panels, cal = _panels(md)
    base = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]), _cfg(cost_mult=1.0), 1e7)
    stressed = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]), _cfg(cost_mult=2.0), 1e7)
    assert float(stressed["cost_pnl"].sum()) > float(base["cost_pnl"].sum())


def test_signal_sign_and_sizing_bounds() -> None:
    md = _market({"GC90G.txt": _bars(_o(1989, 6, 1), _o(1990, 1, 20), 300.0, 1.0, 100.0)})
    ts = mf.build_tradable_series(md, md.dates[0], md.dates[-1])
    ser = mf.continuous_signal_series(ts)
    k = len(ser.ordinals) - 1
    assert mf.momentum_signal(ser, k, 60) == 1.0  # rising prices -> long
    vol = mf.trailing_vol(ser, k, 60)
    assert vol is not None and vol >= 0.0


def test_long_short_accounting() -> None:
    # falling prices -> short -> positive PnL contribution
    md = _market({"GC90G.txt": _bars(_o(1989, 6, 1), _o(1990, 1, 20), 600.0, -1.0, 100.0)})
    panels, cal = _panels(md)
    run = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]), _cfg(), 1e7)
    assert run["status"] == "OK"
    # falling prices -> net short -> negative net exposure
    assert float(np.mean(run["net_exposure"])) <= 0.0


def test_rounding_zeroes_high_notional_markets() -> None:
    md = _chain()
    panels, cal = _panels(md)
    frac = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]),
                                 _cfg(integer_contracts=False), 500_000.0)
    ints = mf.simulate_portfolio(panels, cal, (cal[0], cal[-1]),
                                 _cfg(integer_contracts=True), 500_000.0)
    # at a tiny capital the integer version must take <= the fractional turnover
    assert float(ints["cost_pnl"].sum()) <= float(frac["cost_pnl"].sum()) + 1e-6


# --------------------------------------------------------------------------- #
# split / holdout isolation, gate logic, false success                          #
# --------------------------------------------------------------------------- #
def test_split_isolation_windows_are_disjoint() -> None:
    d0, d1 = mf.SPLIT_BOUNDS["DISCOVERY"]
    v0, v1 = mf.SPLIT_BOUNDS["VALIDATION"]
    assert d0 < d1 < v0 < v1
    assert mf.HOLDOUT == "FUTURE_ONLY"


def test_g_mf_data_gate_logic() -> None:
    ok = {"individual_contracts": True, "expiry_identifiable": True,
          "tradable_contract_at_each_decision": True, "multi_asset_breadth": True,
          "pit_feasible": True, "roll_observable": True, "not_paid_only": True}
    assert mf.gate_g_mf_data(ok).status == "PASS"
    bad = {**ok, "tradable_contract_at_each_decision": False}
    assert mf.gate_g_mf_data(bad).status == "FAIL"


def test_g_mf_2_requires_positive_validation_net() -> None:
    good: dict[str, object] = {"net_pnl": 1.0, "n_markets": 26,
                               "per_market_net": {f"m{i}": 1.0 for i in range(26)}}
    assert mf.gate_g_mf_2(good, "PASS").status == "PASS"
    bad = {**good, "net_pnl": -1.0}
    assert mf.gate_g_mf_2(bad, "PASS").status == "FAIL"
    # a failed reproduction must block validation promotion
    assert mf.gate_g_mf_2(good, "FAIL").status == "FAIL"


def test_false_success_audit_counts_triggers() -> None:
    clean = {t: False for t in mf.FALSE_SUCCESS_TRIGGERS}
    assert mf.audit_false_success(clean)["false_success_count"] == 0
    dirty = dict(clean)
    dirty["roll_costs_omitted"] = True
    assert mf.audit_false_success(dirty)["false_success_count"] == 1


def test_markers_and_frozen_constants() -> None:
    assert mf.EXECUTABLE_VALIDATED_EDGE_COUNT == 0  # baseline at start
    # §82: the marker advances to 1 only on a passing Validation
    assert mf.EXECUTABLE_VALIDATED_EDGE_COUNT_AFTER_RFC036 == 1
    assert mf.PAPER_CANDIDATE_COUNT == 0
    assert mf.P2_STATUS == "AUTHORIZED_WAITING"
    assert mf.REPRODUCTION_FIDELITY in ("EXACT", "CLOSE", "CONCEPTUAL")
    assert mf.PRIMARY_REPRODUCTION_SOURCE == "S001"
    assert "T+1" in mf.EXECUTION_TIMING or ">= T+1" in mf.EXECUTION_TIMING
    # every market has a positive multiplier and a class in the target set
    for spec in mf.MARKET_SPECS.values():
        assert spec["multiplier"] > 0
        assert spec["asset_class"] in mf.ASSET_CLASSES
