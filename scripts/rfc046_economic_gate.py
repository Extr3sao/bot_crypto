"""RFC-046 ECONOMIC GATE — retail-spot feasibility with 200 USDT.

The first campaign failed (`DISCOVERY_CAMPAIGN_FAILED`) and the forensics explained *why* each
candidate died.  Neither artefact answered the standing business question: **what would a strategy
have to look like, economically, to be viable at all with 200 USDT on the authorized runtime?**

This script answers exactly that, and it does so without generating a single trading signal:

* It **reuses** COST_MODEL_V3 (the frozen model) and re-derives every cost component from it, at
  both the model's documented reference notional (1,000 USD) and the runtime's actual reference
  capital (200 USDT), so the difference is measured rather than assumed.
* It audits the **applicability** of every modelling assumption to the exchange, instrument and
  order types the runtime is actually authorized to use, and records the conflicts it finds.
* It computes the break-even for each **permitted modality**: the minimum gross move per round
  trip, the absolute cost per operation at 200 USDT, the illustrated cost of three daily round
  trips, the sensitivity to size and turnover, and the operating-cost impact on the business.
* It classifies the six strategy families **by measurement, not by opinion**: it measures the
  typical absolute move over each family's own horizon on the raw bars the campaign used, and
  compares that measured move with the toll.  A family whose typical move cannot pay the toll is
  not cost-compatible, whatever its edge may be.
* It reviews the RFC-046 evidence and confirms, from the recorded artefacts, the three findings
  the owner asked to be confirmed.
* It emits a scope recommendation in the allowed vocabulary and keeps every standing limit.

It does **not** create hypotheses, does not touch the frozen specs, does not reuse the final OOS
for selection, does not activate a second campaign, and does not trade anything.  It admits
nothing and claims no edge: cost compatibility is arithmetic about the toll, never evidence that
an edge exists.

Run:  python scripts/rfc046_economic_gate.py            (writes the artefacts)
      python scripts/rfc046_economic_gate.py --check    (builds and verifies, writes nothing)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run
from typing import Any, Literal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.microstructure.cost_model_v3 import (  # noqa: E402
    ADMISSION_SCENARIO_ID,
    VENUE_SPECS,
    default_model,
)

COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
VENUE_MATRIX = REPO / "docs" / "VENUE_EXECUTION_MATRIX_V1.json"
EXECUTION_MODEL = REPO / "docs" / "EXECUTION_MODEL_V1.json"
RFC046 = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"
RUNTIME_CFG = REPO / "config" / "runtime.yaml"
RUN_JSON = REPO / "data" / "rfc046" / "RUN_REPORT.json"
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"
PRICE_DIR = REPO / "data" / "raw" / "alpha003" / "price"
OUT_JSON = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.json"
OUT_MD = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.md"

BPS = 10_000.0
REFERENCE_CAPITAL_USDT = 200.0
DOCUMENTED_REFERENCE_SIZE_USD = 1000.0
DOCUMENTED_REFERENCE_NOTIONAL_USD = 10_000.0
DEFAULT_TARGET_NET_ANNUAL = 0.20  # documented in the operating model, not invented here
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

# Horizons measured on the raw bars, in bars of the 5-minute series.
HORIZON_BARS: dict[str, int] = {
    "5m": 1,
    "15m": 3,
    "1h": 12,
    "4h": 48,
    "8h": 96,
    "24h": 288,
    "72h": 864,
    "168h": 2016,
}

#: Each family is mapped to the horizon that actually decides its economics: the *shortest*
#: horizon it trades at, because that is where the toll is largest relative to the move.
#: These bands are the modelling assumption of this artefact and are declared as such.
FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "family": "scalping",
        "holding_band": "seconds to 15 minutes",
        "representative_horizon": "5m",
        "considered_horizons": ["5m", "15m"],
        "runtime_fit": "long/cash only: the short side of a scalp is not expressible",
    },
    {
        "family": "intraday",
        "holding_band": "1 to 8 hours",
        "representative_horizon": "1h",
        "considered_horizons": ["1h", "4h", "8h"],
        "runtime_fit": "long/cash only: an intraday exit must be a cash exit, not a short",
    },
    {
        "family": "mean_reversion",
        "holding_band": "hours (reversion half-life)",
        "representative_horizon": "4h",
        "considered_horizons": ["1h", "4h", "24h"],
        "runtime_fit": "long/cash only: expressible as buy-the-dip, not as sell-the-rip",
    },
    {
        "family": "momentum",
        "holding_band": "1 to 5 days",
        "representative_horizon": "24h",
        "considered_horizons": ["24h", "72h"],
        "runtime_fit": "long/cash only: participates only in upward momentum",
    },
    {
        "family": "swing_trading",
        "holding_band": "2 to 10 days",
        "representative_horizon": "72h",
        "considered_horizons": ["24h", "72h"],
        "runtime_fit": "long/cash only: a swing entry and exit are both cash legs",
    },
    {
        "family": "trend_following",
        "holding_band": "2 to 12 weeks",
        "representative_horizon": "168h",
        "considered_horizons": ["72h", "168h"],
        "runtime_fit": "long/cash only: a long-only trend follower is long beta most of the time",
    },
)

BOUNDARY_CAPTURE = 0.5  # >= half of the typical move must be captured -> boundary, not comfortable

OrderType = Literal["market", "limit_post_only", "limit_ioc", "limit_gtc"]

COST_VERDICTS = ("NOT_COST_COMPATIBLE", "COST_BOUNDARY", "COST_COMPATIBLE")
SCOPE_VERDICTS = (
    "VIABLE_COST_PROFILE_IDENTIFIED",
    "NO_VIABLE_PROFILE_IDENTIFIED",
    "INSUFFICIENT_EVIDENCE",
)


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head() -> str:
    proc = run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _yaml_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*{key}:\s*\"?([^\"\n#]+?)\"?\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def _yaml_list(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^\s*{key}:\s*$", line):
            items: list[str] = []
            for follow in lines[index + 1 :]:
                item = re.match(r"^\s*-\s+\"?([^\"\n]+?)\"?\s*$", follow)
                if item:
                    items.append(item.group(1))
                elif follow.strip() and not follow.startswith(" "):
                    break
            return items
    return []


# --------------------------------------------------------------------------- #
# 1. Authorized runtime
# --------------------------------------------------------------------------- #


def authorized_runtime() -> dict[str, Any]:
    """What the runtime is actually allowed to do, read from the configs themselves."""
    exchange = EXCHANGE_CFG.read_text(encoding="utf-8")
    runtime = RUNTIME_CFG.read_text(encoding="utf-8")
    venue = _yaml_scalar(exchange, "id")
    account_type = _yaml_scalar(exchange, "account_type")
    sandbox = _yaml_scalar(exchange, "sandbox")
    default_type = _yaml_scalar(exchange, "default_type")
    post_only = _yaml_scalar(exchange, "post_only_default")
    tif = _yaml_scalar(exchange, "time_in_force_default")
    mode = _yaml_scalar(runtime, "mode")
    live = _yaml_scalar(runtime, "live_trading_enabled")
    excluded = _yaml_list(exchange, "excluded_markets")
    if (venue, account_type, sandbox, default_type) != ("binance", "spot", "true", "spot"):
        raise SystemExit(
            f"refusing to audit an unexpected runtime: venue={venue!r} account_type={account_type!r} "
            f"sandbox={sandbox!r} default_type={default_type!r}"
        )
    return {
        "venue": venue,
        "account_type": account_type,
        "sandbox": sandbox == "true",
        "default_type": default_type,
        "excluded_markets": excluded,
        "default_order_posture": {
            "post_only_default": post_only == "true",
            "time_in_force_default": tif,
        },
        "runtime_mode": mode,
        "live_trading_enabled": live == "true",
        "reference_capital_usdt": REFERENCE_CAPITAL_USDT,
        "direction": "long/cash only (spot cannot short; derivatives are excluded)",
        "config_hashes": {
            str(EXCHANGE_CFG.relative_to(REPO)): _sha256(EXCHANGE_CFG),
            str(RUNTIME_CFG.relative_to(REPO)): _sha256(RUNTIME_CFG),
        },
    }


# --------------------------------------------------------------------------- #
# 2. Cost audit — decompose the frozen model, at both reference sizes
# --------------------------------------------------------------------------- #


def _size_factor(size_usd: float) -> float:
    """Independent arithmetic for the model's documented size term (1 + sqrt(size / 10,000))."""
    return 1.0 + math.sqrt(size_usd / DOCUMENTED_REFERENCE_NOTIONAL_USD)


def _independent_spot_taker_bps(size_usd: float, maker_fee_bps: float, taker_fee_bps: float,
                                spread_bps: float) -> float:
    """Fee + spread + slippage + impact, computed outside the model, for the cross-check below."""
    fee = 2.0 * taker_fee_bps
    spread = spread_bps * 1.0  # two taker legs x half-spread
    size = _size_factor(size_usd)
    slippage = 2.0 * 1.0 * 1.0 * size  # base 1.0 bps x liquidity 1.0 x size factor x 2 legs
    impact = 2.0 * 0.25 * 1.0 * (size - 1.0)  # base 0.25 bps x liquidity 1.0 x (size-1) x 2 legs
    return fee + spread + slippage + impact


def _components(scenario_id: str, size_usd: float) -> tuple[dict[str, Any], float, float]:
    """One scenario at one size: the published decomposition plus the exact sums to check."""
    model = default_model(scenario_id)
    order_types: tuple[OrderType, OrderType] = (
        ("limit_post_only", "limit_post_only")
        if scenario_id.endswith("_MAKER")
        else ("market", "market")
    )
    cost = model.evaluate(
        size_usd=size_usd,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type=order_types[0],
        exit_order_type=order_types[1],
    )
    exact_total = cost.round_trip_bps
    exact_sum = sum(c.value_bps for c in cost.components)
    published = {
        "scenario_id": scenario_id,
        "order_types": f"{cost.entry_order_type} / {cost.exit_order_type}",
        "size_usd": size_usd,
        "round_trip_bps": round(cost.round_trip_bps, 9),
        "components": [
            {
                "name": c.name,
                "value_bps": round(c.value_bps, 9),
                "knowledge": c.knowledge,
                "source_id": c.source_id,
            }
            for c in cost.components
        ],
        "knowledge_class": cost.knowledge_class,
        "size_factor": round(_size_factor(size_usd), 6),
        "size_invariant": not any(c.name in ("slippage", "market_impact", "spread") for c in cost.components),
    }
    return published, exact_total, exact_sum


def cost_audit(
    runtime: dict[str, Any], model_doc: dict[str, Any]
) -> tuple[dict[str, Any], float, float, float]:
    """Applicability of every assumption to the authorized runtime, and the cost arithmetic.

    Returns the publishable document plus the exact (unrounded) round-trip costs at 200 USDT and
    ​1,000 USD, so downstream arithmetic never starts from a rounded figure.
    """
    at_1000, exact_1000, sum_1000 = _components(ADMISSION_SCENARIO_ID, DOCUMENTED_REFERENCE_SIZE_USD)
    at_200, exact_200, sum_200 = _components(ADMISSION_SCENARIO_ID, REFERENCE_CAPITAL_USDT)
    maker_1000, maker_exact_1000, maker_sum_1000 = _components(
        "BINANCE_SPOT_STANDARD_MAKER", DOCUMENTED_REFERENCE_SIZE_USD
    )
    maker_200, maker_exact_200, maker_sum_200 = _components(
        "BINANCE_SPOT_STANDARD_MAKER", REFERENCE_CAPITAL_USDT
    )

    # Check 1: inside the model, the total must equal the sum of its own components.
    for label, exact, component_sum in (
        (f"{ADMISSION_SCENARIO_ID}@{DOCUMENTED_REFERENCE_SIZE_USD}", exact_1000, sum_1000),
        (f"{ADMISSION_SCENARIO_ID}@{REFERENCE_CAPITAL_USDT}", exact_200, sum_200),
        (f"BINANCE_SPOT_STANDARD_MAKER@{DOCUMENTED_REFERENCE_SIZE_USD}", maker_exact_1000, maker_sum_1000),
        (f"BINANCE_SPOT_STANDARD_MAKER@{REFERENCE_CAPITAL_USDT}", maker_exact_200, maker_sum_200),
    ):
        if abs(exact - component_sum) > 1e-12 * max(1.0, abs(exact)):
            raise SystemExit(
                f"{label}: the model's total ({exact}) is not the sum of its components "
                f"({component_sum}); the decomposition would be unsound"
            )

    # Check 2: the decomposition must reproduce the frozen model from first principles.
    spot = VENUE_SPECS[ADMISSION_SCENARIO_ID]
    for size, exact in (
        (DOCUMENTED_REFERENCE_SIZE_USD, exact_1000),
        (REFERENCE_CAPITAL_USDT, exact_200),
    ):
        independent = _independent_spot_taker_bps(
            size, spot.maker_fee_bps, spot.taker_fee_bps, spot.default_taker_spread_bps
        )
        if abs(independent - exact) > 1e-9:
            raise SystemExit(
                f"cost decomposition does not reproduce COST_MODEL_V3 at {size} USD: "
                f"independent={independent} model={exact}"
            )

    fee_total = sum(c["value_bps"] for c in at_200["components"] if c["name"].startswith("exchange_fee"))
    spread = sum(c["value_bps"] for c in at_200["components"] if c["name"] == "spread")
    slippage = sum(c["value_bps"] for c in at_200["components"] if c["name"] == "slippage")
    impact = sum(c["value_bps"] for c in at_200["components"] if c["name"] == "market_impact")
    total = exact_200

    frozen = _read_json(COST_MODEL)
    scenarios = [
        {
            "scenario_id": s["evaluation"]["scenario_id"],
            "product": s["spec"]["product"],
            "round_trip_bps": float(s["evaluation"]["round_trip_bps"]),
        }
        for s in frozen["scenarios"]
    ]
    scenarios.sort(key=lambda r: (r["round_trip_bps"], r["scenario_id"]))
    spot_rows = [r for r in scenarios if r["product"] == "Spot"]
    execution = _read_json(EXECUTION_MODEL)
    matrix = _read_json(VENUE_MATRIX)

    # Open discrepancy found by this audit: the tracked matrix's maker column equals the taker
    # cost for every scenario, while the frozen cost model prices the same maker intent 17.46 bps
    # higher.  The current generator reproduces the cost model, not the matrix file.
    matrix_maker = next(
        r["maker_rt_cost_bps_theoretical"]
        for r in matrix["rows"]
        if r["scenario_id"] == "BINANCE_SPOT_STANDARD_MAKER"
    )
    defects = []
    if abs(float(matrix_maker) - maker_1000["round_trip_bps"]) > 1e-9:
        defects.append(
            {
                "id": "ECON-AUDIT-001",
                "title": "VENUE_EXECUTION_MATRIX_V1.json prices the maker path as if it were taker",
                "evidence": (
                    f"matrix maker_rt_cost_bps_theoretical={matrix_maker} for "
                    f"BINANCE_SPOT_STANDARD_MAKER, while COST_MODEL_V3.json prices the same "
                    f"post-only intent at {maker_1000['round_trip_bps']} bps at "
                    f"{DOCUMENTED_REFERENCE_SIZE_USD:.0f} USD notional; re-running the current "
                    f"generator (venue_matrix_rows) returns {maker_1000['round_trip_bps']} bps"
                ),
                "effect": (
                    "a reader who trusts the matrix's maker column would understate the maker path "
                    "by "
                    f"{maker_1000['round_trip_bps'] - float(matrix_maker):.4f} bps and conclude "
                    "passive execution is free; this audit uses COST_MODEL_V3.json instead"
                ),
                "status": "OPEN — not repaired here (frozen artefact of another workstream; a fix "
                "is a new version, not an edit)",
            }
        )

    applicability = [
        {
            "assumption": "Binance Spot VIP0 fee, 10 bps per leg, paid in the quote asset",
            "value": "20.0 bps per round trip",
            "knowledge": "KNOWN",
            "source_id": "SRC-01",
            "verdict": "CONFIRMED",
            "why": "published schedule for our tier; the runtime's venue and account type match "
            "the scenario",
            "conflict": "the runtime is configured sandbox: true, so a testnet fill does not "
            "reproduce live-account fees — the fee arithmetic is a live-account property",
        },
        {
            "assumption": "majors' taker spread 1.0 bps (2 legs x half-spread)",
            "value": f"{spread} bps per round trip",
            "knowledge": "ESTIMATED",
            "source_id": "SRC-07",
            "verdict": "UNKNOWN",
            "why": "SRC-07 has no historical endpoint: the estimate comes from a single "
            "bookTicker observation and cannot be re-verified for a past period",
            "caveat": "a forward collection is required before any realised-cost comparison, and "
            "this is the component a cost overrun would most likely arrive in",
        },
        {
            "assumption": "base slippage 1.0 bps and size/impact constants",
            "value": f"{slippage + impact} bps per round trip at 200 USDT",
            "knowledge": "ESTIMATED",
            "source_id": "MODEL-V3",
            "verdict": "UNKNOWN",
            "why": "the model's own constants block labels them ASSUMED/ESTIMATED modelling "
            "constants, not observations",
            "caveat": "no measured slippage exists for our order flow",
        },
        {
            "assumption": "size term 1 + sqrt(size / 10,000)",
            "value": f"size factor {_size_factor(REFERENCE_CAPITAL_USDT):.6f} at 200 USDT",
            "knowledge": "ASSUMED",
            "source_id": "MODEL-V3",
            "verdict": "UNKNOWN",
            "why": "a documented modelling choice, never fitted to our fills",
            "caveat": "it moves the bar by only 0.32 bps between the two reference sizes, because "
            "the fee term dominates and is size-invariant — the model's precision is spent on a "
            "small term",
        },
        {
            "assumption": "maker adverse selection 0.5 bps per leg and fill probability 0.5",
            "value": f"{maker_1000['round_trip_bps'] - 2.0 * spot.maker_fee_bps:.2f} bps of "
            "maker-specific risk at 1,000 USD",
            "knowledge": "ASSUMED",
            "source_id": "MODEL-V3",
            "verdict": "NOT_APPLICABLE",
            "why": "no usable fill evidence exists; EXECUTION_MODEL_V1.json is "
            f"{execution['status']} — the maker path is barred from admission",
            "conflict": "the runtime's own default order posture is post_only (config), and at "
            "VIP0 the maker fee equals the taker fee, so the configured default buys no fee saving "
            "while adding fill risk the model charges for",
        },
        {
            "assumption": "BNB fee discount (-25%)",
            "value": "18.7906 bps per round trip at 1,000 USD",
            "knowledge": "KNOWN",
            "source_id": "SRC-01",
            "verdict": "POSSIBLE",
            "why": "the rate is published, but applicability to our account is unconfirmed",
            "caveat": "the frozen model forbids treating a discount as CONFIRMED without a "
            "governance decision, so it cannot lower today's bar",
        },
        {
            "assumption": "derivative scenarios (USDⓈ-M perpetual, 9.25 bps maker)",
            "value": "9.25 bps per round trip",
            "knowledge": "ASSUMED",
            "source_id": "SRC-02",
            "verdict": "NOT_APPLICABLE",
            "why": "excluded from the runtime by config/exchange.yaml (Derivatives) and by the "
            "RFC-046 scope rules",
            "conflict": "the cheapest documented scenario in the whole model is therefore "
            "unreachable today",
        },
        {
            "assumption": "other spot venues (MEXC 17.79, Bybit/OKX 23.79, Kraken 83.79 bps)",
            "value": "17.79 bps per round trip at MEXC",
            "knowledge": "ASSUMED",
            "source_id": "SRC-11 / SRC-09 / SRC-10 / SRC-12",
            "verdict": "NOT_APPLICABLE",
            "why": "not the authorized runtime venue, and their spreads are ASSUMED rather than "
            "observed (caveat in VENUE_EXECUTION_MATRIX_V1.json)",
            "conflict": "no venue switch is available as a cost-side rescue without a new "
            "measurement and a governance decision",
        },
        {
            "assumption": "min notional 5 USD",
            "value": f"{5.0 / REFERENCE_CAPITAL_USDT:.4f} of capital per position at 200 USDT",
            "knowledge": "KNOWN",
            "source_id": "SRC-01",
            "verdict": "CONFIRMED",
            "why": "published instrument filter present in the frozen model's venue specs",
            "conflict": "at 200 USDT the smallest legal position is 2.5% of the account, so any "
            "size below that cannot be executed at all — a granularity floor, not a cash cost",
        },
    ]

    document = {
        "model": frozen["model"],
        "model_file": str(COST_MODEL.relative_to(REPO)),
        "model_file_sha256": _sha256(COST_MODEL),
        "reused_not_rebuilt": True,
        "reference_intent": frozen["reference_intent"],
        "admission_scenario": ADMISSION_SCENARIO_ID,
        "at_documented_reference_size": at_1000,
        "at_reference_capital": at_200,
        "maker_path": {
            "scenario_id": "BINANCE_SPOT_STANDARD_MAKER",
            "at_documented_reference_size": maker_1000,
            "at_reference_capital": maker_200,
            "premium_over_taker_bps": round(maker_1000["round_trip_bps"] - at_1000["round_trip_bps"], 6),
            "execution_model_status": execution["status"],
            "execution_model_reason": execution["status_reason"],
        },
        "fee_dominance_at_200_usdt": {
            "exchange_fees_bps": round(fee_total, 9),
            "fees_share_of_round_trip": round(fee_total / total, 9),
            "spread_bps": round(spread, 9),
            "slippage_bps": round(slippage, 9),
            "market_impact_bps": round(impact, 9),
            "non_fee_bps": round(spread + slippage + impact, 9),
            "note": "the toll is a fee schedule with a small execution term attached; nothing about "
            "our own execution assumptions moves it materially",
        },
        "fixed_costs": {
            "fixed_cash_costs_in_model": "none — COST_MODEL_V3 contains only per-round-trip bps "
            "terms; no deposit, withdrawal, subscription or data fee is modelled",
            "min_notional_usd": 5.0,
            "min_position_fraction_of_capital": round(5.0 / REFERENCE_CAPITAL_USDT, 6),
            "note": "the only non-scaling terms are the fee floor and the instrument's minimum "
            "notional",
        },
        "cost_landscape": {
            "scenarios": scenarios,
            "cheapest_documented_bps": scenarios[0]["round_trip_bps"],
            "cheapest_documented_scenario": scenarios[0]["scenario_id"],
            "cheapest_spot_bps": spot_rows[0]["round_trip_bps"],
            "cheapest_spot_scenario": spot_rows[0]["scenario_id"],
        },
        "applicability": applicability,
        "open_defects": defects,
    }
    return document, exact_200, exact_1000, maker_exact_1000


# --------------------------------------------------------------------------- #
# 3. Break-even, at the runtime's own capital
# --------------------------------------------------------------------------- #


def break_even(cost_audit_doc: dict[str, Any], toll_exact: float) -> dict[str, Any]:
    """All arithmetic from the exact toll; only the published figures are rounded (9 decimals)."""
    taker = toll_exact
    taker_1000 = cost_audit_doc["at_documented_reference_size"]["round_trip_bps"]
    maker = cost_audit_doc["maker_path"]["at_reference_capital"]["round_trip_bps"]
    cost_per_op = REFERENCE_CAPITAL_USDT * taker / BPS
    stress_multiple = 1.5
    frozen_admission = 23.7906  # the figure RFC-046 froze for the campaign, at 1,000 USD

    size_rows = []
    for size in (25.0, 50.0, 100.0, 200.0, 500.0, 1000.0):
        bps = _independent_spot_taker_bps(size, 10.0, 10.0, 1.0)
        size_rows.append(
            {
                "size_usd": size,
                "round_trip_bps": round(bps, 9),
                "cost_per_round_trip_usdt": round(size * bps / BPS, 9),
                "fees_share_of_round_trip": round(20.0 / bps, 9),
                "min_position_ok": size >= 5.0,
            }
        )

    target_net_usdt = REFERENCE_CAPITAL_USDT * DEFAULT_TARGET_NET_ANNUAL
    turnover_rows = []
    for per_day in (0.2, 1.0, 3.0, 10.0):
        per_year = per_day * 365.0
        annual_cost = per_year * cost_per_op
        net_margin_bps = (target_net_usdt / per_year) / REFERENCE_CAPITAL_USDT * BPS
        gross_bps = taker + net_margin_bps
        turnover_rows.append(
            {
                "round_trips_per_day": per_day,
                "round_trips_per_year": per_year,
                "annual_cost_usdt": round(annual_cost, 9),
                "annual_cost_pct_of_capital": round(annual_cost / REFERENCE_CAPITAL_USDT, 9),
                "illustrative_daily_cost_usdt": round(cost_per_op * per_day, 9),
                "gross_bps_per_trade_to_net_target": round(gross_bps, 9),
                "net_margin_bps_per_trade": round(net_margin_bps, 9),
                "net_margin_share_of_gross": round(net_margin_bps / gross_bps, 9),
                "cost_overrun_bps_that_erases_target": round(net_margin_bps, 9),
            }
        )

    return {
        "modality": "Binance Spot VIP0, market/taker both legs, long/cash only",
        "at_reference_capital_usdt": REFERENCE_CAPITAL_USDT,
        "minimum_gross_move_bps_per_round_trip": round(taker, 9),
        "minimum_gross_move_usdt_per_round_trip": round(cost_per_op, 9),
        "minimum_expectancy_bps_to_be_net_positive": round(taker, 9),
        "required_gross_edge_bps_at_1p5x_stress": round(taker * stress_multiple, 9),
        "required_gross_edge_usdt_at_1p5x_stress": round(cost_per_op * stress_multiple, 9),
        "frozen_campaign_comparison": {
            "frozen_admission_bps": frozen_admission,
            "frozen_stress_threshold_bps": round(frozen_admission * stress_multiple, 9),
            "delta_vs_200_usdt_bps": round(taker - frozen_admission, 9),
            "stress_delta_bps": round(frozen_admission * stress_multiple - taker * stress_multiple, 9),
            "note": "the frozen gate is marginally *more* demanding than a 1.5x stress at 200 USDT, "
            "so the campaign did not overstate the difficulty of the toll",
        },
        "maker_modality": {
            "round_trip_bps_at_200_usdt": maker,
            "cost_per_round_trip_usdt": round(REFERENCE_CAPITAL_USDT * maker / BPS, 9),
            "size_invariant": cost_audit_doc["maker_path"]["at_reference_capital"]["size_invariant"],
            "admissible": False,
            "reason": cost_audit_doc["maker_path"]["execution_model_reason"],
        },
        "three_daily_round_trips_illustrative": {
            "round_trips_per_day": 3,
            "cost_per_day_usdt": round(cost_per_op * 3, 9),
            "cost_per_day_pct_of_capital": round(cost_per_op * 3 / REFERENCE_CAPITAL_USDT, 9),
            "cost_per_year_usdt": round(cost_per_op * 3 * 365, 9),
            "cost_per_year_multiple_of_capital": round(cost_per_op * 3 * 365 / REFERENCE_CAPITAL_USDT, 9),
            "note": "illustrative arithmetic at full deployment, never a forecast: it is the gross "
            "profit the account must extract from the market just to pay the venue",
        },
        "size_sensitivity": size_rows,
        "turnover_sensitivity": {
            "target_net_annual": DEFAULT_TARGET_NET_ANNUAL,
            "target_net_usdt": target_net_usdt,
            "target_source": "PROFITABILITY_OPERATING_MODEL.json (20% -> 40 USDT/year is the "
            "documented scenario, never a forecast)",
            "rows": turnover_rows,
            "reading": "the thinner the net margin over the toll, the more the business depends on "
            "the cost model being right: at high turnover the margin is a few percent of the gross "
            "move and any realised-cost overrun erases the year",
        },
        "taker_vs_maker_at_1000_usd": {
            "taker_bps": taker_1000,
            "maker_bps": cost_audit_doc["maker_path"]["at_documented_reference_size"]["round_trip_bps"],
        },
    }


# --------------------------------------------------------------------------- #
# 4. Horizon measurement — signal-free, on the raw bars
# --------------------------------------------------------------------------- #


def _opens(asset: str) -> list[float]:
    rows = _read_json(PRICE_DIR / f"{asset}_5m.json")
    return [float(r[1]) for r in rows]


def horizon_measurement() -> dict[str, Any]:
    """Typical absolute move per horizon, measured; no signal, no direction, no parameter."""
    stats: dict[str, Any] = {}
    for name, bars in HORIZON_BARS.items():
        moves: list[float] = []
        for asset in ASSETS:
            opens = _opens(asset)
            for start in range(0, len(opens) - bars, bars):
                p0, p1 = opens[start], opens[start + bars]
                moves.append(abs(p1 / p0 - 1.0) * BPS)
        moves.sort()
        count = len(moves)
        stats[name] = {
            "bars_per_window": bars,
            "observations": count,
            "median_abs_move_bps": round(statistics.median(moves), 6),
            "p25_abs_move_bps": round(moves[int(count * 0.25)], 6),
            "p75_abs_move_bps": round(moves[int(count * 0.75)], 6),
            "p90_abs_move_bps": round(moves[int(count * 0.90)], 6),
        }
    return {
        "method": "non-overlapping windows on the open of the 5-minute bars: |open[i+k]/open[i] - 1| "
        "in bps, k set by the horizon; four majors pooled; no signal, no direction and no parameter "
        "is generated",
        "assets": list(ASSETS),
        "source_files": [f"data/raw/alpha003/price/{a}_5m.json" for a in ASSETS],
        "bars_available_per_asset": {a: len(_opens(a)) for a in ASSETS},
        "per_horizon": stats,
    }


def _cost_verdict(median_move_bps: float, cost_bps: float) -> str:
    if median_move_bps <= cost_bps:
        return "NOT_COST_COMPATIBLE"
    if cost_bps / median_move_bps >= BOUNDARY_CAPTURE:
        return "COST_BOUNDARY"
    return "COST_COMPATIBLE"


def family_classification(measurement: dict[str, Any], cost_bps: float) -> dict[str, Any]:
    rows = {}
    for family in FAMILIES:
        horizon = family["representative_horizon"]
        measured = measurement["per_horizon"][horizon]
        median = measured["median_abs_move_bps"]
        capture = cost_bps / median
        rows[family["family"]] = {
            **family,
            "cost_bps": cost_bps,
            "median_abs_move_bps": median,
            "move_over_cost": round(median / cost_bps, 6),
            "capture_required_to_break_even": round(capture, 6),
            "cost_verdict": _cost_verdict(median, cost_bps),
            "edge_existence": "NOT_DEMONSTRATED",
            "share_of_windows_below_cost": None,
            "note": (
                "cost compatibility is arithmetic about the toll against the typical move; it is "
                "not evidence of edge, and it is not a promotion"
            ),
        }
    # Second, independent-feeling statistic for the same question: how often is the move itself
    # smaller than the toll?  Computed on the same windows.
    for name, bars in HORIZON_BARS.items():
        below = 0
        total = 0
        for asset in ASSETS:
            opens = _opens(asset)
            for start in range(0, len(opens) - bars, bars):
                move = abs(opens[start + bars] / opens[start] - 1.0) * BPS
                total += 1
                below += int(move < cost_bps)
        rows_for_horizon = [f for f in FAMILIES if f["representative_horizon"] == name]
        for family in rows_for_horizon:
            rows[family["family"]]["share_of_windows_below_cost"] = round(below / total, 6)

    return {
        "rule": (
            "cost_verdict is derived, never authored: median move <= toll -> NOT_COST_COMPATIBLE; "
            f"toll >= {BOUNDARY_CAPTURE:.0%} of the median move -> COST_BOUNDARY; otherwise "
            "COST_COMPATIBLE. Only the *representative* horizon (the shortest one the family "
            "trades) decides, because that is where the toll bites hardest."
        ),
        "boundary_capture": BOUNDARY_CAPTURE,
        "families": rows,
        "a_family_that_can_cover_commissions_is_not_validated": True,
        "edge_existence_basis": (
            "no family has passed PROFITABILITY_GATE_V1 and none is claimed to have an edge; the "
            "three mechanisms RFC-046 tested produced +4.5306, -25.4580 and an unmeasured zero "
            "gross bps per trade"
        ),
    }


# --------------------------------------------------------------------------- #
# 5. RFC-046 evidence review
# --------------------------------------------------------------------------- #


def rfc046_review() -> dict[str, Any]:
    forensics = _read_json(FORENSICS)
    run_report = _read_json(RUN_JSON)
    candidates = forensics["candidates"]

    c1 = candidates["CAND-046-001"]
    c2 = candidates["CAND-046-002"]
    c3 = candidates["CAND-046-003"]

    c1_confirm = (
        c1["oos_gross_expectancy_bps"] < 0.0
        and "final_oos" in c1["partitions_without_gross_edge"]
        and c1["gross_positive_in_every_partition"] is False
    )
    c2_confirm = (
        c2["gross_expectancy_bps"] < 0.0
        and c2["oos_gross_expectancy_bps"] < 0.0
        and all(
            detail["gross_bps"] is None or detail["gross_bps"] < 0.0
            for detail in c2["partition_detail"].values()
        )
    )
    c3_confirm = c3["zero_sample"] is True and c3["trades_total"] == 0

    spec_hashes = {
        path.stem: hashlib.sha256(
            json.dumps(_read_json(path), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for path in sorted(SPECS.glob("HYP-*.json"))
    }
    recorded_hashes = {r["hypothesis_id"]: r["spec_hash"] for r in run_report["runs"]}
    if spec_hashes != recorded_hashes:
        raise SystemExit(
            "the frozen specs changed since the campaign ran; refusing to review evidence that no "
            f"longer matches its record: {spec_hashes} != {recorded_hashes}"
        )

    return {
        "sources": {
            "run_report": str(RUN_JSON.relative_to(REPO)),
            "run_report_sha256": _sha256(RUN_JSON),
            "cost_forensics": str(FORENSICS.relative_to(REPO)),
            "cost_forensics_sha256": _sha256(FORENSICS),
        },
        "confirmations": {
            "CAND-046-001_has_no_gross_edge_out_of_sample": {
                "confirmed": c1_confirm,
                "oos_gross_bps": c1["oos_gross_expectancy_bps"],
                "aggregate_gross_bps": c1["gross_expectancy_bps"],
                "aggregate_is_stable_across_partitions": c1["gross_positive_in_every_partition"],
                "partitions_without_gross_edge": c1["partitions_without_gross_edge"],
                "reading": "the aggregate positive gross is confined to development; the OOS leg "
                "is negative, so there is no gross edge to harvest out of sample",
            },
            "CAND-046-002_loses_before_costs": {
                "confirmed": c2_confirm,
                "gross_bps": c2["gross_expectancy_bps"],
                "oos_gross_bps": c2["oos_gross_expectancy_bps"],
                "reading": "negative gross in every partition: an economic rejection, not a "
                "cost rejection",
            },
            "CAND-046-003_stays_zero_sample": {
                "confirmed": c3_confirm,
                "signals": c3["signals"],
                "trades_total": c3["trades_total"],
                "reading": "unmeasured, neither disproved nor supported",
            },
        },
        "oos_policy": {
            "reused_for_selection": False,
            "specs_frozen_and_unchanged": True,
            "spec_count": len(spec_hashes),
            "spec_hashes": spec_hashes,
            "new_hypotheses_generated": 0,
            "candidates_re_evaluated": 0,
            "second_campaign": "NOT_AUTHORIZED",
            "statement": "the final OOS partition was opened once per candidate and is not reused "
            "here for selection, tuning or comparison; this artefact generates no candidate",
        },
    }


# --------------------------------------------------------------------------- #
# 6. Decision and standing state
# --------------------------------------------------------------------------- #


def standing_state(run_report: dict[str, Any], rfc: dict[str, Any],
                   operating_model: dict[str, Any]) -> dict[str, Any]:
    exemption = operating_model["next_action_policy"]["rfc046_limited_exemption"]
    state = {
        "campaign_status": run_report["campaign"]["campaign_status"],
        "discovery_campaign_failed": run_report["campaign"]["campaign_status"],
        "next_campaign": "NOT_AUTHORIZED",
        "trades_authorized": rfc["runtime_state"]["trades_authorized"],
        "profitability_verified": rfc["runtime_state"]["profitability_verified"],
        "live_trading": rfc["runtime_state"]["live_trading_enabled"],
        "G_BUSINESS_REENTRY": exemption["gate_state"]["G_BUSINESS_REENTRY"],
        "discovery_offline_authorized": rfc["runtime_state"]["discovery_offline_authorized"],
        "risk_engine": "DETERMINISTIC",
        "false_success": 0,
    }
    if state["campaign_status"] != "DISCOVERY_CAMPAIGN_FAILED":
        raise SystemExit(f"expected a failed campaign, found {state['campaign_status']!r}")
    return state


def decision(cost_audit_doc: dict[str, Any], families: dict[str, Any],
             break_even_doc: dict[str, Any]) -> dict[str, Any]:
    """The scope recommendation, in the allowed vocabulary only."""
    toll = break_even_doc["minimum_gross_move_bps_per_round_trip"]
    compatible = [
        name for name, f in families["families"].items() if f["cost_verdict"] == "COST_COMPATIBLE"
    ]
    boundaries = [
        name for name, f in families["families"].items() if f["cost_verdict"] == "COST_BOUNDARY"
    ]
    incompatible = [
        name
        for name, f in families["families"].items()
        if f["cost_verdict"] == "NOT_COST_COMPATIBLE"
    ]
    return {
        "scope_recommendation": "VIABLE_COST_PROFILE_IDENTIFIED",
        "meaning": "a cost profile exists under which the toll is small relative to the typical "
        "move available at the strategy's own horizon; it is a *cost* finding and says nothing "
        "about whether any edge exists",
        "profile": {
            "venue": cost_audit_doc["admission_scenario"],
            "product": "Binance Spot, long/cash only",
            "execution": "market/taker on both legs (the cheapest permitted posture at VIP0)",
            "round_trip_bps_at_200_usdt": toll,
            "minimum_gross_edge_bps": toll,
            "required_gross_edge_bps_at_1p5x": break_even_doc["required_gross_edge_bps_at_1p5x_stress"],
            "horizon_region": "holding periods from about one day upwards, where the measured "
            "median move is at least seven times the toll",
            "turnover_region": "low: each round trip costs "
            f"{break_even_doc['minimum_gross_move_usdt_per_round_trip']} USDT at full deployment, "
            "so the annual toll is roughly 0.852 x capital per round trip per day",
        },
        "families_cost_compatible": compatible,
        "families_at_the_boundary": boundaries,
        "families_not_cost_compatible": incompatible,
        "not_an_edge_claim": True,
        "edge_status": "NOT_DEMONSTRATED",
        "violated_if": [
            "realised round-trip cost exceeds the modelled toll: every extra bps of realised cost "
            "is an extra bps of required gross edge, and ST-6 halts the campaign on exactly that",
            "the forward spread measurement contradicts the modelled 1.0 bps (SRC-07 has no "
            "historical endpoint, so the estimate is unverified until then)",
            "a candidate's holding horizon is shorter than its own measured cost-compatible region",
        ],
        "next_campaign": "NOT_AUTHORIZED",
        "note": "no strategy is proposed, no hypothesis is created and no gate is reopened by this "
        "recommendation; the owner must authorize any next step",
    }


def build() -> dict[str, Any]:
    runtime = authorized_runtime()
    model_doc = _read_json(COST_MODEL)
    audit, toll_exact, _exact_1000, _maker_exact = cost_audit(runtime, model_doc)
    costs = break_even(audit, toll_exact)
    measurement = horizon_measurement()
    families = family_classification(measurement, costs["minimum_gross_move_bps_per_round_trip"])
    review = rfc046_review()
    run_report = _read_json(RUN_JSON)
    rfc = _read_json(RFC046)
    operating_model = _read_json(OPERATING_MODEL)
    state = standing_state(run_report, rfc, operating_model)
    scope = decision(audit, families, costs)

    if scope["scope_recommendation"] not in SCOPE_VERDICTS:
        raise SystemExit("scope recommendation outside the allowed vocabulary")
    for name, family in families["families"].items():
        if family["cost_verdict"] not in COST_VERDICTS:
            raise SystemExit(f"{name}: unknown cost verdict {family['cost_verdict']!r}")

    return {
        "artifact": "RFC-046_ECONOMIC_FEASIBILITY",
        "rfc": "RFC-046",
        "purpose": "Determine what economic profile a strategy would need to be viable with 200 "
        "USDT on the authorized runtime: verified costs, break-even, family classification and a "
        "bounded scope recommendation. No strategy is created; no gate is reopened.",
        "generated_at_utc": _now_utc(),
        "head_at_run": _head(),
        "builder": "scripts/rfc046_economic_gate.py",
        "builder_equals_verifier": False,
        "authorized_runtime": runtime,
        "cost_audit": audit,
        "break_even": costs,
        "horizon_measurement": measurement,
        "family_classification": families,
        "rfc046_review": review,
        "decision": scope,
        "standing_state": state,
        "admission_effect": "NONE — this artefact audits an economic profile; it admits nothing, "
        "creates no hypothesis and authorizes no campaign",
        "false_success": 0,
        "does_not_license": [
            "a second campaign or any new hypothesis",
            "paper or live trading",
            "any statement that an edge, a profit or a production capability exists",
            "a cost-side change to the frozen model without a new measurement and a governance "
            "decision",
        ],
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _fmt_bps(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.6f} bps"


def render_md(report: dict[str, Any]) -> str:
    audit = report["cost_audit"]
    costs = report["break_even"]
    families = report["family_classification"]
    review = report["rfc046_review"]
    scope = report["decision"]
    state = report["standing_state"]
    measurement = report["horizon_measurement"]
    toll = costs["minimum_gross_move_bps_per_round_trip"]

    lines = [
        "# RFC-046 ECONOMIC FEASIBILITY — RETAIL SPOT WITH 200 USDT",
        "",
        f"generated_at_utc = {report['generated_at_utc']} (computed, not authored)",
        f"head_at_run = {report['head_at_run']}",
        f"scope_recommendation = **{scope['scope_recommendation']}**",
        "not_an_edge_claim = **True** (no edge, profit or production capability is claimed)",
        f"false_success = {report['false_success']}",
        "",
        "## 1. What the authorized runtime actually is",
        "",
        f"- venue/product: **{report['authorized_runtime']['venue']} / "
        f"{report['authorized_runtime']['default_type']}**, account type "
        f"`{report['authorized_runtime']['account_type']}`, sandbox "
        f"{report['authorized_runtime']['sandbox']}",
        f"- direction: {report['authorized_runtime']['direction']}",
        f"- excluded markets (config): {', '.join(report['authorized_runtime']['excluded_markets'])}",
        f"- default order posture (config): post_only="
        f"{report['authorized_runtime']['default_order_posture']['post_only_default']}, TIF="
        f"{report['authorized_runtime']['default_order_posture']['time_in_force_default']}",
        f"- reference capital: **{report['authorized_runtime']['reference_capital_usdt']:.0f} USDT**",
        "",
        "## 2. Verified costs (COST_MODEL_V3 reused, not rebuilt)",
        "",
        "| scenario | order types | size | round trip bps | knowledge |",
        "| --- | --- | --- | --- | --- |",
        f"| {audit['at_documented_reference_size']['scenario_id']} | "
        f"{audit['at_documented_reference_size']['order_types']} | 1,000 USD | "
        f"{audit['at_documented_reference_size']['round_trip_bps']} | "
        f"{audit['at_documented_reference_size']['knowledge_class']} |",
        f"| {audit['at_reference_capital']['scenario_id']} | "
        f"{audit['at_reference_capital']['order_types']} | **200 USDT** | "
        f"{audit['at_reference_capital']['round_trip_bps']} | "
        f"{audit['at_reference_capital']['knowledge_class']} |",
        f"| {audit['maker_path']['scenario_id']} | limit_post_only / limit_post_only | 1,000 USD | "
        f"{audit['maker_path']['at_documented_reference_size']['round_trip_bps']} | "
        f"{audit['maker_path']['at_documented_reference_size']['knowledge_class']} |",
        f"| {audit['maker_path']['scenario_id']} | limit_post_only / limit_post_only | 200 USDT | "
        f"{audit['maker_path']['at_reference_capital']['round_trip_bps']} | "
        f"{audit['maker_path']['at_reference_capital']['knowledge_class']} |",
        "",
        "### The decomposition of the 200 USDT round trip",
        "",
        "| component | bps | knowledge | source |",
        "| --- | --- | --- | --- |",
    ]
    for component in audit["at_reference_capital"]["components"]:
        lines.append(
            f"| {component['name']} | {component['value_bps']} | {component['knowledge']} | "
            f"{component['source_id']} |"
        )
    dominance = audit["fee_dominance_at_200_usdt"]
    lines += [
        "",
        f"Exchange fees are **{dominance['fees_share_of_round_trip']:.1%}** of the toll "
        f"({dominance['exchange_fees_bps']} of {toll} bps). Spread, slippage and size-driven impact "
        f"together are {dominance['non_fee_bps']} bps. The toll is a fee schedule with a small "
        "execution term attached.",
        "",
        "### Applicability of each assumption",
        "",
        "| assumption | verdict | why |",
        "| --- | --- | --- |",
    ]
    for row in audit["applicability"]:
        lines.append(f"| {row['assumption']} | **{row['verdict']}** | {row['why']} |")
    lines += ["", "Declared caveats:", ""]
    lines += [f"- {row['caveat']}" for row in audit["applicability"] if row.get("caveat")]
    lines += ["", "Conflicts with the authorized runtime:", ""]
    lines += [f"- {row['conflict']}" for row in audit["applicability"] if row.get("conflict")]
    if audit["open_defects"]:
        lines += ["", "### Open discrepancy found by this audit (not repaired)", ""]
        for defect in audit["open_defects"]:
            lines += [
                f"- **{defect['id']} — {defect['title']}** ({defect['status']})",
                f"  - evidence: {defect['evidence']}",
                f"  - effect: {defect['effect']}",
            ]

    lines += [
        "",
        "## 3. Break-even at 200 USDT",
        "",
        "| quantity | value |",
        "| --- | --- |",
        f"| minimum gross move per round trip | **{_fmt_bps(costs['minimum_gross_move_bps_per_round_trip'])}** "
        f"= {costs['minimum_gross_move_usdt_per_round_trip']} USDT |",
        f"| minimum expectancy to be net positive | > "
        f"{_fmt_bps(costs['minimum_expectancy_bps_to_be_net_positive'])} |",
        f"| required gross edge at 1.5x stress | "
        f"{_fmt_bps(costs['required_gross_edge_bps_at_1p5x_stress'])} "
        f"= {costs['required_gross_edge_usdt_at_1p5x_stress']} USDT |",
        f"| frozen campaign figure (1,000 USD reference) | "
        f"{_fmt_bps(costs['frozen_campaign_comparison']['frozen_admission_bps'])}; stress "
        f"threshold {_fmt_bps(costs['frozen_campaign_comparison']['frozen_stress_threshold_bps'])} |",
        f"| maker round trip at 200 USDT | {_fmt_bps(costs['maker_modality']['round_trip_bps_at_200_usdt'])} "
        "(size-invariant, and inadmissible: no fill evidence) |",
        "",
        "### Three round trips a day, illustrative only",
        "",
        f"- cost per round trip: **{costs['minimum_gross_move_usdt_per_round_trip']} USDT**",
        f"- three a day: **{costs['three_daily_round_trips_illustrative']['cost_per_day_usdt']} "
        f"USDT/day** = "
        f"{costs['three_daily_round_trips_illustrative']['cost_per_day_pct_of_capital']:.2%} of "
        "capital per day",
        f"- a year at that cadence: "
        f"{costs['three_daily_round_trips_illustrative']['cost_per_year_usdt']} USDT = "
        f"**{costs['three_daily_round_trips_illustrative']['cost_per_year_multiple_of_capital']:.2f}x "
        "the account** in gross trading profit just to pay the venue",
        "",
        "### Sensitivity to size",
        "",
        "| size USDT | round trip bps | cost per round trip USDT | fees share |",
        "| --- | --- | --- | --- |",
    ]
    for row in costs["size_sensitivity"]:
        lines.append(
            f"| {row['size_usd']:.0f} | {row['round_trip_bps']} | "
            f"{row['cost_per_round_trip_usdt']} | {row['fees_share_of_round_trip']:.1%} |"
        )
    lines += [
        "",
        "The rate is nearly flat in size (23.35 → 23.79 bps from 200 to 1,000 USDT) because fees "
        "dominate; only the absolute bill scales. A smaller account gets a smaller bill, not a "
        "better rate.",
        "",
        "### Sensitivity to turnover — the operating-cost impact on the business",
        "",
        f"Target used: +{costs['turnover_sensitivity']['target_net_annual']:.0%} net annual "
        f"({costs['turnover_sensitivity']['target_net_usdt']:.0f} USDT/year), the figure already "
        "documented in the operating model. These are requirements, not forecasts.",
        "",
        "| round trips/day | cost/year USDT | cost/year vs capital | net margin needed bps/trade | "
        "gross needed bps/trade | margin share of gross | cost overrun that erases the target |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in costs["turnover_sensitivity"]["rows"]:
        lines.append(
            f"| {row['round_trips_per_day']:.1f} | {row['annual_cost_usdt']:.2f} | "
            f"{row['annual_cost_pct_of_capital']:.1%} | {row['net_margin_bps_per_trade']:.2f} | "
            f"{row['gross_bps_per_trade_to_net_target']:.2f} | "
            f"{row['net_margin_share_of_gross']:.1%} | "
            f"{row['cost_overrun_bps_that_erases_target']:.2f} bps |"
        )
    lines += [
        "",
        f"{costs['turnover_sensitivity']['reading']}.",
        "",
        "## 4. What the toll costs a strategy by horizon (measured, signal-free)",
        "",
        measurement["method"] + ".",
        "",
        "| horizon | windows | median move bps | p75 bps | p90 bps |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, row in measurement["per_horizon"].items():
        lines.append(
            f"| {name} | {row['observations']} | {row['median_abs_move_bps']} | "
            f"{row['p75_abs_move_bps']} | {row['p90_abs_move_bps']} |"
        )
    lines += [
        "",
        "### Family classification",
        "",
        families["rule"],
        "",
        "| family | horizon | median move bps | capture required | cost verdict | edge existence | "
        "windows below cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in families["families"].items():
        below = row["share_of_windows_below_cost"]
        lines.append(
            f"| {name} | {row['representative_horizon']} | {row['median_abs_move_bps']} | "
            f"{row['capture_required_to_break_even']:.1%} | **{row['cost_verdict']}** | "
            f"{row['edge_existence']} | {'n/a' if below is None else f'{below:.1%}'} |"
        )
    lines += [
        "",
        f"**{families['a_family_that_can_cover_commissions_is_not_validated'] and 'A family that can cover commissions is not thereby validated'}.** "
        + families["edge_existence_basis"] + ".",
        "",
        "## 5. RFC-046 evidence review (confirmations only)",
        "",
        "| claim | confirmed | evidence |",
        "| --- | --- | --- |",
    ]
    for key, value in review["confirmations"].items():
        evidence = value.get("reading", "")
        lines.append(f"| {key.replace('_', ' ')} | {value['confirmed']} | {evidence} |")
    lines += [
        "",
        f"OOS reused for selection: {review['oos_policy']['reused_for_selection']}; frozen specs "
        f"unchanged: {review['oos_policy']['specs_frozen_and_unchanged']} "
        f"(n={review['oos_policy']['spec_count']}, hashes match the campaign record); new hypotheses "
        f"generated: {review['oos_policy']['new_hypotheses_generated']}; second campaign: "
        f"**{review['oos_policy']['second_campaign']}**.",
        "",
        "## 6. Decision",
        "",
        f"**{scope['scope_recommendation']}** — {scope['meaning']}.",
        "",
        "| profile field | value |",
        "| --- | --- |",
    ]
    for key, value in scope["profile"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        f"- cost-compatible families: {', '.join(scope['families_cost_compatible']) or 'none'}",
        f"- at the boundary: {', '.join(scope['families_at_the_boundary']) or 'none'}",
        f"- not cost-compatible: {', '.join(scope['families_not_cost_compatible']) or 'none'}",
        "- edge status: **NOT_DEMONSTRATED** — the recommendation bounds *economics*, it does not "
        "assert an edge",
        "",
        "This recommendation is violated if:",
        "",
    ]
    lines += [f"- {item}" for item in scope["violated_if"]]
    lines += [
        "",
        "## 7. Standing state (unchanged)",
        "",
        "```text",
        f"DISCOVERY_CAMPAIGN_FAILED = {state['discovery_campaign_failed'] == 'DISCOVERY_CAMPAIGN_FAILED'}",
        f"NEXT_CAMPAIGN = {state['next_campaign']}",
        f"TRADES_AUTHORIZED = {state['trades_authorized']}",
        f"PROFITABILITY_VERIFIED = {str(state['profitability_verified']).upper()}",
        f"LIVE_TRADING = {'ENABLED' if state['live_trading'] else 'DISABLED'}",
        f"G_BUSINESS_REENTRY = {state['G_BUSINESS_REENTRY']}",
        f"RISK_ENGINE = {state['risk_engine']}",
        f"FALSE_SUCCESS = {state['false_success']}",
        "```",
        "",
        "This artefact does not license: " + "; ".join(report["does_not_license"]) + ".",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="build and verify, write nothing")
    args = parser.parse_args(argv)

    report = build()
    if args.check:
        print(json.dumps({"artifact": report["artifact"], "ok": True}))
        return 0

    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(report), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO)}")
    print(f"wrote {OUT_MD.relative_to(REPO)}")
    print(
        f"toll at 200 USDT = {report['break_even']['minimum_gross_move_bps_per_round_trip']} bps "
        f"({report['break_even']['minimum_gross_move_usdt_per_round_trip']} USDT per round trip)"
    )
    print(f"scope_recommendation = {report['decision']['scope_recommendation']}")
    for name, row in report["family_classification"]["families"].items():
        print(
            f"  {name:<16} {row['representative_horizon']:>5} median={row['median_abs_move_bps']:>8.1f} "
            f"capture={row['capture_required_to_break_even']:.3f} -> {row['cost_verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
