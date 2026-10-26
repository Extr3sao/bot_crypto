"""ECONOMIC-001 — finite, read-only public-data probe.

The economic gate left one honest gap: the spread (SRC-07) had no historical endpoint, so a past
period could never be re-verified, and every cost number inherited that ``UNKNOWN``. The gate also
forbade the opposite error — presenting a simulator's output as measured slippage or fill quality.

This script closes the *measurable* part of that gap and nothing more. It calls **public Binance
market-data endpoints only**, with no API key, no signature and no order, and it collects a
**finite, declared budget**: a fixed number of rounds, spaced by a fixed interval, of

* ``GET /api/v3/time``               — the venue's clock, to price our own clock skew,
* ``GET /api/v3/ticker/bookTicker``  — the best bid/ask of the authorized instrument class,
* ``GET /api/v3/depth``              — a bounded L2 snapshot (top ``DEPTH_LIMIT`` levels).

From those bytes three things can be *measured* rather than assumed: the live bid/ask spread, the
round-trip latency of the observation path, and the depth that a taker order of a given notional
would actually have to consume. Everything a live order would additionally experience — queue
position, fill probability, realised slippage, fill quality — is **not** produced here and stays
``UNKNOWN``; the artefact says so explicitly instead of filling the hole with a model.

The snapshot is a *forward observation of a bounded window*, not a historical series: it cannot
validate a past period and is not a substitute for a measurement campaign over time.

Run:  python scripts/economic001_readonly_probe.py
      python scripts/economic001_readonly_probe.py --rounds 3 --spacing 4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "economic001" / "READ_ONLY_SNAPSHOT.json"

BASE = "https://api.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
ROUNDS = 5
SPACING_S = 6.0
DEPTH_LIMIT = 100
TIMEOUT_S = 10.0
MAX_ATTEMPTS = 2  # a bounded retry, recorded; the budget stays finite either way
BPS = 10_000.0


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _get(path: str, params: str) -> dict[str, Any]:
    """One public GET, with its latency and outcome recorded either way."""
    url = f"{BASE}{path}"
    if params:
        url = f"{url}?{params}"
    last: dict[str, Any] = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = _utc()
        t0 = time.perf_counter()
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                body = response.read()
                status = response.status
            latency_ms = (time.perf_counter() - t0) * 1000.0
            payload = json.loads(body)
            return {
                "path": path,
                "url": url,
                "attempt": attempt,
                "started_utc": started,
                "latency_ms": round(latency_ms, 3),
                "http_status": status,
                "bytes": len(body),
                "ok": True,
                "payload": payload,
            }
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = {
                "path": path,
                "url": url,
                "attempt": attempt,
                "started_utc": started,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                "http_status": None,
                "bytes": 0,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    return last


def _book(row: dict[str, Any]) -> dict[str, Any] | None:
    payload = row.get("payload")
    if not row["ok"] or not isinstance(payload, dict):
        return None
    try:
        bid = float(payload["bidPrice"])
        ask = float(payload["askPrice"])
    except (KeyError, TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    return {
        "bid": bid,
        "bid_qty": float(payload.get("bidQty", 0.0)),
        "ask": ask,
        "ask_qty": float(payload.get("askQty", 0.0)),
        "mid": mid,
        "spread_abs": ask - bid,
        "spread_bps": (ask - bid) / mid * BPS,
    }


def collect(rounds: int, spacing: float, depth_limit: int) -> dict[str, Any]:
    started_utc = _utc()
    t_start = time.perf_counter()
    observations: list[dict[str, Any]] = []
    latency: dict[str, list[float]] = {"time": [], "bookTicker": [], "depth": []}
    failures: list[str] = []
    requests_made = 0

    for round_index in range(rounds):
        round_row: dict[str, Any] = {
            "round": round_index,
            "local_utc": _utc(),
            "books": {},
            "depth": {},
        }

        clock = _get("/api/v3/time", "")
        requests_made += 1
        if clock["ok"]:
            latency["time"].append(clock["latency_ms"])
            server_ms = int(clock["payload"]["serverTime"])
            round_row["server_time_ms"] = server_ms
            round_row["clock_offset_ms"] = round(
                server_ms - time.time() * 1000.0 - clock["latency_ms"] / 2.0, 3
            )
        else:
            failures.append(f"round {round_index} time: {clock.get('error')}")

        symbols_param = json.dumps(list(SYMBOLS), separators=(",", ":"))
        tickers = _get("/api/v3/ticker/bookTicker", f"symbols={urllib.parse.quote(symbols_param)}")
        requests_made += 1
        if tickers["ok"]:
            latency["bookTicker"].append(tickers["latency_ms"])
            for entry in tickers["payload"]:
                book = _book({"ok": True, "payload": entry})
                if book is not None:
                    round_row["books"][entry["symbol"]] = book
        else:
            failures.append(f"round {round_index} bookTicker: {tickers.get('error')}")

        for symbol in SYMBOLS:
            depth = _get("/api/v3/depth", f"symbol={symbol}&limit={depth_limit}")
            requests_made += 1
            if depth["ok"]:
                latency["depth"].append(depth["latency_ms"])
                payload = depth["payload"]
                round_row["depth"][symbol] = {
                    "last_update_id": payload.get("lastUpdateId"),
                    "bids": [[float(p), float(q)] for p, q in payload.get("bids", [])],
                    "asks": [[float(p), float(q)] for p, q in payload.get("asks", [])],
                }
            else:
                failures.append(f"round {round_index} depth {symbol}: {depth.get('error')}")

        observations.append(round_row)
        if round_index < rounds - 1:
            time.sleep(spacing)

    duration_s = round(time.perf_counter() - t_start, 3)
    return {
        "artifact": "ECONOMIC-001_READ_ONLY_SNAPSHOT",
        "purpose": (
            "Measure, without sending any order, the parts of execution reality that are measurable "
            "from public market data: live spread, observation latency and depth-based impact."
        ),
        "scope": "binance spot public market-data endpoints; authorized instrument class (majors vs USDT)",
        "authentication": "none — public endpoints only; no API key, no signature, no private call",
        "orders_sent": 0,
        "credentials_used": 0,
        "private_endpoints_called": [],
        "budget": {
            "rounds": rounds,
            "spacing_s": spacing,
            "depth_limit": depth_limit,
            "requests_planned": rounds * (1 + 1 + len(SYMBOLS)),
            "requests_made": requests_made,
            "max_attempts_per_request": MAX_ATTEMPTS,
            "finite": True,
            "declared_before_collection": True,
        },
        "local_started_utc": started_utc,
        "local_finished_utc": _utc(),
        "duration_s": duration_s,
        "endpoint_base": BASE,
        "symbols": list(SYMBOLS),
        "observations": observations,
        "latency_ms": {
            "samples": {name: values for name, values in latency.items()},
            "reading": (
                "round-trip time of the observation path (HTTPS request plus venue response), not "
                "execution latency and not any order path"
            ),
        },
        "failures": failures,
        "complete": not failures,
        "not_measured_here": [
            "maker queue position",
            "fill probability",
            "realised slippage",
            "fill quality / price improvement",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--spacing", type=float, default=SPACING_S)
    parser.add_argument("--depth-limit", type=int, default=DEPTH_LIMIT)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    snapshot = collect(args.rounds, args.spacing, args.depth_limit)
    body = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    snapshot["snapshot_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()

    print(
        f"{'complete' if snapshot['complete'] else 'INCOMPLETE'} "
        f"rounds={args.rounds} requests={snapshot['budget']['requests_made']} "
        f"duration={snapshot['duration_s']}s failures={len(snapshot['failures'])}"
    )
    print(f"written -> {out.relative_to(REPO)}")
    for failure in snapshot["failures"]:
        print(f"  FAILED {failure}")
    return 0 if snapshot["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
