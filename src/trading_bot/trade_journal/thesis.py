"""Entry-thesis builder for TSK-860."""

from __future__ import annotations

from dataclasses import dataclass, field

from trading_bot.market_data.types import OHLCV
from trading_bot.market_structure import detect_market_structure, distance_to_zone_bps
from trading_bot.trade_journal.types import EntryThesis, TechnicalZone


@dataclass(frozen=True, slots=True)
class EntryThesisInput:
    trade_case_id: str
    signal_id: str
    symbol: str
    direction: str
    entry_price: float
    tp_price: float
    sl_price: float
    timeframe: str
    entry_reason: str
    candles: tuple[OHLCV, ...]
    indicators: dict[str, float | str | bool] = field(default_factory=dict)
    created_at: int | None = None


def build_entry_thesis(
    payload: EntryThesisInput,
    *,
    swing_window: int = 2,
    near_zone_bps: float = 35.0,
) -> EntryThesis:
    if payload.direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if payload.entry_price <= 0:
        raise ValueError("entry_price must be > 0")

    created_at = (
        payload.created_at if payload.created_at is not None else payload.candles[-1].timestamp
    )
    zones = detect_market_structure(
        list(payload.candles),
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        swing_window=swing_window,
        detected_at=created_at,
    )
    criteria_met, criteria_failed = _score_context(
        direction=payload.direction,
        entry_price=payload.entry_price,
        zones=zones,
        near_zone_bps=near_zone_bps,
    )
    confidence = _confidence_score(criteria_met, criteria_failed)
    indicators = dict(payload.indicators)
    indicators["zones_detected"] = float(len(zones))
    indicators["near_zone_bps"] = near_zone_bps

    return EntryThesis(
        trade_case_id=payload.trade_case_id,
        signal_id=payload.signal_id,
        symbol=payload.symbol,
        direction=payload.direction,  # type: ignore[arg-type]
        entry_price=payload.entry_price,
        tp_price=payload.tp_price,
        sl_price=payload.sl_price,
        timeframe=payload.timeframe,
        entry_reason=payload.entry_reason,
        criteria_met=tuple(criteria_met),
        criteria_failed=tuple(criteria_failed),
        indicators=indicators,
        zones=zones,
        confidence_score=confidence,
        created_at=created_at,
    )


def _score_context(
    *,
    direction: str,
    entry_price: float,
    zones: tuple[TechnicalZone, ...],
    near_zone_bps: float,
) -> tuple[list[str], list[str]]:
    criteria_met: list[str] = []
    criteria_failed: list[str] = []
    nearest = sorted(
        ((distance_to_zone_bps(entry_price, zone), zone) for zone in zones),
        key=lambda item: item[0],
    )
    for distance_bps, zone in nearest[:5]:
        if distance_bps > near_zone_bps:
            continue
        if direction == "LONG":
            if zone.kind in {"support", "range_low", "accumulation", "order_block"}:
                criteria_met.append(f"near_{zone.kind}")
            if zone.kind in {"resistance", "range_high", "distribution"}:
                criteria_failed.append(f"near_{zone.kind}_against_long")
        else:
            if zone.kind in {"resistance", "range_high", "distribution", "order_block"}:
                criteria_met.append(f"near_{zone.kind}")
            if zone.kind in {"support", "range_low", "accumulation"}:
                criteria_failed.append(f"near_{zone.kind}_against_short")

    if not criteria_met:
        criteria_failed.append("no_supporting_structure_near_entry")
    return _dedupe(criteria_met), _dedupe(criteria_failed)


def _confidence_score(criteria_met: list[str], criteria_failed: list[str]) -> float:
    raw = 0.5 + (0.12 * len(criteria_met)) - (0.16 * len(criteria_failed))
    return max(0.0, min(1.0, round(raw, 4)))


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


__all__ = ["EntryThesisInput", "build_entry_thesis"]
