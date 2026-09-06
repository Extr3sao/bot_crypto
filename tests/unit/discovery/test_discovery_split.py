"""FRESH-DATA-001 gate tests (synthetic fixtures; no network required).

Covers: fresh-start boundary (G2), split immutability + locked access
(G4/G5/G6), dataset quality fail-closed, PIT/no-lookahead (G8), legacy
decision impact = 0 (G7), deterministic rerun (G10), candidate freeze
(G11/G12), no paper routing impact (G13).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from trading_bot.discovery import (
    SplitAccessError,
    build_split_manifest,
    compute_split,
    evaluate_combo,
    preregistered_criteria,
    registry_from_runs,
    sha256_candles,
)
from trading_bot.discovery.dataset import (
    FRESH_START_UTC,
    SymbolDataset,
    validate_quality,
)
from trading_bot.discovery.split import SplitAccessor
from trading_bot.market_data.types import OHLCV


def _candles(symbol: str, count: int, start_ms: int, *, seed: int = 3) -> list[OHLCV]:
    import random

    rng = random.Random(seed)
    out: list[OHLCV] = []
    price = 100.0
    ts = start_ms
    for _ in range(count):
        step = rng.uniform(-0.3, 0.33)
        o = price
        c = price + step
        h = max(o, c) + rng.uniform(0.01, 0.08)
        low = min(o, c) - rng.uniform(0.01, 0.08)
        out.append(
            OHLCV(symbol=symbol, timestamp=ts, open=o, high=h, low=low, close=c, volume=100.0)
        )
        price = c
        ts += 300_000
    return out


def _accessor(count_per_symbol: int = 3000) -> SplitAccessor:
    start_ms = int(FRESH_START_UTC.timestamp() * 1000)
    datasets = {
        "BTC/USDT:USDT": SymbolDataset(
            symbol="BTC/USDT:USDT",
            candles=tuple(_candles("BTC/USDT:USDT", count_per_symbol, start_ms)),
            quality=validate_quality(
                "BTC/USDT:USDT", _candles("BTC/USDT:USDT", count_per_symbol, start_ms)
            ),
            sha256="0" * 64,
        ),
    }
    windows = compute_split(start_ms + count_per_symbol * 300_000 - 1)
    manifest = build_split_manifest(windows)
    return SplitAccessor(datasets=datasets, windows=windows, split_sha256=manifest["split_sha256"])


# ---------------------------------------------------------------------------
# G2: fresh start strictly after legacy window
# ---------------------------------------------------------------------------


class TestFreshBoundary:
    def test_fresh_start_is_2026_08_19(self) -> None:
        assert datetime(2026, 8, 19, tzinfo=UTC) == FRESH_START_UTC
        assert datetime(2026, 8, 18, 23, 59, tzinfo=UTC) < FRESH_START_UTC

    def test_quality_rejects_candles_before_start(self) -> None:
        start_ms = int(FRESH_START_UTC.timestamp() * 1000)
        candles = _candles("X", 10, start_ms - 300_000)  # one bar too early
        report = validate_quality("X", candles)
        assert report.before_start == 1
        assert not report.passed

    def test_quality_detects_duplicates_gaps_ohlc(self) -> None:
        start_ms = int(FRESH_START_UTC.timestamp() * 1000)
        good = _candles("X", 20, start_ms)
        dup = good[:10] + good[:10]  # duplicates
        assert validate_quality("X", dup).duplicates == 10
        gapped = good[:10] + good[12:]  # 2-bar gap
        report = validate_quality("X", gapped)
        assert report.gaps == 1 and report.gap_bars == 2
        bad_candle = OHLCV(
            symbol="X", timestamp=start_ms + 5 * 300_000, open=10, high=9, low=11, close=10, volume=1.0
        )
        bad = [*good[:5], bad_candle]
        assert validate_quality("X", bad).ohlc_violations == 1

    def test_content_hash_stable(self) -> None:
        start_ms = int(FRESH_START_UTC.timestamp() * 1000)
        candles = _candles("X", 15, start_ms)
        assert sha256_candles(candles) == sha256_candles(list(candles))


# ---------------------------------------------------------------------------
# G4/G5/G6: immutable split + locked windows
# ---------------------------------------------------------------------------


class TestSplitLock:
    def test_split_is_chronological_60_20_20(self) -> None:
        start_ms = int(FRESH_START_UTC.timestamp() * 1000)
        windows = compute_split(start_ms + 1000 * 300_000 - 1)
        assert windows.discovery_start == FRESH_START_UTC
        assert windows.discovery_end_exclusive > windows.discovery_start
        assert windows.confirmation_end_exclusive > windows.discovery_end_exclusive
        assert windows.holdout_end_exclusive > windows.confirmation_end_exclusive
        total = (windows.holdout_end_exclusive - windows.discovery_start).total_seconds()
        d = (windows.discovery_end_exclusive - windows.discovery_start).total_seconds()
        c = (windows.confirmation_end_exclusive - windows.confirmation_start).total_seconds()
        assert abs(d / total - 0.60) < 0.01
        assert abs(c / total - 0.20) < 0.01

    def test_confirmation_read_fails_closed(self) -> None:
        accessor = _accessor()
        with pytest.raises(SplitAccessError):
            accessor.read("BTC/USDT:USDT", "confirmation")

    def test_holdout_read_fails_closed(self) -> None:
        accessor = _accessor()
        with pytest.raises(SplitAccessError):
            accessor.read("BTC/USDT:USDT", "final_holdout")

    def test_split_manifest_hashed_and_declares_lock(self) -> None:
        windows = compute_split(int(FRESH_START_UTC.timestamp() * 1000) + 1000 * 300_000)
        manifest = build_split_manifest(windows)
        body = {k: v for k, v in manifest.items() if k != "split_sha256"}
        expected = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert manifest["split_sha256"] == expected
        assert manifest["locked_after_freeze"] is True

    def test_accessor_only_serves_discovery(self) -> None:
        accessor = _accessor()
        candles = accessor.discovery_candles("BTC/USDT:USDT")
        assert candles
        end_exclusive = accessor.windows.discovery_end_exclusive
        assert all(c.timestamp < int(end_exclusive.timestamp() * 1000) for c in candles)


# ---------------------------------------------------------------------------
# Runner + determinism (G10) on synthetic slice
# ---------------------------------------------------------------------------


class TestRunnerDeterminism:
    def test_same_input_same_run(self) -> None:
        a = evaluate_combo(
            _accessor(),
            family_name="ema_crossover",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        b = evaluate_combo(
            _accessor(),
            family_name="ema_crossover",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        assert a.to_dict() == b.to_dict()

    def test_run_reads_only_discovery(self) -> None:
        accessor = _accessor()
        run = evaluate_combo(
            accessor,
            family_name="momentum",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="SHORT",
        )
        assert run.window[0] == accessor.windows.discovery_start.isoformat()
        assert run.window[1] == accessor.windows.discovery_end_exclusive.isoformat()


# ---------------------------------------------------------------------------
# G7: legacy impact = 0 (structural)
# ---------------------------------------------------------------------------


class TestLegacyImpactZero:
    def test_criteria_cannot_receive_legacy_records(self) -> None:
        import inspect

        from trading_bot.discovery.criteria import FreezeCriteria

        params = inspect.signature(FreezeCriteria.evaluate).parameters
        assert set(params) == {"self", "run"}

    def test_registry_annotation_never_flips_decision(self) -> None:
        # Same run classified with and without a legacy index => same outcome.
        start_ms = int(FRESH_START_UTC.timestamp() * 1000)
        candles = tuple(
            _candles("BTC/USDT:USDT", 3000, start_ms, seed=11)
        )
        dataset = SymbolDataset(
            symbol="BTC/USDT:USDT",
            candles=candles,
            quality=validate_quality("BTC/USDT:USDT", list(candles)),
            sha256="1" * 64,
        )
        windows = compute_split(start_ms + 3000 * 300_000 - 1)
        accessor = SplitAccessor(
            datasets={"BTC/USDT:USDT": dataset},
            windows=windows,
            split_sha256=build_split_manifest(windows)["split_sha256"],
        )
        run = evaluate_combo(
            accessor,
            family_name="trend",
            symbol="BTC/USDT:USDT",
            regime_filter="ALL",
            direction_filter="LONG",
        )
        criteria = preregistered_criteria()
        with_index = registry_from_runs([run], criteria, legacy_index=object())
        without_index = registry_from_runs([run], criteria, legacy_index=None)
        assert len(with_index.candidates) == len(without_index.candidates)
        assert len(with_index.rejected) == len(without_index.rejected)
        if with_index.rejected:
            assert with_index.rejected[0].legacy_context_note == ""

    def test_no_path_from_legacy_to_discovery_modules(self) -> None:
        # Structural: discovery code never IMPORTS legacy_evidence (docstring
        # mentions of the legacy window are fine; imports are not).
        import ast
        from pathlib import Path

        import trading_bot.discovery as pkg

        src_dir = Path(pkg.__file__).parent
        for path in src_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert not any(
                        "legacy_evidence" in alias.name for alias in node.names
                    ), path.name
                elif isinstance(node, ast.ImportFrom):
                    assert "legacy_evidence" not in (node.module or ""), path.name


# ---------------------------------------------------------------------------
# G11/G12: freeze + registry
# ---------------------------------------------------------------------------


class TestFreezeAndRegistry:
    def test_candidate_is_frozen_and_hashed(self) -> None:
        from trading_bot.discovery import FrozenCandidate

        candidate = FrozenCandidate(
            candidate_id="cand:test",
            family="trend",
            symbols=("BTC/USDT:USDT",),
            regimes=("ALL",),
            direction="LONG",
            costs={"fee_rate": 0.0005, "slippage_bps": 5.0},
            discovery_window=("2026-08-19T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
            discovery_metrics={"trades": 40, "net_expectancy_r": 0.08},
            config_sha256="a" * 64,
            criteria_sha256="b" * 64,
        )
        first = candidate.frozen_sha256
        assert first == candidate.frozen_sha256
        assert candidate.to_dict()["status"] == "FROZEN_AWAITING_CONFIRMATION"

    def test_criteria_fail_closed_by_default(self) -> None:
        from trading_bot.discovery.runner import DiscoveryRun

        run = DiscoveryRun(
            family="trend",
            symbol="BTC/USDT:USDT",
            regime="ALL",
            direction="LONG",
            trades=5,
            wins=3,
            losses=2,
            win_rate=0.6,
            gross_expectancy_r=0.5,
            net_expectancy_r=0.4,
            gross_pf=2.0,
            net_pf=1.8,
            gross_pnl_r=2.0,
            fees_r=0.1,
            slippage_r=0.05,
            net_pnl_r=1.85,
            max_drawdown_r=0.5,
            trades_per_day=1.0,
            stability_halves={"h1_net_exp_r": 0.2, "h2_net_exp_r": 0.2},
            regime_concentration=0.5,
            asset_concentration=1.0,
            window=("a", "b"),
            config_sha256="c" * 64,
        )
        passed, failures = preregistered_criteria().evaluate(run)
        assert not passed
        assert any("trades" in f for f in failures)

    def test_registry_sha_is_content_bound(self) -> None:
        from trading_bot.discovery.runner import DiscoveryRun

        def make_run(net_exp: float) -> DiscoveryRun:
            return DiscoveryRun(
                family="trend",
                symbol="BTC/USDT:USDT",
                regime="ALL",
                direction="LONG",
                trades=50,
                wins=30,
                losses=20,
                win_rate=0.6,
                gross_expectancy_r=net_exp + 0.1,
                net_expectancy_r=net_exp,
                gross_pf=1.5,
                net_pf=1.4,
                gross_pnl_r=5.0,
                fees_r=0.1,
                slippage_r=0.05,
                net_pnl_r=4.85,
                max_drawdown_r=0.5,
                trades_per_day=1.0,
                stability_halves={"h1_net_exp_r": net_exp, "h2_net_exp_r": net_exp},
                regime_concentration=0.5,
                asset_concentration=1.0,
                window=("a", "b"),
                config_sha256="c" * 64,
            )

        criteria = preregistered_criteria()
        registry_a = registry_from_runs([make_run(0.2)], criteria)
        registry_b = registry_from_runs([make_run(0.21)], criteria)
        assert registry_a.to_dict()["registry_sha256"] != registry_b.to_dict()["registry_sha256"]


# ---------------------------------------------------------------------------
# G13: no paper routing impact (structural)
# ---------------------------------------------------------------------------


class TestNoPaperImpact:
    def test_discovery_does_not_touch_paper_or_risk_modules(self) -> None:
        from pathlib import Path

        import trading_bot.discovery as pkg

        src_dir = Path(pkg.__file__).parent
        for path in src_dir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "PaperBroker" not in text, path.name
            assert "RiskManager" not in text, path.name
            assert "paper_multi_agent" not in text, path.name


# ---------------------------------------------------------------------------
# G8: PIT / no-lookahead in the runner
# ---------------------------------------------------------------------------


class TestPitNoLookahead:
    def test_signal_uses_history_up_to_bar_entry_next_bar(self) -> None:
        # Structural audit of evaluate_combo's loop: signals are generated on
        # candles[: index + 1] and entries occur on candles[index + 1].
        from pathlib import Path

        import trading_bot.discovery.runner as runner

        src = Path(runner.__file__).read_text(encoding="utf-8")
        assert "history = candles[: index + 1]" in src
        assert "entry_bar = candles[index + 1]" in src
        assert "candles[index + 2 :]" in src  # exits checked strictly after entry
