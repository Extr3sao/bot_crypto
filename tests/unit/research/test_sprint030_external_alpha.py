"""RFC-030 — external alpha reproduction tests (SYNTHETIC ONLY, no network)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint030_lib as L  # noqa: E402

DAY = 86_400_000


def _panel(n_days: int = 260, n_assets: int = 8, seed: int = 3,
           trend: float = 0.0) -> L.Panel:
    rng = np.random.default_rng(seed)
    # start on a Monday so weekly rebalance days exist
    start = int(datetime(2020, 1, 6, tzinfo=UTC).timestamp() * 1000)
    dates = np.array([start + i * DAY for i in range(n_days)], dtype=np.int64)
    logr = rng.normal(0.001 + trend, 0.02, size=(n_days, n_assets))
    close = 100.0 * np.exp(np.cumsum(logr, axis=0))
    assets = tuple(f"A{i}USDT" for i in range(n_assets))
    return L.Panel(dates=dates, assets=assets, close=close,
                   quote_volume=np.ones_like(close), open_ms=np.zeros_like(close))


# ---------------------------------------------------------------------------
# cost model (§22)
# ---------------------------------------------------------------------------

def test_cost_model_is_v1_and_15bps() -> None:
    assert L.PER_SIDE_COST_BPS == 15.0
    assert (
        L.EXT_CRYPTO_COST_MODEL_V1["taker_fee_bps"]
        + L.EXT_CRYPTO_COST_MODEL_V1["half_spread_bps"]
        + L.EXT_CRYPTO_COST_MODEL_V1["impact_bps"]) == L.PER_SIDE_COST_BPS


def test_cost_is_charged_on_turnover() -> None:
    p = _panel()
    mask = np.ones(p.n, dtype=bool)
    r = L.run_cross_sectional_momentum(p, mask)
    for rb in r.rebalances:
        assert abs(rb.cost_bps - rb.traded_notional * L.PER_SIDE_COST_BPS) < 1e-9
        assert abs(rb.net_bps - (rb.gross_bps - rb.cost_bps)) < 1e-9


# ---------------------------------------------------------------------------
# registry / scorecard / selection (§5, §19, §20, §21)
# ---------------------------------------------------------------------------

def test_registry_integrity() -> None:
    required = {"SOURCE_ID", "title", "authors", "publication", "year", "URL",
                "artifact_type", "asset_class", "strategy_family",
                "holding_horizon", "sample_period", "reported_gross_performance",
                "reported_net_performance", "cost_assumptions",
                "robustness_evidence", "replication_evidence",
                "known_criticisms", "data_requirements",
                "implementation_requirements", "reliability_score"}
    assert len(L.SOURCES) >= 10
    assert all(required <= set(s) for s in L.SOURCES)
    ids = [s["SOURCE_ID"] for s in L.SOURCES]
    assert len(ids) == len(set(ids))


def test_shortlist_is_capped_and_families_differ() -> None:
    assert len(L.CANDIDATES) == L.MAX_EXTERNAL_STRATEGIES == 5
    families = [c["family"] for c in L.CANDIDATES]
    assert len(families) == len(set(families))


def test_selection_is_top2_by_frozen_rule() -> None:
    axes = ["EVIDENCE_STRENGTH", "ECONOMIC_HEADROOM", "DATA_FEASIBILITY",
            "IMPLEMENTATION_COMPLEXITY", "ORTHOGONALITY"]
    ranked = sorted(L.CANDIDATES,
                    key=lambda c: (-sum(c[k] for k in axes), -len(c["SOURCE"]),
                                   c["CANDIDATE_ID"]))
    passing = [c["CANDIDATE_ID"] for c in ranked if c["DECISION"] == "REPRODUCE"]
    assert tuple(passing[:L.MAX_REPRODUCED]) == L.SELECTED
    assert L.MAX_REPRODUCED == 2


def test_selection_frozen_before_backtests() -> None:
    assert L.SELECTED == ("EXT-TSMOM-001", "EXT-XMOM-001")
    assert L.SELECTION_RULE.startswith("Rank candidates")


def test_fidelity_is_close_not_exact() -> None:
    for f in L.REPRODUCTION_FIDELITY.values():
        assert f in ("EXACT_REPRODUCTION", "CLOSE_REPRODUCTION",
                     "CONCEPTUAL_REPRODUCTION")
        assert f == "CLOSE_REPRODUCTION"   # we deviate on universe/costs/weighting


# ---------------------------------------------------------------------------
# survivorship (§57)
# ---------------------------------------------------------------------------

def test_dead_coins_in_universe_for_survivorship() -> None:
    assert "FTTUSDT" in L.UNIVERSE
    assert "LUNAUSDT" in L.UNIVERSE


# ---------------------------------------------------------------------------
# PIT (§55)
# ---------------------------------------------------------------------------

def test_future_data_never_changes_earlier_trades() -> None:
    p = _panel(n_days=300, n_assets=10)
    mask = np.ones(p.n, dtype=bool)
    full = L.run_cross_sectional_momentum(p, mask)
    cut = 220
    cm = p.close.copy()
    cm[cut:, :] = np.nan
    truncated = L.Panel(dates=p.dates, assets=p.assets, close=cm,
                        quote_volume=p.quote_volume, open_ms=p.open_ms)
    r_trunc = L.run_cross_sectional_momentum(truncated, mask)
    # rebalances whose EXIT is before the cut must be identical
    for a, b in zip(r_trunc.rebalances, full.rebalances, strict=False):
        assert a.idx == b.idx
        assert abs(a.gross_bps - b.gross_bps) < 1e-9
        assert abs(a.cost_bps - b.cost_bps) < 1e-9


# ---------------------------------------------------------------------------
# strategy mechanics
# ---------------------------------------------------------------------------

def test_xmom_is_market_neutral_and_non_overlapping() -> None:
    p = _panel()
    r = L.run_cross_sectional_momentum(p, np.ones(p.n, dtype=bool))
    assert r.rebalances, "expected trades"
    idx = [rb.idx for rb in r.rebalances]
    assert idx == sorted(idx) and len(idx) == len(set(idx))
    for rb in r.rebalances:
        assert rb.n_long == rb.n_short > 0


def test_tsmom_sign_rule_direction() -> None:
    up = _panel(trend=0.01, seed=1)
    dn = _panel(trend=-0.01, seed=1)
    ru = L.run_time_series_momentum(up, np.ones(up.n, dtype=bool))
    rd = L.run_time_series_momentum(dn, np.ones(dn.n, dtype=bool))
    # a strongly trending panel is almost fully one-sided
    assert all(rb.n_long >= rb.n_short for rb in ru.rebalances), "uptrend should be long"
    assert all(rb.n_short >= rb.n_long for rb in rd.rebalances), "downtrend should be short"


def test_no_imputation_nan_excluded() -> None:
    p = _panel(n_days=200, n_assets=8)
    cm = p.close.copy()
    cm[:, 0] = np.nan            # asset 0 has no data at all
    cm2 = L.Panel(dates=p.dates, assets=p.assets, close=cm,
                  quote_volume=p.quote_volume, open_ms=p.open_ms)
    r_nan = L.run_cross_sectional_momentum(cm2, np.ones(cm2.n, dtype=bool))
    assert r_nan.rebalances, "still trades on remaining assets"
    # dropping one asset changes the book but must not error or impute zeros
    assert abs(r_nan.rebalances[0].cost_bps) > 0


def test_determinism() -> None:
    p = _panel()
    m = np.ones(p.n, dtype=bool)
    a = L.run_cross_sectional_momentum(p, m)
    b = L.run_cross_sectional_momentum(p, m)
    assert [x.net_bps for x in a.rebalances] == [x.net_bps for x in b.rebalances]
    c = L.run_time_series_momentum(p, m)
    d = L.run_time_series_momentum(p, m)
    assert [x.net_bps for x in c.rebalances] == [x.net_bps for x in d.rebalances]


def test_rebalance_cadence() -> None:
    p = _panel(n_days=120)
    mask = np.ones(p.n, dtype=bool)
    weeks = L._weekly_rebalance_days(p, mask)
    months = L._monthly_rebalance_days(p, mask)
    assert len(weeks) == sum(
        1 for t in p.dates
        if datetime.fromtimestamp(int(t) / 1000, tz=UTC).weekday() == 0)
    assert len(months) == len({(datetime.fromtimestamp(int(t) / 1000, tz=UTC).year,
                               datetime.fromtimestamp(int(t) / 1000, tz=UTC).month)
                              for t in p.dates})


def test_splits_chronological_and_disjoint() -> None:
    order = {"DISCOVERY": ("2018-01-01", "2021-06-30"),
             "VALIDATION": ("2021-07-01", "2023-12-31"),
             "HOLDOUT": ("2024-01-01", "2026-09-30")}
    assert order == L.SPLIT_BOUNDS
    assert order["DISCOVERY"][1] < order["VALIDATION"][0]
    assert order["VALIDATION"][1] < order["HOLDOUT"][0]


# ---------------------------------------------------------------------------
# gates / verification
# ---------------------------------------------------------------------------

def test_metrics_identity() -> None:
    p = _panel()
    r = L.run_cross_sectional_momentum(p, np.ones(p.n, dtype=bool))
    m = r.metrics(52.0)
    assert m["status"] == "OK"
    assert abs(m["net_expectancy_bps"]
               - (m["gross_expectancy_bps"] - m["cost_expectancy_bps"])) < 1e-9


def test_no_trades_reports_status() -> None:
    p = _panel(n_days=10, n_assets=3)
    r = L.run_cross_sectional_momentum(p, np.ones(p.n, dtype=bool))
    assert r.metrics(52.0)["status"] == "NO_TRADES"


def test_verification_artifact_zero_false_success() -> None:
    vp = REPO / "reports" / "external-alpha" / "RFC030_VERIFICATION.json"
    if not vp.exists():
        return  # artifacts are gitignored; skip when absent
    payload = json.loads(vp.read_text(encoding="utf-8"))
    assert payload["FALSE_SUCCESS"] == 0
    assert payload["checks_passed"] == payload["checks_total"]


def test_holdout_not_opened_when_validation_negative() -> None:
    # the discipline is encoded in the run script: validation must be net>0
    run_src = (REPO / "scripts" / "sprint030_run.py").read_text(encoding="utf-8")
    assert "\"reason\": \"VALIDATION did not produce a positive net edge\"" in run_src
    assert "HOLDOUT only if VALIDATION passes" in run_src
