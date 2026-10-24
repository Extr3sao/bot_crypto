"""WP-EDGE04-RECOVERY-15M — replay the producer that wrote the frozen 15m corpus.

``scripts/alpha003_run.py`` is the only code that ever wrote
``data/raw/alpha003/price/<SYM>USDT_<tf>.json``.  It fetched with
``ccxt.binanceusdm.fetch_ohlcv`` from ``2024-10-01T00:00:00Z``, paging by ``last_ts + 1``
and stopping on a short batch, then wrote ``json.dumps(rows)`` — default separators, no
indent, no trailing newline, rows as ``[ts, o, h, l, c, v]``.

Re-running those exact calls answers the only question that decides this work package: can
the frozen bytes be produced again from the venue?  The comparison target is not this
script's own output — it is the two records written before the corpus was lost, the plain
``sha256`` in ``data/economic001/EVIDENCE_CLOSURE.json`` and the ``st_size`` in the
WP-EDGE-06 storage inventory.

The corpus file is never written to ``data/``: a near-identical shard placed where the pin
looks would be exactly the substitution the work package forbids.  Candidates land under
``--out`` and only their digests travel into the evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The producer's own constants (``scripts/alpha003_run.py``).
SINCE = "2024-10-01T00:00:00Z"
MARKET = {"BTC": "BTC/USDT:USDT", "ETH": "ETH/USDT:USDT", "SOL": "SOL/USDT:USDT"}

#: Frozen last 15m bar (open, ms UTC) — ``edge03.forward_plan.FROZEN_15M_END_MS``.
CUT_15M = 1_791_372_600_000

#: Plain sha256 recorded 2026-10-08 by the economic closure, and the pin the EDGE lane carries.
RECORDED_SHA = {
    "BTC": "60b0630153dc8e879d63c9691712c8e15d06ede0cc2ae815725340e44c4e9d7f",
    "ETH": "b3b1f02e9a299500b77fc3b8d31a31c3856820daa1c99bba3921d74cec5b943e",
    "SOL": "d3a637c2f5e98c121f8d197bf8b15229d7ec754d41d59bebf2de2e232a99d0ed",
}
FROZEN_PIN = {"BTC": "cd1d2ea256a97f7c", "ETH": "b8fd5744cc66f635", "SOL": "72a268137cbe944b"}

#: ``st_size`` from ``reports/edge-recovery/WP-EDGE-06/STORAGE_INVENTORY.json``.  SOL is not
#: in that list (it records the biggest files per subtree), so its size is ``None`` and the
#: evidence says so instead of inventing one.
RECORDED_BYTES = {"BTC": 4_497_888, "ETH": 4_466_466, "SOL": None}

#: One control on a different timeframe whose recorded size is also on file: if the recipe
#: reproduces 5m row counts and lands within a few bytes of the recorded size, the 15m
#: residual is a property of *when* the producer ran, not of a missing file.
#: The control's cut is **fitted**, and the evidence says so: the recorded 13,389,298 bytes are
#: 124 bytes (two 5m rows) more than the series truncated at the 15m cut, and 124 bytes past a
#: 62-byte row puts the original file's last row at the 11:40 bar — i.e. the producer ran
#: between 11:40 and 11:45 UTC.  Fitting the cut is what makes the control a measurement of the
#: *recipe* rather than of the calendar.
CONTROL = {"asset": "BTC", "timeframe": "5m", "recorded_bytes": 13_389_298,
           "recorded_sha": "4413f407bca6ae52d26b1a9498ba2fe2e1ccdd8d0c6639ddf31ecca3e335ab1a",
           "cut_ms": CUT_15M + 600_000}


def pin_digest(name: str, file_sha: str) -> str:
    """``edge01.data._digest`` for a one-file corpus: sha256(name + sha256(bytes))."""
    return hashlib.sha256((name + file_sha).encode("utf-8")).hexdigest()


def fetch(ex, market: str, timeframe: str, since_iso: str) -> tuple[list[list[float]], int]:
    """The producer's paging loop, restated: same since, same limit, same stop rule."""
    since = ex.parse8601(since_iso)
    rows: list[list[float]] = []
    requests = 0
    while True:
        batch = ex.fetch_ohlcv(market, timeframe, since=since, limit=1000)
        requests += 1
        if not batch:
            break
        rows.extend(batch)
        since = int(batch[-1][0]) + 1
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000.0)
    return rows, requests


def describe(raw: bytes, name: str, *, recorded_sha: str | None, pin: str | None,
             recorded_bytes: int | None) -> dict[str, Any]:
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "bytes": len(raw),
        "file_sha256": sha,
        "pin_digest_prefix16": pin_digest(name, sha)[:16],
        "rows": len(json.loads(raw)),
        "recorded_bytes": recorded_bytes,
        "byte_delta_vs_recorded": (len(raw) - recorded_bytes) if recorded_bytes else None,
        "matches_recorded_file_sha256": (sha == recorded_sha) if recorded_sha else None,
        "matches_frozen_pin": (pin_digest(name, sha)[:16] == pin) if pin else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="where candidate bytes and the report go")
    ap.add_argument("--control-5m", action="store_true", help="also replay the 5m control")
    args = ap.parse_args(argv)
    import ccxt

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ex = ccxt.binanceusdm({"enableRateLimit": True})
    report: dict[str, Any] = {
        "wp": "WP-EDGE04-RECOVERY-15M",
        "producer": "scripts/alpha003_run.py (fetch_ohlcv + json.dumps(rows))",
        "venue": "ccxt.binanceusdm -> fapi.binance.com /fapi/v1/klines",
        "ccxt_version": ccxt.__version__,
        "since": SINCE,
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cut_15m_ms": CUT_15M,
        "series": {},
    }

    for asset, market in MARKET.items():
        rows, requests = fetch(ex, market, "15m", SINCE)
        name = f"{asset}USDT_15m.json"
        truncated = [r for r in rows if r[0] <= CUT_15M]
        full_raw = json.dumps(rows).encode("utf-8")
        trunc_raw = json.dumps(truncated).encode("utf-8")
        (out / f"candidate_{name}").write_bytes(trunc_raw)
        (out / f"candidate_{name}.full").write_bytes(full_raw)
        report["series"][asset] = {
            "requests": requests,
            "rows_fetched_now": len(rows),
            "last_ts_now": rows[-1][0] if rows else None,
            "frozen": describe(trunc_raw, name, recorded_sha=RECORDED_SHA[asset],
                               pin=FROZEN_PIN[asset], recorded_bytes=RECORDED_BYTES[asset]),
            "frozen_first_ts": truncated[0][0] if truncated else None,
            "frozen_last_ts": truncated[-1][0] if truncated else None,
            "untruncated": describe(full_raw, name, recorded_sha=None, pin=None,
                                    recorded_bytes=None),
            "candidate_path": str(out / f"candidate_{name}"),
        }
        print(f"{asset} 15m: {len(truncated)} rows <= cut, "
              f"{len(trunc_raw)} bytes (recorded {RECORDED_BYTES[asset]}), "
              f"sha match={report['series'][asset]['frozen']['matches_recorded_file_sha256']}",
              flush=True)

    if args.control_5m:
        rows, requests = fetch(ex, MARKET[CONTROL["asset"]], CONTROL["timeframe"], SINCE)
        name = f"{CONTROL['asset']}USDT_{CONTROL['timeframe']}.json"
        # The recorded size belongs to the file as it stood on 2026-10-07, so the control is
        # cut at that instant; comparing a series fetched through today against a three-week-old
        # size would only measure the calendar.
        rows = [r for r in rows if r[0] <= CONTROL["cut_ms"]]
        raw = json.dumps(rows).encode("utf-8")
        (out / f"control_{name}").write_bytes(raw)
        report["control_5m"] = {
            "requests": requests,
            "rows": len(rows),
            "truncated_at_ms": CONTROL["cut_ms"],
            **describe(raw, name, recorded_sha=CONTROL["recorded_sha"], pin=None,
                       recorded_bytes=CONTROL["recorded_bytes"]),
        }
        print(f"control 5m: {len(rows)} rows, {len(raw)} bytes "
              f"(recorded {CONTROL['recorded_bytes']}, delta "
              f"{len(raw) - CONTROL['recorded_bytes']})", flush=True)

    (out / "REFETCH.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
