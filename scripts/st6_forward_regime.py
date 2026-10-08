"""ST-6 forward cost regime validation — a declared 14-day, read-only observation period.

The ECONOMIC-001 closure left two defects and one thin premise.  ECO-2 (maker queue position,
realised fill, slippage) is ``UNKNOWN_NOT_RESOLVABLE_OFFLINE`` and stays that way; ECO-1 (the cost
premises were measured only twice) can still be tested forward.  This phase is that test, and
nothing else:

* it **reuses** the two instruments already proven in this repository — the read-only probe
  (``economic001_readonly_probe.collect``: public endpoints, no key, no signature, no order) and
  the ST-6 drift rule (``cost_drift_monitor.judge``: pooled and worst spread against the modelled
  1.0 bps, the 200 USDT depth walk against the modelled 0.25 bps, depth coverage of the account);
* it hangs one **declared** observation period off them: 14 natural days, at most six independent
  windows per day, one per declared 4-hour UTC slot, so the six slots span the Asian, European and
  United States sessions without ever duplicating a measurement;
* it records the **data contract per observation** (asset, both timestamps, bid, ask, spread,
  depth, book age, liquidity, volatility regime, session, weekday/weekend, estimated impact, the
  frozen thresholds, the source and the raw evidence hash) and keeps the original bytes, gzipped,
  with the sha256 of the *uncompressed* bytes so any reader can reproduce them;
* it **never discards** an incomplete or stale window: such a window is written down as such and
  counted as rejected data;
* it classifies the volatility regime of each observation against a **pre-declared** rule derived
  from the frozen 1-hour archive (rolling 24-bar standard deviation of log returns, tertiles), not
  against thresholds chosen after seeing the results;
* it emits ``COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES``, ``COST_MODEL_DRIFT_DETECTED``,
  ``INSUFFICIENT_REGIME_COVERAGE`` or ``DATA_QUALITY_FAILED``, and it never extends its own period
  to reach the first of those: after the declared end only an explicit ``--authorize-extension``
  keeps collecting.

It creates no hypothesis, opens no campaign, sends no order, uses no credential and does not touch
COST_MODEL_V3, the rejected strategies or the trading campaign scheduler.

Run:  python scripts/st6_forward_regime.py --activate          (declare the period once)
      python scripts/st6_forward_regime.py --due               (collect the current slot, if due)
      python scripts/st6_forward_regime.py --collect           (force one window in this slot)
      python scripts/st6_forward_regime.py --rollup-only       (re-roll the artefacts, collect nothing)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import statistics
import subprocess
import sys
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cost_drift_monitor import judge as st6_judge  # noqa: E402  the proven ST-6 drift rule
from cost_drift_monitor import window_metrics  # noqa: E402  the proven window arithmetic
from economic001_readonly_probe import BASE, SYMBOLS, collect  # noqa: E402  the proven probe

DATA = REPO / "data" / "st6"
PERIOD_PATH = DATA / "ST6_PERIOD.json"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
RAW_DIR = DATA / "raw"
COVERAGE_PATH = DATA / "ST6_REGIME_COVERAGE.json"
DRIFT_PATH = DATA / "ST6_MODEL_DRIFT.json"
REPORT_JSON = DATA / "ST6_FORWARD_REGIME_REPORT.json"
REPORT_MD = DATA / "ST6_FORWARD_REGIME_REPORT.md"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
PRICE_DIR = REPO / "data" / "raw" / "alpha003" / "price"

BPS = 10_000.0
PERIOD_DAYS = 14
SLOT_HOURS = 4
SLOTS_PER_DAY = 24 // SLOT_HOURS
ACCOUNT_USDT = 200.0

# The two modelled terms, taken from the frozen model at run time and asserted equal to these
# values: they are read, never chosen here.  COST_MODEL_V3.model_constants.
SPREAD_THRESHOLD_BPS = 1.0
IMPACT_THRESHOLD_BPS = 0.25
BOUNDARY_MULTIPLE = 1.5  # ST-6's declared boundary policy, reused unchanged
MODEL_PATHS = {
    "spread": ("model_constants", "base_slippage_bps"),
    "impact": ("model_constants", "base_impact_bps"),
}

ROUNDS = 3
SPACING_S = 5.0
DEPTH_LIMIT = 100
KLINE_INTERVAL = "1h"
KLINE_LIMIT = 25
KLINE_TIMEOUT_S = 10.0

# A window is a bounded sequence of rounds, so its first round is legitimately as old as the
# window itself when the window closes.  Freshness is therefore judged against the window's DECLARED
# span (budget.rounds x budget.spacing_s) plus a margin: an age inside the declared cadence is by
# construction, an age beyond it means a round took far longer than declared.
MAX_BOOK_AGE_MARGIN_MS = 5_000.0
MAX_LATENCY_MS = 2_000.0  # median round-trip of the observation path, not an execution path
FRESH_WINDOW_S = 900.0  # a window collected more than this long ago no longer describes "now"
MIN_LEVELS_EXPECTED = 20

SESSIONS = (("asia", 0, 8), ("europe", 8, 16), ("us", 16, 24))
VOLATILITY_BANDS = ("LOW", "NORMAL", "HIGH")
LIQUIDITY_BANDS = ("THIN", "NORMAL", "DEEP")

# Declared before any window of this period was collected.  The period can only be closed as
# supported when every one of these holds.
COVERAGE_RULE = {
    "period_days": PERIOD_DAYS,
    "maximum_windows_per_day": SLOTS_PER_DAY,
    "minimum_days_covered": 10,
    "minimum_windows_total": 42,
    "minimum_windows_per_three_sessions": 8,
    "minimum_weekday_windows": 20,
    "minimum_weekend_windows": 4,
    "minimum_distinct_slots": SLOTS_PER_DAY,
    "minimum_distinct_volatility_bands": 2,
    "minimum_asset_presence_fraction": 0.9,
    "maximum_rejected_fraction": 0.2,
}

OUTCOMES = (
    "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
    "COST_MODEL_DRIFT_DETECTED",
    "INSUFFICIENT_REGIME_COVERAGE",
    "DATA_QUALITY_FAILED",
)

STANDING = {
    "DISCOVERY_CAMPAIGN_FAILED": True,
    "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
    "TRADES_AUTHORIZED": 0,
    "LIVE_TRADING": "DISABLED",
    "PROFITABILITY_VERIFIED": False,
    "ECO_2": "UNKNOWN_NOT_RESOLVABLE_OFFLINE",
}


class ModelMismatch(RuntimeError):
    """The frozen cost model no longer carries the thresholds this phase is built on."""


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ms() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _iso_from_ms(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # pragma: no cover - a non-git checkout still produces an artefact
        return "UNKNOWN"


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot take a percentile of nothing")
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def frozen_thresholds(path: Path | None = None) -> dict[str, Any]:
    """Read the two modelled terms out of the frozen model and refuse to disagree with them."""
    model_path = path or COST_MODEL
    model = json.loads(model_path.read_text(encoding="utf-8"))
    read: dict[str, float] = {}
    for key, trail in MODEL_PATHS.items():
        node: Any = model
        for step in trail:
            node = node[step]
        read[key] = float(node)
    if read["spread"] != SPREAD_THRESHOLD_BPS or read["impact"] != IMPACT_THRESHOLD_BPS:
        raise ModelMismatch(
            f"{model_path.name} carries spread {read['spread']} bps and impact {read['impact']} bps, "
            f"but this phase was built on {SPREAD_THRESHOLD_BPS} and {IMPACT_THRESHOLD_BPS}"
        )
    return {
        "spread_bps": read["spread"],
        "impact_bps": read["impact"],
        "boundary_multiple": BOUNDARY_MULTIPLE,
        "source": str(model_path.relative_to(REPO)),
        "model": model.get("model"),
        "model_sha256": _sha256_bytes(model_path.read_bytes()),
        "knowledge_class": model.get("model_constants", {}).get("knowledge"),
        "declared": "read from the frozen model at run time; this phase never writes them",
    }


def session_of(moment: datetime) -> str:
    for name, start, end in SESSIONS:
        if start <= moment.hour < end:
            return name
    raise AssertionError("hour outside every declared session")


def day_type(moment: date | datetime) -> str:
    return "weekend" if moment.weekday() >= 5 else "weekday"


def slot_of(moment: datetime) -> dict[str, Any]:
    index = moment.hour // SLOT_HOURS
    start = index * SLOT_HOURS
    return {
        "slot_index": index,
        "slot": f"{start:02d}:00-{start + SLOT_HOURS:02d}:00 UTC",
        "session": session_of(moment),
        "day": moment.strftime("%Y-%m-%d"),
        "day_type": day_type(moment),
    }


# --------------------------------------------------------------------------------------------
# Volatility regime: pre-declared, derived from the frozen archive, not from the observations.
# --------------------------------------------------------------------------------------------


def _rolling_volatility_bps(closes: list[float], window: int = 24) -> list[float]:
    logs = [
        (closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    import math

    returns = [math.log(value) for value in logs]
    return [
        statistics.pstdev(returns[i : i + window]) * BPS
        for i in range(0, len(returns) - window + 1)
    ]


def volatility_reference(price_dir: Path | None = None) -> dict[str, Any]:
    """Tertiles of the rolling 24-bar volatility over the frozen 1-hour archive, per symbol."""
    directory = price_dir or PRICE_DIR
    series: dict[str, Any] = {}
    for symbol in SYMBOLS:
        path = directory / f"{symbol}_{KLINE_INTERVAL}.json"
        if not path.exists():
            series[symbol] = {"available": False, "reason": f"{path.name} not present"}
            continue
        bars = json.loads(path.read_text(encoding="utf-8"))
        closes = [float(bar[4]) for bar in bars]
        values = _rolling_volatility_bps(closes)
        series[symbol] = {
            "available": True,
            "archive": str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path),
            "archive_sha256": _sha256_bytes(path.read_bytes()),
            "bars": len(bars),
            "first_bar_utc": _iso_from_ms(float(bars[0][0])),
            "last_bar_utc": _iso_from_ms(float(bars[-1][0])),
            "rolling_windows": len(values),
            "p33_bps": round(_percentile(values, 1 / 3), 6),
            "p67_bps": round(_percentile(values, 2 / 3), 6),
            "median_bps": round(statistics.median(values), 6),
        }
    return {
        "rule": (
            "volatility regime = band of the live rolling 24-bar standard deviation of hourly log "
            "returns (in bps) against the tertiles of the same statistic computed over the frozen "
            "1-hour archive: <= p33 LOW, <= p67 NORMAL, above p67 HIGH"
        ),
        "declared_before_observation": True,
        "interval": KLINE_INTERVAL,
        "window_bars": 24,
        "series": series,
    }


def classify_volatility(value: float, reference: dict[str, Any]) -> str:
    if value <= reference["p33_bps"]:
        return "LOW"
    if value <= reference["p67_bps"]:
        return "NORMAL"
    return "HIGH"


def fetch_klines(symbol: str) -> dict[str, Any]:
    """One public, credential-free klines call, for the volatility regime only."""
    import time

    url = f"{BASE}/api/v3/klines?symbol={symbol}&interval={KLINE_INTERVAL}&limit={KLINE_LIMIT}"
    started = _utc_ms()
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=KLINE_TIMEOUT_S) as response:
            payload = response.read()
        rows = json.loads(payload)
        return {
            "symbol": symbol,
            "ok": True,
            "rows": rows,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "observed_at_utc": started,
            "response_sha256": _sha256_bytes(payload),
            "error": None,
        }
    except Exception as exc:  # a failed reading is recorded, never swallowed
        return {
            "symbol": symbol,
            "ok": False,
            "rows": [],
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "observed_at_utc": started,
            "response_sha256": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def live_volatility_bps(rows: list[list[Any]]) -> float | None:
    if len(rows) < 24:
        return None
    closes = [float(row[4]) for row in rows]
    values = _rolling_volatility_bps(closes, window=24)
    return round(values[-1], 6) if values else None


# --------------------------------------------------------------------------------------------
# Depth walk with the detail the data contract needs.
# --------------------------------------------------------------------------------------------


def walk_detail(levels: list[list[float]], notional: float) -> dict[str, Any]:
    """Level-consuming taker walk: cost in bps, levels touched, and whether it filled."""
    if not levels:
        return {"walk_bps": None, "levels_consumed": 0, "filled": False}
    best = levels[0][0]
    remaining, spent, quantity, levels_consumed = notional, 0.0, 0.0, 0
    for price, size in levels:
        take = min(remaining, price * size)
        if take <= 0:
            continue
        spent += take
        quantity += take / price
        remaining -= take
        levels_consumed += 1
        if remaining <= 1e-9:
            break
    if remaining > 1e-9 or quantity <= 0:
        return {"walk_bps": None, "levels_consumed": levels_consumed, "filled": False}
    return {
        "walk_bps": round((spent / quantity - best) / best * BPS, 9),
        "levels_consumed": levels_consumed,
        "filled": True,
    }


def _notional(levels: list[list[float]], depth: int | None = None) -> float:
    chosen = levels if depth is None else levels[:depth]
    return round(sum(float(price) * float(size) for price, size in chosen), 6)


def liquidity_band(walk: dict[str, Any], top_notional: float) -> str:
    """Declared rule: the band follows the cost of the account's own size first."""
    if not walk["filled"] or (walk["walk_bps"] or 0.0) > IMPACT_THRESHOLD_BPS:
        return "THIN"
    if top_notional < 100.0 * ACCOUNT_USDT:
        return "NORMAL"
    return "DEEP"


# --------------------------------------------------------------------------------------------
# The observation data contract.
# --------------------------------------------------------------------------------------------


def freshness_span_ms(snapshot: dict[str, Any]) -> float:
    """The declared duration of a window: rounds times spacing, from its own recorded budget."""
    budget = snapshot["budget"]
    return float(budget["rounds"]) * float(budget["spacing_s"]) * 1000.0


def freshness_rule(snapshot: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    span = freshness_span_ms(snapshot)
    return {
        "declared_window_span_ms": span,
        "freshness_limit_ms": span + MAX_BOOK_AGE_MARGIN_MS,
        "margin_ms": MAX_BOOK_AGE_MARGIN_MS,
        "rule": (
            "an observation is stale when its book, at the instant the window's evidence closed, "
            "is older than the declared window span plus the declared margin"
        ),
        "observation_path_latency_median_ms": metrics["latency_median_ms"],
        "observation_path_latency_ok": all(
            value <= MAX_LATENCY_MS for value in metrics["latency_median_ms"].values()
        ),
        "observation_path_latency_limit_ms": MAX_LATENCY_MS,
    }


def build_observations(
    snapshot: dict[str, Any],
    window_id: str,
    run_id: str,
    volatility: dict[str, dict[str, Any]],
    raw_ref: dict[str, Any],
    thresholds: dict[str, Any],
    closed_at: datetime,
) -> list[dict[str, Any]]:
    """One row per (round, asset): the data contract, including what was rejected and why.

    The reference instant is the raw snapshot's own ``local_finished_utc``: the moment its evidence
    was complete.  Book age is measured against that instant, so the age of every book can be
    re-derived from the raw bytes alone and never depends on when this function happens to run.
    """
    finished = snapshot.get("local_finished_utc")
    reference = _parse(finished.split(".")[0] + "Z") if finished else closed_at
    declared_span_ms = freshness_span_ms(snapshot)
    freshness_limit_ms = declared_span_ms + MAX_BOOK_AGE_MARGIN_MS
    rows: list[dict[str, Any]] = []
    for observation in snapshot["observations"]:
        round_index = observation.get("round")
        local_utc = observation.get("local_utc")
        # the round's own instant decides its session and slot, so a window that spans a band edge
        # names each observation by where it actually happened
        received = _parse(local_utc.split(".")[0] + "Z") if local_utc else None
        book_age_ms = (
            round((reference - received).total_seconds() * 1000.0, 3) if received else None
        )
        server_ms = observation.get("server_time_ms")
        for symbol in snapshot["symbols"]:
            book = observation["books"].get(symbol)
            depth = observation["depth"].get(symbol)
            row: dict[str, Any] = {
                "run_id": run_id,
                "window_id": window_id,
                "round": round_index,
                "asset": symbol,
                "observed_at_utc": local_utc,
                "exchange_time_ms": server_ms,
                "exchange_time_utc": _iso_from_ms(float(server_ms)) if server_ms else None,
                "exchange_timestamp_source": (
                    "GET /api/v3/time (venue clock, same round); the book endpoints themselves "
                    "return no venue timestamp"
                ),
                "source": {
                    "venue": BASE,
                    "endpoints": [
                        "/api/v3/time",
                        "/api/v3/ticker/bookTicker",
                        f"/api/v3/depth?limit={snapshot['budget']['depth_limit']}",
                        f"/api/v3/klines?interval={KLINE_INTERVAL}&limit={KLINE_LIMIT}",
                    ],
                    "authentication": "public market data only; no key, no signature, no order",
                },
                "thresholds": {
                    "spread_bps": thresholds["spread_bps"],
                    "impact_bps": thresholds["impact_bps"],
                    "source": thresholds["source"],
                },
                "raw": raw_ref,
                "stale": False,
                "stale_reason": None,
                "rejected": False,
                "rejected_reason": None,
            }
            if book is None:
                row["stale"] = True
                row["rejected"] = True
                row["stale_reason"] = "no book in this round"
                row["rejected_reason"] = "no bid/ask for this asset in this round"
                row.update({"bid": None, "ask": None, "spread_bps": None})
            else:
                row.update(
                    {
                        "bid": book["bid"],
                        "ask": book["ask"],
                        "spread_abs": round(book["spread_abs"], 9),
                        "spread_bps": round(book["spread_bps"], 9),
                    }
                )
            if book_age_ms is not None and book_age_ms > freshness_limit_ms:
                row["stale"] = True
                row["rejected"] = True
                row["stale_reason"] = (
                    f"book age {book_age_ms} ms at window close exceeds the declared freshness "
                    f"limit {freshness_limit_ms} ms (declared window span {declared_span_ms} ms plus "
                    f"{MAX_BOOK_AGE_MARGIN_MS} ms)"
                )
                row["rejected_reason"] = "stale book at window close"
            row["freshness_limit_ms"] = freshness_limit_ms
            row["declared_window_span_ms"] = declared_span_ms
            if depth is None:
                row["depth"] = {"levels_sampled": 0, "available": False}
                row["impact"] = {
                    "size_usdt": ACCOUNT_USDT,
                    "filled_buy": False,
                    "filled_sell": False,
                }
                row["liquidity"] = {
                    "band": "THIN",
                    "bid_notional_all_usdt": None,
                    "ask_notional_all_usdt": None,
                }
                row["rejected"] = True
                row["rejected_reason"] = (row["rejected_reason"] or "") + "; no depth snapshot"
            else:
                asks = [[float(price), float(size)] for price, size in depth["asks"]]
                bids = [[float(price), float(size)] for price, size in depth["bids"]]
                buy = walk_detail(asks, ACCOUNT_USDT)
                sell = walk_detail(bids, ACCOUNT_USDT)
                bid_notional = _notional(bids)
                ask_notional = _notional(asks)
                row["depth"] = {
                    "levels_sampled": len(asks) + len(bids),
                    "available": True,
                    "book_last_update_id": depth.get("last_update_id"),
                    "bid_notional_all_usdt": bid_notional,
                    "ask_notional_all_usdt": ask_notional,
                    "bid_notional_top_level_usdt": _notional(bids, 1),
                    "ask_notional_top_level_usdt": _notional(asks, 1),
                }
                row["impact"] = {
                    "size_usdt": ACCOUNT_USDT,
                    "buy_bps": buy["walk_bps"],
                    "sell_bps": sell["walk_bps"],
                    "levels_consumed_buy": buy["levels_consumed"],
                    "levels_consumed_sell": sell["levels_consumed"],
                    "filled_buy": buy["filled"],
                    "filled_sell": sell["filled"],
                }
                if not buy["filled"] or not sell["filled"]:
                    row["rejected"] = True
                    row["rejected_reason"] = (
                        (row["rejected_reason"] or "") + "; the sampled book cannot fill the size"
                    ).lstrip("; ")
                row["liquidity"] = {
                    "band": liquidity_band(buy, min(bid_notional, ask_notional)),
                    "bid_notional_all_usdt": bid_notional,
                    "ask_notional_all_usdt": ask_notional,
                    "levels_sampled_vs_expected": row["depth"]["levels_sampled"]
                    >= MIN_LEVELS_EXPECTED,
                }
            volatility_row = volatility.get(symbol, {})
            row["volatility"] = {
                "value_bps": volatility_row.get("value_bps"),
                "regime": volatility_row.get("regime", "UNKNOWN"),
                "reference": volatility_row.get("reference", "unavailable"),
                "rule": "rolling 24-bar stdev of hourly log returns vs the frozen archive tertiles",
            }
            row["book_age_ms"] = book_age_ms
            moment = received or closed_at
            row["market"] = {
                "session": session_of(moment),
                "iso_weekday": moment.isoweekday(),
                "day_type": day_type(moment),
                "day": moment.strftime("%Y-%m-%d"),
                "slot": slot_of(moment)["slot"],
                "slot_index": slot_of(moment)["slot_index"],
            }
            rows.append(row)
    return rows


# --------------------------------------------------------------------------------------------
# Period, storage, rollups.
# --------------------------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_period() -> dict[str, Any] | None:
    return _read_json(PERIOD_PATH)


def activate_period(thresholds: dict[str, Any], volatility: dict[str, Any]) -> dict[str, Any]:
    """Declare the period once.  A second activation is refused: the clock cannot be restarted."""
    existing = load_period()
    if existing is not None:
        raise SystemExit(
            f"the observation period is already declared: {existing['started_at_utc']} -> "
            f"{existing['ends_at_utc']}; it is not re-activated to chase a result"
        )
    started = datetime.now(UTC).replace(microsecond=0)
    period = {
        "artifact": "ST6_OBSERVATION_PERIOD",
        "phase": "ST-6 forward cost regime validation",
        "declared_at_utc": _utc(),
        "head_at_declaration": _head(),
        "started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ends_at_utc": (started + timedelta(days=PERIOD_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period_days": PERIOD_DAYS,
        "slots_per_day": SLOTS_PER_DAY,
        "slot_hours": SLOT_HOURS,
        "slots": [
            f"{index * SLOT_HOURS:02d}:00-{(index + 1) * SLOT_HOURS:02d}:00 UTC"
            for index in range(SLOTS_PER_DAY)
        ],
        "max_observations_per_day": SLOTS_PER_DAY,
        "one_window_per_slot": True,
        "coverage_rule": COVERAGE_RULE,
        "thresholds": thresholds,
        "volatility_reference": volatility,
        "extension_policy": (
            "the period is not prolonged automatically; after ends_at_utc collection stops unless a "
            "human passes --authorize-extension, and that flag never turns an incomplete period into "
            "a PASS"
        ),
        "does_not_license": [
            "a hypothesis, a strategy, a campaign or a backtest",
            "any paper or live trading, or any deployment of capital",
            "any claim of edge, profit or production capability",
        ],
        "orders_sent": 0,
        "credentials_used": 0,
    }
    _write_json(PERIOD_PATH, period)
    return period


def slot_already_observed(moment: datetime) -> dict[str, Any] | None:
    slot = slot_of(moment)
    for row in _read_jsonl(WINDOWS):
        if row.get("day") == slot["day"] and row.get("slot_index") == slot["slot_index"]:
            return row
    return None


def collect_one(
    period: dict[str, Any],
    thresholds: dict[str, Any],
    volatility_reference_: dict[str, Any],
    rounds: int,
    spacing: float,
    depth_limit: int,
) -> dict[str, Any]:
    """Collect exactly one declared window: probe, klines, raw evidence, contract rows, index row.

    The reference instant of a window is its own ``local_finished_utc`` — the moment its evidence
    was complete — not the moment the process started.  Everything downstream (the window id, the
    slot, the book ages) is derived from that instant, so it can be re-derived from the raw bytes.
    """
    snapshot = collect(rounds, spacing, depth_limit)
    finished = snapshot.get("local_finished_utc")
    closed_at = (
        _parse(finished.split(".")[0] + "Z")
        if finished
        else datetime.now(UTC).replace(microsecond=0)
    )
    window_id = closed_at.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{window_id}-{uuid.uuid4().hex[:8]}"

    klines: dict[str, dict[str, Any]] = {}
    failures = list(snapshot["failures"])
    for symbol in snapshot["symbols"]:
        reading = fetch_klines(symbol)
        reference = volatility_reference_["series"].get(symbol, {"available": False})
        value = live_volatility_bps(reading["rows"]) if reading["ok"] else None
        regime = (
            classify_volatility(value, reference)
            if value is not None and reference.get("available")
            else "UNKNOWN"
        )
        klines[symbol] = {
            "value_bps": value,
            "regime": regime,
            "reference": reference.get("archive", "unavailable")
            if reference.get("available")
            else "unavailable",
            "latency_ms": reading["latency_ms"],
            "response_sha256": reading["response_sha256"],
            "error": reading["error"],
        }
        if not reading["ok"]:
            failures.append(f"klines {symbol}: {reading['error']}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = body.encode("utf-8")
    raw_sha = _sha256_bytes(encoded)
    target = RAW_DIR / f"{window_id}.json.gz"
    with gzip.GzipFile(filename="", mode="wb", fileobj=target.open("wb"), mtime=0) as handle:
        handle.write(encoded)
    raw_ref = {
        "window_id": window_id,
        "path": str(target.relative_to(REPO)),
        "encoding": "gzip",
        "uncompressed_bytes": len(encoded),
        "uncompressed_sha256": raw_sha,
        "compressed_bytes": target.stat().st_size,
        "compressed_sha256": _sha256_bytes(target.read_bytes()),
    }

    rows = build_observations(snapshot, window_id, run_id, klines, raw_ref, thresholds, closed_at)
    metrics = window_metrics(snapshot)  # the proven arithmetic, not a second implementation
    # window_metrics prices the walk from the FIRST round's book only, so a breach in a later round
    # of the same window would be invisible to the ST-6 rule.  The phase therefore judges the worst
    # value over every round it collected and keeps the round-zero value beside it: a fix against
    # hiding an extreme, not a change of policy.
    walks_over_window = [
        value
        for row in rows
        for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
        if isinstance(value, float)
    ]
    unfilled = [
        row
        for row in rows
        if row["depth"].get("available")
        and not (row["impact"].get("filled_buy") and row["impact"].get("filled_sell"))
    ]
    slot = slot_of(closed_at)
    record: dict[str, Any] = {
        "artifact": "ST6_FORWARD_WINDOW",
        "window_id": window_id,
        "run_id": run_id,
        "provenance": "st6_forward_regime (probe: economic001_readonly_probe.collect)",
        "collected_at_utc": closed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw": raw_ref,
        "budget": snapshot["budget"],
        "requests_made": snapshot["budget"]["requests_made"] + len(snapshot["symbols"]),
        "duration_s": snapshot["duration_s"],
        "window_complete": snapshot["complete"] and not failures,
        "failures": failures,
        "orders_sent": snapshot["orders_sent"],
        "credentials_used": snapshot["credentials_used"],
        **slot,
        **metrics,
        "worst_walk_bps_at_account_size": round(max(walks_over_window), 9)
        if walks_over_window
        else None,
        "depth_covers_account_size": not unfilled and bool(rows),
        "worst_walk_bps_round_zero": metrics["worst_walk_bps_at_account_size"],
        "depth_covers_account_size_round_zero": metrics["depth_covers_account_size"],
        "freshness": freshness_rule(snapshot, metrics),
        "window_metric_note": (
            "worst_walk_bps_at_account_size and depth_covers_account_size are computed over every "
            "round of this window; the *_round_zero fields keep what the ST-6 monitor's own "
            "window_metrics saw (first round only)"
        ),
        "observations_written": len(rows),
        "rejected_observations": sum(1 for row in rows if row["rejected"]),
        "assets_present": sorted({row["asset"] for row in rows if row["bid"] is not None}),
        "volatility_regimes": sorted({row["volatility"]["regime"] for row in rows}),
        "liquidity_bands": sorted({row["liquidity"]["band"] for row in rows}),
        "max_book_age_ms": max(
            (row["book_age_ms"] for row in rows if row["book_age_ms"] is not None), default=None
        ),
        "thresholds": {
            "spread_bps": thresholds["spread_bps"],
            "impact_bps": thresholds["impact_bps"],
            "source": thresholds["source"],
        },
    }
    for row in rows:
        _append_jsonl(OBSERVATIONS, row)
    _append_jsonl(WINDOWS, record)
    return record


def rebuild_from_raw(
    period: dict[str, Any],
    thresholds: dict[str, Any],
    volatility_reference_: dict[str, Any],
) -> dict[str, Any]:
    """Re-derive the two event logs from the raw evidence on disk, and say so.

    A derived field that came out impossible (an age below zero, measured against the instant the
    process started rather than the instant the evidence closed) is corrected here, not preserved.
    The raw bytes are the evidence and they are not touched: every hash is re-checked first, and the
    repair is written into the period file so a reader sees what moved and why.
    """
    windows = _read_jsonl(WINDOWS)
    observations = _read_jsonl(OBSERVATIONS)
    volatility_by_window: dict[str, dict[str, dict[str, Any]]] = {}
    for row in observations:
        volatility_by_window.setdefault(row["window_id"], {})[row["asset"]] = {
            "value_bps": row["volatility"]["value_bps"],
            "regime": row["volatility"]["regime"],
            "reference": row["volatility"]["reference"],
        }
    # a field that only records when the rebuild itself ran is bookkeeping, not a change
    volatile = {"rebuilt_from_raw_utc"}
    previous_rows = {(row["window_id"], row["asset"], row["round"]): row for row in observations}
    previous_windows = {row["window_id"]: row for row in windows}
    changed_fields: set[str] = set()
    changed_observations = 0
    rebuilt_windows: list[dict[str, Any]] = []
    rebuilt_rows: list[dict[str, Any]] = []
    for window in windows:
        path = REPO / window["raw"]["path"]
        with gzip.open(path, "rb") as handle:
            payload = handle.read()
        if _sha256_bytes(payload) != window["raw"]["uncompressed_sha256"]:
            raise SystemExit(
                f"{window['raw']['path']} does not reproduce its recorded hash; refusing to "
                "re-derive anything from bytes that do not match"
            )
        snapshot = json.loads(payload.decode("utf-8"))
        finished = snapshot.get("local_finished_utc")
        closed_at = _parse(finished.split(".")[0] + "Z") if finished else datetime.now(UTC)
        rows = build_observations(
            snapshot,
            window["window_id"],
            window["run_id"],
            volatility_by_window.get(window["window_id"], {}),
            window["raw"],
            thresholds,
            closed_at,
        )
        metrics = window_metrics(snapshot)
        walks = [
            value
            for row in rows
            for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
            if isinstance(value, float)
        ]
        unfilled = [
            row
            for row in rows
            if row["depth"].get("available")
            and not (row["impact"].get("filled_buy") and row["impact"].get("filled_sell"))
        ]
        rebuilt = {
            **window,
            **metrics,
            "collected_at_utc": closed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            **slot_of(closed_at),
            "worst_walk_bps_at_account_size": round(max(walks), 9) if walks else None,
            "depth_covers_account_size": not unfilled and bool(rows),
            "worst_walk_bps_round_zero": metrics["worst_walk_bps_at_account_size"],
            "depth_covers_account_size_round_zero": metrics["depth_covers_account_size"],
            "freshness": freshness_rule(snapshot, metrics),
            "window_metric_note": (
                "worst_walk_bps_at_account_size and depth_covers_account_size are computed over "
                "every round of this window; the *_round_zero fields keep what the ST-6 monitor's "
                "own window_metrics saw (first round only)"
            ),
            "observations_written": len(rows),
            "rejected_observations": sum(1 for row in rows if row["rejected"]),
            "assets_present": sorted({row["asset"] for row in rows if row["bid"] is not None}),
            "volatility_regimes": sorted({row["volatility"]["regime"] for row in rows}),
            "liquidity_bands": sorted({row["liquidity"]["band"] for row in rows}),
            "max_book_age_ms": max(
                (row["book_age_ms"] for row in rows if row["book_age_ms"] is not None),
                default=None,
            ),
            "rebuilt_from_raw_utc": _utc(),
        }
        before_window = previous_windows.get(window["window_id"], {})
        changed_fields |= {
            key
            for key, value in rebuilt.items()
            if key not in volatile and (key not in before_window or before_window[key] != value)
        }
        for row in rows:
            before = previous_rows.get((row["window_id"], row["asset"], row["round"]))
            if before is None:
                changed_observations += 1
                continue
            if before != row:
                changed_observations += 1
                changed_fields |= {
                    key for key in row if key not in volatile and before.get(key) != row[key]
                }
        rebuilt_windows.append(rebuilt)
        rebuilt_rows.extend(rows)
    rebuilt_windows.sort(key=lambda row: row["collected_at_utc"])
    WINDOWS.write_text(
        "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rebuilt_windows
        ),
        encoding="utf-8",
    )
    OBSERVATIONS.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rebuilt_rows),
        encoding="utf-8",
    )
    repair = {
        "at_utc": _utc(),
        "what": (
            "the two event logs were re-derived from the raw evidence with the current derivation "
            "rules (a window's reference instant is its own local_finished_utc, and an observation is "
            "stale only beyond the declared window span plus the declared margin)"
        ),
        "why": (
            "a derived field that came out impossible or that was measured against the wrong instant "
            "is a defect of the reading, not evidence: an age below zero was recorded before this "
            "rule existed"
        ),
        "changed_fields": sorted(changed_fields),
        "changed_observations": changed_observations,
        "evidence_unchanged": True,
        "raw_hashes_rechecked": len(rebuilt_windows),
        "windows": [
            {"window_id": row["window_id"], "raw_sha256": row["raw"]["uncompressed_sha256"]}
            for row in rebuilt_windows
        ],
        "derivation": "build_observations / window_metrics, run against the raw bytes on disk",
    }
    if not changed_fields and not changed_observations:
        repair["changed_fields"] = []
        return repair
    period = {**period, "repairs": [*period.get("repairs", []), repair]}
    _write_json(PERIOD_PATH, period)
    return repair


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    out: dict[str, Any] = {
        "n": len(values),
        "median": round(statistics.median(values), 6),
        "p95": round(_percentile(values, 0.95), 6),
        "max": round(max(values), 6),
        "min": round(min(values), 6),
    }
    if len(values) >= 100:
        out["p99"] = round(_percentile(values, 0.99), 6)
    else:
        out["p99"] = None
    return out


def _group(
    observations: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        groups.setdefault(key(row), []).append(row)
    return groups


def regime_statistics(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread, depth, impact and breach statistics per asset and per observed regime."""
    accepted = [row for row in observations if not row["rejected"]]
    spreads = [row["spread_bps"] for row in accepted if row.get("spread_bps") is not None]
    walks = [
        value
        for row in accepted
        for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
        if isinstance(value, float)
    ]
    depths = [
        value
        for row in accepted
        for value in (
            row["depth"].get("bid_notional_all_usdt"),
            row["depth"].get("ask_notional_all_usdt"),
        )
        if isinstance(value, float)
    ]
    latencies = [
        row["book_age_ms"] for row in observations if isinstance(row.get("book_age_ms"), float)
    ]

    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        row_spreads = [row["spread_bps"] for row in rows if row.get("spread_bps") is not None]
        row_walks = [
            value
            for row in rows
            for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
            if isinstance(value, float)
        ]
        over_spread = [value for value in row_spreads if value > SPREAD_THRESHOLD_BPS]
        over_impact = [value for value in row_walks if value > IMPACT_THRESHOLD_BPS]
        row_depth = [
            value
            for row in rows
            for value in (
                row["depth"].get("bid_notional_all_usdt"),
                row["depth"].get("ask_notional_all_usdt"),
            )
            if isinstance(value, float)
        ]
        row_freshness = [
            row["book_age_ms"] for row in rows if isinstance(row.get("book_age_ms"), float)
        ]
        return {
            "observations": len(rows),
            "spread_bps": _stats(row_spreads)
            | {
                "over_model": len(over_spread),
                "over_model_pct": round(100.0 * len(over_spread) / len(row_spreads), 6)
                if row_spreads
                else None,
                "model_threshold_bps": SPREAD_THRESHOLD_BPS,
            },
            "impact_bps": _stats(row_walks)
            | {
                "over_model": len(over_impact),
                "over_model_pct": round(100.0 * len(over_impact) / len(row_walks), 6)
                if row_walks
                else None,
                "model_threshold_bps": IMPACT_THRESHOLD_BPS,
            },
            "depth_notional_usdt": _stats(row_depth),
            "book_age_ms": _stats(row_freshness),
        }

    return {
        "overall": summary(accepted)
        | {
            "depth_notional_usdt": _stats(depths),
            "book_age_ms": _stats(latencies),
            "freshness": "book age is observation freshness, not execution latency",
            "rejected": len(observations) - len(accepted),
            "rejected_fraction": round((len(observations) - len(accepted)) / len(observations), 6)
            if observations
            else None,
            "latency_reading": (
                "book age is the elapsed local time between a round's book and the window close; "
                "it is observation freshness, not execution latency"
            ),
        },
        "by_asset": {
            asset: summary(rows)
            for asset, rows in sorted(_group(accepted, lambda row: row["asset"]).items())
        },
        "by_session": {
            name: summary(rows)
            for name, rows in sorted(_group(accepted, lambda row: row["market"]["session"]).items())
        },
        "by_day_type": {
            name: summary(rows)
            for name, rows in sorted(
                _group(accepted, lambda row: row["market"]["day_type"]).items()
            )
        },
        "by_volatility_regime": {
            name: summary(rows)
            for name, rows in sorted(
                _group(accepted, lambda row: row["volatility"]["regime"]).items()
            )
        },
        "by_liquidity_band": {
            name: summary(rows)
            for name, rows in sorted(_group(accepted, lambda row: row["liquidity"]["band"]).items())
        },
        "spread_extremes": {
            "mean_bps": round(statistics.fmean(spreads), 6) if spreads else None,
            "median_bps": round(statistics.median(spreads), 6) if spreads else None,
            "max_bps": round(max(spreads), 6) if spreads else None,
            "min_bps": round(min(spreads), 6) if spreads else None,
        },
        "impact_extremes": {
            "max_bps": round(max(walks), 6) if walks else None,
            "mean_bps": round(statistics.fmean(walks), 6) if walks else None,
        },
    }


def coverage_document(
    period: dict[str, Any], windows: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Temporal availability, regime coverage and, explicitly, what is still missing."""
    rule = COVERAGE_RULE
    accepted = [row for row in observations if not row["rejected"]]
    expected_days = []
    start = _parse(period["started_at_utc"]).date()
    for offset in range(int(rule["period_days"]) + 1):
        expected_days.append((start + timedelta(days=offset)).strftime("%Y-%m-%d"))
    covered_days = sorted({row["day"] for row in windows})

    by_day: dict[str, Any] = {}
    for day in expected_days:
        day_windows = [row for row in windows if row["day"] == day]
        by_day[day] = {
            "windows": len(day_windows),
            "slots": sorted(row["slot"] for row in day_windows),
            "day_type": day_type(date.fromisoformat(day)),
            "complete": len(day_windows) >= int(rule["maximum_windows_per_day"]),
        }

    sessions = {name: 0 for name, _, _ in SESSIONS}
    for window in windows:
        sessions[window["session"]] = sessions.get(window["session"], 0) + 1
    slots_seen = sorted({window["slot"] for window in windows})
    bands = {row["volatility"]["regime"] for row in accepted} - {
        "UNKNOWN"
    }  # presence is per window, not per observation: the fraction of windows in which the asset was
    # actually observed.  It is derived from the observations themselves, so it never depends on an
    # index row carrying the field.
    observed_assets: dict[str, set[str]] = {window["window_id"]: set() for window in windows}
    for row in accepted:
        if row.get("bid") is not None:
            observed_assets.setdefault(row["window_id"], set()).add(row["asset"])
    presence = {
        asset: round(
            sum(1 for entry in observed_assets.values() if asset in entry) / len(windows), 6
        )
        if windows
        else 0.0
        for asset in SYMBOLS
    }
    rejected_fraction = (
        round((len(observations) - len(accepted)) / len(observations), 6) if observations else None
    )

    checks = {
        "days_covered >= declared minimum": (len(covered_days), rule["minimum_days_covered"]),
        "windows_total >= declared minimum": (len(windows), rule["minimum_windows_total"]),
        "each session >= declared minimum": (
            min(sessions.values()) if sessions else 0,
            rule["minimum_windows_per_three_sessions"],
        ),
        "weekday windows >= declared minimum": (
            sum(1 for row in windows if row["day_type"] == "weekday"),
            rule["minimum_weekday_windows"],
        ),
        "weekend windows >= declared minimum": (
            sum(1 for row in windows if row["day_type"] == "weekend"),
            rule["minimum_weekend_windows"],
        ),
        "distinct slots >= declared minimum": (len(slots_seen), rule["minimum_distinct_slots"]),
        "distinct volatility bands >= declared minimum": (
            len(bands),
            rule["minimum_distinct_volatility_bands"],
        ),
        "every asset present in >= declared fraction of windows": (
            round(min(presence.values()), 6) if presence else 0.0,
            rule["minimum_asset_presence_fraction"],
        ),
        "rejected fraction <= declared maximum": (
            rejected_fraction if rejected_fraction is not None else 0.0,
            rule["maximum_rejected_fraction"],
        ),
    }
    satisfied = {
        name: (actual >= target if "rejected fraction" not in name else actual <= target)
        for name, (actual, target) in checks.items()
    }
    missing = [
        {
            "condition": name,
            "observed": actual,
            "required": target,
            "gap": "still short of the declared coverage rule",
        }
        for name, (actual, target) in checks.items()
        if not satisfied[name]
    ]
    regimes_identified = {
        "sessions": sessions,
        "slots": slots_seen,
        "volatility_bands": sorted(bands),
        "liquidity_bands": sorted({row["liquidity"]["band"] for row in accepted}),
        "day_types": sorted({row["market"]["day_type"] for row in accepted}),
    }
    return {
        "artifact": "ST6_REGIME_COVERAGE",
        "generated_at_utc": _utc(),
        "period": {
            "started_at_utc": period["started_at_utc"],
            "ends_at_utc": period["ends_at_utc"],
            "period_days": period["period_days"],
            "days_elapsed": len(covered_days),
            "days_remaining": max(rule["period_days"] - len(covered_days), 0),
        },
        "declared_rule": rule,
        "planned_windows": rule["period_days"] * rule["maximum_windows_per_day"],
        "observed_windows": len(windows),
        "windows_per_day": {day: entry["windows"] for day, entry in by_day.items()},
        "day_detail": by_day,
        "regimes_identified": regimes_identified,
        "asset_presence_fraction": presence,
        "rejected_fraction": rejected_fraction,
        "checks": {
            name: {
                "observed": actual,
                "required": target,
                "satisfied": satisfied[name],
            }
            for name, (actual, target) in checks.items()
        },
        "missing": missing,
        "coverage_complete": all(satisfied.values()),
        "coverage_token": "REGIME_COVERAGE_SUFFICIENT"
        if all(satisfied.values())
        else "REGIME_COVERAGE_INSUFFICIENT",
        "declared_rule_is_frozen": (
            "the pass/fail rule is the one declared when the period was activated and is not "
            "adjusted after seeing a window; the liquidity bands actually observed are reported "
            "beside it rather than turned into a condition afterwards"
        ),
        "reading": (
            "the period is still open: the coverage rule is checked, not assumed, and an incomplete "
            "period keeps ECO-1 open with this limitation stated"
        )
        if not all(satisfied.values())
        else "every declared coverage condition holds over the closed period",
    }


def drift_document(
    period: dict[str, Any],
    windows: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    statistics_: dict[str, Any],
) -> dict[str, Any]:
    """ST-6's own rule applied to this period's windows, plus the extremes it demands be shown."""
    by_window: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        if not row["rejected"]:
            by_window.setdefault(row["window_id"], []).append(row)
    judge_input: list[dict[str, Any]] = []
    window_inputs: list[dict[str, Any]] = []
    for window in windows:
        rows = by_window.get(window["window_id"], [])
        spreads = [row["spread_bps"] for row in rows if isinstance(row.get("spread_bps"), float)]
        walks = [
            value
            for row in rows
            for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
            if isinstance(value, float)
        ]
        with_depth = [row for row in rows if row["depth"].get("available")]
        depth_ok = (
            all(
                row["impact"].get("filled_buy") and row["impact"].get("filled_sell")
                for row in with_depth
            )
            if with_depth
            else window["depth_covers_account_size"]
        )
        entry = {
            "window_id": window["window_id"],
            "pooled_median_spread_bps": round(statistics.median(spreads), 9)
            if spreads
            else window["pooled_median_spread_bps"],
            "worst_spread_bps": round(max(spreads), 9) if spreads else window["worst_spread_bps"],
            "worst_walk_bps_at_account_size": round(max(walks), 9)
            if walks
            else window["worst_walk_bps_at_account_size"],
            "depth_covers_account_size": depth_ok,
            "source": "observations" if rows else "window index row",
            "rounds_covered": len({row["round"] for row in rows}),
            "observations": len(rows),
        }
        judge_input.append(
            {
                key: entry[key]
                for key in (
                    "pooled_median_spread_bps",
                    "worst_spread_bps",
                    "worst_walk_bps_at_account_size",
                    "depth_covers_account_size",
                )
            }
        )
        window_inputs.append(entry)
    judgement = st6_judge(judge_input)
    breaches: list[dict[str, Any]] = []
    for row in observations:
        if row["rejected"]:
            continue
        spread = row.get("spread_bps")
        if isinstance(spread, float) and spread > SPREAD_THRESHOLD_BPS:
            breaches.append(
                {
                    "kind": "spread_over_model",
                    "asset": row["asset"],
                    "observed_at_utc": row["observed_at_utc"],
                    "value_bps": spread,
                    "threshold_bps": SPREAD_THRESHOLD_BPS,
                    "multiple_of_model": round(spread / SPREAD_THRESHOLD_BPS, 6),
                    "context": {
                        "window_id": row["window_id"],
                        "session": row["market"]["session"],
                        "slot": row["market"]["slot"],
                        "day_type": row["market"]["day_type"],
                        "volatility_regime": row["volatility"]["regime"],
                        "liquidity_band": row["liquidity"]["band"],
                    },
                    "st6_effect": "AT_BOUNDARY"
                    if spread <= BOUNDARY_MULTIPLE * SPREAD_THRESHOLD_BPS
                    else "DRIFT",
                }
            )
        for side in ("buy_bps", "sell_bps"):
            value = row["impact"].get(side)
            if isinstance(value, float) and value > IMPACT_THRESHOLD_BPS:
                breaches.append(
                    {
                        "kind": f"impact_over_model_{side.split('_')[0]}",
                        "asset": row["asset"],
                        "observed_at_utc": row["observed_at_utc"],
                        "value_bps": value,
                        "threshold_bps": IMPACT_THRESHOLD_BPS,
                        "multiple_of_model": round(value / IMPACT_THRESHOLD_BPS, 6),
                        "context": {
                            "window_id": row["window_id"],
                            "session": row["market"]["session"],
                            "slot": row["market"]["slot"],
                            "day_type": row["market"]["day_type"],
                            "volatility_regime": row["volatility"]["regime"],
                            "liquidity_band": row["liquidity"]["band"],
                            "levels_consumed": row["impact"].get(
                                f"levels_consumed_{side.split('_')[0]}"
                            ),
                            "size_usdt": ACCOUNT_USDT,
                        },
                        "st6_effect": "AT_BOUNDARY"
                        if value <= BOUNDARY_MULTIPLE * IMPACT_THRESHOLD_BPS
                        else "DRIFT",
                    }
                )
    breaches.sort(key=lambda entry: entry["multiple_of_model"], reverse=True)
    per_asset_extremes = {
        asset: {
            "worst_spread_bps": entry["spread_bps"]["max"],
            "worst_impact_bps": entry["impact_bps"]["max"],
            "median_spread_bps": entry["spread_bps"]["median"],
            "over_model_observations": entry["spread_bps"]["over_model"],
            "observations": entry["observations"],
        }
        for asset, entry in statistics_["by_asset"].items()
    }
    return {
        "artifact": "ST6_MODEL_DRIFT",
        "generated_at_utc": _utc(),
        "period": {
            "started_at_utc": period["started_at_utc"],
            "ends_at_utc": period["ends_at_utc"],
        },
        "rule": {
            "spread_threshold_bps": SPREAD_THRESHOLD_BPS,
            "impact_threshold_bps": IMPACT_THRESHOLD_BPS,
            "boundary_multiple": BOUNDARY_MULTIPLE,
            "size_usdt": ACCOUNT_USDT,
            "source": "COST_MODEL_V3.model_constants, read at run time; this phase never writes it",
            "aggregation_policy": (
                "extreme values are never hidden by aggregation: every observation above a "
                "threshold is listed individually with its asset, instant and context, up to "
                f"{len(breaches)} recorded here"
            ),
        },
        "st6_window_verdict": judgement["verdict"],
        "st6_components": judgement["components"],
        "st6_provisional": judgement["provisional"],
        "windows_judged": judgement["windows"],
        "what_the_rule_saw": window_inputs,
        "what_the_rule_saw_note": (
            "the ST-6 rule is applied to values recomputed over every round of each window, from the "
            "recorded observations; the *_round_zero fields in the window index are kept beside them "
            "so the difference is visible instead of hidden"
        ),
        "breaches_total": len(breaches),
        "drift_breaches": sum(1 for entry in breaches if entry["st6_effect"] == "DRIFT"),
        "boundary_breaches": sum(1 for entry in breaches if entry["st6_effect"] == "AT_BOUNDARY"),
        "breaches": breaches,
        "per_asset_extremes": per_asset_extremes,
        "drift_detected": judgement["verdict"] == "DRIFT_WIDER_THAN_MODELLED"
        or any(entry["st6_effect"] == "DRIFT" for entry in breaches),
        "actions_on_drift": [
            "the observation is recorded with its raw evidence and its hash",
            "the asset and the context are named in the breach entry",
            "the model is NOT adjusted and no strategy is touched",
            "no real order is requested",
        ],
        "not_measured": [
            "realised slippage",
            "fill quality or price improvement",
            "maker queue position",
        ],
    }


def outcome_document(
    period: dict[str, Any],
    coverage: dict[str, Any],
    drift: dict[str, Any],
    windows: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    rejected_fraction = coverage["rejected_fraction"] or 0.0
    evidence_failures: list[str] = []
    for window in windows:
        raw = window["raw"]
        path = REPO / raw["path"]
        if not path.exists():
            evidence_failures.append(f"{raw['path']} missing")
            continue
        with gzip.open(path, "rb") as handle:
            payload = handle.read()
        if _sha256_bytes(payload) != raw["uncompressed_sha256"]:
            evidence_failures.append(f"{raw['path']} sha256 mismatch")
    if rejected_fraction > COVERAGE_RULE["maximum_rejected_fraction"]:
        evidence_failures.append(
            f"rejected fraction {rejected_fraction} exceeds the declared maximum "
            f"{COVERAGE_RULE['maximum_rejected_fraction']}"
        )
    if not windows:
        outcome = "INSUFFICIENT_REGIME_COVERAGE"
        basis = "the period is declared and open, but no window has been collected yet"
    elif evidence_failures:
        outcome = "DATA_QUALITY_FAILED"
        basis = "evidence or data quality condition failed"
    elif not coverage["coverage_complete"]:
        outcome = "INSUFFICIENT_REGIME_COVERAGE"
        basis = "the declared coverage rule is not yet satisfied: the period is open" + (
            "; a drift breach has already been measured and is reported in this artefact rather "
            "than hidden behind the open period"
            if drift["drift_detected"]
            else ""
        )
    elif drift["drift_detected"]:
        outcome = "COST_MODEL_DRIFT_DETECTED"
        basis = "a measured cost exceeded the modelled term beyond the declared boundary policy"
    else:
        outcome = "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES"
        basis = (
            "every declared coverage condition held and no measured cost exceeded the modelled "
            "term; this certifies compatibility with the observed regimes only"
        )
    eco1 = (
        "CLOSED_WITHIN_OBSERVED_REGIMES"
        if outcome == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES"
        else "OPEN — " + basis
    )
    return {
        "outcome": outcome,
        "outcome_basis": basis,
        "allowed_outcomes": list(OUTCOMES),
        "coverage_token": coverage["coverage_token"],
        "eco_1": eco1,
        "eco_1_limitation": (
            "ECO-1 stays open until the declared coverage rule is met over the closed period; "
            "two windows were never a regime and a partial period is not a result"
        )
        if outcome == "INSUFFICIENT_REGIME_COVERAGE"
        else None,
        "eco_2": STANDING["ECO_2"],
        "no_observations_yet": not windows,
        "drift_observed_so_far": drift["drift_detected"],
        "evidence_failures": evidence_failures,
        "false_success": 0,
        "does_not_certify": (
            "future or unobserved regimes, any execution quality, or the existence of an edge"
        ),
        "period_open": len(coverage["missing"]) > 0,
    }


def test_reference() -> dict[str, Any]:
    return {
        "independent_verifier": "scripts/st6_forward_regime_verify.py",
        "verification_artifact": "data/st6/ST6_INDEPENDENT_VERIFICATION.json",
        "unit_suite": "tests/unit/research/test_st6_forward_regime.py",
        "false_success_target": 0,
        "note": (
            "the verifier recomputes spread, depth, impact and the per-regime statistics from the "
            "raw window bytes and compares them with the recorded observations; it is not the "
            "builder"
        ),
    }


def build_report(
    period: dict[str, Any],
    coverage: dict[str, Any],
    drift: dict[str, Any],
    outcome: dict[str, Any],
    statistics_: dict[str, Any],
    windows: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    accepted = [row for row in observations if not row["rejected"]]
    return {
        "artifact": "ST6_FORWARD_REGIME_REPORT",
        "phase": "ST-6 forward cost regime validation",
        "generated_at_utc": _utc(),
        "current_head": _head(),
        "period": {
            "started_at_utc": period["started_at_utc"],
            "ends_at_utc": period["ends_at_utc"],
            "declared_days": period["period_days"],
            "windows_planned": coverage["planned_windows"],
            "windows_observed": coverage["observed_windows"],
            "days_covered": coverage["period"]["days_elapsed"],
            "slots": period["slots"],
            "max_windows_per_day": period["max_observations_per_day"],
        },
        "files_written": [
            "data/st6/ST6_PERIOD.json",
            "data/st6/ST6_WINDOWS.jsonl",
            "data/st6/ST6_OBSERVATIONS.jsonl",
            "data/st6/ST6_REGIME_COVERAGE.json",
            "data/st6/ST6_MODEL_DRIFT.json",
            "data/st6/ST6_FORWARD_REGIME_REPORT.json",
            "data/st6/ST6_FORWARD_REGIME_REPORT.md",
        ],
        "regimes_identified": coverage["regimes_identified"],
        "coverage": coverage,
        "model_comparison": {
            "thresholds": thresholds,
            "statistics": statistics_,
            "reading": (
                "the modelled terms are unchanged and were read from the frozen model at run time; "
                "no simulator output is presented as a measurement"
            ),
        },
        "drift": drift,
        "outcome": outcome["outcome"],
        "outcome_basis": outcome["outcome_basis"],
        "drift_observed_so_far": outcome["drift_observed_so_far"],
        "eco_1": outcome["eco_1"],
        "eco_2": outcome["eco_2"],
        "insufficient_data": coverage["missing"],
        "repairs": [
            {
                "at_utc": repair["at_utc"],
                "what": repair["what"],
                "why": repair["why"],
                "changed_fields": repair.get("changed_fields"),
                "changed_observations": repair.get("changed_observations"),
                "evidence_unchanged": repair["evidence_unchanged"],
                "raw_hashes_rechecked": repair["raw_hashes_rechecked"],
            }
            for repair in period.get("repairs", [])
        ],
        "errors": {
            "windows_incomplete": [
                {"window_id": row["window_id"], "failures": row["failures"]}
                for row in windows
                if not row["window_complete"]
            ],
            "rejected_observations": [
                {
                    "window_id": row["window_id"],
                    "asset": row["asset"],
                    "reason": row["rejected_reason"],
                }
                for row in observations
                if row["rejected"]
            ][:50],
            "evidence_failures": outcome["evidence_failures"],
        },
        "tests": test_reference(),
        "commit": {
            "head_at_run": _head(),
            "head_at_declaration": period["head_at_declaration"],
        },
        "false_success": 0,
        "eco_1_decision": outcome["eco_1"],
        "standing_state": STANDING,
        "duplication_policy": (
            "one compact observation line per (window, asset, round) plus an index line per window; "
            "rollups live only in the report artefacts, never repeated inside individual events "
            "(CAP-004C)"
        ),
        "storage": {
            "raw": "data/st6/raw/<window_id>.json.gz (gzip; sha256 of the uncompressed bytes)",
            "events": "data/st6/ST6_OBSERVATIONS.jsonl, data/st6/ST6_WINDOWS.jsonl",
            "bounded": "gzip keeps the raw evidence well under a megabyte per day at six windows",
            "uncompressed_bytes": sum(row["raw"]["uncompressed_bytes"] for row in windows),
            "compressed_bytes": sum(row["raw"]["compressed_bytes"] for row in windows),
        },
        "scheduler": {
            "daemon_created": False,
            "reused_cadence": "none: ST-6 was not scheduled, so this phase adds an idempotent "
            "--due command instead of a second scheduler",
            "trading_scheduler_touched": False,
        },
        "assets_observed": sorted({row["asset"] for row in accepted}),
        "observations_written": len(observations),
        "rejected_observations": len(observations) - len(accepted),
        "orders_sent": sum(row["orders_sent"] for row in windows),
        "credentials_used": sum(row["credentials_used"] for row in windows),
        "does_not_license": period["does_not_license"],
    }


def _render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    drift = report["drift"]
    stats = report["model_comparison"]["statistics"]
    lines = [
        "# ST-6 — forward cost regime validation",
        "",
        f"Generated {report['generated_at_utc']} at `{report['current_head']}`.",
        "",
        "## Period",
        "",
        f"Declared for {report['period']['declared_days']} natural days, "
        f"{report['period']['max_windows_per_day']} windows per day maximum, one per declared UTC slot:",
        "",
        f"`{report['period']['started_at_utc']}` → `{report['period']['ends_at_utc']}`.",
        "",
        "Slots: " + ", ".join(f"`{slot}`" for slot in report["period"]["slots"]) + ".",
        "",
        f"Windows planned {report['period']['windows_planned']}, observed "
        f"{report['period']['windows_observed']}, days covered "
        f"{report['period']['days_covered']}.",
        "",
        "## Regimes identified",
        "",
        f"Sessions: {coverage['regimes_identified']['sessions']}. "
        f"Slots seen: {coverage['regimes_identified']['slots']}. "
        f"Volatility bands: {coverage['regimes_identified']['volatility_bands']}. "
        f"Liquidity bands: {coverage['regimes_identified']['liquidity_bands']}. "
        f"Day types: {coverage['regimes_identified']['day_types']}.",
        "",
        "## Comparison with COST_MODEL_V3",
        "",
        "| threshold | value | source |",
        "| --- | --- | --- |",
        f"| spread | {report['model_comparison']['thresholds']['spread_bps']} bps | "
        f"`{report['model_comparison']['thresholds']['source']}` |",
        f"| impact | {report['model_comparison']['thresholds']['impact_bps']} bps | "
        f"`{report['model_comparison']['thresholds']['source']}` |",
        "",
        f"Measured spread: median {stats['spread_extremes']['median_bps']} bps, mean "
        f"{stats['spread_extremes']['mean_bps']} bps, extreme "
        f"{stats['spread_extremes']['max_bps']} bps. Measured {ACCOUNT_USDT:.0f} USDT impact: "
        f"extreme {stats['impact_extremes']['max_bps']} bps. Observations above the model: "
        f"{stats['overall']['spread_bps']['over_model']} of "
        f"{stats['overall']['spread_bps']['n']} spread readings and "
        f"{stats['overall']['impact_bps']['over_model']} of "
        f"{stats['overall']['impact_bps']['n']} impact readings.",
        "",
        "| asset | observations | median spread | worst spread | worst impact | over model |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for asset, entry in stats["by_asset"].items():
        lines.append(
            f"| {asset} | {entry['observations']} | {entry['spread_bps']['median']} | "
            f"{entry['spread_bps']['max']} | {entry['impact_bps']['max']} | "
            f"{entry['spread_bps']['over_model']} |"
        )
    depth_line = ", ".join(
        f"{asset} {entry['depth_notional_usdt']['median']} USDT"
        for asset, entry in stats["by_asset"].items()
        if entry.get("depth_notional_usdt", {}).get("median") is not None
    )
    lines += [
        "",
        f"Depth available per side, median bid/ask notional at 100 sampled levels: {depth_line}. "
        f"Median book age when the window closed: "
        f"{stats['overall']['book_age_ms'].get('median')} ms, extreme "
        f"{stats['overall']['book_age_ms'].get('max')} ms (observation freshness, not execution "
        f"latency).",
        "",
        "## Drift",
        "",
        f"ST-6 verdict over {drift['windows_judged']} window(s): **{drift['st6_window_verdict']}**"
        f"{' (provisional)' if drift['st6_provisional'] else ''}, components "
        f"{drift['st6_components']}. Breaches recorded: {drift['breaches_total']} "
        f"({drift['drift_breaches']} beyond the boundary multiple, "
        f"{drift['boundary_breaches']} at the boundary).",
        "",
    ]
    if drift["breaches"]:
        lines += [
            "| asset | kind | value bps | x model | when | context |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for entry in drift["breaches"][:20]:
            context = entry["context"]
            lines.append(
                f"| {entry['asset']} | {entry['kind']} | {entry['value_bps']} | "
                f"{entry['multiple_of_model']} | {entry['observed_at_utc']} | "
                f"{context.get('session')} {context.get('slot')} "
                f"{context.get('volatility_regime', '')} |"
            )
    else:
        lines.append("No observation exceeded a modelled threshold in this period.")
    lines += [
        "",
        "## Coverage rule",
        "",
        "| condition | observed | required | satisfied |",
        "| --- | --- | --- | --- |",
    ]
    for name, entry in coverage["checks"].items():
        lines.append(
            f"| {name} | {entry['observed']} | {entry['required']} | "
            f"{'yes' if entry['satisfied'] else 'no'} |"
        )
    lines += [
        "",
        f"Coverage token: **{coverage['coverage_token']}**. {coverage['declared_rule_is_frozen']}.",
    ]
    if report["repairs"]:
        lines += ["", "## Corrections to derived readings", ""]
        for repair in report["repairs"]:
            changed = repair["changed_fields"]
            observations = repair["changed_observations"]
            lines.append(
                f"- {repair['at_utc']}: {repair['what']}. Why: {repair['why']} Raw hashes "
                f"re-checked: {repair['raw_hashes_rechecked']}; evidence unchanged: "
                f"{repair['evidence_unchanged']}. Fields changed: "
                f"{changed if changed is not None else 'not recorded for that run'}; observations "
                f"changed: "
                f"{observations if observations is not None else 'not recorded for that run'}."
            )
    lines += [
        "",
        "## Insufficient data and errors",
        "",
        f"Incomplete windows: {len(report['errors']['windows_incomplete'])}. "
        f"Rejected observations: {report['rejected_observations']} of "
        f"{report['observations_written']}. Evidence failures: "
        f"{len(report['errors']['evidence_failures'])}.",
        "",
    ]
    for entry in report["insufficient_data"]:
        lines.append(
            f"- missing: {entry['condition']} (observed {entry['observed']}, required {entry['required']})"
        )
    lines += [
        "",
        "## Decision",
        "",
        f"**{report['outcome']}** — {report['outcome_basis']}.",
        "",
        f"A drift breach has been measured in the observed windows: "
        f"**{report['drift_observed_so_far']}**. When it is true it is reported here and in the "
        "breach table below, with the asset and the instant named, while the period is still open; "
        "the model is not adjusted and no strategy is touched because of it.",
        "",
        f"ECO-1: {report['eco_1']}.",
        "",
        f"ECO-2: {report['eco_2']}.",
        "",
        "## Tests and verification",
        "",
        f"Independent verifier: `{report['tests']['independent_verifier']}` → "
        f"`{report['tests']['verification_artifact']}`. Unit suite: "
        f"`{report['tests']['unit_suite']}`. FALSE_SUCCESS target "
        f"{report['tests']['false_success_target']}; recorded {report['false_success']}.",
        "",
        "## Standing state",
        "",
        "```text",
    ]
    for key, value in report["standing_state"].items():
        lines.append(f"{key} = {value}")
    lines += [
        "```",
        "",
        f"Orders sent: {report['orders_sent']}. Credentials used: {report['credentials_used']}. "
        f"Observations recorded: {report['observations_written']} "
        f"({report['rejected_observations']} rejected and written down as such).",
        "",
        "## What this does not say",
        "",
        "- It does not certify future or unobserved regimes, only compatibility with the conditions "
        "actually observed.",
        "- It does not measure realised slippage, fill quality or maker queue position: those stay "
        "`UNKNOWN`.",
        "- It does not license a campaign, a hypothesis, a strategy, capital or live trading.",
        "",
        f"Storage: {report['storage']['compressed_bytes']} compressed bytes of raw evidence for "
        f"{report['storage']['uncompressed_bytes']} uncompressed. Scheduler: "
        f"{report['scheduler']['reused_cadence']}.",
        "",
    ]
    return "\n".join(lines)


def rollup(
    period: dict[str, Any],
    thresholds: dict[str, Any],
    volatility_reference_: dict[str, Any],
    windows: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    window_rows = windows if windows is not None else _read_jsonl(WINDOWS)
    observation_rows = observations if observations is not None else _read_jsonl(OBSERVATIONS)
    coverage = coverage_document(period, window_rows, observation_rows)
    statistics_ = regime_statistics(observation_rows)
    drift = drift_document(period, window_rows, observation_rows, statistics_)
    outcome = outcome_document(period, coverage, drift, window_rows, observation_rows)
    report = build_report(
        period,
        coverage,
        drift,
        outcome,
        statistics_,
        window_rows,
        observation_rows,
        thresholds,
    )
    report["volatility_reference"] = volatility_reference_
    _write_json(COVERAGE_PATH, coverage)
    _write_json(DRIFT_PATH, drift)
    _write_json(REPORT_JSON, report)
    REPORT_MD.write_text(_render_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true", help="declare the period once")
    parser.add_argument("--collect", action="store_true", help="collect one window in this slot")
    parser.add_argument(
        "--due", action="store_true", help="collect only if this slot is unobserved"
    )
    parser.add_argument("--rollup-only", action="store_true", help="re-roll without collecting")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--spacing", type=float, default=SPACING_S)
    parser.add_argument("--depth-limit", type=int, default=DEPTH_LIMIT)
    parser.add_argument(
        "--authorize-extension",
        action="store_true",
        help="keep collecting after the declared end; never turns an incomplete period into a PASS",
    )
    parser.add_argument(
        "--rebuild-observations",
        action="store_true",
        help="re-derive the event logs from the raw evidence, re-checking every hash first",
    )
    args = parser.parse_args(argv)

    thresholds = frozen_thresholds()
    volatility_reference_ = volatility_reference()

    if args.activate:
        period = activate_period(thresholds, volatility_reference_)
        print(
            f"period declared: {period['started_at_utc']} -> {period['ends_at_utc']} "
            f"({period['period_days']} days, {period['slots_per_day']} windows/day max)"
        )
    loaded = load_period()
    if loaded is None:
        print("no period declared yet; run --activate first (nothing was collected)")
        return 1
    period = loaded

    now = datetime.now(UTC)
    ended = now >= _parse(period["ends_at_utc"])
    if (args.collect or args.due) and ended and not args.authorize_extension:
        print(
            f"the declared period ended at {period['ends_at_utc']}; collection stops here. "
            "An extension needs --authorize-extension from a human and still cannot turn an "
            "incomplete period into a PASS."
        )
        return 0

    if args.rebuild_observations:
        repair = rebuild_from_raw(period, thresholds, volatility_reference_)
        print(
            f"rebuilt {repair['raw_hashes_rechecked']} window(s) from raw evidence; "
            f"fields changed: {repair['changed_fields'] or 'none'}, observations changed: "
            f"{repair['changed_observations']}"
        )

    if args.collect or args.due:
        existing = slot_already_observed(now)
        if args.due and existing is not None:
            print(
                f"slot {existing['slot']} on {existing['day']} is already observed by window "
                f"{existing['window_id']}; no duplicate measurement"
            )
        else:
            record = collect_one(
                period,
                thresholds,
                volatility_reference_,
                args.rounds,
                args.spacing,
                args.depth_limit,
            )
            print(
                f"window {record['window_id']} slot {record['slot']} ({record['session']}, "
                f"{record['day_type']}): {record['observations_written']} observations, "
                f"{record['rejected_observations']} rejected, pooled median spread "
                f"{record['pooled_median_spread_bps']} bps, worst {record['worst_spread_bps']} bps, "
                f"walk {record['worst_walk_bps_at_account_size']} bps, complete "
                f"{record['window_complete']}"
            )

    report = rollup(period, thresholds, volatility_reference_)
    print(
        f"{report['outcome']} over {report['period']['windows_observed']} window(s) / "
        f"{report['period']['days_covered']} day(s) - coverage {report['coverage']['coverage_token']}, "
        f"ST-6 {report['drift']['st6_window_verdict']}, breaches {report['drift']['breaches_total']}"
    )
    print(
        f"written -> {REPORT_MD.relative_to(REPO)}, {REPORT_JSON.relative_to(REPO)}, "
        f"{COVERAGE_PATH.relative_to(REPO)}, {DRIFT_PATH.relative_to(REPO)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
