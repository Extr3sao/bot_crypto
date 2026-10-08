"""Independent verification of the ECONOMIC-001 evidence closure.

Different program from the builder, and it reaches every claim by a different route:

* the deliverable hashes are recomputed as bytes and as git blobs, and the *delivery commit* is
  inspected directly (its tree, its file list, and the absence of this closure from it);
* the horizon medians are recomputed from the raw series with a **different window convention**
  (exhaustive overlapping windows plus an odd shifted offset), and the builder's aligned, shifted
  and exhaustive medians are re-derived independently and compared;
* the one-timeline claim is re-checked by a **time-keyed join** (a dictionary from open time to bar)
  rather than by index arithmetic;
* the toll is recomputed through the **library** and against the frozen constants, so the two routes
  must agree with each other and with the closure;
* the depth-based impact is recomputed with a **marginal-level interpolation** instead of the
  builder's whole-level walk;
* the governance limits are read from the source documents and the absence of an order path is
  re-derived from the configuration, the RFC invariants and the recorded decision files;
* the closure's own record of what is measured, estimated and unknown is checked against the raw
  snapshot's declared budget and against the flags.

It refuses forbidden tokens, requires ``FALSE_SUCCESS = 0``, and fails closed: any mismatch is a
FAIL with the offending field named.  Verdicts: ``COST_EVIDENCE_VERIFIED``,
``COST_EVIDENCE_INCOMPLETE``, ``COST_EVIDENCE_FAILED``.

Run:  python scripts/economic001_closure_verify.py
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CLOSURE = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.json"
CLOSURE_MD = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.md"
SNAPSHOT = REPO / "data" / "economic001" / "READ_ONLY_SNAPSHOT.json"
OUT = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE_VERIFICATION.json"

FEASIBILITY = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.json"
FEASIBILITY_VERIFICATION = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY_VERIFICATION.json"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
RUN_REPORT = REPO / "data" / "rfc046" / "RUN_REPORT.json"
RFC046 = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"
RUNTIME_CFG = REPO / "config" / "runtime.yaml"
PRICE_DIR = REPO / "data" / "raw" / "alpha003" / "price"
STORAGE = REPO / "data" / "storage"
REAL_DECISIONS = REPO / "evidence" / "real_decisions"

VERDICTS = ("COST_EVIDENCE_VERIFIED", "COST_EVIDENCE_INCOMPLETE", "COST_EVIDENCE_FAILED")
FORBIDDEN_TOKENS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")
BPS = 10_000.0
CAPITAL = 200.0
DOCUMENTED_SIZE = 1000.0
FROZEN_HISTORICAL_TOLL_BPS = 23.7906
POSTERIOR_TOLL_BPS = 23.353553391
MEDIAN_TOLERANCE = 0.25
AGGREGATION_TOLERANCE = 1e-3
EXACT = 1e-9
SERIES_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
HORIZONS: dict[str, tuple[str, int, int]] = {
    "5m": ("5m", 1, 60),
    "15m": ("15m", 1, 60),
    "1h": ("1h", 1, 60),
    "4h": ("1h", 4, 7),
    "8h": ("1h", 8, 7),
    "24h": ("1h", 24, 7),
    "72h": ("1h", 72, 7),
    "168h": ("1h", 168, 7),
}
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
DELIVERABLES = (
    "scripts/rfc046_economic_gate.py",
    "scripts/rfc046_economic_gate_verify.py",
    "tests/unit/research/test_rfc046_economic_gate.py",
    "data/rfc046/ECONOMIC_FEASIBILITY.json",
    "data/rfc046/ECONOMIC_FEASIBILITY.md",
    "data/rfc046/ECONOMIC_FEASIBILITY_VERIFICATION.json",
)
LONG_HORIZON_FAMILIES = ("momentum", "swing_trading", "trend_following")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> tuple[str, int]:
    """Raw stdout with only the trailing newline removed, so porcelain lines keep their leading space."""
    result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return result.stdout.rstrip("\n"), result.returncode


def find_dict_with_key(node: Any, key: str) -> dict[str, Any]:
    """First nested mapping that carries `key`: the verifier must not assume where a block lives."""
    if isinstance(node, dict):
        if key in node:
            return node
        for value in node.values():
            found = find_dict_with_key(value, key)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_dict_with_key(value, key)
            if found:
                return found
    return {}


def git_blob_sha256(ref: str, path: str) -> str | None:
    """Hash the blob as bytes: the working tree may differ by line endings, the blob may not."""
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{ref}:{path}"], cwd=REPO, capture_output=True, check=False
    )
    return hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None


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


# --------------------------------------------------------------------------- #
# independent re-derivations
# --------------------------------------------------------------------------- #
def series(asset: str, timeframe: str) -> dict[str, list[float]]:
    rows = read_json(PRICE_DIR / f"{asset}_{timeframe}.json")
    return {
        "open_ms": [int(row[0]) for row in rows],
        "open": [float(row[1]) for row in rows],
        "close": [float(row[4]) for row in rows],
    }


def medians(asset: str, timeframe: str, bars: int, step: int, offset: int) -> list[float]:
    data = series(asset, timeframe)
    out: list[float] = []
    for start in range(offset, len(data["open"]) - bars, step):
        out.append(abs(data["open"][start + bars] / data["open"][start] - 1.0) * BPS)
    return out


def pooled(timeframe: str, bars: int, step: int, offset: int) -> list[float]:
    moves: list[float] = []
    for asset in ASSETS:
        moves.extend(medians(asset, timeframe, bars, step, offset))
    return moves


def independent_toll(size_usd: float) -> float:
    """The other route: the frozen library, not the constants."""
    from trading_bot.research.microstructure.cost_model_v3 import default_model

    return float(
        default_model()
        .evaluate(size_usd=size_usd, entry_order_type="market", exit_order_type="market")
        .round_trip_bps
    )


def interpolated_impact(levels: list[list[float]], notional: float) -> dict[str, Any]:
    """Marginal-level interpolation, not a whole-level walk."""
    if not levels:
        return {"filled": False, "cost_bps": None}
    best = levels[0][0]
    cumulative_notional = 0.0
    cumulative_qty = 0.0
    for price, size in levels:
        level_notional = price * size
        if cumulative_notional + level_notional >= notional:
            take = notional - cumulative_notional
            cumulative_qty += take / price
            cumulative_notional += take
            vwap = cumulative_notional / cumulative_qty
            return {"filled": True, "cost_bps": (vwap - best) / best * BPS}
        cumulative_notional += level_notional
        cumulative_qty += size
    return {"filled": False, "cost_bps": None}


# --------------------------------------------------------------------------- #
# verification blocks
# --------------------------------------------------------------------------- #
def verify_preservation(c: Checks, closure: dict[str, Any]) -> None:
    preservation = closure["evidence_preservation"]
    commit = preservation["delivery_commit"]

    listing, rc = git("show", "--name-only", "--format=", commit)
    paths = [line for line in listing.splitlines() if line.strip()]
    c.check("the delivery commit exists", rc == 0 and bool(commit), commit)
    c.check(
        "the delivery commit carries all six deliverables and nothing else",
        sorted(paths) == sorted(DELIVERABLES),
        paths,
    )
    for path in DELIVERABLES:
        recorded = preservation["deliverable_hashes"][path]
        c.check(
            f"the recorded hash of {path} matches the bytes on disk",
            recorded["working_tree_sha256"] == sha256(REPO / path),
            recorded["working_tree_sha256"],
        )
        blob_hash = git_blob_sha256(commit, path)
        c.check(
            f"the recorded blob hash of {path} matches the repository",
            recorded["git_blob_sha256"] == blob_hash,
            f"{recorded['git_blob_sha256']} vs {blob_hash}",
        )
    c.check(
        "the report bytes equal the hash the RFC-046 verifier recorded",
        preservation["bytes_match_the_verified_run"]
        and preservation["verified_artifact_sha256_recorded_by_verifier"]
        == sha256(FEASIBILITY)
        == read_json(FEASIBILITY_VERIFICATION)["verified_artifact_sha256"],
        preservation["verified_artifact_sha256_recorded_by_verifier"],
    )
    c.check(
        "nothing foreign was swept into the delivery commit",
        preservation["foreign_paths_in_delivery_commit"] == [],
        preservation["foreign_paths_in_delivery_commit"],
    )

    closure_path = str(CLOSURE.relative_to(REPO)).replace("\\", "/")
    _, present_rc = git("cat-file", "-e", f"{commit}:{closure_path}")
    c.check(
        "non-circularity: the named commit does not contain this closure",
        present_rc != 0 and preservation["non_circularity"]["holds"] is True,
        present_rc,
    )
    head, _ = git("rev-parse", "HEAD")
    _, ancestor_rc = git("merge-base", "--is-ancestor", commit, head)
    c.check(
        "the delivery commit is an ancestor of the verified HEAD",
        ancestor_rc == 0,
        (commit, head),
    )
    c.check(
        "the commit the closure names precedes the head it ran at",
        git("merge-base", "--is-ancestor", commit, closure["head_at_run"])[1] == 0,
        (commit, closure["head_at_run"]),
    )
    closure_blob = git_blob_sha256(closure["head_at_run"], closure_path)
    c.check(
        "the closure's own bytes are not inside the head it ran at",
        closure_blob != sha256(CLOSURE),
        f"head copy {closure_blob} vs current {sha256(CLOSURE)}",
    )
    c.check(
        "this verification ran at the delivery commit or a descendant of it",
        git("merge-base", "--is-ancestor", commit, git("rev-parse", "HEAD")[0])[1] == 0,
        commit,
    )


def verify_horizons(c: Checks, closure: dict[str, Any]) -> None:
    block = closure["horizon_verification"]
    for horizon, (timeframe, bars, offset) in HORIZONS.items():
        reported = block["per_horizon"][horizon]
        horizon_minutes = int(horizon.rstrip("mh") or 0) * (60 if horizon.endswith("h") else 1)
        resolution = SERIES_MINUTES[timeframe]
        c.check(
            f"{horizon}: the series can certify the horizon",
            resolution <= horizon_minutes and horizon_minutes % resolution == 0,
            resolution,
        )
        c.check(
            f"{horizon}: the closure itself declares that resolution sufficient",
            reported["resolution_is_sufficient"] is True,
            reported["resolution_is_sufficient"],
        )
        exhaustive = pooled(timeframe, bars, 1, 0)
        shifted = pooled(timeframe, bars, bars, offset)
        c.close(
            f"{horizon}: the aligned median reproduces independently",
            reported["median_abs_move_bps"],
            statistics.median(pooled(timeframe, bars, bars, 0)),
            abs(reported["median_abs_move_bps"]) * MEDIAN_TOLERANCE,
        )
        c.close(
            f"{horizon}: the shifted median reproduces independently",
            reported["shifted_window_median_bps"],
            statistics.median(shifted),
            abs(reported["shifted_window_median_bps"]) * MEDIAN_TOLERANCE,
        )
        c.close(
            f"{horizon}: the exhaustive median reproduces independently",
            reported["exhaustive_window_median_bps"],
            statistics.median(exhaustive),
            abs(reported["exhaustive_window_median_bps"]) * 0.05,
        )
        c.check(
            f"{horizon}: the aligned windows are declared disjoint",
            reported.get("windows_are_disjoint") is True
            and reported["overlap_declared"] is False
            and reported["windows"] >= reported["windows_declared_non_overlapping"] - 1,
            reported.get("windows"),
        )

    # Timestamps, spacing, coverage, timezone: recomputed from the raw rows.
    for timeframe, minutes in SERIES_MINUTES.items():
        for asset in ASSETS:
            data = series(asset, timeframe)
            times = data["open_ms"]
            step_ms = minutes * 60_000
            steps = [b - a for a, b in itertools.pairwise(times)]
            c.check(
                f"{timeframe}/{asset}: monotonic, gapless and grid-aligned",
                all(b > a for a, b in itertools.pairwise(times))
                and all(delta == step_ms for delta in steps)
                and all(t % step_ms == 0 for t in times)
                and len(set(times)) == len(times),
                f"{len(times)} bars",
            )

    # One timeline, joined by open time rather than by index.
    for asset in ASSETS:
        five = series(asset, "5m")
        by_time = dict(
            zip(five["open_ms"], zip(five["open"], five["close"], strict=False), strict=False)
        )
        for timeframe, ratio in (("15m", 3), ("1h", 12)):
            coarse = series(asset, timeframe)
            mismatches = 0
            compared = 0
            for open_ms, open_price, close_price in zip(
                coarse["open_ms"], coarse["open"], coarse["close"], strict=False
            ):
                last_ms = open_ms + (ratio - 1) * 300_000
                first = by_time.get(open_ms)
                last = by_time.get(last_ms)
                if first is None or last is None:
                    continue
                compared += 1
                if (
                    abs(first[0] / open_price - 1.0) > 1e-9
                    or abs(last[1] / close_price - 1.0) > 1e-9
                ):
                    mismatches += 1
            rate = mismatches / compared if compared else 1.0
            c.check(
                f"{asset}: {timeframe} bars join the 5m series on the same timeline (rate {rate:.2e})",
                compared > 0 and rate <= AGGREGATION_TOLERANCE,
                f"{mismatches}/{compared}",
            )
    c.check(
        "the closure's aggregation verdict agrees with the independent join",
        block["assets_with_aggregation_mismatch"] == [],
        block["assets_with_aggregation_mismatch"],
    )


def verify_costs(c: Checks, closure: dict[str, Any]) -> None:
    block = closure["cost_model_verification"]
    frozen = read_json(COST_MODEL)
    c.check(
        "the frozen model is the one named and hashed",
        block["model"] == frozen["model"] and block["model_file_sha256"] == sha256(COST_MODEL),
        block["model"],
    )
    components = {
        component["name"]: component
        for component in next(
            scenario["evaluation"]
            for scenario in frozen["scenarios"]
            if scenario["evaluation"]["scenario_id"] == "BINANCE_SPOT_STANDARD_TAKER"
        )["components"]
    }
    c.close(
        "the fee components are counted as known", block["split"]["known_fees_bps"], 20.0, EXACT
    )
    c.close(
        "the modelled execution terms are the rest of the toll",
        block["split"]["estimated_execution_bps"],
        float(components["spread"]["value_bps"])
        + float(components["slippage"]["value_bps"])
        + float(components["market_impact"]["value_bps"]),
        EXACT,
    )
    c.close(
        "the recomputation at the documented size matches the frozen record",
        block["independent_recomputation"]["at_1000_usd"]["total_bps"],
        FROZEN_HISTORICAL_TOLL_BPS,
        1e-4,
    )
    c.close(
        "the recomputation at the account size matches the posterior figure",
        block["independent_recomputation"]["at_200_usdt"]["total_bps"],
        POSTERIOR_TOLL_BPS,
        EXACT,
    )
    c.close(
        "the library agrees with the constants at the account size",
        independent_toll(CAPITAL),
        block["independent_recomputation"]["at_200_usdt"]["total_bps"],
        1e-9,
    )
    c.close(
        "the library agrees with the constants at the documented size",
        independent_toll(DOCUMENTED_SIZE),
        block["independent_recomputation"]["at_1000_usd"]["total_bps"],
        1e-9,
    )
    c.close(
        "the stressed toll is 1.5x the toll",
        block["independent_recomputation"]["at_200_usdt"]["stressed_at_1p5x_bps"],
        POSTERIOR_TOLL_BPS * 1.5,
        1e-6,
    )
    c.check(
        "the historical evaluation keeps the frozen toll",
        block["historical_evaluation_toll_bps"] == FROZEN_HISTORICAL_TOLL_BPS
        and read_json(FORENSICS)["cost_model"]["admission_round_trip_bps"]
        == FROZEN_HISTORICAL_TOLL_BPS,
        block["historical_evaluation_toll_bps"],
    )
    c.check(
        "no rejected result was recalculated against the smaller toll",
        block["non_retroactivity"]["rejected_candidates_recomputed"] is False
        and block["non_retroactivity"]["cost_forensics_sha256"] == sha256(FORENSICS)
        and block["non_retroactivity"]["run_report_sha256"] == sha256(RUN_REPORT),
        block["non_retroactivity"]["cost_forensics_sha256"],
    )
    c.check(
        "the maker path stays inadmissible",
        block["maker_path"]["admissible"] is False,
        block["maker_path"],
    )


def verify_reality(c: Checks, closure: dict[str, Any]) -> None:
    block = closure["read_only_execution_reality"]
    snapshot = read_json(SNAPSHOT)
    c.check(
        "the snapshot is the verified file and was complete",
        block["source_sha256"] == sha256(SNAPSHOT) and snapshot["complete"] is True,
        block["source_sha256"],
    )
    c.check(
        "no order was sent, no credential used, no private endpoint called",
        snapshot["orders_sent"] == 0
        and snapshot["credentials_used"] == 0
        and snapshot["private_endpoints_called"] == []
        and snapshot["authentication"].startswith("none"),
        snapshot["budget"],
    )
    c.check(
        "the collection budget was finite, declared and met",
        snapshot["budget"]["finite"] is True
        and snapshot["budget"]["declared_before_collection"] is True
        and snapshot["budget"]["requests_made"] <= snapshot["budget"]["requests_planned"],
        snapshot["budget"],
    )
    c.check(
        "the endpoint is the public market-data host",
        snapshot["endpoint_base"] == "https://api.binance.com",
        snapshot["endpoint_base"],
    )

    spreads: dict[str, list[float]] = {symbol: [] for symbol in snapshot["symbols"]}
    for row in snapshot["observations"]:
        for symbol, book in row["books"].items():
            spreads[symbol].append(book["spread_bps"])
    for symbol, values in spreads.items():
        c.close(
            f"{symbol}: the reported median spread reproduces",
            block["spread"]["per_symbol"][symbol]["median_full_spread_bps"],
            statistics.median(values),
            1e-6,
        )
        c.close(
            f"{symbol}: the reported maximum spread reproduces",
            block["spread"]["per_symbol"][symbol]["max_full_spread_bps"],
            max(values),
            1e-6,
        )
    pooled = [value for values in spreads.values() for value in values]
    c.close(
        "the pooled median spread reproduces",
        block["spread"]["pooled_median_full_spread_bps"],
        statistics.median(pooled),
        1e-6,
    )
    c.close(
        "the worst observed spread reproduces",
        block["spread"]["max_observed_full_spread_bps"],
        max(pooled),
        1e-6,
    )
    c.check(
        "the spread is compared like for like against the round-trip model term",
        block["spread"]["modelled_round_trip_spread_bps"] == 1.0
        and block["spread"]["verdict"]
        in ("MODEL_CONSERVATIVE", "AT_THE_MODELLED_BOUNDARY", "WIDER_THAN_MODELLED"),
        block["spread"]["verdict"],
    )

    for symbol in snapshot["symbols"]:
        depth = snapshot["observations"][0]["depth"][symbol]
        for size in (25.0, 200.0, 2000.0, 20000.0):
            label = f"{size:.0f}_usdt"
            reported = block["depth"]["impact_estimate_bps"][symbol][label]["buy"]
            recomputed = interpolated_impact(depth["asks"], size)
            if recomputed["filled"]:
                c.close(
                    f"{symbol}: the buy-side impact at {size:.0f} USDT reproduces by interpolation",
                    reported["cost_bps"],
                    recomputed["cost_bps"],
                    1e-6,
                )
            c.check(
                f"{symbol}: the buy-side fill status at {size:.0f} USDT agrees",
                reported["filled"] == recomputed["filled"],
                (reported["filled"], recomputed["filled"]),
            )
    c.check(
        "the closure does not claim measured slippage, fill quality or a simulator",
        block["realized_slippage_measured"] is False
        and block["fill_quality_measured"] is False
        and block["simulator_used_as_measurement"] is False,
        block["realized_slippage_measured"],
    )
    unknown = " ".join(block["estimated_vs_measured"]["unknown_and_stated"]).lower()
    for term in ("queue position", "fill probability", "realised slippage", "fill quality"):
        c.check(f"the closure keeps {term} explicitly UNKNOWN", term in unknown, unknown)
    c.check(
        "the measured list contains only things the snapshot actually contains",
        all(
            any(
                keyword in item.lower()
                for keyword in ("spread", "latency", "clock", "depth", "impact")
            )
            for item in block["estimated_vs_measured"]["measured_now"]
        ),
        block["estimated_vs_measured"]["measured_now"],
    )


def verify_decision(c: Checks, closure: dict[str, Any]) -> None:
    block = closure["economic_decision"]
    horizons = closure["horizon_verification"]["per_horizon"]
    forensics = read_json(FORENSICS)
    run_report = read_json(RUN_REPORT)

    for family, row in block["per_family"].items():
        expected = row["median_abs_move_bps"] / POSTERIOR_TOLL_BPS >= 5.0
        c.check(
            f"{family}: the margin verdict follows from the measured median",
            row["movement_margin_sufficient"] is expected,
            (row["median_abs_move_bps"], row["movement_margin_sufficient"]),
        )
        c.close(
            f"{family}: the median is the one measured at its representative horizon",
            row["median_abs_move_bps"],
            horizons[row["horizon"]]["median_abs_move_bps"],
            EXACT,
        )
    profile = block["low_turnover_long_horizon_region"]
    c.check(
        "the scope verdict follows from the long-horizon families",
        (block["scope_verdict"] == "MOVEMENT_MARGIN_SUFFICIENT_FOR_FURTHER_RESEARCH")
        == all(
            block["per_family"][family]["movement_margin_sufficient"]
            for family in LONG_HORIZON_FAMILIES
        ),
        block["scope_verdict"],
    )
    c.check(
        "the short-horizon families that fail the rule are reported, not hidden",
        set(profile["families"]) == set(LONG_HORIZON_FAMILIES)
        and all(
            family in block["per_family"]
            for family in block["families_outside_the_proposed_profile"]
        ),
        block["families_outside_the_proposed_profile"],
    )

    for candidate_id, forensic in forensics["candidates"].items():
        preserved = block["rejected_candidates_preserved"][candidate_id]
        for field in ("gross_expectancy_bps", "oos_gross_expectancy_bps"):
            recorded = forensic.get(field)
            kept = preserved.get(field)
            if recorded is None:
                c.check(
                    f"{candidate_id}: {field} stays unmeasured (zero-sample honest None)",
                    kept is None,
                    kept,
                )
            else:
                c.close(
                    f"{candidate_id}: the preserved {field} is the recorded one",
                    kept,
                    recorded,
                    EXACT,
                )
        c.check(
            f"{candidate_id}: nothing was recomputed and the verdict is unchanged",
            preserved["recomputed_here"] is False
            and preserved["verdict"] == forensic["verdict"]
            and preserved["gate_verdict"]
            == next(
                run["gate"]["verdict"]
                for run in run_report["runs"]
                if run["candidate_id"] == candidate_id
            ),
            preserved["verdict"],
        )
    c.check(
        "no hypothesis and no strategy was produced",
        block["new_hypotheses_generated"] == 0
        and block["new_strategies_recommended"] == 0
        and block["rejected_candidates_recomputed"] == 0,
        block["new_hypotheses_generated"],
    )
    c.check(
        "movement margin is explicitly not alpha",
        block["movement_margin_is_not_alpha"] is True
        and block["movement_margin_is_not_capturable_edge"] is True,
        block["movement_margin_is_not_alpha"],
    )


def verify_governance(c: Checks, closure: dict[str, Any]) -> None:
    standing = closure["standing"]
    rfc = read_json(RFC046)
    operating = read_json(OPERATING_MODEL)
    runtime_text = RUNTIME_CFG.read_text(encoding="utf-8")
    exchange_text = EXCHANGE_CFG.read_text(encoding="utf-8")

    invariants = rfc["invariants_while_active"]
    c.check(
        "the RFC invariants are the standing limits",
        standing["trades_authorized"] == invariants["TRADES_AUTHORIZED"] == 0
        and standing["rfc_live_trading"] == invariants["LIVE_TRADING"] == "DISABLED"
        and standing["rfc_g_business_reentry"] == invariants["G_BUSINESS_REENTRY"] == "NOT_PASS"
        and invariants["real_orders"] == "REFUSED_BY_POLICY",
        invariants,
    )
    c.check(
        "the runtime cannot trade live",
        standing["live_trading"] is False
        and "live_trading_enabled: false" in runtime_text
        and "sandbox: true" in exchange_text
        and standing["runtime_mode"] == "paper",
        (standing["live_trading"], standing["runtime_mode"]),
    )
    operating_gate = find_dict_with_key(operating, "G_BUSINESS_REENTRY")
    c.check(
        "the operating model still blocks re-entry and profitability",
        bool(operating_gate)
        and standing["G_BUSINESS_REENTRY"] == operating_gate["G_BUSINESS_REENTRY"] == "NOT_PASS"
        and standing["profitability_verified"] is False
        and operating_gate["TRADES_AUTHORIZED"] == 0
        and operating_gate["LIVE_TRADING"] == "DISABLED",
        operating_gate,
    )
    c.check(
        "the campaign is still failed and the next one unauthorized",
        standing["campaign_status"] == "DISCOVERY_CAMPAIGN_FAILED"
        and standing["next_campaign"] == "NOT_AUTHORIZED",
        standing["campaign_status"],
    )

    absence = closure["absence_of_real_trades"]
    carries_order = False
    for name in ("decisions.jsonl", "operations.jsonl", "outcomes.jsonl"):
        path = REAL_DECISIONS / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            keys = json.loads(line).keys()
            carries_order = carries_order or any(
                "order" in key.lower() or "fill" in key.lower() for key in keys
            )
    c.check(
        "no order archive and no order field exists anywhere",
        (STORAGE / "bot.db").exists() is False and carries_order is False,
        (STORAGE / "bot.db").exists(),
    )
    c.check(
        "the closure reaches the same absence verdict",
        absence["no_real_trades"] is True
        and absence["any_record_carries_an_order_or_fill_field"] is False,
        absence["no_real_trades"],
    )


def verify_meta(c: Checks, closure: dict[str, Any], text: str) -> None:
    feasibility_stamp = read_json(FEASIBILITY)["generated_at_utc"]
    c.check(
        "the closure is not older than the evidence it closes",
        closure["generated_at_utc"] >= feasibility_stamp,
        (closure["generated_at_utc"], feasibility_stamp),
    )
    c.check(
        "the closure records the commit it ran at",
        len(closure["head_at_run"]) == 40,
        closure["head_at_run"],
    )
    c.check(
        "the builder is not the verifier",
        closure["builder_equals_verifier"] is False
        and closure["builder"].endswith("economic001_closure.py"),
        closure["builder"],
    )
    # Structural, not textual: parse this file's real import statements, so the check cannot be
    # satisfied or broken by a string that happens to sit in its own source.
    own_source = Path(__file__).read_text(encoding="utf-8")
    builder_module = "economic001_closure"
    imported: set[str] = set()
    for node in ast.walk(ast.parse(own_source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    c.check(
        "this verifier imports the builder nowhere",
        not any(builder_module in name for name in imported),
        sorted(imported),
    )
    c.check(
        "the closure admits nothing",
        "does_not_license" in closure and len(closure["does_not_license"]) >= 3,
        closure.get("does_not_license"),
    )
    haystack = json.dumps(closure).upper() + text.upper()
    offenders = [token for token in FORBIDDEN_TOKENS if token in haystack]
    c.check("no forbidden verdict token appears", offenders == [], offenders)
    c.check(
        "false_success is exactly zero", closure["false_success"] == 0, closure["false_success"]
    )
    required = (
        "CURRENT_HEAD",
        "FILES_COMMITTED",
        "DATASET_HASHES",
        "TIMEFRAME_VERIFICATION",
        "COST_MODEL_STATUS",
        "READ_ONLY_MARKET_DATA_STATUS",
        "ESTIMATED_VS_MEASURED_COSTS",
        "INDEPENDENT_VERIFICATION",
        "FALSE_SUCCESS",
        "OPEN_DEFECTS",
        "NEXT_GATE",
    )
    final = closure["final_report"]
    missing = [key for key in required if key not in final]
    c.check("the final report delivers every required field", missing == [], missing)
    c.check(
        "the horizon count matches the eight required horizons",
        set(closure["horizon_verification"]["per_horizon"]) == set(HORIZONS),
        sorted(closure["horizon_verification"]["per_horizon"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    c = Checks()
    closure = read_json(CLOSURE)
    text = CLOSURE_MD.read_text(encoding="utf-8")

    verify_preservation(c, closure)
    verify_horizons(c, closure)
    verify_costs(c, closure)
    verify_reality(c, closure)
    verify_decision(c, closure)
    verify_governance(c, closure)
    verify_meta(c, closure, text)

    if not c.failed:
        verdict = "COST_EVIDENCE_VERIFIED"
    elif c.passed >= c.total * 0.9:
        verdict = "COST_EVIDENCE_INCOMPLETE"
    else:
        verdict = "COST_EVIDENCE_FAILED"

    head, _ = git("rev-parse", "HEAD")
    result = {
        "artifact": "ECONOMIC-001_COST_EVIDENCE_CLOSURE_VERIFICATION",
        "verifier": "scripts/economic001_closure_verify.py",
        "builder": "scripts/economic001_closure.py",
        "builder_equals_verifier": False,
        "verified_artifact": "data/economic001/EVIDENCE_CLOSURE.json",
        "verified_artifact_sha256": sha256(CLOSURE),
        "closure_head": closure["head_at_run"],
        "closure_delivery_commit": closure["evidence_preservation"]["delivery_commit"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": head,
        "checks_total": c.total,
        "checks_passed": c.passed,
        "mismatches": len(c.failed),
        "failures": c.failed,
        "false_success": 0 if not c.failed else len(c.failed),
        "verdict": verdict,
        "allowed_verdicts": list(VERDICTS),
        "status": "PASS" if not c.failed else "FAIL",
        "method": (
            "deliverable hashes recomputed as bytes and as git blobs and the delivery commit "
            "inspected directly; horizon medians recomputed with exhaustive and shifted windows; the "
            "one-timeline claim re-joined by open time; the toll recomputed through the library and "
            "against the frozen constants; the depth impact recomputed by marginal-level "
            "interpolation; governance limits read from the source documents; the absence of an order "
            "path re-derived from configuration, RFC invariants and the recorded files"
        ),
    }
    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{result['verdict']} {c.passed}/{c.total} checks, {result['mismatches']} mismatches, "
        f"FALSE_SUCCESS = {result['false_success']}"
    )
    for failure in c.failed:
        print(f"  FAIL {failure}")
    print(f"written -> {out.relative_to(REPO)}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
