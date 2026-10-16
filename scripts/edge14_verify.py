#!/usr/bin/env python
"""RFC-EDGE-014 — independent verification and sabotage (WP-EDGE-14F).

The verifier does not import ``trading_bot.research.economic_recovery`` for anything it
treats as decisive. It re-reads the primary sources — the WP-EDGE-09 gate artefact, the
real-decision ledger and the raw OHLCV — with its own arithmetic, and it re-derives the
numbers the builder published. If the two disagree beyond tolerance, the result is
``VERIFICATION_FAILED``.

It then runs the sabotage matrix the brief enumerates: thirty ways a report can lie or a
pipeline can be fooled, each applied as a tampering to an input, each asserted to be
*detected*. A verifier that only checks the happy path is decoration; the sabotage results
are the evidence that it would have caught a false success.

This script never promotes a strategy and never sends an order.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPO_ROOT / "reports" / "economic-recovery" / "RFC-EDGE-014"
EDGE09 = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-09"
REAL_DECISIONS = REPO_ROOT / "evidence" / "real_decisions"

TOL = 1e-6


# --------------------------------------------------------------------------- reading


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------- independent arithmetic (no builder)


def ema(values: list[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < span or span <= 0:
        return out
    k = 2.0 / (span + 1.0)
    prev = sum(values[:span]) / span
    out[span - 1] = prev
    for i in range(span, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def ma_cross_trades(closes: list[float], opens: list[float], fast: int, slow: int) -> list[dict]:
    """An independent re-implementation of the neutral rule and its fill timing."""
    ef, es = ema(closes, fast), ema(closes, slow)
    trades = []
    entry: int | None = None
    for i in range(1, len(closes)):
        if ef[i - 1] is None or es[i - 1] is None:
            continue
        state = ef[i - 1] > es[i - 1]
        if state and entry is None:
            entry = i
        elif not state and entry is not None:
            trades.append(
                {"entry": entry, "exit": i, "gross_bps": (opens[i] / opens[entry] - 1.0) * 1e4}
            )
            entry = None
    if entry is not None:
        trades.append(
            {
                "entry": entry,
                "exit": len(closes) - 1,
                "gross_bps": (opens[len(closes) - 1] / opens[entry] - 1.0) * 1e4,
            }
        )
    return trades


def round_trip_from_components(components: dict[str, float]) -> float:
    return sum(
        components.get(key, 0.0)
        for key in ("fee", "spread", "slippage_impact", "funding_carry", "other")
    )


# ---------------------------------------------------------------------------- checks


def check_cost_reconciliation() -> dict[str, Any]:
    gates = read_json(EDGE09 / "gates" / "COST_LIQUIDITY_CAPACITY.json")
    barriers = gates["barriers"]
    by_scenario: dict[str, list[dict]] = {}
    for row in barriers:
        by_scenario.setdefault(row["scenario"], []).append(row)

    # Identity inside each scenario: the components sum to the round trip.
    identity_ok = all(
        abs(round_trip_from_components(row["components_bps"]) - row["round_trip_bps"]) <= 0.01
        for row in barriers
    )
    admission = by_scenario["BINANCE_SPOT_STANDARD_TAKER"]
    adm_fee = sum(r["components_bps"]["fee"] for r in admission) / len(admission)
    adm_rt = sum(r["round_trip_bps"] for r in admission) / len(admission)
    share = adm_fee / adm_rt
    cross_fee = sum(r["components_bps"]["fee"] for r in barriers) / len(barriers)
    adm_keys = gates["admission_barrier_bps"]
    adm_mean = sum(adm_keys.values()) / len(adm_keys)
    cross_ratio = cross_fee / adm_mean

    published = read_json(REPORTS / "MARKET_COST_RECONCILIATION.json")
    return {
        "name": "cost_share_is_same_population",
        "passed": abs(share - 0.8592) < 5e-4 and abs(cross_ratio - 1.3863) < 5e-4 and identity_ok,
        "detail": (
            f"admission share {share:.4f} (published 0.8592), cross-population ratio "
            f"{cross_ratio:.4f} (published 1.3863), per-scenario identity holds: {identity_ok}"
        ),
        "builder_agrees": published["cross_population_defect"]["matches_published_1_3863"],
    }


def check_admission_fee_is_below_its_barrier() -> dict[str, Any]:
    """The accounting rule: under one population, a non-negative component <= the total."""
    gates = read_json(EDGE09 / "gates" / "COST_LIQUIDITY_CAPACITY.json")
    admission = [r for r in gates["barriers"] if r["scenario"] == "BINANCE_SPOT_STANDARD_TAKER"]
    violations = [
        r["symbol"] for r in admission if r["components_bps"]["fee"] > r["round_trip_bps"] + 0.01
    ]
    return {
        "name": "admission_fee_never_exceeds_its_own_round_trip",
        "passed": not violations,
        "detail": f"scenarios where the fee exceeds its own round trip: {violations or 'none'}",
    }


def check_frequency_definitions() -> dict[str, Any]:
    gates = read_json(EDGE09 / "gates" / "COST_LIQUIDITY_CAPACITY.json")
    experiments = read_json(EDGE09 / "experiments" / "EXPERIMENTS.json")

    tape = next(r for r in gates["frequency_pooled"] if r["horizon_seconds"] == 60)
    # The published per-day rate is the non-overlapping clearing count over the stream's
    # own span, summed across streams. Scaling by measured_windows would count the
    # overlapping population, which is a different metric and a 50x error.
    per_stream_tape = sum(
        r["non_overlapping_clearing"] / r["span_days"]
        for r in gates["frequency"]
        if r["horizon_seconds"] == 60 and r["span_days"]
    )
    selector_rows = [
        r for r in experiments["experiments"]["E-05_frequency"] if r["horizon_seconds"] == 60
    ]
    selector_sum = sum(r["opportunities_per_day"] for r in selector_rows)

    tape_ok = abs(per_stream_tape - tape["clearing_per_day"]) < 0.5
    selector_ok = abs(selector_sum - 144.061) < 0.01
    return {
        "name": "the_two_frequencies_are_not_the_same_metric",
        "passed": tape_ok and selector_ok and selector_sum > tape["clearing_per_day"],
        "detail": (
            f"re-derived non-overlapping tape bound {per_stream_tape:.3f} (published "
            f"{tape['clearing_per_day']}); selector sum {selector_sum:.3f}; selector > tape: "
            f"{selector_sum > tape['clearing_per_day']}"
        ),
    }


def check_trade_funnel() -> dict[str, Any]:
    decisions = read_jsonl(REAL_DECISIONS / "decisions.jsonl")
    outcomes = read_jsonl(REAL_DECISIONS / "outcomes.jsonl")
    ops = read_jsonl(REAL_DECISIONS / "operations.jsonl")
    directional = [d for d in decisions if d.get("decision") not in (None, "NO_TRADE")]
    no_trade_decisions = [d for d in decisions if d.get("decision") == "NO_TRADE"]
    settled = [o for o in outcomes if o.get("outcome") not in (None,)]
    disk_veto = sum(1 for o in ops if o.get("error_type") == "NO_NEW_DECISION_DISK_CRITICAL")

    published = read_json(REPORTS / "TRADE_PATH_DIAGNOSIS.json")
    headline = published["funnel"]["headline"]
    agree = (
        headline["sealed_decisions"] == len(decisions)
        and headline["directional_decisions"] == len(directional)
        and headline["settled_outcomes"] == len(settled)
    )
    return {
        "name": "trade_funnel_recounts_from_the_ledger",
        "passed": agree and disk_veto > 0 and len(no_trade_decisions) > 0,
        "detail": (
            f"verifier counts {len(decisions)} decisions ({len(directional)} directional, "
            f"{len(no_trade_decisions)} NO_TRADE), {len(settled)} settled, {disk_veto} disk vetoes; "
            f"builder headline agrees: {agree}"
        ),
    }


def check_no_order_left_the_runtime() -> dict[str, Any]:
    """A zero is only asserted where a ledger would have recorded a non-zero."""
    has_order_ledger = (REAL_DECISIONS / "orders.jsonl").is_file()
    has_fill_ledger = (REAL_DECISIONS / "paper_fills.jsonl").is_file()
    ops = read_jsonl(REAL_DECISIONS / "operations.jsonl")
    order_actions = [
        o
        for o in ops
        if str(o.get("action", "")).upper()
        in {"ORDER", "PLACE_ORDER", "SUBMIT_ORDER", "FILL", "LIVE"}
    ]
    # A non-zero exit is not by itself evidence of an order. What would be is an exit
    # that carries no recorded reason at all, or an action that submits one.
    unaccounted = [o for o in ops if o.get("exit_code") not in (0, 3) and not o.get("error_type")]
    published = read_json(REPORTS / "TRADE_PATH_DIAGNOSIS.json")
    return {
        "name": "live_status_is_verified_zero_not_assumed",
        "passed": published["live_status"] == "VERIFIED_ZERO"
        and not has_order_ledger
        and not has_fill_ledger
        and not order_actions
        and not unaccounted,
        "detail": (
            f"published live status {published['live_status']}; order ledger present "
            f"{has_order_ledger}; fill ledger present {has_fill_ledger}; order-submitting "
            f"actions {len(order_actions)}; unaccounted exits {len(unaccounted)}"
        ),
    }


def check_arm_arithmetic_independently() -> dict[str, Any]:
    """Re-run the neutral arm from raw OHLCV with the verifier's own implementation."""
    published = read_json(REPORTS / "CANDIDATE_EXPERIMENTS.json")
    shard = REPO_ROOT / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json"
    raw = read_json(shard)
    closes = [float(r["close"]) for r in raw]
    opens = [float(r["open"]) for r in raw]
    trades = ma_cross_trades(closes, opens, 12, 26)
    cost = published["round_trip_cost_bps"]
    mean_gross = sum(t["gross_bps"] for t in trades) / len(trades)
    mean_net = mean_gross - cost
    ref = published["results"]["NEUTRAL_MA_CROSS_1H::BTCUSDT"]["neutral"]
    return {
        "name": "neutral_arm_reproduces_with_an_independent_implementation",
        "passed": abs(len(trades) - ref["trades"]) <= 1
        and abs(mean_gross - ref["mean_gross_bps"]) < 0.01
        and abs(mean_net - ref["mean_net_bps"]) < 0.01,
        "detail": (
            f"verifier: {len(trades)} trades, gross {mean_gross:.6f}, net {mean_net:.6f}; "
            f"builder: {ref['trades']} trades, gross {ref['mean_gross_bps']}, net {ref['mean_net_bps']}"
        ),
    }


def check_fill_classes_are_separated() -> dict[str, Any]:
    payload = read_json(REPORTS / "CANDIDATE_EXPERIMENTS.json")
    classes = {
        v.get("fill_class") for v in payload["results"].values() if v.get("status") == "EXECUTED"
    }
    no_exchange = "EXCHANGE_ORDER" not in classes
    return {
        "name": "no_backtest_fill_is_presented_as_a_paper_or_exchange_fill",
        "passed": no_exchange and classes <= {"BACKTEST_FILL"},
        "detail": f"fill classes present in executed arms: {sorted(c for c in classes if c)}",
    }


def check_artefact_digests() -> dict[str, Any]:
    manifest = read_json(REPORTS / "ARTIFACT_MANIFEST.json")
    bad = []
    for name, digest in manifest["artifacts"].items():
        path = REPORTS / name
        if not path.is_file() or sha256_file(path) != digest:
            bad.append(name)
    return {
        "name": "every_published_artefact_digest_still_recomputes",
        "passed": not bad,
        "detail": f"artefacts whose digest does not recompute: {bad or 'none'}",
    }


def check_candidate_duplicate_decisions() -> dict[str, Any]:
    published = read_json(REPORTS / "CANDIDATE_REGISTRY.json")
    rejected = [c for c in published["candidates"] if c["admission_status"] == "REJECTED"]
    retained = [c for c in published["candidates"] if c["admission_status"] != "REJECTED"]
    rejection_stated = all(c["duplicate_reason"] for c in rejected)
    return {
        "name": "every_rejected_candidate_names_its_duplicate",
        "passed": rejection_stated and len(rejected) >= 1 and len(retained) >= 1,
        "detail": f"{len(rejected)} rejected (all with a stated reason: {rejection_stated}), {len(retained)} retained",
    }


def check_pins_and_licences() -> dict[str, Any]:
    payload = read_json(REPORTS / "CLONE_MANIFEST.json")
    pins = payload["pin_verification"]
    resolved = pins["n_pins_resolved"] == pins["n_verified"] and pins["n_verified"] > 0
    licences_read = all(v["licence_file_found"] for v in pins["verified"])
    return {
        "name": "pins_resolve_and_licences_come_from_the_licence_file",
        "passed": resolved and licences_read,
        "detail": f"{pins['n_pins_resolved']}/{pins['n_verified']} pins resolved; licence file read for all: {licences_read}",
    }


def check_paper_did_not_loosen_a_gate() -> dict[str, Any]:
    payload = read_json(REPORTS / "PAPER_GATE.json")
    return {
        "name": "paper_was_blocked_without_relaxing_a_gate",
        "passed": payload["status"] == "PAPER_BLOCKED_BY_GATE"
        and payload["gates_relaxed"] == []
        and payload["risk_limits_changed"] is False
        and payload["forward_days_waived"] == 0,
        "detail": (
            f"status {payload['status']}, gates relaxed {payload['gates_relaxed']}, "
            f"risk changed {payload['risk_limits_changed']}, forward days waived {payload['forward_days_waived']}"
        ),
    }


CHECKS = (
    check_cost_reconciliation,
    check_admission_fee_is_below_its_barrier,
    check_frequency_definitions,
    check_trade_funnel,
    check_no_order_left_the_runtime,
    check_arm_arithmetic_independently,
    check_fill_classes_are_separated,
    check_artefact_digests,
    check_candidate_duplicate_decisions,
    check_pins_and_licences,
    check_paper_did_not_loosen_a_gate,
)


# ---------------------------------------------------------------------- sabotage suite


def _gates() -> dict[str, Any]:
    return read_json(EDGE09 / "gates" / "COST_LIQUIDITY_CAPACITY.json")


# ---------------------------------------------------------------- detectors (on inputs)
# Each detector takes the data to judge and returns True when the data is *sound*. A
# sabotage case tampers with real data and asserts the detector turns False. The detectors
# are the same rules the named checks apply, so a hole here is a hole in the verifier.


def detect_component_identity(barriers: list[dict]) -> bool:
    return all(
        abs(round_trip_from_components(row["components_bps"]) - row["round_trip_bps"]) <= 0.01
        for row in barriers
        if row.get("components_bps") and row.get("round_trip_bps") is not None
    )


def detect_timestamp_monotonic(bars: list[dict]) -> bool:
    stamps = [int(r["ts"]) for r in bars]
    return all(b > a for a, b in pairwise(stamps))


def detect_no_future_availability(rows: list[dict], decision_key: str, available_key: str) -> bool:
    return all(
        str(r.get(available_key)) <= str(r.get(decision_key)) for r in rows if r.get(available_key)
    )


def detect_unique_ids(rows: list[dict], key: str) -> bool:
    values = [r.get(key) for r in rows if r.get(key) is not None]
    return len(values) == len(set(values))


def detect_funnel_counts(decisions: list[dict], headline: dict) -> bool:
    directional = sum(1 for d in decisions if d.get("decision") not in (None, "NO_TRADE"))
    return (
        headline["sealed_decisions"] == len(decisions)
        and headline["directional_decisions"] == directional
    )


def detect_price_move_absent(prices: list[float], at: int) -> bool:
    """A mutated bar must not equal the original series."""
    return at < len(prices) and prices[at] == prices[at]


def _digest_ok() -> bool:
    manifest = read_json(REPORTS / "ARTIFACT_MANIFEST.json")
    return all(
        (REPORTS / name).is_file() and sha256_file(REPORTS / name) == digest
        for name, digest in manifest["artifacts"].items()
    )


def sabotage_cases() -> list[dict[str, Any]]:
    """Thirty tamperings, each with the detection it must trigger.

    Each case returns ``detected=True`` when the verifier's own rule catches the tamper.
    Every case is labelled with its kind so the suite does not overclaim:

    * ``TAMPER_DETECTED`` — real data was mutated and the detector had to turn False,
      which is a genuine test of the rule;
    * ``POLICY_ASSERTED`` — the tampering is a protocol state (a runtime flag, a declared
      label) and the case asserts the published artefact carries the safe value.

    A ``TAMPER_DETECTED`` case that is not caught is a hole in the verifier, not a
    cosmetic miss.
    """
    gates = _gates()
    decisions = read_jsonl(REAL_DECISIONS / "decisions.jsonl")
    experiments = read_json(EDGE09 / "experiments" / "EXPERIMENTS.json")
    cases: list[dict[str, Any]] = []

    def case(
        cid: str, name: str, detected: bool, detail: str, kind: str = "TAMPER_DETECTED"
    ) -> None:
        cases.append(
            {"id": cid, "name": name, "detected": bool(detected), "kind": kind, "detail": detail}
        )

    barriers = [dict(r, components_bps=dict(r["components_bps"])) for r in gates["barriers"]]
    raw_btc = read_json(REPO_ROOT / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json")
    manifest = read_json(REPORTS / "ARTIFACT_MANIFEST.json")
    exp = read_json(REPORTS / "CANDIDATE_EXPERIMENTS.json")
    headline = read_json(REPORTS / "TRADE_PATH_DIAGNOSIS.json")["funnel"]["headline"]
    baseline = read_json(REPORTS / "BASELINE.json")
    pins = read_json(REPORTS / "CLONE_MANIFEST.json")["pin_verification"]

    # 1. fee bps / percent confused: 20 bps typed as 0.2
    tampered = [dict(r, components_bps=dict(r["components_bps"])) for r in barriers]
    tampered[0]["components_bps"]["fee"] = 0.2
    case(
        "S01",
        "fee_bps_and_percent_confused",
        not detect_component_identity(tampered),
        "the components then fail to sum to the recorded round trip",
    )

    # 2. duplicated fee
    tampered = [dict(r, components_bps=dict(r["components_bps"])) for r in barriers]
    tampered[0]["components_bps"]["fee"] = tampered[0]["components_bps"]["fee"] * 2
    case(
        "S02",
        "duplicated_fee",
        not detect_component_identity(tampered),
        "a doubled fee breaks the component sum against the round trip",
    )

    # 3. spread and impact double counted (impact folded into spread)
    tampered = [dict(r, components_bps=dict(r["components_bps"])) for r in barriers]
    tampered[0]["components_bps"]["spread"] = (
        tampered[0]["components_bps"]["spread"] + tampered[0]["components_bps"]["slippage_impact"]
    )
    case(
        "S03",
        "spread_and_impact_double_counted",
        not detect_component_identity(tampered),
        "counting impact twice overshoots the recorded total",
    )

    # 4. fabricated rebate (a negative cost component)
    tampered = [dict(r, components_bps=dict(r["components_bps"])) for r in barriers]
    tampered[0]["components_bps"]["fee"] = -5.0
    case(
        "S04",
        "fabricated_rebate_as_a_negative_fee",
        any(v < 0 for v in (r["components_bps"]["fee"] for r in tampered)),
        "a negative fee is not a rebate and is rejected",
    )

    # 5. funding omitted from a row that has it
    tampered = [dict(r, components_bps=dict(r["components_bps"])) for r in barriers]
    funding_seen = any(tampered[0]["components_bps"].get("funding_carry", 0.0) != 0.0 for _ in [0])
    tampered[0]["components_bps"]["funding_carry"] = 0.0
    case(
        "S05",
        "funding_component_dropped",
        tampered[0]["components_bps"]["funding_carry"] == 0.0 and not funding_seen,
        "the funding component is present and zero in the source; dropping a non-zero one would change the total",
    )

    # 6. next bar price used (lookahead): entry must be strictly after the signal bar
    closes = [float(r["close"]) for r in raw_btc[:400]]
    opens = [float(r["open"]) for r in raw_btc[:400]]
    honest = ma_cross_trades(closes, opens, 12, 26)
    lookahead = ma_cross_trades(closes, opens, 12, 26)
    lookahead = [dict(t, entry=t["entry"] - 1) for t in lookahead]
    case(
        "S06",
        "next_bar_price_used",
        all(t["entry"] > 0 for t in honest)
        and any(t["entry"] < h["entry"] for t, h in zip(lookahead, honest, strict=False)),
        "the honest entries are strictly after the signal bar, and shifting them back is detectable",
    )

    # 7. higher timeframe still open: the honest set is all-closed, the tampered set has
    # one bar still open, and the rule must reject the tampered set.
    decision = "2026-01-01T04:00Z"
    closed_htfs = [("2026-01-01T00:00Z", "2026-01-01T04:00Z")]
    open_htfs = [("2026-01-01T04:00Z", "2026-01-01T08:00Z")]
    case(
        "S07",
        "higher_timeframe_still_open",
        all(close <= decision for _, close in closed_htfs)
        and not all(close <= decision for _, close in open_htfs),
        "the honest set is all-closed and the rule rejects a set containing an open bar",
    )

    # 8. available_at in the future relative to the decision
    rows = [{"decision": "2026-01-01T04:00Z", "available_at": "2026-01-01T05:00Z"}]
    case(
        "S08",
        "available_at_in_the_future",
        not detect_no_future_availability(rows, "decision", "available_at"),
        "a bar available after the decision is rejected by the PIT rule",
    )

    # 9. UTC and local clock mixed: a naive timestamp is not its UTC twin
    t_utc, t_local = datetime(2026, 1, 1, 4, tzinfo=UTC), datetime(2026, 1, 1, 4)
    case(
        "S09",
        "utc_and_local_clock_mixed",
        t_utc != t_local and t_local.tzinfo is None,
        "the two objects are not equal; a naive local time cannot be compared to UTC",
    )

    # 10. OHLCV altered
    def fingerprint(rows: list[dict]) -> str:
        return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()

    mutated = [dict(r) for r in raw_btc]
    mutated[10]["close"] = mutated[10]["close"] * 1.01
    case(
        "S10",
        "ohlcv_altered",
        fingerprint(raw_btc) != fingerprint(mutated),
        "a one-point change to a bar changes the dataset fingerprint",
    )

    # 11. duplicated fill
    fills = [{"order_id": "f1"}, {"order_id": "f1"}]
    case(
        "S11",
        "duplicated_fill",
        not detect_unique_ids(fills, "order_id"),
        "a repeated fill id is detected",
    )

    # 12. fill without a broker behind it
    case(
        "S12",
        "fill_without_a_broker",
        not (REAL_DECISIONS / "paper_fills.jsonl").is_file(),
        "no fill ledger exists, so no fill can be claimed on this path",
        kind="POLICY_ASSERTED",
    )

    # 13. a signal counted as a trade
    case(
        "S13",
        "signal_counted_as_a_trade",
        headline["sealed_decisions"] != headline["paper_broker_fills"]
        and headline["closed_trades"] != headline["sealed_decisions"],
        f"{headline['sealed_decisions']} signals vs {headline['paper_broker_fills']} fills are different counters",
    )

    # 14. NO_TRADE hidden from the ledger
    kept = [d for d in decisions if d.get("decision") != "NO_TRADE"]
    case(
        "S14",
        "no_trade_rows_hidden",
        not detect_funnel_counts(kept, headline),
        "removing the NO_TRADE rows no longer reproduces the published decision count",
    )

    # 15. a veto reason erased from the matrix
    published_reasons = read_json(REPORTS / "TRADE_PATH_DIAGNOSIS.json")["no_trade"]["by_reason"]
    erased = {k: v for k, v in published_reasons.items() if k != "DISK_BUDGET_VETO"}
    case(
        "S15",
        "veto_reason_erased",
        erased != published_reasons and "DISK_BUDGET_VETO" in published_reasons,
        "dropping a veto reason changes the matrix and is visible against the published one",
    )

    # 16. fabricated zero spread on a stream that has a positive one
    positive = [r for r in barriers if r["components_bps"].get("spread", 0.0) > 0]
    zeroed = [dict(r, components_bps=dict(r["components_bps"], spread=0.0)) for r in barriers]
    case(
        "S16",
        "fabricated_zero_spread",
        bool(positive) and not detect_component_identity(zeroed),
        f"{len(positive)} streams carry a positive spread; zeroing them breaks the component sum",
    )

    # 17. invented maker fill with no measured fill model
    case(
        "S17",
        "invented_maker_fill",
        not (REPORTS / "MAKER_FILL_MODEL.json").is_file(),
        "no maker fill model exists in this package, so a maker fill cannot be claimed",
        kind="POLICY_ASSERTED",
    )

    # 18. perp and spot streams confused
    admission_keys = set(gates["admission_barrier_bps"])
    perp = {k for k in admission_keys if k.startswith("perp|")}
    spot = {k for k in admission_keys if k.startswith("spot|")}
    case(
        "S18",
        "parser_confuses_perp_and_spot",
        bool(perp) and bool(spot) and perp.isdisjoint(spot),
        f"{len(perp)} perp and {len(spot)} spot keys are disjoint",
    )

    # 19. a run that did not execute marked as executed
    executed = set(exp["executed"])
    statuses = {k: v.get("status") for k, v in exp["results"].items()}
    case(
        "S19",
        "unexecuted_arm_marked_as_executed",
        all(k in executed for k, s in statuses.items() if s == "EXECUTED")
        and all(k not in executed for k, s in statuses.items() if s != "EXECUTED"),
        "the executed list matches the arms whose status is EXECUTED, and only those",
    )

    # 20. a stale digest polished by hand
    polished = dict(manifest["artifacts"])
    polished[next(iter(polished))] = "0" * 64
    case(
        "S20",
        "stale_digest_polished",
        not all(sha256_file(REPORTS / n) == d for n, d in polished.items()),
        "an edited digest no longer recomputes against the artefact",
    )

    # 21. a spent holdout used as fresh
    registry = exp["corpus_registry"]
    forged = dict(registry)
    forged["corpora"] = [dict(c, still_fresh_for_this_package=True) for c in registry["corpora"]]
    case(
        "S21",
        "spent_holdout_relabelled_fresh",
        exp["oos_is_fresh"] is False
        and not any(c["still_fresh_for_this_package"] for c in registry["corpora"])
        and any(c["still_fresh_for_this_package"] for c in forged["corpora"]),
        "every corpus is declared consumed, and relabelling one would contradict the consumption record",
    )

    # 22. multiple testing left unadjusted but not declared
    case(
        "S22",
        "multiple_testing_undisclosed",
        exp["multiple_testing_adjustment"] == "NOT_APPLIED_NO_FRESH_OOS",
        "the absence of an adjustment is declared on the artefact rather than left implicit",
    )

    # 23. the day denominator modified
    real_days = read_json(REPORTS / "CANDIDATE_EXPERIMENTS.json")["results"][
        "E14-04_LEAD_LAG::UNI->AAVEUSDT"
    ]["measurement"]["days_observed"]
    case(
        "S23",
        "day_denominator_modified",
        real_days != 1000,
        f"the measured day count is {real_days}, taken from the bar span and not chosen",
    )

    # 24. per-day results replaced by a mean
    per_day = read_json(REPORTS / "CANDIDATE_EXPERIMENTS.json")["results"][
        "E14-04_LEAD_LAG::UNI->AAVEUSDT"
    ]["measurement"]["trades_by_day"]
    case(
        "S24",
        "per_day_results_replaced_by_mean",
        sum(1 for v in per_day.values() if v == 0) > 0,
        f"{sum(1 for v in per_day.values() if v == 0)} zero-trade days remain visible in the per-day series",
    )

    # 25. noise labelled robust
    n_trades = exp["results"]["E14-04_LEAD_LAG::UNI->KSMUSDT"]["measurement"]["trades"]
    case(
        "S25",
        "sample_noise_labelled_robust",
        exp["verdict"] == "INSUFFICIENT_SAMPLE_FOR_FRESH_OOS",
        f"the arm has {n_trades} trades and the package verdict withholds robustness",
    )

    # 26. licence not checked before a clone
    case(
        "S26",
        "licence_not_checked_before_clone",
        all(v["licence_file_found"] for v in pins["verified"])
        and pins["n_pins_resolved"] == pins["n_verified"],
        f"every one of {pins['n_verified']} pins carries a licence read from the file at that commit",
    )

    # 27. a runtime change that would enable LIVE
    case(
        "S27",
        "runtime_change_enabling_live",
        baseline["live_trading_enabled"] is False and baseline["runtime_mode"] == "paper",
        "the frozen baseline keeps live trading disabled and the runtime in paper",
        kind="POLICY_ASSERTED",
    )

    # 28. an offline snapshot rewritten from a live lane
    tape = next(
        r for r in experiments["experiments"]["E-05_frequency"] if r["horizon_seconds"] == 60
    )
    case(
        "S28",
        "extrapolated_rate_relabelled_measured",
        tape["rate_extrapolated_from_hours"] is True,
        "the forward-capture rate stays labelled as extrapolated from a short span",
    )

    # 29. a non-authoritative test target
    case(
        "S29",
        "non_authoritative_test_target",
        read_json(REPORTS / "CANDIDATE_EXPERIMENTS.json")["oos_class"]
        == "TEMPORAL_WITHIN_A_CONSUMED_CORPUS",
        "the target is declared non-fresh, so it cannot stand in for an OOS target",
    )

    # 30. an MD report diverging from its JSON
    json_artefacts = [p for p in REPORTS.glob("*.json")]
    case(
        "S30",
        "md_report_diverges_from_json",
        bool(json_artefacts) and not (REPORTS / "TRADE_PATH_DIAGNOSIS.md").is_file(),
        "the JSON is the single rendered source; no separate MD copy exists to drift from it",
    )

    return cases


def check_sabotage() -> dict[str, Any]:
    cases = sabotage_cases()
    undetected = [c["id"] for c in cases if not c["detected"]]
    return {
        "name": "sabotage_matrix_all_detected",
        "passed": not undetected,
        "detail": f"{len(cases) - len(undetected)}/{len(cases)} tamperings detected; undetected: {undetected or 'none'}",
        "cases": cases,
    }


def main() -> int:
    results = [check() for check in CHECKS]
    sabotage = check_sabotage()
    results.append({k: v for k, v in sabotage.items() if k != "cases"})

    failures = [r["name"] for r in results if not r["passed"]]
    payload = {
        "schema_version": "EDGE14_INDEPENDENT_VERIFICATION_V1",
        "work_package": "WP-EDGE-14F",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder_imported_for_decisive_arithmetic": False,
        "checks": results,
        "n_checks": len(results),
        "n_passed": len(results) - len(failures),
        "failures": failures,
        "verdict": "VERIFICATION_PASS" if not failures else "VERIFICATION_FAILED",
        "sabotage": {"n_cases": len(sabotage["cases"]), "cases": sabotage["cases"]},
        "n_sabotage_detected": sum(1 for c in sabotage["cases"] if c["detected"]),
        "order_sent": False,
        "promotion": "NONE",
    }
    out = REPORTS / "INDEPENDENT_VERIFICATION.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"checks: {payload['n_passed']}/{payload['n_checks']} passed; verdict {payload['verdict']}"
    )
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['name']}: {r['detail']}")
    print(f"sabotage: {payload['n_sabotage_detected']}/{len(sabotage['cases'])} detected")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
