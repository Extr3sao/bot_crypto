"""WP-PAPER-REAL-DATA-001 — the PAPER campaign against real public market data.

Why this file exists
--------------------
``scripts/autonomous_paper.py`` builds its market-data source from
``--provider {ccxt,fake}``. Neither option yields *real production* bars in
PAPER mode:

* ``ccxt`` composes a venue session through ``resolve_scanner_source``, and
  ``Settings`` forbids ``runtime.mode='paper'`` with ``sandbox=false``
  (``settings.py``: "runtime.mode='paper' exige sandbox=true"). Testnet bars are
  a simulated feed, so they cannot validate market data.
* ``fake`` is deterministic by construction.

That guard is governance, not an obstacle to route around: PAPER must not open
a live venue session. So this harness leaves the guard **exactly as it is** and
uses the composition seam the runtime already exposes — ``scanner_factory`` /
``history_reader`` injection — to feed the campaign from a read-only public
data client that opens no venue session at all.

What is replaced, and what is not
---------------------------------
Replaced: one function, ``build_scanner_factory``, so the campaign reads from
``PublicKlinesSource`` (public REST: klines / ticker / bookTicker, zero
credentials) instead of opening a venue session.

The run is still invoked with ``--provider ccxt`` because that is the client
library doing the reading (and the entrypoint's argparse vocabulary has no
third option). It is NOT the runtime's venue connector: the fetch journal
(``--audit-jsonl``) labels every request ``provider=binance-public-rest``,
``authenticated=false``, and the verifier asserts the process logs contain no
``multi_exchange.call.*`` line — i.e. no connector session was ever opened.

Everything else is the production entrypoint's own code, imported unmodified:
``build_settings``, ``AdmissionLedger.load``, ``StrategyRegistry.from_ledger``,
``preflight_run_universe``, ``FetcherBarReader`` (closed-candle filter),
``PaperBroker``, ``RiskManager``, ``StartupReconcilerV4``, the
``AutonomousPaperRuntime`` cycle, the heartbeat, the daily report, the run
report and the run descriptor. No module under ``src/`` is patched.

Every fetch is journalled (``--audit-jsonl``) with the digest of the exact rows
returned, so an independent verifier can recompute the PIT invariant from the
artefacts instead of trusting this file.

Usage::

    uv run python scripts/wp_prd001_campaign.py \
        --cycles 3 --timeframe 1h --assets BTC,ETH,SOL \
        --run-root <evidence>/raw/runs --state-path <evidence>/raw/paper_state.json \
        --audit-jsonl <evidence>/raw/DATA_ACCESS.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import autonomous_paper as entrypoint  # noqa: E402  (the production entrypoint)

TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def _iso(ts_ms: int | None) -> str | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows_digest(rows: list[Any]) -> str:
    payload = json.dumps(
        [[int(b.timestamp), float(b.open), float(b.high), float(b.low), float(b.close), float(b.volume)]
         for b in rows],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PublicKlinesSource:
    """``MarketDataSourceProtocol`` over the exchange's PUBLIC read-only routes.

    No apiKey, no secret, no signature, no order endpoint. The client is CCXT
    because that is the library the runtime's own connector is built on; the
    *session* type is what differs — this is a data client, not a venue session.
    """

    provider = "binance-public-rest"

    def __init__(self, *, timeframe: str, audit_path: Path | None = None) -> None:
        import ccxt

        self.timeframe = timeframe
        self._tf_ms = TIMEFRAME_MS[timeframe]
        self._audit = audit_path
        self._exchange = ccxt.binance(
            {"enableRateLimit": True, "apiKey": "", "secret": "", "timeout": 15_000}
        )
        if audit_path is not None:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text("", encoding="utf-8")

    # -- provider preflight half (§39/DEF-AUTO-2) ---------------------------
    @property
    def markets(self) -> dict[str, Any]:
        return getattr(self._exchange, "markets", None) or {}

    def load_markets(self) -> None:
        self._exchange.load_markets()

    # -- MarketDataSourceProtocol ------------------------------------------
    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[Any]:
        from trading_bot.market_data.types import OHLCV

        requested_ms = int(time.time() * 1000)
        raw = await asyncio.to_thread(
            self._exchange.fetch_ohlcv, symbol, self.timeframe, None, limit
        )
        received_ms = int(time.time() * 1000)
        bars = [
            OHLCV(
                symbol=symbol,
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in raw
        ]
        self._journal(
            {
                "kind": "fetch_recent",
                "symbol": symbol,
                "timeframe": self.timeframe,
                "requested_ms": requested_ms,
                "received_ms": received_ms,
                "limit": limit,
                "bars": len(bars),
                "first_open_ms": bars[0].timestamp if bars else None,
                "last_open_ms": bars[-1].timestamp if bars else None,
                "last_close_ms": bars[-1].timestamp + self._tf_ms if bars else None,
                "rows_sha256": _rows_digest(bars),
            }
        )
        return bars

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        ticker = await asyncio.to_thread(self._exchange.fetch_ticker, symbol)
        quote = ticker.get("quoteVolume")
        return float(quote) if quote is not None else 0.0

    async def fetch_spread_bps(self, symbol: str) -> float:
        book = await asyncio.to_thread(self._exchange.fetch_order_book, symbol, 5)
        bids, asks = book.get("bids") or [], book.get("asks") or []
        if not bids or not asks:
            return 0.0
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0
        if mid <= 0:
            return 0.0
        return (best_ask - best_bid) / mid * 10_000.0

    # -- journal ------------------------------------------------------------
    def _journal(self, record: dict[str, Any]) -> None:
        if self._audit is None:
            return
        record = {
            **record,
            "provider": self.provider,
            "authenticated": False,
            "utc": _iso(record["requested_ms"]),
        }
        with self._audit.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def build_public_factory(settings: Any, timeframe: str, audit_path: Path | None):
    """The ONE substitution: the same closure ``autonomous_paper`` builds, sourced publicly."""
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    source = PublicKlinesSource(timeframe=timeframe, audit_path=audit_path)

    def factory() -> Any:
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    return factory, source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-jsonl", default=None)
    known, passthrough = parser.parse_known_args(argv)
    audit_path = Path(known.audit_jsonl) if known.audit_jsonl else None

    # Rebuild the entrypoint's argv: this harness takes no campaign flags of its
    # own beyond the audit journal, so every other argument is the entrypoint's.
    sys.argv = [str(REPO_ROOT / "scripts" / "autonomous_paper.py"), *passthrough]

    timeframe = "5m"
    if "--timeframe" in passthrough:
        timeframe = passthrough[passthrough.index("--timeframe") + 1]

    original_build = entrypoint.build_scanner_factory

    def _factory(settings: Any, provider: str) -> Any:
        if provider != "ccxt":
            raise SystemExit(
                f"this harness only substitutes the ccxt source (got {provider!r}); "
                "the fake provider is the entrypoint's own and stays untouched"
            )
        return build_public_factory(settings, timeframe, audit_path)

    entrypoint.build_scanner_factory = _factory  # type: ignore[assignment]
    try:
        return asyncio.run(entrypoint.main())
    finally:
        entrypoint.build_scanner_factory = original_build  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
