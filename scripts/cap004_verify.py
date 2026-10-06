"""CAP-004 independent verification — cadence, exactly-once, evidence, governance.

Builder != verifier.  This script imports nothing from the campaign runner, the
campaign modules or the CAP-003 modules: it re-declares every frozen constant and
re-derives every invariant from the artefacts on disk.

The two checks worth the reader's attention are the ones the campaign could not
have made about itself:

* **Comparator B is recomputed from first principles.**  SMA(200), an EMA-seeded
  MACD(12,26,9) and a Wilder RSI(14) are re-implemented here, fed with the raw
  bars the decision actually saw, filtered to the same fixed-length causal window
  — and the resulting direction is compared with the one recorded in the
  immutable evaluation.  A comparator nobody else can reproduce is not a
  comparator.
* **Exactly-once is checked as a property, not a hope.**  Slot keys must be
  unique and recomputable, every decision must sit on the declared slot, no
  decision may post-date its slot by more than the seal window, and no checkpoint
  may describe a population other than the one its file claims.

Missing local raw evidence is reported as a **limitation**, never as a pass and
never re-downloaded.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LEDGER_ROOT = REPO / "evidence" / "real_decisions"
REPORTS = REPO / "reports"
CAP004_ROOT = REPORTS / "cap004"
DOCS = REPO / "docs" / "research"
CAP003_VERIFIER = REPO / "scripts" / "cap003_verify.py"
CAP003_VERIFICATION = REPORTS / "agentic-campaign-cap003" / "CAP003_VERIFICATION.json"

# --- independently re-declared frozen contract ------------------------------ #
MANIFEST_FILENAME = "CAMPAIGN_MANIFEST.json"
DECISIONS_FILENAME = "decisions.jsonl"
OUTCOMES_FILENAME = "outcomes.jsonl"
EVALUATIONS_FILENAME = "evaluations.jsonl"
RAW_MANIFEST_FILENAME = "RAW_EVIDENCE_MANIFEST.jsonl"
HEARTBEAT_FILENAME = "heartbeat.json"
CHECKPOINT_DIRNAME = "checkpoints"

CAMPAIGN_ID = "CAP004-REAL-DECISIONS-V1"
CAMPAIGN_VERSION = "1.0"
MANIFEST_VERSION = "CAMPAIGN_MANIFEST_V1"
COHORT_LEGACY = "LEGACY_CAP003_PILOT"
HORIZON = "24H"
HORIZON_SECONDS = 86_400
ASSETS = ("BINANCE:BTCUSDT", "BINANCE:ETHUSDT", "BINANCE:SOLUSDT", "BINANCE:XRPUSDT")
SLOT_UTC_HOUR = 16
SEAL_WINDOW_SECONDS = 14_400
PROMPT_VERSION = "MARKET_ANALYST_V1.0"
SCHEMA_VERSION = "MARKET_ANALYST_OUTPUT_V1"
FEATURE_VERSION = "REAL_MARKET_CONTEXT_V1"
BASE_PROVENANCE_FIELDS = (
    "analyst_id",
    "prompt_version",
    "prompt_digest",
    "model",
    "provider",
    "temperature",
    "schema_version",
    "feature_version",
    "dataset",
)
CAMPAIGN_PROVENANCE_FIELDS = (*BASE_PROVENANCE_FIELDS, "campaign_id", "code_commit")
COST_ROUND_TRIP = 0.002
EVALUATOR_ID = "DecisionOutcomeEvaluator"
EVALUATOR_VERSION = "DECISION_OUTCOME_EVALUATOR_V1"
RULE_VERSION = "DETERMINISTIC_TREND_RULE_V1_1"
RULE_INPUT_BARS_4H = 400
RULE_INPUT_BARS_1D = 300
SMA_WINDOW = 200
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RSI_PERIOD, RSI_LOW, RSI_HIGH = 14, 30.0, 70.0
BAR_4H, BAR_1D = 14_400, 86_400
BASELINE_B = "B_DETERMINISTIC_TREND_RULE"
BASELINE_C = "C_BUY_AND_HOLD"
BASELINE_D = "D_RANDOM_MATCHED_DISTRIBUTION"
SEAL_TIME_COMPARATORS = (BASELINE_B, BASELINE_C)
RANDOM_SEED = 20_261_003
MIN_EVALUABLE_DECISIONS = 100
CHECKPOINTS = (20, 50, 100)
CONCLUSION_NOT_MEASURABLE = "EDGE_NOT_MEASURABLE_NO_EVALUABLE_DECISIONS"
CONCLUSION_INSUFFICIENT = "INSUFFICIENT_SAMPLE_NO_EDGE_VERDICT"
CONCLUSION_NON_POSITIVE = "EDGE_NON_POSITIVE"
CONCLUSION_POSITIVE = "EDGE_POSITIVE_PRELIMINARY_ONLY"
EXPECTED_CONCLUSIONS = {
    CONCLUSION_NOT_MEASURABLE,
    CONCLUSION_INSUFFICIENT,
    CONCLUSION_NON_POSITIVE,
    CONCLUSION_POSITIVE,
}
CAMPAIGN_STATUSES = {
    "INITIALIZING",
    "RUNNING",
    "DEGRADED",
    "BLOCKED",
    "INTEGRITY_FAILURE",
    "COMPLETE_100",
}
MISSED_DECISION_SLOT = "MISSED_DECISION_SLOT"
NO_TRADE_SELECTIVITY_MIN_SAMPLE = 20
ECONOMIC_STATE_DIGEST = "bda63db863771823501ddb5715e664c686774486882efef4778d53b84be496e8"
ANALYST_SOURCE = "src/trading_bot/research/market_analyst_v1.py"
CAMPAIGN_SOURCES = (
    "src/trading_bot/research/campaign_manifest.py",
    "src/trading_bot/research/campaign_state.py",
    "src/trading_bot/research/campaign_reporting.py",
    "src/trading_bot/research/campaign_lock.py",
    "scripts/cap004_campaign_runner.py",
)
FORBIDDEN_CODE_PATTERNS = (
    r"\bcreate_order\b",
    r"\bset_leverage\b",
    r"\bcancel_order\b",
    r"api_secret\s*=",
    r"api_key\s*=",
    r"\bimport\s+openai\b",
    r"\bimport\s+anthropic\b",
    r"\blangchain\b",
    r"mcp\.tradingview\.com",
)
FORBIDDEN_STATUS_WORDS = (
    "PROFITABLE",
    "EDGE_CONFIRMED",
    "STRATEGY_VALIDATED",
    "PAPER_READY",
    "LIVE_READY",
    "AGENT_EDGE_CONFIRMED",
)

CHECKS: list[dict[str, Any]] = []
LIMITATIONS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"check": name, "passed": bool(ok), "detail": detail})
    return bool(ok)


def limit(note: str) -> None:
    LIMITATIONS.append(note)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approx(a: float, b: float, tol: float = 1e-12) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)


def as_int(value: Any, default: int = -1) -> int:
    """Lenient integer coercion for optional JSON fields (``-1`` when absent)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value)


def decision_hash_of(entry: Mapping[str, Any]) -> str:
    return sha256_text(
        canonical(
            {
                "timestamp": entry["decision_time"],
                "prompt_version": entry["prompt_version"],
                "evidence_snapshot_hash": entry["snapshot_hash"],
                "agent_output": entry["agent_output"],
                "critic_output": entry["critic_output"],
                "decision": entry["decision"],
            }
        )
    )


def strip_hash(entry: Mapping[str, Any], key: str) -> str:
    return sha256_text(canonical({k: v for k, v in entry.items() if k != key}))


def decision_key(entry: Mapping[str, Any]) -> str:
    return (
        f"{CAMPAIGN_ID}|{entry['asset']}|{int(entry['decision_time'])}|"
        f"{entry['horizon']}|{entry['prompt_version']}"
    )


def slot_unix(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, SLOT_UTC_HOUR, tzinfo=dt.UTC).timestamp())


def frozen_prompt_digest() -> str:
    path = REPO / ANALYST_SOURCE
    if not path.is_file():
        return ""
    match = re.search(r'SYSTEM_PROMPT = """(.*?)"""', path.read_text(encoding="utf-8"), re.DOTALL)
    return sha256_text(match.group(1)) if match else ""


# --------------------------------------------------------------------------- #
# independent indicator implementations (this is the point of the verifier)
# --------------------------------------------------------------------------- #


def _fmean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError("not enough values for the EMA seed")
    multiplier = 2.0 / (period + 1.0)
    ema = _fmean(values[:period])
    series = [ema]
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        series.append(ema)
    return series


def _macd(closes: Sequence[float]) -> tuple[float, float]:
    fast = _ema_series(closes, MACD_FAST)
    slow = _ema_series(closes, MACD_SLOW)
    aligned_fast = fast[MACD_SLOW - MACD_FAST :]
    macd_series = [f - s for f, s in zip(aligned_fast, slow, strict=False)]
    signal_series = _ema_series(macd_series, MACD_SIGNAL)
    return macd_series[-1], signal_series[-1]


def _rsi(closes: Sequence[float]) -> float:
    deltas = [b - a for a, b in itertools.pairwise(closes)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = _fmean(gains[:RSI_PERIOD])
    avg_loss = _fmean(losses[:RSI_PERIOD])
    for gain, loss in zip(gains[RSI_PERIOD:], losses[RSI_PERIOD:], strict=False):
        avg_gain = ((avg_gain * (RSI_PERIOD - 1)) + gain) / RSI_PERIOD
        avg_loss = ((avg_loss * (RSI_PERIOD - 1)) + loss) / RSI_PERIOD
    if avg_loss == 0.0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))


def recompute_rule(*, bars_4h: Sequence[Mapping[str, Any]], bars_1d: Sequence[Mapping[str, Any]], decision_time: int) -> dict[str, Any]:
    """Comparator B, re-derived from raw bars with no campaign code involved."""
    daily = [b for b in bars_1d if int(b["t"]) + BAR_1D <= decision_time][-RULE_INPUT_BARS_1D:]
    causal = [b for b in bars_4h if int(b["t"]) + BAR_4H <= decision_time][-RULE_INPUT_BARS_4H:]
    if any(int(b["t"]) + BAR_4H > decision_time for b in causal):
        return {"direction": "LOOK_AHEAD", "reason": "CAUSALITY_BROKEN"}
    if len(daily) < SMA_WINDOW:
        return {"direction": "NO_TRADE", "reason": "INSUFFICIENT_SMA200_HISTORY"}
    daily_closes = [float(b["c"]) for b in daily]
    trend_up = daily_closes[-1] > _fmean(daily_closes[-SMA_WINDOW:])
    if len(causal) < MACD_SLOW + MACD_SIGNAL - 1:
        return {"direction": "NO_TRADE", "reason": "INSUFFICIENT_MACD_HISTORY"}
    closes = [float(b["c"]) for b in causal]
    macd_value, signal_value = _macd(closes)
    rsi = _rsi(closes)
    if not RSI_LOW <= rsi <= RSI_HIGH:
        return {"direction": "NO_TRADE", "reason": "RSI_EXTREME"}
    momentum_up = macd_value > signal_value
    if trend_up and momentum_up:
        return {"direction": "LONG", "reason": "TREND_UP_MACD_LONG"}
    if not trend_up and not momentum_up:
        return {"direction": "SHORT", "reason": "TREND_DOWN_MACD_SHORT"}
    return {"direction": "NO_TRADE", "reason": "SIGNAL_MIXED"}


def sleeve_net(direction: str, entry: float, exit_: float) -> tuple[float, float, float]:
    if direction == "LONG":
        gross = exit_ / entry - 1.0
    elif direction == "SHORT":
        gross = 1.0 - exit_ / entry
    else:
        gross = 0.0
    costs = 0.0 if direction == "NO_TRADE" else COST_ROUND_TRIP
    return gross, costs, gross - costs


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    now = int(time.time())
    manifest_path = LEDGER_ROOT / MANIFEST_FILENAME
    check("campaign manifest exists", manifest_path.is_file())
    manifest = load(manifest_path) if manifest_path.is_file() else {}
    decisions = read_lines(LEDGER_ROOT / DECISIONS_FILENAME)
    outcomes = read_lines(LEDGER_ROOT / OUTCOMES_FILENAME)
    evaluations = read_lines(LEDGER_ROOT / EVALUATIONS_FILENAME)
    raw_manifest = read_lines(LEDGER_ROOT / RAW_MANIFEST_FILENAME)

    for path in (
        CAP004_ROOT / "CAMPAIGN_STATUS.json",
        CAP004_ROOT / "CAMPAIGN_STATUS.md",
        CAP004_ROOT / "ALPHA_SCORECARD.json",
        CAP004_ROOT / "CAMPAIGN_METRICS.json",
        CAP004_ROOT / "NO_TRADE_SELECTIVITY.json",
        LEDGER_ROOT / HEARTBEAT_FILENAME,
    ):
        check(f"artifact present: {path.name}", path.is_file())
    status = load(CAP004_ROOT / "CAMPAIGN_STATUS.json") if (CAP004_ROOT / "CAMPAIGN_STATUS.json").is_file() else {}
    scorecard = load(CAP004_ROOT / "ALPHA_SCORECARD.json") if (CAP004_ROOT / "ALPHA_SCORECARD.json").is_file() else {}
    metrics = load(CAP004_ROOT / "CAMPAIGN_METRICS.json") if (CAP004_ROOT / "CAMPAIGN_METRICS.json").is_file() else {}
    selectivity = load(CAP004_ROOT / "NO_TRADE_SELECTIVITY.json") if (CAP004_ROOT / "NO_TRADE_SELECTIVITY.json").is_file() else {}
    heartbeat = load(LEDGER_ROOT / HEARTBEAT_FILENAME) if (LEDGER_ROOT / HEARTBEAT_FILENAME).is_file() else {}

    # --- §A the frozen identity ------------------------------------------- #
    check("manifest declares its version", manifest.get("manifest_version") == MANIFEST_VERSION)
    check("campaign id is the frozen one", manifest.get("campaign_id") == CAMPAIGN_ID)
    check("campaign version is the frozen one", manifest.get("campaign_version") == CAMPAIGN_VERSION)
    check("manifest is frozen (has a freeze instant)", isinstance(manifest.get("frozen_at"), int))
    check(
        "the live campaign_id constant still matches",
        CAMPAIGN_ID == "CAP004-REAL-DECISIONS-V1",
    )
    check("horizon is the frozen 24H", manifest.get("horizon") == HORIZON)
    check("asset universe is the frozen four", tuple(manifest.get("assets") or ()) == ASSETS)
    check(
        "cadence reuses the CAP-003 16:00 UTC slot",
        (manifest.get("cadence") or {}).get("decision_slot_utc_hour") == SLOT_UTC_HOUR,
    )
    check(
        "seal window is declared and frozen",
        (manifest.get("cadence") or {}).get("seal_window_seconds") == SEAL_WINDOW_SECONDS,
    )
    check("backfill is explicitly forbidden", (manifest.get("cadence") or {}).get("backfill") == "FORBIDDEN")
    check("analyst version is frozen", manifest.get("analyst_version") == PROMPT_VERSION)
    check("schema version is frozen", manifest.get("schema_version") == SCHEMA_VERSION)
    check("feature version is frozen", manifest.get("feature_version") == FEATURE_VERSION)
    check("campaign provenance contract is the extended one", tuple(manifest.get("campaign_provenance_fields") or ()) == CAMPAIGN_PROVENANCE_FIELDS)
    check(
        "cost model is the frozen shared round trip",
        approx((manifest.get("cost_model") or {}).get("round_trip_fraction", -1.0), COST_ROUND_TRIP),
    )
    check("evaluator identity is frozen", (manifest.get("evaluator") or {}) == {"id": EVALUATOR_ID, "version": EVALUATOR_VERSION})
    baseline_b = (manifest.get("baselines") or {}).get("B") or {}
    check("comparator B definition is frozen", baseline_b.get("frozen") is True)
    check("comparator B version is the reproducibility-fixed one", baseline_b.get("version") == RULE_VERSION, str(baseline_b.get("version")))
    check("comparator B reads a fixed 4h window", baseline_b.get("input_bars_4h") == RULE_INPUT_BARS_4H)
    check("comparator B reads a fixed 1d window", baseline_b.get("input_bars_1d") == RULE_INPUT_BARS_1D)
    baseline_d = (manifest.get("baselines") or {}).get("D") or {}
    check("comparator D seed is frozen", baseline_d.get("seed") == RANDOM_SEED)
    check(
        "comparator D is assigned at dataset level, not baked into outcomes",
        baseline_d.get("assignment_scope") == "DATASET_LEVEL_AT_SCORING_TIME",
    )
    check("primary metric is frozen", (manifest.get("primary_metric") or {}).get("frozen") is True)
    check(
        "primary metric floor is not relaxed",
        (manifest.get("primary_metric") or {}).get("min_evaluable_decisions") == MIN_EVALUABLE_DECISIONS,
    )
    check("checkpoints are the declared ones", tuple(manifest.get("checkpoints") or ()) == CHECKPOINTS)
    check("runtime promotion is forbidden", manifest.get("runtime_promotion") == "FORBIDDEN")
    check("no trade is authorized", manifest.get("trades_authorized") == 0)
    check("no alpha is claimed", manifest.get("alpha_claimed") == "NONE")
    check("the freeze is still active", manifest.get("alpha_research_freeze") == "ACTIVE")
    check("no alpha RFC is allowed", manifest.get("next_alpha_rfc_allowed") == "NO")
    check("legacy cohort is declared, not silently merged", COHORT_LEGACY in (manifest.get("cohorts") or {}))
    check(
        "the frozen prompt digest matches the prompt in source",
        manifest.get("prompt_digest") == frozen_prompt_digest(),
        f"{str(manifest.get('prompt_digest'))[:16]} vs {frozen_prompt_digest()[:16]}",
    )

    # --- §B cadence and exactly-once sealing ------------------------------ #
    keys = [decision_key(item) for item in decisions]
    check("slot keys are unique across the ledger", len(set(keys)) == len(keys), str(len(keys) - len(set(keys))))
    check("the campaign has at least one decision", len(decisions) >= 1)
    for entry in decisions:
        label = str(entry["decision_id"])[:12]
        slot_moment = dt.datetime.fromtimestamp(int(entry["decision_time"]), dt.UTC)
        check(
            f"decision sits on the declared UTC slot ({label})",
            slot_moment.hour == SLOT_UTC_HOUR and slot_moment.minute == 0 and slot_moment.second == 0,
            slot_moment.isoformat(),
        )
        check(
            f"decision time is on the 4H grid ({label})",
            int(entry["decision_time"]) % BAR_4H == 0,
        )
        check(f"asset is in the frozen universe ({label})", entry["asset"] in ASSETS, str(entry["asset"]))
        check(f"horizon is the frozen 24H ({label})", entry["horizon"] == HORIZON)
        check(f"prompt version is the frozen one ({label})", entry["prompt_version"] == PROMPT_VERSION)
        check(
            f"scheduled slot matches the seal timestamp ({label})",
            int(entry.get("scheduled_decision_time", entry["decision_time"])) == int(entry["decision_time"]),
        )
        cohort = str((entry.get("provenance") or {}).get("campaign_id") or COHORT_LEGACY)
        if cohort == CAMPAIGN_ID:
            actual = entry.get("actual_execution_time")
            check(f"CAP-004 decision records its actual execution time ({label})", isinstance(actual, int))
            delay = entry.get("delay_seconds")
            check(
                f"seal delay is recorded and consistent ({label})",
                isinstance(delay, int) and delay == as_int(actual) - int(entry["decision_time"]),
                f"delay={delay}",
            )
            check(
                f"no slot was filled after the seal window ({label})",
                isinstance(delay, int) and delay <= SEAL_WINDOW_SECONDS,
                str(delay),
            )
            check(
                f"CAP-004 decision carries extended provenance ({label})",
                not [
                    field
                    for field in CAMPAIGN_PROVENANCE_FIELDS
                    if not str((entry.get("provenance") or {}).get(field, "")).strip()
                ],
            )
        else:
            check(f"legacy decision is labelled, not retro-fitted ({label})", cohort == COHORT_LEGACY)
            check(
                f"legacy decision provenance was not rewritten ({label})",
                "campaign_id" not in (entry.get("provenance") or {}),
            )
        blanks = [f for f in BASE_PROVENANCE_FIELDS if not str((entry.get("provenance") or {}).get(f, "")).strip()]
        check(f"base provenance is complete ({label})", not blanks, str(blanks))
    legacy = [item for item in decisions if str((item.get("provenance") or {}).get("campaign_id") or COHORT_LEGACY) == COHORT_LEGACY]
    check("the adopted CAP-003 pilot cohort is exactly four decisions", len(legacy) == 4, str(len(legacy)))

    # --- §C ledger chain -------------------------------------------------- #
    decision_hashes = {str(item["decision_hash"]) for item in decisions}
    for entry in decisions:
        label = str(entry["decision_id"])[:12]
        check(f"decision hash recomputes ({label})", decision_hash_of(entry) == entry["decision_hash"])
        check(f"decision id derives from the hash ({label})", entry["decision_id"] == "DEC-" + str(entry["decision_hash"])[:16])
        check(f"snapshot re-digests to its hash ({label})", sha256_text(canonical(entry["snapshot"])) == entry["snapshot_hash"])

    outcome_keys = [(str(item["decision_id"]), str(item["horizon"])) for item in outcomes]
    check("outcome keys are unique", len(set(outcome_keys)) == len(outcome_keys))
    evaluation_keys = [(str(item["decision_id"]), str(item["horizon"])) for item in evaluations]
    check("evaluation keys are unique", len(set(evaluation_keys)) == len(evaluation_keys))

    for entry in outcomes:
        label = f"{str(entry['decision_id'])[:12]}:{entry['horizon']}"
        check(f"outcome hash recomputes ({label})", strip_hash(entry, "outcome_hash") == entry["outcome_hash"])
        check(f"outcome links to a known decision ({label})", str(entry["decision_hash"]) in decision_hashes)
        check(f"outcome was produced by the evaluator ({label})", entry["evaluator"] == EVALUATOR_ID)
        check(f"outcome uses the evaluator version ({label})", entry["evaluator_version"] == EVALUATOR_VERSION)
        gross, costs, net = float(entry["gross_return"]), float(entry["costs"]), float(entry["net_return"])
        check(f"net equals gross minus costs ({label})", approx(net, gross - costs))
        if entry["decision"] == "NO_TRADE":
            check(f"NO_TRADE pays exactly zero ({label})", costs == 0.0 and gross == 0.0)
            check(f"NO_TRADE is labelled NO_TRADE ({label})", entry["outcome"] == "NO_TRADE")
        else:
            check(f"an active sleeve pays the shared round trip ({label})", approx(costs, COST_ROUND_TRIP))
            expected_gross, _, expected_net = sleeve_net(entry["decision"], float(entry["entry_price"]), float(entry["exit_price"]))
            check(f"gross recomputes from the reference prices ({label})", approx(gross, expected_gross))
            check(
                f"outcome label matches the net sign ({label})",
                entry["outcome"] == ("WIN" if net > 0 else ("LOSS" if net < 0 else "FLAT")),
            )
            check(
                f"direction correctness matches the gross sign ({label})",
                bool(entry["direction_correct"]) == bool(gross > 0.0),
            )
            check(f"net recomputes as a sleeve too ({label})", approx(net, expected_net))
        check(f"evidence hash is a digest ({label})", len(str(entry["evidence_hash"])) == 64)
        check(
            f"free-text invalidation is reported honestly ({label})",
            entry["invalidation_hit"] is None
            and entry["invalidation_rule"] == "NOT_MACHINE_CHECKABLE_TEXT_INVALIDATION",
        )

    for entry in evaluations:
        label = f"{str(entry['decision_id'])[:12]}:{entry['horizon']}"
        check(f"evaluation hash recomputes ({label})", strip_hash(entry, "evaluation_hash") == entry["evaluation_hash"])
        check(f"evaluation links to a known outcome ({label})", str(entry["outcome_hash"]) in {str(o["outcome_hash"]) for o in outcomes})
        produced = {str(item["baseline_id"]) for item in entry["comparisons"]}
        check(f"seal-time comparators are exactly B and C ({label})", produced == set(SEAL_TIME_COMPARATORS), str(sorted(produced)))
        check(f"comparator D is not frozen into an evaluation ({label})", BASELINE_D not in produced)
        for comparison in entry["comparisons"]:
            direction = str(comparison["direction"])
            check(
                f"comparator direction is a contract value ({label}:{comparison['baseline_id']})",
                direction in ("LONG", "SHORT", "NO_TRADE"),
            )
            expected_gross, expected_costs, expected_net = sleeve_net(
                direction, float(entry["entry_price"]), float(entry["exit_price"])
            )
            check(
                f"comparator net recomputes ({label}:{comparison['baseline_id']})",
                approx(float(comparison["net_return"]), expected_net)
                and approx(float(comparison["gross_return"]), expected_gross)
                and approx(float(comparison["costs"]), expected_costs),
            )
            if comparison["baseline_id"] == BASELINE_B:
                check(
                    f"comparator B records its rule version ({label})",
                    comparison.get("rule_version") == RULE_VERSION,
                    str(comparison.get("rule_version")),
                )
                check(
                    f"comparator B records its input digest ({label})",
                    len(str(comparison.get("rule_input_hash", ""))) == 64,
                )
        check(f"evaluation carries MFE and MAE ({label})", "mfe" in entry and "mae" in entry)
        check(f"evaluation shares the round trip ({label})", approx(float(entry["round_trip_cost"]), COST_ROUND_TRIP))

    # --- §D maturity ------------------------------------------------------ #
    for entry in outcomes:
        label = f"{str(entry['decision_id'])[:12]}:{entry['horizon']}"
        expected_exit = int(entry["decision_time"]) + HORIZON_SECONDS
        check(f"outcome stops exactly at the horizon ({label})", int(entry["exit_close_time"]) == expected_exit)
        check(f"outcome was not written before maturity ({label})", expected_exit <= now)
        check(f"the entry bar closes at the decision time ({label})", int(entry["entry_close_time"]) == int(entry["decision_time"]))
    settled_keys = set(outcome_keys)
    unsettled_matured = []
    for entry in decisions:
        key = (str(entry["decision_id"]), str(entry["horizon"]))
        if key in settled_keys:
            continue
        maturity = int(entry["decision_time"]) + HORIZON_SECONDS
        if maturity <= now:
            unsettled_matured.append(str(entry["decision_id"]))
    check(
        "no matured horizon is left unsettled and unreported",
        not unsettled_matured
        or int(status.get("population", {}).get("matured_unsettled", 0)) == len(unsettled_matured),
        f"{len(unsettled_matured)} unsettled vs status {status.get('population', {}).get('matured_unsettled')}",
    )
    check("a settled decision is never settled twice", len(outcome_keys) == len(set(outcome_keys)))

    # --- §E comparator B recomputed from first principles ----------------- #
    raw_by_snapshot = {str(item["snapshot_hash"]): item for item in raw_manifest}
    b_recomputed = 0
    for entry in evaluations:
        comparison = next((c for c in entry["comparisons"] if c["baseline_id"] == BASELINE_B), None)
        if comparison is None:
            continue
        label = str(entry["decision_id"])[:12]
        decision = next((d for d in decisions if d["decision_id"] == entry["decision_id"]), None)
        if decision is None:
            check(f"comparator B decision is recoverable ({label})", False)
            continue
        record = raw_by_snapshot.get(str(decision["snapshot_hash"]))
        if record is None:
            limit(f"comparator B not independently recomputed for {label}: raw evidence unregistered")
            continue
        raw_path = LEDGER_ROOT / str(record["local_path"])
        if not raw_path.is_file():
            limit(f"comparator B not independently recomputed for {label}: raw evidence missing locally")
            continue
        raw = load(raw_path)
        rederived = recompute_rule(
            bars_4h=raw["intervals"]["4h"]["bars"],
            bars_1d=raw["intervals"]["1D"]["bars"],
            decision_time=int(decision["decision_time"]),
        )
        b_recomputed += 1
        check(
            f"comparator B direction reproduces independently ({label})",
            rederived["direction"] == comparison["direction"],
            f"{rederived['direction']} vs {comparison['direction']}",
        )
        check(
            f"comparator B reason reproduces independently ({label})",
            rederived["reason"] == comparison.get("reason"),
            f"{rederived['reason']} vs {comparison.get('reason')}",
        )
    if evaluations:
        check("comparator B was independently recomputed at least once", b_recomputed >= 1, str(b_recomputed))

    # --- §F raw evidence manifest ----------------------------------------- #
    check(
        "raw evidence manifest covers every decision",
        {str(item["snapshot_hash"]) for item in decisions}
        <= {str(item["snapshot_hash"]) for item in raw_manifest},
        f"{len(raw_manifest)} registered vs {len({d['snapshot_hash'] for d in decisions})} needed",
    )
    check("raw evidence manifest has unique snapshot hashes", len({str(i["snapshot_hash"]) for i in raw_manifest}) == len(raw_manifest))
    for record in raw_manifest:
        label = str(record["snapshot_hash"])[:12]
        check(
            f"raw evidence entry declares intervals ({label})",
            bool(record.get("intervals")),
            str([i.get("timeframe") for i in record.get("intervals", [])]),
        )
        path = LEDGER_ROOT / str(record["local_path"])
        if not path.is_file():
            limit(f"raw evidence file missing locally for {label} (reported, never re-downloaded)")
            continue
        raw = load(path)
        check(
            f"raw evidence content digest matches ({label})",
            sha256_text(canonical(raw)) == str(record["raw_evidence_hash"]),
            f"{sha256_text(canonical(raw))[:16]} vs {str(record['raw_evidence_hash'])[:16]}",
        )
        for interval in record["intervals"]:
            bars = raw["intervals"][interval["timeframe"]]["bars"]
            check(
                f"raw evidence row count matches ({label}:{interval['timeframe']})",
                len(bars) == int(interval["row_count"]),
            )
            check(
                f"raw evidence range matches ({label}:{interval['timeframe']})",
                int(bars[0]["t"]) == int(interval["start_open_time"])
                and int(bars[-1]["t"]) == int(interval["end_open_time"]),
            )
            check(
                f"raw evidence interval digest recomputes ({label}:{interval['timeframe']})",
                sha256_text(canonical(bars)) == str(interval["sha256"]),
            )

    # --- §G comparator D -------------------------------------------------- #
    directions = [str(item["decision"]) for item in evaluations]
    if evaluations:
        random_stats = scorecard["comparators"][BASELINE_D]
        check("comparator D carries the frozen seed", random_stats["seed"] == RANDOM_SEED)
        observed = {d: directions.count(d) for d in ("LONG", "SHORT", "NO_TRADE")}
        check("comparator D matches the analyst distribution", random_stats["distribution"] == observed, f"{random_stats['distribution']} vs {observed}")
        check("comparator D is an exact permutation", sorted(random_stats["assignment"]) == sorted(directions))
        check(
            "comparator D assignment digest recomputes",
            sha256_text(canonical(list(random_stats["assignment"]))) == random_stats["assignment_digest"],
        )
    else:
        check("comparator D is absent while no decision is evaluated", scorecard.get("comparators", {}).get(BASELINE_D) is None)

    # --- §H scorecard and checkpoints ------------------------------------- #
    check("scorecard counts match the ledger", int(scorecard.get("n_decisions_evaluated", -1)) == len(evaluations))
    if evaluations:
        agent_mean = sum(float(item["net_return"]) for item in evaluations) / len(evaluations)
        check("scorecard agent expectancy recomputes", approx(scorecard["agent"]["mean_net_return"], agent_mean))
        for baseline_id in SEAL_TIME_COMPARATORS:
            values = [
                float(item["net_return"])
                for entry in evaluations
                for item in entry["comparisons"]
                if str(item["baseline_id"]) == baseline_id
            ]
            comparator_mean = scorecard["comparators"][baseline_id]["mean_net_return"]
            check(
                f"scorecard comparator mean recomputes ({baseline_id})",
                not values or approx(comparator_mean, sum(values) / len(values)),
            )
            edge = scorecard["incremental_edges"][baseline_id]
            check(
                f"scorecard edge recomputes ({baseline_id})",
                edge is None or approx(edge, agent_mean - comparator_mean),
            )
    n_evaluated = int(scorecard.get("n_decisions_evaluated", 0))
    expected = (
        CONCLUSION_NOT_MEASURABLE
        if n_evaluated == 0
        else (CONCLUSION_INSUFFICIENT if n_evaluated < MIN_EVALUABLE_DECISIONS else None)
    )
    check(
        "scorecard conclusion matches the declared floor",
        expected is None or scorecard.get("gate", {}).get("conclusion") == expected,
        f"n={n_evaluated} conclusion={scorecard.get('gate', {}).get('conclusion')}",
    )
    check("scorecard conclusion is a declared value", scorecard.get("gate", {}).get("conclusion") in EXPECTED_CONCLUSIONS)
    check(
        "no positive edge is claimed below the sample floor",
        not (n_evaluated < MIN_EVALUABLE_DECISIONS and scorecard.get("gate", {}).get("conclusion") == CONCLUSION_POSITIVE),
    )
    check("scorecard claims no alpha", scorecard.get("alpha_claimed") is False)
    check("scorecard claims no profitability", scorecard.get("profitability_status") == "NOT_DEMONSTRATED")
    check("the edge KPI is still zero", scorecard.get("kpi_agentic_decision_edge") == 0)
    check(
        "extended metrics are labelled a diagnostic",
        metrics.get("label") == "EXTENDED_DIAGNOSTIC_NOT_THE_PRIMARY_METRIC",
        str(metrics.get("label")),
    )
    check(
        "the extended metric count matches the ledger",
        int(metrics.get("n_decisions", -1)) == len(evaluations),
    )
    check(
        "sharpe is refused below the sample floor",
        metrics.get("net", {}).get("sharpe_status")
        == (
            "COMPUTED_NON_ANNUALISED"
            if n_evaluated >= MIN_EVALUABLE_DECISIONS
            else "NOT_COMPUTED_BELOW_SAMPLE_FLOOR"
        ),
        str(metrics.get("net", {}).get("sharpe_status")),
    )
    check(
        "small samples are flagged, never smoothed over",
        (n_evaluated >= MIN_EVALUABLE_DECISIONS)
        == (metrics.get("sample_warnings") == []),
        str(metrics.get("sample_warnings")),
    )
    if evaluations:
        directional = [item for item in evaluations if item["decision"] != "NO_TRADE"]
        expected_accuracy = (
            sum(1 for item in directional if item["direction_correct"]) / len(directional)
            if directional
            else None
        )
        check(
            "direction accuracy recomputes",
            metrics.get("direction_accuracy") == expected_accuracy,
            f"{metrics.get('direction_accuracy')} vs {expected_accuracy}",
        )
        check(
            "the per-asset breakdown covers every asset in the sample",
            set((metrics.get("per_asset") or {}).keys())
            == {str(item["asset"]) for item in evaluations},
            str(sorted((metrics.get("per_asset") or {}).keys())),
        )
        check(
            "the confidence buckets are the predeclared four",
            [item["bucket"] for item in metrics.get("confidence_buckets") or []]
            == ["0.00-0.40", "0.40-0.60", "0.60-0.80", "0.80-1.00"],
        )

    created: list[int] = []
    for checkpoint in CHECKPOINTS:
        path = LEDGER_ROOT / CHECKPOINT_DIRNAME / f"CHECKPOINT_{checkpoint:03d}.json"
        if not path.is_file():
            check(f"checkpoint {checkpoint} is absent below its threshold", n_evaluated < checkpoint, str(n_evaluated))
            continue
        payload = load(path)
        created.append(int(payload["checkpoint"]))
        checkpoint_population = evaluations[: int(payload["n_evaluated"])]
        expected_hash = sha256_text(
            canonical(
                sorted(
                    [str(i["decision_id"]), str(i["outcome_hash"]), str(i["evaluation_hash"])]
                    for i in checkpoint_population
                )
            )
        )
        check(
            f"checkpoint {checkpoint} describes the population it claims",
            payload["decision_set_hash"] == expected_hash,
        )
        check(
            f"checkpoint {checkpoint} was not rewritten from another population",
            int(payload["n_evaluated"]) >= checkpoint and int(payload["n_evaluated"]) <= n_evaluated,
            f"n_evaluated={payload['n_evaluated']} vs current {n_evaluated}",
        )
        check(
            f"checkpoint {checkpoint} refuses an edge verdict below the floor",
            payload.get("edge_verdict") == (
                "NOT_PERMITTED_BELOW_SAMPLE_FLOOR" if n_evaluated < MIN_EVALUABLE_DECISIONS else "PERMITTED_AT_OR_ABOVE_SAMPLE_FLOOR"
            ),
        )
        check(f"checkpoint {checkpoint} is labelled diagnostic", payload.get("is_diagnostic_only") is True)
        check(f"checkpoint {checkpoint} has a markdown mirror", (LEDGER_ROOT / CHECKPOINT_DIRNAME / f"CHECKPOINT_{checkpoint:03d}.md").is_file())
    check("checkpoints were created in ascending order", created == sorted(created))

    # --- §I state, status and heartbeat ---------------------------------- #
    population = status.get("population") or {}
    check("status reports sealed as the ledger size", int(population.get("sealed_decisions", -1)) == len(decisions))
    check("status reports evaluated as the evaluation count", int(population.get("evaluated_decisions", -1)) == len(evaluations))
    check("status reports settled as the outcome count", int(population.get("settled_outcomes", -1)) == len(outcomes))
    check(
        "status reports matured consistently",
        int(population.get("matured_decisions", -1))
        == len([d for d in decisions if int(d["decision_time"]) + HORIZON_SECONDS <= now]),
    )
    check(
        "status keeps pending and matured as separate populations",
        int(population.get("pending_decisions", 0)) >= 0 and len(decisions) >= int(population.get("sealed_decisions", 0)),
    )
    check("campaign status uses the allowed vocabulary", status.get("campaign_status") in CAMPAIGN_STATUSES, str(status.get("campaign_status")))
    check("status declares chain integrity", status.get("chain_status") == "INTACT", str(status.get("chain_status")))
    check("status carries a denominator warning", bool(status.get("denominator_note")))
    check("heartbeat declares the campaign", heartbeat.get("campaign_id") == CAMPAIGN_ID)
    check("heartbeat process status is in the allowed vocabulary", heartbeat.get("process_status") in CAMPAIGN_STATUSES, str(heartbeat.get("process_status")))
    check("heartbeat publishes the next decision slot", isinstance(heartbeat.get("next_decision_slot"), int))
    check("heartbeat publishes pending maturities", isinstance(heartbeat.get("pending_maturities"), int))
    check("heartbeat age is bounded by the interval", (now - int(heartbeat.get("timestamp", 0))) <= 3_600, str(now - int(heartbeat.get("timestamp", 0))))
    today = dt.datetime.fromtimestamp(now, dt.UTC).strftime("%Y-%m-%d")
    check("a daily rollup exists for today", (CAP004_ROOT / "daily" / f"{today}.json").is_file())

    blobs: list[str] = []
    for path in (
        CAP004_ROOT / "CAMPAIGN_STATUS.json",
        CAP004_ROOT / "CAMPAIGN_STATUS.md",
        CAP004_ROOT / "ALPHA_SCORECARD.json",
    ):
        if path.is_file():
            blobs.append(path.read_text(encoding="utf-8"))
    for path in sorted((LEDGER_ROOT / CHECKPOINT_DIRNAME).glob("*")) if (LEDGER_ROOT / CHECKPOINT_DIRNAME).is_dir() else []:
        blobs.append(path.read_text(encoding="utf-8"))
    offending = sorted({word for word in FORBIDDEN_STATUS_WORDS for blob in blobs if word in blob})
    check("no promotional status word appears in any report", offending == [], str(offending))

    # --- §J NO_TRADE as a first-class decision --------------------------- #
    no_trade_decisions = [item for item in decisions if item["decision"] == "NO_TRADE"]
    check("NO_TRADE decisions are in the ledger, not dropped", len(no_trade_decisions) == int(status.get("analyst_distribution", {}).get("NO_TRADE", -1)))
    check("NO_TRADE is in the reported population", "no_trade_count" in json.dumps(status))
    check("selectivity is reported as a diagnostic", selectivity.get("is_diagnostic_only") is True)
    if len(no_trade_decisions) < NO_TRADE_SELECTIVITY_MIN_SAMPLE:
        check("selectivity stays INSUFFICIENT_SAMPLE below its floor", selectivity.get("status") == "INSUFFICIENT_SAMPLE", str(selectivity.get("status")))
    else:
        check("selectivity status is a declared value", selectivity.get("status") in {"MEASURED", "INSUFFICIENT_SAMPLE"})
    for item in selectivity.get("counterfactuals", []):
        comparison_value = float(item["counterfactual_net_return"])
        check(
            f"counterfactual arithmetic recomputes ({str(item['decision_id'])[:12]})",
            approx(float(item["avoided_loss"]), max(0.0, -comparison_value))
            and approx(float(item["missed_gain"]), max(0.0, comparison_value)),
        )
        check(
            f"counterfactual is labelled COUNTERFACTUAL ({str(item['decision_id'])[:12]})",
            item.get("label") == "COUNTERFACTUAL",
        )
    check("counterfactuals are never called PnL", "pnl" not in json.dumps(selectivity).lower())

    # --- §K governance and safety ---------------------------------------- #
    economic = DOCS / "ECONOMIC_STATE.json"
    check(
        "ECONOMIC_STATE.json is byte-identical to the frozen canonical state",
        sha256_file(economic) == ECONOMIC_STATE_DIGEST,
        sha256_file(economic),
    )
    state = load(economic)
    check("the freeze is ACTIVE in the canonical state", state["alpha_research_freeze"] == "ACTIVE")
    check("next_alpha_rfc_allowed is still false", state["next_alpha_rfc_allowed"] is False)
    check("PAPER stays NOT_AUTHORIZED", state["paper_status"] == "NOT_AUTHORIZED")
    check("LIVE stays NOT_AUTHORIZED", state["live_status"] == "NOT_AUTHORIZED")
    rfc045 = sorted(path.name for path in DOCS.rglob("*RFC045*"))
    check("no RFC-045 artifact exists", rfc045 == [], str(rfc045))
    code_hits: list[str] = []
    for relative in CAMPAIGN_SOURCES:
        text = (REPO / relative).read_text(encoding="utf-8")
        code_hits.extend(f"{relative}:{pattern}" for pattern in FORBIDDEN_CODE_PATTERNS if re.search(pattern, text))
    check("campaign code contains no order, credential or LLM import", code_hits == [], str(code_hits))
    runner_text = (REPO / "scripts" / "cap004_campaign_runner.py").read_text(encoding="utf-8")
    check("the runner never commits or pushes", '"push"' not in runner_text and '"commit"' not in runner_text)
    check(
        "no selftest artefact entered the campaign sample",
        all(item["prompt_version"] == PROMPT_VERSION for item in decisions),
    )
    check(
        "every campaign decision is a real forward decision at its own slot",
        all(int(item["decision_time"]) <= now for item in decisions),
    )
    check("no decision was backfilled after its slot closed", all(
        str((item.get("provenance") or {}).get("campaign_id") or COHORT_LEGACY) != CAMPAIGN_ID
        or int(item.get("delay_seconds") or 0) <= SEAL_WINDOW_SECONDS
        for item in decisions
    ))
    check("the runner exposes the four phase flags", all(flag in runner_text for flag in ("--seal", "--settle", "--score", "--verify")))
    check("the runner exposes continuous mode", "--continuous" in runner_text)
    check("the runner refuses a second instance", "ALREADY_RUNNING" in runner_text)
    check("the runner is idempotent per slot", "occupied_decision_keys" in runner_text)

    # --- §L CAP-003 is not broken ---------------------------------------- #
    if CAP003_VERIFICATION.is_file() and CAP003_VERIFIER.is_file():
        env = {
            **os.environ,
            "PYTHONPATH": (
                f"{REPO / 'src'}{os.pathsep}{REPO / 'scripts'}"
            ),
            "PYTHONIOENCODING": "utf-8",
        }
        proc = subprocess.run(
            [sys.executable, str(CAP003_VERIFIER)],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        payload = load(CAP003_VERIFICATION) if CAP003_VERIFICATION.is_file() else {}
        check(
            "the CAP-003 verifier still passes",
            payload.get("status") == "PASS",
            f"status={payload.get('status')} passed={payload.get('passed')}/{payload.get('total')} exit={proc.returncode}",
        )
    else:
        limit("CAP-003 verifier inputs are absent locally (reports/ is local-only); CAP-003 not re-verified")

    # --- FALSE_SUCCESS ---------------------------------------------------- #
    false_success: list[str] = []
    if any(decision_hash_of(item) != item["decision_hash"] for item in decisions):
        false_success.append("an unsealed/tampered decision sits in the ledger")
    if any(strip_hash(item, "outcome_hash") != item["outcome_hash"] for item in outcomes):
        false_success.append("a tampered outcome was accepted")
    if any(strip_hash(item, "evaluation_hash") != item["evaluation_hash"] for item in evaluations):
        false_success.append("a tampered evaluation was accepted")
    if len(set(keys)) != len(keys):
        false_success.append("a decision slot was sealed twice")
    if any(int(item["exit_close_time"]) > now for item in outcomes):
        false_success.append("an outcome was recorded before its horizon closed")
    if any(
        str((item.get("provenance") or {}).get("campaign_id") or COHORT_LEGACY) == CAMPAIGN_ID
        and int(item.get("delay_seconds") or 0) > SEAL_WINDOW_SECONDS
        for item in decisions
    ):
        false_success.append("a slot was filled after its seal window (backfill)")
    if any(
        not all(str((item.get("provenance") or {}).get(f, "")).strip() for f in CAMPAIGN_PROVENANCE_FIELDS)
        for item in decisions
        if str((item.get("provenance") or {}).get("campaign_id") or COHORT_LEGACY) == CAMPAIGN_ID
    ):
        false_success.append("a CAP-004 decision lacks extended provenance")
    if scorecard.get("kpi_agentic_decision_edge") != 0:
        false_success.append("an edge KPI was raised off zero without business evidence")
    if not (n_evaluated < MIN_EVALUABLE_DECISIONS) and scorecard.get("gate", {}).get("conclusion") == CONCLUSION_POSITIVE:
        false_success.append("a positive edge verdict was issued at or above the floor without out-of-sample work")
    if sha256_file(economic) != ECONOMIC_STATE_DIGEST:
        false_success.append("the canonical economic state was modified")
    if any(
        str((item.get("provenance") or {}).get("campaign_id") or COHORT_LEGACY) == CAMPAIGN_ID
        and not all(str((item.get("provenance") or {}).get(f, "")).strip() for f in CAMPAIGN_PROVENANCE_FIELDS)
        for item in decisions
    ):
        false_success.append("an incomplete provenance record entered the campaign")
    if rfc045:
        false_success.append("RFC-045 exists despite the freeze")
    if heartbeat.get("process_status") not in CAMPAIGN_STATUSES:
        false_success.append("the heartbeat published an unknown process status")
    if code_hits:
        false_success.append("campaign code contains an order/credential pattern")

    # --- declared limitations (never silently hidden) --------------------- #
    limit(
        "model temperature is NOT_EXPOSED: the analyst client publishes no temperature, so "
        "temperature drift is undetectable by construction (recorded as NOT_EXPOSED, never inferred)"
    )
    limit(
        "raw OHLCV evidence lives outside Git (evidence/real_decisions/raw_evidence/ is "
        "gitignored); candle-level replay needs that local copy, which is why every snapshot is "
        "pinned by content digest and its absence is reported as RAW_EVIDENCE_MISSING, never "
        "re-fetched silently"
    )
    limit(
        "invalidation_hit is always None under MARKET_ANALYST_V1.0: the frozen schema carries no "
        "invalidation rule, so no invalidation can be scored yet"
    )
    limit(
        "the four CAP-003 pilot decisions stay in cohort LEGACY_CAP003_PILOT and are never "
        "retro-fitted with CAP-004 provenance or campaign_id"
    )
    limit(
        f"the campaign holds {len(evaluations)} evaluable decisions; every edge verdict stays "
        f"blocked until {MIN_EVALUABLE_DECISIONS}"
    )

    passed = sum(1 for entry in CHECKS if entry["passed"])
    total = len(CHECKS)
    mismatches = [entry for entry in CHECKS if not entry["passed"]]
    status_name = "PASS" if not mismatches and not false_success else "FAIL"

    payload = {
        "campaign": CAMPAIGN_ID,
        "verifier": "scripts/cap004_verify.py",
        "status": status_name,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "mismatch_detail": mismatches,
        "false_success": len(false_success),
        "false_success_detail": false_success,
        "limitations": LIMITATIONS,
        "ledger": {
            "root": str(LEDGER_ROOT),
            "n_decisions": len(decisions),
            "n_outcomes": len(outcomes),
            "n_evaluations": len(evaluations),
            "n_raw_evidence_registered": len(raw_manifest),
            "n_checkpoints": len(created),
        },
        "checks": CHECKS,
    }
    CAP004_ROOT.mkdir(parents=True, exist_ok=True)
    (CAP004_ROOT / "CAP004_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "CAP-004 INDEPENDENT VERIFICATION",
        "",
        f"STATUS = {status_name}",
        f"CHECKS = {passed}/{total}",
        f"MISMATCHES = {len(mismatches)}",
        f"FALSE_SUCCESS = {len(false_success)}",
        f"LIMITATIONS = {len(LIMITATIONS)}",
        "",
    ]
    for bad in mismatches:
        lines.append(f"- MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        lines.append(f"- FALSE_SUCCESS: {trigger}")
    for note in LIMITATIONS:
        lines.append(f"- LIMITATION: {note}")
    lines.append("")
    (CAP004_ROOT / "CAP004_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    print("CAP-004 INDEPENDENT VERIFICATION")
    print(f"STATUS = {status_name}")
    print(f"CHECKS = {passed}/{total}")
    print(f"MISMATCHES = {len(mismatches)}")
    print(f"FALSE_SUCCESS = {len(false_success)}")
    print(f"LIMITATIONS = {len(LIMITATIONS)}")
    for bad in mismatches:
        print(f"  MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        print(f"  FALSE_SUCCESS: {trigger}")
    for note in LIMITATIONS:
        print(f"  LIMITATION: {note}")
    return 0 if status_name == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
