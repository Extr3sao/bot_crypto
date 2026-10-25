"""ARP-009 §8/§25/§30 — PIT + governance tests for EXP-ARP-021.

Covers the mandated failure surfaces for the frozen cross-sectional risk-adjusted
relative-strength rotation (``H-XSEC-RISKADJ-RELSTR-001``):

* future bars are never referenced by the scorer;
* a missing formation / skip / volatility bar excludes the symbol (no fill);
* a non-positive price or a zero-volatility window fails closed;
* ties rank deterministically (``(-score, symbol)``);
* selection fails closed below ``min_members``;
* the simulation fills at the **next open** and is deterministic;
* the frozen contract validates ``PASS``; split mutation is refused; the forward
  holdout stays ``UNTOUCHED`` (OOS firewall).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified import xsec_riskadj as R  # noqa: E402
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

START = 1_546_300_800_000  # 2019-01-01 UTC
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-021"
FROZEN_SPLIT = SplitDefinition(
    "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2026-03-01", "2027-03-01"
)


def _bars(symbol: str, closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(
            symbol=symbol,
            timestamp=START + i * MS_PER_DAY,
            open=c,
            high=c,
            low=c,
            close=c,
            volume=10.0,
            quote_volume=5_000_000.0,
        )
        for i, c in enumerate(closes)
    ]


def _index(bars: list[DailyBar]) -> dict[int, DailyBar]:
    return {b.timestamp: b for b in bars}


def _ramp(n: int, base: float = 100.0, step: float = 0.5) -> list[float]:
    return [base + i * step + ((i * 7) % 5) for i in range(n)]


DECISION_DAY = START + 150 * MS_PER_DAY


def test_future_bar_is_never_referenced() -> None:
    bars = _bars("A", _ramp(160))
    base = R.score_of(_index(bars), DECISION_DAY, R.riskadj_config())
    assert base is not None
    poisoned = [
        *bars,
        DailyBar("A", DECISION_DAY + 10 * MS_PER_DAY, 1e9, 1e9, 1e9, 1e9, 1.0, 1.0),
    ]
    assert R.score_of(_index(poisoned), DECISION_DAY, R.riskadj_config()) == base


def test_missing_skip_bar_excludes_symbol() -> None:
    bars = _bars("A", _ramp(160))
    t_skip = DECISION_DAY - 7 * MS_PER_DAY
    trimmed = [b for b in bars if b.timestamp != t_skip]
    assert R.score_of(_index(trimmed), DECISION_DAY, R.riskadj_config()) is None


def test_missing_volatility_bar_excludes_symbol() -> None:
    bars = _bars("A", _ramp(160))
    t_skip = DECISION_DAY - 7 * MS_PER_DAY
    victim = t_skip - 5 * MS_PER_DAY
    trimmed = [b for b in bars if b.timestamp != victim]
    assert R.score_of(_index(trimmed), DECISION_DAY, R.riskadj_config()) is None


def test_non_positive_price_excludes_symbol() -> None:
    bars = _bars("A", _ramp(160))
    t_form = DECISION_DAY - 97 * MS_PER_DAY
    idx = _index(bars)
    bar = idx[t_form]
    idx[t_form] = DailyBar(bar.symbol, bar.timestamp, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0)
    assert R.score_of(idx, DECISION_DAY, R.riskadj_config()) is None


def test_zero_volatility_fails_closed_unless_raw_control() -> None:
    flat = [100.0] * 160
    bars = _bars("A", flat)
    assert R.score_of(_index(bars), DECISION_DAY, R.riskadj_config()) is None
    raw = R.score_of(_index(bars), DECISION_DAY, R.riskadj_config(risk_adjusted=False))
    assert raw == 0.0  # flat price: formation return 0, control still returns it


def test_select_top_fails_closed_below_min_members() -> None:
    cfg = R.riskadj_config()
    assert R.select_top({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}, cfg) == []
    assert len(R.select_top({s: float(i) for i, s in enumerate("ABCDEF")}, cfg)) == 5


def test_select_top_tie_breaks_deterministically() -> None:
    cfg = R.riskadj_config()
    scored = {s: 1.0 for s in ("E", "D", "C", "B", "A", "F")}
    assert R.select_top(scored, cfg) == ["A", "B", "C", "D", "E"]


def test_compute_scores_excludes_short_history() -> None:
    corpus = {"A": _bars("A", _ramp(160)), "B": _bars("B", _ramp(50))}
    scored = R.compute_scores(corpus, DECISION_DAY, R.riskadj_config())
    assert "A" in scored and "B" not in scored


def _corpus(n_symbols: int = 6, n_bars: int = 160) -> dict[str, list[DailyBar]]:
    return {
        f"S{k}": _bars(f"S{k}", [100.0 + k * 10.0 + i * (0.5 + 0.05 * k) + ((i * 7 + k) % 5)
                                  for i in range(n_bars)])
        for k in range(n_symbols)
    }


def _run(corpus: dict[str, list[DailyBar]]) -> list[DailyBar]:
    trades, _ = R.simulate_riskadj_xsec(
        corpus,
        {s: START for s in corpus},
        "test-fingerprint",
        config=R.riskadj_config(),
        cost_bps_rt=23.559,
    )
    assert trades, "synthetic corpus must produce at least one position"
    return trades  # type: ignore[return-value]


def test_simulation_fills_at_next_open() -> None:
    corpus = _corpus()
    trades = _run(corpus)
    index = {s: _index(bars) for s, bars in corpus.items()}
    for t in trades:
        bar = index[t.symbol].get(t.entry_ts)
        assert bar is not None, "entry must land on a real next bar"
        assert t.entry == pytest.approx(bar.open), "must fill at the next open, not the close"


def test_simulation_is_deterministic() -> None:
    corpus = _corpus()
    a = [t.as_dict() for t in _run(corpus)]
    b = [t.as_dict() for t in _run(corpus)]
    assert a == b


def test_no_trade_before_listing() -> None:
    corpus = _corpus()
    listing = {s: START + 5 * MS_PER_DAY for s in corpus}  # late listing
    trades, _ = R.simulate_riskadj_xsec(
        corpus, listing, "test", config=R.riskadj_config(), cost_bps_rt=23.559
    )
    for t in trades:
        assert t.entry_ts >= listing[t.symbol]


# ------------------------------------------------------------------ governance


def _frozen_contract() -> ExperimentContract:
    manifest = json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    spec_block = dict(manifest["spec_contract"])
    split_dict = FROZEN_SPLIT.to_dict()
    spec_view = {**spec_block, "split_contract": split_dict}
    manifest_view = {**spec_block, "split_contract": split_dict}
    cfg = R.riskadj_config()
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
        spec=spec_view,
        manifest=manifest_view,
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


def test_frozen_manifest_matches_corpus_digest() -> None:
    manifest = json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["spec_contract"]["dataset_fingerprint"] == D.corpus_digest()


def test_split_mutation_is_refused() -> None:
    reg = ImmutableSplitRegistry()
    reg.register("EXP-ARP-021", FROZEN_SPLIT)
    with pytest.raises(SplitMutationError):
        reg.register("EXP-ARP-021", SplitDefinition(
            "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2025-07-01", "2026-03-01"
        ))


def test_forward_holdout_stays_untouched() -> None:
    reg = HoldoutRegistry()
    reg.register(Holdout(
        holdout_id="HOLDOUT-ARP-019-FORWARD",
        start="2026-03-01",
        end="2027-03-01",
        assets=("DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",),
        dataset_hash=D.corpus_digest(),
        forward_only=True,
    ))
    assert reg.status("HOLDOUT-ARP-019-FORWARD") is HoldoutStatus.UNTOUCHED
    reg.assert_untouched("HOLDOUT-ARP-019-FORWARD")
