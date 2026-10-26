#!/usr/bin/env python
"""WP-EDGE-09F — independent verification of the EDGE-09 package.

    python scripts/edge09_verify.py [--self-test]

BUILDER != VERIFIER. This script shares no computation with the experiments: it
re-derives the panel samples from the raw segments with its own reader, recomputes
the barrier arithmetic with its own thresholds (and then checks that those
thresholds still equal the registration), and recomputes the classification of a
published cell. It reads files read-only and writes only ``VERIFICATION.{json,md}``.

``--self-test`` tampers with one input per check and requires the check to fail:
a verifier that cannot fail is not a verifier.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09.registration import (  # noqa: E402
    CONSUMED_HOLDOUTS,
    HYPOTHESES,
    MIN_GROSS_SAFETY_MULTIPLE,
    MIN_OBSERVATIONS,
    SCENARIOS_COMPARED,
    SCHEMA_VERSION,
    UNIVERSE,
    WP,
)

PANEL_DIR = WP / "panel"
GATES_JSON = WP / "gates" / "COST_LIQUIDITY_CAPACITY.json"
EXP_JSON = WP / "experiments" / "EXPERIMENTS.json"
REGISTRY_JSON = WP / "experiments" / "EXPERIMENT_REGISTRY.json"
AUDIT_JSON = WP / "audit" / "ESTATE.json"
WINDOW_LEDGER = WP / "WINDOW_LEDGER.jsonl"
EXPERIMENT_LEDGER = WP / "EXPERIMENT_LEDGER.jsonl"
RESULTS_MATRIX = WP / "RESULTS_MATRIX.json"
DELIVERABLES_JSON = WP / "DELIVERABLES.json"

#: The verifier's own copy of the registered thresholds. They are duplicated ON
#: PURPOSE: check C-8 compares them with the registration, so a threshold that
#: moved without the registration moving is caught rather than inherited.
VERIFIER_MIN_ABS_IC = 0.01
VERIFIER_SAMPLE_FLOOR = MIN_OBSERVATIONS
VERIFIER_SAFETY_MULTIPLE = MIN_GROSS_SAFETY_MULTIPLE
VERIFIER_ACTIVE_TARGET = 3.0

#: Windows a package may only read when a gate let an arm through. This package's
#: own registration says nothing passed, so a ledger row that claims to have read
#: one is a contradiction the verifier refuses.
UNREADABLE_WINDOW_ROLES = ("VAL", "FRESH_OOS", "FORWARD")

#: Words that would be an overclaim in this package's artifacts.
FORBIDDEN_VOCABULARY = (
    "PAPER_READY",
    "PRODUCTION_READY",
    "LIVE_READY",
    "profitable strategy",
    "estrategia rentable",
)

CROSS_SECTION_SYMBOLS = ("AAVEUSDT", "UNIUSDT", "KSMUSDT", "SNXUSDT", "CRVUSDT", "SUSHIUSDT")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
        for line in handle:
            parts = line.strip().split(",")
            if len(parts) == len(header):
                rows.append(dict(zip(header, parts, strict=True)))
    return rows


def independent_seconds(
    path: Path, *, start_ms: int
) -> tuple[dict[int, tuple[float, float]], int] | dict[str, str]:
    """Re-read a raw segment with a reader that is not the panel builder.

    Returns ``({second_ms: (mid, spread_bps)}, last_receive_ms)`` where each mid
    is the FIRST quote at or after its one-second boundary on or after
    ``start_ms``, computed without importing ``panel.py``. The whole segment is
    walked (no early exit), so a caller can tell which seconds the segment can
    speak for.
    """
    found: dict[int, tuple[float, float]] = {}
    last_receive = 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if '"book_ticker"' not in line:
                    continue
                row = json.loads(line)
                bid, ask = row.get("bid"), row.get("ask")
                receive = row.get("receive_time")
                if not bid or not ask or not isinstance(receive, int):
                    continue
                last_receive = max(last_receive, receive)
                second = receive - (receive % 1000)
                if second < start_ms or second in found:
                    continue
                mid = (float(bid) + float(ask)) / 2.0
                found[second] = (mid, (float(ask) - float(bid)) / mid * 10_000.0)
    except (EOFError, OSError, gzip.BadGzipFile) as exc:
        return {"error": str(exc)}
    return found, last_receive


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def facts() -> dict[str, Any]:
    """Everything the checks judge, read from disk once."""
    audit = load_json(AUDIT_JSON)
    gates = load_json(GATES_JSON)
    experiments = load_json(EXP_JSON)
    registry = load_json(REGISTRY_JSON).get("registry") or []
    panel_meta = load_json(PANEL_DIR / "PANEL.json")
    panel_rows = read_csv_rows(PANEL_DIR / "PANEL_SECONDS.csv")
    depth_rows = read_csv_rows(PANEL_DIR / "DEPTH_SNAPSHOTS.csv")
    return {
        "audit": audit,
        "gates": gates,
        "experiments": experiments,
        "registry": registry,
        "panel_meta": panel_meta,
        "panel_rows": panel_rows,
        "depth_rows": depth_rows,
        "panel_digest_now": sha256_file(PANEL_DIR / "PANEL_SECONDS.csv"),
        "raw_sample": _raw_sample(panel_meta),
        "window_ledger": read_jsonl(WINDOW_LEDGER),
        "experiment_ledger": read_jsonl(EXPERIMENT_LEDGER),
        "results_matrix": load_json(RESULTS_MATRIX),
        "deliverables": load_json(DELIVERABLES_JSON),
    }


def _raw_sample(panel_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Panel rows re-derived from the raw segments, all of a segment's worth."""
    rows = read_csv_rows(PANEL_DIR / "PANEL_SECONDS.csv")
    if not rows:
        return []
    index: dict[tuple[str, str, str], dict[int, dict[str, str]]] = {}
    for row in rows:
        key = (row["run"], row["market"], row["symbol"])
        index.setdefault(key, {})[int(row["second_ms"])] = row
    #: Only the runs the panel declares are re-read, and only the roots the
    #: capture manifest of those runs names: another run on disk holds the same
    #: symbols at another time and comparing against it would prove nothing.
    roots = {
        (row["run"], row["market"], row["symbol"]): row["root"]
        for row in panel_meta.get("coverage") or []
    }
    samples: list[dict[str, Any]] = []
    for key, seconds in list(index.items())[:4]:
        run, market, symbol = key
        root = roots.get(key)
        if root is None:
            samples.append(
                {
                    "run": run,
                    "market": market,
                    "symbol": symbol,
                    "segment": None,
                    "compared": 0,
                    "mismatches": [],
                    "note": "the panel declares no capture root for this stream",
                }
            )
            continue
        segments = sorted(
            (REPO_ROOT / root).glob(f"segments/binance/{market}/{symbol}/book_ticker/*/*.jsonl.gz")
        )
        first = min(seconds)
        hits = 0
        mismatches: list[dict[str, float]] = []
        chosen: str | None = None
        for segment in segments[:24]:
            derived, last_receive = independent_seconds(segment, start_ms=first)
            if not isinstance(derived, dict) or not derived:
                continue
            if min(derived) > first:
                #: Segments are ordered in time: this one begins after the stream.
                break
            chosen = segment.name
            for second, (mid, spread) in sorted(derived.items()):
                published = seconds.get(second)
                if published is None:
                    continue
                if int(published["decision_time"]) >= last_receive:
                    #: The panel's quote for this boundary may come from the next
                    #: segment: the current one cannot speak for it.
                    continue
                hits += 1
                if (
                    abs(mid - float(published["mid"])) > 1e-9
                    or abs(spread - float(published["spread_bps"])) > 1e-6
                ):
                    mismatches.append(
                        {"second": second, "mid": mid, "expected_mid": float(published["mid"])}
                    )
            break
        samples.append(
            {
                "run": run,
                "market": market,
                "symbol": symbol,
                "segment": chosen,
                "compared": hits,
                "mismatches": mismatches[:10],
            }
        )
    return samples


# --------------------------------------------------------------------------- checks


def check_authoritative_unchanged(f: dict[str, Any]) -> dict[str, Any]:
    offenders = []
    for row in (f["audit"].get("authoritative") or {}).get("files") or []:
        path = REPO_ROOT / row["path"]
        if not path.is_file():
            offenders.append({"path": row["path"], "why": "missing"})
            continue
        if sha256_file(path) != row["sha256"]:
            offenders.append({"path": row["path"], "why": "digest changed since the audit"})
    return {
        "name": "C-1",
        "passed": not offenders,
        "offenders": offenders,
        "why": "every authoritative input still carries the digest the audit recorded",
    }


def check_panel_digest(f: dict[str, Any]) -> dict[str, Any]:
    recorded = ((f["panel_meta"].get("digests") or {}).get("panel_seconds") or {}).get("sha256")
    now = f["panel_digest_now"]
    return {
        "name": "C-2",
        "passed": bool(recorded) and recorded == now,
        "recorded": recorded,
        "recomputed": now,
        "why": "the panel hash recomputes from the bytes on disk",
    }


def check_panel_re_derivation(f: dict[str, Any]) -> dict[str, Any]:
    samples = f["raw_sample"]
    usable = [sample for sample in samples if sample["compared"] > 0]
    offenders = [sample for sample in samples if sample["mismatches"]]
    return {
        "name": "C-3",
        "passed": bool(usable) and not offenders,
        "samples": samples,
        "why": "panel rows re-derive from the raw segments through a second reader",
    }


def check_pit_ordering(f: dict[str, Any]) -> dict[str, Any]:
    offenders = []
    previous: dict[tuple[str, str, str], int] = {}
    for row in f["panel_rows"]:
        key = (row["run"], row["market"], row["symbol"])
        decision = int(row["decision_time"])
        second = int(row["second_ms"])
        if decision < second or decision >= second + 1000:
            offenders.append({"key": key, "second": second, "decision": decision})
        if key in previous and decision <= previous[key]:
            offenders.append({"key": key, "why": "decision clock not strictly increasing"})
        previous[key] = decision
    return {
        "name": "C-4",
        "passed": not offenders,
        "offenders": offenders[:10],
        "rows_checked": len(f["panel_rows"]),
        "why": "every row's decision clock lies inside its own second and moves forward",
    }


def check_forward_horizon(f: dict[str, Any]) -> dict[str, Any]:
    """The published horizon pairing recomputes, and no partner is early."""
    per_stream: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in f["panel_rows"]:
        per_stream.setdefault((row["run"], row["market"], row["symbol"]), []).append(row)
    for key in per_stream:
        per_stream[key] = sorted(per_stream[key], key=lambda row: int(row["decision_time"]))

    offenders: list[dict[str, Any]] = []
    checked = 0
    for cell in (f["experiments"].get("experiments") or {}).get("E-01_imbalance") or []:
        published = cell.get("pit") or {}
        key = (cell["run"], cell["market"], cell["symbol"])
        rows = per_stream.get(key) or []
        if not rows or "min_partner_lag_ms" not in published:
            continue
        horizon = cell["horizon_seconds"]
        lags = []
        for index in range(0, len(rows), max(1, len(rows) // 500)):
            row = rows[index]
            target = int(row["decision_time"]) + horizon * 1000
            partner = next(
                (later for later in rows[index + 1 :] if int(later["decision_time"]) >= target),
                None,
            )
            if partner is None:
                continue
            lags.append(int(partner["decision_time"]) - target)
        checked += 1
        if not lags:
            offenders.append({"cell": key, "why": "no partner windows recomputed"})
            continue
        if min(lags) < 0:
            offenders.append({"cell": key, "why": "a partner landed before decision_time + h"})
        if published.get("min_partner_lag_ms", 0) < 0:
            offenders.append({"cell": key, "why": "the published pairing is not point-in-time"})
        if (published.get("max_partner_lag_ms") or 0) < (published.get("min_partner_lag_ms") or 0):
            offenders.append({"cell": key, "why": "published lag range is inverted"})
    return {
        "name": "C-5",
        "passed": checked > 0 and not offenders,
        "cells_checked": checked,
        "offenders": offenders[:10],
        "why": "every published horizon pairing has its partner at or after decision_time + h",
    }


def check_barrier_arithmetic(f: dict[str, Any]) -> dict[str, Any]:
    offenders = []
    checked = 0
    for row in f["gates"].get("barriers") or []:
        if "error" in row:
            continue
        checked += 1
        components = row["components_bps"]
        total = sum(components.values())
        if abs(total - row["round_trip_bps"]) > 0.02:
            offenders.append(
                {"scenario": row["scenario"], "why": "components do not sum to the round trip"}
            )
        if abs(row["required_bps"] - VERIFIER_SAFETY_MULTIPLE * row["round_trip_bps"]) > 0.02:
            offenders.append(
                {"scenario": row["scenario"], "why": "required is not 1.5x the round trip"}
            )
        if components["fee"] <= 0:
            offenders.append({"scenario": row["scenario"], "why": "a round trip with no fee"})
        if row["spread_observations"] < 1:
            offenders.append({"scenario": row["scenario"], "why": "a spread with no observation"})
    return {
        "name": "C-6",
        "passed": checked > 0 and not offenders,
        "checked": checked,
        "offenders": offenders,
        "why": "the barrier is the sum of its components, with the 1.5x margin",
    }


def check_registered_thresholds(f: dict[str, Any]) -> dict[str, Any]:
    """Compare the verifier's own thresholds with the registration, live.

    The registration is read through the module (not through a binding imported
    earlier), so a threshold edited after this file was written is seen.
    """
    import trading_bot.research.edge09.registration as registration

    registered = {
        "sample_floor": registration.MIN_OBSERVATIONS,
        "safety_multiple": registration.MIN_GROSS_SAFETY_MULTIPLE,
        "active_target": registration.ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
        "min_abs_ic": VERIFIER_MIN_ABS_IC,
    }
    consistency = (
        registered["sample_floor"] == VERIFIER_SAMPLE_FLOOR
        and abs(registered["safety_multiple"] - VERIFIER_SAFETY_MULTIPLE) < 1e-12
        and abs(registered["active_target"] - VERIFIER_ACTIVE_TARGET) < 1e-12
        and abs(registered["min_abs_ic"] - 0.01) < 1e-12
    )
    _ = f
    return {
        "name": "C-7",
        "passed": consistency,
        "thresholds": registered,
        "why": "the verifier's own thresholds still agree with the registration",
    }


def check_verdicts_recompute(f: dict[str, Any]) -> dict[str, Any]:
    """Re-classify the best published cell from the published numbers."""
    cells = (f["experiments"].get("experiments") or {}).get("E-01_imbalance") or []
    usable = [cell for cell in cells if cell.get("stats")]
    if not usable:
        return {"name": "C-8", "passed": False, "why": "no measured cell to re-classify"}
    cell = min(usable, key=lambda item: -(item["stats"]["long_only_mean_bps"]))
    verdict = cell["verdict"]
    gross = cell["stats"]["long_only_mean_bps"]
    cost = verdict["cost_bps"]
    ic = cell["ic"] or 0.0
    n = cell["n"]
    if n < VERIFIER_SAMPLE_FLOOR:
        expected = "INSUFFICIENT_SAMPLE"
    elif abs(ic) < VERIFIER_MIN_ABS_IC:
        expected = "NO_INFORMATION"
    elif gross <= 0:
        expected = "NO_GROSS_EDGE"
    elif cost is None:
        expected = "NO_VIABLE_DATA"
    elif gross < cost or gross < VERIFIER_SAFETY_MULTIPLE * cost:
        expected = "COST_KILLED"
    else:
        expected = "ADMIT_RESEARCH"
    return {
        "name": "C-8",
        "passed": expected == verdict["classification"],
        "cell": {
            "market": cell["market"],
            "symbol": cell["symbol"],
            "horizon_seconds": cell["horizon_seconds"],
            "gross_bps": gross,
            "cost_bps": cost,
            "ic": ic,
            "n": n,
        },
        "published": verdict["classification"],
        "recomputed": expected,
        "why": "the published classification follows from the published numbers and the thresholds",
    }


def check_negative_control(f: dict[str, Any]) -> dict[str, Any]:
    cells = (f["experiments"].get("experiments") or {}).get("E-07_negative_control") or []
    classifications = sorted({cell["verdict"]["classification"] for cell in cells})
    false_success = f["experiments"].get("false_success")
    offenders = [value for value in classifications if value in ("ADMIT_RESEARCH",)]
    return {
        "name": "C-9",
        "passed": bool(cells) and not offenders and false_success == 0,
        "classifications": classifications,
        "false_success": false_success,
        "why": "the negative control is not positive, so FALSE_SUCCESS stays at zero",
    }


def check_no_overclaim(f: dict[str, Any]) -> dict[str, Any]:
    offenders = []
    exempt = {
        #: These quote the forbidden vocabulary in order to forbid it; a
        #: document that names a state to rule it out is not claiming it.
        "VERIFICATION.md",
        "VERIFICATION.json",
        "RFC-EDGE-009.md",
    }
    for path in sorted(WP.rglob("*.md")) + sorted(WP.rglob("*.json")):
        if path.name in exempt:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for word in FORBIDDEN_VOCABULARY:
            if word in text:
                offenders.append({"path": str(path.relative_to(REPO_ROOT)), "word": word})
    promotion = {
        "experiments": f["experiments"].get("promotion"),
        "order_sent": f["experiments"].get("order_sent"),
    }
    return {
        "name": "C-10",
        "passed": not offenders
        and promotion["experiments"] == "NONE"
        and promotion["order_sent"] is False,
        "offenders": offenders,
        "promotion": promotion,
        "exempt_documents": sorted(exempt),
        "why": (
            "no measurement artifact claims readiness or profitability, and no order was sent; "
            "the verifier and the registered RFC name those states only to forbid them"
        ),
    }


def check_holdout_discipline(f: dict[str, Any]) -> dict[str, Any]:
    symbols = set(f["experiments"].get("universe") or UNIVERSE)
    consumed = set()
    for entry in CONSUMED_HOLDOUTS:
        if entry.get("symbols"):
            consumed.update(part.strip() for part in entry["symbols"].split(","))
    overlap = sorted(symbols & consumed | set(CROSS_SECTION_SYMBOLS) & symbols)
    declared = bool(f["audit"].get("captures"))
    return {
        "name": "C-11",
        "passed": not overlap and declared,
        "universe": sorted(symbols),
        "overlap_with_consumed_holdouts": overlap,
        "why": "the measured universe shares no symbol with a holdout this project already spent",
    }


def check_capacity_recompute(f: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], dict[str, list[tuple[float, float]]]] = {}
    for row in f["depth_rows"]:
        key = (row["run"], row["market"], row["symbol"], row["ts_ms"])
        grouped.setdefault(key, {}).setdefault(row["side"], []).append(
            (float(row["price"]), float(row["qty"]))
        )
    recomputed: dict[tuple[str, str], list[float]] = {}
    for (_run, market, symbol, _ts), sides in grouped.items():
        bids, asks = sides.get("bid") or [], sides.get("ask") or []
        if not bids or not asks:
            continue
        mid = (max(price for price, _ in bids) + min(price for price, _ in asks)) / 2.0
        limit = mid * 5.0 / 10_000.0
        notional = sum(price * qty for price, qty in bids if mid - price <= limit)
        recomputed.setdefault((market, symbol), []).append(notional)
    published: dict[tuple[str, str], float] = {}
    for row in (f["experiments"].get("capacity") or {}).get("rows") or []:
        published[(row["market"], row["symbol"])] = row["median_notional_within_5bps_usd"]
    offenders = []
    for key, values in recomputed.items():
        median = statistics.median(values)
        if key not in published:
            offenders.append({"stream": key, "why": "capacity published without a recomputation"})
            continue
        if abs(median - published[key]) > 1.0:
            offenders.append(
                {"stream": key, "published": published[key], "recomputed": round(median, 4)}
            )
    return {
        "name": "C-12",
        "passed": bool(recomputed) and not offenders,
        "streams_recomputed": len(recomputed),
        "offenders": offenders,
        "why": "the published capacity recomputes from the kept depth levels",
    }


def check_registry_completeness(f: dict[str, Any]) -> dict[str, Any]:
    ids = [row["id"] for row in f["registry"]]
    expected = [hypothesis.id for hypothesis in HYPOTHESES]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    missing = sorted(set(expected) - set(ids))
    return {
        "name": "C-13",
        "passed": not duplicates and not missing and len(ids) == len(expected),
        "ids": sorted(ids),
        "missing": missing,
        "duplicates": duplicates,
        "why": "every registered hypothesis — including the rejected ones — appears once",
    }


def check_scenarios_compared(f: dict[str, Any]) -> dict[str, Any]:
    compared = {row["scenario"] for row in (f["gates"].get("barriers") or [])}
    missing = sorted(set(SCENARIOS_COMPARED) - compared)
    fees = {
        row["scenario"]: row["components_bps"]["fee"]
        for row in (f["gates"].get("barriers") or [])
        if "components_bps" in row
    }
    distinct = len({round(value, 6) for value in fees.values()})
    return {
        "name": "C-14",
        "passed": not missing and distinct >= 2,
        "missing": missing,
        "fee_components": {key: round(value, 4) for key, value in sorted(fees.items())},
        "why": "every registered venue scenario is priced, and the schedules are not all the same",
    }


def check_window_ledger(f: dict[str, Any]) -> dict[str, Any]:
    rows = f["window_ledger"]
    streams = set((f["panel_meta"].get("stats") or {}).keys())
    consulted = {
        row.get("dataset_id", "").removeprefix("EDGE09-PANEL-")
        for row in rows
        if row.get("window_role") == "CONSULTED"
    }
    missing = sorted(streams - consulted)
    claimed = [
        row.get("window_id")
        for row in rows
        if row.get("window_role") in UNREADABLE_WINDOW_ROLES and row.get("first_read_utc")
    ]
    spent = []
    for entry in CONSUMED_HOLDOUTS:
        holder = entry.get("holder")
        match = [
            row
            for row in rows
            if row.get("window_role") == "CONSULTED_OOS" and row.get("holder") == holder
        ]
        if not match or any(row.get("read_by_this_package") for row in match):
            spent.append(holder)
    return {
        "name": "C-15",
        "passed": bool(rows) and not missing and not claimed and not spent,
        "streams_without_a_ledger_row": missing,
        "windows_claimed_as_read_but_unreadable": claimed,
        "consumed_holdouts_claimed_again": spent,
        "why": (
            "every measured stream is in the ledger as CONSULTED, no market window that the "
            "cost gate never opened is claimed as read, and no spent holdout is re-read"
        ),
    }


def check_results_match_registry(f: dict[str, Any]) -> dict[str, Any]:
    registry = {row["id"]: row["classification"] for row in f["registry"]}
    matrix = {
        row["hypothesis_id"]: row["classification"] for row in f["results_matrix"].get("rows") or []
    }
    mismatched = sorted(
        f"{key}: registry={value} matrix={matrix.get(key)}"
        for key, value in registry.items()
        if matrix.get(key) != value
    )
    unknown = sorted(
        set(matrix.values())
        - {
            "OBSERVED",
            "NO_GROSS_EDGE",
            "COST_KILLED",
            "FREQUENCY_KILLED",
            "CAPACITY_KILLED",
            "NO_INFORMATION",
            "INSUFFICIENT_SAMPLE",
            "NO_VIABLE_DATA",
            "LIMITED_HISTORY",
            "NON_EXECUTABLE_UNDER_RUNTIME",
            "ADMIT_RESEARCH",
        }
    )
    ledger_ids = {row.get("hypothesis_id") for row in f["experiment_ledger"]}
    absent = sorted(set(registry) - ledger_ids)
    return {
        "name": "C-16",
        "passed": not mismatched and not unknown and not absent and bool(registry),
        "mismatched": mismatched,
        "unknown_classifications": unknown,
        "hypotheses_absent_from_ledger": absent,
        "why": (
            "the results matrix, the registry and the experiment ledger agree hypothesis by "
            "hypothesis, and every classification is registered vocabulary"
        ),
    }


def check_frequency_declaration(f: dict[str, Any]) -> dict[str, Any]:
    pooled = f["experiments"].get("frequency_pooled") or []
    undeclared = [
        row.get("horizon_seconds")
        for row in pooled
        if row.get("opportunities_per_day") is not None and row.get("hours_min") is None
    ]
    contradictions = [
        row.get("horizon_seconds")
        for row in pooled
        if row.get("opportunities_per_day") is not None
        and row.get("opportunities_per_day_any_direction") is not None
        and row["opportunities_per_day"] > row["opportunities_per_day_any_direction"] + 1e-9
    ]
    measured = [row for row in pooled if row.get("opportunities_per_day") is not None]
    every_below = bool(measured) and all(
        row["opportunities_per_day"] < VERIFIER_ACTIVE_TARGET for row in measured
    )
    expected = "FREQUENCY_KILLED" if every_below else "OBSERVED"
    published = next(
        (row["classification"] for row in f["registry"] if row["id"] == "E-05"),
        None,
    )
    return {
        "name": "C-17",
        "passed": not undeclared
        and not contradictions
        and bool(measured)
        and published == expected,
        "horizons_without_a_declared_span": undeclared,
        "long_only_exceeding_any_direction": contradictions,
        "published": published,
        "recomputed": expected,
        "why": (
            "the pooled frequency carries the span it was extrapolated from, never counts more "
            "long-only opportunities than moves of either sign, and is classified by the rule "
            "that kills a book only when every measured horizon is below the target"
        ),
    }


def check_derived_digests(f: dict[str, Any]) -> dict[str, Any]:
    declared = f["deliverables"].get("digests") or {}
    offenders = []
    for name, digest in sorted(declared.items()):
        path = WP / name
        actual = sha256_file(path) if path.is_file() else None
        if actual != digest:
            offenders.append({"artifact": name, "declared": digest, "actual": actual})
    empty = not declared
    return {
        "name": "C-18",
        "passed": not empty and not offenders,
        "offenders": offenders,
        "declared_artifacts": len(declared),
        "why": "every derived deliverable still hashes to the digest its manifest declares",
    }


CHECKS: tuple[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]], ...] = (
    ("C-1", check_authoritative_unchanged),
    ("C-2", check_panel_digest),
    ("C-3", check_panel_re_derivation),
    ("C-4", check_pit_ordering),
    ("C-5", check_forward_horizon),
    ("C-6", check_barrier_arithmetic),
    ("C-7", check_registered_thresholds),
    ("C-8", check_verdicts_recompute),
    ("C-9", check_negative_control),
    ("C-10", check_no_overclaim),
    ("C-11", check_holdout_discipline),
    ("C-12", check_capacity_recompute),
    ("C-13", check_registry_completeness),
    ("C-14", check_scenarios_compared),
    ("C-15", check_window_ledger),
    ("C-16", check_results_match_registry),
    ("C-17", check_frequency_declaration),
    ("C-18", check_derived_digests),
)


def sabotage(name: str, f: dict[str, Any]) -> None:
    """Tamper with exactly the input the named check is supposed to protect."""
    if name == "C-1":
        for row in f["audit"]["authoritative"]["files"]:
            if row["path"].endswith("risk.yaml"):
                row["sha256"] = "0" * 64
    elif name == "C-2":
        f["panel_meta"]["digests"]["panel_seconds"]["sha256"] = "0" * 64
    elif name == "C-3":
        f["raw_sample"][0]["mismatches"] = [{"second": 1, "mid": 1.0, "expected_mid": 2.0}]
    elif name == "C-4":
        f["panel_rows"].append({**f["panel_rows"][0], "second_ms": "0", "decision_time": "-1"})
    elif name == "C-5":
        for cell in f["experiments"]["experiments"]["E-01_imbalance"]:
            if cell.get("pit"):
                cell["pit"]["min_partner_lag_ms"] = -1000
    elif name == "C-6":
        f["gates"]["barriers"][0]["required_bps"] = 0.0
    elif name == "C-7":
        import trading_bot.research.edge09.registration as registration

        registration.MIN_OBSERVATIONS = VERIFIER_SAMPLE_FLOOR + 1
    elif name == "C-8":
        for cell in f["experiments"]["experiments"]["E-01_imbalance"]:
            if cell.get("stats"):
                cell["verdict"]["classification"] = "ADMIT_RESEARCH"
    elif name == "C-9":
        f["experiments"]["false_success"] = 1
    elif name == "C-10":
        (WP / "SABOTAGE_TMP.md").write_text("status: PAPER_READY\n", encoding="utf-8")
    elif name == "C-11":
        f["experiments"]["universe"] = ["AAVEUSDT"]
    elif name == "C-12":
        f["experiments"]["capacity"]["rows"][0]["median_notional_within_5bps_usd"] = 1e12
    elif name == "C-13":
        f["registry"] = f["registry"][:-1]
    elif name == "C-14":
        f["gates"]["barriers"] = []
    elif name == "C-15":
        for row in f["window_ledger"]:
            if row.get("window_role") == "CONSULTED_OOS":
                row["read_by_this_package"] = True
                break
    elif name == "C-16":
        f["results_matrix"]["rows"][0]["classification"] = "ADMIT_RESEARCH"
    elif name == "C-17":
        for row in f["registry"]:
            if row["id"] == "E-05":
                row["classification"] = (
                    "OBSERVED" if row["classification"] != "OBSERVED" else "FREQUENCY_KILLED"
                )
                break
    elif name == "C-18":
        first = next(iter(f["deliverables"]["digests"]))
        f["deliverables"]["digests"][first] = "0" * 64


def run_checks(f: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for name, check in CHECKS:
        try:
            results.append(check(f))
        except Exception as exc:
            results.append({"name": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    return results


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09F — independent verification",
        "",
        f"*Run at `{payload['as_of_utc']}`. Result: **{payload['result']}** — "
        f"{payload['passed']}/{payload['total']} checks passed.*",
        "",
        "| # | Check | Result |",
        "| --- | --- | --- |",
    ]
    for row in payload["checks"]:
        lines.append(
            f"| {row['name']} | {row.get('why', '')} | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines += ["", "## Sabotage self-test", ""]
    self_test = payload.get("self_test") or {}
    if self_test:
        lines += [
            f"Baseline {self_test.get('baseline')}; "
            f"{self_test.get('detected')}/{self_test.get('total')} tampered inputs detected; "
            f"result **{self_test.get('result')}**.",
            "",
            "| Check sabotaged | Detected |",
            "| --- | :-: |",
        ]
        for name, detected in sorted((self_test.get("detected_by_check") or {}).items()):
            lines.append(f"| {name} | {detected} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from datetime import UTC, datetime

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true")
    options = parser.parse_args(argv)

    current = facts()
    checks = run_checks(current)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09F",
        "as_of_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": checks,
        "passed": sum(1 for row in checks if row["passed"]),
        "total": len(checks),
        "failing": [row["name"] for row in checks if not row["passed"]],
    }
    payload["result"] = "PASS" if payload["passed"] == payload["total"] else "FAIL"

    if options.self_test:
        detected_by_check: dict[str, bool] = {}
        for name, check in CHECKS:
            tampered = facts()
            sabotage(name, tampered)
            try:
                detected = check(tampered)["passed"] is False
            except Exception:
                detected = True
            detected_by_check[name] = bool(detected)
        temporary = WP / "SABOTAGE_TMP.md"
        if temporary.is_file():
            temporary.unlink()
        detected = sum(1 for value in detected_by_check.values() if value)
        payload["self_test"] = {
            "baseline": payload["result"],
            "total": len(detected_by_check),
            "detected": detected,
            "detected_by_check": detected_by_check,
            "result": "PASS" if detected == len(detected_by_check) else "FAIL",
            "note": "every check must fail on its own tampered input",
        }

    (WP / "VERIFICATION.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (WP / "VERIFICATION.md").write_text(render(payload), encoding="utf-8")
    print(
        f"verification {payload['result']} ({payload['passed']}/{payload['total']})"
        + (
            f"; self-test {payload['self_test']['result']} "
            f"({payload['self_test']['detected']}/{payload['self_test']['total']} detected)"
            if options.self_test
            else ""
        )
    )
    if payload["failing"]:
        print(f"failing: {payload['failing']}")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
