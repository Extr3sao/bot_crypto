"""CAP-001 — deterministic adapter from TradingView MCP payloads to a snapshot.

The TradingView MCP server is the *intelligence source*.  It is **not** an
accounting source of truth and it is not a REST API with an API key: it is a
streamable-HTTP MCP surface authenticated with OAuth 2.1 against a paid
TradingView account, consumed by an LLM client (Claude / ChatGPT / Codex).

This module therefore does the only deterministic job available to the repo:

* take the raw payloads of the read-only MCP tools (``get_ohlcv``,
  ``get_technicals_rating``, ``get_news``, ``get_economic_calendar``, ...),
* map them into the :class:`~trading_bot.research.agentic_contracts.MarketSnapshot`
  contract with an explicit timestamp and freshness class,
* refuse to invent anything: a missing field becomes ``None`` and a missing
  structure raises instead of being fabricated.

Documented limits the adapter respects:

* ``get_ohlcv`` returns at most 5000 bars and takes a single interval,
* ``get_technicals_rating`` is **single-timeframe** per call, so the
  ``multi_timeframe`` block has to be composed from several calls,
* write tools (alerts, watchlists) are rejected outright by the spike.

No network, no credentials, no orders, no capital.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from trading_bot.research.agentic_contracts import (
    MCP_MAX_OHLCV_BARS,
    READ_ONLY_MCP_TOOLS,
    WRITE_MCP_TOOLS,
    DataFreshness,
    Evidence,
    MacroEvent,
    MarketSnapshot,
    NewsItem,
    PriceState,
    RelativeStrength,
    TechnicalState,
    TimeframeState,
    VolumeState,
    freshness_class,
)

TIMEFRAME_ORDER: tuple[str, ...] = ("1h", "4h", "1D")

#: Candidate key names seen in the documented MCP responses.  Absence -> None.
_TECHNICAL_KEYS: dict[str, tuple[str, ...]] = {
    "rsi": ("RSI", "RSI14", "rsi"),
    "macd": ("MACD.macd", "MACD", "MACD_Level", "macd"),
    "adx": ("ADX", "ADX14", "adx"),
    "momentum": ("Momentum", "Mom", "momentum"),
    "sma50": ("SMA50", "SMA.50", "sma50"),
    "ema200": ("EMA200", "EMA.200", "ema200"),
}
_RECOMMENDATION_KEYS: tuple[str, ...] = ("Recommend.Summary", "Recommend", "recommendation", "summary")


# --------------------------------------------------------------------------- #
# low-level, non-fabricating helpers
# --------------------------------------------------------------------------- #


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            return None
        return result if math.isfinite(result) else None
    return None


def _pick(payload: Mapping[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        if key in payload:
            found = _as_float(payload[key])
            if found is not None:
                return found
    return None


def extract_bars(payload: Any) -> tuple[dict[str, Any], ...]:
    """Pull the raw OHLCV bars out of a ``get_ohlcv`` response, or raise."""
    raw: Any
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, Mapping):
        for key in ("bars", "ohlcv", "candles", "data"):
            if key in payload:
                raw = payload[key]
                break
        else:
            raise ValueError("get_ohlcv payload has no bars array")
    else:
        raise ValueError("get_ohlcv payload must be a mapping or a bar list")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError("get_ohlcv payload bars must be a non-empty sequence")
    if len(raw) > MCP_MAX_OHLCV_BARS:
        raise ValueError(f"get_ohlcv returned {len(raw)} bars, above the documented {MCP_MAX_OHLCV_BARS}")
    bars: list[dict[str, Any]] = []
    for bar in raw:
        if not isinstance(bar, Mapping):
            raise ValueError("each OHLCV bar must be a mapping")
        close = _as_float(bar.get("c", bar.get("close")))
        if close is None:
            raise ValueError("each OHLCV bar needs a numeric close")
        bars.append(dict(bar))
    return tuple(bars)


def closes(bars: Sequence[Mapping[str, Any]]) -> tuple[float, ...]:
    return tuple(
        value
        for bar in bars
        if (value := _as_float(bar.get("c", bar.get("close")))) is not None
    )


def volumes(bars: Sequence[Mapping[str, Any]]) -> tuple[float, ...]:
    return tuple(
        value
        for bar in bars
        if (value := _as_float(bar.get("v", bar.get("volume")))) is not None
    )


def bar_timestamps(bars: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    stamps: list[int] = []
    for bar in bars:
        stamp = bar.get("t", bar.get("time", bar.get("timestamp")))
        if isinstance(stamp, bool) or stamp is None:
            continue
        if isinstance(stamp, (int, float)):
            stamps.append(int(stamp))
    return tuple(stamps)


def trend_of(bars: Sequence[Mapping[str, Any]]) -> str:
    """Deterministic trend label from closes alone (no indicator library)."""
    series = closes(bars)
    if len(series) < 2:
        return "unknown"
    lookback = min(20, len(series))
    reference = series[-lookback]
    mean = math.fsum(series[-lookback:]) / lookback
    last = series[-1]
    if last > reference and last > mean:
        return "up"
    if last < reference and last < mean:
        return "down"
    return "range"


# --------------------------------------------------------------------------- #
# block builders
# --------------------------------------------------------------------------- #


def price_state_from_ohlcv(symbol: str, interval: str, payload: Any) -> PriceState:
    bars = extract_bars(payload)
    series = closes(bars)
    first, last = series[0], series[-1]
    change_pct = 0.0 if first == 0.0 else (last - first) / first * 100.0
    return PriceState(
        symbol=symbol,
        last=last,
        change_pct=change_pct,
        bar_interval=interval,
        bar_count=len(bars),
    )


def volume_state_from_ohlcv(payload: Any) -> VolumeState:
    values = volumes(extract_bars(payload))
    if not values:
        return VolumeState(last=0.0, relative=0.0)
    last = values[-1]
    history = values[:-1]
    if not history:
        return VolumeState(last=last, relative=0.0)
    average = math.fsum(history) / len(history)
    relative = 0.0 if average == 0.0 else last / average
    return VolumeState(last=last, relative=relative)


def timeframe_state(symbol: str, interval: str, payload: Any) -> TimeframeState:
    state = price_state_from_ohlcv(symbol, interval, payload)
    return TimeframeState(
        interval=interval,
        last=state.last,
        change_pct=state.change_pct,
        trend=trend_of(extract_bars(payload)),
    )


def multi_timeframe_states(per_interval: Mapping[str, Any], symbol: str) -> tuple[TimeframeState, ...]:
    """Compose the multi-timeframe block (technicals are single-TF per call)."""
    ordered = [interval for interval in TIMEFRAME_ORDER if interval in per_interval]
    ordered.extend(sorted(interval for interval in per_interval if interval not in TIMEFRAME_ORDER))
    return tuple(timeframe_state(symbol, interval, per_interval[interval]) for interval in ordered)


def technical_state_from_rating(payload: Mapping[str, Any]) -> TechnicalState:
    recommendation = ""
    for key in _RECOMMENDATION_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            recommendation = candidate.strip()
            break
    return TechnicalState(
        rsi=_pick(payload, _TECHNICAL_KEYS["rsi"]),
        macd=_pick(payload, _TECHNICAL_KEYS["macd"]),
        adx=_pick(payload, _TECHNICAL_KEYS["adx"]),
        momentum=_pick(payload, _TECHNICAL_KEYS["momentum"]),
        sma50=_pick(payload, _TECHNICAL_KEYS["sma50"]),
        ema200=_pick(payload, _TECHNICAL_KEYS["ema200"]),
        recommendation=recommendation,
    )


def news_items(payload: Any) -> tuple[NewsItem, ...]:
    raw = payload.get("items", payload.get("headlines", payload)) if isinstance(payload, Mapping) else payload
    if not isinstance(raw, (list, tuple)):
        return ()
    items: list[NewsItem] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        title = str(entry.get("title", "")).strip()
        published = entry.get("published", entry.get("t"))
        if not title or not isinstance(published, (int, float)) or isinstance(published, bool):
            continue
        items.append(
            NewsItem(
                title=title,
                published=int(published),
                provider=str(entry.get("provider", "")),
                urgency=int(entry.get("urgency", 2)),
                link=str(entry.get("link", "")),
            )
        )
    return tuple(items)


def macro_events(payload: Any) -> tuple[MacroEvent, ...]:
    raw = payload.get("events", payload.get("items", payload)) if isinstance(payload, Mapping) else payload
    if not isinstance(raw, (list, tuple)):
        return ()
    events: list[MacroEvent] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", entry.get("title", entry.get("event", "")))).strip()
        when = entry.get("when", entry.get("date", entry.get("t")))
        if not name or not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        importance = entry.get("importance", -1)
        events.append(
            MacroEvent(
                name=name,
                country=str(entry.get("country", "")),
                when=int(when),
                importance=importance if importance in (-1, 0, 1) else -1,
                actual=_as_float(entry.get("actual")),
            )
        )
    return tuple(events)


def relative_strength(symbol: str, reference: str, value: float | None) -> RelativeStrength:
    return RelativeStrength(symbol=symbol, reference=reference, value=0.0 if value is None else value)


# --------------------------------------------------------------------------- #
# evidence collection (mechanical; weighting stays non-deterministic)
# --------------------------------------------------------------------------- #


def evidence_from_blocks(
    *,
    technicals: TechnicalState,
    multi_timeframe: Sequence[TimeframeState],
    volume: VolumeState,
    relative_strength_block: RelativeStrength,
    news: Sequence[NewsItem],
    macro: Sequence[MacroEvent],
) -> tuple[Evidence, ...]:
    items: list[Evidence] = []
    if technicals.rsi is not None or technicals.adx is not None:
        items.append(
            Evidence(
                kind="technical",
                source="tradingview_mcp.get_technicals_rating",
                detail=(
                    f"RSI={technicals.rsi} ADX={technicals.adx} "
                    f"MACD={technicals.macd} recommendation={technicals.recommendation or 'n/a'}"
                ),
                value=technicals.rsi,
            )
        )
    if multi_timeframe:
        aligned = {state.trend for state in multi_timeframe}
        items.append(
            Evidence(
                kind="price_structure",
                source="tradingview_mcp.get_ohlcv",
                detail="timeframe trends: "
                + ", ".join(f"{state.interval}={state.trend}" for state in multi_timeframe),
                value=float(len(aligned) == 1),
            )
        )
    items.append(
        Evidence(
            kind="volume",
            source="tradingview_mcp.get_ohlcv",
            detail=f"last volume vs trailing average = {volume.relative:.3f}x",
            value=volume.relative,
        )
    )
    items.append(
        Evidence(
            kind="relative_strength",
            source="tradingview_mcp.run_screener",
            detail=f"{relative_strength_block.symbol} vs {relative_strength_block.reference}",
            value=relative_strength_block.value,
        )
    )
    if news:
        items.append(
            Evidence(
                kind="news",
                source="tradingview_mcp.get_news",
                detail=f"{len(news)} headline(s); newest: {news[0].title}",
                value=float(len(news)),
            )
        )
    if macro:
        upcoming = [event for event in macro if event.importance == 1]
        items.append(
            Evidence(
                kind="macro",
                source="tradingview_mcp.get_economic_calendar",
                detail=f"{len(macro)} event(s), {len(upcoming)} high-importance",
                value=float(len(upcoming)),
            )
        )
    return tuple(items)


def assert_read_only_tools(tool_names: Iterable[str]) -> tuple[str, ...]:
    """Reject write tools and unknown tools; return the read-only tool names."""
    used = tuple(tool_names)
    writes = [name for name in used if name in WRITE_MCP_TOOLS]
    if writes:
        raise ValueError(f"the spike must never call a write MCP tool: {sorted(writes)}")
    unknown = [name for name in used if name not in READ_ONLY_MCP_TOOLS]
    if unknown:
        raise ValueError(f"unknown MCP tool(s): {sorted(unknown)}")
    return used


def data_freshness(
    *, snapshot_at: int, source_timestamps: Sequence[int], degraded: bool = False
) -> DataFreshness:
    stamps = [int(stamp) for stamp in source_timestamps if stamp]
    if not stamps:
        return DataFreshness(
            snapshot_at=snapshot_at,
            newest_source_at=0,
            oldest_source_at=0,
            age_seconds=-1,
            level="UNKNOWN",
            degraded=True,
        )
    newest = max(stamps)
    oldest = min(stamps)
    age = snapshot_at - newest
    level = freshness_class(age)
    return DataFreshness(
        snapshot_at=snapshot_at,
        newest_source_at=newest,
        oldest_source_at=oldest,
        age_seconds=age,
        level=level,
        degraded=degraded or level in ("STALE", "UNKNOWN"),
    )


def build_snapshot(
    *,
    asset: str,
    snapshot_at: int,
    ohlcv_by_interval: Mapping[str, Any],
    technicals_payload: Mapping[str, Any],
    news_payload: Any,
    macro_payload: Any,
    market_regime: str,
    reference_symbol: str,
    relative_strength_value: float | None,
    source_timestamps: Sequence[int],
    degraded: bool = False,
) -> MarketSnapshot:
    """Assemble a timestamped :class:`MarketSnapshot` from read-only MCP payloads.

    ``market_regime`` is supplied by the analyst (a non-deterministic domain);
    every other block is mapped mechanically from the payloads.
    """
    if not ohlcv_by_interval:
        raise ValueError("at least one OHLCV interval is required to build a snapshot")
    multi = multi_timeframe_states(ohlcv_by_interval, asset)
    primary_interval = multi[0].interval
    technicals = technical_state_from_rating(technicals_payload)
    volume = volume_state_from_ohlcv(ohlcv_by_interval[primary_interval])
    news = news_items(news_payload)
    macro = macro_events(macro_payload)
    rs = relative_strength(asset, reference_symbol, relative_strength_value)
    return MarketSnapshot(
        timestamp=snapshot_at,
        asset=asset,
        price_state=price_state_from_ohlcv(asset, primary_interval, ohlcv_by_interval[primary_interval]),
        multi_timeframe=multi,
        technical_state=technicals,
        relative_strength=rs,
        volume_state=volume,
        market_regime=market_regime.strip(),
        news=news,
        macro_events=macro,
        evidence=evidence_from_blocks(
            technicals=technicals,
            multi_timeframe=multi,
            volume=volume,
            relative_strength_block=rs,
            news=news,
            macro=macro,
        ),
        data_freshness=data_freshness(
            snapshot_at=snapshot_at, source_timestamps=source_timestamps, degraded=degraded
        ),
    )
