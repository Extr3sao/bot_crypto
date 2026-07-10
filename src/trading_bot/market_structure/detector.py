"""Deterministic market-structure detector for TSK-860."""

from __future__ import annotations

from statistics import mean

from trading_bot.market_data.types import OHLCV
from trading_bot.trade_journal.types import TechnicalZone


def detect_market_structure(
    candles: list[OHLCV],
    *,
    symbol: str,
    timeframe: str,
    swing_window: int = 2,
    detected_at: int | None = None,
) -> tuple[TechnicalZone, ...]:
    if swing_window < 1:
        raise ValueError("swing_window must be >= 1")
    if len(candles) < (swing_window * 2) + 1:
        return ()

    event_ts = detected_at if detected_at is not None else candles[-1].timestamp
    zones: list[TechnicalZone] = []
    zones.extend(_pivot_zones(candles, symbol, timeframe, swing_window, event_ts))
    zones.extend(_range_zones(candles, symbol, timeframe, event_ts))
    order_block = _order_block_zone(candles, symbol, timeframe, event_ts)
    if order_block is not None:
        zones.append(order_block)
    consolidation = _consolidation_zone(candles, symbol, timeframe, event_ts)
    if consolidation is not None:
        zones.append(consolidation)
    return tuple(zones)


def distance_to_zone_bps(price: float, zone: TechnicalZone) -> float:
    if price <= 0:
        raise ValueError("price must be > 0")
    if zone.low <= price <= zone.high:
        return 0.0
    edge = zone.low if price < zone.low else zone.high
    return abs(price - edge) / price * 10_000.0


def _pivot_zones(
    candles: list[OHLCV],
    symbol: str,
    timeframe: str,
    swing_window: int,
    detected_at: int,
) -> list[TechnicalZone]:
    zones: list[TechnicalZone] = []
    for idx in range(swing_window, len(candles) - swing_window):
        candle = candles[idx]
        left = candles[idx - swing_window : idx]
        right = candles[idx + 1 : idx + swing_window + 1]
        neighbors = left + right
        if candle.low < min(row.low for row in neighbors):
            zones.append(
                _zone(
                    symbol=symbol,
                    timeframe=timeframe,
                    kind="support",
                    low=candle.low,
                    high=min(candle.open, candle.close),
                    detected_at=detected_at,
                    source="swing_pivot",
                    suffix=str(candle.timestamp),
                    evidence={"pivot_timestamp": candle.timestamp},
                )
            )
        if candle.high > max(row.high for row in neighbors):
            zones.append(
                _zone(
                    symbol=symbol,
                    timeframe=timeframe,
                    kind="resistance",
                    low=max(candle.open, candle.close),
                    high=candle.high,
                    detected_at=detected_at,
                    source="swing_pivot",
                    suffix=str(candle.timestamp),
                    evidence={"pivot_timestamp": candle.timestamp},
                )
            )
    return zones


def _range_zones(
    candles: list[OHLCV],
    symbol: str,
    timeframe: str,
    detected_at: int,
) -> list[TechnicalZone]:
    low_candle = min(candles, key=lambda row: row.low)
    high_candle = max(candles, key=lambda row: row.high)
    return [
        _zone(
            symbol=symbol,
            timeframe=timeframe,
            kind="range_low",
            low=low_candle.low,
            high=min(low_candle.open, low_candle.close),
            detected_at=detected_at,
            source="lookback_extreme",
            suffix=str(low_candle.timestamp),
            evidence={"lookback": len(candles), "extreme_timestamp": low_candle.timestamp},
        ),
        _zone(
            symbol=symbol,
            timeframe=timeframe,
            kind="range_high",
            low=max(high_candle.open, high_candle.close),
            high=high_candle.high,
            detected_at=detected_at,
            source="lookback_extreme",
            suffix=str(high_candle.timestamp),
            evidence={"lookback": len(candles), "extreme_timestamp": high_candle.timestamp},
        ),
    ]


def _order_block_zone(
    candles: list[OHLCV],
    symbol: str,
    timeframe: str,
    detected_at: int,
) -> TechnicalZone | None:
    atr = _mean_range(candles)
    if atr <= 0:
        return None
    for prev, current in zip(reversed(candles[:-1]), reversed(candles[1:]), strict=False):
        impulse = abs(current.close - current.open)
        prev_bearish = prev.close < prev.open
        current_bullish = current.close > current.open
        prev_bullish = prev.close > prev.open
        current_bearish = current.close < current.open
        if impulse >= atr and (
            (prev_bearish and current_bullish) or (prev_bullish and current_bearish)
        ):
            return _zone(
                symbol=symbol,
                timeframe=timeframe,
                kind="order_block",
                low=min(prev.open, prev.close),
                high=max(prev.open, prev.close),
                detected_at=detected_at,
                source="opposite_candle_before_atr_impulse",
                suffix=str(prev.timestamp),
                evidence={
                    "impulse": impulse,
                    "atr_proxy": atr,
                    "bullish_impulse": current_bullish,
                },
            )
    return None


def _consolidation_zone(
    candles: list[OHLCV],
    symbol: str,
    timeframe: str,
    detected_at: int,
) -> TechnicalZone | None:
    window = candles[-min(8, len(candles)) :]
    high = max(candle.high for candle in window)
    low = min(candle.low for candle in window)
    avg_close = mean(candle.close for candle in window)
    if avg_close <= 0:
        return None
    range_pct = (high - low) / avg_close * 100.0
    recent_volume = mean(candle.volume for candle in window)
    baseline = mean(candle.volume for candle in candles)
    if range_pct <= 1.0 and recent_volume >= baseline:
        direction = "accumulation" if window[-1].close >= window[0].close else "distribution"
        return _zone(
            symbol=symbol,
            timeframe=timeframe,
            kind=direction,
            low=low,
            high=high,
            detected_at=detected_at,
            source="tight_range_relative_volume",
            suffix=str(window[-1].timestamp),
            evidence={
                "range_pct": range_pct,
                "recent_volume": recent_volume,
                "baseline_volume": baseline,
            },
        )
    return None


def _mean_range(candles: list[OHLCV]) -> float:
    return mean(max(0.0, candle.high - candle.low) for candle in candles)


def _zone(
    *,
    symbol: str,
    timeframe: str,
    kind: str,
    low: float,
    high: float,
    detected_at: int,
    source: str,
    suffix: str,
    evidence: dict[str, float | str | bool],
) -> TechnicalZone:
    zone_low = min(low, high)
    zone_high = max(low, high)
    width = max(zone_high - zone_low, 0.0)
    mid = (zone_low + zone_high) / 2.0
    width_pct = width / mid if mid > 0 else 1.0
    strength = max(0.1, min(1.0, 1.0 - width_pct))
    return TechnicalZone(
        zone_id=f"{symbol}:{timeframe}:{kind}:{suffix}",
        symbol=symbol,
        timeframe=timeframe,
        kind=kind,  # type: ignore[arg-type]
        low=zone_low,
        high=zone_high,
        strength=strength,
        detected_at=detected_at,
        source=source,
        evidence=evidence,
    )


__all__ = ["detect_market_structure", "distance_to_zone_bps"]
