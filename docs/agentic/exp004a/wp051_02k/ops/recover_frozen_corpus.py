"""WP051-02K — re-derive the frozen corpora from the same public source, or prove we cannot.

The acceptance test is never this script's opinion: the 1h corpus is accepted only when the
digest equals ``FROZEN_SHARD_SHA256`` from ``edge03/forward_plan.py``, and the 15m shard only
when its bytes hash to the sha256 the economic closure published. A mismatch is reported, and
nothing is written into the live corpus path.

Layout and serialisation mirror the original producers exactly:
  * 1h  — ``scripts/fetch_alpha_expansion_history.py``: year shards ``{SYM}_{YYYY}.json``,
          ``json.dumps(list)``; range 2019-01-01 .. 2026-02-28 (exclusive).
  * 15m — one shard per asset, ``json.dumps(list)``, ending at the frozen 15m end; the start is
          found by solving for the published byte length instead of guessing a date.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

LIMIT = 1000
HOUR_MS = 3_600_000
START_1H = 1_546_300_800_000  # 2019-01-01T00:00:00Z
END_1H = 1_772_323_200_000  # 2026-03-01T00:00:00Z exclusive
FROZEN_1H_END = 1_772_319_600_000  # 2026-02-28T23:00:00Z
FROZEN_15M_END = 1_791_372_600_000  # 2026-10-07T11:30:00Z

#: The 15m shard is ~4.5 MB, so its window is about a year; these starts are tried in order and
#: the search is repeated one step further back only when the fetched history is too short to
#: produce the published byte count. Guessing a date is not how the window is accepted.
START_15M_CANDIDATES = (1_735_689_600_000, 1_640_995_200_000, START_1H)  # 2025-01-01, 2022-01-01, 2019

FROZEN_1H = {"BTC": "f4d16c3664c142d1", "ETH": "365046d4738aa7b1", "SOL": "847d8eb45eafebd8"}
FROZEN_15M = {"BTC": "cd1d2ea256a97f7c", "ETH": "b8fd5744cc66f635", "SOL": "72a268137cbe944b"}
#: sha256 of the shard bytes, published by the economic closure before this recovery existed.
PUBLISHED_15M_SHA256 = {
    "BTC": "60b0630153dc8e879d63c9691712c8e15d06ede0cc2ae815725340e44c4e9d7f",
    "ETH": "b3b1f02e9a299500b77fc3b8d31a31c3856820daa1c99bba3921d74cec5b943e",
    "SOL": "d3a637c2f5e98c121f8d197bf8b15229d7ec754d41d59bebf2de2e232a99d0ed",
}
#: Bytes each shard occupied before it was lost (WP-EDGE-06 storage inventory).
PUBLISHED_15M_BYTES = {"BTC": 4_497_888, "ETH": 4_466_466, "SOL": 4_223_041}


def log(message: str) -> None:
    print(f"[{datetime.now(tz=UTC).strftime('%H:%M:%S')}] {message}", flush=True)


def fetch(symbol: str, interval: str, start_ms: int, end_ms: int) -> tuple[list[list], int]:
    rows: list[list] = []
    cursor = start_ms
    requests = 0
    while cursor < end_ms:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}&startTime={cursor}"
            f"&endTime={end_ms - 1}&limit={LIMIT}"
        )
        batch = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    batch = json.loads(response.read().decode())
                break
            except Exception as exc:  # noqa: BLE001 - the retry is the data
                if attempt == 4:
                    raise
                log(f"  retry {attempt + 1}/{symbol} {interval}: {exc!r}")
                time.sleep(2 * (attempt + 1))
        requests += 1
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][6] + 1
        if len(batch) < LIMIT:
            break
        time.sleep(0.15)
    return rows, requests


def bars_of(raw: list[list]) -> list[dict]:
    return [
        {
            "ts": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
        for k in raw
    ]


def digest_of_files(paths: list[Path]) -> str:
    """``edge01.data._digest``: sha256 over sorted ``name`` + ``sha256(file)`` pairs."""
    combined = hashlib.sha256()
    for path in sorted(paths):
        combined.update(path.name.encode("utf-8"))
        combined.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8"))
    return combined.hexdigest()


def one_hour(asset: str, out: Path, staging: Path) -> dict:
    log(f"1h {asset}: fetching")
    raw, requests = fetch(f"{asset}USDT", "1h", START_1H, END_1H)
    bars = bars_of(raw)
    staging.mkdir(parents=True, exist_ok=True)
    by_year: dict[int, list[dict]] = {}
    for bar in bars:
        by_year.setdefault(datetime.fromtimestamp(bar["ts"] / 1000, tz=UTC).year, []).append(bar)
    written: dict[str, dict] = {}
    for year, ybars in sorted(by_year.items()):
        path = staging / f"{asset}USDT_{year}.json"
        path.write_text(json.dumps(ybars), encoding="utf-8")
        written[str(year)] = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "bars": len(ybars),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    digest = digest_of_files(sorted(staging.glob(f"{asset}USDT_*.json")))
    last_ts = bars[-1]["ts"] if bars else None
    result = {
        "timeframe": "1h",
        "asset": asset,
        "requests": requests,
        "bars": len(bars),
        "first_ts": bars[0]["ts"] if bars else None,
        "last_ts": last_ts,
        "last_ts_is_frozen_end": last_ts == FROZEN_1H_END,
        "corpus_digest": digest,
        "frozen_prefix16": FROZEN_1H[asset],
        "digest_matches_frozen": digest[:16] == FROZEN_1H[asset],
        "files": written,
    }
    log(f"1h {asset}: {result['digest_matches_frozen']} ({digest[:16]})")
    if result["digest_matches_frozen"] and result["last_ts_is_frozen_end"]:
        out.mkdir(parents=True, exist_ok=True)
        for path in sorted(staging.glob(f"{asset}USDT_*.json")):
            (out / path.name).write_bytes(path.read_bytes())
        result["written_to"] = str(out)
    return result


def fifteen_minutes(asset: str, out: Path) -> dict:
    """Solve for the window the published bytes describe instead of guessing a start date."""
    requests = 0
    raw: list[list] = []
    for start in START_15M_CANDIDATES:
        log(f"15m {asset}: fetching from {start} to the frozen end")
        raw, used = fetch(f"{asset}USDT", "15m", start, FROZEN_15M_END + 1)
        requests += used
        estimated = 2 + sum(len(json.dumps(bar)) for bar in bars_of(raw)) + 2 * (len(raw) - 1)
        if estimated >= PUBLISHED_15M_BYTES[asset]:
            break
        log(f"15m {asset}: only ~{estimated} bytes at this start; reaching further back")
    bars = bars_of(raw)
    target_bytes = PUBLISHED_15M_BYTES[asset]
    target_sha = PUBLISHED_15M_SHA256[asset]
    log(f"15m {asset}: {len(bars)} bars fetched, last={bars[-1]['ts'] if bars else None}")
    if not bars or bars[-1]["ts"] != FROZEN_15M_END:
        return {
            "timeframe": "15m",
            "asset": asset,
            "requests": requests,
            "bars": len(bars),
            "last_ts": bars[-1]["ts"] if bars else None,
            "last_ts_is_frozen_end": False,
            "found": False,
            "reason": "the fetched history does not end at the frozen 15m end",
        }
    parts = [json.dumps(bar) for bar in bars]
    lengths = [len(part) for part in parts]
    count = len(parts)
    total = sum(lengths) + 2 * (count - 1) + 2

    def window_length(start: int) -> int:
        return sum(lengths[start:]) + 2 * (count - start - 1) + 2

    if window_length(0) == target_bytes:
        start = 0
    elif window_length(0) < target_bytes:
        return {
            "timeframe": "15m",
            "asset": asset,
            "found": False,
            "reason": (
                f"the whole fetched history serialises to {window_length(0)} bytes, less than "
                f"the published {target_bytes}: the missing window is older than this fetch"
            ),
        }
    else:
        low, high = 0, count - 1
        while low < high:
            middle = (low + high) // 2
            if window_length(middle) > target_bytes:
                low = middle + 1
            else:
                high = middle
        start = low
    # Same serialisation the 1h shards used and the one json.dumps produces: separators are
    # ", " (two bytes), which is what the length search above already assumed. Joining with a
    # bare comma would be a different file, and a different digest, for the same bars.
    payload = json.dumps(bars[start:]).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    prefix = hashlib.sha256(
        f"{asset}USDT_15m.json".encode("utf-8") + digest.encode("utf-8")
    ).hexdigest()[:16]
    result = {
        "timeframe": "15m",
        "asset": asset,
        "requests": requests,
        "bars_fetched": count,
        "window_bars": count - start,
        "window_first_ts": bars[start]["ts"],
        "window_last_ts": bars[-1]["ts"],
        "bytes": len(payload),
        "published_bytes": target_bytes,
        "sha256": digest,
        "published_sha256": target_sha,
        "sha256_matches_published": digest == target_sha,
        "corpus_digest_prefix16": prefix,
        "frozen_prefix16": FROZEN_15M[asset],
        "digest_matches_frozen": prefix == FROZEN_15M[asset],
        "last_ts_is_frozen_end": bars[-1]["ts"] == FROZEN_15M_END,
    }
    result["found"] = bool(result["sha256_matches_published"] and result["digest_matches_frozen"])
    log(f"15m {asset}: bytes={len(payload)} sha_match={result['sha256_matches_published']} "
        f"pin_match={result['digest_matches_frozen']}")
    if result["found"]:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{asset}USDT_15m.json").write_bytes(payload)
        result["written_to"] = str(out)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="checkout whose corpora are missing")
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--timeframes", default="1h,15m")
    parser.add_argument("--staging", required=True, help="scratch directory, never the corpus path")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    staging_root = Path(args.staging).resolve()
    corpus_1h = repo / "reports" / "alpha-expansion-v1" / "data"
    corpus_15m = repo / "data" / "raw" / "alpha003" / "price"
    results: list[dict] = []
    for asset in [item.strip() for item in args.assets.split(",") if item.strip()]:
        for timeframe in [item.strip() for item in args.timeframes.split(",") if item.strip()]:
            try:
                if timeframe == "1h":
                    results.append(
                        one_hour(asset, corpus_1h, staging_root / "1h" / asset)
                    )
                else:
                    results.append(fifteen_minutes(asset, corpus_15m))
            except Exception as exc:  # noqa: BLE001 - a failed asset is the datum
                log(f"{timeframe} {asset}: FAILED {exc!r}")
                results.append({"timeframe": timeframe, "asset": asset, "error": repr(exc)[:400]})
    report = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "repo": str(repo),
        "source": "BINANCE_PUBLIC_REST:/api/v3/klines",
        "acceptance": (
            "1h accepted only when the corpus digest equals FROZEN_SHARD_SHA256; 15m only when "
            "the shard bytes hash to the sha256 published before this recovery"
        ),
        "results": results,
        "supported": sorted(
            f"{row['timeframe']}:{row['asset']}" for row in results if row.get("found", row.get("digest_matches_frozen"))
        ),
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"supported: {report['supported']}")
    return 0 if len(report["supported"]) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
