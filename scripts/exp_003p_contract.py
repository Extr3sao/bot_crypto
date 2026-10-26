"""exp_003p_contract — everything EXP-003P decided *before* it ran anything.

Frozen here: the paths, the runtime that is instrumented, the frozen-data window, the
scenario scripts the venue will be asked to play, the success rules and the inventory of
negative controls with the exact class each must be detected as. Nothing here computes an
order, a fill or a verdict.

The preregistration is written from this module, so the protocol and the rehearsal cannot
disagree about what was promised: they read the same constants.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[1]
OUT: Final = REPO / "reports" / "ai-bots" / "EXP-003P-PAPER-EXECUTION-001"
DATASET: Final = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
SOURCE_003O_DIR: Final = REPO / "reports" / "ai-bots" / "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001"

RUN_ID: Final = "EXP-003P-PAPER-EXECUTION-001"
SCHEMA_PROTOCOL: Final = "AI_BOTS_003P_PROTOCOL_V1"
SCHEMA_TRACE: Final = "AI_BOTS_003P_ENVELOPE_V1"
SCHEMA_RUN_REPORT: Final = "AI_BOTS_003P_RUN_REPORT_V1"

#: The protocol is dated by hand, not by the clock: a preregistration whose date changes
#: every time it is re-rendered is a document changing under the experiment.
PROTOCOL_FROZEN_UTC: Final = "2026-10-21T00:00:00Z"

# -- the runtime that is instrumented ---------------------------------------

RUNTIME: Final[dict[str, Any]] = {
    "entrypoint": "scripts/exp_003p_rehearsal.py",
    "lanes": ["trading_bot.vision.lane.VisionLane"],
    "signal_source": "strategy_experimental",
    "strategy_id": "ema_crossover",
    "risk": "trading_bot.risk.manager.RiskManager",
    "execution_boundary": "trading_bot.paper.broker.PaperBroker",
    "instrumentation": "trading_bot.paper.lifecycle.recorder.PaperBrokerRecorder",
    "provenance": "OFFLINE_SIMULATED",
    "provider_environment": "OFFLINE",
    "live": False,
}

#: The TEST partition of 003O (2026-07-26T00:00:00Z .. 2026-08-06T00:00:00Z): real frozen
#: bars, outside the holdout. No window is widened if a slot comes out empty.
WINDOW: Final[dict[str, Any]] = {
    "start_utc": "2026-07-26T00:00:00Z",
    "end_utc": "2026-08-06T00:00:00Z",
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "timeframe": "1h",
    "window_bars": 120,
    "decision_every_bars": 4,
    "equity_usdt": 10_000.0,
    "subbar_entries": False,
    "holdout_touched": False,
}

#: The offline fee schedule the lifecycle scenario venue charges. Declared once; the
#: rehearsal's broker keeps its own committed cost schedule.
SCENARIO_FEE_BPS: Final = 4.0

#: Scenario scripts the offline venue plays, frozen before the run. ``salt`` moves the
#: reference price by a deterministic amount so two orders do not share a price.
SCENARIOS: Final[tuple[dict[str, Any], ...]] = (
    {
        "scenario_id": "S01_FULL_FILL",
        "mode": "FULL_FILL",
        "quantity": 1.0,
        "side": "buy",
        "tranches": [1.0],
        "fill_delays_ms": [120],
        "duplicate_last": False,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "FILLED",
    },
    {
        "scenario_id": "S02_PARTIAL_THEN_FILL",
        "mode": "PARTIAL_THEN_FILL",
        "quantity": 2.0,
        "side": "buy",
        "tranches": [0.4, 0.6],
        "fill_delays_ms": [90, 240],
        "duplicate_last": False,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "FILLED",
    },
    {
        "scenario_id": "S03_PARTIAL_THEN_CANCEL",
        "mode": "PARTIAL_THEN_CANCEL",
        "quantity": 2.0,
        "side": "sell",
        "tranches": [0.5],
        "fill_delays_ms": [150],
        "duplicate_last": False,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "CANCELED",
    },
    {
        "scenario_id": "S04_DUPLICATE_DELIVERY",
        "mode": "FULL_FILL",
        "quantity": 1.5,
        "side": "buy",
        "tranches": [1.0],
        "fill_delays_ms": [75],
        "duplicate_last": True,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "FILLED",
    },
    {
        "scenario_id": "S05_OUT_OF_ORDER",
        "mode": "PARTIAL_THEN_FILL",
        "quantity": 1.0,
        "side": "buy",
        "tranches": [0.5, 0.5],
        "fill_delays_ms": [40, 80],
        "duplicate_last": False,
        "deliver_fills_before_ack": True,
        "expected_terminal_state": "FILLED",
    },
    {
        "scenario_id": "S06_TIMEOUT_UNKNOWN",
        "mode": "TIMEOUT_UNKNOWN",
        "quantity": 1.0,
        "side": "buy",
        "tranches": [1.0],
        "fill_delays_ms": [100],
        "duplicate_last": False,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "UNKNOWN",
    },
    {
        "scenario_id": "S07_REJECT",
        "mode": "REJECT_AT_SUBMIT",
        "quantity": 1.0,
        "side": "buy",
        "tranches": [1.0],
        "fill_delays_ms": [100],
        "duplicate_last": False,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "REJECTED",
    },
    {
        "scenario_id": "S08_ACK_WITHOUT_FILL",
        "mode": "ACK_WITHOUT_FILL",
        "quantity": 1.0,
        "side": "buy",
        "tranches": [1.0],
        "fill_delays_ms": [100],
        "duplicate_last": False,
        "deliver_fills_before_ack": False,
        "expected_terminal_state": "ACKNOWLEDGED",
    },
)

#: Deterministic reference prices for the scenarios: no randomness, no market data needed.
SCENARIO_REFERENCE_PRICE: Final = 100.0

#: Success rules of the phase, written before any number exists.
SUCCESS_RULES: Final[dict[str, Any]] = {
    "OFFLINE_RUNTIME_VALIDATION": {
        "requires": [
            "two rehearsals produce the same trace digest",
            "every persisted event carries provenance, adapter and correlation",
            "no illegal transition and no unexplained anomaly in the runtime phase",
            "reconciliation against the broker book is PASS",
            "scenario reconciliation against the venue snapshot is PASS",
            "live_orders == 0",
        ],
        "on_failure": "FAIL",
    },
    "PAPER_VALIDATION": {
        "requires": [
            "an authorised paper provider, endpoint and account already configured",
            "at least one fill observed from that provider in the evaluated cycle",
        ],
        "on_absence": "BLOCKED_NOT_CONFIGURED",
        "note": (
            "No paper venue is configured in this workspace. The phase therefore reports "
            "BLOCKED and does not relabel an offline simulation as observed paper."
        ),
    },
    "FINAL_STATUS": "PARTIAL unless PAPER_VALIDATION is PASS",
}

#: The negative-control inventory. Each entry names the single defect it injects and the
#: class that must be observed; a control detected as "some other error" does not count.
CONTROLS: Final[tuple[dict[str, str], ...]] = (
    {"control_id": "NEG-01", "defect": "acknowledgement without a fill",
     "expected_class": "ACK_NOT_FILL"},
    {"control_id": "NEG-02", "defect": "partial fill that never completes", "expected_class": "PARTIAL_ACCOUNTING"},
    {"control_id": "NEG-03", "defect": "cancel after a partial fill", "expected_class": "PARTIAL_PRESERVED"},
    {"control_id": "NEG-04", "defect": "venue rejection of the order", "expected_class": "ZERO_FILL"},
    {"control_id": "NEG-05", "defect": "duplicate delivery of one fill", "expected_class": "DUPLICATE_FILL"},
    {"control_id": "NEG-06", "defect": "retry after an acknowledgement timeout", "expected_class": "UNKNOWN_REQUIRES_RECONCILIATION"},
    {"control_id": "NEG-07", "defect": "chronologically out-of-order event", "expected_class": "OUT_OF_ORDER_EVENT"},
    {"control_id": "NEG-08", "defect": "fill observed before its acknowledgement", "expected_class": "FILL_WITHOUT_ACK"},
    {"control_id": "NEG-09", "defect": "fill quantity altered in the persisted trace", "expected_class": "DATA_INTEGRITY_FAIL"},
    {"control_id": "NEG-10", "defect": "provenance relabelled after the fact", "expected_class": "PROVENANCE_MISMATCH"},
    {"control_id": "NEG-11", "defect": "slippage requested without a point-in-time quote", "expected_class": "NOT_AVAILABLE"},
    {"control_id": "NEG-12", "defect": "primary source unavailable at reconciliation", "expected_class": "INCOMPLETE"},
    {"control_id": "NEG-13", "defect": "decision taken on data from the future", "expected_class": "CAUSALITY_VIOLATION"},
    {"control_id": "NEG-14", "defect": "adapter pointed at a live environment",
     "expected_class": "LIVE_MODE_FORBIDDEN"},
    {"control_id": "NEG-15", "defect": "submit without a risk-approved intent", "expected_class": "RISK_GATE_VIOLATION"},
    {"control_id": "NEG-16", "defect": "ledger missing a fill the venue reported", "expected_class": "RECONCILIATION_FAIL"},
    {"control_id": "NEG-17", "defect": "NO_TRADE decision carried into an order", "expected_class": "ZERO_ORDER_INTENT"},
)

ACCEPTANCE_CRITERIA: Final[tuple[dict[str, str], ...]] = (
    {"req": "REQ-003P-01", "acc": "runtime authority map + reachable PaperBroker demonstration"},
    {"req": "REQ-003P-02", "acc": "every event carries provenance, adapter, clock, correlation"},
    {"req": "REQ-003P-03", "acc": "data_time <= decision_time <= event_time on every event"},
    {"req": "REQ-003P-04", "acc": "no submit without risk approval and policy identity"},
    {"req": "REQ-003P-05", "acc": "only legal transitions; ACK != FILL; terminal states hold"},
    {"req": "REQ-003P-06", "acc": "one fill key books exactly once across replay and duplicates"},
    {"req": "REQ-003P-07", "acc": "quantities, cash, positions, fees and PnL rebuilt from events"},
    {"req": "REQ-003P-08", "acc": "reconciliation PASS/FAIL/INCOMPLETE, never a simulated source"},
    {"req": "REQ-003P-09", "acc": "timeouts and unknowns produce no duplicate order or invented fill"},
    {"req": "REQ-003P-10", "acc": "trace, metrics, per-provenance counts and a verifiable manifest"},
    {"req": "REQ-003P-11", "acc": "each control fails with its declared class, not any error"},
    {"req": "REQ-003P-12", "acc": "separate verification program; organisational independence declared"},
    {"req": "REQ-003P-13", "acc": "LIVE unreachable, no secrets, config hashes preserved"},
    {"req": "REQ-003P-14", "acc": "two offline runs produce the same canonical digest"},
)

#: Configuration files whose bytes must not move, checked at baseline and at the seal.
FROZEN_CONFIGS: Final = (
    "config/runtime.yaml",
    "config/risk.yaml",
    "config/vision.yaml",
)

#: Artefacts another agent may be editing; 003P never writes them.
DO_NOT_TOUCH: Final = (
    "docs/agentic/EXECUTION_CHECKPOINT.md",
    "config/runtime.yaml",
    "config/risk.yaml",
    "config/vision.yaml",
)


def parse_utc_ms(text: str) -> int:
    """ISO-8601 UTC with or without milliseconds → epoch milliseconds."""

    from datetime import UTC, datetime

    value = text[:-1] if text.endswith("Z") else text
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in value else "%Y-%m-%dT%H:%M:%S"
    return int(datetime.strptime(value, fmt).replace(tzinfo=UTC).timestamp() * 1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload), encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False
    ).stdout.strip()


def config_digest() -> str:
    """One digest over the three frozen configuration files."""

    digest = hashlib.sha256()
    for relative in FROZEN_CONFIGS:
        path = REPO / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0" if path.exists() else b"\1")
        if path.exists():
            digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def protocol_payload() -> dict[str, Any]:
    """The frozen protocol, assembled from the constants above and nothing else."""

    return {
        "schema_version": SCHEMA_PROTOCOL,
        "run_id": RUN_ID,
        "experiment": RUN_ID,
        "frozen_at_utc": PROTOCOL_FROZEN_UTC,
        "dependency": {
            "experiment": "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001",
            "status": "PASS_PARTIAL_INCOMPLETE_REAL_DATA",
            "inherited": {
                "technical_signal_parity": "PASS",
                "full_independent_certification": "INCOMPLETE_REAL_DATA_COVERAGE",
                "organizational_independence": False,
                "economic_edge": "NOT_EVALUATED",
            },
        },
        "mode": "OFFLINE_SIMULATED",
        "live": {
            "enabled": False,
            "orders_allowed": 0,
            "flags_checked": ["runtime.mode", "features.enable_paper_trading"],
        },
        "runtime": RUNTIME,
        "window": WINDOW,
        "dataset": {
            "directory": str(DATASET.relative_to(REPO)).replace("\\", "/"),
            "files": {
                f"{symbol}.1m.jsonl.gz": sha256_file(DATASET / f"{symbol}.1m.jsonl.gz")
                for symbol in WINDOW["symbols"]
                if (DATASET / f"{symbol}.1m.jsonl.gz").exists()
            },
        },
        "config_digest": config_digest(),
        "scenarios": list(SCENARIOS),
        "scenario_fee_bps": SCENARIO_FEE_BPS,
        "scenario_reference_price": SCENARIO_REFERENCE_PRICE,
        "success_rules": SUCCESS_RULES,
        "controls": list(CONTROLS),
        "acceptance_criteria": list(ACCEPTANCE_CRITERIA),
        "declared_limits": [
            "the offline venue is a test double, not a paper broker; a fill from it proves "
            "code semantics and never venue acceptance",
            "the broker-observed events stamp the decision instant with the booking instant "
            "of the fill; the payload says so instead of inventing a decision clock",
            "the recorded risk gate on broker-observed events is the broker's notional "
            "guard, not a copy of the RiskManager transcript",
            "PAPER_VALIDATION stays BLOCKED until an authorised paper provider exists",
            "organisational independence is false: the same agent wrote producer, verifier "
            "and controls",
        ],
        "reproduction": {
            "commands": [
                "python scripts/exp_003p_pipeline.py baseline",
                "python scripts/exp_003p_pipeline.py preregister",
                "python scripts/exp_003p_pipeline.py rehearse --runs 2",
                "python scripts/exp_003p_pipeline.py controls",
                "python scripts/exp_003p_pipeline.py verify",
                "python scripts/exp_003p_pipeline.py tests",
                "python scripts/exp_003p_pipeline.py report",
                "python scripts/exp_003p_pipeline.py seal",
            ],
            "clean_checkout": "python scripts/exp_003p_rehearsal.py --checkout-check",
        },
    }


__all__ = [
    "ACCEPTANCE_CRITERIA",
    "CONTROLS",
    "DATASET",
    "DO_NOT_TOUCH",
    "FROZEN_CONFIGS",
    "OUT",
    "PROTOCOL_FROZEN_UTC",
    "RUNTIME",
    "RUN_ID",
    "SCENARIOS",
    "SCENARIO_FEE_BPS",
    "SCENARIO_REFERENCE_PRICE",
    "SCHEMA_PROTOCOL",
    "SCHEMA_RUN_REPORT",
    "SCHEMA_TRACE",
    "SOURCE_003O_DIR",
    "SUCCESS_RULES",
    "WINDOW",
    "canonical_json",
    "config_digest",
    "git",
    "parse_utc_ms",
    "protocol_payload",
    "read_json",
    "sha256_file",
    "write_json",
]
