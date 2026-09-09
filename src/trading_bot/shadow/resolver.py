"""Shadow PIT resolution for POC02 (§9 — SHADOW V2).

Resolves PENDING ShadowCandidateCapture records against REAL public
binanceusdm 5m bars. Strictly observational and isolated:

- fetches PUBLIC OHLCV only (no credentials, no order-capable calls);
- every bar handed to the outcome engine is strictly AFTER the capture's
  ``decision_time`` PIT anchor (the engine re-filters defensively);
- captures without enough post-decision bars stay PENDING — never
  synthesized, never back-filled with later campaign data;
- no PaperBroker / RiskManager / portfolio / accounting contact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.shadow.integration import ShadowCaptureHook
from trading_bot.shadow.outcome import ShadowBar

__all__ = ["resolve_pending_shadow_captures"]


def _fetch_public_bars_binanceusdm(
    symbol: str, start_ms: int, end_ms: int
) -> list[OHLCV]:
    """Fetch public binanceusdm 5m bars in [start_ms, end_ms]."""
    import ccxt

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        rows: list[list[Any]] = []
        since = start_ms
        # paginate 1500-bar windows to cover the full horizon
        while since < end_ms:
            chunk = exchange.fetch_ohlcv(
                symbol, timeframe="5m", since=since, limit=1500
            )
            if not chunk:
                break
            rows.extend(chunk)
            last_ts = int(chunk[-1][0])
            if last_ts <= since:
                break
            since = last_ts + 60_000
        return [
            OHLCV(
                symbol=symbol,
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
            if row[0] <= end_ms
        ]
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()


def resolve_pending_shadow_captures(
    *,
    captures_path: Path,
    outcomes_path: Path,
    horizon_hours: int = 48,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve captures whose 48h horizon has data available.

    Returns a summary dict; appends only NEW outcomes (ledger-guarded by
    ``shadow_candidate_id`` — duplicates raise and are pre-filtered here).
    """
    hook = ShadowCaptureHook(
        captures_path=captures_path,
        outcomes_path=outcomes_path,
    )
    now = now or datetime.now(UTC)
    already_resolved = {t.decision_id for t in hook.outcomes.trades}
    pending = [
        c
        for c in hook.captures.captures
        if c.decision_id not in already_resolved
    ]
    summary: dict[str, Any] = {
        "captures_total": len(hook.captures.captures),
        "already_resolved": len(already_resolved),
        "pending_before": len(pending),
        "resolved_now": 0,
        "kept_pending": 0,
        "skipped_insufficient_bars": 0,
        "errors": [],
    }
    if not pending:
        return summary

    resolved_ids = set(already_resolved)
    for capture in pending:
        try:
            decision_dt = datetime.fromisoformat(
                capture.decision_time.replace("Z", "+00:00")
            )
        except ValueError as exc:
            summary["errors"].append(f"{capture.decision_id}: {exc}")
            continue
        start_ms = int(decision_dt.timestamp() * 1000) + 1
        end_ms = min(
            int((decision_dt + timedelta(hours=horizon_hours)).timestamp() * 1000),
            int(now.timestamp() * 1000),
        )
        if end_ms <= start_ms:
            summary["kept_pending"] += 1  # horizon not yet reachable
            continue
        try:
            bars = _fetch_public_bars_binanceusdm(
                capture.asset, start_ms, end_ms
            )
        except Exception as exc:  # provider error: loud, capture stays PENDING
            summary["errors"].append(
                f"{capture.decision_id}: {type(exc).__name__}: {exc}"
            )
            continue
        if not bars:
            summary["skipped_insufficient_bars"] += 1
            continue
        shadow_bars = [
            ShadowBar(
                time=datetime.fromtimestamp(b.timestamp / 1000, tz=UTC).isoformat(),
                high=b.high,
                low=b.low,
                close=b.close,
            )
            for b in bars
        ]
        try:
            trades = hook.resolve_pending(
                {capture.decision_id: shadow_bars},
            )
        except ValueError as exc:
            # duplicate / plan inconsistency: recorded, never invented
            summary["errors"].append(f"{capture.decision_id}: {exc}")
            continue
        summary["resolved_now"] += len(trades)
        for trade in trades:
            resolved_ids.add(trade.decision_id)

    summary["resolved_total_after"] = len(hook.outcomes.trades)
    summary["pending_after"] = summary["captures_total"] - len(hook.outcomes.trades)
    return summary
