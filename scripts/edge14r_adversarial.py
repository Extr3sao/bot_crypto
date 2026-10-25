"""edge14r_adversarial — tamper with this package's own evidence and see what catches it.

The previous verification suite carried three ``POLICY_ASSERTED`` cases: rules that were
*declared* rather than executed, because the data they needed did not exist on that path.
Two of the three now have real recordings behind them (a fill ledger with 301 closed fills
and a live paper path), so this suite turns all three into executed tests, and adds the
kinds of tampering this work package's numbers are actually exposed to.

Every case runs the same detector twice: once on the untouched artifact, where it must
stay quiet, and once on a mutated copy, where it must fire. A detector that fires on both
is not testing anything and a detector that fires on neither is a hole — both are reported
as failures rather than as passes.

    python scripts/edge14r_adversarial.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.economic_recovery import engine_parity as ep

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
FROZEN = OUT / "scratch" / "PAPER_REPLAY_BARS.jsonl"
PAPER = OUT / "PAPER_EXECUTION_EVIDENCE.json"
FEE = OUT / "FEE_CONVENTION_RECONCILIATION.json"
PARITY = OUT / "BENCHMARK_PARITY_REPORT.json"
JESSE = OUT / "BENCHMARK_PARITY_REPORT_JESSE.json"
OOS = OUT / "OOS_CAPTURE_MANIFEST.json"
TRADE_PATH = OUT / "TRADE_PATH_RECONCILIATION.json"
CONFIG = REPO / "config" / "runtime.yaml"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# detectors: each returns True when it believes the artifact is tampered
# --------------------------------------------------------------------------- #


def detect_dataset_digest(payload: dict[str, Any]) -> bool:
    if not FROZEN.is_file():
        return True
    digest = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    recorded = (payload.get("dataset") or {}).get("exported_sha256")
    return recorded != digest


def detect_authoritative_fills(payload: dict[str, Any]) -> bool:
    """A fill on the authoritative arm must be backed by an order on that arm."""
    for arm_name, arm in payload["arms"].items():
        closed = int(arm.get("fills_closed") or 0)
        orders = int((arm.get("stage_totals") or {}).get("orders_created") or 0)
        if arm_name == "GATE_INTACT" and closed and not orders:
            return True
        if closed > max(orders, 1) * 2:
            return True
    return False


def detect_maker_fill(payload: dict[str, Any]) -> bool:
    """Every recorded fill must be a hypothetical fill the broker itself modelled."""
    for arm in payload["arms"].values():
        for exit_row in arm.get("exits") or []:
            if str(exit_row.get("liquidity", "HYPOTHETICAL")).upper() == "MAKER":
                return True
    return False


def detect_broker_commission_units(payload: dict[str, Any]) -> bool:
    """The broker charges 2 x commission_bps of the ENTRY notional per round trip."""
    from trading_bot.paper.broker import PaperBroker

    defaults = PaperBroker.__init__.__defaults__ or ()
    try:
        commission_bps = float(defaults[-2])
    except Exception:  # pragma: no cover
        commission_bps = 5.0
    for arm in payload["arms"].values():
        for exit_row in arm.get("exits") or []:
            entry = float(exit_row["entry_price"])
            qty = float(exit_row["quantity"])
            side = str(exit_row["side"])
            gross = (
                (float(exit_row["exit_price"]) - entry) * qty
                if side == "buy"
                else (entry - float(exit_row["exit_price"])) * qty
            )
            charged = gross - float(exit_row["pnl"])
            expected = (commission_bps * 2.0 / 10_000.0) * qty * entry
            if abs(charged - expected) > 1e-6:
                return True
    return False


def detect_fee_identity(payload: dict[str, Any]) -> bool:
    """The convention gap must equal ADDITIVE(g) - COMPOUNDED(g) for every trade."""
    return any(not block.get("identity_holds") for block in (payload.get("engines") or {}).values())


def detect_parity_convention_gap(payload: dict[str, Any]) -> bool:
    """A per-trade residual pair must satisfy the closed form of the gap."""
    f = float(payload["costs"]["fees_bps_per_side"])
    for row in payload["comparison"]["detail"]["per_trade"]:
        g = float(row["ta_gross_bps"])
        predicted = ep.net_bps(g, f, convention="ADDITIVE") - ep.net_bps(
            g, f, convention="COMPOUNDED"
        )
        observed = float(row["net_bps_diff_additive"]) - float(row["net_bps_diff_compounded"])
        if abs(observed - predicted) > 1e-4:
            return True
    return False


def detect_duplicate_trades(payload: dict[str, Any]) -> bool:
    detail = payload["comparison"]["detail"]
    per_trade = detail["per_trade"]
    keys = [(int(r["index"]), int(r["ta_entry_ts_ms"])) for r in per_trade]
    # Two symbols may legitimately enter and exit in the same hour, so the key is the
    # row's own index plus its entry instant: a duplicated row repeats that pair, and
    # the row count must also equal the number of matched trades it claims.
    return len(keys) != len(set(keys)) or len(per_trade) != int(detail["matched_trades"])


def detect_live_enabled(payload: dict[str, Any]) -> bool:
    """The runtime this package measured must be in paper mode, not live."""
    text = payload.get("text", "")
    lowered = text.lower()
    for marker in ("live_trading: true", "live_mode: true", "enable_live: true"):
        if marker in lowered:
            return True
    return "paper" not in lowered


def detect_oos_leak(payload: dict[str, Any]) -> bool:
    return bool(payload.get("selection_has_read_this_slice")) or bool(payload.get("scoring_run"))


def detect_unknown_is_zero(payload: dict[str, Any]) -> bool:
    """A stage without a ledger must never be reported as a measured zero."""
    stages = payload["arms"]["GATE_INTACT"]["stages"]
    for name in ("ROUTER", "DETERMINISTIC_RISK", "PAPER_BROKER", "FILL_LEDGER"):
        block = stages.get(name) or {}
        if block.get("ledger") == "absent" and block.get("count") == 0:
            return True
    return False


def main() -> int:
    paper = _json(PAPER)
    fee = _json(FEE)
    parity = _json(PARITY)
    jesse = _json(JESSE)
    oos = _json(OOS)
    trade_path = _json(TRADE_PATH)
    config_text = {"text": CONFIG.read_text(encoding="utf-8")} if CONFIG.is_file() else {"text": ""}

    cases: list[dict[str, Any]] = []

    def run(
        cid: str,
        name: str,
        detector: Callable[[Any], Any],
        clean: Any,
        tamper: Callable[[Any], None],
        detail: str,
        legacy: str = "",
    ) -> None:
        clean_fired = bool(detector(clean))
        tampered = copy.deepcopy(clean)
        tamper(tampered)
        tamper_fired = bool(detector(tampered))
        cases.append(
            {
                "id": cid,
                "name": name,
                "kind": "TAMPER_DETECTED",
                "detector_fired_on_clean": clean_fired,
                "detector_fired_on_tampered": tamper_fired,
                "passed": (not clean_fired) and tamper_fired,
                "detail": detail,
                "replaces_legacy_policy_assertion": legacy or None,
            }
        )

    # S12 successor: a fill with no broker/order behind it, now against a real ledger
    run(
        "A01",
        "fill_without_an_order",
        detect_authoritative_fills,
        paper,
        lambda p: p["arms"]["GATE_INTACT"].update({"fills_closed": 3}),
        "the authoritative arm reports closed fills while creating no orders",
        legacy="S12 fill_without_a_broker",
    )

    # S17 successor: an invented maker fill, now against 301 recorded fills
    def _inject_maker(payload: dict[str, Any]) -> None:
        exits = payload["arms"]["SANDBOX_ADMISSION"]["exits"]
        exits[0]["liquidity"] = "MAKER"

    run(
        "A02",
        "invented_maker_fill",
        detect_maker_fill,
        paper,
        _inject_maker,
        "a fill claims maker liquidity, which no model in this package produces",
        legacy="S17 invented_maker_fill",
    )

    # S27 successor: the runtime quietly moved to live
    def _enable_live(payload: dict[str, Any]) -> None:
        payload["text"] = payload["text"].replace("paper", "live") + "\nlive_trading: true\n"

    run(
        "A03",
        "runtime_change_enabling_live",
        detect_live_enabled,
        config_text,
        _enable_live,
        "the runtime configuration no longer puts the bot in paper mode",
        legacy="S27 runtime_change_enabling_live",
    )

    run(
        "A04",
        "dataset_digest_replaced",
        detect_dataset_digest,
        paper,
        lambda p: p["dataset"].update({"exported_sha256": "0" * 64}),
        "the recorded dataset hash does not match the exported bars",
    )

    run(
        "A05",
        "broker_commission_charged_on_exit_notional",
        detect_broker_commission_units,
        paper,
        lambda p: p["arms"]["SANDBOX_ADMISSION"]["exits"][0].update(
            {"pnl": p["arms"]["SANDBOX_ADMISSION"]["exits"][0]["pnl"] + 0.5}
        ),
        "a fill's net PnL no longer reconciles with the broker's charging rule",
    )

    run(
        "A06",
        "fee_convention_identity_broken",
        detect_fee_identity,
        fee,
        lambda p: p["engines"]["jesse"].update({"identity_holds": False}),
        "an engine's per-trade residual no longer satisfies the closed-form gap",
    )

    run(
        "A07",
        "reported_residual_swapped",
        detect_parity_convention_gap,
        parity,
        lambda p: p["comparison"]["detail"]["per_trade"][0].update(
            {"net_bps_diff_additive": 0.0, "net_bps_diff_compounded": 0.0}
        ),
        "a residual pair was edited so the identity no longer holds",
    )

    run(
        "A08",
        "trade_count_inflated_by_duplication",
        detect_duplicate_trades,
        jesse,
        lambda p: p["comparison"]["detail"]["per_trade"].append(
            dict(p["comparison"]["detail"]["per_trade"][0])
        ),
        "the same trade appears twice, which inflates the trade count",
    )

    run(
        "A09",
        "oos_slice_read_by_selection",
        detect_oos_leak,
        oos,
        lambda p: p.update({"selection_has_read_this_slice": True}),
        "the reserved holdout was read while choosing a strategy",
    )

    run(
        "A10",
        "unknown_stage_reported_as_measured_zero",
        detect_unknown_is_zero,
        trade_path,
        lambda p: p["arms"]["GATE_INTACT"]["stages"]["ROUTER"].update(
            {"ledger": "absent", "count": 0}
        ),
        "a stage with no ledger is reported as a measured zero",
    )

    executed = [c for c in cases if c["kind"] == "TAMPER_DETECTED"]
    legacy = [c for c in cases if c["replaces_legacy_policy_assertion"]]
    payload: dict[str, Any] = {
        "schema_version": "EDGE14R_ADVERSARIAL_V1",
        "work_package": "WP-EDGE-14R/P4",
        "order_sent": False,
        "promotion": "NONE",
        "cases": cases,
        "counts": {
            "total": len(cases),
            "executed": len(executed),
            "declared": 0,
            "passed": sum(1 for c in cases if c["passed"]),
            "failed": sum(1 for c in cases if not c["passed"]),
        },
        "separation": (
            "every case in this suite is EXECUTED: a detector runs on the untouched "
            "artifact and on a mutated copy, and only a quiet-then-firing pair counts as a "
            "pass. There are no declared-only cases here"
        ),
        "legacy_policy_assertions_replaced": [
            c["replaces_legacy_policy_assertion"] for c in legacy
        ],
        "legacy_note": (
            "S12, S17 and S27 were POLICY_ASSERTED in RFC-EDGE-014: the artifacts they "
            "needed did not exist. Two of the three now exist (a real fill ledger and a "
            "real paper runtime), so all three are executed tests here, and the earlier "
            "declared grouping is left untouched in its own report"
        ),
        "limitations": [
            "a detector that is written by the same author as the artifact can share its "
            "blind spots; the clean/tampered pairing removes the most common one",
            "the suite tests this package's own evidence, not the engine internals",
        ],
    }
    (OUT / "ADVERSARIAL_SUITE.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    failed = payload["counts"]["failed"]
    for case in cases:
        mark = "PASS" if case["passed"] else "FAIL"
        print(
            f"[adv] {mark} {case['id']} {case['name']:44s} "
            f"clean={case['detector_fired_on_clean']} tampered={case['detector_fired_on_tampered']}"
        )
    print(f"[adv] {payload['counts']['passed']}/{payload['counts']['total']} executed cases pass")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
