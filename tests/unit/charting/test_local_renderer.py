from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.charting import ChartSnapshotRequest, render_local_chart_snapshot
from trading_bot.market_data.types import OHLCV
from trading_bot.trade_journal.types import TechnicalZone


def _candle(ts: int, open_: float, high: float, low: float, close: float) -> OHLCV:
    return OHLCV("BTC/USDT", ts, open_, high, low, close, 100)


def test_local_renderer_writes_svg_with_core_overlays(tmp_path: Path) -> None:
    zone = TechnicalZone(
        zone_id="zone-1",
        symbol="BTC/USDT",
        timeframe="1m",
        kind="support",
        low=99,
        high=100,
        strength=0.8,
        detected_at=10,
        source="test",
    )

    snapshot = render_local_chart_snapshot(
        ChartSnapshotRequest(
            trade_case_id="case/1",
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=101,
            tp_price=104,
            sl_price=98,
            candles=(
                _candle(1, 100, 102, 99, 101),
                _candle(2, 101, 103, 100, 102),
                _candle(3, 102, 104, 101, 103),
            ),
            zones=(zone,),
            output_dir=tmp_path,
            captured_at=11,
        )
    )

    path = Path(snapshot.path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "ENTRY 101.0000" in content
    assert "TP 104.0000" in content
    assert "SL 98.0000" in content
    assert "support" in content
    assert snapshot.provider == "local_renderer"
    assert snapshot.overlays["zones"] == ["zone-1"]


def test_local_renderer_rejects_empty_candles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="candles must be non-empty"):
        render_local_chart_snapshot(
            ChartSnapshotRequest(
                trade_case_id="case-1",
                symbol="BTC/USDT",
                direction="LONG",
                entry_price=101,
                tp_price=104,
                sl_price=98,
                candles=(),
                zones=(),
                output_dir=tmp_path,
                captured_at=11,
            )
        )
