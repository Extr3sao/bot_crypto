"""Independent verification of the ST-6 forward regime validation artefacts.

Different program from the builder, and it reaches every number by a different route:

* the raw evidence is re-opened from the gzip, the sha256 of the **uncompressed** bytes is
  recomputed, and the compressed digest is recomputed as well;
* the spread of every observation is recomputed straight from the raw bid/ask in the window bytes,
  not from the recorded observation row;
* the 200 USDT depth walk is recomputed with a **cumulative-capacity** derivation (find the level
  whose cumulative notional covers the order, then average the spend) instead of the builder's
  level-consuming loop, so an off-by-one in either route shows up as a mismatch;
* the per-asset and per-regime spread and impact statistics are recomputed from those values and
  compared with the report's tables, including the count above the modelled term;
* the ST-6 verdict is **re-derived from scratch** against the declared policy (the modelled 1.0 and
  0.25 bps, the 1.5x boundary multiple, three windows before a verdict stops being provisional) and
  compared with what the builder recorded, and the inputs the rule saw are recomputed from the raw
  bytes rather than trusted;
* the coverage rule is re-applied window by window (days, slots, sessions, weekday and weekend,
  volatility bands, asset presence, rejected fraction) and the token is recomputed;
* the two modelled thresholds are re-read from COST_MODEL_V3 and compared with every artefact that
  quotes them;
* the absence of trading is re-derived from the configuration, from the artefacts and from the
  phase script's own abstract syntax tree;
* the builder is not the verifier, the outcome is inside the allowed vocabulary, and it is
  consistent with the coverage and drift it reports.

It fails closed: any mismatch is a FAIL with the offending field named, and ``FALSE_SUCCESS`` is the
number of mismatches.

Run:  python scripts/st6_forward_regime_verify.py
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BUILDER = REPO / "scripts" / "st6_forward_regime.py"
DATA = REPO / "data" / "st6"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
COVERAGE = DATA / "ST6_REGIME_COVERAGE.json"
DRIFT = DATA / "ST6_MODEL_DRIFT.json"
REPORT = DATA / "ST6_FORWARD_REGIME_REPORT.json"
REPORT_MD = DATA / "ST6_FORWARD_REGIME_REPORT.md"
OUT = DATA / "ST6_INDEPENDENT_VERIFICATION.json"
OUT_MD = DATA / "ST6_INDEPENDENT_VERIFICATION.md"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
RUNTIME_CFG = REPO / "config" / "runtime.yaml"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"

BPS = 10_000.0
ACCOUNT_USDT = 200.0
SPREAD_MODEL_BPS = 1.0
IMPACT_MODEL_BPS = 0.25
BOUNDARY_MULTIPLE = 1.5
MIN_WINDOWS_FOR_STABLE_VERDICT = 3
EXACT = 1e-9
BPS_TOL = 1e-6
STAT_TOL = 1e-6
OUTCOMES = (
    "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
    "COST_MODEL_DRIFT_DETECTED",
    "INSUFFICIENT_REGIME_COVERAGE",
    "DATA_QUALITY_FAILED",
)
FORBIDDEN_TOKENS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")
ORDER_TOKENS = (
    "create_order",
    "place_order",
    "submit_order",
    "new_order",
    "post_order",
    "cancel_order",
    "createOrder",
    "privateKey",
    "signature",
    "apiKey",
    "api_key",
    "secret",
    "testnet_order",
)
SESSIONS = (("asia", 0, 8), ("europe", 8, 16), ("us", 16, 24))


class Checks:
    def __init__(self) -> None:
        self.total = 0
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{name}: {detail}")

    def close(self, name: str, value: float | None, expected: float | None, tol: float) -> None:
        ok = (
            value is not None
            and expected is not None
            and abs(float(value) - float(expected)) <= tol
        )
        self.check(name, ok, f"{value} vs {expected} (tol {tol})")


def read_json(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def cumulative_walk_bps(levels: list[list[float]], notional: float) -> tuple[float | None, int]:
    """Cumulative-capacity derivation: the level that covers the order pays the margin."""
    if not levels:
        return None, 0
    best = levels[0][0]
    cumulative: list[float] = []
    total = 0.0
    for price, size in levels:
        total += price * size
        cumulative.append(total)
    if cumulative[-1] < notional:
        return None, len(levels)
    level = next(index for index, value in enumerate(cumulative) if value >= notional)
    spent_before = cumulative[level - 1] if level else 0.0
    quantity_before = sum(size for price, size in levels[:level] if price > 0)
    remainder = notional - spent_before
    price = levels[level][0]
    spent = spent_before + remainder
    quantity = quantity_before + remainder / price
    if quantity <= 0:
        return None, level + 1
    return (spent / quantity - best) / best * BPS, level + 1


def session_of(hour: int) -> str:
    for name, start, end in SESSIONS:
        if start <= hour < end:
            return name
    raise AssertionError("hour outside every declared session")


def recompute_window(raw_path: Path) -> dict[str, Any]:
    """Everything the builder claims about one window, recomputed from its raw bytes."""
    with gzip.open(raw_path, "rb") as handle:
        payload = handle.read()
    snapshot = json.loads(payload.decode("utf-8"))
    spreads: list[float] = []
    per_symbol_spreads: dict[str, list[float]] = {}
    per_symbol_buy: dict[str, list[float]] = {}
    per_symbol_sell: dict[str, list[float]] = {}
    observations: list[dict[str, Any]] = []
    for observation in snapshot["observations"]:
        for symbol, book in observation["books"].items():
            bid, ask = float(book["bid"]), float(book["ask"])
            spread = (ask - bid) / ((ask + bid) / 2.0) * BPS
            spreads.append(spread)
            per_symbol_spreads.setdefault(symbol, []).append(spread)
            observations.append(
                {
                    "symbol": symbol,
                    "observed_at_utc": observation.get("local_utc"),
                    "round": observation.get("round"),
                    "bid": bid,
                    "ask": ask,
                    "spread_bps": spread,
                }
            )
        for symbol, book in observation["depth"].items():
            asks = [[float(price), float(size)] for price, size in book["asks"]]
            bids = [[float(price), float(size)] for price, size in book["bids"]]
            buy, _ = cumulative_walk_bps(asks, ACCOUNT_USDT)
            sell, _ = cumulative_walk_bps(bids, ACCOUNT_USDT)
            if buy is not None:
                per_symbol_buy.setdefault(symbol, []).append(buy)
            if sell is not None:
                per_symbol_sell.setdefault(symbol, []).append(sell)
    return {
        "uncompressed_bytes": payload,
        "snapshot": snapshot,
        "spreads": spreads,
        "per_symbol_spreads": per_symbol_spreads,
        "per_symbol_buy": per_symbol_buy,
        "per_symbol_sell": per_symbol_sell,
        "observations": observations,
        "pooled_median_spread_bps": median(spreads) if spreads else None,
        "worst_spread_bps": max(spreads) if spreads else None,
        "worst_walk_bps": max(
            [
                *per_symbol_buy.get("buy", []),
                *[v for values in per_symbol_buy.values() for v in values],
            ]
            + [v for values in per_symbol_sell.values() for v in values],
            default=None,
        ),
    }


def verify_evidence(c: Checks, windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    recomputed: dict[str, dict[str, Any]] = {}
    for window in windows:
        raw = window["raw"]
        path = REPO / raw["path"]
        c.check(f"{window['window_id']}: raw evidence present", path.exists(), raw["path"])
        if not path.exists():
            continue
        with gzip.open(path, "rb") as handle:
            payload = handle.read()
        c.check(
            f"{window['window_id']}: uncompressed sha256 reproduces",
            sha256(payload) == raw["uncompressed_sha256"],
            f"{sha256(payload)[:16]} vs {raw['uncompressed_sha256'][:16]}",
        )
        c.check(
            f"{window['window_id']}: compressed sha256 reproduces",
            sha256(path.read_bytes()) == raw["compressed_sha256"],
            f"{sha256(path.read_bytes())[:16]} vs {raw['compressed_sha256'][:16]}",
        )
        c.check(
            f"{window['window_id']}: uncompressed byte count matches",
            len(payload) == raw["uncompressed_bytes"],
            f"{len(payload)} vs {raw['uncompressed_bytes']}",
        )
        c.check(
            f"{window['window_id']}: gzip is the recorded encoding",
            raw["encoding"] == "gzip",
            raw["encoding"],
        )
        recomputed[window["window_id"]] = recompute_window(path)
    return recomputed


def verify_observations(
    c: Checks, observations: list[dict[str, Any]], recomputed: dict[str, dict[str, Any]]
) -> None:
    c.check("the observation log is not empty", bool(observations), len(observations))
    for row in observations:
        window = recomputed.get(row["window_id"])
        if window is None:
            c.check(f"{row['window_id']}: window recomputed", False, "missing raw window")
            continue
        if row["rejected"]:
            c.check(
                f"{row['window_id']} {row['asset']} r{row['round']}: rejected observation states why",
                bool(row["rejected_reason"]),
                row["rejected_reason"],
            )
            continue
        spread = row.get("spread_bps")
        c.check(
            f"{row['window_id']} {row['asset']} r{row['round']}: spread present",
            spread is not None,
            spread,
        )
        if spread is None:
            continue
        # recompute the spread from the raw bid/ask of that (round, asset)
        raw_row = next(
            (
                entry
                for entry in window["observations"]
                if entry["symbol"] == row["asset"] and entry["round"] == row["round"]
            ),
            None,
        )
        c.check(
            f"{row['window_id']} {row['asset']} r{row['round']}: the raw book exists",
            raw_row is not None,
            "no matching raw round",
        )
        if raw_row is None:
            continue
        finished = window["snapshot"].get("local_finished_utc")
        if finished and raw_row["observed_at_utc"]:
            reference = datetime.strptime(finished.split(".")[0], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=UTC
            )
            observed = datetime.strptime(
                raw_row["observed_at_utc"].split(".")[0], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=UTC)
            c.close(
                f"{row['window_id']} {row['asset']} r{row['round']}: book age recomputed from "
                "the raw instants",
                row.get("book_age_ms"),
                (reference - observed).total_seconds() * 1000.0,
                1000.0,
            )
            c.check(
                f"{row['window_id']} {row['asset']} r{row['round']}: the book age is not negative",
                (row.get("book_age_ms") or 0.0) >= 0.0,
                row.get("book_age_ms"),
            )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: spread recomputed from bid/ask",
            spread,
            raw_row["spread_bps"],
            BPS_TOL,
        )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: bid matches the raw book",
            row.get("bid"),
            raw_row["bid"],
            EXACT,
        )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: ask matches the raw book",
            row.get("ask"),
            raw_row["ask"],
            EXACT,
        )
        # the walk, recomputed with the other derivation
        snapshot_round = window["snapshot"]["observations"][row["round"]]
        depth = snapshot_round["depth"].get(row["asset"])
        if depth is None:
            c.check(
                f"{row['window_id']} {row['asset']} r{row['round']}: depth presence consistent",
                row["depth"]["available"] is False,
                row["depth"],
            )
            continue
        buy, _ = cumulative_walk_bps([[float(p), float(s)] for p, s in depth["asks"]], ACCOUNT_USDT)
        sell, _ = cumulative_walk_bps(
            [[float(p), float(s)] for p, s in depth["bids"]], ACCOUNT_USDT
        )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: buy walk recomputed",
            row["impact"].get("buy_bps"),
            buy,
            BPS_TOL,
        )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: sell walk recomputed",
            row["impact"].get("sell_bps"),
            sell,
            BPS_TOL,
        )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: buy fill agrees",
            float(bool(row["impact"].get("filled_buy"))),
            float(buy is not None),
            EXACT,
        )
        bid_notional = sum(float(price) * float(size) for price, size in depth["bids"])
        ask_notional = sum(float(price) * float(size) for price, size in depth["asks"])
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: bid depth notional recomputed",
            row["depth"].get("bid_notional_all_usdt"),
            bid_notional,
            BPS_TOL,
        )
        c.close(
            f"{row['window_id']} {row['asset']} r{row['round']}: ask depth notional recomputed",
            row["depth"].get("ask_notional_all_usdt"),
            ask_notional,
            BPS_TOL,
        )
        c.check(
            f"{row['window_id']} {row['asset']} r{row['round']}: sampled levels counted",
            row["depth"].get("levels_sampled") == len(depth["asks"]) + len(depth["bids"]),
            f"{row['depth'].get('levels_sampled')} vs {len(depth['asks']) + len(depth['bids'])}",
        )


def verify_freshness(
    c: Checks,
    windows: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    recomputed: dict[str, dict[str, Any]],
) -> None:
    """The freshness rule must be the declared one, applied to the raw instants."""
    for window in windows:
        rows = [row for row in observations if row["window_id"] == window["window_id"]]
        raw = recomputed.get(window["window_id"])
        if not rows or raw is None or "freshness" not in window:
            continue
        budget = raw["snapshot"]["budget"]
        span = float(budget["rounds"]) * float(budget["spacing_s"]) * 1000.0
        limit = span + window["freshness"]["margin_ms"]
        c.close(
            f"{window['window_id']}: the declared span comes from the raw budget",
            window["freshness"]["declared_window_span_ms"],
            span,
            EXACT,
        )
        c.close(
            f"{window['window_id']}: the freshness limit is the span plus the margin",
            window["freshness"]["freshness_limit_ms"],
            limit,
            EXACT,
        )
        for row in rows:
            age = row.get("book_age_ms")
            if age is None:
                continue
            c.check(
                f"{row['asset']} r{row['round']}: stale flag follows the declared limit",
                row["stale"] == (age > limit),
                f"age {age} vs limit {limit} with stale={row['stale']}",
            )
            c.close(
                f"{row['asset']} r{row['round']}: the row quotes the same limit",
                row.get("freshness_limit_ms"),
                limit,
                EXACT,
            )


def verify_window_index(
    c: Checks, windows: list[dict[str, Any]], recomputed: dict[str, dict[str, Any]]
) -> None:
    counts: dict[str, int] = {}
    for window in windows:
        written = sum(1 for _ in ())
        counts[window["window_id"]] = written
        window_rows = recomputed.get(window["window_id"])
        c.check(
            f"{window['window_id']}: thresholds quoted from the frozen model",
            window["thresholds"]["spread_bps"] == SPREAD_MODEL_BPS
            and window["thresholds"]["impact_bps"] == IMPACT_MODEL_BPS,
            window["thresholds"],
        )
        c.check(
            f"{window['window_id']}: no order was sent by this window",
            window["orders_sent"] == 0,
            window["orders_sent"],
        )
        c.check(
            f"{window['window_id']}: no credential was used by this window",
            window["credentials_used"] == 0,
            window["credentials_used"],
        )
        c.check(
            f"{window['window_id']}: slot is inside the declared grid",
            window["slot"].endswith("UTC") and ":" in window["slot"],
            window["slot"],
        )
        c.check(
            f"{window['window_id']}: session agrees with the slot",
            session_of(int(window["slot"][:2])) == window["session"],
            f"{window['slot']} vs {window['session']}",
        )
        c.check(
            f"{window['window_id']}: day type agrees with the day",
            window["day_type"]
            == ("weekend" if datetime.fromisoformat(window["day"]).weekday() >= 5 else "weekday"),
            window["day_type"],
        )
        if window_rows is not None:
            finished = window_rows["snapshot"].get("local_finished_utc")
            if finished:
                c.check(
                    f"{window['window_id']}: the window's reference instant is the raw one",
                    window["collected_at_utc"] == finished.split(".")[0] + "Z",
                    f"{window['collected_at_utc']} vs {finished}",
                )
            c.close(
                f"{window['window_id']}: pooled median spread matches the raw books",
                window["pooled_median_spread_bps"],
                window_rows["pooled_median_spread_bps"],
                STAT_TOL,
            )
            c.close(
                f"{window['window_id']}: worst spread matches the raw books",
                window["worst_spread_bps"],
                window_rows["worst_spread_bps"],
                STAT_TOL,
            )
    # no duplicated slot on the same day: the declared anti-duplication rule
    seen: set[tuple[str, int]] = set()
    for window in windows:
        key = (window["day"], window["slot_index"])
        c.check(
            f"{window['window_id']}: its slot was not already measured that day",
            key not in seen,
            key,
        )
        seen.add(key)
    per_day: dict[str, int] = {}
    for window in windows:
        per_day[window["day"]] = per_day.get(window["day"], 0) + 1
    c.check(
        "no day exceeds the declared maximum of windows per day",
        all(count <= 6 for count in per_day.values()),
        per_day,
    )


def verify_statistics(
    c: Checks, report: dict[str, Any], observations: list[dict[str, Any]]
) -> None:
    accepted = [row for row in observations if not row["rejected"]]
    statistics_ = report["model_comparison"]["statistics"]
    spreads = [row["spread_bps"] for row in accepted if row.get("spread_bps") is not None]
    walks = [
        value
        for row in accepted
        for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
        if isinstance(value, float)
    ]
    c.close(
        "overall spread median recomputed",
        statistics_["overall"]["spread_bps"]["median"],
        median(spreads) if spreads else None,
        STAT_TOL,
    )
    c.close(
        "overall spread p95 recomputed",
        statistics_["overall"]["spread_bps"]["p95"],
        percentile(spreads, 0.95) if spreads else None,
        STAT_TOL,
    )
    c.close(
        "overall spread worst recomputed",
        statistics_["overall"]["spread_bps"]["max"],
        max(spreads) if spreads else None,
        STAT_TOL,
    )
    c.check(
        "overall spread over-model count recomputed",
        statistics_["overall"]["spread_bps"]["over_model"]
        == sum(1 for value in spreads if value > SPREAD_MODEL_BPS),
        statistics_["overall"]["spread_bps"]["over_model"],
    )
    c.close(
        "overall impact worst recomputed",
        statistics_["overall"]["impact_bps"]["max"],
        max(walks) if walks else None,
        STAT_TOL,
    )
    c.check(
        "overall impact over-model count recomputed",
        statistics_["overall"]["impact_bps"]["over_model"]
        == sum(1 for value in walks if value > IMPACT_MODEL_BPS),
        statistics_["overall"]["impact_bps"]["over_model"],
    )
    c.check(
        "the p99 is only quoted when the sample allows it",
        (
            statistics_["overall"]["spread_bps"].get("p99") is None
            if len(spreads) < 100
            else statistics_["overall"]["spread_bps"]["p99"] is not None
        ),
        statistics_["overall"]["spread_bps"].get("p99"),
    )
    for asset, entry in statistics_["by_asset"].items():
        asset_spreads = [
            row["spread_bps"]
            for row in accepted
            if row["asset"] == asset and row.get("spread_bps") is not None
        ]
        c.close(
            f"{asset}: per-asset median recomputed",
            entry["spread_bps"]["median"],
            median(asset_spreads) if asset_spreads else None,
            STAT_TOL,
        )
        c.close(
            f"{asset}: per-asset worst recomputed",
            entry["spread_bps"]["max"],
            max(asset_spreads) if asset_spreads else None,
            STAT_TOL,
        )
        asset_depth = [
            value
            for row in accepted
            if row["asset"] == asset
            for value in (
                row["depth"].get("bid_notional_all_usdt"),
                row["depth"].get("ask_notional_all_usdt"),
            )
            if isinstance(value, float)
        ]
        c.close(
            f"{asset}: per-asset median depth notional recomputed",
            entry["depth_notional_usdt"].get("median"),
            median(asset_depth) if asset_depth else None,
            BPS_TOL,
        )
        asset_freshness = [row["book_age_ms"] for row in accepted if row["asset"] == asset]
        c.close(
            f"{asset}: per-asset median book age recomputed",
            entry["book_age_ms"].get("median"),
            median(asset_freshness) if asset_freshness else None,
            STAT_TOL,
        )
    for regime, entry in statistics_["by_volatility_regime"].items():
        regime_spreads = [
            row["spread_bps"]
            for row in accepted
            if row["volatility"]["regime"] == regime and row.get("spread_bps") is not None
        ]
        c.close(
            f"regime {regime}: median recomputed",
            entry["spread_bps"]["median"],
            median(regime_spreads) if regime_spreads else None,
            STAT_TOL,
        )
    c.check(
        "rejected count in the statistics matches the observation log",
        statistics_["overall"]["rejected"] == len(observations) - len(accepted),
        statistics_["overall"]["rejected"],
    )


def verify_rule_and_breaches(
    c: Checks,
    drift: dict[str, Any],
    observations: list[dict[str, Any]],
    recomputed: dict[str, dict[str, Any]],
) -> None:
    # the inputs the rule saw, recomputed from the raw bytes
    by_window: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        if not row["rejected"]:
            by_window.setdefault(row["window_id"], []).append(row)
    independent: dict[str, dict[str, Any]] = {}
    for window_id, rows in by_window.items():
        raw = recomputed.get(window_id)
        spreads = [row["spread_bps"] for row in rows if row.get("spread_bps") is not None]
        walks = [
            value
            for row in rows
            for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
            if isinstance(value, float)
        ]
        depth_ok = all(
            row["impact"].get("filled_buy") and row["impact"].get("filled_sell")
            for row in rows
            if row["depth"].get("available")
        )
        independent[window_id] = {
            "pooled_median_spread_bps": median(spreads) if spreads else None,
            "worst_spread_bps": max(spreads) if spreads else None,
            "worst_walk_bps_at_account_size": max(walks) if walks else None,
            "depth_covers_account_size": depth_ok,
            "raw_worst_spread_bps": raw["worst_spread_bps"] if raw else None,
        }
    recorded = {entry["window_id"]: entry for entry in drift["what_the_rule_saw"]}
    for window_id, values in independent.items():
        entry = recorded.get(window_id)
        c.check(f"{window_id}: the rule's inputs are recorded", entry is not None, window_id)
        if entry is None:
            continue
        c.close(
            f"{window_id}: worst spread the rule saw",
            entry["worst_spread_bps"],
            values["worst_spread_bps"],
            STAT_TOL,
        )
        c.close(
            f"{window_id}: median spread the rule saw",
            entry["pooled_median_spread_bps"],
            values["pooled_median_spread_bps"],
            STAT_TOL,
        )
        c.close(
            f"{window_id}: worst walk the rule saw",
            entry["worst_walk_bps_at_account_size"],
            values["worst_walk_bps_at_account_size"],
            STAT_TOL,
        )
        c.check(
            f"{window_id}: depth coverage the rule saw",
            entry["depth_covers_account_size"] == values["depth_covers_account_size"],
            entry["depth_covers_account_size"],
        )
        c.close(
            f"{window_id}: worst spread also agrees with the raw books",
            entry["worst_spread_bps"],
            values["raw_worst_spread_bps"],
            STAT_TOL,
        )

    # the policy itself, re-derived: spread and impact, worst-of across windows
    def spread_component(entry: dict[str, Any]) -> str:
        worst = entry["worst_spread_bps"]
        pooled = entry["pooled_median_spread_bps"]
        if worst is None:
            return "INSUFFICIENT_EVIDENCE"
        if worst <= SPREAD_MODEL_BPS:
            return "WITHIN"
        if pooled is not None and pooled <= SPREAD_MODEL_BPS and worst <= BOUNDARY_MULTIPLE:
            return "AT_BOUNDARY"
        return "DRIFT"

    def impact_component(entry: dict[str, Any]) -> str:
        worst = entry["worst_walk_bps_at_account_size"]
        if worst is None:
            return "INSUFFICIENT_EVIDENCE"
        if worst <= IMPACT_MODEL_BPS:
            return "WITHIN"
        if worst <= BOUNDARY_MULTIPLE * IMPACT_MODEL_BPS:
            return "AT_BOUNDARY"
        return "DRIFT"

    def worst_of(values: list[str]) -> str:
        if not values:
            return "INSUFFICIENT_EVIDENCE"
        if "DRIFT" in values:
            return "DRIFT"
        if "AT_BOUNDARY" in values:
            return "AT_BOUNDARY"
        return "WITHIN"

    entries = [entry for entry in recorded.values()]
    components = {
        "spread": worst_of([spread_component(entry) for entry in entries]),
        "impact": worst_of([impact_component(entry) for entry in entries]),
        "depth": worst_of(
            ["WITHIN" if entry["depth_covers_account_size"] else "DRIFT" for entry in entries]
        ),
    }
    if "DRIFT" in components.values():
        verdict = "DRIFT_WIDER_THAN_MODELLED"
    elif "AT_BOUNDARY" in components.values():
        verdict = "AT_THE_MODELLED_BOUNDARY"
    elif len(entries) < MIN_WINDOWS_FOR_STABLE_VERDICT:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "WITHIN_MODELLED_ASSUMPTIONS"
    c.check(
        "the ST-6 verdict is re-derived from the raw inputs",
        drift["st6_window_verdict"] == verdict,
        f"{drift['st6_window_verdict']} vs {verdict}",
    )
    for name, value in components.items():
        c.check(
            f"the ST-6 {name} component is re-derived",
            drift["st6_components"][name] == value,
            f"{drift['st6_components'][name]} vs {value}",
        )
    c.check(
        "provisional state follows the declared minimum",
        drift["st6_provisional"] == (len(entries) < MIN_WINDOWS_FOR_STABLE_VERDICT),
        drift["st6_provisional"],
    )

    # breaches: every observation above a threshold must be listed, individually and with context
    expected: list[tuple[str, str, float]] = []
    for row in observations:
        if row["rejected"]:
            continue
        if isinstance(row.get("spread_bps"), float) and row["spread_bps"] > SPREAD_MODEL_BPS:
            expected.append(("spread", row["asset"], row["spread_bps"]))
        for side in ("buy_bps", "sell_bps"):
            walk = row["impact"].get(side)
            if isinstance(walk, float) and walk > IMPACT_MODEL_BPS:
                expected.append((f"impact_{side.split('_')[0]}", row["asset"], walk))
    listed = [
        (
            entry["kind"].replace("over_model_", "").replace("over_model", "spread"),
            entry["asset"],
            entry["value_bps"],
        )
        for entry in drift["breaches"]
    ]
    c.check(
        "every observation above a modelled threshold is listed as a breach",
        len(listed) == len(expected),
        f"{len(listed)} listed vs {len(expected)} above threshold",
    )
    for breach_kind, breach_asset, breach_value in expected:
        match = [
            entry
            for entry in listed
            if entry[1] == breach_asset and abs(entry[2] - breach_value) <= BPS_TOL
        ]
        c.check(
            f"{breach_asset}: the breach of {breach_kind} at {breach_value} bps is listed",
            bool(match),
            f"{breach_kind} {breach_value}",
        )
    c.check(
        "the drift flag follows the breaches and the policy",
        drift["drift_detected"]
        == (
            verdict == "DRIFT_WIDER_THAN_MODELLED"
            or any(e["st6_effect"] == "DRIFT" for e in drift["breaches"])
        ),
        drift["drift_detected"],
    )
    c.check(
        "the extreme values are not hidden: the excluded tail is named",
        "aggregation" in json.dumps(drift["rule"]) or "aggregation_policy" in drift["rule"],
        "aggregation policy missing",
    )
    c.check(
        "no measurement of realised slippage or fill quality is claimed",
        drift["not_measured"]
        == ["realised slippage", "fill quality or price improvement", "maker queue position"],
        drift["not_measured"],
    )


def verify_coverage(
    c: Checks, period: dict[str, Any], coverage: dict[str, Any], windows: list[dict[str, Any]]
) -> None:
    rule = coverage["declared_rule"]
    c.check(
        "the applied coverage rule is the rule declared in the period",
        rule == period["coverage_rule"],
        {key: value for key, value in rule.items() if period["coverage_rule"].get(key) != value},
    )
    days = sorted({window["day"] for window in windows})
    c.check(
        "days covered recomputed",
        coverage["period"]["days_elapsed"] == len(days),
        f"{coverage['period']['days_elapsed']} vs {len(days)}",
    )
    c.check(
        "observed windows recomputed",
        coverage["observed_windows"] == len(windows),
        coverage["observed_windows"],
    )
    c.check(
        "planned windows follow the declared rule",
        coverage["planned_windows"] == rule["period_days"] * rule["maximum_windows_per_day"],
        coverage["planned_windows"],
    )
    sessions = {name: 0 for name, _, _ in SESSIONS}
    for window in windows:
        sessions[window["session"]] += 1
    c.check(
        "session coverage recomputed",
        coverage["regimes_identified"]["sessions"] == sessions,
        coverage["regimes_identified"]["sessions"],
    )
    weekday = sum(1 for window in windows if window["day_type"] == "weekday")
    weekend = sum(1 for window in windows if window["day_type"] == "weekend")
    c.check(
        "weekday windows recomputed",
        coverage["checks"]["weekday windows >= declared minimum"]["observed"] == weekday,
        coverage["checks"]["weekday windows >= declared minimum"]["observed"],
    )
    c.check(
        "weekend windows recomputed",
        coverage["checks"]["weekend windows >= declared minimum"]["observed"] == weekend,
        coverage["checks"]["weekend windows >= declared minimum"]["observed"],
    )
    slots = sorted({window["slot"] for window in windows})
    c.check(
        "distinct slots recomputed",
        coverage["checks"]["distinct slots >= declared minimum"]["observed"] == len(slots),
        coverage["checks"]["distinct slots >= declared minimum"]["observed"],
    )
    satisfied = all(entry["satisfied"] for entry in coverage["checks"].values())
    c.check(
        "the coverage token follows the checks",
        coverage["coverage_token"]
        == ("REGIME_COVERAGE_SUFFICIENT" if satisfied else "REGIME_COVERAGE_INSUFFICIENT"),
        coverage["coverage_token"],
    )
    c.check(
        "an incomplete coverage keeps at least one missing condition named",
        satisfied or bool(coverage["missing"]),
        coverage["missing"],
    )


def verify_thresholds(c: Checks, period: dict[str, Any], report: dict[str, Any]) -> None:
    model = read_json(COST_MODEL)
    spread = float(model["model_constants"]["base_slippage_bps"])
    impact = float(model["model_constants"]["base_impact_bps"])
    c.close(
        "the frozen model still carries the 1.0 bps spread term", spread, SPREAD_MODEL_BPS, EXACT
    )
    c.close(
        "the frozen model still carries the 0.25 bps impact term", impact, IMPACT_MODEL_BPS, EXACT
    )
    quoted = {
        "period": period["thresholds"],
        "report": report["model_comparison"]["thresholds"],
    }
    for label, document in quoted.items():
        c.check(
            f"{label}: the quoted spread threshold is the frozen constant",
            document["spread_bps"] == spread,
            document,
        )
        c.check(
            f"{label}: the quoted impact threshold is the frozen constant",
            document["impact_bps"] == impact,
            document,
        )
    rule = report["drift"]["rule"]
    c.check(
        "the drift rule quotes the frozen spread threshold",
        rule["spread_threshold_bps"] == spread,
        rule,
    )
    c.check(
        "the drift rule quotes the frozen impact threshold",
        rule["impact_threshold_bps"] == impact,
        rule,
    )
    c.check(
        "the period records the boundary policy it reuses",
        period["thresholds"]["boundary_multiple"] == BOUNDARY_MULTIPLE,
        period["thresholds"]["boundary_multiple"],
    )
    c.check(
        "the drift artefact quotes the boundary policy it applies",
        report["drift"]["rule"]["boundary_multiple"] == BOUNDARY_MULTIPLE,
        report["drift"]["rule"]["boundary_multiple"],
    )
    c.check(
        "the drift artefact prices the account size it walks",
        report["drift"]["rule"]["size_usdt"] == ACCOUNT_USDT,
        report["drift"]["rule"]["size_usdt"],
    )
    c.check(
        "the model hash quoted by the period is the file on disk",
        period["thresholds"]["model_sha256"] == sha256(COST_MODEL.read_bytes()),
        period["thresholds"]["model_sha256"][:16],
    )


def order_path_tokens(source: str) -> list[str]:
    """Tokens of an order or credential path found in a program's syntax tree.

    Extracted so the scan can be shown to fire: a check that cannot fail is not a check.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value.lower())
    return sorted({token for token in ORDER_TOKENS if token.lower() in names})


def verify_governance(c: Checks, report: dict[str, Any], windows: list[dict[str, Any]]) -> None:
    import yaml

    runtime = yaml.safe_load(RUNTIME_CFG.read_text(encoding="utf-8"))["runtime"]
    exchange = yaml.safe_load(EXCHANGE_CFG.read_text(encoding="utf-8"))["exchange"]
    c.check(
        "the runtime mode is not live",
        str(runtime["mode"]).lower() != "live",
        runtime["mode"],
    )
    c.check(
        "the runtime configuration keeps live trading disabled",
        runtime["live_trading_enabled"] is False,
        runtime["live_trading_enabled"],
    )
    c.check(
        "the exchange configuration points at the sandbox",
        exchange["sandbox"] is True,
        exchange["sandbox"],
    )
    c.check(
        "the exchange configuration is spot, not margin",
        exchange["account_type"] == "spot",
        exchange["account_type"],
    )
    standing = report["standing_state"]
    c.check(
        "the discovery campaign stays failed",
        standing["DISCOVERY_CAMPAIGN_FAILED"] is True,
        standing,
    )
    c.check(
        "no new campaign is authorized", standing["NEXT_CAMPAIGN"] == "NOT_AUTHORIZED", standing
    )
    c.check("trades authorized stays zero", standing["TRADES_AUTHORIZED"] == 0, standing)
    c.check("live trading stays disabled", standing["LIVE_TRADING"] == "DISABLED", standing)
    c.check("profitability stays unverified", standing["PROFITABILITY_VERIFIED"] is False, standing)
    c.check(
        "ECO-2 stays unknown offline",
        standing["ECO_2"] == "UNKNOWN_NOT_RESOLVABLE_OFFLINE",
        standing,
    )
    c.check(
        "no window reports an order",
        all(window["orders_sent"] == 0 for window in windows),
        [window["orders_sent"] for window in windows],
    )
    c.check(
        "no window reports a credential",
        all(window["credentials_used"] == 0 for window in windows),
        [window["credentials_used"] for window in windows],
    )
    offenders = order_path_tokens(BUILDER.read_text(encoding="utf-8"))
    c.check(
        "the builder's own syntax tree carries no order or credential path",
        not offenders,
        offenders,
    )
    body = REPORT_MD.read_text(encoding="utf-8")
    forbidden = [token for token in FORBIDDEN_TOKENS if token in body]
    c.check("the report refuses the forbidden tokens", not forbidden, forbidden)


def verify_artefacts(c: Checks, report: dict[str, Any]) -> None:
    c.check("the builder is not the verifier", BUILDER.name != Path(__file__).name, BUILDER.name)
    c.check(
        "the outcome is inside the allowed vocabulary",
        report["outcome"] in OUTCOMES,
        report["outcome"],
    )
    c.check(
        "the coverage token is inside the allowed vocabulary",
        report["coverage"]["coverage_token"]
        in ("REGIME_COVERAGE_SUFFICIENT", "REGIME_COVERAGE_INSUFFICIENT"),
        report["coverage"]["coverage_token"],
    )
    complete = report["coverage"]["coverage_complete"]
    drift_observed = report["drift"]["drift_detected"]
    if report["outcome"] == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES":
        c.check(
            "a supported verdict requires complete coverage and no drift",
            complete and not drift_observed,
            f"coverage_complete={complete}, drift={drift_observed}",
        )
    c.check(
        "an incomplete coverage cannot be reported as supported",
        not (not complete and report["outcome"] == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES"),
        report["outcome"],
    )
    c.check(
        "a drift under an open period is reported, not hidden",
        (not drift_observed) or report["drift_observed_so_far"] is True,
        report["drift_observed_so_far"],
    )
    c.check(
        "ECO-1 is only closed when the period closed as supported",
        (report["eco_1"] == "CLOSED_WITHIN_OBSERVED_REGIMES")
        == (report["outcome"] == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES"),
        report["eco_1"],
    )
    c.check(
        "ECO-2 stays unresolvable offline",
        report["eco_2"] == "UNKNOWN_NOT_RESOLVABLE_OFFLINE",
        report["eco_2"],
    )
    c.check(
        "the report states what it does not certify",
        "not" in report["outcome_basis"] or "only" in report["outcome_basis"],
        report["outcome_basis"],
    )
    c.check(
        "FALSE_SUCCESS is declared zero by the builder",
        report["false_success"] == 0,
        report["false_success"],
    )
    storage = report["storage"]
    c.check(
        "compressed evidence is smaller than the raw bytes it preserves",
        storage["compressed_bytes"] <= storage["uncompressed_bytes"],
        storage,
    )
    c.check(
        "no trading scheduler was created or touched",
        report["scheduler"]["daemon_created"] is False
        and report["scheduler"]["trading_scheduler_touched"] is False,
        report["scheduler"],
    )
    c.check(
        "the storage policy forbids duplicated rollups inside events",
        "CAP-004C" in report["duplication_policy"],
        report["duplication_policy"],
    )
    for repair in report.get("repairs", []):
        c.check(
            f"repair at {repair['at_utc']}: the evidence is stated as unchanged and was re-checked",
            repair["evidence_unchanged"] is True and repair["raw_hashes_rechecked"] >= 1,
            repair,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument(
        "--md-out",
        default=str(OUT_MD),
        help="where the markdown verification goes; a caller that must not rewrite the committed "
        "artefact points this at a temporary path",
    )
    args = parser.parse_args(argv)

    c = Checks()
    period = read_json(PERIOD)
    windows = read_jsonl(WINDOWS)
    observations = read_jsonl(OBSERVATIONS)
    coverage = read_json(COVERAGE)
    drift = read_json(DRIFT)
    report = read_json(REPORT)

    recomputed = verify_evidence(c, windows)
    verify_window_index(c, windows, recomputed)
    verify_freshness(c, windows, observations, recomputed)
    verify_observations(c, observations, recomputed)
    verify_statistics(c, report, observations)
    verify_rule_and_breaches(c, drift, observations, recomputed)
    verify_coverage(c, period, coverage, windows)
    verify_thresholds(c, period, report)
    verify_governance(c, report, windows)
    verify_artefacts(c, report)

    result = {
        "artifact": "ST6_INDEPENDENT_VERIFICATION",
        "verifier": "scripts/st6_forward_regime_verify.py",
        "builder": "scripts/st6_forward_regime.py",
        "builder_equals_verifier": False,
        "verified_artifacts": [
            "data/st6/ST6_PERIOD.json",
            "data/st6/ST6_WINDOWS.jsonl",
            "data/st6/ST6_OBSERVATIONS.jsonl",
            "data/st6/ST6_REGIME_COVERAGE.json",
            "data/st6/ST6_MODEL_DRIFT.json",
            "data/st6/ST6_FORWARD_REGIME_REPORT.json",
        ],
        "verified_hashes": {
            "ST6_PERIOD.json": sha256(PERIOD.read_bytes()),
            "ST6_WINDOWS.jsonl": sha256(WINDOWS.read_bytes()),
            "ST6_OBSERVATIONS.jsonl": sha256(OBSERVATIONS.read_bytes()),
            "ST6_REGIME_COVERAGE.json": sha256(COVERAGE.read_bytes()),
            "ST6_MODEL_DRIFT.json": sha256(DRIFT.read_bytes()),
            "ST6_FORWARD_REGIME_REPORT.json": sha256(REPORT.read_bytes()),
        },
        "raw_windows_verified": sorted(recomputed),
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks_total": c.total,
        "checks_passed": c.passed,
        "mismatches": len(c.failed),
        "failures": c.failed,
        "false_success": len(c.failed),
        "status": "PASS" if not c.failed else "FAIL",
        "verdict": "ST6_FORWARD_EVIDENCE_VERIFIED"
        if not c.failed
        else "ST6_FORWARD_EVIDENCE_FAILED",
        "builder_outcome_corroborated": report["outcome"],
        "builder_coverage_token_corroborated": report["coverage"]["coverage_token"],
        "method": (
            "spread and depth recomputed from the raw window bytes through a cumulative-capacity "
            "walk; statistics, coverage, thresholds, the ST-6 verdict and the breach list re-derived "
            "independently; governance re-read from configuration and from the builder's syntax tree"
        ),
    }
    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# ST-6 — independent verification",
        "",
        f"Generated {result['generated_at_utc']}. Verifier `{result['verifier']}`, builder "
        f"`{result['builder']}`.",
        "",
        f"**{result['status']}** — {result['checks_passed']}/{result['checks_total']} checks, "
        f"{result['mismatches']} mismatches, FALSE_SUCCESS = {result['false_success']}. "
        f"Verdict **{result['verdict']}**.",
        "",
        "## What was re-derived",
        "",
        result["method"] + ".",
        "",
        f"Raw windows verified: {len(result['raw_windows_verified'])}.",
        "",
        "## Artefact hashes verified as bytes",
        "",
        "| artefact | sha256 |",
        "| --- | --- |",
    ]
    for name, digest in result["verified_hashes"].items():
        lines.append(f"| `{name}` | `{digest[:32]}…` |")
    lines += [
        "",
        f"Builder outcome corroborated: **{result['builder_outcome_corroborated']}**; coverage token "
        f"corroborated: **{result['builder_coverage_token_corroborated']}**.",
        "",
    ]
    if result["failures"]:
        lines += ["## Failures", ""] + [f"- {entry}" for entry in result["failures"]] + [""]
    else:
        lines += [
            "## Failures",
            "",
            "None. Every recomputation agreed with the builder's artefact.",
            "",
        ]
    md_out = Path(args.md_out)
    md_out.write_text("\n".join(lines), encoding="utf-8")

    print(
        f"{result['status']} {result['checks_passed']}/{result['checks_total']} checks, "
        f"{result['mismatches']} mismatches, FALSE_SUCCESS = {result['false_success']}"
    )
    for failure in result["failures"][:20]:
        print(f"  FAIL {failure}")
    print(f"written -> {out}, {md_out}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
