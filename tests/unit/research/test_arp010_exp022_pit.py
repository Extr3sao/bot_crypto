"""ARP-010 §31 — data authority, intermarket PIT, calendar-sync, contract,
holdout-firewall, split-immutability and determinism tests for EXP-ARP-022.

The frozen mechanism (``H-INTERMARKET-RISKAPP-001``) decides on the ETH/BTC ratio
versus its SMA50 and rotates between BTC and an equal-weight alt basket. The
mandated failure surfaces:

* the ratio / SMA read closed bars only (future bars never leak);
* a missing ratio or SMA bar fails closed (``NO_SIGNAL``);
* the frozen inputs are required — their absence raises ``IntermarketError``
  rather than substituting a proxy;
* the crypto 24/7 calendar needs no weekend/holiday alignment, but a missing
  session / duplicate / stale symbol is excluded;
* the debut contract validates ``PASS``; split mutation is refused; the forward
  holdout stays ``UNTOUCHED``;
* the rotation is deterministic and fills at the next open.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified import intermarket as IM  # noqa: E402
from trading_bot.research.diversified.data import MS_PER_DAY, DailyBar  # noqa: E402
from trading_bot.research.diversified.intermarket import _exact_ratio  # noqa: E402
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
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-022"
FROZEN_SPLIT = SplitDefinition(
    "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2026-03-01", "2027-03-01"
)


def _bars(symbol: str, closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(symbol, START + i * MS_PER_DAY, c, c, c, c, 10.0, 5_000_000.0)
        for i, c in enumerate(closes)
    ]


def _corpus(n_bars: int = 160) -> dict[str, list[DailyBar]]:
    btc = [100.0 + i * 0.3 for i in range(n_bars)]
    eth = [btc[i] * (0.05 + 0.02 * math.sin(i / 9)) for i in range(n_bars)]
    corpus = {IM.BTC: _bars(IM.BTC, btc), IM.ETH: _bars(IM.ETH, eth)}
    for k in range(6):
        closes = [50.0 + k * 5 + i * 0.2 + 3 * math.sin(i / (5 + k)) for i in range(n_bars)]
        corpus[f"S{k}"] = _bars(f"S{k}", closes)
    return corpus


def _index(bars: list[DailyBar]) -> dict[int, DailyBar]:
    return {b.timestamp: b for b in bars}


DAY = START + 150 * MS_PER_DAY


# ------------------------------------------------------------------ PIT / signal


def test_risk_on_state_insufficient_window_fails_closed() -> None:
    assert IM.risk_on_state([0.1] * 49, 50) is None


def test_risk_on_state_compares_latest_to_window_mean() -> None:
    rising = [0.05] * 49 + [0.20]
    falling = [0.05] * 49 + [0.01]
    assert IM.risk_on_state(rising, 50) is True
    assert IM.risk_on_state(falling, 50) is False


def test_exact_ratio_ignores_future_bars() -> None:
    corpus = _corpus()
    btc, eth = _index(corpus[IM.BTC]), _index(corpus[IM.ETH])
    base = _exact_ratio(btc, eth, DAY, 50)
    assert base is not None
    poisoned_btc = dict(btc)
    poisoned_btc[DAY + 5 * MS_PER_DAY] = DailyBar(IM.BTC, DAY + 5 * MS_PER_DAY, 1, 1, 1, 1e9, 1, 1)
    assert _exact_ratio(poisoned_btc, eth, DAY, 50) == base


def test_exact_ratio_missing_bar_returns_none() -> None:
    corpus = _corpus()
    btc, eth = _index(corpus[IM.BTC]), _index(corpus[IM.ETH])
    del eth[DAY - 10 * MS_PER_DAY]  # a gap inside the ratio window
    assert _exact_ratio(btc, eth, DAY, 50) is None


def test_missing_frozen_input_raises_instead_of_proxying() -> None:
    corpus = {IM.BTC: _bars(IM.BTC, [100.0] * 160)}  # ETH absent
    with pytest.raises(IM.IntermarketError):
        IM.simulate_intermarket_rotation(
            corpus, {IM.BTC: START}, "fp", config=IM.intermarket_config(), cost_bps_rt=23.559
        )


# ------------------------------------------------------------------ calendar / data


def test_gapped_eth_produces_no_signal_days() -> None:
    corpus = _corpus()
    # remove a mid-board ETH bar so some decisions cannot form the ratio window
    corpus[IM.ETH] = [b for b in corpus[IM.ETH] if b.timestamp != START + 120 * MS_PER_DAY]
    _tr, _st, audit = IM.simulate_intermarket_rotation(
        corpus,
        {s: START for s in corpus},
        "fp",
        config=IM.intermarket_config(),
        cost_bps_rt=23.559,
    )
    no_signal = audit["no_signal_days"]
    assert isinstance(no_signal, int) and no_signal >= 1


def test_crypto_calendar_needs_no_weekend_alignment() -> None:
    # every calendar day is a valid trading day for both crypto legs
    corpus = _corpus()
    btc = corpus[IM.BTC]
    deltas = {btc[i + 1].timestamp - btc[i].timestamp for i in range(len(btc) - 1)}
    assert deltas == {MS_PER_DAY}


# ------------------------------------------------------------------ simulation


def test_rotation_fills_at_next_open() -> None:
    corpus = _corpus()
    trades, _states, _audit = IM.simulate_intermarket_rotation(
        corpus,
        {s: START for s in corpus},
        "fp",
        config=IM.intermarket_config(),
        cost_bps_rt=23.559,
    )
    assert trades, "synthetic corpus must trade"
    index = {s: _index(bars) for s, bars in corpus.items()}
    for t in trades:
        bar = index[t.symbol].get(t.entry_ts)
        assert bar is not None
        assert t.entry == pytest.approx(bar.open)


def test_rotation_is_deterministic() -> None:
    corpus = _corpus()
    args = (corpus, {s: START for s in corpus}, "fp")
    a = [
        t.as_dict()
        for t in IM.simulate_intermarket_rotation(
            *args, config=IM.intermarket_config(), cost_bps_rt=23.559
        )[0]
    ]
    b = [
        t.as_dict()
        for t in IM.simulate_intermarket_rotation(
            *args, config=IM.intermarket_config(), cost_bps_rt=23.559
        )[0]
    ]
    assert a == b


def test_one_leg_at_a_time() -> None:
    corpus = _corpus()
    trades, _st, _audit = IM.simulate_intermarket_rotation(
        corpus,
        {s: START for s in corpus},
        "fp",
        config=IM.intermarket_config(),
        cost_bps_rt=23.559,
    )
    # a BTC position episode must never overlap an alt episode in wall-clock
    btc_episodes: list[tuple[int, int]] = [
        (int(t.entry_ts), int(t.exit_ts)) for t in trades if t.symbol == IM.BTC
    ]
    alt_episodes: list[tuple[int, int]] = [
        (int(t.entry_ts), int(t.exit_ts)) for t in trades if t.symbol != IM.BTC
    ]
    for bs, be in btc_episodes:
        for a_s, a_e in alt_episodes:
            assert be <= a_s or a_e <= bs


# ------------------------------------------------------------------ governance


def _frozen_contract() -> ExperimentContract:
    manifest = json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    spec_block = dict(manifest["spec_contract"])
    split_dict = FROZEN_SPLIT.to_dict()
    cfg = IM.intermarket_config()
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
    reg.register("EXP-ARP-022", FROZEN_SPLIT)
    with pytest.raises(SplitMutationError):
        reg.register(
            "EXP-ARP-022",
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
