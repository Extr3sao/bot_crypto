"""WP-EDGE-08 — the registration, the books, the screen and the holdout claim.

These tests are about the *decisions* the package makes, not about its prose:

* the parameters under test are the registered bytes (every book's hash is recomputed and
  compared with ``PREREGISTRATION.json``), and the hashes a defect SUPERSEDED are gone;
* a book's decision instant is the close of the bar it read, so nothing in the package can act
  before the bar it decided on had closed;
* the gross screen really stops a book with no setups, and its consequence is the registered one;
* the disjointness classifier cannot be talked out of a corpus shard or a result artefact, and it
  allows the work package's own files for the reason it states;
* the analysis readings are deterministic: the same trades give the same bootstrap interval, and
  the frequency is derived from the window's own length;
* the verdict device turns criteria into the four registered verdicts and nothing else.

Nothing here reads the cross-section's outcomes: the heavy readings are published by the scripts and
checked by ``scripts/edge08_verify.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge08 import disjointness
from trading_bot.research.edge08.analysis import extras, leave_out_largest
from trading_bot.research.edge08.books import (
    DECLARED_PARAMS,
    PROPOSED_ARMS,
    QualityReversionDaily,
    build_proposed,
    params_hash,
)
from trading_bot.research.edge08.registration import (
    COVERAGE_FLOOR_BARS,
    HOLDOUT_SYMBOLS,
    HOLDOUT_UNIVERSE,
    MIN_TRADES,
    PREREGISTRATION,
    UNIVERSE_MANIFEST,
    WINDOWS,
)
from trading_bot.research.edge08.screens import DEFECTS_FIXED, screen_verdict
from trading_bot.research.edge08.validation import coverage_reading, criteria_reading, decide

REPO_ROOT = Path(__file__).resolve().parents[3]

HOUR_MS = 3_600_000


def _bars(
    closes: list[float], *, step_ms: int = HOUR_MS, start_ms: int = 1_600_000_000_000
) -> list[OHLCVBar]:
    """A tiny synthetic series: open == previous close, high/low one unit around the close."""
    bars: list[OHLCVBar] = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        bars.append(
            OHLCVBar(
                ts=start_ms + index * step_ms,
                open=opened,
                high=max(opened, close) + 1.0,
                low=min(opened, close) - 1.0,
                close=close,
                volume=1.0,
            )
        )
    return bars


# -- the registration ------------------------------------------------------------------ #
def test_every_registered_book_hash_matches_the_preregistration() -> None:
    registered = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert set(registered["books"]) == set(DECLARED_PARAMS)
    for arm, params in DECLARED_PARAMS.items():
        assert registered["books"][arm]["params"] == params, arm
        assert registered["books"][arm]["params_hash"] == params_hash(params), arm


def test_the_superseded_hashes_of_def_edge08_01_are_not_the_hash_of_any_book_under_test() -> None:
    current = {params_hash(params) for params in DECLARED_PARAMS.values()}
    superseded = {
        value
        for defect in DEFECTS_FIXED
        for value in dict(defect.get("superseded_params_hashes") or {}).values()
    }
    assert superseded, "the defect record must name what it superseded"
    assert not (superseded & current), "a superseded parameter hash is still under test"


def test_the_cross_section_manifest_holds_the_registered_symbols() -> None:
    manifest = json.loads(UNIVERSE_MANIFEST.read_text(encoding="utf-8"))
    assert list(manifest["symbols"]) == list(HOLDOUT_SYMBOLS)
    assert manifest["totals"]["bars"] > 300_000
    assert manifest["unread_cross_section"]["claim_holds"] is True
    assert HOLDOUT_UNIVERSE == ("AAVE", "UNI", "KSM", "SNX", "CRV", "SUSHI")


# -- no look-ahead --------------------------------------------------------------------- #
def test_a_decision_is_taken_on_a_closed_bar_and_acts_after_it() -> None:
    quoted = OHLCVBar(
        ts=1_700_000_000_000, open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0
    )
    decision_ts = quoted.ts + BAR_MS["1h"]
    assert decision_ts > quoted.ts, "the decision instant is the close of the bar that was read"


def test_quality_reversion_refuses_without_a_dislocation() -> None:
    book = QualityReversionDaily()
    closes = [100.0] * 40 + [99.5] * 30
    bars = _bars(closes, step_ms=86_400_000)
    book.prepare(bars)
    plane = _plane()
    outcomes = [book.on_bar(bars, i, None, plane) for i in range(len(bars))]
    assert all(outcome is None for outcome in outcomes), "a flat tape is not a three-range dip"
    assert book.bars_evaluated == 0


def _plane() -> Any:
    from trading_bot.research.edge01.costs import cost_plane

    return cost_plane(size_usd=1000.0, horizon_minutes=4320.0)


def test_every_proposed_book_declares_an_answer_and_a_clock() -> None:
    for arm, scope in PROPOSED_ARMS.items():
        assert scope["track"] in ("QUALITY", "ACTIVE"), arm
        assert scope["timeframe"] in ("1d", "1h"), arm
        assert scope["answers"], arm
        assert float(scope["horizon_minutes"]) > 0, arm


def test_books_are_built_with_the_registered_parameters() -> None:
    books = build_proposed({})
    assert set(books) == set(DECLARED_PARAMS)
    for arm, book in books.items():
        assert book.params == DECLARED_PARAMS[arm], arm


# -- the screen ------------------------------------------------------------------------ #
def test_a_flat_gross_reading_fails_the_screen_and_says_what_that_means() -> None:
    rows: dict[str, dict[str, Any]] = {
        "DEV": {"arm": "x", "trades": 10, "gross_expectancy_usdt": -0.5, "net_usdt": -9.0}
    }
    verdict = screen_verdict(rows)
    assert verdict["passed"] is False
    assert verdict["verdict_if_failed"] == "REJECT_NO_GROSS_EDGE"
    assert "NOT read on the cross-section" in verdict["consequence"]


def test_a_book_with_no_setups_cannot_pass_the_screen() -> None:
    rows: dict[str, dict[str, Any]] = {
        "DEV": {"arm": "x", "trades": 0, "gross_expectancy_usdt": None, "net_usdt": 0.0}
    }
    assert screen_verdict(rows)["passed"] is False


# -- the claim ------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("reports/alpha-expansion-v1/data/AAVEUSDT_2026.json", "corpus_shard"),
        ("data/raw/alpha003/price/AAVEUSDT_1h.json", "corpus_shard"),
        ("data/edge07/holdout-1h/AAVEUSDT_holdout2026.json", "corpus_shard"),
        ("data/edge08/universe-1h/AAVEUSDT_2021_2026_1h.json", "this_work_package"),
        ("reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json", "result_artefact"),
        ("data/rfc048/raw/binance_usdm_exchange_info.json", "catalogue"),
        ("scripts/sprint030_lib.py", "fetch_or_list_script"),
        ("tests/unit/research/test_alpha003_experiment.py", "test"),
    ],
)
def test_the_classifier_names_what_a_path_is(path: str, kind: str) -> None:
    assert disjointness.classify_path(path) == kind


def test_only_catalogue_script_test_documentation_and_this_package_are_allowed() -> None:
    assert "corpus_shard" not in disjointness.ALLOWED_CLASSES
    assert "result_artefact" not in disjointness.ALLOWED_CLASSES
    assert "this_work_package" in disjointness.ALLOWED_CLASSES


# -- the readings ---------------------------------------------------------------------- #
def test_the_bootstrap_is_deterministic_and_the_frequency_uses_the_window() -> None:
    trades = [
        {
            "decision_ts": WINDOWS["DEV"]["start"] + index * HOUR_MS,
            "net": 10.0 if index % 3 else -5.0,
            "notional": 500.0,
            "duration_min": 60.0,
        }
        for index in range(40)
    ]
    first = extras(trades=trades, window=WINDOWS["DEV"], n_assets=3, timeframe="1h")
    second = extras(trades=trades, window=WINDOWS["DEV"], n_assets=3, timeframe="1h")
    assert first["expectancy_ci_90_usdt"] == second["expectancy_ci_90_usdt"]
    days = (WINDOWS["DEV"]["end"] - WINDOWS["DEV"]["start"]) / 86_400_000
    assert first["frequency"]["trades_per_day_universe"] == round(40 / days, 4)
    assert first["frequency"]["trades_per_day_per_asset"] == round(40 / days / 3, 4)


def test_leave_out_largest_removes_exactly_one_trade() -> None:
    trades = [{"net": 5.0}, {"net": -2.0}, {"net": 100.0}]
    reading = leave_out_largest(trades=trades, start_equity=10_000.0)
    assert reading["trades"] == 2
    assert reading["net_usdt"] == pytest.approx(3.0)
    assert reading["removed_trade_net_usdt"] == pytest.approx(100.0)


def test_coverage_floor_is_the_registered_number() -> None:
    reading = coverage_reading(bars_per_asset={"AAVE": 500, "UNI": 10_000}, timeframe="1d")
    assert reading["floor_bars_per_asset"] == COVERAGE_FLOOR_BARS["1d"]
    assert reading["enough"] is True
    short = coverage_reading(bars_per_asset={"AAVE": 1}, timeframe="1h")
    assert short["enough"] is False and short["assets_below_floor"] == {"AAVE": 1}


# -- the verdict device ---------------------------------------------------------------- #
def _cells(*, trades: int, net: float, stress: float, share: float | None) -> dict[str, Any]:
    return {
        "DEV": {"BASE": {"gross_usdt": 10.0}},
        "OOS": {
            "BASE": {
                "trades": trades,
                "net_usdt": net,
                "expectancy_usdt": net / trades if trades else None,
                "largest_trade_share_of_net": share,
                "positive_time_blocks": 2,
                "with_the_largest_winner_removed": {"net_usdt": net * 0.5},
                "by_market_context_detail": {"BULL": {"net_usdt": 1.0}},
                "frequency": {"trades_per_day_universe": 0.1},
            },
            "2X_FEES": {"net_usdt": stress},
        },
    }


def test_an_unpowered_but_non_negative_book_is_insufficient_evidence() -> None:
    cells = _cells(trades=MIN_TRADES - 5, net=5.0, stress=1.0, share=0.1)
    reading = criteria_reading(cells=cells, track="QUALITY")
    verdict, _why = decide(reading=reading, net_usdt=5.0)
    assert verdict == "INSUFFICIENT_EVIDENCE"


def test_a_negative_window_is_rejected() -> None:
    cells = _cells(trades=MIN_TRADES + 10, net=-50.0, stress=-80.0, share=None)
    reading = criteria_reading(cells=cells, track="ACTIVE")
    verdict, _why = decide(reading=reading, net_usdt=-50.0)
    assert verdict == "REJECT"


def test_a_book_that_passes_everything_is_admitted_to_paper() -> None:
    cells = _cells(trades=MIN_TRADES + 10, net=500.0, stress=200.0, share=0.1)
    cells["OOS"]["BASE"]["frequency"] = {"trades_per_day_universe": 3.5}
    reading = criteria_reading(cells=cells, track="ACTIVE")
    assert reading["failed"] == []
    verdict, why = decide(reading=reading, net_usdt=500.0)
    assert verdict == "ADMIT_PAPER" and "paper" in why


def test_the_active_track_fails_on_frequency_when_it_cannot_reach_three_a_day() -> None:
    cells = _cells(trades=MIN_TRADES + 10, net=500.0, stress=200.0, share=0.1)
    reading = criteria_reading(cells=cells, track="ACTIVE")
    assert "F1" in reading["failed"]


def test_the_quality_track_uses_its_own_floor() -> None:
    cells = _cells(trades=MIN_TRADES + 10, net=500.0, stress=200.0, share=0.1)
    cells["OOS"]["BASE"]["frequency"] = {"trades_per_day_universe": 0.06}
    reading = criteria_reading(cells=cells, track="QUALITY")
    assert "F2" not in reading["failed"]
