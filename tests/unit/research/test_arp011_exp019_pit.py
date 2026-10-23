"""ARP-011 §30 — PIT-breadth, dynamic universe, contract, firewall, split,
determinism and drawdown-semantics tests for EXP-ARP-019.

Mandated surfaces:

* drawdown metric semantics: ``max_drawdown_bps`` is a peak-to-trough of the
  cumulative **non-compounding PnL** divided by the fixed notional, and it can
  exceed 10000 bps (registered metric defect);
* breadth reads closed bars only (future bars never leak) and fails closed on a
  missing SMA/bar;
* the dynamic universe excludes not-yet-listed assets;
* the frozen contract validates ``PASS``; split mutation is refused; the forward
  holdout stays ``UNTOUCHED``; the simulation is deterministic and fills at the
  next open.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery.metrics import max_drawdown_bps  # noqa: E402
from trading_bot.research.diversified import breadth as B  # noqa: E402
from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified.data import MS_PER_DAY, DailyBar  # noqa: E402
from trading_bot.research.governance import (  # noqa: E402
    ExperimentContract,
    ExperimentContractValidator,
    Holdout,
    HoldoutRegistry,
    HoldoutStatus,
    ImmutableSplitRegistry,
    SplitDefinition,
    SplitMutationError,
)

START = 1_546_300_800_000
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-019"
FROZEN_SPLIT = SplitDefinition(
    "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2026-03-01", "2027-03-01"
)


def _bars(symbol: str, closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(symbol, START + i * MS_PER_DAY, c, c, c, c, 10.0, 5_000_000.0)
        for i, c in enumerate(closes)
    ]


def _corpus(n_bars: int = 130, n_symbols: int = 8) -> dict[str, list[DailyBar]]:
    corpus: dict[str, list[DailyBar]] = {}
    for k in range(n_symbols):
        closes = [100.0 + k * 10 + i * (0.4 + 0.1 * k) + ((i * 5 + k) % 4) for i in range(n_bars)]
        corpus[f"S{k}"] = _bars(f"S{k}", closes)
    return corpus


def _idx(bars: list[DailyBar]) -> dict[int, DailyBar]:
    return {b.timestamp: b for b in bars}


DAY = START + 100 * MS_PER_DAY


# ------------------------------------------------------------- drawdown semantics


def test_drawdown_is_pnl_drawdown_not_equity_drawdown() -> None:
    # a $600 cumulative loss on a fixed $500 notional = 12000 bps, i.e. >100%
    assert max_drawdown_bps([-600.0]) == pytest.approx(12_000.0)
    # cumulative losses compound on the PnL curve: -10,-210,-810 -> 810/500 = 16200 bps
    assert max_drawdown_bps([-10.0, -200.0, -600.0]) == pytest.approx(16_200.0)
    # therefore the field cannot be equity drawdown (that would cap at 10000 bps)
    assert max_drawdown_bps([-600.0]) > 10_000.0


def test_drawdown_uses_peak_to_trough_of_cumulative_pnl() -> None:
    # up to +100 then down to -100 -> peak-to-trough swing of $200 = 4000 bps
    assert max_drawdown_bps([100.0, -200.0]) == pytest.approx(4_000.0)


# ------------------------------------------------------------------- breadth PIT


def test_breadth_ignores_future_bars() -> None:
    corpus = _corpus()
    index = {s: _idx(bars) for s, bars in corpus.items()}
    eligible = sorted(corpus)
    base = B.breadth_of_day(index, DAY, eligible, 50)
    poison = dict(index)
    poison["S0"] = dict(index["S0"])
    poison["S0"][DAY + 5 * MS_PER_DAY] = DailyBar("S0", DAY + 5 * MS_PER_DAY, 1, 1, 1, 1e9, 1, 1)
    assert B.breadth_of_day(poison, DAY, eligible, 50) == base


def test_breadth_excludes_asset_with_missing_sma_bar() -> None:
    corpus = _corpus()
    index = {s: _idx(bars) for s, bars in corpus.items()}
    eligible = sorted(corpus)
    _pos, ev = B.breadth_of_day(index, DAY, eligible, 50)
    assert ev == len(eligible)
    index["S0"] = {ts: b for ts, b in index["S0"].items() if ts != DAY - 5 * MS_PER_DAY}
    _pos2, ev2 = B.breadth_of_day(index, DAY, eligible, 50)
    assert ev2 == ev - 1


# --------------------------------------------------------------- dynamic universe


def test_no_trade_before_listing() -> None:
    corpus = _corpus()
    listing = {s: START for s in corpus}
    listing["S0"] = START + 60 * MS_PER_DAY  # late listing
    trades, _r, _a = B.simulate_breadth_regime(
        corpus, listing, "fp", config=B.breadth_config(), cost_bps_rt=23.559
    )
    for t in trades:
        assert t.entry_ts >= listing[t.symbol]


# ------------------------------------------------------------------- simulation


def test_breadth_rotation_fills_at_next_open() -> None:
    corpus = _corpus()
    trades, _r, _a = B.simulate_breadth_regime(
        corpus, {s: START for s in corpus}, "fp", config=B.breadth_config(), cost_bps_rt=23.559
    )
    assert trades
    index = {s: _idx(bars) for s, bars in corpus.items()}
    for t in trades:
        bar = index[t.symbol].get(t.entry_ts)
        assert bar is not None
        assert t.entry == pytest.approx(bar.open)


def test_always_long_control_enters_immediately() -> None:
    corpus = _corpus()
    trades, _r, _a = B.simulate_breadth_regime(
        corpus,
        {s: START for s in corpus},
        "fp",
        config=B.breadth_config(entry_breadth=0.0, exit_breadth=-1.0),
        cost_bps_rt=23.559,
    )
    assert trades


def test_breadth_rotation_is_deterministic() -> None:
    corpus = _corpus()
    args = (corpus, {s: START for s in corpus}, "fp")
    a = [
        t.as_dict()
        for t in B.simulate_breadth_regime(*args, config=B.breadth_config(), cost_bps_rt=23.559)[0]
    ]
    b = [
        t.as_dict()
        for t in B.simulate_breadth_regime(*args, config=B.breadth_config(), cost_bps_rt=23.559)[0]
    ]
    assert a == b


# ------------------------------------------------------------------- governance


def _frozen_contract() -> ExperimentContract:
    manifest = json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    spec_block = dict(manifest["spec_contract"])
    split_dict = FROZEN_SPLIT.to_dict()
    cfg = B.breadth_config()
    impl = {
        "experiment_id": manifest["experiment_id"],
        "strategy_id": manifest["strategy_id"],
        "timeframe": manifest["timeframe"],
        "assets": manifest["assets"],
        "lookback_days": cfg.lookback_days,
        "max_hold_days": cfg.max_hold_days,
        "entry_rule": spec_block["entry_rule"],
        "exit_rule": spec_block["exit_rule"],
        "dataset_fingerprint": D.corpus_digest(),
        "cost_model_version": manifest["cost_model"]["version"],
        "cost_scenario": manifest["cost_model"]["scenario"],
        "split_contract": split_dict,
    }
    return ExperimentContract(
        experiment_id=manifest["experiment_id"],
        spec={**spec_block, "split_contract": split_dict},
        manifest={**spec_block, "split_contract": split_dict},
        implementation_config=impl,
        split_definition=split_dict,
        cost_model={
            "cost_round_trip_bps": 23.559016994374947,
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
        },
    )


def test_frozen_contract_passes() -> None:
    result = ExperimentContractValidator().validate(_frozen_contract())
    assert result.status == "PASS"
    assert result.mismatches == ()


def test_split_mutation_is_refused() -> None:
    reg = ImmutableSplitRegistry()
    reg.register("EXP-ARP-019", FROZEN_SPLIT)
    with pytest.raises(SplitMutationError):
        reg.register(
            "EXP-ARP-019",
            SplitDefinition(
                "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2025-07-01", "2026-03-01"
            ),
        )


def test_forward_holdout_stays_untouched() -> None:
    reg = HoldoutRegistry()
    reg.register(
        Holdout(
            holdout_id="HOLDOUT-ARP-019-FORWARD",
            start="2026-03-01",
            end="2027-03-01",
            assets=("DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",),
            dataset_hash=D.corpus_digest(),
            forward_only=True,
        )
    )
    assert reg.status("HOLDOUT-ARP-019-FORWARD") is HoldoutStatus.UNTOUCHED
    reg.assert_untouched("HOLDOUT-ARP-019-FORWARD")
