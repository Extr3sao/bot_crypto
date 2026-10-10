"""RFC-048 — derive InstrumentSpec fixtures from the venue's own raw payloads.

Reads the raw payloads already stored in ``data/rfc048/raw/`` (fetched once, no
credentials, public market-data endpoints only) and writes:

* ``data/rfc048/INSTRUMENTS.json``      — instrument contracts + provenance
* ``data/rfc048/MARKET_SNAPSHOT.json``  — mark/index/last, spread, book depth
* ``data/rfc048/FUNDING_HISTORY.json``  — point-in-time funding observations
* ``data/rfc048/PROVENANCE.json``       — sha256 of every raw source consumed

Nothing here invents a number: every field is either copied from a named raw
payload, derived by an arithmetic rule stated next to it, or explicitly marked
``null``/``declared_not_fetched`` so the engine refuses to use it.

    uv run python scripts/rfc048_derive_instruments.py
"""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "rfc048" / "raw"
OUT = ROOT / "data" / "rfc048"

#: Sources consumed by this derivation. Each must exist on disk.
SOURCES: dict[str, str] = {
    "exchange_info": "binance_usdm_exchange_info.json",
    "leverage_brackets": "binance_usdm_leverage_brackets_btcusdt.json",
    "premium_index": "binance_usdm_premium_index_btcusdt.json",
    "depth": "binance_usdm_depth_btcusdt_100.json",
    "funding_rate": "binance_usdm_funding_rate_btcusdt.json",
    "klines_5m": "binance_usdm_btcusdt_5m_klines.json",
    "esma_statement": "esma_cfd_product_intervention_2026-02-24.html",
}

SOURCE_URLS: dict[str, str] = {
    "exchange_info": "https://fapi.binance.com/fapi/v1/exchangeInfo",
    "leverage_brackets": (
        "https://www.binance.com/bapi/futures/v1/friendly/future/common/brackets?symbol=BTCUSDT"
    ),
    "premium_index": "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT",
    "depth": "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100",
    "funding_rate": "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=200",
    "klines_5m": "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=1000",
    "esma_statement": (
        "https://www.esma.europa.eu/press-news/esma-news/"
        "esma-reminds-firms-their-obligations-under-cfd-product-intervention-measures"
    ),
}

#: The one instrument this RFC implements. Symbol literal, never inferred.
SUPPORTED_SYMBOL = "BTCUSDT"
#: A real, listed quarterly contract used to prove DELIVERY_FUTURE is refused.
UNSUPPORTED_DELIVERY_SYMBOL = "BTCUSDT_261225"

#: Published VIP0 USDⓈ-M fee schedule (venue documentation, not an authenticated
#: read of this account). Kept as ESTIMATED by the cost model, never as KNOWN.
PUBLISHED_FEE_SCHEDULE_BPS = {"maker": 2.0, "taker": 5.0}
PUBLISHED_FEE_SOURCE = "https://www.binance.com/en/fee/futureFee (VIP0 USDⓈ-M, published)"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(name: str) -> Any:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def filter_of(symbol: dict[str, Any], kind: str) -> dict[str, Any]:
    filters: list[dict[str, Any]] = symbol["filters"]
    for f in filters:
        if f["filterType"] == kind:
            return f
    raise KeyError(f"{symbol['symbol']}: missing filter {kind}")


def build_brackets(payload: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    for entry in payload["data"]["brackets"]:
        if entry["symbol"] == symbol:
            return [
                {
                    "bracket_seq": r["bracketSeq"],
                    "notional_floor": float(r["bracketNotionalFloor"]),
                    "notional_cap": float(r["bracketNotionalCap"]),
                    "maintenance_margin_rate": float(r["bracketMaintenanceMarginRate"]),
                    "cum_maintenance_amount": float(r["cumFastMaintenanceAmount"]),
                    "max_open_pos_leverage": int(r["maxOpenPosLeverage"]),
                    "min_open_pos_leverage": int(r["minOpenPosLeverage"]),
                }
                for r in entry["riskBrackets"]
            ]
    raise KeyError(f"no brackets for {symbol}")


def funding_interval_ms(records: list[dict[str, Any]]) -> int | None:
    """Funding interval observed in the venue's own settlement timestamps.

    The venue stamps settlements with millisecond jitter (+/-13 ms observed), so
    each delta is rounded to the second and ALL deltas must resolve to a single
    value. A real gap (a missing settlement) changes the delta by hours and is
    therefore rejected instead of averaged away.
    """
    times = sorted(int(r["fundingTime"]) for r in records)
    deltas = {round((b - a) / 1000.0) * 1000 for a, b in pairwise(times) if b > a}
    if len(deltas) != 1:
        return None
    return deltas.pop()


def main() -> int:
    provenance: dict[str, Any] = {"sources": {}}
    for key, filename in SOURCES.items():
        raw = (RAW / filename).read_bytes()
        provenance["sources"][key] = {
            "url": SOURCE_URLS[key],
            "file": f"data/rfc048/raw/{filename}",
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
        }

    exchange_info = load(SOURCES["exchange_info"])
    brackets_payload = load(SOURCES["leverage_brackets"])
    premium = load(SOURCES["premium_index"])
    depth = load(SOURCES["depth"])
    funding_records = load(SOURCES["funding_rate"])
    klines = load(SOURCES["klines_5m"])

    symbols = {s["symbol"]: s for s in exchange_info["symbols"]}
    perp = symbols[SUPPORTED_SYMBOL]
    price_filter = filter_of(perp, "PRICE_FILTER")
    lot = filter_of(perp, "LOT_SIZE")
    market_lot = filter_of(perp, "MARKET_LOT_SIZE")
    min_notional = filter_of(perp, "MIN_NOTIONAL")

    interval = funding_interval_ms(funding_records)
    if interval is None:
        raise SystemExit("funding interval is not a single value; refusing to guess")

    brackets = build_brackets(brackets_payload, SUPPORTED_SYMBOL)

    if perp["contractType"] != "PERPETUAL" or perp["marginAsset"] != "USDT":
        raise SystemExit(f"{SUPPORTED_SYMBOL} is not a USDT-margined PERPETUAL: {perp}")

    supported = {
        "instrument_id": "BINANCE_USDM_BTCUSDT_PERP",
        "venue": "BINANCE_USDM",
        "venue_symbol": SUPPORTED_SYMBOL,
        "contract_type": "LINEAR_PERPETUAL",
        "collateral_asset": perp["marginAsset"],
        "settlement_asset": perp["marginAsset"],
        "base_asset": perp["baseAsset"],
        "quote_asset": perp["quoteAsset"],
        # contractMultiplier is absent from the venue payload for BTCUSDT; the
        # default of 1 is recorded as DECLARED rather than derived from the read.
        "contract_multiplier": 1.0,
        "contract_multiplier_source": "venue_absent_default_1.0",
        "quantity_step": float(lot["stepSize"]),
        "quantity_min": float(lot["minQty"]),
        "quantity_max": float(market_lot["maxQty"]),
        "price_tick": float(price_filter["tickSize"]),
        "price_precision": int(perp["pricePrecision"]),
        "quantity_precision": int(perp["quantityPrecision"]),
        "minimum_notional": float(min_notional["notional"]),
        "maximum_notional": None,
        "initial_margin_schedule": {
            "mode": "isolated_only",
            "venue_required_margin_percent": float(perp["requiredMarginPercent"]),
            "venue_maintenance_margin_percent": float(perp["maintMarginPercent"]),
            "note": (
                "requiredMarginPercent/maintMarginPercent are the venue's symbol-level "
                "defaults; the binding schedule is maintenance_margin_brackets below."
            ),
        },
        "maintenance_margin_brackets": brackets,
        "fee_schedule": {
            "maker_bps": PUBLISHED_FEE_SCHEDULE_BPS["maker"],
            "taker_bps": PUBLISHED_FEE_SCHEDULE_BPS["taker"],
            "source": PUBLISHED_FEE_SOURCE,
            "verified_against_account": False,
        },
        "funding_schedule": {
            "interval_ms": interval,
            "interval_source": "observed_delta_of_fundingRate_endpoint",
            "observed_rate_count": len(funding_records),
        },
        "liquidation_fee_rate": float(perp["liquidationFee"]),
        "supported_position_modes": ["ONE_WAY", "ISOLATED"],
        "regulatory_eligibility_status": "PRODUCT_ELIGIBILITY_UNKNOWN",
        "regulatory_note": (
            "ESMA statement 24/02/2026 (ESMA35-243228190-8024): derivatives marketed "
            "as perpetual futures may fall within the scope of national CFD product "
            "intervention measures (leverage limits, margin close-out, negative balance "
            "protection). Offline research on venue fixtures is allowed; promotion to "
            "production is blocked while eligibility is unverified."
        ),
        "research_allowed": True,
        "production_eligible": False,
        "source_version": f"exchangeInfo:{exchange_info.get('serverTime')}",
        "source_hash": provenance["sources"]["exchange_info"]["sha256"],
        "source_hash_brackets": provenance["sources"]["leverage_brackets"]["sha256"],
        "effective_timestamp_ms": int(exchange_info.get("serverTime", 0)),
    }

    delivery_meta = symbols[UNSUPPORTED_DELIVERY_SYMBOL]
    delivery = {
        "instrument_id": f"BINANCE_USDM_{UNSUPPORTED_DELIVERY_SYMBOL}",
        "venue": "BINANCE_USDM",
        "venue_symbol": UNSUPPORTED_DELIVERY_SYMBOL,
        "contract_type": "DELIVERY_FUTURE",
        "collateral_asset": delivery_meta["marginAsset"],
        "settlement_asset": delivery_meta["marginAsset"],
        "base_asset": delivery_meta["baseAsset"],
        "quote_asset": delivery_meta["quoteAsset"],
        "contract_multiplier": 1.0,
        "quantity_step": float(filter_of(delivery_meta, "LOT_SIZE")["stepSize"]),
        "quantity_min": float(filter_of(delivery_meta, "LOT_SIZE")["minQty"]),
        "price_tick": float(filter_of(delivery_meta, "PRICE_FILTER")["tickSize"]),
        "minimum_notional": float(filter_of(delivery_meta, "MIN_NOTIONAL")["notional"]),
        "maintenance_margin_brackets": [],
        "fee_schedule": None,
        "funding_schedule": None,
        "supported_position_modes": [],
        "regulatory_eligibility_status": "PRODUCT_ELIGIBILITY_UNKNOWN",
        "research_allowed": True,
        "production_eligible": False,
        "source_version": f"exchangeInfo:{exchange_info.get('serverTime')}",
        "source_hash": provenance["sources"]["exchange_info"]["sha256"],
        "effective_timestamp_ms": int(exchange_info.get("serverTime", 0)),
        "unsupported_reason": (
            "delivery futures settle at expiry and carry a settlement mechanics this RFC "
            "did not model (no expiry handling, no delivery margin path). Parameters were "
            "read from the venue fixture and are registered, but the contract type is "
            "refused with INSTRUMENT_NOT_SUPPORTED."
        ),
    }

    inverse: dict[str, Any] = {
        "instrument_id": "BINANCE_COINM_BTCUSD_PERP",
        "venue": "BINANCE_COINM",
        "venue_symbol": "BTCUSD_PERP",
        "contract_type": "INVERSE_PERPETUAL",
        "collateral_asset": "BTC",
        "settlement_asset": "BTC",
        "base_asset": "BTC",
        "quote_asset": "USD",
        "contract_multiplier": None,
        "quantity_step": None,
        "price_tick": None,
        "minimum_notional": None,
        "maintenance_margin_brackets": [],
        "fee_schedule": None,
        "funding_schedule": None,
        "supported_position_modes": [],
        "regulatory_eligibility_status": "PRODUCT_ELIGIBILITY_UNKNOWN",
        "research_allowed": True,
        "production_eligible": False,
        "source_version": "declared_not_fetched",
        "source_hash": None,
        "effective_timestamp_ms": None,
        "unsupported_reason": (
            "inverse contracts are coin-margined and their PnL/liquidation algebra is not "
            "the linear one. No fixture was fetched, so no parameter is available and no "
            "linear formula may be applied to it. Refused with INSTRUMENT_NOT_SUPPORTED."
        ),
    }

    instruments: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": "scripts/rfc048_derive_instruments.py",
        "generated_at_utc": _utc(int(exchange_info.get("serverTime", 0))),
        "supported_contract_types": ["LINEAR_PERPETUAL"],
        "unsupported_contract_types": [
            "INVERSE_PERPETUAL",
            "DELIVERY_FUTURE",
            "LINEAR_DELIVERY_FUTURE",
        ],
        "position_modes_supported": ["ISOLATED"],
        "position_modes_unsupported": ["CROSS"],
        "instruments": [supported, delivery, inverse],
    }

    best_bid = float(depth["bids"][0][0])
    best_ask = float(depth["asks"][0][0])
    mid = (best_bid + best_ask) / 2.0
    bids = [(float(p), float(q)) for p, q in depth["bids"]]
    asks = [(float(p), float(q)) for p, q in depth["asks"]]
    last_close = float(klines[-1][4])

    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "instrument_id": supported["instrument_id"],
        "source_hash": provenance["sources"]["depth"]["sha256"],
        "source_hash_klines": provenance["sources"]["klines_5m"]["sha256"],
        "source_hash_premium": provenance["sources"]["premium_index"]["sha256"],
        "data_timestamp_ms": int(depth["E"]),
        "last_price": last_close,
        "mark_price": float(premium["markPrice"]),
        "index_price": float(premium["indexPrice"]),
        "estimated_settle_price": float(premium["estimatedSettlePrice"]),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid,
        "spread_bps": round((best_ask - best_bid) / mid * 10_000.0, 6),
        "depth_bids": bids,
        "depth_asks": asks,
        "bid_notional_top100": round(sum(p * q for p, q in bids), 2),
        "ask_notional_top100": round(sum(p * q for p, q in asks), 2),
        "klines_5m": [
            {
                "open_time_ms": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time_ms": int(k[6]),
            }
            for k in klines
        ],
    }

    funding: dict[str, Any] = {
        "schema_version": 1,
        "instrument_id": supported["instrument_id"],
        "source_hash": provenance["sources"]["funding_rate"]["sha256"],
        "interval_ms": interval,
        "observations": [
            {
                "funding_time_ms": int(r["fundingTime"]),
                "funding_rate": float(r["fundingRate"]),
                "mark_price": float(r["markPrice"]),
                "rate_type": r.get("rateType"),
            }
            for r in sorted(funding_records, key=lambda r: int(r["fundingTime"]))
        ],
    }

    provenance["derived"] = {
        "instruments": {
            "supported_instrument_id": supported["instrument_id"],
            "bracket_count": len(brackets),
            "max_bracket_notional_cap": brackets[-1]["notional_cap"],
        },
        "snapshot": {
            "data_timestamp_ms": snapshot["data_timestamp_ms"],
            "spread_bps": snapshot["spread_bps"],
            "kline_count": len(snapshot["klines_5m"]),
        },
        "funding": {
            "interval_ms": interval,
            "observation_count": len(funding["observations"]),
            "first_funding_time_ms": funding["observations"][0]["funding_time_ms"],
            "last_funding_time_ms": funding["observations"][-1]["funding_time_ms"],
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "INSTRUMENTS.json", instruments)
    _write(OUT / "MARKET_SNAPSHOT.json", snapshot)
    _write(OUT / "FUNDING_HISTORY.json", funding)
    _write(OUT / "PROVENANCE.json", provenance)

    print(f"instruments: {len(instruments['instruments'])} (supported: 1)")
    print(f"brackets: {len(brackets)}  funding interval: {interval} ms")
    print(f"snapshot: {snapshot['data_timestamp_ms']} spread {snapshot['spread_bps']} bps")
    print(f"klines: {len(snapshot['klines_5m'])} funding obs: {len(funding['observations'])}")
    return 0


def _utc(ms: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000.0, tz=datetime.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
