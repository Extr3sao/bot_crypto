"""edge15_oos_preregistration — freeze first, capture second, prove the order.

WP-EDGE-14R left this defect on the record: its capture manifest carried
``order_check: "preregistration_frozen_at_utc < captured_at_utc: False"``. Both
timestamps had one-second resolution and came from the same run, so the string
comparison was False and the package could not show that the protocol preceded
the data. A preregistration written in the same breath as the capture is a
description, not a commitment.

This script splits the two into separate invocations:

    python scripts/edge15_oos_preregistration.py --freeze     # commit this, then
    python scripts/edge15_oos_preregistration.py --capture

``--freeze`` writes the protocol once and refuses to overwrite it. It records a
nanosecond timestamp, the digest of the file it wrote, and the digest of the
exhausted corpus. ``--capture`` re-hashes that file, reads its recorded instant,
reads *its own* instant **before** it touches the network, and then splits what
it fetches:

* a bar whose **open** is after the freeze instant is ``prospective`` — no
  decision in this project had seen it when the protocol was written;
* a bar at or before the freeze instant is ``descriptive`` — it is data, and it
  is kept, but it cannot carry an out-of-sample inference now that it postdates
  nothing.

The order check is a structured verdict with the numbers in it, not a sentence
containing ``False``. Its one assumption is stated rather than implied: the two
instants come from the same host clock, read in different processes, and the
frozen file is committed between them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"

PREREG = OUT / "OOS_PREREGISTRATION_V2.json"
CAPTURE = OUT / "OOS_CAPTURE_MANIFEST_V2.json"
PROSPECTIVE_SLICE = OUT / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"
DESCRIPTIVE_SLICE = OUT / "scratch" / "OOS_DESCRIPTIVE_1H.jsonl"

#: The 14R slice, captured before this freeze existed. It is data, and it is now
#: descriptive for every hypothesis frozen below, because none of them was
#: written when it was fetched.
V1_SLICE = (
    REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R" / "scratch" / "OOS_SLICE_1H.jsonl"
)

#: The window the corpus was exhausted at (14R). Everything at or after the
#: boundary is unseen by the selection that consumed that corpus.
BOUNDARY_MS = 1_792_162_800_000


def _utc(ns: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ns / 1_000_000_000))


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _canonical_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _git_state(path: Path) -> dict[str, Any]:
    """The committed blob and its commit time for ``path``, or why not.

    The freeze file cannot contain its own digest (writing it would change it),
    so the digest that binds it is the one Git recorded when the file was
    committed. This reads that blob back and hashes it, both raw and with LF
    normalisation, because a checkout may have rewritten line endings.
    """
    rel = path.relative_to(REPO).as_posix()
    try:
        blob = subprocess.run(
            ["git", "-C", str(REPO), "show", f"HEAD:{rel}"],
            capture_output=True,
            check=True,
        ).stdout
        stamp = subprocess.run(
            ["git", "-C", str(REPO), "log", "-1", "--format=%ct", "--", rel],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception as exc:  # git absent, or the file is not committed yet
        return {"committed": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "committed": True,
        "commit": head,
        "commit_unix": int(stamp) if stamp.isdigit() else None,
        "blob_sha256": hashlib.sha256(blob).hexdigest(),
        "blob_sha256_lf": hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest(),
        "path": rel,
    }


def freeze(protocol: dict[str, Any], *, force: bool = False) -> int:
    if PREREG.exists() and not force:
        print(f"[oos] REFUSED: {PREREG.name} already exists — a freeze is immutable")
        print("[oos] delete it deliberately if the protocol must be re-frozen, and say why")
        return 2

    ns = time.time_ns()
    payload: dict[str, Any] = {
        "schema_version": "EDGE15_OOS_PREREGISTRATION_V2",
        "work_package": "WP-EDGE-015/P0.1",
        "kind": "PROSPECTIVE_HOLDOUT",
        "frozen_at_unix_ns": ns,
        "frozen_at_epoch_ms": ns // 1_000_000,
        "frozen_at_utc": _utc(ns),
        "clock": (
            "host wall clock, nanosecond resolution, read in the freeze process before "
            "this file was written; the file is committed before any capture runs"
        ),
        "file_digest_binding": (
            "this file cannot contain its own digest: the binding digest is the one Git "
            "recorded in the commit that adds it, and the capture compares the working "
            "bytes against that committed blob"
        ),
        "prospective_boundary_ms": BOUNDARY_MS,
        "previously_captured": {
            "path": str(V1_SLICE),
            "sha256": _sha256(V1_SLICE),
            "status": "DESCRIPTIVE_FOR_THESE_HYPOTHESES",
            "why": (
                "captured by WP-EDGE-14R at 2026-10-16T20:01:44Z, before this protocol "
                "existed, so no bar in it can be prospective with respect to it"
            ),
        },
        "protocol": protocol,
    }
    payload["protocol_sha256"] = _canonical_sha(dict(payload["protocol"]))
    PREREG.parent.mkdir(parents=True, exist_ok=True)
    PREREG.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["file_sha256"] = _sha256(PREREG)  # reported, not stored: see below
    print(f"[oos] FROZEN at {payload['frozen_at_utc']} (ns={ns})")
    print(f"[oos] file sha256 {payload['file_sha256']}")
    print(f"[oos] protocol sha256 {payload['protocol_sha256']}")
    print("[oos] commit this file before running --capture")
    return 0


def _fetch(
    symbols: list[str], start_ms: int, end_ms: int, exchange_id: str
) -> dict[str, list[list[float]]]:
    import ccxt

    exchange = getattr(ccxt, exchange_id)()
    out: dict[str, list[list[float]]] = {}
    for symbol in symbols:
        raw = exchange.fetch_ohlcv(symbol, "1h", since=start_ms, limit=1000) or []
        out[symbol] = [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in raw
            if start_ms <= int(r[0]) < end_ms
        ]
        time.sleep(max(exchange.rateLimit, 1000) / 1000.0)
    return out


def _write_slice(path: Path, bars: dict[str, list[list[float]]]) -> tuple[int, str | None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with path.open("w", encoding="utf-8") as handle:
        for symbol in sorted(bars):
            for row in bars[symbol]:
                handle.write(
                    json.dumps(
                        {
                            "symbol": symbol,
                            "timestamp": row[0],
                            "open": row[1],
                            "high": row[2],
                            "low": row[3],
                            "close": row[4],
                            "volume": row[5],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                rows += 1
    return rows, _sha256(path)


def capture(symbols: list[str], exchange_id: str) -> int:
    if not PREREG.is_file():
        print(f"[oos] REFUSED: {PREREG.name} does not exist — freeze before capturing")
        return 2
    prereg: dict[str, Any] = json.loads(PREREG.read_text(encoding="utf-8"))
    freeze_ns = int(prereg["frozen_at_unix_ns"])
    freeze_ms = int(prereg["frozen_at_epoch_ms"])

    # The capture instant is read BEFORE any network call, and it is compared
    # against the instant stored inside the frozen file.
    capture_ns = time.time_ns()
    prereg_sha = _sha256(PREREG)
    protocol_sha = _canonical_sha(dict(prereg["protocol"]))
    git_state = _git_state(PREREG)
    disk = PREREG.read_bytes()
    disk_lf = hashlib.sha256(disk.replace(b"\r\n", b"\n")).hexdigest()
    order: dict[str, Any] = {
        "method": (
            "the frozen file records its own nanosecond instant and is committed before "
            "this runs; the capture reads its own instant before the first network call, "
            "compares the two integers, and compares the file on disk against the blob "
            "Git holds for that commit"
        ),
        "freeze_at_unix_ns": freeze_ns,
        "capture_started_unix_ns": capture_ns,
        "delta_ns": capture_ns - freeze_ns,
        "assumption": (
            "both instants come from the same host clock in different processes; the commit "
            "between them is what makes the ordering checkable from outside this machine"
        ),
        "preregistration_file": {
            "disk_sha256": prereg_sha,
            "disk_sha256_lf": disk_lf,
            "git": git_state,
        },
    }
    order["freeze_precedes_capture"] = capture_ns > freeze_ns
    committed_blob = git_state.get("blob_sha256")
    committed_blob_lf = git_state.get("blob_sha256_lf")
    order["prereg_file_matches_committed_blob"] = bool(
        git_state.get("committed")
        and (prereg_sha in (committed_blob, committed_blob_lf) or disk_lf == committed_blob_lf)
    )
    commit_unix = git_state.get("commit_unix")
    order["commit_precedes_capture"] = bool(
        isinstance(commit_unix, int) and commit_unix * 1_000_000_000 < capture_ns
    )
    order["protocol_digest_matches"] = protocol_sha == prereg.get("protocol_sha256")

    start_ms = max(BOUNDARY_MS + 3_600_000, freeze_ms)
    end_ms = (int(time.time() * 1000) // 3_600_000) * 3_600_000
    status = "CAPTURED"
    fetched: dict[str, list[list[float]]] = {}
    try:
        fetched = _fetch(symbols, start_ms, end_ms, exchange_id)
    except Exception as exc:  # network is external to the scientific claim
        status = "NETWORK_UNAVAILABLE"
        print(f"[oos] capture could not reach the venue: {type(exc).__name__}: {exc}")

    prospective: dict[str, list[list[float]]] = {}
    descriptive: dict[str, list[list[float]]] = {}
    for symbol, rows in fetched.items():
        prospective[symbol] = [r for r in rows if r[0] > freeze_ms]
        descriptive[symbol] = [r for r in rows if r[0] <= freeze_ms]

    n_prospective, sha_prospective = (
        _write_slice(PROSPECTIVE_SLICE, prospective) if status == "CAPTURED" else (0, None)
    )
    n_descriptive, sha_descriptive = (
        _write_slice(DESCRIPTIVE_SLICE, descriptive) if status == "CAPTURED" else (0, None)
    )
    order["all_prospective_bars_open_after_freeze"] = all(
        row[0] > freeze_ms for rows in prospective.values() for row in rows
    )
    order["verdict"] = (
        "ORDER_VERIFIED"
        if order["freeze_precedes_capture"]
        and order["prereg_file_matches_committed_blob"]
        and order["commit_precedes_capture"]
        and order["protocol_digest_matches"]
        and order["all_prospective_bars_open_after_freeze"]
        else "ORDER_VIOLATED"
    )

    first_prospective_open_ms = min(
        (row[0] for rows in prospective.values() for row in rows), default=None
    )
    manifest = {
        "schema_version": "EDGE15_OOS_CAPTURE_V2",
        "work_package": "WP-EDGE-015/P0.1",
        "captured_at_utc": _utc(capture_ns),
        "capture_started_unix_ns": capture_ns,
        "capture_status": status,
        "preregistration": {
            "path": str(PREREG),
            "file_sha256": prereg_sha,
            "protocol_sha256": protocol_sha,
            "frozen_at_unix_ns": freeze_ns,
            "frozen_at_utc": prereg["frozen_at_utc"],
        },
        "order_check": order,
        "window": {
            "capture_from_ms": start_ms,
            "capture_to_ms": end_ms,
            "freeze_epoch_ms": freeze_ms,
            "first_prospective_bar_open_ms": first_prospective_open_ms,
        },
        "prospective": {
            "path": str(PROSPECTIVE_SLICE),
            "bars": n_prospective,
            "sha256": sha_prospective,
            "rule": "bar open_ms > frozen_at_epoch_ms",
        },
        "descriptive": {
            "path": str(DESCRIPTIVE_SLICE),
            "bars": n_descriptive,
            "sha256": sha_descriptive,
            "rule": "boundary <= bar open_ms <= frozen_at_epoch_ms",
            "reading": (
                "kept as descriptive evidence: these bars were fetched after the freeze, so "
                "no hypothesis was fitted to them, but they start before the freeze instant "
                "and therefore carry no prospective claim"
            ),
        },
        "previously_captured": prereg["previously_captured"],
        "selection_has_read_any_slice": False,
        "scoring_run": False,
        "state": ("OOS_ACCRUING" if n_prospective < 1 else "OOS_ACCRUING_WITH_PROSPECTIVE_BARS"),
        "symbols": {
            symbol: {
                "prospective_bars": len(prospective.get(symbol, [])),
                "descriptive_bars": len(descriptive.get(symbol, [])),
            }
            for symbol in sorted(fetched)
        },
    }
    CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"[oos] order check: {order['verdict']} (freeze->capture {order['delta_ns'] / 1e9:.1f} s, "
        f"committed={git_state.get('committed')}, commit={str(git_state.get('commit'))[:12]})"
    )
    print(
        f"[oos] capture status {status}; prospective bars {n_prospective}, descriptive {n_descriptive}"
    )
    if n_prospective == 0:
        print(
            "[oos] zero prospective bars yet: every bar fetched so far starts at or before "
            "the freeze instant, which is the expected state within the first hour"
        )
    return 0 if order["verdict"] == "ORDER_VERIFIED" else 1


def default_protocol() -> dict[str, Any]:
    """The protocol frozen for WP-EDGE-015, with its own parameters spelled out."""
    from trading_bot.research.economic_recovery.alpha15 import FROZEN_PROTOCOL

    return FROZEN_PROTOCOL


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-015 prospective holdout preregistration")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-freeze (deliberate, recorded)")
    parser.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT")
    parser.add_argument("--exchange", default="binance")
    args = parser.parse_args()
    if args.freeze == args.capture:
        parser.error("choose exactly one of --freeze / --capture")
    if args.freeze:
        return freeze(default_protocol(), force=args.force)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    return capture(symbols, args.exchange)


if __name__ == "__main__":
    raise SystemExit(main())
