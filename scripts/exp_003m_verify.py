"""exp_003m_verify — an independent pass over EXP-003M, with its own arithmetic.

    ./.venv/Scripts/python.exe scripts/exp_003m_verify.py            # read-only, no writes
    ./.venv/Scripts/python.exe scripts/exp_003m_verify.py --write    # pre-seal only
    ./.venv/Scripts/python.exe scripts/exp_003m_verify.py --online   # + re-download a sample

This program does not import the fill engine it is checking. It re-derives the limit
prices from EXP-003L's ledger and cost table, recomputes every fill fraction from the raw
tape with a different algorithm (masks and cumulative sums instead of a scan), rebuilds the
economic totals, the bootstrap interval and the verdict, and compares.

``--write`` is refused once ``SEAL.json`` exists: a verifier that can rewrite the tree it
is verifying is not a verifier. Post-seal runs are read-only by construction.

``--online`` re-downloads a deterministic sample of the published archives, checks their
digests against the manifest, and recomputes the sample from the archive rather than from
the reduced tape. That is the check that makes the tape itself falsifiable; without it the
run reports ``NOT_EXECUTED`` rather than claiming the check passed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"

SCHEMA = "AI_BOTS_003M_VERIFICATION_V1"
HOLDOUT_START_MS = int(datetime(2026, 8, 6, tzinfo=UTC).timestamp() * 1000)
HOLDOUT_END_MS = int(datetime(2026, 8, 20, tzinfo=UTC).timestamp() * 1000)
MINUTE_MS = 60_000
STOP_LOSS_PCT = 0.5
TAKE_PROFIT_PCT = 0.75
USER_AGENT = "trading-agentic-portable/exp-003m-verifier"
NEWLINE = chr(10)


def _parse_utc_ms(text: str) -> int:
    """ISO UTC to epoch milliseconds.

    ``strptime`` returns a *naive* datetime, and ``.timestamp()`` on a naive datetime
    silently uses the machine's local timezone. That is how a window declared in UTC ends
    up shifted by two hours and a complete tape looks like it has rows outside its own
    window. The tzinfo is attached before the conversion, deliberately.
    """

    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=8)
def _load_bars(symbol: str) -> dict[str, Any]:
    stamps: list[int] = []
    rows: list[list[float]] = []
    with gzip.open(DATASET / f"{symbol}.1m.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            stamps.append(int(row[0]))
            rows.append([float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
    array = np.asarray(rows, dtype=float)
    return {
        "stamps": stamps,
        "index": {stamp: position for position, stamp in enumerate(stamps)},
        "open": array[:, 0],
        "high": array[:, 1],
        "low": array[:, 2],
        "close": array[:, 3],
        "volume": array[:, 4],
    }


def _load_tape_bytes(
    payload: bytes,
) -> tuple[
    NDArray[np.int64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.int64],
    NDArray[np.bool_],
]:
    """Arrays from a reduced tape: ids, prices, quantities, microsecond stamps, buyer-is-maker."""

    ids: list[int] = []
    prices: list[float] = []
    quantities: list[float] = []
    stamps: list[int] = []
    makers: list[bool] = []
    with gzip.open(io.BytesIO(payload), "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            agg_id, price, qty, ts_ms, buyer_is_maker = json.loads(line)
            ids.append(int(agg_id))
            prices.append(float(price))
            quantities.append(float(qty))
            stamps.append(int(ts_ms) * 1000)
            makers.append(bool(buyer_is_maker))
    return (
        np.asarray(ids, dtype=np.int64),
        np.asarray(prices, dtype=float),
        np.asarray(quantities, dtype=float),
        np.asarray(stamps, dtype=np.int64),
        np.asarray(makers, dtype=bool),
    )


def fill_fraction_numpy(
    *,
    stamps_us: NDArray[np.int64],
    prices: NDArray[np.float64],
    quantities: NDArray[np.float64],
    aggressor_is_seller: NDArray[np.bool_],
    side: str,
    limit: float,
    order_qty: float,
    queue_multiple: float,
    start_us: int,
    end_us: int,
) -> dict[str, Any]:
    """Second implementation of the same mechanism: masks, cumsum, searchsorted."""

    when = (stamps_us >= start_us) & (stamps_us <= end_us)
    who = aggressor_is_seller if side == "buy" else ~aggressor_is_seller
    where = prices <= limit if side == "buy" else prices >= limit
    mask = when & who & where
    if not bool(mask.any()):
        return {
            "fill_fraction": 0.0,
            "fill_us": None,
            "cumulative": 0.0,
            "touched": False,
        }
    selected_qty = quantities[mask]
    selected_ts = stamps_us[mask]
    order = np.argsort(selected_ts, kind="stable")
    cumulative = np.cumsum(selected_qty[order])
    needed = max(queue_multiple, 0.0) * order_qty
    reached = np.nonzero(cumulative > needed)[0]
    total = float(cumulative[-1])
    fraction = min(1.0, max(0.0, (total - needed) / order_qty))
    return {
        "fill_fraction": fraction,
        "fill_us": int(selected_ts[order][reached[0]]) if reached.size else None,
        "cumulative": total,
        "touched": True,
    }


def exit_walk_second_implementation(
    bars: dict[str, Any],
    *,
    side: str,
    entry: float,
    start_index: int,
    end_index: int,
    friction_bps: float,
) -> dict[str, Any]:
    stop = entry * (1.0 - STOP_LOSS_PCT / 100.0) if side == "buy" else entry * (1.0 + STOP_LOSS_PCT / 100.0)
    target = (
        entry * (1.0 + TAKE_PROFIT_PCT / 100.0) if side == "buy" else entry * (1.0 - TAKE_PROFIT_PCT / 100.0)
    )
    last = min(end_index, len(bars["stamps"]) - 1)
    if start_index > last:
        return {"status": "OPEN_AT_END", "exit_reason": None, "price": None, "index": None}
    for index in range(start_index, last + 1):
        high = float(bars["high"][index])
        low = float(bars["low"][index])
        opened = float(bars["open"][index])
        if side == "buy":
            stop_hit = low <= stop
            target_hit = high >= target
            gapped = opened <= stop
        else:
            stop_hit = high >= stop
            target_hit = low <= target
            gapped = opened >= stop
        if stop_hit:
            reference = opened if gapped else stop
            factor = 1.0 + friction_bps / 10_000.0
            price = reference / factor if side == "buy" else reference * factor
            return {"status": "CLOSED", "exit_reason": "stop_loss", "price": price, "index": index}
        if target_hit:
            return {"status": "CLOSED", "exit_reason": "take_profit", "price": target, "index": index}
    return {"status": "OPEN_AT_END", "exit_reason": None, "price": None, "index": None}


def check(name: str, passed: bool, detail: Any, *, executed: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "status": ("PASS" if passed else "FAIL") if executed else "NOT_EXECUTED",
        "detail": detail,
    }


class Context:
    """Everything a check needs, loaded once."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.design = _read_json(out / "design" / "DESIGN.json")
        self.signals = _read_json(out / "analysis" / "SIGNALS.json")
        self.fill_model = _read_json(out / "analysis" / "FILL_MODEL.json")
        self.economics = _read_json(out / "analysis" / "ECONOMICS.json")
        self.decision = _read_json(out / "analysis" / "DECISION.json")
        self.manifest = _read_json(out / "dataset" / "TAPE_MANIFEST.json")
        self.ledger_rows = [
            json.loads(line)["entry"]
            for line in (
                PREDECESSOR / "runs" / "5m" / "mean_reversion" / "real" / "research" / "ledger.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.predecessor_design = _read_json(PREDECESSOR / "design" / "DESIGN.json")


def check_predecessor_seal(ctx: Context) -> dict[str, Any]:
    seal = PREDECESSOR / "SHA256SUMS.txt"
    if not seal.exists():
        return check("predecessor_seal", False, {"error": "EXP-003L SHA256SUMS.txt missing"})
    bad: list[str] = []
    missing: list[str] = []
    listed = 0
    for line in seal.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        target = PREDECESSOR / relative.lstrip("*").strip()
        listed += 1
        if not target.exists():
            missing.append(relative.strip())
        elif _sha256(target) != expected:
            bad.append(relative.strip())
    return check(
        "predecessor_seal",
        listed > 0 and not bad and not missing,
        {"listed": listed, "mismatched": bad, "missing": missing},
    )


def check_signals_reconstruct(ctx: Context) -> dict[str, Any]:
    """Re-derive every limit from the ledger and the frozen cost table, independently."""

    cost = {
        str(row["symbol"]).replace("/", ""): float(row["half_spread_bps"])
        for row in ctx.predecessor_design["cost_table"]
    }
    fills = {row["position_id"]: row for row in ctx.ledger_rows if row.get("kind") == "FILL"}
    worst = 0.0
    problems: list[str] = []
    for signal in ctx.signals["signals"]:
        fill = fills.get(signal["position_id"])
        if fill is None:
            problems.append(f"{signal['position_id']}: no FILL in the ledger")
            continue
        if float(fill["reference_price"]) != float(signal["reference_price"]):
            problems.append(f"{signal['position_id']}: reference price moved")
        half_spread = cost[str(signal["symbol"]).replace("/", "")]
        for offset, published in signal["limit_price"].items():
            improvement = half_spread + float(offset)
            factor = 1.0 + improvement / 10_000.0
            expected = (
                float(signal["reference_price"]) / factor
                if signal["side"] == "buy"
                else float(signal["reference_price"]) * factor
            )
            worst = max(worst, abs(expected - float(published)))
            if abs(expected - float(published)) > 1e-12:
                problems.append(f"{signal['position_id']} offset {offset}: {published} != {expected}")
    return check(
        "signals_reconstruct",
        not problems,
        {"signals": len(ctx.signals["signals"]), "max_abs_gap": worst, "problems": problems[:5]},
    )


def check_tape_integrity(ctx: Context) -> dict[str, Any]:
    problems: list[str] = []
    rows_total = 0
    for key, entry in sorted(ctx.manifest["pairs"].items()):
        target = ctx.out / entry["tape"]["file"]
        if not target.exists():
            problems.append(f"{key}: tape file missing")
            continue
        payload = target.read_bytes()
        if _sha256_bytes(payload) != entry["tape"]["sha256"]:
            problems.append(f"{key}: digest mismatch")
            continue
        ids, prices, quantities, stamps, _ = _load_tape_bytes(payload)
        rows_total += int(ids.size)
        if ids.size != int(entry["tape"]["rows_kept"]):
            problems.append(f"{key}: {ids.size} rows, manifest says {entry['tape']['rows_kept']}")
        if ids.size and not bool((np.diff(ids) > 0).all()):
            problems.append(f"{key}: agg ids not strictly increasing")
        if ids.size and not bool((np.diff(stamps) >= 0).all()):
            problems.append(f"{key}: timestamps not monotonic")
        if ids.size and (bool((prices <= 0).any()) or bool((quantities <= 0).any())):
            problems.append(f"{key}: non-positive price or quantity")
        windows = [
            (_parse_utc_ms(w["start_utc"]) * 1000, _parse_utc_ms(w["end_utc"]) * 1000)
            for w in entry["tape"]["windows_present"]
        ]
        if ids.size:
            inside = all(any(start <= int(stamp) <= end for start, end in windows) for stamp in stamps[:2000])
            if not inside:
                problems.append(f"{key}: rows outside the declared windows")
    return check(
        "tape_integrity",
        not problems,
        {"pairs": len(ctx.manifest["pairs"]), "rows": rows_total, "problems": problems[:5]},
    )


def check_klines_provenance(ctx: Context) -> dict[str, Any]:
    """The frozen bars must be the market's bars, checked against a second endpoint."""

    problems: list[str] = []
    compared = 0
    exact = 0
    for key, entry in sorted(ctx.manifest["pairs"].items()):
        symbol = str(entry["symbol"])
        path = ctx.out / entry["klines"]["file"]
        if not path.exists():
            problems.append(f"{key}: klines file missing")
            continue
        published: dict[int, list[float]] = {}
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                published[int(row[0])] = [float(value) for value in row[1:6]]
        bars = _load_bars(symbol)
        for stamp, values in published.items():
            position = bars["index"].get(stamp)
            if position is None:
                problems.append(f"{key}: bar {stamp} absent from the frozen dataset")
                continue
            compared += 1
            frozen = [
                float(bars["open"][position]),
                float(bars["high"][position]),
                float(bars["low"][position]),
                float(bars["close"][position]),
                float(bars["volume"][position]),
            ]
            if all(abs(a - b) <= 1e-9 for a, b in zip(values, frozen, strict=True)):
                exact += 1
            elif len(problems) < 5:
                problems.append(f"{key}: bar {stamp} differs from the frozen dataset")
    return check(
        "klines_provenance",
        not problems and compared > 0,
        {"bars_compared": compared, "bars_exact": exact, "problems": problems[:5]},
    )


def check_tape_matches_bars(ctx: Context) -> dict[str, Any]:
    """Tape extremes inside each signal's first minute must equal the frozen bar."""

    problems: list[str] = []
    checked = 0
    for signal in ctx.signals["signals"]:
        symbol = str(signal["symbol"]).replace("/", "")
        bars = _load_bars(symbol)
        decision = int(signal["decision_ts_ms"])
        position = bars["index"].get(decision)
        if position is None:
            problems.append(f"{signal['position_id']}: no bar at the decision minute")
            continue
        key = f"{symbol}-{datetime.fromtimestamp(decision / 1000, tz=UTC).strftime('%Y-%m-%d')}"
        entry = ctx.manifest["pairs"].get(key)
        if entry is None:
            problems.append(f"{signal['position_id']}: no tape for {key}")
            continue
        _, prices, _, stamps, _ = _load_tape_bytes(
            (ctx.out / entry["tape"]["file"]).read_bytes()
        )
        minute = (stamps >= decision * 1000) & (stamps < (decision + MINUTE_MS) * 1000)
        if not bool(minute.any()):
            problems.append(f"{signal['position_id']}: tape has no trades in the decision minute")
            continue
        checked += 1
        if abs(float(prices[minute].min()) - float(bars["low"][position])) > 1e-9:
            problems.append(f"{signal['position_id']}: tape low != bar low")
        if abs(float(prices[minute].max()) - float(bars["high"][position])) > 1e-9:
            problems.append(f"{signal['position_id']}: tape high != bar high")
    return check(
        "tape_matches_bars",
        not problems and checked == len(ctx.signals["signals"]),
        {"signals_checked": checked, "problems": problems[:5]},
    )


def check_fills_recompute(ctx: Context) -> dict[str, Any]:
    """Recompute every fill fraction from the tape, with the numpy implementation."""

    problems: list[str] = []
    evaluated = 0
    max_gap = 0.0
    bars_cache: dict[str, dict[str, Any]] = {}
    tape_cache: dict[
        str, tuple[NDArray[np.int64], NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]
    ] = {}
    friction = {
        str(row["symbol"]).replace("/", ""): float(row["price_bps_per_side"])
        for row in ctx.predecessor_design["cost_table"]
    }
    end_ms = int(datetime(2026, 8, 6, tzinfo=UTC).timestamp() * 1000)
    for name, scenario in ctx.design["scenarios"].items():
        schedule = ctx.design["fee_schedules"][scenario["fee_schedule"]]
        rows = ctx.fill_model["per_signal"][name]
        for row in rows:
            signal = ctx.signals["signals"][int(row["index"]) - 1]
            symbol = str(signal["symbol"]).replace("/", "")
            key = f"{symbol}-{datetime.fromtimestamp(int(signal['decision_ts_ms']) / 1000, tz=UTC).strftime('%Y-%m-%d')}"
            if symbol not in bars_cache:
                bars_cache[symbol] = _load_bars(symbol)
            if key not in tape_cache:
                entry = ctx.manifest["pairs"][key]
                _, prices, quantities, stamps, buyer_is_maker = _load_tape_bytes(
                    (ctx.out / entry["tape"]["file"]).read_bytes()
                )
                tape_cache[key] = (stamps, prices, quantities, buyer_is_maker)
            stamps, prices, quantities, buyer_is_maker = tape_cache[key]
            bars = bars_cache[symbol]
            if name == "F0_touch_full":
                index = bars["index"][int(signal["decision_ts_ms"])]
                horizon = min(index + int(scenario["horizon_minutes"]), len(bars["stamps"]) - 1)
                limit = float(row["limit_price"])
                if signal["side"] == "buy":
                    touched = bool((bars["low"][index : horizon + 1] <= limit).any())
                else:
                    touched = bool((bars["high"][index : horizon + 1] >= limit).any())
                expected_fraction = 1.0 if touched else 0.0
                if expected_fraction != float(row["fill_fraction"]):
                    problems.append(f"{name} {row['position_id']}: touch/fill disagreement")
                evaluated += 1
                continue
            recomputed = fill_fraction_numpy(
                stamps_us=stamps,
                prices=prices,
                quantities=quantities,
                aggressor_is_seller=buyer_is_maker,
                side=str(signal["side"]),
                limit=float(row["limit_price"]),
                order_qty=float(row["order_qty"]),
                queue_multiple=float(scenario["queue_multiple"]),
                start_us=(int(signal["decision_ts_ms"]) + int(scenario["latency_ms"])) * 1000,
                end_us=(int(signal["decision_ts_ms"]) + int(scenario["latency_ms"])) * 1000
                + int(scenario["horizon_minutes"]) * 60 * 1_000_000,
            )
            gap = abs(recomputed["fill_fraction"] - float(row["fill_fraction"]))
            max_gap = max(max_gap, gap)
            evaluated += 1
            if gap > 1e-9:
                problems.append(
                    f"{name} {row['position_id']}: {recomputed['fill_fraction']} != {row['fill_fraction']}"
                )
                continue
            if recomputed["fill_us"] is not None and row["seconds_to_fill"] is None:
                problems.append(f"{name} {row['position_id']}: fill time missing")
            if recomputed["fill_us"] is not None:
                if int(recomputed["fill_us"]) // 1000 != int(row["fill_ts_ms"]):
                    problems.append(f"{name} {row['position_id']}: fill instant differs")
                latency_us = int(scenario["latency_ms"]) * 1000
                if int(recomputed["fill_us"]) < int(signal["decision_ts_ms"]) * 1000 + latency_us:
                    problems.append(f"{name} {row['position_id']}: filled before the order arrived")
            if row["fill_fraction"] <= 0:
                #: A miss has no exit to adjudicate; its net must be zero by construction.
                if abs(float(row["net_usdt"])) > 1e-12:
                    problems.append(f"{name} {row['position_id']}: a miss carries PnL")
                continue
            exit_start = int(bars["index"][int(row["fill_ts_ms"]) // MINUTE_MS * MINUTE_MS]) + 1
            walk = exit_walk_second_implementation(
                bars,
                side=str(signal["side"]),
                entry=float(row["limit_price"]),
                start_index=exit_start,
                end_index=int(np.searchsorted(bars["stamps"], end_ms)) - 1,
                friction_bps=friction[symbol],
            )
            if walk["exit_reason"] != row["exit_reason"]:
                problems.append(
                    f"{name} {row['position_id']}: exit {walk['exit_reason']} != {row['exit_reason']}"
                )
            elif (
                walk["price"] is not None
                and row["exit_price"] is not None
                and abs(float(walk["price"]) - float(row["exit_price"])) > 1e-9
            ):
                problems.append(f"{name} {row['position_id']}: exit price differs")
            # Fees and net, recomputed from the second implementation's prices.
            fraction = float(row["fill_fraction"])
            notional = float(signal["notional_usdt"])
            maker_bps = float(schedule["maker_bps"])
            taker_bps = float(schedule["taker_bps"])
            if fraction <= 0:
                expected_net = 0.0
            elif walk["price"] is None:
                #: open at the end: entry commission only, no invented exit
                expected_net = -fraction * notional * maker_bps / 10_000.0
            else:
                quantity = notional / float(row["limit_price"])
                gross = (
                    (float(walk["price"]) - float(row["limit_price"])) * quantity
                    if signal["side"] == "buy"
                    else (float(row["limit_price"]) - float(walk["price"])) * quantity
                )
                exit_bps = maker_bps if walk["exit_reason"] == "take_profit" else taker_bps
                expected_net = (
                    fraction * gross
                    - fraction * notional * maker_bps / 10_000.0
                    - fraction * notional * exit_bps / 10_000.0
                )
            if abs(expected_net - float(row["net_usdt"])) > 1e-7:
                problems.append(
                    f"{name} {row['position_id']}: net {expected_net:.8f} != {row['net_usdt']}"
                )
    return check(
        "fills_recompute",
        not problems,
        {"evaluations": evaluated, "max_fill_gap": max_gap, "problems": problems[:5]},
    )


def check_economics_recompute(ctx: Context) -> dict[str, Any]:
    """Rebuild totals, the block bootstrap and the interval without the producer's code."""

    problems: list[str] = []
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    for name, rows in ctx.fill_model["per_signal"].items():
        published = ctx.economics["economics"][name]
        total = sum(float(row["net_usdt"]) for row in rows)
        if abs(round(total, 8) - float(published["net_usdt"])) > 1e-8:
            problems.append(f"{name}: total {total} != {published['net_usdt']}")
        if abs(round(total / len(rows), 8) - float(published["net_per_signal_usdt"])) > 1e-8:
            problems.append(f"{name}: net per signal differs")
        blocks: dict[int, list[float]] = {}
        for row in rows:
            day = datetime.fromtimestamp(int(row["decision_ts_ms"]) / 1000, tz=UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ordinal = (day - origin).days
            blocks.setdefault(ordinal // 5, []).append(float(row["net_usdt"]))
        groups = [np.asarray(blocks[key]) for key in sorted(blocks)]
        rng = np.random.default_rng(int(ctx.design["economics"]["bootstrap"]["seed"]))
        means = np.empty(int(ctx.design["economics"]["bootstrap"]["resamples"]))
        size = len(rows)
        for index in range(means.size):
            picks = rng.integers(0, len(groups), size=len(groups))
            sample = np.concatenate([groups[pick] for pick in picks])
            while sample.size < size:
                sample = np.concatenate([sample, groups[int(rng.integers(0, len(groups)))]])
            means[index] = float(sample[:size].mean())
        lower = round(float(np.percentile(means, 2.5)), 8)
        upper = round(float(np.percentile(means, 97.5)), 8)
        published_ci = published["bootstrap_ci95_net_per_signal"]
        if abs(lower - float(published_ci["lower"])) > 1e-8:
            problems.append(f"{name}: CI lower {lower} != {published_ci['lower']}")
        if abs(upper - float(published_ci["upper"])) > 1e-8:
            problems.append(f"{name}: CI upper {upper} != {published_ci['upper']}")
    return check("economics_recompute", not problems, {"problems": problems[:5]})


def check_reproduction(ctx: Context) -> dict[str, Any]:
    target = ctx.design["predecessor"]["reproduction_target"]
    f0 = ctx.economics["economics"]["F0_touch_full"]
    deltas = {
        "fill_rate": abs((f0["fill_rate"] or 0.0) - target["fill_rate"]),
        "net_per_signal_usdt": abs((f0["net_per_signal_usdt"] or 0.0) - target["net_per_signal_usdt"]),
        "net_per_fill_usdt": abs((f0["net_per_fill_usdt"] or 0.0) - target["net_per_fill_usdt"]),
        "gross_per_fill_usdt": abs((f0["gross_per_fill_usdt"] or 0.0) - target["gross_per_fill_usdt"]),
    }
    return check(
        "reproduction_of_003l",
        all(value <= 1e-8 for value in deltas.values()),
        {"deltas": deltas, "tolerance": 1e-8},
    )


def _epoch_values(payload: Any, found: list[int]) -> None:
    """Collect every number that could be an epoch stamp, whatever its nesting.

    Strings are *not* parsed: a declaration such as the holdout's own boundaries names the
    window in ISO text, and treating that as data would make the check fail on the document
    that closes the window. Numbers are what a leaked bar looks like.
    """

    if isinstance(payload, dict):
        for value in payload.values():
            _epoch_values(value, found)
    elif isinstance(payload, list):
        for value in payload:
            _epoch_values(value, found)
    elif (
        isinstance(payload, int | float)
        and not isinstance(payload, bool)
        and 10**12 <= float(payload) < 10**14
    ):
        found.append(int(payload))


def check_holdout_closed(ctx: Context) -> dict[str, Any]:
    """No stored row and no archive URL may cover the holdout."""

    problems: list[str] = []
    scanned = 0

    def inside(ms: int) -> bool:
        return HOLDOUT_START_MS <= ms < HOLDOUT_END_MS

    for path in sorted(ctx.out.rglob("*")):
        if not path.is_file() or "raw" in path.parts:
            continue
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    scanned += 1
                    stamp = int(row[0])
                    ts_ms = stamp // 1000 if stamp > 10**14 else stamp
                    if inside(ts_ms):
                        problems.append(f"{path.name}: row inside the holdout")
                        break
        elif path.suffix in (".json", ".jsonl"):
            scanned += 1
            if path.suffix == ".jsonl":
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    stamps: list[int] = []
                    _epoch_values(json.loads(line), stamps)
                    if any(inside(stamp) for stamp in stamps):
                        problems.append(f"{path.name}: timestamp inside the holdout")
                        break
            else:
                stamps = []
                _epoch_values(_read_json(path), stamps)
                if any(inside(stamp) for stamp in stamps):
                    problems.append(f"{path.name}: timestamp inside the holdout")
    urls = [
        value["url"]
        for value in (entry.get("tape_source", {}) for entry in ctx.manifest["pairs"].values())
        if "url" in value
    ]
    bad_urls = [url for url in urls if any(f"2026-08-{day:02d}" in url for day in range(6, 21))]
    if bad_urls:
        problems.append(f"manifest references the holdout: {bad_urls[:2]}")
    return check(
        "holdout_closed",
        not problems,
        {"files_scanned": scanned, "problems": problems[:5], "holdout": ctx.design["holdout"]},
    )


def check_no_live_trading(ctx: Context) -> dict[str, Any]:
    """Zero live orders, and the runtime still declares paper with live trading off."""

    import yaml

    run_rows = [row for row in ctx.ledger_rows if row.get("kind") == "RUN"]
    live_orders = [row.get("live_orders") for row in run_rows]
    problems: list[str] = []
    if any(value not in (None, False) for value in live_orders):
        problems.append(f"ledger reports live orders: {live_orders}")
    if ctx.design.get("market_data_plan", {}).get("credential_used") is not False:
        problems.append("design does not assert credential_used false")
    if ctx.design.get("market_data_plan", {}).get("live_orders") is not False:
        problems.append("design does not assert live_orders false")
    runtime = yaml.safe_load((REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"))
    block = runtime.get("runtime") or {}
    if bool(block.get("live_trading_enabled")):
        problems.append("config/runtime.yaml has live trading enabled")
    if str(block.get("mode")) != "paper":
        problems.append(f"config/runtime.yaml mode is {block.get('mode')!r}, not 'paper'")
    return check(
        "no_live_trading",
        not problems,
        {"run_rows": len(run_rows), "mode": block.get("mode"), "problems": problems},
    )


def check_config_unchanged(ctx: Context) -> dict[str, Any]:
    """The stop, the target and the fee terms must be the ones the design froze."""

    frozen = (ctx.design.get("runtime_config") or {}).get("files") or {}
    if not frozen:
        return check("config_unchanged", False, {"error": "design carries no config fingerprint"})
    drifted = {
        name: {"frozen": digest, "current": _sha256(REPO / "config" / name)}
        for name, digest in frozen.items()
        if _sha256(REPO / "config" / name) != digest
    }
    return check("config_unchanged", not drifted, {"files": sorted(frozen), "drifted": drifted})


def decide_from_numbers(ctx: Context) -> dict[str, Any]:
    """Recompute the verdict from the gates; never trust the published one."""

    f0 = ctx.economics["economics"]["F0_touch_full"]
    f2 = ctx.economics["economics"]["F2_tape_pessimistic"]
    reproduction = ctx.economics["reproduction"]["matches"]
    pessimistic_ok = bool(
        (f2["net_per_signal_usdt"] or 0.0) > 0
        and (f2["net_per_fill_usdt"] or 0.0) > 0
        and f2["bootstrap_ci95_net_per_signal"]["lower"] > 0
    )
    ceiling_ok = bool((f0["net_per_fill_usdt"] or 0.0) > 0)
    signals = len(ctx.fill_model["per_signal"]["F0_touch_full"])
    if not reproduction:
        verdict = "BLOCKED"
    elif not pessimistic_ok or not ceiling_ok:
        verdict = "REJECT"
    elif signals < 40:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
    return {
        "verdict": verdict,
        "pessimistic_ok": pessimistic_ok,
        "ceiling_ok": ceiling_ok,
        "signals": signals,
        "published": ctx.decision["verdict"],
        "consistent": verdict == ctx.decision["verdict"],
    }


def check_decision_consistency(ctx: Context) -> dict[str, Any]:
    recomputed = decide_from_numbers(ctx)
    return check("decision_consistency", recomputed["consistent"], recomputed)


def check_seal_if_present(ctx: Context) -> dict[str, Any]:
    seal = ctx.out / "SHA256SUMS.txt"
    marker = ctx.out / "SEAL.json"
    if not seal.exists():
        return check("seal", False, {"status": "NOT_SEALED"}, executed=False)
    bad: list[str] = []
    missing: list[str] = []
    listed = 0
    for line in seal.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        target = ctx.out / relative.strip()
        listed += 1
        if not target.exists():
            missing.append(relative.strip())
        elif _sha256(target) != expected:
            bad.append(relative.strip())
    marker_ok = False
    if marker.exists():
        payload = _read_json(marker)
        marker_ok = payload.get("manifest_sha256") == _sha256(seal) and listed == int(
            payload.get("files", -1)
        )
    return check(
        "seal",
        listed > 0 and not bad and not missing and marker_ok,
        {"listed": listed, "mismatched": bad[:5], "missing": missing[:5], "marker_ok": marker_ok},
    )


# --------------------------------------------------------------------------------------
# Negative controls: mutate a copy, re-run the check that is supposed to notice, and
# require it to FAIL. A control that only asserts its own inequality proves nothing.
# --------------------------------------------------------------------------------------


def _copy_experiment(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("raw", "__pycache__", "*.zip"),
    )


def _write_json_file(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + NEWLINE,
        encoding="utf-8",
        newline=NEWLINE,
    )


def _rewrite_fill_model(root: Path, mutate: Callable[[dict[str, Any]], str]) -> str:
    path = root / "analysis" / "FILL_MODEL.json"
    payload = _read_json(path)
    note = mutate(payload)
    _write_json_file(path, payload)
    return note


def _mutate_fill_before_latency(root: Path) -> str:
    def mutate(payload: dict[str, Any]) -> str:
        row = next(
            row for row in payload["per_signal"]["F1_tape_base"] if row["fill_ts_ms"] is not None
        )
        row["fill_ts_ms"] = int(row["decision_ts_ms"]) - 1_000
        return f"{row['position_id']}: fill moved before the order could arrive"

    return _rewrite_fill_model(root, mutate)


def _mutate_queue_ignored(root: Path) -> str:
    def mutate(payload: dict[str, Any]) -> str:
        changed = 0
        for row, zero in zip(
            payload["per_signal"]["F1_tape_base"],
            payload["per_signal"]["F3_tape_no_queue"],
            strict=True,
        ):
            if row["fill_fraction"] != zero["fill_fraction"]:
                row["fill_fraction"] = zero["fill_fraction"]
                changed += 1
        return f"{changed} fills rewritten as if the queue were zero"

    return _rewrite_fill_model(root, mutate)


def _mutate_partial_forced_full(root: Path) -> str:
    def mutate(payload: dict[str, Any]) -> str:
        row = next(
            row
            for row in payload["per_signal"]["F1_tape_base"]
            if 0 < float(row["fill_fraction"]) < 1
        )
        row["fill_fraction"] = 1.0
        return f"{row['position_id']}: partial fill forced to 100 %"

    return _rewrite_fill_model(root, mutate)


def _mutate_tape_byte(root: Path) -> str:
    manifest = _read_json(root / "dataset" / "TAPE_MANIFEST.json")
    key = sorted(manifest["pairs"])[0]
    target = root / manifest["pairs"][key]["tape"]["file"]
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 0xFF
    target.write_bytes(bytes(payload))
    return f"{key}: one byte flipped in the reduced tape"


def _mutate_missing_tape(root: Path) -> str:
    manifest = _read_json(root / "dataset" / "TAPE_MANIFEST.json")
    key = sorted(manifest["pairs"])[0]
    (root / manifest["pairs"][key]["tape"]["file"]).unlink()
    return f"{key}: tape file deleted"


def _mutate_holdout_injection(root: Path) -> str:
    def mutate(payload: dict[str, Any]) -> str:
        row = payload["per_signal"]["F0_touch_full"][0]
        row["decision_ts_ms"] = HOLDOUT_START_MS + 3_600_000
        return "one signal re-stamped inside the holdout window"

    return _rewrite_fill_model(root, mutate)


def _mutate_false_success(root: Path) -> str:
    path = root / "analysis" / "DECISION.json"
    payload = _read_json(path)
    payload["verdict"] = "PROMOTE"
    _write_json_file(path, payload)
    return "verdict replaced by PROMOTE while the economics are negative"


CONTROLS: list[dict[str, Any]] = [
    {
        "name": "fill_before_latency",
        "mutate": _mutate_fill_before_latency,
        "check": check_fills_recompute,
    },
    {"name": "queue_ignored", "mutate": _mutate_queue_ignored, "check": check_fills_recompute},
    {
        "name": "partial_forced_full",
        "mutate": _mutate_partial_forced_full,
        "check": check_fills_recompute,
    },
    {"name": "tape_byte_flip", "mutate": _mutate_tape_byte, "check": check_tape_integrity},
    {"name": "missing_tape", "mutate": _mutate_missing_tape, "check": check_tape_integrity},
    {
        "name": "holdout_injection",
        "mutate": _mutate_holdout_injection,
        "check": check_holdout_closed,
    },
    {
        "name": "false_success",
        "mutate": _mutate_false_success,
        "check": check_decision_consistency,
    },
]


def _control_predecessor_tamper(ctx: Context) -> dict[str, Any]:
    """Point the seal check at a synthetic predecessor, prove it passes, then tamper."""

    global PREDECESSOR
    original = PREDECESSOR
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        (scratch / "a.md").write_text("a" + NEWLINE, encoding="utf-8")
        (scratch / "b.json").write_text("{}" + NEWLINE, encoding="utf-8")
        lines = [f"{_sha256(scratch / name)}  {name}" for name in ("a.md", "b.json")]
        (scratch / "SHA256SUMS.txt").write_text(NEWLINE.join(lines) + NEWLINE, encoding="utf-8")
        try:
            PREDECESSOR = scratch
            before = check_predecessor_seal(ctx)
            (scratch / "a.md").write_text("a" + NEWLINE + "edited" + NEWLINE, encoding="utf-8")
            after = check_predecessor_seal(ctx)
        finally:
            PREDECESSOR = original
    detected = before["status"] == "PASS" and after["status"] == "FAIL"
    return {
        "control": "predecessor_tamper",
        "detected": detected,
        "check": "predecessor_seal",
        "detail": f"clean seal {before['status']}, tampered seal {after['status']}",
    }


def run_controls(ctx: Context) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for control in CONTROLS:
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / "exp"
            _copy_experiment(ctx.out, scratch)
            try:
                note = control["mutate"](scratch)
                outcome = control["check"](Context(scratch))
            except Exception as error:  # a control that throws is a control that failed
                results.append(
                    {
                        "control": control["name"],
                        "detected": False,
                        "check": control["check"].__name__,
                        "detail": f"control raised {error!r}",
                    }
                )
                continue
        results.append(
            {
                "control": control["name"],
                "detected": outcome["status"] == "FAIL",
                "check": outcome["name"],
                "detail": note,
                "observed": outcome["status"],
            }
        )
    results.append(_control_predecessor_tamper(ctx))
    return results


def check_online_sample(ctx: Context, sample: int = 6) -> dict[str, Any]:
    """Re-download a deterministic sample and recompute it from the archive itself."""

    keys = sorted(ctx.manifest["pairs"])
    step = max(1, len(keys) // sample)
    chosen = keys[::step][:sample]
    problems: list[str] = []
    verified = 0
    for key in chosen:
        entry = ctx.manifest["pairs"][key]
        url = entry["tape_source"]["url"]
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
        except Exception as error:
            problems.append(f"{key}: download failed {error}")
            continue
        if _sha256_bytes(payload) != entry["tape_source"]["sha256"]:
            problems.append(f"{key}: archive digest differs from the manifest")
            continue
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            name = archive.namelist()[0]
            with archive.open(name) as raw:
                lines = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                rows = [line.split(",") for line in lines if line.strip()]
        kept = [
            (int(row[0]), float(row[1]), float(row[2]), int(row[5]) // 1000, row[6].strip().lower() == "true")
            for row in rows
            if len(row) >= 7 and row[0][0].isdigit()
        ]
        windows = [
            (_parse_utc_ms(w["start_utc"]), _parse_utc_ms(w["end_utc"]))
            for w in entry["tape"]["windows_present"]
        ]
        expected = sorted(
            (agg_id, price, qty, ts_ms, maker)
            for agg_id, price, qty, ts_ms, maker in kept
            if any(start <= ts_ms <= end for start, end in windows)
        )
        stored: list[tuple[int, float, float, int, bool]] = []
        with gzip.open(ctx.out / entry["tape"]["file"], "rt", encoding="utf-8") as handle:
            for line in handle:
                agg_id, price, qty, ts_ms, maker = json.loads(line)
                stored.append((int(agg_id), float(price), float(qty), int(ts_ms), bool(maker)))
        if len(stored) != len(expected):
            problems.append(f"{key}: {len(stored)} stored rows vs {len(expected)} from the archive")
            continue
        if sorted(stored) != expected:
            problems.append(f"{key}: stored rows differ from the archive")
            continue
        verified += 1
    return check(
        "online_sample",
        not problems and verified == len(chosen),
        {"sample": chosen, "verified": verified, "problems": problems[:5]},
    )


CHECKS: list[Callable[[Context], dict[str, Any]]] = [
    check_predecessor_seal,
    check_signals_reconstruct,
    check_tape_integrity,
    check_klines_provenance,
    check_tape_matches_bars,
    check_fills_recompute,
    check_economics_recompute,
    check_reproduction,
    check_holdout_closed,
    check_no_live_trading,
    check_config_unchanged,
    check_decision_consistency,
    check_seal_if_present,
]


def run(out: Path = OUT, *, online: bool = False) -> dict[str, Any]:
    ctx = Context(out)
    results = [function(ctx) for function in CHECKS]
    if online:
        results.append(check_online_sample(ctx))
    else:
        results.append(
            check(
                "online_sample",
                False,
                {"detail": "run with --online to re-download a sample of the archives"},
                executed=False,
            )
        )
    controls = run_controls(ctx)
    failed = [result["name"] for result in results if result["status"] == "FAIL"]
    not_executed = [result["name"] for result in results if result["status"] == "NOT_EXECUTED"]
    summary = {
        "checks": len(results),
        "passed": sum(1 for result in results if result["status"] == "PASS"),
        "failed": len(failed),
        "not_executed": len(not_executed),
        "failed_names": failed,
        "not_executed_names": not_executed,
        "negative_controls": len(controls),
        "negative_controls_detected": sum(1 for control in controls if control["detected"]),
        "false_success": 0 if not failed else 1,
    }
    return {
        "schema_version": SCHEMA,
        "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
        "independent_verifier": "PROGRAM_NOT_PERSON",
        "online_sample": online,
        "checks": results,
        "negative_controls": controls,
        "summary": summary,
        "verdict_recomputed": decide_from_numbers(ctx),
        "notes": [
            "this verifier shares no fill code with the producer: fills are recomputed with masks and cumsum",
            "a program checking a program is independent code, not an independent party",
            "the queue position remains unobservable; no check here can turn an estimate into an observed fill",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--write", action="store_true", help="write analysis/VERIFICATION.json")
    parser.add_argument("--online", action="store_true", help="re-download a sample of archives")
    args = parser.parse_args(argv)
    out = Path(args.out)
    if args.write and (out / "SEAL.json").exists():
        print(
            "[003m-verify] REFUSED — the experiment is sealed; a verifier may not rewrite it",
            file=sys.stderr,
        )
        return 2
    payload = run(out, online=args.online)
    summary = payload["summary"]
    print(
        f"[003m-verify] {summary['passed']}/{summary['checks']} PASS, "
        f"{summary['failed']} FAIL, {summary['not_executed']} NOT_EXECUTED; "
        f"controls {summary['negative_controls_detected']}/{summary['negative_controls']} detected"
    )
    for result in payload["checks"]:
        if result["status"] != "PASS":
            print(f"[003m-verify]   {result['status']}: {result['name']} {result['detail']}")
    if args.write:
        target = out / "analysis" / "VERIFICATION.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"[003m-verify] wrote {target}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
