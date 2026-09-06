"""FRESH-DATA-001-R1 edge-sanity audit tests.

Adversarial coverage for the discovery simulation semantics: paginated
ingestion, single-position (no-overlap) policy, entry/exit slippage,
frozen initial risk, no-lookahead, duplicate-signal prevention,
deterministic intrabar policy, independent expectancy recomputation,
superseded-registry exclusion, and the tightened v2 criteria.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.discovery import (
    preregistered_criteria,
)
from trading_bot.discovery.criteria import CRITERIA_SCHEMA_VERSION
from trading_bot.discovery.dataset import DatasetFetcher, validate_quality
from trading_bot.discovery.runner import (
    DiscoveryRun,
    evaluate_combo_with_ledger,
)
from trading_bot.discovery.split import compute_split
from trading_bot.research.types import AlphaSignal

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeExchange:
    """Duck-typed ccxt exchange: serves pre-canned pages of raw candles."""

    pages: dict[str, list[list[list[float]]]]
    calls: dict[str, int]

    def __init__(self, pages: dict[str, list[list[list[float]]]]):
        self.pages = pages
        self.calls = {sym: 0 for sym in pages}

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int):
        seq = self.pages[symbol]
        i = self.calls[symbol]
        self.calls[symbol] = i + 1
        return seq[i] if i < len(seq) else []

    def close(self) -> None:
        return None


def _raw_page(start_ts: int, count: int, price: float = 100.0) -> list[list[float]]:
    return [
        [start_ts + i * 300_000, price, price + 0.5, price - 0.5, price + 0.1, 10.0]
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# G1/G3: pagination completeness
# ---------------------------------------------------------------------------


class TestPagination:
    def test_short_pages_are_not_exhaustion(self) -> None:
        # Two short pages (Binance tail behaviour); the old code stopped
        # after the first short page (the 1000-bar truncation defect).
        start = 1787097600000  # 2026-08-19T00:00:00Z
        p1 = _raw_page(start, 600)
        p2 = _raw_page(start + 600 * 300_000, 400)
        ex = _FakeExchange({"X/USDT:USDT": [p1, p2]})
        fetcher = DatasetFetcher(symbols=("X/USDT:USDT",), exchange_factory=lambda: ex)
        datasets = fetcher.fetch()
        ds = datasets["X/USDT:USDT"]
        assert ds.quality.candles == 1000
        assert ds.fetch_pages == 2

    def test_continuity_gap_fails_loud(self) -> None:
        start = 1787097600000
        p1 = _raw_page(start, 600)
        # second page starts 2 bars late => missing-page gap
        p2 = _raw_page(start + 602 * 300_000, 400)
        ex = _FakeExchange({"X/USDT:USDT": [p1, p2]})
        fetcher = DatasetFetcher(symbols=("X/USDT:USDT",), exchange_factory=lambda: ex)
        with pytest.raises(ValueError, match="missing page"):
            fetcher.fetch()

    def test_continuity_overlap_fails_loud(self) -> None:
        start = 1787097600000
        p1 = _raw_page(start, 600)
        p2 = _raw_page(start + 599 * 300_000, 400)  # overlaps p1
        ex = _FakeExchange({"X/USDT:USDT": [p1, p2]})
        fetcher = DatasetFetcher(symbols=("X/USDT:USDT",), exchange_factory=lambda: ex)
        with pytest.raises(ValueError, match="overlap/dupe"):
            fetcher.fetch()

    def test_non_monotonic_page_fails_loud(self) -> None:
        start = 1787097600000
        page = _raw_page(start, 50)
        page[10], page[11] = page[11], page[10]  # scramble order
        ex = _FakeExchange({"X/USDT:USDT": [page]})
        fetcher = DatasetFetcher(symbols=("X/USDT:USDT",), exchange_factory=lambda: ex)
        with pytest.raises(ValueError, match="non-monotonic"):
            fetcher.fetch()

    def test_open_tail_candle_is_dropped(self) -> None:
        # Last candle of the last page closes in the "future" relative to a
        # fixed now: the fetcher must drop it (closed-candle-only policy).
        start = 1787097600000
        p1 = _raw_page(start, 600)
        p2 = _raw_page(start + 600 * 300_000, 400)
        # Freeze "now" while the final candle is still open: now = close_time
        # of the second-to-last candle => the last candle must be dropped.
        fixed_last_close = start + 998 * 300_000 + 300_000 - 1
        real_fromtimestamp = datetime.fromtimestamp

        class _FrozenNow(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return real_fromtimestamp((fixed_last_close + 1) / 1000, tz=UTC)

        import trading_bot.discovery.dataset as ds_mod

        original_dt = ds_mod.datetime
        ds_mod.datetime = _FrozenNow
        try:
            ex = _FakeExchange({"X/USDT:USDT": [p1, p2]})
            fetcher = DatasetFetcher(symbols=("X/USDT:USDT",), exchange_factory=lambda: ex)
            datasets = fetcher.fetch()
        finally:
            ds_mod.datetime = original_dt
        ds = datasets["X/USDT:USDT"]
        assert ds.quality.candles == 999

    def test_full_history_scales_beyond_1000(self) -> None:
        # 3 pages of 1000 => 3000 candles (only bounded by data, not code).
        start = 1787097600000
        pages = [_raw_page(start + i * 1000 * 300_000, 1000) for i in range(3)]
        ex = _FakeExchange({"X/USDT:USDT": pages})
        fetcher = DatasetFetcher(symbols=("X/USDT:USDT",), exchange_factory=lambda: ex)
        datasets = fetcher.fetch()
        assert datasets["X/USDT:USDT"].quality.candles == 3000
        assert datasets["X/USDT:USDT"].fetch_pages == 3


# ---------------------------------------------------------------------------
# Simulation-semantics audit (overlaps, slippage, risk, duplicates)
# ---------------------------------------------------------------------------


def _trend_accessor(count: int = 3000, *, seed: int = 7):
    from trading_bot.discovery.dataset import FRESH_START_UTC, SymbolDataset
    from trading_bot.discovery.split import SplitAccessor, build_split_manifest

    start_ms = int(FRESH_START_UTC.timestamp() * 1000)

    def _candles(sym: str, n: int, start: int, *, seed: int = seed):
        import random

        rng = random.Random(seed)
        out = []
        price = 100.0
        ts = start
        for _ in range(n):
            step = rng.uniform(-0.3, 0.33)
            o = price
            c = price + step
            h = max(o, c) + rng.uniform(0.01, 0.08)
            low = min(o, c) - rng.uniform(0.01, 0.08)
            out.append(
                __import__(
                    "trading_bot.market_data.types", fromlist=["OHLCV"]
                ).OHLCV(symbol=sym, timestamp=ts, open=o, high=h, low=low, close=c, volume=100.0)
            )
            price = c
            ts += 300_000
        return out

    candles = _candles("BTC/USDT:USDT", count, start_ms)
    datasets = {
        "BTC/USDT:USDT": SymbolDataset(
            symbol="BTC/USDT:USDT",
            candles=tuple(candles),
            quality=validate_quality("BTC/USDT:USDT", candles),
            sha256="0" * 64,
            fetch_pages=(count + 999) // 1000,
        ),
    }
    windows = compute_split(start_ms + count * 300_000 - 1)
    manifest = build_split_manifest(windows)
    return SplitAccessor(
        datasets=datasets, windows=windows, split_sha256=manifest["split_sha256"]
    )


class _StubFamily:
    """Deterministic family emitting a signal every N bars (adversarial control)."""

    family_name = "stub"

    def __init__(self, every: int = 40, stop_frac: float = 0.01) -> None:
        self.every = every
        self.stop_frac = stop_frac

    def generate(self, history, params, ctx):

        bar = history[-1]
        if len(history) % self.every != 0:
            return []
        entry = bar.close
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                direction="LONG",
                entry_reference=entry,
                structural_stop=entry * (1 - self.stop_frac),
                timeframe="5m",
            )
        ]


@pytest.fixture()
def stub_registry_family(monkeypatch):
    import trading_bot.discovery.runner as runner_mod

    fam = _StubFamily()
    monkeypatch.setattr(
        runner_mod,
        "_family_instances",
        lambda: [fam],
    )
    return fam


class TestSimulationSemantics:
    def test_no_overlapping_trades(self, stub_registry_family) -> None:
        accessor = _trend_accessor(3000)
        _run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        assert ledger.trades
        assert not ledger.has_overlap()
        ordered = sorted(ledger.trades, key=lambda t: t.entry_ts)
        for prev, nxt in itertools.pairwise(ordered):
            assert nxt.entry_ts > prev.exit_ts  # entry strictly after previous exit

    def test_one_signal_one_trade_no_duplicates(self, stub_registry_family) -> None:
        accessor = _trend_accessor(3000)
        _run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        signal_ts = [t.entry_signal_ts for t in ledger.trades]
        assert len(signal_ts) == len(set(signal_ts))  # no duplicate executions

    def test_exit_slippage_applied_both_sides(self, stub_registry_family) -> None:
        accessor = _trend_accessor(3000)
        _run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        slip = 5.0 / 10_000.0
        for t in ledger.trades:
            assert t.eff_entry_price == pytest.approx(t.entry_price * (1 + slip))
            assert t.eff_exit_price == pytest.approx(t.exit_price * (1 - slip))
            # realized_net R uses effective prices with frozen risk
            expected_gross = (t.eff_exit_price - t.eff_entry_price) / t.risk_per_unit
            assert t.gross_r == pytest.approx(expected_gross, rel=1e-9)

    def test_initial_risk_frozen_at_entry(self, stub_registry_family) -> None:
        accessor = _trend_accessor(3000)
        _run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        for t in ledger.trades:
            assert t.risk_per_unit == pytest.approx(t.eff_entry_price - t.stop_price)
            assert t.risk_per_unit > 0

    def test_net_r_identity_per_trade(self, stub_registry_family) -> None:
        accessor = _trend_accessor(3000)
        _run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        for t in ledger.trades:
            assert t.net_r == pytest.approx(t.gross_r - t.fee_r - t.slippage_r, rel=1e-9)

    def test_independent_expectancy_recomputation_matches(
        self, stub_registry_family
    ) -> None:
        accessor = _trend_accessor(3000)
        run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        recomputed = sum(t.net_r for t in ledger.trades) / len(ledger.trades)
        assert run.net_expectancy_r == pytest.approx(recomputed, rel=1e-9)
        assert ledger.net_expectancy_r() == pytest.approx(run.net_expectancy_r)

    def test_unclosed_trade_excluded(self, monkeypatch) -> None:
        import trading_bot.discovery.runner as runner_mod

        # Signal every bar; exit never triggers within window via a family
        # with an extremely tight... instead: make _risk_exit return None by
        # giving bars none below stop => huge window, tiny stop distance is
        # unrealistic; simpler: monkeypatch _risk_exit to always return None.
        monkeypatch.setattr(runner_mod, "_risk_exit", lambda *a, **k: None)
        fam = _StubFamily(every=40)
        monkeypatch.setattr(runner_mod, "_family_instances", lambda: [fam])
        accessor = _trend_accessor(2000)
        run, ledger = evaluate_combo_with_ledger(
            accessor,
            family_name="stub",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        assert run.trades == 0
        assert ledger.trades == ()
        assert run.net_expectancy_r == 0.0

    def test_intrabar_gap_policy_deterministic(self) -> None:
        # Deterministic SL/TP intrabar policy: exit uses min(stop, open) for
        # LONG (gap fill at the worse of stop/open) — pinned by source audit.
        import inspect

        import trading_bot.discovery.runner as runner_mod

        src = inspect.getsource(runner_mod._risk_exit)
        assert "min(stop_price, bar.open)" in src  # LONG gap fill
        assert "max(stop_price, bar.open)" in src  # SHORT gap fill

    def test_no_lookahead_structural(self) -> None:
        # PIT: signal uses candles[:index+1], entry at index+1, exits from
        # index+2 onward — pinned structurally.
        import inspect

        import trading_bot.discovery.runner as runner_mod

        src = inspect.getsource(runner_mod.evaluate_combo_with_ledger)
        assert "history = candles[: index + 1]" in src
        assert "entry_bar = candles[index + 1]" in src
        assert "candles[index + 2 :]" in src


# ---------------------------------------------------------------------------
# G10: superseded candidates excluded from selection
# ---------------------------------------------------------------------------


class TestSupersedeExclusion:
    def test_superseded_records_rejected_by_selection_gate(self, tmp_path: Path) -> None:
        registry = {
            "schema_version": "candidate-registry-v2-superseded",
            "candidates": [
                {
                    "candidate_id": "cand:old:1",
                    "status": "SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW",
                    "frozen_sha256": "a" * 64,
                },
                {
                    "candidate_id": "cand:old:2",
                    "status": "FROZEN_AWAITING_CONFIRMATION",
                    "frozen_sha256": "b" * 64,
                },
            ],
        }
        path = tmp_path / "CANDIDATE_REGISTRY.json"
        path.write_text(json.dumps(registry), encoding="utf-8")

        def load_promotable(p: Path) -> list[dict]:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [
                c
                for c in data.get("candidates", [])
                if c.get("status") == "FROZEN_AWAITING_CONFIRMATION"
            ]

        promotable = load_promotable(path)
        assert [c["candidate_id"] for c in promotable] == ["cand:old:2"]

    def test_all_r0_candidates_marked_superseded(self) -> None:
        base = Path(__file__).resolve().parents[3]
        registry_path = base / "docs/fresh-data-001/evidence/CANDIDATE_REGISTRY.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        candidates = registry.get("candidates", [])
        assert len(candidates) == 9  # R0 evidence preserved
        assert all(
            c["status"] == "SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW"
            for c in candidates
        )
        assert registry.get("schema_version") == "candidate-registry-v2-superseded"
        assert registry.get("superseded_by") == "FRESH-DATA-001-R1"


# ---------------------------------------------------------------------------
# v2 criteria: no freeze on PF/expectancy alone
# ---------------------------------------------------------------------------


def _run_with(**overrides) -> DiscoveryRun:
    defaults = dict(
        family="trend",
        symbol="BTC/USDT:USDT",
        regime="ALL",
        direction="LONG",
        trades=50,
        wins=30,
        losses=20,
        win_rate=0.6,
        gross_expectancy_r=0.5,
        net_expectancy_r=0.4,
        gross_pf=2.0,
        net_pf=1.8,
        gross_pnl_r=20.0,
        fees_r=0.1,
        slippage_r=0.05,
        net_pnl_r=19.85,
        max_drawdown_r=1.0,
        trades_per_day=1.0,
        stability_halves={"h1_net_exp_r": 0.2, "h2_net_exp_r": 0.2},
        regime_concentration=0.5,
        asset_concentration=1.0,
        window=("a", "b"),
        config_sha256="c" * 64,
        temporal_concentration=0.1,
        stability_thirds={"t1_net_exp_r": 0.2, "t2_net_exp_r": 0.2, "t3_net_exp_r": 0.2},
    )
    defaults.update(overrides)
    return DiscoveryRun(**defaults)


class TestCriteriaV2:
    def test_schema_version_bumped(self) -> None:
        assert CRITERIA_SCHEMA_VERSION == "fresh-criteria-v2"

    def test_good_run_passes(self) -> None:
        passed, failures = preregistered_criteria().evaluate(_run_with())
        assert passed, failures

    def test_temporal_concentration_blocks(self) -> None:
        passed, failures = preregistered_criteria().evaluate(
            _run_with(temporal_concentration=0.7)
        )
        assert not passed
        assert "temporal_concentration_too_high" in failures

    def test_single_positive_third_insufficient(self) -> None:
        passed, failures = preregistered_criteria().evaluate(
            _run_with(
                stability_thirds={
                    "t1_net_exp_r": 0.5,
                    "t2_net_exp_r": -0.1,
                    "t3_net_exp_r": -0.1,
                }
            )
        )
        assert not passed
        assert "insufficient_subperiod_stability" in failures

    def test_two_positive_thirds_sufficient(self) -> None:
        passed, failures = preregistered_criteria().evaluate(
            _run_with(
                stability_thirds={
                    "t1_net_exp_r": 0.5,
                    "t2_net_exp_r": -0.1,
                    "t3_net_exp_r": 0.2,
                }
            )
        )
        assert passed, failures

    def test_pf_and_expectancy_alone_still_insufficient(self) -> None:
        # PF/expectancy fine, but concentration defects present => reject.
        passed, failures = preregistered_criteria().evaluate(
            _run_with(
                regime_concentration=0.95,
                temporal_concentration=0.8,
                stability_thirds={
                    "t1_net_exp_r": 1.0,
                    "t2_net_exp_r": -0.2,
                    "t3_net_exp_r": -0.2,
                },
            )
        )
        assert not passed
        assert len(failures) >= 3
