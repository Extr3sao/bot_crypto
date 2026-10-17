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
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.oos_capture import (
    PERIOD_MS_1H,
    is_closed,
    last_open_ms,
    merge_and_write,
    merge_slice,
    next_since_ms,
    paginate,
    read_slice,
    row_from_ccxt,
    slice_sha256,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"

PREREG = OUT / "OOS_PREREGISTRATION_V2.json"
CAPTURE = OUT / "OOS_CAPTURE_MANIFEST_V2.json"
PROSPECTIVE_SLICE = OUT / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"
DESCRIPTIVE_SLICE = OUT / "scratch" / "OOS_DESCRIPTIVE_1H.jsonl"
#: Independent of the slice: one line per capture attempt and symbol, so coverage can be
#: recomputed without trusting the file the collector itself rewrites.
CAPTURE_LEDGER = OUT / "scratch" / "OOS_CAPTURE_LEDGER.jsonl"

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


def _rel(path: Path) -> str:
    """The path as the repository sees it, never as this host sees it.

    Artefacts are published so that a clean checkout can re-verify them; a
    ``C:\\Users\\…`` path in a committed manifest would make this machine the
    only place the holdout can be checked.
    """
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


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


def _fetch_symbol(
    symbol: str, since_ms: int, end_ms: int, exchange_id: str, page_limit: int = 1000
) -> tuple[list[list[float]], dict[str, Any]]:
    """Every closed bar for one symbol in ``[since_ms, end_ms)``, page by page.

    ``since_ms`` is the resumption point from the slice, not the freeze instant,
    so a restart fills the gap forward instead of re-downloading (and, in the
    previous implementation, overwriting) history it already held.
    """
    import ccxt

    exchange = getattr(ccxt, exchange_id)()
    pause = max(exchange.rateLimit, 1000) / 1000.0

    def fetch_page(cursor: int, limit: int) -> list[list[float]]:
        raw = exchange.fetch_ohlcv(symbol, "1h", since=cursor, limit=limit) or []
        time.sleep(pause)
        return [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in raw
        ]

    result = paginate(
        fetch_page,
        since_ms=since_ms,
        end_ms=end_ms,
        period_ms=PERIOD_MS_1H,
        page_limit=page_limit,
    )
    audit = {
        "requested_from_ms": int(since_ms),
        "requested_to_ms": int(end_ms),
        "pages": result.pages,
        "fetch_calls": result.fetch_calls,
        "stop_reason": result.stop_reason,
        "truncated": result.truncated,
        "retried_short_pages": result.retried_short_pages,
        "bars_returned": len(result.rows),
    }
    return result.rows, audit


def _append_ledger(entry: dict[str, Any]) -> None:
    """Append one line to the independent coverage ledger.

    ``O_APPEND`` + a single ``write`` keeps concurrent readers from ever seeing
    a half-written line; the collector never rewrites this file.
    """
    CAPTURE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(CAPTURE_LEDGER, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    now_ms = int(time.time() * 1000)
    end_ms = (now_ms // 3_600_000) * 3_600_000
    status = "CAPTURED"

    # Append-only starts here: read what the slice already holds, and fetch each
    # symbol forward from its newest held bar. Nothing below opens the slice for
    # writing directly, so a failed run cannot truncate it.
    existing_prospective = read_slice(PROSPECTIVE_SLICE)
    existing_descriptive = read_slice(DESCRIPTIVE_SLICE)
    held = [*existing_prospective, *existing_descriptive]
    sha_before = slice_sha256(existing_prospective)
    descriptive_sha_before = slice_sha256(existing_descriptive)
    rows_before = len(existing_prospective)

    fetched: dict[str, list[list[float]]] = {}
    fetch_audit: dict[str, dict[str, Any]] = {}
    try:
        for symbol in symbols:
            since = next_since_ms(held, symbol, floor_ms=start_ms, period_ms=PERIOD_MS_1H)
            rows, audit = _fetch_symbol(symbol, since, end_ms, exchange_id)
            fetched[symbol] = rows
            fetch_audit[symbol] = audit
    except Exception as exc:  # network is external to the scientific claim
        status = "NETWORK_UNAVAILABLE"
        print(f"[oos] capture could not reach the venue: {type(exc).__name__}: {exc}")

    prospective: dict[str, list[list[float]]] = {}
    descriptive: dict[str, list[list[float]]] = {}
    for symbol, rows in fetched.items():
        prospective[symbol] = [r for r in rows if r[0] > freeze_ms]
        descriptive[symbol] = [r for r in rows if r[0] <= freeze_ms]

    incoming_prospective: list[dict[str, Any]] = []
    incoming_descriptive: list[dict[str, Any]] = []
    for symbol in sorted(fetched):
        for raw in fetched[symbol]:
            open_ms = int(raw[0])
            if not is_closed(open_ms, now_ms, PERIOD_MS_1H):
                continue  # the current hour is still forming: not evidence yet
            target = incoming_prospective if open_ms > freeze_ms else incoming_descriptive
            target.append(row_from_ccxt(symbol, raw))

    merge_prospective = merge_slice(existing_prospective, incoming_prospective)
    merge_descriptive = merge_slice(existing_descriptive, incoming_descriptive)

    n_prospective: int | None = None
    sha_prospective: str | None = None
    n_descriptive: int | None = None
    sha_descriptive: str | None = None
    written: dict[str, Any] = {}
    if status == "CAPTURED":
        # Single-writer transaction: re-read under the lock, merge, replace atomically.
        # The reads above happened before the (slow) network fetch, so they are only
        # used to decide where to resume — never as the base of the write. Otherwise a
        # second collector that finished during our fetch would lose its bars.
        prospective_txn = merge_and_write(PROSPECTIVE_SLICE, incoming_prospective)
        descriptive_txn = merge_and_write(DESCRIPTIVE_SLICE, incoming_descriptive)
        merge_prospective = prospective_txn.merge
        merge_descriptive = descriptive_txn.merge
        rows_before = prospective_txn.rows_before
        sha_before = prospective_txn.sha256_before
        descriptive_sha_before = descriptive_txn.sha256_before
        n_prospective = prospective_txn.rows_after
        sha_prospective = prospective_txn.sha256_after
        n_descriptive = descriptive_txn.rows_after
        sha_descriptive = descriptive_txn.sha256_after
        written = {
            "prospective": {
                "rows": prospective_txn.rows_after,
                "bytes": prospective_txn.bytes_written,
            },
            "descriptive": {
                "rows": descriptive_txn.rows_after,
                "bytes": descriptive_txn.bytes_written,
            },
        }
        partial_excluded = sum(
            1
            for rows in fetched.values()
            for row in rows
            if not is_closed(int(row[0]), now_ms, PERIOD_MS_1H)
        )
        _append_ledger(
            {
                "schema_version": "EDGE17_OOS_CAPTURE_LEDGER_V1",
                "captured_at_utc": _utc(capture_ns),
                "capture_started_unix_ns": capture_ns,
                "status": status,
                "slice_path": _rel(PROSPECTIVE_SLICE),
                "slice_sha256_before": sha_before,
                "slice_sha256_after": sha_prospective,
                "rows_before": rows_before,
                "rows_after": n_prospective,
                "added": merge_prospective.added,
                "duplicates_identical": merge_prospective.duplicates_identical,
                "conflicts": len(merge_prospective.conflicts),
                "partial_bar_excluded": partial_excluded,
                "symbols": {
                    symbol: {
                        "opens": [
                            int(row["timestamp"])
                            for row in merge_prospective.rows
                            if row["symbol"] == symbol
                        ],
                        "fetched": len(fetched.get(symbol, [])),
                        "requested_from_ms": fetch_audit.get(symbol, {}).get("requested_from_ms"),
                        "pages": fetch_audit.get(symbol, {}).get("pages"),
                        "stop_reason": fetch_audit.get(symbol, {}).get("stop_reason"),
                    }
                    for symbol in symbols
                },
            }
        )
    else:
        # Nothing was written: report the slice as it stands, never as zero.
        partial_excluded = 0
        n_prospective = rows_before
        sha_prospective = sha_before
        n_descriptive = len(existing_descriptive)
        sha_descriptive = descriptive_sha_before

    order["all_prospective_bars_open_after_freeze"] = all(
        row["timestamp"] > freeze_ms for row in merge_prospective.rows
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
        (row["timestamp"] for row in merge_prospective.rows), default=None
    )
    per_symbol_captured = {
        symbol: {
            "prospective_bars": sum(1 for row in merge_prospective.rows if row["symbol"] == symbol),
            "descriptive_bars": sum(1 for row in merge_descriptive.rows if row["symbol"] == symbol),
            "newly_added": sum(
                1
                for row in merge_prospective.rows
                if row["symbol"] == symbol
                and row["timestamp"] > (last_open_ms(existing_prospective, symbol) or -1)
            ),
        }
        for symbol in sorted(set(fetched) | set(symbols))
    }
    manifest = {
        "schema_version": "EDGE15_OOS_CAPTURE_V3",
        "work_package": "WP-EDGE-015/P0.1 (capture contract repaired by WP-EDGE-017/P0.1)",
        "captured_at_utc": _utc(capture_ns),
        "capture_started_unix_ns": capture_ns,
        "capture_status": status,
        "preregistration": {
            "path": _rel(PREREG),
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
            "first_prospective_bar_open_utc": (
                _utc(int(first_prospective_open_ms) * 1_000_000)
                if first_prospective_open_ms is not None
                else None
            ),
        },
        "prospective": {
            "path": _rel(PROSPECTIVE_SLICE),
            "bars": n_prospective,
            "sha256": sha_prospective,
            "rule": "bar open_ms > frozen_at_epoch_ms",
            "cumulative": True,
        },
        "append_only": {
            "contract": (
                "existing rows are read first and never replaced; the merged file is written "
                "to a temporary sibling and moved with os.replace, so a failed run leaves the "
                "previous slice intact"
            ),
            "rows_before": rows_before,
            "rows_after": n_prospective,
            "added": merge_prospective.added,
            "duplicates_identical": merge_prospective.duplicates_identical,
            "conflicts": list(merge_prospective.conflicts),
            "slice_sha256_before": sha_before,
            "slice_sha256_after": sha_prospective,
            "descriptive_slice_sha256_before": descriptive_sha_before,
            "descriptive_slice_sha256_after": sha_descriptive,
            "partial_bars_excluded": partial_excluded,
            "ledger": _rel(CAPTURE_LEDGER),
        },
        "pagination": fetch_audit,
        "bytes_written": {
            key: {"rows": value["rows"], "bytes": value["bytes"]}
            for key, value in (written or {}).items()
        },
        "descriptive": {
            "path": _rel(DESCRIPTIVE_SLICE),
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
        "state": ("OOS_ACCRUING" if not n_prospective else "OOS_ACCRUING_WITH_PROSPECTIVE_BARS"),
        "symbols": per_symbol_captured,
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
    if not n_prospective:
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
