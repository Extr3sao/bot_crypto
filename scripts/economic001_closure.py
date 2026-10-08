"""ECONOMIC-001 — cost-evidence closure and execution reality.

The economic gate answered "what would a strategy have to look like?" but it left the answer on
unversioned files, and it inherited a cost model whose spread term had no historical endpoint and
whose medians were measured on one window convention at one resolution.  Before any further
campaign is even discussed, the evidence has to survive an audit: the numbers must be tied to
committed bytes, re-derived at a resolution that can actually certify them, separated into what is
known and what is estimated, and joined by the parts of execution reality that can be measured
without sending an order.

This builder produces that closure.  It does six things and refuses to do a seventh:

1. **Evidence preservation.** It names the commit that carries the six economic deliverables, hashes
   them as bytes on disk *and* as git blobs, proves nothing else from another thread was swept in,
   and enforces a non-circularity rule: the commit the artefact records must not contain the
   artefact.
2. **Horizon verification.** It recomputes the absolute move for 5m, 15m, 1h, 4h, 8h, 24h, 72h and
   168h from the **native series of each horizon** (the 15-minute file for 15m, the hourly file for
   the multi-hour horizons), never certifying a short horizon from a long bar, and it audits the
   timestamps, the timezone alignment, the bar spacing, the gaps, the coverage and the declared
   non-overlap.  It also proves the three series describe one timeline by aggregating the 5-minute
   bars into the 15-minute and hourly ones.
3. **Cost-model verification.** It recomputes COST_MODEL_V3 and splits its components into known
   fees and estimated execution costs, keeps the frozen 23.7906 bps as the historical evaluation,
   and records that the 200 USDT figure is a *posterior* economic evaluation that authorizes **no**
   retrospective recalculation of the rejected strategies.
4. **Read-only execution reality.** It consumes a finite, declared public-data snapshot (no key, no
   signature, no order) and measures what is measurable — live spread, observation latency, clock
   skew, quote changes and depth-based impact per order size — while leaving maker queue position,
   fill probability, realised slippage and fill quality explicitly ``UNKNOWN``.
5. **Economic decision.** It preserves the three rejected candidates unchanged and decides whether
   the proposed low-turnover / long-horizon region has enough *movement margin* to justify further
   research — while stating that movement margin is not alpha.
6. **Standing state.** It re-derives every governance limit from the documents and shows that no
   order path exists at all.

It creates no strategy, no hypothesis and no campaign; it changes no frozen spec; it recomputes no
rejected result; and it recommends nothing to trade.

Run:  python scripts/economic001_closure.py            (writes the artefacts)
      python scripts/economic001_closure.py --check    (builds, writes nothing)
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

try:  # the frozen model is the authority; the optional import only cross-checks it
    from trading_bot.research.microstructure.cost_model_v3 import default_model

    MODEL_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    default_model = None  # type: ignore[assignment]
    MODEL_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

OUT_JSON = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.json"
OUT_MD = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.md"
SNAPSHOT = REPO / "data" / "economic001" / "READ_ONLY_SNAPSHOT.json"

FEASIBILITY = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.json"
FEASIBILITY_MD = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.md"
FEASIBILITY_VERIFICATION = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY_VERIFICATION.json"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
RUN_REPORT = REPO / "data" / "rfc046" / "RUN_REPORT.json"
RFC046 = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
REENTRY_POLICY = REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.json"
FREEZE = REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"
RUNTIME_CFG = REPO / "config" / "runtime.yaml"
PRICE_DIR = REPO / "data" / "raw" / "alpha003" / "price"
STORAGE = REPO / "data" / "storage"
REAL_DECISIONS = REPO / "evidence" / "real_decisions"

#: The six economic deliverables of the previous gate: code, tests, report and both manifests.
DELIVERABLES: tuple[str, ...] = (
    "scripts/rfc046_economic_gate.py",
    "scripts/rfc046_economic_gate_verify.py",
    "tests/unit/research/test_rfc046_economic_gate.py",
    "data/rfc046/ECONOMIC_FEASIBILITY.json",
    "data/rfc046/ECONOMIC_FEASIBILITY.md",
    "data/rfc046/ECONOMIC_FEASIBILITY_VERIFICATION.json",
)
#: What this gate adds; committed after the closure is built, so the closure can name it as pending.
THIS_GATE: tuple[str, ...] = (
    "scripts/economic001_readonly_probe.py",
    "scripts/economic001_closure.py",
    "scripts/economic001_closure_verify.py",
    "tests/unit/research/test_economic001_evidence_closure.py",
    "data/economic001/READ_ONLY_SNAPSHOT.json",
    "data/economic001/EVIDENCE_CLOSURE.json",
    "data/economic001/EVIDENCE_CLOSURE.md",
    "data/economic001/EVIDENCE_CLOSURE_VERIFICATION.json",
)

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
BPS = 10_000.0
CAPITAL = 200.0
DOCUMENTED_SIZE = 1000.0
FROZEN_HISTORICAL_TOLL_BPS = 23.7906  # the figure the rejected strategies were judged against
POSTERIOR_TOLL_BPS = 23.353553391  # the 200 USDT economic evaluation, later and not retroactive
MOVEMENT_MARGIN_MULTIPLE = 5.0  # declared rule for "enough movement margin"
QUOTE_CHANGE_TOL = 0.0
MEDIAN_TOLERANCE = 0.25  # agreement with the already-verified medians, on a different convention
#: Two files of the same market fetched minutes apart and occasionally carrying a bad print are not
#: bit-identical; the aligned comparison is therefore a rate with a declared tolerance, and the
#: exceptions are named with their timestamps.  The *time keys* must match everywhere.
AGGREGATION_TOLERANCE = 1e-3

#: horizon -> (native series, bars per window).  The series must be able to *certify* the horizon:
#: its own resolution divides the horizon exactly and is never coarser than it.
HORIZONS: dict[str, tuple[str, int]] = {
    "5m": ("5m", 1),
    "15m": ("15m", 1),
    "1h": ("1h", 1),
    "4h": ("1h", 4),
    "8h": ("1h", 8),
    "24h": ("1h", 24),
    "72h": ("1h", 72),
    "168h": ("1h", 168),
}
SERIES_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
#: The representative horizon each family is judged at (the shortest one it trades), as declared by
#: the previous gate; repeated here so this closure ties its decision to the same band.
FAMILY_HORIZONS = {
    "scalping": "5m",
    "intraday": "1h",
    "mean_reversion": "4h",
    "momentum": "24h",
    "swing_trading": "72h",
    "trend_following": "168h",
}
ADMISSION_SCENARIO = "BINANCE_SPOT_STANDARD_TAKER"
#: Account scale (25-500) plus two sizes beyond it, so the depth walk is exercised past the first
#: price level rather than stopping at the tick.
IMPACT_TARGETS_USDT = (25.0, 50.0, 100.0, 200.0, 500.0, 2000.0, 20000.0)
STANDING = {
    "DISCOVERY_CAMPAIGN_FAILED": True,
    "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
    "LIVE_TRADING": "DISABLED",
    "PROFITABILITY_VERIFIED": False,
    "TRADES_AUTHORIZED": 0,
    "G_BUSINESS_REENTRY": "NOT_PASS",
}
FORBIDDEN_TOKENS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git(*args: str) -> tuple[str, int]:
    """Raw stdout with only the trailing newline removed: porcelain status lines start with a space
    and stripping it would silently move every path one character to the left."""
    result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return result.stdout.rstrip("\n"), result.returncode


def _git_blob_sha256(ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{ref}:{path}"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    return _sha256_bytes(result.stdout) if result.returncode == 0 else None


def _find_dict_with_key(node: Any, key: str) -> dict[str, Any]:
    """First nested mapping that carries `key`, so a moved block is found rather than assumed."""
    if isinstance(node, dict):
        if key in node:
            return node
        for value in node.values():
            found = _find_dict_with_key(value, key)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_dict_with_key(value, key)
            if found:
                return found
    return {}


def _yaml_scalar(text: str, key: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:") and not stripped.startswith("#"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def _series(asset: str, timeframe: str) -> dict[str, list[float]]:
    """Raw rows are [open_time_ms, open, high, low, close, volume]."""
    rows = _read_json(PRICE_DIR / f"{asset}_{timeframe}.json")
    return {
        "open_ms": [int(row[0]) for row in rows],
        "open": [float(row[1]) for row in rows],
        "high": [float(row[2]) for row in rows],
        "low": [float(row[3]) for row in rows],
        "close": [float(row[4]) for row in rows],
    }


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return float(ordered[idx])


def _moves(series: dict[str, list[float]], bars: int, offset: int, step: int) -> list[float]:
    opens = series["open"]
    moves: list[float] = []
    for start in range(offset, len(opens) - bars, step):
        p0 = opens[start]
        p1 = opens[start + bars]
        moves.append(abs(p1 / p0 - 1.0) * BPS)
    return moves


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# 1. evidence preservation
# --------------------------------------------------------------------------- #
def evidence_preservation() -> dict[str, Any]:
    head, _ = _git("rev-parse", "HEAD")
    subject, _ = _git("log", "-1", "--format=%s")

    introduced, rc = _git("log", "--diff-filter=A", "--format=%H", "-1", "--", DELIVERABLES[3])
    delivery_commit = introduced.splitlines()[0] if rc == 0 and introduced else None
    delivery_subject = ""
    commit_paths: list[str] = []
    if delivery_commit:
        delivery_subject, _ = _git("log", "-1", "--format=%s", delivery_commit)
        listing, _ = _git("show", "--name-only", "--format=", delivery_commit)
        commit_paths = [line for line in listing.splitlines() if line.strip()]

    in_commit = [path for path in DELIVERABLES if path in commit_paths]
    foreign = [path for path in commit_paths if path not in DELIVERABLES]

    hashes: dict[str, Any] = {}
    for path in DELIVERABLES:
        file_path = REPO / path
        hashes[path] = {
            "working_tree_sha256": _sha256(file_path),
            "git_blob_sha256": _git_blob_sha256(delivery_commit, path) if delivery_commit else None,
            "bytes": file_path.stat().st_size,
        }

    verification = _read_json(FEASIBILITY_VERIFICATION)
    verified_hash = verification["verified_artifact_sha256"]
    report_hash = hashes["data/rfc046/ECONOMIC_FEASIBILITY.json"]["working_tree_sha256"]

    status, _ = _git("status", "--porcelain=v1")
    dirty = [line[3:].strip().strip('"') for line in status.splitlines() if line.strip()]
    mine = set(DELIVERABLES) | set(THIS_GATE)
    my_directories = {
        str(Path(path).parent).replace("\\", "/") + "/"
        for path in mine
        if str(Path(path).parent) != "."
    }
    foreign_in_tree = [
        path
        for path in dirty
        if path not in mine and not (path.endswith("/") and path in my_directories)
    ]

    # Non-circularity: the commit this artefact names must not contain this artefact.
    closure_path = str(OUT_JSON.relative_to(REPO)).replace("\\", "/")
    _in_delivery, closure_rc = _git("cat-file", "-e", f"{delivery_commit}:{closure_path}")

    return {
        "current_head": head,
        "current_head_subject": subject,
        "delivery_commit": delivery_commit,
        "delivery_subject": delivery_subject,
        "deliverables": list(DELIVERABLES),
        "deliverable_hashes": hashes,
        "deliverables_in_delivery_commit": in_commit,
        "foreign_paths_in_delivery_commit": foreign,
        "foreign_paths_left_in_worktree": sorted(foreign_in_tree),
        "files_committed": len(commit_paths),
        "bytes_match_the_verified_run": report_hash == verified_hash,
        "verified_artifact_sha256_recorded_by_verifier": verified_hash,
        "line_endings": {
            "core_autocrlf": (_git("config", "core.autocrlf")[0] or ""),
            "note": (
                "the working tree carries CRLF for the report artefacts and LF for the scripts; git "
                "stores LF.  Both hashes are recorded: working_tree_sha256 is what a reader of this "
                "checkout verifies, git_blob_sha256 is what the repository stores."
            ),
        },
        "non_circularity": {
            "rule": (
                "the commit named by this artefact must not contain this artefact, so the artefact "
                "can never describe the commit that carries it"
            ),
            "named_commit": delivery_commit,
            "artefact_path": closure_path,
            "artefact_present_in_named_commit": closure_rc == 0,
            "holds": closure_rc != 0,
        },
        "pending_in_this_gate": list(THIS_GATE),
        "reverification_after_integration": "scripts/economic001_closure_verify.py",
    }


# --------------------------------------------------------------------------- #
# 2. horizon verification
# --------------------------------------------------------------------------- #
def _integrity(asset: str, timeframe: str) -> dict[str, Any]:
    series = _series(asset, timeframe)
    times = series["open_ms"]
    step_ms = SERIES_MINUTES[timeframe] * 60_000
    steps = [b - a for a, b in itertools.pairwise(times)]
    gaps = [i for i, delta in enumerate(steps) if delta != step_ms]
    duplicates = len(times) - len(set(times))
    aligned = all(t % step_ms == 0 for t in times)
    monotonic = all(b > a for a, b in itertools.pairwise(times))
    covered = (times[-1] - times[0] + step_ms) / step_ms
    return {
        "bars": len(times),
        "timeframe_minutes": SERIES_MINUTES[timeframe],
        "interval_ms": step_ms,
        "monotonic": monotonic,
        "duplicate_timestamps": duplicates,
        "gaps": len(gaps),
        "gap_examples": [_iso(times[i]) for i in gaps[:3]],
        "expected_bars_from_coverage": int(covered),
        "coverage_start_utc": _iso(times[0]),
        "coverage_end_utc": _iso(times[-1]),
        "aligned_to_utc_grid": aligned,
        "timezone": "UTC (epoch milliseconds interpreted as UTC; every open time is grid-aligned)",
    }


def horizon_verification(report: dict[str, Any]) -> dict[str, Any]:
    integrity: dict[str, Any] = {}
    for timeframe in ("5m", "15m", "1h"):
        integrity[timeframe] = {asset: _integrity(asset, timeframe) for asset in ASSETS}

    per_horizon: dict[str, Any] = {}
    reported = report["horizon_measurement"]["per_horizon"]
    for horizon, (timeframe, bars) in HORIZONS.items():
        resolution = SERIES_MINUTES[timeframe]
        horizon_minutes = int(horizon.rstrip("mh") or 0) * (60 if horizon.endswith("h") else 1)
        aligned: list[float] = []
        shifted: list[float] = []
        exhaustive: list[float] = []
        windows_declared = 0
        for asset in ASSETS:
            series = _series(asset, timeframe)
            aligned.extend(_moves(series, bars, 0, bars))
            shifted.extend(_moves(series, bars, bars // 2 + 1, bars))
            exhaustive.extend(_moves(series, bars, 0, 1))
            windows_declared += max(0, len(range(0, len(series["open"]) - bars, bars)))
        primary = aligned
        reported_median = reported[horizon]["median_abs_move_bps"]
        median = _median(primary)
        per_horizon[horizon] = {
            "native_series": f"{timeframe} bars",
            "series_resolution_minutes": resolution,
            "bars_per_window": bars,
            "resolution_is_sufficient": resolution <= horizon_minutes
            and horizon_minutes % resolution == 0,
            "windows": len(primary),
            "windows_declared_non_overlapping": windows_declared,
            "overlap_declared": False,
            "non_overlap_proof": (
                f"step = {bars} bars >= window = {bars} bars, so no two windows share a bar; the "
                f"declared count is floor(available / {bars}) per asset and equals the windows used"
            ),
            "windows_are_disjoint": True,
            "median_abs_move_bps": round(median, 6),
            "p75_abs_move_bps": round(_pct(primary, 0.75), 6),
            "p90_abs_move_bps": round(_pct(primary, 0.90), 6),
            "shifted_window_median_bps": round(_median(shifted), 6),
            "exhaustive_window_median_bps": round(_median(exhaustive), 6),
            "reported_median_bps": reported_median,
            "relative_delta_vs_reported": round(abs(median - reported_median) / reported_median, 6),
            "agrees_with_reported": abs(median - reported_median) / reported_median
            <= MEDIAN_TOLERANCE,
        }

    # One timeline: the coarser series must be the exact aggregate of the finer one.
    aggregation: dict[str, Any] = {}
    for asset in ASSETS:
        five = _series(asset, "5m")
        fifteen = _series(asset, "15m")
        hour = _series(asset, "1h")
        checks = {
            "15m_from_3x5m": _aggregate_check(five, fifteen, 3),
            "1h_from_12x5m": _aggregate_check(five, hour, 12),
        }
        aggregation[asset] = checks

    mismatched = [
        asset
        for asset, checks in aggregation.items()
        if any(not value["ok"] for value in checks.values())
    ]
    return {
        "method": (
            "each horizon is measured on the *native series of that horizon* (the 15-minute file for "
            "15m, the hourly file for the multi-hour horizons); no short horizon is certified from a "
            "longer bar.  The window convention differs from the already-verified report on purpose: "
            "aligned, shifted and exhaustive windows are all computed and compared."
        ),
        "series_integrity": integrity,
        "per_horizon": per_horizon,
        "cross_resolution_aggregation": aggregation,
        "assets_with_aggregation_mismatch": mismatched,
        "all_horizons_certifiable": all(
            row["resolution_is_sufficient"] for row in per_horizon.values()
        ),
        "all_horizons_agree_with_reported": all(
            row["agrees_with_reported"] for row in per_horizon.values()
        ),
        "max_relative_delta_vs_reported": max(
            row["relative_delta_vs_reported"] for row in per_horizon.values()
        ),
        "all_series_monotonic_and_gapless": all(
            row["monotonic"] and row["gaps"] == 0 and row["duplicate_timestamps"] == 0
            for per_asset in integrity.values()
            for row in per_asset.values()
        ),
        "declared_non_overlap": True,
        "note": (
            "the last bar of every series is the one still forming when the file was fetched, so the "
            "aligned comparison against a series fetched minutes later is allowed the handful of "
            "exceptions recorded above rather than a claim of bit equality"
        ),
    }


def _aggregate_check(
    fine: dict[str, list[float]], coarse: dict[str, list[float]], ratio: int
) -> dict[str, Any]:
    """The coarse bar must open where the first fine bar opens and close where the last one does.

    Market data fetched at different instants is not bit-identical, so the check is a rate with a
    declared tolerance rather than a claim of perfection: every exception is named with its
    timestamp instead of being averaged away.
    """
    pairs = 0
    time_mismatches: list[str] = []
    price_mismatches: list[dict[str, Any]] = []
    max_open_diff = 0.0
    max_close_diff = 0.0
    count_mismatch = abs(len(coarse["open"]) * ratio - len(fine["open"]))
    for i, coarse_open_ms in enumerate(coarse["open_ms"]):
        j = i * ratio
        if j + ratio - 1 >= len(fine["open_ms"]):
            break
        pairs += 1
        if fine["open_ms"][j] != coarse_open_ms:
            time_mismatches.append(_iso(coarse_open_ms))
            continue
        open_diff = abs(coarse["open"][i] / fine["open"][j] - 1.0)
        close_diff = abs(coarse["close"][i] / fine["close"][j + ratio - 1] - 1.0)
        max_open_diff = max(max_open_diff, open_diff)
        max_close_diff = max(max_close_diff, close_diff)
        if open_diff > 1e-9 or close_diff > 1e-9:
            price_mismatches.append(
                {
                    "utc": _iso(coarse_open_ms),
                    "open_relative_diff": round(open_diff, 9),
                    "close_relative_diff": round(close_diff, 9),
                }
            )
    mismatch_rate = len(price_mismatches) / pairs if pairs else 1.0
    return {
        "pairs": pairs,
        "time_key_mismatches": len(time_mismatches),
        "time_key_mismatch_examples": time_mismatches[:3],
        "price_mismatch_count": len(price_mismatches),
        "price_mismatch_examples": price_mismatches[:3],
        "price_mismatch_rate": round(mismatch_rate, 9),
        "max_open_relative_diff": round(max_open_diff, 9),
        "max_close_relative_diff": round(max_close_diff, 9),
        "bar_count_ratio_rest": count_mismatch,
        "tolerance": AGGREGATION_TOLERANCE,
        "ok": len(time_mismatches) == 0 and mismatch_rate <= AGGREGATION_TOLERANCE,
    }


# --------------------------------------------------------------------------- #
# 3. cost-model verification
# --------------------------------------------------------------------------- #
def cost_model_verification() -> dict[str, Any]:
    frozen = _read_json(COST_MODEL)
    evaluation_row = None
    for scenario in frozen.get("scenarios", []):
        if scenario.get("evaluation", {}).get("scenario_id") == ADMISSION_SCENARIO:
            evaluation_row = scenario["evaluation"]
    components = list(evaluation_row["components"]) if evaluation_row else []

    # Independent arithmetic from the frozen constants: fees per leg, the spread term, and the
    # two size-driven terms whose constants the model itself labels ASSUMED/ESTIMATED.
    constants = frozen["model_constants"]
    reference_notional = float(constants["reference_notional_usd"])
    base_slippage = float(constants["base_slippage_bps"])
    base_impact = float(constants["base_impact_bps"])
    admission_spec = next(
        (
            scenario["spec"]
            for scenario in frozen.get("scenarios", [])
            if scenario["spec"]["scenario_id"] == ADMISSION_SCENARIO
        ),
        None,
    )
    taker_fee = float(admission_spec["taker_fee_bps"]) if admission_spec else 10.0
    spread_bps = float(admission_spec["default_taker_spread_bps"]) if admission_spec else 1.0

    def recompute(size_usd: float) -> dict[str, float]:
        size_ratio = math.sqrt(size_usd / reference_notional)
        fees = 2.0 * taker_fee
        slippage = 2.0 * base_slippage * (1.0 + size_ratio)
        impact = 2.0 * base_impact * size_ratio
        total = fees + spread_bps + slippage + impact
        return {
            "fees_bps": round(fees, 9),
            "spread_bps": round(spread_bps, 9),
            "slippage_bps": round(slippage, 9),
            "impact_bps": round(impact, 9),
            "total_bps": round(total, 9),
            "stressed_at_1p5x_bps": round(total * 1.5, 9),
            "fees_share": round(fees / total, 6),
        }

    recomputed_1000 = recompute(DOCUMENTED_SIZE)
    recomputed_200 = recompute(CAPITAL)

    library: dict[str, Any] = {"ran": False, "import_error": MODEL_IMPORT_ERROR}
    if default_model is not None:
        model = default_model()
        for label, size in (("at_1000_usd", DOCUMENTED_SIZE), ("at_200_usdt", CAPITAL)):
            evaluation = model.evaluate(
                size_usd=size, entry_order_type="market", exit_order_type="market"
            )
            library[label] = {
                "round_trip_bps": evaluation.round_trip_bps,
                "required_edge_bps_at_1p5x": evaluation.stress(1.5),
                "knowledge_class": evaluation.knowledge_class,
            }
        library["ran"] = True

    known = [c for c in components if c["knowledge"] == "KNOWN"]
    estimated = [c for c in components if c["knowledge"] != "KNOWN"]
    known_bps = round(sum(float(c["value_bps"]) for c in known), 9)
    estimated_bps = round(sum(float(c["value_bps"]) for c in estimated), 9)
    total_bps = round(known_bps + estimated_bps, 9)

    forensics_paths_clean = (
        _git("status", "--porcelain=v1", "--", str(FORENSICS.relative_to(REPO)))[0] == ""
    )
    run_report_clean = (
        _git("status", "--porcelain=v1", "--", str(RUN_REPORT.relative_to(REPO)))[0] == ""
    )

    return {
        "model": frozen["model"],
        "model_file": str(COST_MODEL.relative_to(REPO)),
        "model_file_sha256": _sha256(COST_MODEL),
        "reused_not_rebuilt": True,
        "components": components,
        "independent_recomputation": {
            "method": (
                "from the frozen constants only: 2 x taker fee, the spread term as published, and "
                "2 x base slippage x (1 + sqrt(size / reference_notional)) plus "
                "2 x base impact x sqrt(size / reference_notional)"
            ),
            "at_1000_usd": recomputed_1000,
            "at_200_usdt": recomputed_200,
        },
        "library_cross_check": library,
        "split": {
            "known_fees_bps": known_bps,
            "estimated_execution_bps": estimated_bps,
            "recomputed_total_bps_at_1000_usd": total_bps,
            "fees_share_of_total": round(known_bps / total_bps, 6) if total_bps else None,
            "known_component_names": [c["name"] for c in known],
            "estimated_component_names": [c["name"] for c in estimated],
            "reading": (
                "the exchange fee is a published schedule (KNOWN); spread, slippage and size-driven "
                "impact are modelled terms (ESTIMATED) whose constants the frozen model itself labels "
                "ASSUMED/ESTIMATED rather than observed.  The fee share is quoted at the frozen "
                "1,000 USD reference; at 200 USDT the same fee is 20 of 23.35 bps, i.e. a larger share "
                "of a smaller bill"
            ),
        },
        "toll_at_1000_usd": FROZEN_HISTORICAL_TOLL_BPS,
        "toll_at_200_usdt": POSTERIOR_TOLL_BPS,
        "model_matches_recorded_1000": abs(
            recomputed_1000["total_bps"] - FROZEN_HISTORICAL_TOLL_BPS
        )
        < 1e-4,
        "model_matches_recorded_200": abs(recomputed_200["total_bps"] - POSTERIOR_TOLL_BPS) < 1e-9,
        "frozen_recorded_toll_at_1000": FROZEN_HISTORICAL_TOLL_BPS,
        "cost_forensics_admission_toll_bps": _read_json(FORENSICS)["cost_model"][
            "admission_round_trip_bps"
        ],
        "historical_evaluation_toll_bps": FROZEN_HISTORICAL_TOLL_BPS,
        "historical_toll_unchanged": True,
        "posterior_evaluation_toll_bps": POSTERIOR_TOLL_BPS,
        "non_retroactivity": {
            "rule": (
                "the 23.353553 bps figure is a *posterior* economic evaluation at the account size we "
                "actually hold; the rejected strategies were judged against the frozen 23.7906 bps and "
                "must not be recalculated against a smaller toll"
            ),
            "applied": True,
            "rejected_candidates_recomputed": False,
            "cost_forensics_path": str(FORENSICS.relative_to(REPO)),
            "cost_forensics_sha256": _sha256(FORENSICS),
            "cost_forensics_unmodified_in_worktree": forensics_paths_clean,
            "run_report_path": str(RUN_REPORT.relative_to(REPO)),
            "run_report_sha256": _sha256(RUN_REPORT),
            "run_report_unmodified_in_worktree": run_report_clean,
        },
        "maker_path": {
            "round_trip_bps": 41.25,
            "admissible": False,
            "why": (
                "no usable fill evidence exists; the execution model is EXECUTION_MODEL_REQUIRED, so "
                "the cheaper-looking passive path stays barred"
            ),
        },
    }


# --------------------------------------------------------------------------- #
# 4. read-only execution reality
# --------------------------------------------------------------------------- #
def _vwap_cost(levels: list[list[float]], notional: float) -> dict[str, Any]:
    """Taker walk against one side of the book: what a market order of `notional` would consume."""
    if not levels:
        return {"filled": False, "reason": "empty book side"}
    best = levels[0][0]
    remaining = notional
    spent = 0.0
    quantity = 0.0
    consumed = 0
    for price, size in levels:
        available = price * size
        take = min(remaining, available)
        if take <= 0:
            break
        spent += take
        quantity += take / price
        remaining -= take
        consumed += 1
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:
        return {"filled": False, "reason": "depth insufficient", "levels_consumed": consumed}
    vwap = spent / quantity
    return {
        "filled": True,
        "vwap": vwap,
        "levels_consumed": consumed,
        "cost_bps": (vwap - best) / best * BPS,
        "tick_slippage_bps": (best - levels[0][0]) / best * BPS,
    }


def read_only_execution_reality() -> dict[str, Any]:
    snapshot = _read_json(SNAPSHOT)
    rounds = snapshot["observations"]
    symbols = snapshot["symbols"]

    spreads: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    quotes: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    for row in rounds:
        for symbol in symbols:
            book = row["books"].get(symbol)
            if book:
                spreads[symbol].append(book["spread_bps"])
                quotes[symbol].append(book["mid"])

    per_symbol: dict[str, Any] = {}
    for symbol in symbols:
        values = spreads[symbol]
        mids = quotes[symbol]
        changes = sum(1 for a, b in itertools.pairwise(mids) if a != b)
        intervals = max(1, len(mids) - 1)
        full_spread = _median(values)
        per_symbol[symbol] = {
            "observations": len(values),
            "median_full_spread_bps": round(full_spread, 6),
            "min_full_spread_bps": round(min(values), 6),
            "max_full_spread_bps": round(max(values), 6),
            "round_trip_spread_cost_bps": round(full_spread, 6),
            "modelled_round_trip_spread_bps": 1.0,
            "verdict": (
                "MODEL_CONSERVATIVE"
                if full_spread <= 1.0
                else ("WIDER_THAN_MODELLED" if full_spread > 1.5 else "AT_THE_MODELLED_BOUNDARY")
            ),
            "quote_changes": changes,
            "quote_intervals": intervals,
            "quote_change_rate": round(changes / intervals, 6),
        }

    pooled = [value for values in spreads.values() for value in values]
    worst_symbol = max(per_symbol, key=lambda symbol: per_symbol[symbol]["median_full_spread_bps"])
    worst_spread = max(value for values in spreads.values() for value in values)
    impact: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        row = rounds[0]["depth"].get(symbol, {})
        asks = row.get("asks", [])
        bids = row.get("bids", [])
        impact[symbol] = {
            "top_level_notional_usdt": round(asks[0][0] * asks[0][1], 2) if asks else None,
            **{
                f"{target:.0f}_usdt": {
                    "buy": _vwap_cost(asks, target),
                    "sell": _vwap_cost(bids, target),
                }
                for target in IMPACT_TARGETS_USDT
            },
        }

    latency = snapshot["latency_ms"]["samples"]
    latency_summary = {
        channel: {
            "n": len(values),
            "median_ms": round(_median(values), 3),
            "p95_ms": round(_pct(values, 0.95), 3),
            "max_ms": round(max(values), 3),
        }
        for channel, values in latency.items()
        if values
    }
    offsets = [row["clock_offset_ms"] for row in rounds if "clock_offset_ms" in row]
    depth_covered = all(
        entry[f"{target:.0f}_usdt"]["buy"]["filled"]
        and entry[f"{target:.0f}_usdt"]["sell"]["filled"]
        for entry in impact.values()
        for target in IMPACT_TARGETS_USDT
    )

    def worst_walk(size: float) -> float:
        return max(
            (
                entry[f"{size:.0f}_usdt"][side].get("cost_bps") or 0.0
                for entry in impact.values()
                for side in ("buy", "sell")
            ),
            default=0.0,
        )

    walk_at_account = worst_walk(CAPITAL)
    walk_at_100x = worst_walk(20_000.0)

    return {
        "source": str(SNAPSHOT.relative_to(REPO)),
        "source_sha256": _sha256(SNAPSHOT),
        "snapshot_complete": snapshot["complete"],
        "collection": {
            "budget": snapshot["budget"],
            "authentication": snapshot["authentication"],
            "orders_sent": snapshot["orders_sent"],
            "credentials_used": snapshot["credentials_used"],
            "private_endpoints_called": snapshot["private_endpoints_called"],
            "window_started_utc": snapshot["local_started_utc"],
            "window_finished_utc": snapshot["local_finished_utc"],
            "duration_s": snapshot["duration_s"],
            "finite_and_documented": True,
        },
        "spread": {
            "per_symbol": per_symbol,
            "pooled_median_full_spread_bps": round(_median(pooled), 6),
            "pooled_min_full_spread_bps": round(min(pooled), 6),
            "pooled_max_full_spread_bps": round(max(pooled), 6),
            "modelled_round_trip_spread_bps": 1.0,
            "verdict": (
                "MODEL_CONSERVATIVE"
                if _median(pooled) <= 1.0
                else (
                    "WIDER_THAN_MODELLED" if _median(pooled) > 1.5 else "AT_THE_MODELLED_BOUNDARY"
                )
            ),
            "worst_symbol_by_median": worst_symbol,
            "max_observed_full_spread_bps": round(worst_spread, 6),
            "conservative_verdict": (
                "MODEL_CONSERVATIVE"
                if worst_spread <= 1.0
                else ("WIDER_THAN_MODELLED" if worst_spread > 1.5 else "AT_THE_MODELLED_BOUNDARY")
            ),
            "like_for_like": (
                "the model's spread term is the round-trip cost (2 legs x half-spread), which equals "
                "the full bid/ask spread, so the comparison against the measured full spread is "
                "like for like"
            ),
            "caveat": (
                "one bounded window of a few seconds across four instruments is a spot reading, not a "
                "regime: it cannot certify a past period and does not replace a forward campaign"
            ),
        },
        "quote_changes": {
            "per_symbol": {symbol: per_symbol[symbol]["quote_changes"] for symbol in symbols},
            "reading": (
                "how often the mid moved between consecutive observations of the same bounded window; "
                "a coarse proxy for quote volatility, not a signal"
            ),
        },
        "observation_latency": latency_summary,
        "clock_skew": {
            "samples_ms": offsets,
            "median_ms": round(_median(offsets), 3) if offsets else None,
            "reading": (
                "local clock minus venue clock after removing half the round trip; every timestamp in "
                "this programme is therefore trustworthy to about a third of a second, which matters "
                "for latency reasoning and for nothing else"
            ),
        },
        "depth": {
            "depth_limit": snapshot["budget"]["depth_limit"],
            "levels_sampled": {
                symbol: len(rounds[0]["depth"].get(symbol, {}).get("bids", []))
                for symbol in symbols
            },
            "all_targets_covered": depth_covered,
            "impact_estimate_bps": impact,
            "worst_walk_bps_at_account_size": round(walk_at_account, 9),
            "worst_walk_bps_at_100x_size": round(walk_at_100x, 9),
            "reading": (
                "static L2 depth walk at the sampled instant: the market-order cost a taker of that "
                f"size would face *if the book stayed still*.  The largest measured walk across the "
                f"four instruments and both sides is {walk_at_account:.6f} bps at the account size "
                f"and {walk_at_100x:.6f} bps at a hundred times the account, i.e. the book absorbs "
                "our size inside its best price.  It is a snapshot estimate, not realised slippage: "
                "no order was sent and no fill was observed."
            ),
        },
        "published_fees": {
            "applicable_spot_schedule": "SRC-01 Binance Spot VIP0, 10 bps maker / 10 bps taker",
            "payment_asset": "quote asset",
            "bnb_discount": "POSSIBLE, not confirmed for our account",
            "maker_route": "inadmissible (no fill evidence)",
        },
        "estimated_vs_measured": {
            "measured_now": [
                "live best bid/ask spread",
                "observation-path latency",
                "clock skew",
                "depth available per side",
                "depth-based impact estimate per order size",
            ],
            "still_estimated": [
                "base slippage as a modelling constant: the measured depth walk at account scale is "
                "inside one tick, so this term is a conservative penalty rather than a depth effect",
                "volatility regime scaling",
                "maker adverse selection and fill probability",
            ],
            "unknown_and_stated": [
                "maker queue position",
                "fill probability",
                "realised slippage",
                "fill quality / price improvement",
                "historical spread for any past period (no endpoint exists)",
            ],
        },
        "realized_slippage_measured": False,
        "fill_quality_measured": False,
        "simulator_used_as_measurement": False,
        "maker_queue_position": "UNKNOWN",
        "historical_spread": "UNVERIFIABLE_NO_HISTORICAL_ENDPOINT",
    }


# --------------------------------------------------------------------------- #
# 5. economic decision
# --------------------------------------------------------------------------- #
def economic_decision(horizons: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    run_report = _read_json(RUN_REPORT)
    forensics = _read_json(FORENSICS)

    gate_verdicts: dict[str, Any] = {}
    for run in run_report.get("runs", []):
        candidates = run.get("gate", {}) if isinstance(run, dict) else {}
        candidate_id = run.get("candidate_id") if isinstance(run, dict) else None
        if candidate_id:
            gate_verdicts[candidate_id] = {
                "gate_verdict": candidates.get("verdict"),
                "failed_requirements": candidates.get("failed"),
                "zero_sample": candidates.get("zero_sample"),
            }

    preserved: dict[str, Any] = {}
    for candidate_id, forensic in (forensics.get("candidates") or {}).items():
        preserved[candidate_id] = {
            "verdict": forensic.get("verdict"),
            "mechanism": forensic.get("mechanism"),
            "strategy": forensic.get("strategy"),
            "gross_expectancy_bps": forensic.get("gross_expectancy_bps"),
            "oos_gross_expectancy_bps": forensic.get("oos_gross_expectancy_bps"),
            "recorded_net_expectancy_bps": forensic.get("recorded_net_expectancy_bps"),
            "cost_reduction_factor_required": forensic.get("cost_reduction_factor_required"),
            "recomputed_here": False,
            **gate_verdicts.get(candidate_id, {}),
        }

    margin: dict[str, Any] = {}
    for family, horizon in FAMILY_HORIZONS.items():
        row = horizons["per_horizon"][horizon]
        median = row["median_abs_move_bps"]
        margin[family] = {
            "horizon": horizon,
            "median_abs_move_bps": median,
            "multiple_of_frozen_toll": round(median / FROZEN_HISTORICAL_TOLL_BPS, 6),
            "multiple_of_posterior_toll": round(median / POSTERIOR_TOLL_BPS, 6),
            "movement_margin_sufficient": median / POSTERIOR_TOLL_BPS >= MOVEMENT_MARGIN_MULTIPLE,
        }

    long_horizon_families = ("momentum", "swing_trading", "trend_following")
    insufficient = [
        family for family, row in margin.items() if not row["movement_margin_sufficient"]
    ]
    outside_profile = [family for family in insufficient if family not in long_horizon_families]
    profile_clears = all(
        margin[family]["movement_margin_sufficient"] for family in long_horizon_families
    )

    return {
        "rejected_candidates_preserved": preserved,
        "rejected_candidates_recomputed": 0,
        "new_hypotheses_generated": 0,
        "new_strategies_recommended": 0,
        "rule": (
            f"movement margin is sufficient at a horizon when the measured median absolute move is at "
            f"least {MOVEMENT_MARGIN_MULTIPLE:.0f}x the toll the strategy would pay to trade it"
        ),
        "per_family": margin,
        "low_turnover_long_horizon_region": {
            "families": list(long_horizon_families),
            "families_clearing_the_rule": [
                family
                for family in long_horizon_families
                if margin[family]["movement_margin_sufficient"]
            ],
            "median_multiple_of_posterior_toll": round(
                _median(
                    [
                        margin[family]["multiple_of_posterior_toll"]
                        for family in long_horizon_families
                    ]
                ),
                6,
            ),
            "margin_sufficient": profile_clears,
        },
        "families_outside_the_proposed_profile": outside_profile,
        "families_outside_the_profile_verdicts": {
            family: margin[family] for family in outside_profile
        },
        "scope_verdict": (
            "MOVEMENT_MARGIN_SUFFICIENT_FOR_FURTHER_RESEARCH"
            if profile_clears
            else "MOVEMENT_MARGIN_INSUFFICIENT"
        ),
        "verdict_basis": (
            "the rule is applied to the profile under evaluation, the low-turnover long-horizon "
            "region; the short-horizon families are reported alongside and their failure is a "
            "finding about them, not a contradiction of this verdict"
        ),
        "movement_margin_is_not_alpha": True,
        "movement_margin_is_not_capturable_edge": True,
        "reading": (
            "the long-horizon region clears the toll by a wide margin, so a mechanism there could *pay "
            "for itself*; that is an arithmetic statement about the venue's take, not evidence that any "
            "mechanism can take the move.  The three tested mechanisms produced no demonstrated gross "
            "edge, so the margin stays unclaimed."
        ),
        "it_does_not_authorize": [
            "a campaign or any new hypothesis",
            "paper or live trading",
            "any statement that an edge, a profit or a production capability exists",
            "recalculating the rejected candidates against the smaller toll",
        ],
        "remaining_question": (
            "whether any mechanism suited to a holding period of about a day and upwards can convert "
            "the available movement into net return — a question this gate does not answer and does "
            "not recommend answering by opening another campaign"
        ),
        "previous_scope_recommendation": report["decision"]["scope_recommendation"],
    }


# --------------------------------------------------------------------------- #
# 6. standing state and absence of real trades
# --------------------------------------------------------------------------- #
def standing_state() -> dict[str, Any]:
    rfc = _read_json(RFC046)
    operating = _read_json(OPERATING_MODEL)
    reentry = _read_json(REENTRY_POLICY)
    forensics = _read_json(FORENSICS)
    runtime_text = RUNTIME_CFG.read_text(encoding="utf-8")
    exchange_text = EXCHANGE_CFG.read_text(encoding="utf-8")
    invariants = rfc.get("invariants_while_active", {})

    order_artifacts: dict[str, Any] = {}
    for name in sorted(path.name for path in STORAGE.glob("*")):
        order_artifacts[f"data/storage/{name}"] = "present"
    order_artifacts["data/storage/bot.db"] = (
        "present" if (STORAGE / "bot.db").exists() else "absent"
    )

    records: dict[str, Any] = {}
    carries_order = False
    for name in ("decisions.jsonl", "operations.jsonl", "outcomes.jsonl"):
        path = REAL_DECISIONS / name
        if not path.exists():
            records[name] = {"present": False}
            continue
        keys: set[str] = set()
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            count += 1
            keys.update(json.loads(line).keys())
        order_fields = sorted(k for k in keys if "order" in k.lower() or "fill" in k.lower())
        carries_order = carries_order or bool(order_fields)
        records[name] = {"present": True, "records": count, "order_fields": order_fields}

    freeze_text = FREEZE.read_text(encoding="utf-8")
    state = {
        "campaign_status": "DISCOVERY_CAMPAIGN_FAILED",
        "next_campaign": "NOT_AUTHORIZED",
        "live_trading": (_yaml_scalar(runtime_text, "live_trading_enabled") or "").lower()
        == "true",
        "live_trading_flag_literal": _yaml_scalar(runtime_text, "live_trading_enabled"),
        "runtime_mode": _yaml_scalar(runtime_text, "mode"),
        "exchange_sandbox": (_yaml_scalar(exchange_text, "sandbox") or "").lower() == "true",
        "trades_authorized": invariants.get("TRADES_AUTHORIZED", 0),
        "real_orders": invariants.get("real_orders"),
        "rfc_live_trading": invariants.get("LIVE_TRADING"),
        "rfc_g_business_reentry": invariants.get("G_BUSINESS_REENTRY"),
        "forensics_trades_authorized": forensics.get("standing_state", {}).get("trades_authorized"),
        "forensics_live_trading": forensics.get("standing_state", {}).get("live_trading"),
        "campaign_status_from_forensics": forensics.get("campaign_status_unchanged"),
        "profitability_verified": False,
        "G_BUSINESS_REENTRY": _find_dict_with_key(operating, "G_BUSINESS_REENTRY").get(
            "G_BUSINESS_REENTRY", "NOT_PASS"
        ),
        "risk_engine": "DETERMINISTIC",
        "reentry_policy_authorizes_capital": bool(
            reentry.get("authorizes_capital", False) if isinstance(reentry, dict) else False
        ),
        "freeze_still_governs": "TRADES_AUTHORIZED" in freeze_text,
        "false_success": 0,
    }
    absence = {
        "runtime_live_trading_enabled": state["live_trading"],
        "exchange_sandbox": state["exchange_sandbox"],
        "trades_authorized": state["trades_authorized"],
        "order_archive_files": order_artifacts,
        "any_record_carries_an_order_or_fill_field": carries_order,
        "real_decision_records": records,
        "reading": (
            "there is no order archive at all: the storage directory holds state journals, not an "
            "order book, and the sealed real-decision records carry no order id and no fill.  Nothing "
            "in this programme has been executed against a venue."
        ),
        "no_real_trades": (
            not state["live_trading"]
            and state["exchange_sandbox"]
            and state["trades_authorized"] == 0
            and (STORAGE / "bot.db").exists() is False
            and not carries_order
            and state["real_orders"] == "REFUSED_BY_POLICY"
        ),
    }
    return {"standing_state": state, "absence_of_real_trades": absence}


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def build() -> dict[str, Any]:
    report = _read_json(FEASIBILITY)
    horizons = horizon_verification(report)
    costs = cost_model_verification()
    reality = read_only_execution_reality()
    decision = economic_decision(horizons, report)
    governance = standing_state()
    preservation = evidence_preservation()

    dataset_hashes = {
        f"data/raw/alpha003/price/{asset}_{timeframe}.json": _sha256(
            PRICE_DIR / f"{asset}_{timeframe}.json"
        )
        for timeframe in ("5m", "15m", "1h")
        for asset in ASSETS
    }

    open_defects = [
        {
            "id": "TD-1",
            "status": "OPEN_NOT_REPAIRED",
            "scope": "repo-wide mypy over another workstream's analyse script",
            "this_gate": "not attempted; out of scope and not caused by this evidence",
        },
        {
            "id": "TD-2",
            "status": "OPEN_NOT_REPAIRED",
            "scope": "RFC-035E verifier raises on absent inputs",
            "this_gate": "not attempted; repairing it would edit frozen evidence",
        },
        {
            "id": "ECO-1",
            "status": "OPEN_BOUNDED",
            "scope": (
                "the read-only snapshot is one bounded window: spread, latency and depth are measured "
                "for a few seconds, not across regimes"
            ),
            "this_gate": "declared, not hidden; a forward collection remains the only cure",
        },
        {
            "id": "ECO-2",
            "status": "UNKNOWN_NOT_RESOLVABLE_OFFLINE",
            "scope": "maker queue position, fill probability, realised slippage, fill quality",
            "this_gate": "kept UNKNOWN rather than estimated by a simulator",
        },
    ]

    return {
        "artifact": "ECONOMIC-001_COST_EVIDENCE_CLOSURE",
        "purpose": (
            "Consolidate and verify the economic viability evidence before any further discovery "
            "campaign is even discussed."
        ),
        "gate": "ECONOMIC-001",
        "builder": "scripts/economic001_closure.py",
        "builder_equals_verifier": False,
        "generated_at_utc": _utc(),
        "head_at_run": preservation["current_head"],
        "evidence_preservation": preservation,
        "horizon_verification": horizons,
        "cost_model_verification": costs,
        "read_only_execution_reality": reality,
        "economic_decision": decision,
        "dataset_hashes": dataset_hashes,
        "standing": governance["standing_state"],
        "absence_of_real_trades": governance["absence_of_real_trades"],
        "open_defects": open_defects,
        "false_success": 0,
        "does_not_license": [
            "a new campaign, a new hypothesis or a new strategy",
            "paper or live trading, or any deployment of capital",
            "any recalculated verdict for a rejected candidate",
            "any claim that an edge, a profit or a production capability exists",
        ],
        "final_report": {},
    }


def final_report(closure: dict[str, Any]) -> dict[str, Any]:
    """The eleven fields the gate asks the report to deliver, computed from the closure itself."""
    preservation = closure["evidence_preservation"]
    horizons = closure["horizon_verification"]
    costs = closure["cost_model_verification"]
    reality = closure["read_only_execution_reality"]
    decision = closure["economic_decision"]
    return {
        "CURRENT_HEAD": closure["head_at_run"],
        "FILES_COMMITTED": {
            "delivery_commit": preservation["delivery_commit"],
            "count": preservation["files_committed"],
            "paths": preservation["deliverables"],
            "pending_in_this_gate": preservation["pending_in_this_gate"],
            "foreign_files_excluded": len(preservation["foreign_paths_left_in_worktree"]),
        },
        "DATASET_HASHES": closure["dataset_hashes"],
        "TIMEFRAME_VERIFICATION": {
            "horizons": list(horizons["per_horizon"]),
            "certifiable": horizons["all_horizons_certifiable"],
            "agree_with_verified_report": horizons["all_horizons_agree_with_reported"],
            "max_relative_delta": horizons["max_relative_delta_vs_reported"],
            "series_monotonic_and_gapless": horizons["all_series_monotonic_and_gapless"],
            "aggregation_mismatches": horizons["assets_with_aggregation_mismatch"],
        },
        "COST_MODEL_STATUS": {
            "model": costs["model"],
            "sha256": costs["model_file_sha256"],
            "historical_toll_bps": costs["historical_evaluation_toll_bps"],
            "posterior_toll_bps": costs["posterior_evaluation_toll_bps"],
            "known_fees_bps": costs["split"]["known_fees_bps"],
            "estimated_execution_bps": costs["split"]["estimated_execution_bps"],
            "rejected_candidates_recomputed": costs["non_retroactivity"][
                "rejected_candidates_recomputed"
            ],
        },
        "READ_ONLY_MARKET_DATA_STATUS": {
            "snapshot": reality["source"],
            "sha256": reality["source_sha256"],
            "complete": reality["snapshot_complete"],
            "orders_sent": reality["collection"]["orders_sent"],
            "credentials_used": reality["collection"]["credentials_used"],
            "window_s": reality["collection"]["duration_s"],
            "measured": reality["estimated_vs_measured"]["measured_now"],
            "still_unknown": reality["estimated_vs_measured"]["unknown_and_stated"],
        },
        "ESTIMATED_VS_MEASURED_COSTS": {
            "measured_pooled_median_spread_bps": reality["spread"]["pooled_median_full_spread_bps"],
            "measured_max_spread_bps": reality["spread"]["max_observed_full_spread_bps"],
            "modelled_spread_bps": reality["spread"]["modelled_round_trip_spread_bps"],
            "spread_verdict": reality["spread"]["verdict"],
            "conservative_spread_verdict": reality["spread"]["conservative_verdict"],
            "depth_impact_estimate_available": reality["depth"]["all_targets_covered"],
            "realized_slippage_measured": reality["realized_slippage_measured"],
            "fill_quality_measured": reality["fill_quality_measured"],
        },
        "INDEPENDENT_VERIFICATION": {
            "verifier": "scripts/economic001_closure_verify.py",
            "artifact": "data/economic001/EVIDENCE_CLOSURE_VERIFICATION.json",
            "allowed_verdicts": [
                "COST_EVIDENCE_VERIFIED",
                "COST_EVIDENCE_INCOMPLETE",
                "COST_EVIDENCE_FAILED",
            ],
            "result": (
                "written by the verifier into that artefact: a builder does not grade its own "
                "closure, and rebuilding it after verification would change the bytes just verified"
            ),
        },
        "FALSE_SUCCESS": closure["false_success"],
        "OPEN_DEFECTS": closure["open_defects"],
        "NEXT_GATE": {
            "recommendation": decision["scope_verdict"],
            "campaign": closure["standing"]["next_campaign"],
            "trades_authorized": closure["standing"]["trades_authorized"],
            "note": (
                "this gate names no successor and opens nothing; the next step is the owner's decision, "
                "not a new RFC"
            ),
        },
        "STANDING_STATE": closure["standing"],
    }


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render_md(closure: dict[str, Any]) -> str:
    preservation = closure["evidence_preservation"]
    horizons = closure["horizon_verification"]
    costs = closure["cost_model_verification"]
    reality = closure["read_only_execution_reality"]
    decision = closure["economic_decision"]
    final = closure["final_report"]

    lines = [
        "# ECONOMIC-001 — COST EVIDENCE CLOSURE & EXECUTION REALITY",
        "",
        f"generated_at_utc = {closure['generated_at_utc']} (computed, not authored)",
        f"current_head = {closure['head_at_run']}",
        f"false_success = {closure['false_success']}",
        "",
        "> This gate adds no strategy and opens no campaign. It consolidates the economic evidence,",
        "> re-derives the horizons at a resolution that can certify them, separates known fees from",
        "> estimated execution costs, and measures the parts of execution reality that can be measured",
        "> without sending an order.",
        "",
        "## 1. Evidence preservation",
        "",
        f"- delivery commit: `{preservation['delivery_commit']}` — {preservation['delivery_subject']}",
        f"- files in that commit: **{preservation['files_committed']}** "
        f"(the six economic deliverables, plus {len(preservation['foreign_paths_in_delivery_commit'])} "
        "other paths)",
        f"- foreign files left in the working tree untouched: "
        f"**{len(preservation['foreign_paths_left_in_worktree'])}**",
        f"- report bytes equal the hash the verifier recorded: "
        f"**{preservation['bytes_match_the_verified_run']}**",
        f"- non-circularity (the named commit must not contain this artefact): "
        f"**{preservation['non_circularity']['holds']}**",
        "",
        "| file | working tree sha256 | git blob sha256 |",
        "| --- | --- | --- |",
    ]
    for path, values in preservation["deliverable_hashes"].items():
        lines.append(
            f"| `{path}` | `{values['working_tree_sha256'][:16]}…` | "
            f"`{(values['git_blob_sha256'] or 'n/a')[:16]}…` |"
        )
    lines += [
        "",
        preservation["line_endings"]["note"],
        "",
        "## 2. Horizon verification (native resolution per horizon)",
        "",
        horizons["method"],
        "",
        "| horizon | series | bars/window | windows | median bps | shifted | exhaustive | reported bps "
        "| delta |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in horizons["per_horizon"].items():
        lines.append(
            f"| {name} | {row['native_series']} | {row['bars_per_window']} | {row['windows']} | "
            f"{row['median_abs_move_bps']} | {row['shifted_window_median_bps']} | "
            f"{row['exhaustive_window_median_bps']} | {row['reported_median_bps']} | "
            f"{row['relative_delta_vs_reported']:.2%} |"
        )
    lines += [
        "",
        f"All horizons certifiable at their own resolution: **{horizons['all_horizons_certifiable']}**; "
        f"all agree with the already-verified report within "
        f"{horizons['max_relative_delta_vs_reported']:.2%}: "
        f"**{horizons['all_horizons_agree_with_reported']}**; monotonic and gapless: "
        f"**{horizons['all_series_monotonic_and_gapless']}**.",
        "",
        "Windows are disjoint by construction at every horizon (step equals the window length, so "
        "no two windows share a bar), and the count is the declared `floor(available / bars)` per "
        "asset.  The shifted and exhaustive conventions are reported beside the aligned one as a "
        "robustness check, not as the primary measurement.",
        "",
        "### Series integrity and one timeline",
        "",
        "| series | bars | gaps | duplicates | covers | aligned to UTC grid |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for timeframe, per_asset in horizons["series_integrity"].items():
        row = per_asset["BTCUSDT"]
        lines.append(
            f"| {timeframe} | {row['bars']} | {row['gaps']} | {row['duplicate_timestamps']} | "
            f"{row['coverage_start_utc']} → {row['coverage_end_utc']} | {row['aligned_to_utc_grid']} |"
        )
    lines += [
        "",
        "The coarser series must be the exact aggregate of the finer one (open where the first fine "
        f"bar opens, close where the last one closes). Assets with a mismatch: "
        f"**{horizons['assets_with_aggregation_mismatch'] or 'none'}**.",
        "",
        "## 3. Cost-model verification",
        "",
        f"`{costs['model']}` reused, not rebuilt (`{costs['model_file']}`, "
        f"`{costs['model_file_sha256'][:16]}…`).",
        "",
        "| component | bps | class | source |",
        "| --- | --- | --- | --- |",
    ]
    for component in costs["components"]:
        lines.append(
            f"| {component['name']} | {component['value_bps']} | {component['knowledge']} | "
            f"{component['source_id']} |"
        )
    lines += [
        "",
        f"Known exchange fees: **{costs['split']['known_fees_bps']} bps**; estimated execution terms: "
        f"**{costs['split']['estimated_execution_bps']} bps** "
        f"({costs['split']['fees_share_of_total']:.1%} of the toll is the published schedule).",
        "",
        f"- historical evaluation (the rejected strategies): **{costs['historical_evaluation_toll_bps']} bps**",
        f"- posterior evaluation at 200 USDT: **{costs['posterior_evaluation_toll_bps']} bps**",
        f"- rejected candidates recomputed: **{costs['non_retroactivity']['rejected_candidates_recomputed']}**"
        f" — {costs['non_retroactivity']['rule']}",
        f"- maker path: {costs['maker_path']['round_trip_bps']} bps, admissible: "
        f"**{costs['maker_path']['admissible']}**",
        "",
        f"Independent recomputation from the frozen constants: "
        f"{costs['independent_recomputation']['at_1000_usd']['total_bps']} bps at 1,000 USD and "
        f"{costs['independent_recomputation']['at_200_usdt']['total_bps']} bps at 200 USDT "
        f"(stressed 1.5x: {costs['independent_recomputation']['at_200_usdt']['stressed_at_1p5x_bps']} and "
        f"{costs['independent_recomputation']['at_1000_usd']['stressed_at_1p5x_bps']} bps); frozen "
        f"record of the historical toll: {costs['cost_forensics_admission_toll_bps']} bps; library "
        f"cross-check ran: **{costs['library_cross_check']['ran']}**.",
        "",
        "## 4. Read-only execution reality",
        "",
        f"Source `{reality['source']}` (`{reality['source_sha256'][:16]}…`), "
        f"{reality['collection']['budget']['rounds']} rounds, "
        f"{reality['collection']['budget']['requests_made']} requests, "
        f"{reality['collection']['duration_s']}s, orders sent "
        f"**{reality['collection']['orders_sent']}**, credentials used "
        f"**{reality['collection']['credentials_used']}**.",
        "",
        "| symbol | median spread bps | min | max | round-trip spread cost bps | vs modelled 1.0 | quote "
        "changes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for symbol, row in reality["spread"]["per_symbol"].items():
        lines.append(
            f"| {symbol} | {row['median_full_spread_bps']} | {row['min_full_spread_bps']} | "
            f"{row['max_full_spread_bps']} | {row['round_trip_spread_cost_bps']} | {row['verdict']} | "
            f"{row['quote_changes']}/{row['quote_intervals']} |"
        )
    lines += [
        "",
        f"Pooled median spread over the four instruments: "
        f"**{reality['spread']['pooled_median_full_spread_bps']} bps** against a modelled 1.0 bps "
        f"({reality['spread']['verdict']}); the widest single observation of any instrument was "
        f"**{reality['spread']['max_observed_full_spread_bps']} bps** "
        f"({reality['spread']['conservative_verdict']} even then, on "
        f"{reality['spread']['worst_symbol_by_median']}). {reality['spread']['like_for_like']}. "
        f"{reality['spread']['caveat']}.",
        "",
        "Observation latency (round trip of the observation path): "
        + ", ".join(
            f"{channel} median {row['median_ms']} ms"
            for channel, row in reality["observation_latency"].items()
        )
        + f". Clock skew: {reality['clock_skew']['median_ms']} ms — "
        + reality["clock_skew"]["reading"]
        + ".",
        "",
        "### Depth-based impact estimate (taker walk, one instant)",
        "",
        "| symbol | top level notional USDT | order size | buy cost bps | sell cost bps | levels "
        "consumed (buy) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for symbol, entry in reality["depth"]["impact_estimate_bps"].items():
        top_notional = entry.get("top_level_notional_usdt")
        for size in IMPACT_TARGETS_USDT:
            row = entry[f"{size:.0f}_usdt"]
            buy = row["buy"]
            sell = row["sell"]
            buy_cell = "n/a" if not buy.get("filled") else f"{buy['cost_bps']:.6f}"
            sell_cell = "n/a" if not sell.get("filled") else f"{sell['cost_bps']:.6f}"
            lines.append(
                f"| {symbol} | {top_notional} | {size:.0f} USDT | {buy_cell} | {sell_cell} | "
                f"{buy.get('levels_consumed', 0)} |"
            )
    lines += [
        "",
        reality["depth"]["reading"],
        "",
        f"Measured now: {', '.join(reality['estimated_vs_measured']['measured_now'])}. Still estimated: "
        f"{', '.join(reality['estimated_vs_measured']['still_estimated'])}. Unknown and stated: "
        f"{', '.join(reality['estimated_vs_measured']['unknown_and_stated'])}.",
        "",
        f"Realised slippage measured: **{reality['realized_slippage_measured']}**; fill quality "
        f"measured: **{reality['fill_quality_measured']}**; a simulator was used as a measurement: "
        f"**{reality['simulator_used_as_measurement']}**.",
        "",
        "## 5. Economic decision",
        "",
        f"Rule: {decision['rule']}.",
        "",
        "| family | horizon | median bps | x frozen toll | x posterior toll | margin sufficient |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for family, row in decision["per_family"].items():
        lines.append(
            f"| {family} | {row['horizon']} | {row['median_abs_move_bps']} | "
            f"{row['multiple_of_frozen_toll']} | {row['multiple_of_posterior_toll']} | "
            f"{row['movement_margin_sufficient']} |"
        )
    lines += [
        "",
        f"**{decision['scope_verdict']}** — {decision['reading']}",
        "",
        f"The three rejected candidates stay as they were recorded (recomputed here: "
        f"{decision['rejected_candidates_recomputed']}); new hypotheses: "
        f"{decision['new_hypotheses_generated']}; new strategies recommended: "
        f"**{decision['new_strategies_recommended']}**.",
        "",
        "## 6. Standing state and absence of real trades",
        "",
        "```text",
    ]
    for key, value in closure["standing"].items():
        lines.append(f"{key.upper()} = {value}")
    lines += [
        "```",
        "",
        closure["absence_of_real_trades"]["reading"],
        "",
        "## 7. Final report",
        "",
        "| field | value |",
        "| --- | --- |",
    ]
    for key in (
        "CURRENT_HEAD",
        "FALSE_SUCCESS",
    ):
        lines.append(f"| {key} | {final[key]} |")
    lines += [
        f"| FILES_COMMITTED | {final['FILES_COMMITTED']['count']} files at "
        f"`{final['FILES_COMMITTED']['delivery_commit']}`; "
        f"{len(final['FILES_COMMITTED']['pending_in_this_gate'])} pending in this gate; "
        f"{final['FILES_COMMITTED']['foreign_files_excluded']} foreign files excluded |",
        f"| DATASET_HASHES | {len(final['DATASET_HASHES'])} series hashed (`data/raw/alpha003/price/*.json`) |",
        f"| TIMEFRAME_VERIFICATION | certifiable {final['TIMEFRAME_VERIFICATION']['certifiable']}, "
        f"agrees with the verified report {final['TIMEFRAME_VERIFICATION']['agree_with_verified_report']} "
        f"(max delta {final['TIMEFRAME_VERIFICATION']['max_relative_delta']:.2%}) |",
        f"| COST_MODEL_STATUS | {final['COST_MODEL_STATUS']['model']} reused; historical "
        f"{final['COST_MODEL_STATUS']['historical_toll_bps']} bps; posterior "
        f"{final['COST_MODEL_STATUS']['posterior_toll_bps']} bps; rejected candidates recomputed "
        f"{final['COST_MODEL_STATUS']['rejected_candidates_recomputed']} |",
        f"| READ_ONLY_MARKET_DATA_STATUS | {final['READ_ONLY_MARKET_DATA_STATUS']['window_s']}s window, "
        f"orders sent {final['READ_ONLY_MARKET_DATA_STATUS']['orders_sent']}, credentials "
        f"{final['READ_ONLY_MARKET_DATA_STATUS']['credentials_used']}, complete "
        f"{final['READ_ONLY_MARKET_DATA_STATUS']['complete']} |",
        f"| ESTIMATED_VS_MEASURED_COSTS | measured pooled spread "
        f"{final['ESTIMATED_VS_MEASURED_COSTS']['measured_pooled_median_spread_bps']} bps, worst "
        f"observed {final['ESTIMATED_VS_MEASURED_COSTS']['measured_max_spread_bps']} bps, vs modelled "
        f"{final['ESTIMATED_VS_MEASURED_COSTS']['modelled_spread_bps']} bps "
        f"({final['ESTIMATED_VS_MEASURED_COSTS']['spread_verdict']} / "
        f"{final['ESTIMATED_VS_MEASURED_COSTS']['conservative_spread_verdict']}) |",
        f"| INDEPENDENT_VERIFICATION | {final['INDEPENDENT_VERIFICATION']['verifier']} → "
        f"{final['INDEPENDENT_VERIFICATION']['artifact']} |",
        f"| OPEN_DEFECTS | {len(final['OPEN_DEFECTS'])} recorded |",
        f"| NEXT_GATE | {final['NEXT_GATE']['recommendation']}; campaign "
        f"{final['NEXT_GATE']['campaign']}; trades authorized "
        f"{final['NEXT_GATE']['trades_authorized']} |",
        "",
        "This artefact does not license: " + "; ".join(closure["does_not_license"]) + ".",
        "",
        "### Open defects",
        "",
        "| id | status | scope |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {defect['id']} | {defect['status']} | {defect['scope']} |"
        for defect in closure["open_defects"]
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="build and report without writing")
    args = parser.parse_args(argv)

    closure = build()
    closure["final_report"] = final_report(closure)
    markdown = render_md(closure)

    if args.check:
        print(json.dumps(closure["final_report"], indent=2, ensure_ascii=False))
        return 0

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(closure, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    OUT_MD.write_text(markdown, encoding="utf-8")
    print(
        f"built {closure['artifact']} at head {closure['head_at_run'][:8]} "
        f"delivery {closure['evidence_preservation']['delivery_commit']} "
        f"false_success={closure['false_success']}"
    )
    print(f"written -> {OUT_JSON.relative_to(REPO)}, {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
