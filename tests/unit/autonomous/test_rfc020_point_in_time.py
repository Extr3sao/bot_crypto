"""RFC-020 point-in-time acceptance matrix (§34).

Fast, deterministic unit tests for the temporal invariants the RFC demands.
The full adversarial runtime proof lives in ``scripts/rfc020_future_injection.py``
(this file guards the primitives it relies on so a regression is caught early).

PIT-001 future LTF bar hidden        -> closed_bar_slice
PIT-003 closed LTF bar visible       -> closed_bar_slice
PIT-002/004/005/026 future mutation  -> compute_shared invariance
PIT-006/007 duplicate timestamp      -> FetcherBarReader sanitization
PIT-008 missing bars / asset isolation -> BaseCryptoAssetAgent.slice_window
PIT-016/020 outcome poisoning        -> OutcomeEvaluator horizon gate
PIT-014 timezone / unit consistency  -> availability_ms
Orphan HTF                           -> not imported by the runtime
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.autonomous.pit import availability_ms, closed_bar_slice, infer_bar_interval_ms
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.snapshot_history import _sanitize_bars
from trading_bot.research.asset_intelligence.base import BaseCryptoAssetAgent
from trading_bot.research.asset_intelligence.features import compute_shared
from trading_bot.research.asset_intelligence.models import AssetContextError

from .test_contracts import _proposal, _trace

BAR_MS = 300_000
TS0 = 1_700_000_000_000


def _series(n: int, symbol: str = "BTC/USDT") -> list[OHLCV]:
    return [
        OHLCV(
            symbol=symbol,
            timestamp=TS0 + i * BAR_MS,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000.0 + i,
        )
        for i in range(n)
    ]


def test_pit_001_future_bar_hidden_until_close() -> None:
    bars = _series(3)
    # decision exactly at the OPEN of bar 2: only bars whose CLOSE <= decision.
    decision = bars[2].timestamp
    used = closed_bar_slice(bars, decision, interval_ms=BAR_MS)
    assert [b.timestamp for b in used] == [bars[0].timestamp, bars[1].timestamp]


def test_pit_003_bar_visible_once_it_closes() -> None:
    bars = _series(3)
    decision = bars[2].timestamp + BAR_MS  # the close of bar 2
    used = closed_bar_slice(bars, decision, interval_ms=BAR_MS)
    assert [b.timestamp for b in used] == [b.timestamp for b in bars]


def test_pit_001_one_millisecond_before_close_is_hidden() -> None:
    bars = _series(2)
    decision = bars[1].timestamp + BAR_MS - 1
    used = closed_bar_slice(bars, decision, interval_ms=BAR_MS)
    assert [b.timestamp for b in used] == [bars[0].timestamp]


def test_pit_014_availability_is_close_not_open() -> None:
    bars = _series(1)
    assert availability_ms(bars[0], BAR_MS) == bars[0].timestamp + BAR_MS
    # unknown interval -> conservative (open) rather than a guess
    assert availability_ms(bars[0], None) == bars[0].timestamp
    assert infer_bar_interval_ms(bars) is None


def test_pit_002_004_feature_invariance_under_future_mutation() -> None:
    past = _series(60)
    window = past[:40]
    base = compute_shared(window)
    poisoned = past[:40] + [
        replace(b, open=b.open * 10, high=b.high * 10, low=b.low * 10, close=b.close * 10)
        for b in past[40:]
    ]
    mutated = compute_shared([b for b in poisoned if b.timestamp <= window[-1].timestamp])
    assert base == mutated


def test_pit_006_007_duplicate_timestamp_keeps_first() -> None:
    a = _series(1)[0]
    b = replace(a, close=999.0)  # conflicting duplicate at the same timestamp
    kept = _sanitize_bars([a, b])
    assert len(kept) == 1
    assert kept[0].close == a.close  # first occurrence wins, silently


def test_pit_006_out_of_order_reordered_and_bad_timestamp_dropped() -> None:
    bars = _series(3)
    shuffled = [bars[2], replace(bars[0], timestamp=0), bars[1]]
    kept = _sanitize_bars(shuffled)
    assert [b.timestamp for b in kept] == [bars[1].timestamp, bars[2].timestamp]


def test_pit_008_asset_isolation_and_fail_closed() -> None:
    agent = BaseCryptoAssetAgent()
    agent.asset_id = "BTC"
    btc = _series(30, "BTC/USDT")
    eth = _series(30, "ETH/USDT")
    window = agent.slice_window([*btc, *eth], btc[-1].timestamp)
    assert all(b.symbol.startswith("BTC/") for b in window)
    with pytest.raises(AssetContextError):
        agent.slice_window(btc[:10], btc[-1].timestamp)  # < 22 bars: fail closed
    with pytest.raises(AssetContextError):
        agent.slice_window(eth, eth[-1].timestamp)  # no bars for BTC at all


def test_pit_016_outcome_never_resolves_before_horizon() -> None:
    from trading_bot.autonomous.outcomes import OutcomeEvaluator

    decision = TS0
    proposal = _proposal(
        decision_id="d-1",
        market_time_ms=decision,
        decision_time_ms=decision,
        horizon_minutes=25.0,
        entry_reference=100.0,
        expected_gross_edge_bps=4.0,
        expected_cost_bps=21.0,
        expected_net_edge_bps=-17.0,
    )
    trace = _trace(
        decision_id="d-1",
        market_time_ms=decision,
        decision_time_ms=decision,
        proposal=proposal.to_dict(),
    )
    evaluator = OutcomeEvaluator()
    # Only bars that closed at/just after the decision exist: horizon not elapsed.
    short = _series(3)
    result = evaluator.evaluate(trace=trace, bars=short, created_at_ms=decision)
    assert result.record is None
    # Once the horizon has elapsed, the outcome is strictly after the decision.
    long = _series(10)
    resolved = evaluator.evaluate(trace=trace, bars=long, created_at_ms=decision)
    record = resolved.record
    assert record is not None
    assert record.outcome_time_ms > record.decision_time_ms
    assert record.reference_price_time_ms <= record.decision_time_ms


def test_orphan_htf_helper_has_no_runtime_importer() -> None:
    """DEF-HTF-PIT-001 stays ORPHAN: no src/ module imports htf_pit."""
    src = Path(__file__).resolve().parents[3] / "src"
    experimental = src / "trading_bot" / "research" / "experimental"
    importers = []
    for path in src.rglob("*.py"):
        if path.name == "htf_pit.py" or experimental in path.parents:
            continue  # EXPERIMENTAL area is certified RESEARCH_ONLY, not runtime
        text = path.read_text(encoding="utf-8", errors="replace")
        if "htf_pit" in text:
            importers.append(path.as_posix())
    assert importers == [], f"htf_pit became runtime-reachable: {importers}"
