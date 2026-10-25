"""ARP-003 §7/§8/§24 — cost-feasibility screen tests.

TEST_TARGET == RUNTIME_TARGET: the module under test is the exact module the
driver script ``scripts/alpha_recovery_feasibility.py`` imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery.feasibility import (  # noqa: E402
    BARS_PER_DAY_5M,
    HORIZONS_5M,
    abs_move_bps,
    frontier_row,
    horizon_frontier,
    signed_move_bps,
)


def random_walk(n: int, *, seed: int = 7) -> list[float]:
    """Deterministic, diffusive price series (no RNG module, no wall-clock)."""
    state = seed
    price = 100.0
    out = [price]
    for _ in range(n - 1):
        state = (1103515245 * state + 12345) % (2**31)
        price = max(1.0, price * (1.0 + ((state / 2**31) - 0.5) * 0.004))
        out.append(price)
    return out


def test_abs_move_matches_definition() -> None:
    closes = [100.0, 101.0, 99.0, 100.5]
    got = abs_move_bps(closes, 1)
    assert len(got) == 3
    assert got[0] == pytest.approx(100.0, abs=1e-3)
    assert got[1] == pytest.approx(abs(99.0 / 101.0 - 1.0) * 10_000.0, abs=1e-3)


def test_signed_non_overlapping_takes_stride() -> None:
    closes = [100.0 * (1.01**i) for i in range(25)]
    overlapping = signed_move_bps(closes, 5, non_overlapping=False)
    independent = signed_move_bps(closes, 5, non_overlapping=True)
    assert len(overlapping) == 20
    assert len(independent) == 4
    assert all(v > 0 for v in independent)


def test_frontier_row_ratio_is_gross_over_cost() -> None:
    row = frontier_row(random_walk(600), 12, cost_bps_rt=20.0)
    assert row["gross_opportunity_bps"] is not None
    assert row["opportunity_to_cost_ratio"] == pytest.approx(
        row["gross_opportunity_bps"] / 20.0, abs=2e-3
    )


def test_horizon_frontier_is_deterministic_and_ordered() -> None:
    series = {f"X_W{i}": random_walk(900, seed=i) for i in range(2)}
    first = horizon_frontier(series, cost_bps_rt=23.559017)
    second = horizon_frontier(series, cost_bps_rt=23.559017)
    assert first == second  # pure / deterministic
    per = first["per_horizon"]
    # a diffusive series exposes a strictly larger typical move at longer horizons
    assert per["30m"]["gross_opportunity_bps"] < per["1d"]["gross_opportunity_bps"]
    assert per["30m"]["opportunity_to_cost_ratio"] < per["1d"]["opportunity_to_cost_ratio"]
    assert 0.0 <= per["1d"]["frac_abs_ge_cost"] <= 1.0
    assert set(per["1d"]["by_asset"]) == {"X"}


def test_horizon_ladder_is_frozen() -> None:
    assert HORIZONS_5M["30m"] == 6
    assert HORIZONS_5M["7d"] == 2016
    assert HORIZONS_5M["1d"] == BARS_PER_DAY_5M
    assert list(HORIZONS_5M.values()) == sorted(HORIZONS_5M.values())
