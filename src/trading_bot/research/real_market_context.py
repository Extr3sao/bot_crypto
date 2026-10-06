"""CAP-002 free real market pilot — real context from the existing provider.

This is the *minimal* glue the pilot allows: reuse the repository's existing,
runtime-reachable real provider (``CCXTExchangeConnector`` on Binance, public
read-only OHLCV, no credentials), map it into the existing
:class:`~trading_bot.research.agentic_contracts.MarketSnapshot` contract, and
evaluate the replacement gate :data:`G_REAL_MARKET_CONTEXT`.

Nothing here invents context.  News, macro and sentiment are deliberately
**absent** for V1 (they would confound the experiment); TradingView technical
ratings are absent too.  Only deterministic, causal, bar-derived features are
attached, and only from indicators the repository already implements
(``trading_bot.indicators.builtin``) plus the frozen RFC-039 ``sma``.

Causality is enforced, not assumed: every timeframe keeps only bars that had
*fully closed* at ``decision_time`` (``bar_open + interval <= decision_time``),
so an in-progress candle can never reach the analyst.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from trading_bot.config.exchange import Exchange
from trading_bot.indicators.builtin import (
    EmaIndicator,
    MacdIndicator,
    MomentumIndicator,
    RsiIndicator,
    VolatilityIndicator,
)
from trading_bot.market_data.exchange_connector import CCXTExchangeConnector
from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import tradingview_mcp_adapter as tva
from trading_bot.research.small_capital_v1 import sma

__all__ = [
    "BAR_SECONDS",
    "CONTRACT_INTERVALS",
    "G_REAL_MARKET_CONTEXT",
    "PILOT_ASSETS",
    "PROVIDER",
    "PROVIDER_SYMBOLS",
    "REAL_SOURCE_TYPE",
    "build_real_snapshot_artifact",
    "completed_rows",
    "daily_bars",
    "evaluate_g_real_market_context",
    "fetch_provider_ohlcv",
    "last_completed_close",
    "provider_symbol",
    "to_contract_bars",
]

PROVIDER = "binance_public_ccxt"
REAL_SOURCE_TYPE = "REAL_MARKET_DATA"

#: Pilot universe — deliberately two assets only.
PILOT_ASSETS: tuple[str, ...] = ("BINANCE:BTCUSDT", "BINANCE:ETHUSDT")
PROVIDER_SYMBOLS: dict[str, str] = {
    "BINANCE:BTCUSDT": "BTC/USDT",
    "BINANCE:ETHUSDT": "ETH/USDT",
}

#: Contract interval -> (ccxt interval, seconds per bar).
CONTRACT_INTERVALS: dict[str, tuple[str, int]] = {
    "1h": ("1h", 3_600),
    "4h": ("4h", 14_400),
    "1D": ("1d", 86_400),
}
BAR_SECONDS: dict[str, int] = {key: value[1] for key, value in CONTRACT_INTERVALS.items()}

#: Fetch depth: enough 1D history for the SMA(200) baseline, with margin.
FETCH_LIMITS: dict[str, int] = {"1h": 1_000, "4h": 500, "1D": 500}

#: A snapshot built at a 4H boundary is fresh while its newest close is <= 4h old.
MAX_FRESHNESS_SECONDS = 4 * 3_600

G_REAL_MARKET_CONTEXT = "G_REAL_MARKET_CONTEXT"


def provider_symbol(asset: str) -> str:
    try:
        return PROVIDER_SYMBOLS[asset]
    except KeyError as exc:  # pragma: no cover - guarded by the pilot universe
        raise ValueError(f"{asset!r} is not in the pilot universe") from exc


def make_connector() -> CCXTExchangeConnector:
    """Real, read-only, credential-free provider. Sandbox OFF = real market."""
    return CCXTExchangeConnector(Exchange(id="binance", sandbox=False))


def fetch_provider_ohlcv(
    connector: CCXTExchangeConnector, asset: str, interval_key: str
) -> list[OHLCV]:
    ccxt_interval = CONTRACT_INTERVALS[interval_key][0]
    return connector.fetch_ohlcv(
        provider_symbol(asset), ccxt_interval, limit=FETCH_LIMITS[interval_key]
    )


def completed_rows(
    rows: Sequence[OHLCV], *, decision_ms: int, interval_key: str
) -> list[OHLCV]:
    """Only bars that had fully closed at ``decision_ms`` (never the live one)."""
    bar_ms = BAR_SECONDS[interval_key] * 1_000
    kept = [row for row in rows if int(row.timestamp) + bar_ms <= decision_ms]
    kept.sort(key=lambda row: row.timestamp)
    return kept


def last_completed_close(rows: Sequence[OHLCV], *, interval_key: str) -> int:
    """Close time (unix seconds) of the newest completed bar."""
    if not rows:
        raise ValueError("no completed bars to close")
    return int(rows[-1].timestamp) // 1_000 + BAR_SECONDS[interval_key]


def to_contract_bars(rows: Sequence[OHLCV]) -> list[dict[str, float | int]]:
    """Map provider rows onto the adapter's ``get_ohlcv`` bar shape."""
    return [
        {
            "t": int(row.timestamp) // 1_000,
            "o": float(row.open),
            "h": float(row.high),
            "l": float(row.low),
            "c": float(row.close),
            "v": float(row.volume),
        }
        for row in rows
    ]


def daily_bars(rows: Sequence[OHLCV]) -> list[ab.DailyBar]:
    """RFC-039 daily bars (open time seconds + close) for the SMA(200) baseline."""
    return [ab.DailyBar(open_time=int(row.timestamp) // 1_000, close=float(row.close)) for row in rows]


# --------------------------------------------------------------------------- #
# deterministic, bar-derived features (only indicators the repo already has)
# --------------------------------------------------------------------------- #


def technicals_from_rows(rows: Sequence[OHLCV]) -> dict[str, float]:
    """RSI/MACD/Momentum/SMA50/EMA200 from existing indicators, causal only.

    A field is omitted (never faked) when there is not enough history.
    """
    payload: dict[str, float] = {}
    if len(rows) >= 15:
        payload["RSI"] = float(RsiIndicator().compute(rows, {"period": 14}))
    if len(rows) >= 35:
        payload["MACD"] = float(
            MacdIndicator().compute(rows, {"fast": 12, "slow": 26, "signal": 9})["macd"]
        )
    if len(rows) >= 21:
        payload["Momentum"] = float(MomentumIndicator().compute(rows, {"lookback": 20}))
    closes: list[float | None] = [float(row.close) for row in rows]
    if len(closes) >= 50:
        sma50 = sma(closes, 50)[-1]
        if sma50 is not None:
            payload["SMA50"] = float(sma50)
    if len(rows) >= 200:
        payload["EMA200"] = float(EmaIndicator().compute(rows, {"period": 200}))
    return payload


def deterministic_regime(rows_4h: Sequence[OHLCV]) -> str:
    """Price-structure regime label (deterministic, never analyst-invented)."""
    trend = tva.trend_of(to_contract_bars(rows_4h))
    volatility = 0.0
    if len(rows_4h) >= 31:
        volatility = float(VolatilityIndicator().compute(rows_4h, {"lookback": 30}))
    if volatility <= 0.0:
        vol_label = "unknown_volatility"
    elif volatility < 0.01:
        vol_label = "low_volatility"
    elif volatility > 0.02:
        vol_label = "high_volatility"
    else:
        vol_label = "mid_volatility"
    return f"trend_{trend}_{vol_label}"


def return_over(rows: Sequence[OHLCV], lookback: int) -> float:
    if len(rows) < 2:
        return 0.0
    span = rows[-(lookback + 1) :]
    start, end = float(span[0].close), float(span[-1].close)
    return 0.0 if start <= 0.0 else end / start - 1.0


def relative_strength_value(asset_rows_4h: Sequence[OHLCV], reference_rows_4h: Sequence[OHLCV]) -> float:
    return return_over(asset_rows_4h, 30) - return_over(reference_rows_4h, 30)


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# snapshot + raw evidence
# --------------------------------------------------------------------------- #


def build_real_snapshot_artifact(
    *,
    asset: str,
    decision_time: int,
    rows_by_interval: dict[str, list[OHLCV]],
    reference_asset: str = "BINANCE:BTCUSDT",
    reference_rows_4h: Sequence[OHLCV] | None = None,
) -> dict[str, Any]:
    """Assemble a real :class:`MarketSnapshot` + its provenance artefact.

    The snapshot itself is built by the existing CAP-001 adapter
    (:func:`trading_bot.research.tradingview_mcp_adapter.build_snapshot`); this
    function only supplies real bars and deterministic features.
    """
    ohlcv_by_interval: dict[str, Any] = {}
    source_timestamps: list[int] = []
    for interval_key in CONTRACT_INTERVALS:
        rows = rows_by_interval.get(interval_key, [])
        if not rows:
            raise ValueError(f"missing real {interval_key} bars for {asset}")
        ohlcv_by_interval[interval_key] = to_contract_bars(rows)
        source_timestamps.append(last_completed_close(rows, interval_key=interval_key))

    technicals = technicals_from_rows(rows_by_interval["4h"])
    rows_4h = rows_by_interval["4h"]
    ref_rows = reference_rows_4h if reference_rows_4h is not None else rows_4h
    snapshot = tva.build_snapshot(
        asset=asset,
        snapshot_at=decision_time,
        ohlcv_by_interval=ohlcv_by_interval,
        technicals_payload=technicals,
        news_payload={},
        macro_payload=[],
        market_regime=deterministic_regime(rows_4h),
        reference_symbol=reference_asset,
        relative_strength_value=relative_strength_value(rows_4h, ref_rows),
        source_timestamps=source_timestamps,
    )
    problems = ac.validate_snapshot(snapshot)
    raw_evidence = {
        "source_type": REAL_SOURCE_TYPE,
        "provider": PROVIDER,
        "asset": asset,
        "provider_symbol": provider_symbol(asset),
        "decision_time": decision_time,
        "intervals": {
            key: {
                "bar_seconds": BAR_SECONDS[key],
                "n_completed": len(rows_by_interval.get(key, [])),
                "first_open_time": int(rows_by_interval[key][0].timestamp) // 1_000,
                "last_open_time": int(rows_by_interval[key][-1].timestamp) // 1_000,
                "last_close_time": last_completed_close(rows_by_interval[key], interval_key=key),
                "bars": to_contract_bars(rows_by_interval[key]),
            }
            for key in CONTRACT_INTERVALS
        },
    }
    raw_hash = _digest(raw_evidence)
    snapshot_hash = ac.payload_digest(snapshot.to_dict())
    return {
        "asset": asset,
        "source_type": REAL_SOURCE_TYPE,
        "provider": PROVIDER,
        "synthetic": False,
        "credentialed_source": False,
        "decision_time": decision_time,
        "snapshot": snapshot.to_dict(),
        "snapshot_hash": snapshot_hash,
        "raw_evidence_hash": raw_hash,
        "validation_problems": problems,
        "usable": ac.snapshot_is_usable(snapshot),
        "technicals": technicals,
        "reference_symbol": reference_asset,
        "derived": {
            "market_regime": snapshot.market_regime,
            "relative_strength": snapshot.relative_strength.value,
            "multi_timeframe_trends": {tf.interval: tf.trend for tf in snapshot.multi_timeframe},
            "daily_bars_for_sma200": len(rows_by_interval.get("1D", [])),
        },
        "raw_evidence": raw_evidence,
    }


# --------------------------------------------------------------------------- #
# the replacement gate
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    passed: bool
    detail: str = ""


def evaluate_g_real_market_context(artifact: dict[str, Any], *, snapshot_at: int) -> dict[str, Any]:
    """``G_REAL_MARKET_CONTEXT`` — PASS only on a fully real, causal snapshot.

    TradingView's ``G_TV_CONTEXT`` is untouched and still ``NOT_VERIFIED``; it is
    simply not required for this pilot.
    """
    raw = artifact["raw_evidence"]
    intervals = raw["intervals"]
    snapshot = artifact["snapshot"]

    checks: list[GateCheck] = []
    checks.append(
        GateCheck(
            "REAL_MARKET_SOURCE",
            artifact["source_type"] == REAL_SOURCE_TYPE and artifact["provider"] == PROVIDER,
            artifact["provider"],
        )
    )
    checks.append(GateCheck("SYNTHETIC_CERTIFICATION_FALSE", artifact["synthetic"] is False))
    checks.append(
        GateCheck(
            "OHLCV_1H_4H_1D",
            all(int(intervals[key]["n_completed"]) > 0 for key in CONTRACT_INTERVALS),
        )
    )
    checks.append(
        GateCheck(
            "DAILY_HISTORY_FOR_SMA200",
            int(intervals["1D"]["n_completed"]) >= 200,
            str(intervals["1D"]["n_completed"]),
        )
    )
    completed_ok = True
    for key, bar_seconds in BAR_SECONDS.items():
        for bar in intervals[key]["bars"]:
            if int(bar["t"]) + bar_seconds > snapshot_at:
                completed_ok = False
    checks.append(GateCheck("COMPLETED_BAR_ENFORCEMENT", completed_ok))
    last_close = max(int(intervals[key]["last_close_time"]) for key in CONTRACT_INTERVALS)
    checks.append(
        GateCheck(
            "FRESHNESS",
            0 <= snapshot_at - last_close <= MAX_FRESHNESS_SECONDS,
            f"age_seconds={snapshot_at - last_close}",
        )
    )
    checks.append(
        GateCheck(
            "TIMESTAMP_CAUSALITY",
            all(
                int(intervals[key]["last_open_time"]) + BAR_SECONDS[key] <= snapshot_at
                for key in CONTRACT_INTERVALS
            ),
        )
    )
    checks.append(GateCheck("SCHEMA_VALID", artifact["validation_problems"] == []))
    checks.append(GateCheck("SNAPSHOT_HASH", len(artifact["snapshot_hash"]) == 64))
    checks.append(GateCheck("RAW_EVIDENCE_FINGERPRINT", len(artifact["raw_evidence_hash"]) == 64))
    checks.append(
        GateCheck(
            "TECHNICALS_FROM_REPO",
            bool(artifact["technicals"]),
            ",".join(sorted(artifact["technicals"])),
        )
    )
    checks.append(
        GateCheck(
            "NO_INVENTED_CONTEXT",
            not snapshot["news"] and not snapshot["macro_events"],
        )
    )

    passed = all(check.passed for check in checks)
    return {
        "gate": G_REAL_MARKET_CONTEXT,
        "status": "PASS" if passed else "FAIL",
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks],
        "failed": [c.name for c in checks if not c.passed],
        "g_tv_context": ac.G_TV_CONTEXT,
    }
