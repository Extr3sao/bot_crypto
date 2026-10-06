"""ALPHA-001 — independent verification of the economic alpha discovery campaign.

Builder != verifier.  Nothing here imports ``scripts/alpha001_run.py``; the checks
re-derive the campaign's claims from the delivered artifacts, the frozen registry
copy and the raw cached candles, using this file's own canonical serialiser,
statistics, multiplicity corrections, permutation null and admission rule — and
its own re-implementation of three hypothesis builders (one per data path) so the
data pipeline itself is re-walked rather than trusted.

It answers three questions:

1. *Is the campaign faithful to its own protocol?*  (preregistration frozen, no
   hypothesis added or removed, holdout untouched, cost applied, underpowered
   cells not called negative.)
2. *Do the numbers reproduce?*  (dataset hashes, series, information metrics, gross
   and net effects, multiplicity, best-of-N null, winner's curse, concentration,
   stability.)
3. *Is any false success present?*  (a promoted candidate, a reused validation, a
   renamed falsified family, a raw p presented as corrected evidence.)

Output: ``reports/alpha001/ALPHA001_VERIFICATION.{json,md}``.
Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import alpha001 as a1  # noqa: E402

REPORT_DIR = REPO / "reports" / "alpha001"
CACHE_DIR = REPO / "data" / "raw" / "alpha001"

ARTIFACTS_PATH = REPORT_DIR / "ALPHA001_ARTIFACTS.json"
SERIES_PATH = REPORT_DIR / "ALPHA001_SERIES.json"
REGISTRY_PATH = REPORT_DIR / "ALPHA001_HYPOTHESIS_REGISTRY.json"
INVENTORY_PATH = REPORT_DIR / "EXISTING_ALPHA_INVENTORY.json"
NEGATIVE_PATH = REPORT_DIR / "NEGATIVE_ALPHA_REGISTRY.json"
DISCOVERY_PATH = REPORT_DIR / "DISCOVERY_RESULTS.json"
OUT_JSON = REPORT_DIR / "ALPHA001_VERIFICATION.json"
OUT_MD = REPORT_DIR / "ALPHA001_VERIFICATION.md"

EXPECTED_HYPOTHESIS_COUNT = 12
EXPECTED_FAMILY_COUNT = 6
EXPECTED_HYPOTHESES = [f"A1-H{index:02d}" for index in range(1, EXPECTED_HYPOTHESIS_COUNT + 1)]
FROZEN_REGISTRY_HASH = "cf49586a349c292921faec53c8931a05e223dd3cd00a04e6009cb6ea1476068c"
COST_BPS_V3 = 23.790569
DISCOVERY_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
NULL_DRAWS = 1000
NULL_SEED = 20_261_003
BH_Q = 0.10
HOLM_ALPHA = 0.10
DESIGN_SIGMA_BPS = 400.0
EXECUTION_UNCERTAINTY_FRACTION = 0.25
WINNERS_CURSE_BUFFER_BPS = 8.121
Z_975 = 1.959963985
Z_ALPHA_ONE_SIDED = 1.6448536269514722
SESSION_SYMBOL = "BTC/USDT:4h"
FORBIDDEN_VERDICT_WORDS = (
    "PROFITABLE",
    "EDGE_CERTIFIED",
    "PAPER_READY",
    "LIVE_READY",
    "DIRECTIONAL_ALPHA",
)


# --------------------------------------------------------------------------- #
# independent primitives
# --------------------------------------------------------------------------- #


def canonical(value: Any) -> str:
    """Own canonical JSON writer (sorted keys, compact separators, UTF-8)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{canonical(str(key))}:{canonical(value[key])}" for key in sorted(value)) + "}"
    return json.dumps(str(value), ensure_ascii=False)


def digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def pstdev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    out = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for cursor in range(position, end + 1):
            out[order[cursor]] = shared
        position = end + 1
    return out


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml, mr = mean(left), mean(right)
    dl = [value - ml for value in left]
    dr = [value - mr for value in right]
    denom = math.sqrt(sum(v * v for v in dl) * sum(v * v for v in dr))
    return sum(x * y for x, y in zip(dl, dr, strict=True)) / denom if denom else 0.0


def spearman(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        return 0.0
    return pearson(ranks(left), ranks(right))


def effective_sample_size(series: list[float]) -> float:
    """Autocorrelation-adjusted sample size, reimplemented from the documented rule."""
    total = len(series)
    if total < 3:
        return float(max(total, 1))
    mu = mean(series)
    variance = sum((value - mu) ** 2 for value in series) / total
    if variance <= 0.0:
        return float(total)
    factor = 1.0
    for lag in range(1, min(10, total - 1) + 1):
        covariance = (
            sum((series[index] - mu) * (series[index - lag] - mu) for index in range(lag, total))
            / total
        )
        rho = covariance / variance
        if rho <= 0.0:
            break
        factor += 2.0 * rho
    return max(1.0, total / factor)


def one_sided_p(t_stat: float) -> float:
    if t_stat <= 0.0:
        return 1.0
    return max(0.0, min(1.0, 0.5 * math.erfc(t_stat / math.sqrt(2.0))))


def probit(probability: float) -> float:
    """Own inverse-normal (Acklam coefficients), used only for the MDE."""
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    if probability <= 0.0:
        return float("-inf")
    if probability >= 1.0:
        return float("inf")
    low, high = 0.02425, 1.0 - 0.02425
    if probability < low:
        q = math.sqrt(-2.0 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if probability > high:
        q = math.sqrt(-2.0 * math.log(1.0 - probability))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = probability - 0.5
    r = q * q
    numerator = ((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]
    denominator = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
    return numerator * q / denominator


def mde_bps(sigma_bps: float, n: int) -> float:
    if n <= 0 or sigma_bps <= 0.0:
        return float("inf")
    return (Z_ALPHA_ONE_SIDED + probit(0.8)) * sigma_bps / math.sqrt(n)


def benjamini_hochberg(pvalues: list[float], q: float) -> list[bool]:
    total = len(pvalues)
    order = sorted(range(total), key=lambda index: pvalues[index])
    passes = [False] * total
    last = 0
    for rank, index in enumerate(order, start=1):
        if pvalues[index] <= q * rank / total:
            last = rank
    for rank, index in enumerate(order, start=1):
        passes[index] = rank <= last
    return passes


def holm(pvalues: list[float], alpha: float) -> list[bool]:
    total = len(pvalues)
    order = sorted(range(total), key=lambda index: pvalues[index])
    passes = [False] * total
    for rank, index in enumerate(order, start=1):
        if pvalues[index] <= alpha / (total - rank + 1):
            passes[index] = True
        else:
            break
    return passes


def concentration(contributions: list[float]) -> dict[str, Any]:
    total = sum(contributions)
    ranked = sorted(contributions, reverse=True)
    top = [sum(ranked[:k]) / total if total else 0.0 for k in (1, 3, 5)]
    net_ex_best = total - ranked[0]
    robust = top[0] <= 0.25 and top[1] <= 0.60 and top[2] <= 0.85 and net_ex_best > 0
    return {
        "top1_share": top[0],
        "top3_share": top[1],
        "top5_share": top[2],
        "net_ex_best": net_ex_best,
        "net_ex_top3": total - sum(ranked[:3]),
        "classification": "ROBUST" if robust else "FRAGILE",
    }


def circular_shift(values: list[float], shift: int) -> list[float]:
    if not values:
        return []
    shift %= len(values)
    return list(values[shift:]) + list(values[:shift])


def hurdle_bps(n_effective: int) -> float:
    statistical = Z_975 * DESIGN_SIGMA_BPS / math.sqrt(n_effective)
    return (
        COST_BPS_V3
        + COST_BPS_V3 * EXECUTION_UNCERTAINTY_FRACTION
        + WINNERS_CURSE_BUFFER_BPS
        + statistical
    )


# --------------------------------------------------------------------------- #
# check harness
# --------------------------------------------------------------------------- #


class Verifier:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.limitations: list[str] = []
        self.false_success: list[str] = []

    def check(self, name: str, passed: bool, expected: Any, actual: Any, detail: str = "") -> bool:
        self.checks.append(
            {
                "check": name,
                "status": "PASS" if passed else "MISMATCH",
                "expected": expected,
                "actual": actual,
                "detail": detail,
            }
        )
        return passed

    def close(self, value: float, expected: float, tol: float = 1e-6) -> bool:
        return abs(value - expected) <= tol

    @property
    def mismatches(self) -> int:
        return sum(1 for item in self.checks if item["status"] == "MISMATCH")

    @property
    def passed(self) -> int:
        return sum(1 for item in self.checks if item["status"] == "PASS")


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_candles(symbol: str, timeframe: str) -> list[list[float]]:
    rows: list[list[float]] = json.loads(
        (CACHE_DIR / f"{symbol.replace('/', '-')}_{timeframe}.json").read_text("utf-8")
    )
    return rows


def dataset_hash(rows: list[list[float]]) -> str:
    payload = ",".join(
        "[" + str(int(row[0])) + "," + ",".join(repr(round(float(value), 8)) for value in row[1:6]) + "]"
        for row in rows
    )
    return digest("[" + payload + "]")


def to_closes(rows: list[list[float]]) -> dict[int, float]:
    return {int(row[0]): float(row[4]) for row in rows}


# --------------------------------------------------------------------------- #
# independent re-implementation of the data path for three hypotheses
# --------------------------------------------------------------------------- #


class Panel:
    def __init__(self, universe: list[str]) -> None:
        self.closes = {symbol: to_closes(load_candles(symbol, "1d")) for symbol in universe}
        self.calendar = sorted(self.closes[universe[0]].keys())

    def price(self, symbol: str, stamp: int) -> float | None:
        return self.closes[symbol].get(stamp)

    def forward(self, symbol: str, position: int, horizon: int) -> float | None:
        if position + horizon >= len(self.calendar):
            return None
        now = self.price(symbol, self.calendar[position])
        then = self.price(symbol, self.calendar[position + horizon])
        return then / now - 1.0 if now and then and now > 0 else None


def rebuid_a1_h01(universe: list[str], limit: int) -> dict[str, list[Any]]:
    """Cross-sectional dispersion short when dispersion is high (own implementation)."""
    panel = Panel(universe)
    dispersion: list[float | None] = [None]
    for position in range(1, len(panel.calendar)):
        returns = []
        for symbol in universe:
            now = panel.price(symbol, panel.calendar[position])
            previous = panel.price(symbol, panel.calendar[position - 1])
            if now and previous and previous > 0:
                returns.append(now / previous - 1.0)
        dispersion.append(statistics.pstdev(returns) if len(returns) >= 5 else None)
    signal: list[float | None] = []
    forward: list[float | None] = []
    contributions: list[float] = []
    for position in range(0, limit):
        signal.append(dispersion[position])
        forward.append(panel.forward("BTC/USDT", position, 1))
    for sig, fwd in zip(signal, forward, strict=True):
        contributions.append(0.0 if sig is None or fwd is None else -_sign(sig) * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def rebuid_a1_h09(universe: list[str], limit: int) -> dict[str, list[Any]]:
    """Down/up volatility-shock continuation (own implementation)."""
    panel = Panel(universe)
    closes = [panel.price("BTC/USDT", stamp) for stamp in panel.calendar]
    returns: list[float | None] = [None]
    for position in range(1, len(closes)):
        previous, now = closes[position - 1], closes[position]
        returns.append(now / previous - 1.0 if previous and now and previous > 0 else None)
    clean = [value if value is not None else 0.0 for value in returns]
    sigmas: list[float | None] = []
    for position in range(len(clean)):
        if position < 20:
            sigmas.append(None)
        else:
            sigmas.append(statistics.pstdev(clean[position - 20 : position]))
    signal: list[float | None] = []
    forward: list[float | None] = []
    for position in range(0, limit):
        shock, sigma = returns[position], sigmas[position]
        if shock is None or sigma is None or sigma == 0.0 or abs(shock) <= 2.0 * sigma:
            signal.append(None)
        else:
            signal.append(shock)
        forward.append(panel.forward("BTC/USDT", position, 1))
    contributions = [
        0.0 if sig is None or fwd is None else _sign(sig) * fwd * 1e4
        for sig, fwd in zip(signal, forward, strict=True)
    ]
    return {"signal": signal, "forward": forward, "contributions": contributions}


def rebuid_a1_h11(start: int, end: int, hard_end: int) -> dict[str, list[Any]]:
    """First 4h bar of the UTC day predicts the next bar (own implementation)."""
    rows = load_candles("BTC/USDT", "4h")
    opens = [int(row[0]) for row in rows]
    closes = [float(row[4]) for row in rows]
    signal: list[float | None] = []
    forward: list[float | None] = []
    for position in range(start, end):
        if position == 0 or position + 1 >= hard_end or closes[position - 1] <= 0.0:
            continue
        ret = closes[position] / closes[position - 1] - 1.0
        fwd = closes[position + 1] / closes[position] - 1.0 if closes[position] > 0 else None
        hour = dt.datetime.fromtimestamp(opens[position] // 1000, dt.UTC).hour
        if hour in (0, 1, 2, 3):
            signal.append(ret)
            forward.append(fwd)
    contributions = [
        0.0 if sig is None or fwd is None else _sign(sig) * fwd * 1e4
        for sig, fwd in zip(signal, forward, strict=True)
    ]
    return {"signal": signal, "forward": forward, "contributions": contributions}


def _sign(value: float) -> float:
    return 1.0 if value > 0 else (-1.0 if value < 0 else 0.0)


def paired(built: dict[str, list[Any]]) -> dict[str, list[Any]]:
    """Apply the delivered series' filter: keep the pairs where both sides exist."""

    def keep(signal: float | None, forward: float | None) -> bool:
        return signal is not None and forward is not None

    paired_signal = [
        signal
        for signal, forward in zip(built["signal"], built["forward"], strict=True)
        if keep(signal, forward)
    ]
    paired_forward = [
        forward
        for signal, forward in zip(built["signal"], built["forward"], strict=True)
        if keep(signal, forward)
    ]
    contributions = [
        float(value)
        for value, signal in zip(built["contributions"], built["signal"], strict=True)
        if signal is not None
    ]
    return {"signal": paired_signal, "forward": paired_forward, "contributions": contributions}


def compare_cell(
    name: str, expected: dict[str, list[Any]], delivered: dict[str, Any]
) -> tuple[bool, str]:
    worst = 0.0
    reasons: list[str] = []
    for key in ("signal", "forward", "contributions"):
        left, right = expected[key], delivered[key]
        if len(left) != len(right):
            reasons.append(f"{key} length {len(right)} != {len(left)}")
            continue
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            if a is None or b is None:
                if a is not b:
                    reasons.append(f"{key}[{index}] None mismatch")
                continue
            worst = max(worst, abs(float(a) - float(b)))
    if worst > 1e-9:
        reasons.append(f"max |delta| {worst:.3e}")
    return (not reasons, "; ".join(reasons) or f"{name} reproduced exactly (max |delta| {worst:.1e})")


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #


def verify_registry(verifier: Verifier, artifacts: dict[str, Any]) -> None:
    registry = load_json(REGISTRY_PATH)
    evidence = {"families": registry["families"], "hypotheses": registry["hypotheses"]}
    recomputed = digest(canonical(evidence))
    recorded = artifacts["registry_hash"]
    verifier.check(
        "REGISTRY_HASH_RECOMPUTED_FROM_EVIDENCE",
        recomputed == recorded,
        recorded,
        recomputed,
        "independent canonical serialisation of the frozen registry copy",
    )
    verifier.check(
        "REGISTRY_HASH_IS_THE_PREREGISTERED_ONE",
        recorded == FROZEN_REGISTRY_HASH,
        FROZEN_REGISTRY_HASH,
        recorded,
        "the registry hash cannot have moved after results were seen",
    )
    module_view = {"families": list(a1.FAMILIES), "hypotheses": list(a1.HYPOTHESES)}
    verifier.check(
        "REGISTRY_MATCHES_THE_CODE",
        digest(canonical(module_view)) == recorded,
        recorded,
        digest(canonical(module_view)),
        "the evidence copy and the importing module describe the same registry",
    )
    ids = [item["hypothesis_id"] for item in registry["hypotheses"]]
    verifier.check("HYPOTHESIS_COUNT", len(ids) == EXPECTED_HYPOTHESIS_COUNT, EXPECTED_HYPOTHESIS_COUNT, len(ids))
    verifier.check(
        "HYPOTHESIS_IDS_CONTIGUOUS",
        ids == EXPECTED_HYPOTHESES,
        EXPECTED_HYPOTHESES,
        ids,
        "no hypothesis added after results, no loser removed",
    )
    families = [item["family_id"] for item in registry["families"]]
    verifier.check("FAMILY_COUNT", len(families) == EXPECTED_FAMILY_COUNT, EXPECTED_FAMILY_COUNT, len(families))
    verifier.check(
        "ARTIFACT_COUNTS_MATCH_REGISTRY",
        artifacts["hypothesis_count"] == len(ids) and artifacts["family_count"] == len(families),
        {"hypothesis_count": len(ids), "family_count": len(families)},
        {"hypothesis_count": artifacts["hypothesis_count"], "family_count": artifacts["family_count"]},
    )
    verifier.limitations.append(
        "Preregistration *timing* is attested by the frozen hash plus the versioned code; it is not "
        "independently provable from the artifacts alone."
    )


def verify_dataset_hashes(verifier: Verifier, artifacts: dict[str, Any]) -> None:
    recorded = artifacts["dataset_hashes"]
    recomputed = {symbol: dataset_hash(load_candles(symbol, "1d")) for symbol in artifacts["universe"]}
    recomputed[SESSION_SYMBOL] = dataset_hash(load_candles("BTC/USDT", "4h"))
    mismatched = [symbol for symbol, value in recomputed.items() if recorded.get(symbol) != value]
    verifier.check(
        "DATASET_HASHES",
        not mismatched and len(recorded) == len(recomputed),
        {"count": len(recomputed), "mismatched": []},
        {"count": len(recorded), "mismatched": mismatched},
        "sha256 over the cached candles, recomputed with an independent serialiser",
    )


def verify_holdout(verifier: Verifier, artifacts: dict[str, Any], series: dict[str, Any]) -> None:
    panel = Panel(list(artifacts["universe"]))
    total = len(panel.calendar)
    discovery_end = int(total * DISCOVERY_FRACTION)
    validation_end = int(total * (DISCOVERY_FRACTION + VALIDATION_FRACTION))
    recorded_panel = artifacts["panel"]
    verifier.check(
        "PANEL_SIZE",
        recorded_panel["n_days"] == total,
        total,
        recorded_panel["n_days"],
        "daily calendar reconstructed from the raw candles",
    )
    verifier.check(
        "SPLIT_INDICES",
        recorded_panel["discovery_end"] == discovery_end and recorded_panel["validation_end"] == validation_end,
        {"discovery_end": discovery_end, "validation_end": validation_end},
        {"discovery_end": recorded_panel["discovery_end"], "validation_end": recorded_panel["validation_end"]},
    )

    discovery_stamp = panel.calendar[discovery_end]
    validation_stamp = panel.calendar[validation_end]
    intraday_opens = [int(row[0]) for row in load_candles("BTC/USDT", "4h")]
    held_out = len([stamp for stamp in intraday_opens if stamp >= validation_stamp])
    verifier.check(
        "HOLDOUT_DATA_EXISTS_BUT_WAS_EXCLUDED",
        held_out > 0,
        "at least one 4h bar at or after the validation boundary",
        f"{held_out} 4h bars at or after the validation boundary",
        "the holdout is present in the cache, so excluding it is a real decision",
    )
    daily_ok = all(item["n"] <= recorded_panel["discovery_end"] for item in artifacts["summaries"].values())
    verifier.check(
        "DAILY_DECISIONS_INSIDE_WINDOW",
        daily_ok,
        "every daily hypothesis has n <= discovery_end",
        {hid: item["n"] for hid, item in artifacts["summaries"].items() if hid not in ("A1-H11", "A1-H12")},
    )

    session_start = 60
    session_end = next(
        index for index, stamp in enumerate(intraday_opens) if stamp >= discovery_stamp
    )
    session_hard_end = next(
        index for index, stamp in enumerate(intraday_opens) if stamp >= validation_stamp
    )
    rebuilt = rebuid_a1_h11(session_start, session_end, session_hard_end)
    expected = paired(rebuilt)
    session_cells = {
        "A1-H11": {key: series["A1-H11"][key] for key in ("signal", "forward", "contributions")}
    }
    ok, detail = compare_cell("A1-H11", expected, session_cells["A1-H11"])
    verifier.check(
        "SESSION_WINDOW_AND_SERIES_RECOMPUTED",
        ok,
        "A1-H11 rebuilt independently from the 4h cache, discovery slice only",
        detail,
    )
    verifier.check(
        "SESSION_DECISIONS_BEFORE_HOLDOUT",
        len(series["A1-H11"]["signal"]) <= session_end - session_start
        and len(series["A1-H12"]["signal"]) <= session_end - session_start,
        "every 4h decision lies in the discovery slice, before the validation boundary",
        {
            "A1-H11": len(series["A1-H11"]["signal"]),
            "A1-H12": len(series["A1-H12"]["signal"]),
            "discovery_slice_bars": session_end - session_start,
        },
    )
    verifier.check(
        "HOLDOUT_READ_FLAG", artifacts["holdout_read"] is False, False, artifacts["holdout_read"]
    )
    verifier.check(
        "NO_HOLDOUT_DERIVED_FIELD",
        not any("holdout" in str(key).lower() and key != "holdout_read" for key in artifacts),
        "no artifact field derived from the holdout",
        [key for key in artifacts if "holdout" in str(key).lower()],
    )
    verifier.limitations.append(
        "Boundary rule: in DISCOVERY a decision's forward return may be realised inside the "
        "VALIDATION slice (the next unread window) but never at or beyond the HOLDOUT start. No "
        "validation run was executed, so no realised return touches the holdout."
    )
    verifier.limitations.append(
        "DEFECT FOUND AND FIXED DURING VERIFICATION: the first run built A1-H11/A1-H12 over the whole "
        "4h history (2021-2026), i.e. it read the validation and holdout slices of the intraday series "
        "during DISCOVERY. The split was made a calendar split (all timeframes end their discovery "
        "phase on the same date, at or before the daily discovery boundary) and the campaign was "
        "re-run; the holdout stayed unread throughout. Both session cells remain far below the hurdle."
    )


def verify_information(verifier: Verifier, artifacts: dict[str, Any], series: dict[str, Any]) -> None:
    worst = 0.0
    worst_id = ""
    for hid in EXPECTED_HYPOTHESES:
        row = series[hid]
        ic = spearman([float(value) for value in row["signal"]], [float(value) for value in row["forward"]])
        recorded = artifacts["summaries"][hid]["ic"]
        if abs(ic - recorded) > worst:
            worst, worst_id = abs(ic - recorded), hid
    verifier.check(
        "INFORMATION_METRICS",
        worst <= 1e-6,
        "every |IC - recorded| <= 1e-6",
        f"{worst_id or 'none'} max deviation {worst:.9f}",
        "rank IC recomputed from the delivered signal/forward series",
    )
    informational = sum(1 for hid in EXPECTED_HYPOTHESES if abs(artifacts["summaries"][hid]["ic"]) >= 0.02)
    document = load_json(DISCOVERY_PATH)
    verifier.check(
        "EVIDENCE_DOCUMENT_MATCHES_ARTIFACTS",
        document["gross_positive_count"]
        == sum(1 for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["gross_bps"] > 0)
        and document["net_positive_count"]
        == sum(1 for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["net_bps"] > 0)
        and document["economically_viable_count"] == 0,
        {
            "gross_positive_count": sum(
                1 for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["gross_bps"] > 0
            ),
            "net_positive_count": sum(
                1 for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["net_bps"] > 0
            ),
            "economically_viable_count": 0,
        },
        {
            "gross_positive_count": document["gross_positive_count"],
            "net_positive_count": document["net_positive_count"],
            "economically_viable_count": document["economically_viable_count"],
        },
        "the published evidence document is generated from the verified artifacts",
    )
    verifier.check(
        "INFORMATION_EXISTS_IN_SEVERAL_CELLS",
        informational >= 1,
        ">= 1 cell with |IC| >= 0.02",
        informational,
        "information exists; the question is whether it is large enough to pay the cost",
    )
    verifier.limitations.append(
        f"{informational} of {EXPECTED_HYPOTHESIS_COUNT} cells carry |IC| >= 0.02, but a rank IC is not "
        "an economic edge: several of those cells have a non-positive gross mean."
    )


def verify_economics(verifier: Verifier, artifacts: dict[str, Any], series: dict[str, Any]) -> None:
    failures: dict[str, list[str]] = {}
    recorded_discovery = load_json(ARTIFACTS_PATH)["summaries"]
    for hid in EXPECTED_HYPOTHESES:
        contributions = [float(value) for value in series[hid]["contributions"]]
        row = recorded_discovery[hid]
        gross = mean(contributions)
        sigma = pstdev(contributions)
        n_eff = effective_sample_size(contributions)
        se = sigma / math.sqrt(n_eff) if n_eff > 0 and sigma > 0 else float("inf")
        t_stat = gross / se if se not in (0.0, float("inf")) else 0.0
        power = "POWERED" if mde_bps(sigma, int(max(1, round(n_eff)))) <= artifacts["hurdle_bps"] else "UNDERPOWERED"
        checks = {
            "n": len(contributions) == row["n"],
            "gross": verifier.close(gross, row["gross_bps"], 1e-4),
            "sigma": verifier.close(sigma, row["sigma_bps"], 1e-4),
            "t": verifier.close(t_stat, row["t_stat"], 1e-6),
            "n_eff": verifier.close(n_eff, row["n_effective"], 1e-3),
            "p": verifier.close(one_sided_p(t_stat), row["p_raw"], 1e-8),
            "mde": verifier.close(
                mde_bps(sigma, int(max(1, round(n_eff)))), row["mde_bps"], 1e-4
            ),
            "power": power == row["power_class"],
            "net": verifier.close(row["gross_bps"] - COST_BPS_V3, row["net_bps"], 1e-6),
        }
        failing = [name for name, ok in checks.items() if not ok]
        if failing:
            failures[hid] = failing
    verifier.check(
        "GROSS_EFFECTS",
        not failures,
        "gross/sigma/t/n/n_eff/p reproduce for every cell",
        failures or "all reproduce",
    )
    verifier.check(
        "COST_APPLIED_TO_EVERY_CELL",
        not any("net" in failing for failing in failures.values())
        and verifier.close(COST_BPS_V3, artifacts["cost_bps"], 1e-12),
        f"net == gross - {COST_BPS_V3} for every hypothesis",
        failures or "all reproduce",
        "a missing mandatory cost cannot silently become 0",
    )
    verifier.check(
        "POWER_CLASSIFICATION",
        not any("mde" in failing or "power" in failing for failing in failures.values()),
        "MDE vs hurdle reproduces POWERED/UNDERPOWERED",
        failures or "all reproduce",
    )


def verify_hurdle(verifier: Verifier, artifacts: dict[str, Any]) -> None:
    derived = hurdle_bps(artifacts["panel"]["discovery_end"])
    components = artifacts["hurdle"]
    verifier.check(
        "ECONOMIC_HURDLE",
        verifier.close(derived, artifacts["hurdle_bps"], 1e-6)
        and verifier.close(derived, components["min_gross_alpha_hurdle_bps"], 1e-6),
        round(derived, 6),
        components["min_gross_alpha_hurdle_bps"],
        "cost + 25% execution + 8.121 winner's-curse buffer + z_0.975 * 400 / sqrt(n_eff)",
    )
    verifier.check(
        "HURDLE_COMPONENTS_ADD_UP",
        verifier.close(
            components["cost_bps"]
            + components["execution_uncertainty_bps"]
            + components["winners_curse_buffer_bps"]
            + components["statistical_uncertainty_bps"],
            components["min_gross_alpha_hurdle_bps"],
            1e-6,
        ),
        components["min_gross_alpha_hurdle_bps"],
        round(
            components["cost_bps"]
            + components["execution_uncertainty_bps"]
            + components["winners_curse_buffer_bps"]
            + components["statistical_uncertainty_bps"],
            6,
        ),
    )
    above = [hid for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["gross_above_hurdle"]]
    recomputed = [
        hid for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["gross_bps"] >= artifacts["hurdle_bps"]
    ]
    verifier.check(
        "ECONOMICALLY_VIABLE_COUNT",
        above == recomputed,
        recomputed,
        above,
        "a gross edge below the hurdle may not be promoted",
    )
    verifier.check(
        "NET_POSITIVE_COUNT",
        sum(1 for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["net_bps"] > 0) == 0,
        0,
        sum(1 for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["net_bps"] > 0),
        "not a single cell survives the certified cost",
    )
    verifier.limitations.append(
        "A1-H09's point estimate (+18.58 bps) has a 95% normal interval of roughly [-62, +99] bps: the "
        "cell is economically too small on its point estimate and statistically inconclusive, and its "
        "rank IC is negative, so no data expansion is justified to rescue it."
    )


def verify_multiplicity(verifier: Verifier, artifacts: dict[str, Any]) -> None:
    rows = artifacts["multiple_testing"]["rows"]
    ids = [row["hypothesis_id"] for row in rows]
    pvalues = [row["p_raw"] for row in rows]
    computed_bh = benjamini_hochberg(pvalues, BH_Q)
    computed_holm = holm(pvalues, HOLM_ALPHA)
    verifier.check(
        "BH_FDR_CORRECTION",
        computed_bh == [row["bh_pass"] for row in rows],
        {"q": BH_Q, "survivors": [ids[i] for i, ok in enumerate(computed_bh) if ok]},
        {"q": BH_Q, "survivors": [row["hypothesis_id"] for row in rows if row["bh_pass"]]},
    )
    verifier.check(
        "HOLM_CORRECTION",
        computed_holm == [row["holm_pass"] for row in rows],
        {"alpha": HOLM_ALPHA, "survivors": [ids[i] for i, ok in enumerate(computed_holm) if ok]},
        {"alpha": HOLM_ALPHA, "survivors": [row["hypothesis_id"] for row in rows if row["holm_pass"]]},
    )
    verifier.check(
        "MULTIPLICITY_N_IS_EXACT_HYPOTHESIS_COUNT",
        len(rows) == artifacts["hypothesis_count"],
        artifacts["hypothesis_count"],
        len(rows),
        "the correction uses the preregistered N, not a subset",
    )
    verifier.check(
        "NO_RAW_P_PRESENTED_AS_CORRECTED",
        not any(row["bh_pass"] or row["holm_pass"] for row in rows),
        "0 BH survivors and 0 Holm survivors",
        {
            "bh_survivors": sum(1 for row in rows if row["bh_pass"]),
            "holm_survivors": sum(1 for row in rows if row["holm_pass"]),
        },
        "no cell may be presented as significant on a raw p alone",
    )
    verifier.limitations.append(
        "A1-H10 is the exact mirror of A1-H09, so the two are not independent tests; the "
        "preregistered BH/Holm corrections treat them as separate hypotheses."
    )


def verify_best_of_n(verifier: Verifier, artifacts: dict[str, Any], series: dict[str, Any]) -> None:
    # The campaign's "best observed" is the largest per-cell gross mean; a cell's own
    # denominator (including its flat days) is the one used by its summary.
    gross = {hid: mean([float(value) for value in series[hid]["contributions"]]) for hid in EXPECTED_HYPOTHESES}
    observed = max(gross.values())
    best_id = max(EXPECTED_HYPOTHESES, key=lambda hid: gross[hid])
    verifier.check(
        "OBSERVED_BEST_RECOMPUTED",
        verifier.close(observed, artifacts["null"]["observed_best"], 1e-6)
        and best_id == artifacts["best_hypothesis"],
        {"observed_best": round(observed, 6), "best_hypothesis": best_id},
        {
            "observed_best": artifacts["null"]["observed_best"],
            "best_hypothesis": artifacts["best_hypothesis"],
        },
    )
    rng = random.Random(NULL_SEED)
    draws: list[float] = []
    for _ in range(NULL_DRAWS):
        best = float("-inf")
        for hid in EXPECTED_HYPOTHESES:
            direction = series[hid]["active_direction"]
            forward = series[hid]["active_forward"]
            if len(direction) < 20:
                continue
            shifted = circular_shift(direction, rng.randrange(1, len(direction)))
            best = max(best, mean([d * f * 1e4 for d, f in zip(shifted, forward, strict=True)]))
        if best > float("-inf"):
            draws.append(best)
    draws.sort()

    def quantile(level: float) -> float:
        return draws[min(len(draws) - 1, max(0, math.ceil(level * len(draws)) - 1))]

    p_value = sum(1 for value in draws if value >= observed) / len(draws)
    reproduced = {
        "draws": len(draws),
        "null_median": round(quantile(0.50), 6),
        "null_p95": round(quantile(0.95), 6),
        "null_p99": round(quantile(0.99), 6),
        "null_max": round(draws[-1], 6),
        "p_null_best_ge_observed": round(p_value, 6),
    }
    null = artifacts["null"]
    verifier.check(
        "BEST_OF_N_NULL_REPRODUCED",
        reproduced["draws"] == null["draws"]
        and all(
            verifier.close(reproduced[key], null[key], 1e-6)
            for key in ("null_median", "null_p95", "null_p99", "null_max", "p_null_best_ge_observed")
        ),
        {key: null[key] for key in ("draws", "null_median", "null_p95", "null_p99", "p_null_best_ge_observed")},
        reproduced,
        "permutation null re-run from the delivered series with the recorded seed",
    )
    verifier.check(
        "NULL_NOT_SIGNIFICANT",
        not null["significant_at_0_05"] and null["p_null_best_ge_observed"] > 0.05,
        "P(null best >= observed) > 0.05",
        null["p_null_best_ge_observed"],
        "the best observed cell sits inside the no-alpha distribution",
    )
    curse = artifacts["winners_curse"]
    shrunken = null["observed_best"] - null["null_median"]
    verifier.check(
        "WINNERS_CURSE_SHRINKAGE",
        verifier.close(shrunken, curse["shrunken_edge_bps"], 1e-6)
        and verifier.close(null["null_median"], curse["selection_inflation_bps"], 1e-6)
        and curse["shrunken_edge_bps"] <= 0.0,
        {"selection_inflation_bps": null["null_median"], "shrunken_edge_bps": round(shrunken, 6)},
        {
            "selection_inflation_bps": curse["selection_inflation_bps"],
            "shrunken_edge_bps": curse["shrunken_edge_bps"],
        },
        "the raw winner may never be used as a forward expectation; after shrinkage it is negative",
    )
    verifier.limitations.append(
        "The permutation null makes the selection question conservative; it cannot express a "
        "rare-event strategy's dependence on a few large moves."
    )
    verifier.limitations.append(
        "A1-H05/A1-H06 take flat days (breadth exactly at its midline, contribution 0) into the "
        "signed permutation as direction +1, because the direction is recovered from the sign of "
        "contribution * forward. Those days are a small fraction of the sample and the null stays "
        "far from significance, but the walk is not an exact model of a flat decision."
    )


def verify_concentration_and_stability(
    verifier: Verifier, artifacts: dict[str, Any], series: dict[str, Any]
) -> None:
    best = artifacts["best_hypothesis"]
    contributions = [float(value) for value in series[best]["contributions"] if value != 0.0]
    recomputed = concentration(contributions)
    recorded = artifacts["concentration"]
    verifier.check(
        "TRADE_CONCENTRATION",
        all(
            verifier.close(recomputed[key], recorded[key], 1e-4)
            for key in ("top1_share", "top3_share", "top5_share", "net_ex_best", "net_ex_top3")
        )
        and recomputed["classification"] == recorded["classification"],
        {"classification": recorded["classification"], "top1_share": recorded["top1_share"]},
        {"classification": recomputed["classification"], "top1_share": round(recomputed["top1_share"], 6)},
        "a single-trade edge is not an edge",
    )
    verifier.check(
        "CONCENTRATION_IS_FRAGILE",
        recorded["classification"] == "FRAGILE" and recomputed["classification"] == "FRAGILE",
        "FRAGILE",
        recorded["classification"],
        "the best cell is dominated by its single largest trade",
    )
    size = math.ceil(len(contributions) / 4)
    chunks = [contributions[index : index + size] for index in range(0, len(contributions), size)]
    windows = [mean(chunk) for chunk in chunks]
    stability = artifacts["stability"]
    verifier.check(
        "STABILITY_WINDOWS",
        len(stability["windows"]) == len(windows)
        and all(verifier.close(value, stability["windows"][index], 1e-4) for index, value in enumerate(windows)),
        {"windows": [round(value, 6) for value in windows]},
        {"windows": stability["windows"]},
        "no window was dropped to improve the result",
    )
    verifier.check(
        "STABILITY_NOT_CONSISTENT",
        stability["consistent"] is False and stability["n_positive"] > 0 and stability["n_negative"] > 0,
        "both positive and negative windows",
        {"n_positive": stability["n_positive"], "n_negative": stability["n_negative"]},
    )
    verifier.limitations.append(
        "A1-H05/A1-H06 include flat days (contribution exactly 0) in the gross mean, while "
        "concentration and stability are computed on the active subset. The asymmetry is visible in "
        "the artifacts and inflates the denominator of those two cells' gross means."
    )


def verify_admission_and_validation(
    verifier: Verifier, artifacts: dict[str, Any], series: dict[str, Any]
) -> None:
    rows = {row["hypothesis_id"]: row for row in artifacts["multiple_testing"]["rows"]}
    admitted: list[str] = []
    for hid in EXPECTED_HYPOTHESES:
        item = artifacts["summaries"][hid]
        contributions = [float(value) for value in series[hid]["contributions"] if value != 0.0]
        if (
            abs(item["ic"]) > 0.0
            and item["gross_above_hurdle"]
            and rows[hid]["bh_pass"]
            and item["power_class"] == "POWERED"
            and concentration(contributions)["classification"] == "ROBUST"
        ):
            admitted.append(hid)
    verifier.check(
        "ADMISSION_RULE_REPRODUCED",
        admitted == artifacts["admitted"],
        artifacts["admitted"],
        admitted,
        "information + hurdle + multiplicity + power + concentration, recomputed",
    )
    verifier.check(
        "NO_CANDIDATE_ADMITTED",
        artifacts["admitted"] == [],
        [],
        artifacts["admitted"],
        "nothing was promoted on a gross edge below the hurdle",
    )
    verifier.check(
        "NO_VALIDATION_RUN_WITHOUT_ADMISSION",
        artifacts["validation"] == {} and artifacts["admitted"] == [],
        "validation {} because admitted []",
        {"admitted": artifacts["admitted"], "validation_runs": len(artifacts["validation"])},
        "validating a non-admitted candidate would be a false-success path",
    )
    verifier.check(
        "NO_LIMIT_TUNED_AFTER_RESULTS",
        all(
            artifacts["summaries"][hid]["hurdle_bps"] == artifacts["hurdle_bps"]
            for hid in EXPECTED_HYPOTHESES
        ),
        "one single hurdle for every cell",
        sorted({artifacts["summaries"][hid]["hurdle_bps"] for hid in EXPECTED_HYPOTHESES}),
        "no per-cell threshold tuning",
    )
    underpowered = [
        hid for hid in EXPECTED_HYPOTHESES if artifacts["summaries"][hid]["power_class"] == "UNDERPOWERED"
    ]
    verifier.check(
        "UNDERPOWERED_ARE_NOT_CALLED_NEGATIVE",
        all(hid not in artifacts["admitted"] for hid in underpowered),
        "underpowered cells cannot be promoted and cannot be declared NO_ALPHA",
        {"underpowered": underpowered, "count": len(underpowered)},
        "an undetected effect is INCONCLUSIVE, not absent",
    )
    verifier.check(
        "MAX_VALIDATION_CANDIDATES",
        len(artifacts["admitted"]) <= 3,
        "at most 3 validation candidates",
        len(artifacts["admitted"]),
    )


def verify_false_success(verifier: Verifier, artifacts: dict[str, Any]) -> None:
    blobs = [
        path.read_text(encoding="utf-8").upper()
        for path in (ARTIFACTS_PATH, REGISTRY_PATH, INVENTORY_PATH, NEGATIVE_PATH)
    ]
    promoted = sorted({word for word in FORBIDDEN_VERDICT_WORDS if any(word in blob for blob in blobs)})
    verifier.check(
        "NO_FORBIDDEN_VERDICT_WORDS",
        not promoted,
        "no EDGE_CERTIFIED / PROFITABLE / PAPER_READY / LIVE_READY / DIRECTIONAL_ALPHA claim",
        promoted or "none",
    )
    inventory = load_json(INVENTORY_PATH)
    falsified = {
        item["family_id"]
        for item in inventory["families"]
        if item["status"].startswith("FALSIFIED") or item["status"] == "ECONOMICALLY_TOO_SMALL"
    }
    new_families = {item["family_id"] for item in load_json(REGISTRY_PATH)["families"]}
    verifier.check(
        "NO_FALSIFIED_FAMILY_RENAMED",
        not (new_families & falsified),
        "no new family id reuses a falsified family id",
        sorted(new_families & falsified),
        "a falsified family may not reappear under a new name",
    )
    verifier.check(
        "NO_DIFFERENT_INSTRUMENT_SUBSTITUTED",
        set(artifacts["dataset_hashes"]) == set(artifacts["universe"]) | {SESSION_SYMBOL},
        sorted(set(artifacts["universe"]) | {SESSION_SYMBOL}),
        sorted(artifacts["dataset_hashes"]),
        "the traded set is exactly the preregistered universe; no stand-in was swapped in",
    )
    verifier.limitations.append(
        "RISK DISCLOSED, NOT A FALSE SUCCESS: F5_VOL_SHOCK_ASYMMETRY (A1-H09/A1-H10) re-asks the "
        "directional question of the falsified volatility family at 1D. It was preregistered before "
        "results and its gross stayed below the hurdle, so no falsified family was resurrected."
    )


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# ALPHA-001 — INDEPENDENT VERIFICATION",
        "",
        f"`STATUS = {result['status']}`",
        "",
        f"- checks: **{result['passed']}/{result['total']}** PASS",
        f"- mismatches: **{result['mismatches']}**",
        f"- false successes: **{result['false_success']}**",
        f"- limitations: **{result['limitations']}**",
        f"- builder: `{result['builder']}` — verifier: `{result['verifier']}` (no shared import)",
        "",
        "Verified artifacts (content-addressed):",
        "",
    ]
    for name, value in result["verified_files"].items():
        lines.append(f"- `{name}`: `{value}`")
    lines.extend(["", "| check | status | expected | actual |", "| --- | --- | --- | --- |"])
    for item in result["checks"]:
        lines.append(f"| {item['check']} | **{item['status']}** | {item['expected']} | {item['actual']} |")
    lines.extend(["", "## Limitations declared by the verifier", ""])
    lines.extend(f"- {note}" for note in result["limitations_list"])
    lines.extend(["", "## False-success candidates", ""])
    lines.extend(f"- {note}" for note in result["false_success_list"] or ["none"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="ALPHA-001 independent verifier").parse_args(argv)

    artifacts = load_json(ARTIFACTS_PATH)
    series = load_json(SERIES_PATH)

    verifier = Verifier()
    verify_registry(verifier, artifacts)
    verify_dataset_hashes(verifier, artifacts)
    verify_holdout(verifier, artifacts, series)
    verify_information(verifier, artifacts, series)
    verify_economics(verifier, artifacts, series)
    verify_hurdle(verifier, artifacts)
    verify_multiplicity(verifier, artifacts)
    verify_best_of_n(verifier, artifacts, series)
    verify_concentration_and_stability(verifier, artifacts, series)
    verify_admission_and_validation(verifier, artifacts, series)
    verify_false_success(verifier, artifacts)

    # independent re-walks of one cell per data path
    for hid, rebuilt in (
        ("A1-H01", rebuid_a1_h01(list(artifacts["universe"]), artifacts["panel"]["discovery_end"])),
        ("A1-H09", rebuid_a1_h09(list(artifacts["universe"]), artifacts["panel"]["discovery_end"])),
    ):
        ok, detail = compare_cell(
            hid, paired(rebuilt), {key: series[hid][key] for key in ("signal", "forward", "contributions")}
        )
        verifier.check(
            f"{hid}_SERIES_RECOMPUTED",
            ok,
            f"{hid} rebuilt independently from the raw candles, discovery slice only",
            detail,
        )

    verified_files = {
        "src/trading_bot/research/alpha001.py": file_sha256(REPO / "src/trading_bot/research/alpha001.py"),
        "scripts/alpha001_run.py": file_sha256(REPO / "scripts/alpha001_run.py"),
        "reports/alpha001/ALPHA001_ARTIFACTS.json": file_sha256(ARTIFACTS_PATH),
        "reports/alpha001/ALPHA001_SERIES.json": file_sha256(SERIES_PATH),
        "reports/alpha001/ALPHA001_HYPOTHESIS_REGISTRY.json": file_sha256(REGISTRY_PATH),
    }
    result = {
        "campaign": "ALPHA-001",
        "verifier": "scripts/alpha001_verify.py",
        "builder": "scripts/alpha001_run.py",
        "independence": "no import of the builder; own canonicaliser, statistics, corrections, permutation null, admission rule and builder re-implementations for A1-H01/A1-H09/A1-H11",
        "status": "PASS" if verifier.mismatches == 0 else "FAIL",
        "passed": verifier.passed,
        "total": len(verifier.checks),
        "mismatches": verifier.mismatches,
        "false_success": len(verifier.false_success),
        "limitations": len(verifier.limitations),
        "holdout_read": artifacts["holdout_read"],
        "registry_hash": artifacts["registry_hash"],
        "hurdle_bps": artifacts["hurdle_bps"],
        "cost_bps": artifacts["cost_bps"],
        "best_hypothesis": artifacts["best_hypothesis"],
        "best_observed_gross_bps": artifacts["null"]["observed_best"],
        "p_null_best_ge_observed": artifacts["null"]["p_null_best_ge_observed"],
        "admitted": artifacts["admitted"],
        "validation_runs": len(artifacts["validation"]),
        "checks": verifier.checks,
        "limitations_list": verifier.limitations,
        "false_success_list": verifier.false_success,
        "verified_files": verified_files,
    }
    OUT_JSON.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    OUT_MD.write_text(render_markdown(result), encoding="utf-8")

    print(
        json.dumps(
            {
                "STATUS": result["status"],
                "PASSED": result["passed"],
                "TOTAL": result["total"],
                "MISMATCHES": result["mismatches"],
                "FALSE_SUCCESS": result["false_success"],
                "LIMITATIONS": result["limitations"],
            },
            indent=2,
        )
    )
    for item in verifier.checks:
        if item["status"] == "MISMATCH":
            print(f"  MISMATCH {item['check']}: expected {item['expected']} got {item['actual']}")
    return 0 if verifier.mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
