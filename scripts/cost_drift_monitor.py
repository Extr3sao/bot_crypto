"""ST-6 cost-drift monitor — append-only forward sampling of the modelled cost assumptions.

The ECONOMIC-001 closure left one defect open (ECO-1) and one premise measured exactly once: the
only window in which the spread, the observation latency and the book depth were ever *observed*
lasted 32 seconds.  The whole business case rests on one modelled term — 1.0 bps of round-trip
spread, 0.25 bps of size-driven impact — and RFC-046's standing kill-switch (ST-6) fires when the
realised cost comes in above the modelled cost.  A single snapshot cannot fire it and cannot clear
it.

This monitor is that missing instrument, and nothing more:

* it collects a **finite, declared** window with the same public, credential-free endpoints as the
  read-only probe (no key, no signature, no order);
* it **appends** one record per window to an append-only history, keeping the raw bytes of each
  window as evidence and recording their sha256;
* it re-derives, from the accumulated history, whether the cost assumptions still hold, using a
  **declared rule** rather than a story: pooled and worst spread against the modelled 1.0 bps,
  the 200 USDT depth walk against the modelled 0.25 bps, and depth coverage of the account size;
* it states when the sample is still too small to conclude, instead of dressing two windows as a
  regime.

It creates no hypothesis, admits nothing, opens no campaign, touches no credential and sends no
order.  Its outcomes are all decision-grade: WITHIN the assumptions, AT the modelled boundary, or
DRIFT — the last one being exactly the condition that invalidates the recommended cost profile.

Run:  python scripts/cost_drift_monitor.py                 (collect one window, append, judge)
      python scripts/cost_drift_monitor.py --rounds 3 --spacing 5
      python scripts/cost_drift_monitor.py --judge-only    (re-judge the history, collect nothing)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from economic001_readonly_probe import collect  # noqa: E402

DATA = REPO / "data" / "economic001"
HISTORY = DATA / "COST_DRIFT_HISTORY.jsonl"
RAW_DIR = DATA / "drift_raw"
STATUS = DATA / "COST_DRIFT_STATUS.json"

BPS = 10_000.0
ACCOUNT_USDT = 200.0
MODELLED_SPREAD_BPS = 1.0  # the frozen model's round-trip spread term
MODELLED_IMPACT_BPS = 0.25  # the frozen model's base impact term
BOUNDARY_MULTIPLE = 1.5  # a spread above 1.5x the modelled term is drift, not a boundary case
MIN_WINDOWS = 3  # declared minimum before a verdict stops being provisional
ROUNDS = 3
SPACING_S = 5.0
DEPTH_LIMIT = 100
VERDICTS = (
    "WITHIN_MODELLED_ASSUMPTIONS",
    "AT_THE_MODELLED_BOUNDARY",
    "DRIFT_WIDER_THAN_MODELLED",
    "INSUFFICIENT_EVIDENCE",
)


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _walk_bps(levels: list[list[float]], notional: float) -> float | None:
    """Level-consuming walk, the same arithmetic as the closure's taker walk.

    Returns None when the sampled book cannot fill the notional, which is itself a finding.
    """
    if not levels:
        return None
    best = levels[0][0]
    remaining, spent, quantity = notional, 0.0, 0.0
    for price, size in levels:
        take = min(remaining, price * size)
        if take <= 0:
            break
        spent += take
        quantity += take / price
        remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-9 or quantity <= 0:
        return None
    return (spent / quantity - best) / best * BPS


def window_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    symbols = snapshot["symbols"]
    spreads: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    for row in snapshot["observations"]:
        for symbol, book in row["books"].items():
            spreads[symbol].append(book["spread_bps"])
    pool = [value for values in spreads.values() for value in values]
    per_symbol = {symbol: round(_median(values), 6) for symbol, values in spreads.items() if values}

    walks: dict[str, dict[str, float | None]] = {}
    for symbol in symbols:
        asks = snapshot["observations"][0]["depth"].get(symbol, {}).get("asks", [])
        bids = snapshot["observations"][0]["depth"].get(symbol, {}).get("bids", [])
        walks[symbol] = {
            "buy": _walk_bps(asks, ACCOUNT_USDT),
            "sell": _walk_bps(bids, ACCOUNT_USDT),
        }
    numeric_walks = [
        value for entry in walks.values() for value in entry.values() if isinstance(value, float)
    ]
    covered = all(isinstance(value, float) for entry in walks.values() for value in entry.values())
    latency = {
        channel: round(_median(values), 3)
        for channel, values in snapshot["latency_ms"]["samples"].items()
        if values
    }
    offsets = [
        row["clock_offset_ms"] for row in snapshot["observations"] if "clock_offset_ms" in row
    ]
    return {
        "pooled_median_spread_bps": round(_median(pool), 6),
        "worst_spread_bps": round(max(pool), 6),
        "per_symbol_median_spread_bps": per_symbol,
        "worst_walk_bps_at_account_size": round(max(numeric_walks), 6) if numeric_walks else None,
        "walk_by_symbol": walks,
        "depth_covers_account_size": covered,
        "latency_median_ms": latency,
        "clock_offset_median_ms": round(_median(offsets), 3) if offsets else None,
        "observations": len(snapshot["observations"]),
    }


def judge(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Declared rule, applied to the accumulated history: no story, no cherry-picking."""
    if not history:
        component = {
            "spread": "INSUFFICIENT_EVIDENCE",
            "impact": "INSUFFICIENT_EVIDENCE",
            "depth": "INSUFFICIENT_EVIDENCE",
        }
        return {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "components": component,
            "windows": 0,
            "provisional": True,
            "why": "no window has been collected yet",
        }

    def spread_verdict(median: float, worst: float) -> str:
        if worst <= MODELLED_SPREAD_BPS:
            return "WITHIN"
        if median <= MODELLED_SPREAD_BPS and worst <= BOUNDARY_MULTIPLE * MODELLED_SPREAD_BPS:
            return "AT_BOUNDARY"
        return "DRIFT"

    spread = [
        spread_verdict(row["pooled_median_spread_bps"], row["worst_spread_bps"]) for row in history
    ]
    walks = [
        row["worst_walk_bps_at_account_size"]
        for row in history
        if row["worst_walk_bps_at_account_size"] is not None
    ]
    impact = [
        "WITHIN"
        if value <= MODELLED_IMPACT_BPS
        else ("AT_BOUNDARY" if value <= BOUNDARY_MULTIPLE * MODELLED_IMPACT_BPS else "DRIFT")
        for value in walks
    ]
    depth = ["WITHIN" if row["depth_covers_account_size"] else "DRIFT" for row in history]

    def worst_of(values: list[str]) -> str:
        if not values:
            return "INSUFFICIENT_EVIDENCE"
        if "DRIFT" in values:
            return "DRIFT"
        if "AT_BOUNDARY" in values:
            return "AT_BOUNDARY"
        return "WITHIN"

    components = {
        "spread": worst_of(spread),
        "impact": worst_of(impact),
        "depth": worst_of(depth),
    }
    if (
        components["spread"] == "DRIFT"
        or components["impact"] == "DRIFT"
        or components["depth"] == "DRIFT"
    ):
        verdict = "DRIFT_WIDER_THAN_MODELLED"
    elif components["spread"] == "AT_BOUNDARY" or components["impact"] == "AT_BOUNDARY":
        verdict = "AT_THE_MODELLED_BOUNDARY"
    elif len(history) < MIN_WINDOWS:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "WITHIN_MODELLED_ASSUMPTIONS"
    return {
        "verdict": verdict,
        "components": components,
        "windows": len(history),
        "provisional": len(history) < MIN_WINDOWS,
        "why": (
            f"{len(history)} window(s) collected; a verdict stops being provisional at "
            f"{MIN_WINDOWS}.  Spread is judged on the pooled median and the worst observation "
            f"against the modelled {MODELLED_SPREAD_BPS} bps round trip, impact on the "
            f"{ACCOUNT_USDT:.0f} USDT depth walk against the modelled {MODELLED_IMPACT_BPS} bps, "
            "depth on whether the account size fits inside the sampled book"
        ),
    }


def collect_window(rounds: int, spacing: float, depth_limit: int, keep_raw: bool) -> dict[str, Any]:
    snapshot = collect(rounds, spacing, depth_limit)
    window_id = _window_id()
    metrics = window_metrics(snapshot)
    body = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    raw_path = None
    if keep_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        target = RAW_DIR / f"{window_id}.json"
        target.write_text(body, encoding="utf-8")
        raw_path = str(target.relative_to(REPO))
        # Hash the bytes that are actually on disk: text mode translates the newline, so hashing the
        # in-memory string would record a digest no reader could ever reproduce.
        raw_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    else:
        raw_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

    return {
        "window_id": window_id,
        "collected_at_utc": _utc(),
        "artifact": "ECONOMIC-001_COST_DRIFT_WINDOW",
        "provenance": "cost_drift_monitor",
        "budget": snapshot["budget"],
        "requests_made": snapshot["budget"]["requests_made"],
        "duration_s": snapshot["duration_s"],
        "window_complete": snapshot["complete"],
        "failures": snapshot["failures"],
        "orders_sent": snapshot["orders_sent"],
        "credentials_used": snapshot["credentials_used"],
        "raw_path": raw_path,
        "raw_sha256": raw_sha,
        **metrics,
    }


def import_window(path: Path, provenance: str) -> dict[str, Any]:
    """Adopt an already-collected window into the history, re-deriving its metrics here.

    The provenance is recorded, so a window collected by another tool is never silently mixed with
    this monitor's own: the reader always knows which run produced which bytes.
    """
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    stamp = snapshot.get("local_finished_utc") or snapshot.get("local_started_utc") or _utc()
    window_id = stamp.replace("-", "").replace(":", "").split(".")[0] + "Z"
    return {
        "window_id": window_id,
        "collected_at_utc": stamp,
        "artifact": "ECONOMIC-001_COST_DRIFT_WINDOW",
        "provenance": provenance,
        "budget": snapshot["budget"],
        "requests_made": snapshot["budget"]["requests_made"],
        "duration_s": snapshot["duration_s"],
        "window_complete": snapshot["complete"],
        "failures": snapshot["failures"],
        "orders_sent": snapshot["orders_sent"],
        "credentials_used": snapshot["credentials_used"],
        "raw_path": str(path.relative_to(REPO)),
        "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **window_metrics(snapshot),
    }


def load_history() -> list[dict[str, Any]]:
    if not HISTORY.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def append_history(record: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def status_document(history: list[dict[str, Any]]) -> dict[str, Any]:
    judgement = judge(history)
    return {
        "artifact": "ECONOMIC-001_COST_DRIFT_STATUS",
        "gate": "ECONOMIC-001 (defect ECO-1: the cost premises were measured once)",
        "generated_at_utc": _utc(),
        "history": str(HISTORY.relative_to(REPO)),
        "raw_windows": str(RAW_DIR.relative_to(REPO)),
        "declared_rule": {
            "modelled_round_trip_spread_bps": MODELLED_SPREAD_BPS,
            "modelled_impact_bps": MODELLED_IMPACT_BPS,
            "boundary_multiple": BOUNDARY_MULTIPLE,
            "account_size_usdt": ACCOUNT_USDT,
            "minimum_windows_for_a_stable_verdict": MIN_WINDOWS,
            "verdicts": list(VERDICTS),
        },
        "verdict": judgement["verdict"],
        "provisional": judgement["provisional"],
        "components": judgement["components"],
        "windows": judgement["windows"],
        "reading": judgement["why"],
        "windows_detail": [
            {
                "window_id": row["window_id"],
                "provenance": row.get("provenance", "cost_drift_monitor"),
                "collected_at_utc": row["collected_at_utc"],
                "pooled_median_spread_bps": row["pooled_median_spread_bps"],
                "worst_spread_bps": row["worst_spread_bps"],
                "worst_walk_bps_at_account_size": row["worst_walk_bps_at_account_size"],
                "depth_covers_account_size": row["depth_covers_account_size"],
                "raw_sha256": row["raw_sha256"],
                "raw_path": row["raw_path"],
                "window_complete": row["window_complete"],
            }
            for row in history
        ],
        "stop_rule": (
            "stop collecting when the declared budget of windows is reached, when the venue or the "
            "public endpoint becomes unavailable, or on the first window whose verdict is "
            "DRIFT_WIDER_THAN_MODELLED — a drift that fires ST-6 invalidates the recommended cost "
            "profile and is a result, not a failure"
        ),
        "next_action_when_provisional": (
            "collect one further window at a different time of day; nothing else is licensed here"
        ),
        "orders_sent": sum(row["orders_sent"] for row in history),
        "credentials_used": sum(row["credentials_used"] for row in history),
        "false_success": 0,
        "does_not_license": [
            "a campaign, a hypothesis or a strategy",
            "paper or live trading, or any deployment of capital",
            "any claim that an edge, a profit or a production capability exists",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--spacing", type=float, default=SPACING_S)
    parser.add_argument("--depth-limit", type=int, default=DEPTH_LIMIT)
    parser.add_argument("--judge-only", action="store_true", help="re-judge without collecting")
    parser.add_argument("--no-raw", action="store_true", help="do not keep the raw window bytes")
    parser.add_argument(
        "--import-window",
        default=None,
        help="adopt an already-collected snapshot into the history, re-deriving its metrics",
    )
    parser.add_argument(
        "--provenance",
        default="external snapshot imported by the operator",
        help="where an imported window came from",
    )
    args = parser.parse_args(argv)

    if args.import_window:
        path = Path(args.import_window)
        if not path.is_absolute():
            path = REPO / path
        record = import_window(path, args.provenance)
        if any(row["window_id"] == record["window_id"] for row in load_history()):
            print(f"window {record['window_id']} is already in the history; nothing appended")
        else:
            append_history(record)
            print(
                f"imported {record['window_id']} from {record['raw_path']}: pooled median spread "
                f"{record['pooled_median_spread_bps']} bps"
            )

    if not args.judge_only and not args.import_window:
        record = collect_window(args.rounds, args.spacing, args.depth_limit, not args.no_raw)
        append_history(record)
        print(
            f"window {record['window_id']}: pooled median spread "
            f"{record['pooled_median_spread_bps']} bps, worst {record['worst_spread_bps']} bps, "
            f"walk {record['worst_walk_bps_at_account_size']} bps, complete "
            f"{record['window_complete']}"
        )

    history = load_history()
    status = status_document(history)
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(
        json.dumps(status, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"{status['verdict']} ({'provisional' if status['provisional'] else 'stable'}) over "
        f"{status['windows']} window(s) — components {status['components']}"
    )
    print(f"written -> {HISTORY.relative_to(REPO)}, {STATUS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
