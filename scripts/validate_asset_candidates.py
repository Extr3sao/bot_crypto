"""ASSET-VALIDATION-001 — objective measurement of asset candidates.

Candidates: BNB, XRP, LINK, DOGE.  Baselines: BTC, ETH, SOL.
Public market data only (ccxt binanceusdm, no credentials).  Analysis only:
nothing here touches POC01, the trading runtime, or any locked window of
EDGE-RESEARCH-002 (this is market-structure measurement, not hypothesis
evaluation, and no strategy selection is performed from it).

PRE-REGISTERED ACCEPTANCE (fixed BEFORE fetching any data):

  ADOPT_P1    depth >= 90 days (1d candles) AND 5m gaps == 0 in window
              AND median 5m quote volume >= $1,000,000
              AND |corr| vs each of BTC/ETH/SOL < 0.85
              AND annualized vol in [30%, 150%]
  ADOPT_P2    depth >= 30 days AND gaps <= 3
              AND median 5m quote volume >= $250,000
              AND |corr| vs each baseline < 0.92
              AND annualized vol in [20%, 200%]
  EXPERIMENT  liquidity+depth at ADOPT_P2 levels but 0.92 <= |corr| < 0.97,
              or vol outside the ADOPT_P2 band but inside [10%, 250%]
  DEFER       data-quality issues (gaps > 3 or OHLC violations) or
              liquidity below ADOPT_P2
  REJECT      no usable 5m data

Spread/slippage proxies (no tick data available — documented as proxies):
  spread_proxy   = median( (high-low)/close ) per 5m bar
  slippage_proxy = spread_proxy / 2  (half-spread cost model, conservative)
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import ccxt

SYMBOLS = ["BNB/USDT:USDT", "XRP/USDT:USDT", "LINK/USDT:USDT", "DOGE/USDT:USDT",
           "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
CANDIDATES = SYMBOLS[:4]
BASELINES = SYMBOLS[4:]
TIMEFRAME_5M = "5m"
WINDOW_DAYS = 20
DEPTH_DAYS_1D = 400
LIMIT = 1000


def _public_exchange() -> ccxt.binanceusdm:
    """Public client: explicitly credential-free by construction."""
    return ccxt.binanceusdm({"enableRateLimit": True, "apiKey": "", "secret": ""})


def fetch_paginated(ex: ccxt.binanceusdm, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> list[list]:
    rows: list[list] = []
    cursor = since_ms
    while cursor < until_ms:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=cursor, limit=LIMIT)
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1][0]
        if last <= cursor:  # provider stall guard
            break
        cursor = last + 1
        if len(batch) < LIMIT:
            break
        time.sleep(ex.rateLimit / 1000.0)
    seen: set[int] = set()
    clean = [r for r in rows if r[0] < until_ms and r[0] not in seen and not seen.add(r[0])]
    clean.sort(key=lambda r: r[0])
    return clean


def continuity(candles: list[list], tf_ms: int) -> dict:
    ts = [c[0] for c in candles]
    gaps = sum(1 for a, b in zip(ts, ts[1:]) if b - a != tf_ms)
    dups = len(ts) - len(set(ts))

    def _bad(c: list) -> bool:
        o, h, l, cl = c[1], c[2], c[3], c[4]
        if min(o, h, l, cl) <= 0:
            return True
        return not (h >= max(o, cl, l) and l <= min(o, cl, h))

    ohlc_bad = sum(1 for c in candles if _bad(c))
    return {"gaps": gaps, "duplicates": dups, "ohlc_violations": ohlc_bad}


def returns_of(candles: list[list]) -> list[float]:
    closes = [c[4] for c in candles]
    return [statistics.log(closes[i + 1] / closes[i]) for i in range(len(closes) - 1)]


def metrics_5m(candles: list[list]) -> dict:
    if len(candles) < 10:
        return {}
    rets = returns_of(candles)
    ann = statistics.pstdev(rets) * ((24 * 12) * 365) ** 0.5
    qv = [c[5] * ((c[1] + c[4]) / 2) for c in candles]  # volume x typical price
    rng = [(c[2] - c[3]) / c[4] for c in candles]
    closes = [c[4] for c in candles]
    tr = [max(candles[i][2] - candles[i][3], abs(candles[i][2] - closes[i - 1]),
              abs(candles[i][3] - closes[i - 1])) / closes[i - 1] for i in range(1, len(candles))]
    return {
        "ann_vol": round(ann, 4),
        "median_quote_volume_usd": round(statistics.median(qv)),
        "mean_daily_quote_volume_usd": round(sum(qv) / (len(qv) / (24 * 12))),
        "spread_proxy_median": round(statistics.median(rng), 6),
        "slippage_proxy_half_spread": round(statistics.median(rng) / 2, 6),
        "atr_pct_median": round(statistics.median(tr), 6),
    }


def corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def classify(depth_days: int, cont: dict, m: dict, max_abs_corr: float) -> str:
    if not m or depth_days == 0:
        return "REJECT"
    vol_pct = m["ann_vol"] * 100
    liq = m["median_quote_volume_usd"]
    gaps = cont["gaps"]
    if cont["ohlc_violations"] > 0:
        return "DEFER"
    if depth_days >= 90 and gaps == 0 and liq >= 1_000_000 and max_abs_corr < 0.85 and 30 <= vol_pct <= 150:
        return "ADOPT_P1"
    if depth_days >= 30 and gaps <= 3 and liq >= 250_000 and max_abs_corr < 0.92 and 20 <= vol_pct <= 200:
        return "ADOPT_P2"
    if gaps <= 3 and liq >= 250_000 and (0.92 <= max_abs_corr < 0.97 or 10 <= vol_pct <= 250):
        return "EXPERIMENT"
    return "DEFER"


def main() -> int:
    ex = _public_exchange()
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - WINDOW_DAYS * 24 * 3600 * 1000
    since_depth = now_ms - DEPTH_DAYS_1D * 24 * 3600 * 1000
    tf_ms = 5 * 60 * 1000

    data: dict[str, dict] = {}
    for sym in SYMBOLS:
        d5 = fetch_paginated(ex, sym, TIMEFRAME_5M, since_ms, now_ms)
        d1 = fetch_paginated(ex, sym, "1d", since_depth, now_ms)
        cont = continuity(d5, tf_ms)
        data[sym] = {
            "candles_5m": len(d5),
            "first_5m_ts": datetime.fromtimestamp(d5[0][0] / 1000, tz=UTC).isoformat() if d5 else None,
            "last_5m_ts": datetime.fromtimestamp(d5[-1][0] / 1000, tz=UTC).isoformat() if d5 else None,
            "depth_days_1d": len(d1),
            "continuity": cont,
            "metrics": metrics_5m(d5),
            "_returns": returns_of(d5),
        }

    for sym in SYMBOLS:
        if sym in CANDIDATES:
            corrs = {b.split("/")[0]: round(corr(data[sym]["_returns"], data[b]["_returns"]), 4) for b in BASELINES}
            data[sym]["corr_to_baselines"] = corrs
            data[sym]["max_abs_corr"] = round(max(abs(v) for v in corrs.values()), 4)
            data[sym]["opportunity_diversity"] = round(1 - sum(abs(v) for v in corrs.values()) / 3, 4)
            data[sym]["classification"] = classify(
                data[sym]["depth_days_1d"], data[sym]["continuity"], data[sym]["metrics"], data[sym]["max_abs_corr"]
            )

    payload = {
        "checkpoint": "ASSET-VALIDATION-001",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "window_days_5m": WINDOW_DAYS,
        "window_5m": [datetime.fromtimestamp(since_ms / 1000, tz=UTC).isoformat(),
                      datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat()],
        "provider": "ccxt.binanceusdm (public, credentials empty)",
        "preregistered_acceptance": "module docstring — fixed before fetch",
        "note": "market-structure measurement only; not a strategy backtest; no locked-window access",
        "results": {s: {k: v for k, v in data[s].items() if k != "_returns"} for s in SYMBOLS},
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    sha = hashlib.sha256(blob).hexdigest()

    out = Path("reports/research-expansion-v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "ASSET_VALIDATION.json").write_text(json.dumps({**payload, "payload_sha256": sha}, indent=1))

    for sym in CANDIDATES:
        d = data[sym]
        print(sym, "->", d["classification"],
              "| depth1d:", d["depth_days_1d"],
              "| candles5m:", d["candles_5m"],
              "| gaps:", d["continuity"]["gaps"],
              "| corr:", d["corr_to_baselines"],
              "| vol:", d["metrics"]["ann_vol"],
              "| med5m$:", d["metrics"]["median_quote_volume_usd"])
    print("payload_sha256:", sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
