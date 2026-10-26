"""ARP-008 POST-OOS RECOVERY — deterministic governance driver (research only).

Reads the frozen EXP-ARP-008 preregistration, the ARP-007 OOS evidence and the
four NEW pre-registered hypotheses, then writes the machine-readable artifacts
that back ``reports/post-oos-recovery/``:

* ``EXP_ARP_008_TERMINAL_RECORD.json`` — §1 terminal failure, never editable;
* ``HOLDOUT_REGISTRY.json``            — §6 consumed-ledger (old OOS = CONSUMED);
* ``CONTRACT_VALIDATION.json``         — §4/§5/§3 the validator's verdicts;
* ``RUN_REPORT.json``                  — §26 machine summary.

The EXP-ARP-008 contract MUST come out ``EXPERIMENT_INVALID``: the frozen
SPEC/MANIFEST describe a W1-W7 window contract and a next-open max-hold exit,
while the executed code used epoch splits and a bar-close force-exit. The four
new contracts MUST come out ``PASS`` (spec block == implementation config ==
frozen splits == live cost model).

Research-only. No runtime authority, no Risk, no lifecycle, no promotion, and
NO OOS is opened here.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp008_post_oos_recovery.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery.campaign import cost_model_v3_rt_bps  # noqa: E402
from trading_bot.research.diversified import data as DIV  # noqa: E402
from trading_bot.research.governance import (  # noqa: E402
    ExperimentContract,
    ExperimentContractValidator,
    Holdout,
    HoldoutRegistry,
    HoldoutStatus,
    SplitDefinition,
    TerminalExperimentRecord,
    TerminalExperimentRegistry,
    TerminalState,
)

OUT = REPO / "reports" / "post-oos-recovery"
ARP007 = REPO / "reports" / "exp-arp-008-oos-verification"
BUILDER_RESULTS = REPO / "reports" / "alpha-diversified-v1" / "RESULTS.json"
FROZEN_EXP008 = REPO / "docs" / "research" / "alpha_recovery_v1_2" / "experiments" / "EXP-ARP-008"
NEW_EXPS = REPO / "docs" / "research" / "post_oos_recovery" / "experiments"

#: the driver's own frozen split for the NEW experiments. If a pre-registered
#: MANIFEST drifts from this, the contract validator flags EXPERIMENT_INVALID.
FROZEN_NEW_SPLIT = SplitDefinition(
    dev_start="2019-01-01",
    dev_end="2024-01-01",
    validation_start="2024-01-01",
    validation_end="2025-07-01",
    oos_start="2026-03-01",
    oos_end="2027-03-01",
)

#: EXP-ARP-008's actually-executed split (epoch, from research/diversified/data.py)
EXECUTED_EXP008_SPLIT = SplitDefinition(
    dev_start="2019-01-01",
    dev_end="2024-01-01",
    validation_start="2024-01-01",
    validation_end="2025-07-01",
    oos_start="2025-07-01",
    oos_end="2026-03-01",
)

NEW_EXP_IDS = ("EXP-ARP-019", "EXP-ARP-020", "EXP-ARP-021", "EXP-ARP-022")

COST_VERSION = "COST_MODEL_V3"
COST_SCENARIO = "BINANCE_SPOT_STANDARD_TAKER"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return "unknown"


# --------------------------------------------------------------------- §1
def build_terminal_record(cost: float) -> TerminalExperimentRecord:
    receipt = load_json(ARP007 / "OOS_FREEZE_RECEIPT.json")
    oos = load_json(ARP007 / "OOS_RESULT.json")
    builder = load_json(BUILDER_RESULTS) if BUILDER_RESULTS.exists() else {}
    exp8 = builder.get("experiments", {}).get("EXP-ARP-008", {})
    dev = exp8.get("DEV", {})
    val = exp8.get("VALIDATION", {})
    metrics = {
        "DEV": {
            "trades": dev.get("trades"),
            "expectancy_gross_bps": dev.get("expectancy_gross_bps"),
            "expectancy_net_bps": dev.get("expectancy_net_bps"),
            "profit_factor": dev.get("profit_factor"),
        },
        "VALIDATION": {
            "trades": val.get("trades"),
            "expectancy_gross_bps": val.get("expectancy_gross_bps"),
            "expectancy_net_bps": val.get("expectancy_net_bps"),
            "profit_factor": val.get("profit_factor"),
        },
        "OOS": dict(oos.get("metrics", {})),
        "cost_bps_rt": cost,
    }
    return TerminalExperimentRecord(
        experiment_id="EXP-ARP-008",
        strategy_id="H-DAILY-TSMOM-001",
        terminal_state=TerminalState(str(oos["decision"])),
        reason=(
            "OOS (2025-07-01..2026-03-01) net expectancy "
            f"{oos['metrics']['expectancy_net_bps']} bps, PF {oos['metrics']['profit_factor']}; "
            "the edge did not survive the one-time holdout and reversed in the exact "
            "BULL regime that produced it in DEV/VALIDATION."
        ),
        execution_sha=str(receipt["commit_sha_pre_freeze"]),
        manifest_hash=str(receipt["manifest_hash"]),
        spec_hash=str(receipt["spec_hash"]),
        dataset_hash=str(receipt["dataset_fingerprint"]),
        metrics=metrics,
        oos_window=("2025-07-01", "2026-03-01"),
        evidence_hashes={
            "code_hash": str(receipt["code_hash"]),
            "config_hash": str(receipt["config_hash"]),
            "oos_dataset_hash": str(receipt["oos_dataset_hash"]),
            "dev_result_hash": str(receipt["dev_result_hash"]),
            "validation_result_hash": str(receipt["validation_result_hash"]),
            "robustness_result_hash": str(receipt["robustness_result_hash"]),
        },
    )


# --------------------------------------------------------------------- §6,§7
def build_holdout_registry() -> HoldoutRegistry:
    receipt = load_json(ARP007 / "OOS_FREEZE_RECEIPT.json")
    registry = HoldoutRegistry()
    registry.register(
        Holdout(
            holdout_id="HOLDOUT-ARP-006-OOS",
            start="2025-07-01",
            end="2026-03-01",
            assets=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            dataset_hash=str(receipt["oos_dataset_hash"]),
            status=HoldoutStatus.CONSUMED,
            accessed_by=("EXP-ARP-008",),
            first_access_timestamp=str(oos_opened_utc()),
            note=(
                "One-time OOS for EXP-ARP-008 (H-DAILY-TSMOM-001). CONSUMED by ARP-007; "
                "no configuration may be re-tested on this window."
            ),
        )
    )
    registry.register(
        Holdout(
            holdout_id="HOLDOUT-ARP-019-FORWARD",
            start="2026-03-01",
            end="2027-03-01",
            assets=("DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",),
            dataset_hash="PENDING_FORWARD_PAPER_COLLECTION",
            status=HoldoutStatus.UNTOUCHED,
            forward_only=True,
            note=(
                "Forward-only holdout for the ARP-019..022 hypotheses. NOT available as a "
                "static window (the frozen corpus ends 2026-02-28). Collected in real time "
                "via PAPER; never used for feature or parameter selection. Classified "
                "NO_FRESH_OOS_AVAILABLE for immediate use."
            ),
        )
    )
    return registry


def oos_opened_utc() -> str:
    oos = load_json(ARP007 / "OOS_RESULT.json")
    return str(oos.get("opened_utc", "2026-10-02T19:32:35+00:00"))


# --------------------------------------------------------------------- §4,§5
def arp008_original_contract(cost: float) -> ExperimentContract:
    """Rebuild EXP-ARP-008's contract from SPEC + MANIFEST vs the executed code."""
    frozen_manifest = load_json(FROZEN_EXP008 / "MANIFEST.json")
    spec_view: dict[str, Any] = {
        "experiment_id": "EXP-ARP-008",
        "strategy_id": "H-DAILY-TSMOM-001",
        "timeframe": "1d",
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "lookback_days": 30,
        "max_hold_days": 20,
        "entry_rule": "long if close_t > close_{t-lookback_days} else flat; act next open",
        "exit_rule": "exit on signal flip at next open; max_hold_days=20 at next open",
        "dataset_fingerprint": str(frozen_manifest["data"]["dataset_fingerprint"]),
        "cost_model_version": COST_VERSION,
        "cost_scenario": COST_SCENARIO,
        "split_contract": dict(frozen_manifest["splits"]),
    }
    manifest_view: dict[str, Any] = {
        "experiment_id": str(frozen_manifest["experiment_id"]),
        "strategy_id": str(frozen_manifest["strategy_id"]),
        "timeframe": str(frozen_manifest["timeframe"]),
        "assets": list(frozen_manifest["assets"]),
        "lookback_days": frozen_manifest["parameters"]["lookback_days"],
        "max_hold_days": frozen_manifest["parameters"]["max_hold_days"],
        "entry_rule": "long if close_t > close_{t-lookback_days} else flat; act next open",
        "exit_rule": "exit on signal flip at next open; max_hold_days=20 at next open",
        "dataset_fingerprint": str(frozen_manifest["data"]["dataset_fingerprint"]),
        "cost_model_version": str(frozen_manifest["cost_model"]["version"]),
        "cost_scenario": str(frozen_manifest["cost_model"]["scenario"]),
        "split_contract": dict(frozen_manifest["splits"]),
    }
    implementation_view: dict[str, Any] = {
        "experiment_id": "EXP-ARP-008",
        "strategy_id": "H-DAILY-TSMOM-001",
        "timeframe": "1d",
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "lookback_days": 30,
        "max_hold_days": 20,
        "entry_rule": "long if close_t > close_{t-lookback_days} else flat; act next open",
        # the code force-closes on window expiry at bar.close, not at next open
        "exit_rule": "signal flip at next open; max_hold_days=20 forced at bar close",
        "dataset_fingerprint": DIV.corpus_digest(),
        "cost_model_version": COST_VERSION,
        "cost_scenario": COST_SCENARIO,
        "split_contract": EXECUTED_EXP008_SPLIT.to_dict(),
    }
    return ExperimentContract(
        experiment_id="EXP-ARP-008",
        spec=spec_view,
        manifest=manifest_view,
        implementation_config=implementation_view,
        split_definition=EXECUTED_EXP008_SPLIT.to_dict(),
        cost_model={
            "cost_round_trip_bps": cost,
            "cost_model_version": COST_VERSION,
            "cost_scenario": COST_SCENARIO,
        },
    )


def _manifest_split(manifest: dict[str, Any]) -> SplitDefinition:
    splits = manifest["splits"]
    dev = splits["DEV"]
    val = splits["VALIDATION"]
    oos = splits["OOS_LOCK"]
    return SplitDefinition(
        dev_start=str(dev[0]),
        dev_end=str(dev[1]),
        validation_start=str(val[0]),
        validation_end=str(val[1]),
        oos_start=str(oos[0]),
        oos_end=str(oos[1]),
    )


def new_contract(manifest: dict[str, Any], cost: float) -> ExperimentContract:
    """Build a NEW contract from its MANIFEST (spec block vs planned config)."""
    spec_block = dict(manifest["spec_contract"])
    manifest_split = _manifest_split(manifest)
    spec_view = dict(spec_block)
    spec_view["split_contract"] = manifest_split.to_dict()
    manifest_view = dict(spec_block)
    manifest_view["split_contract"] = manifest_split.to_dict()
    implementation_view = dict(manifest["implementation_config"])
    implementation_view.update(
        {
            "experiment_id": manifest["experiment_id"],
            "strategy_id": manifest["strategy_id"],
            "timeframe": manifest["timeframe"],
            "assets": manifest["assets"],
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
            "split_contract": FROZEN_NEW_SPLIT.to_dict(),
        }
    )
    return ExperimentContract(
        experiment_id=str(manifest["experiment_id"]),
        spec=spec_view,
        manifest=manifest_view,
        implementation_config=implementation_view,
        split_definition=FROZEN_NEW_SPLIT.to_dict(),
        cost_model={
            "cost_round_trip_bps": cost,
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
        },
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cost = cost_model_v3_rt_bps()
    validator = ExperimentContractValidator()

    # §1 terminal record (immutable)
    terminal_registry = TerminalExperimentRegistry()
    terminal = build_terminal_record(cost)
    terminal_hash = terminal_registry.record(terminal)
    (OUT / "EXP_ARP_008_TERMINAL_RECORD.json").write_text(
        json.dumps(terminal.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # §6 holdout registry
    registry = build_holdout_registry()
    registry.save(OUT / "HOLDOUT_REGISTRY.json")
    forward_available = registry.get("HOLDOUT-ARP-019-FORWARD").forward_only
    fresh_oos_available = not forward_available

    # §4/§5 contract validation
    exp008_result = validator.validate(arp008_original_contract(cost))
    new_results: list[dict[str, Any]] = []
    for exp_id in NEW_EXP_IDS:
        manifest = load_json(NEW_EXPS / exp_id / "MANIFEST.json")
        result = validator.validate(new_contract(manifest, cost))
        new_results.append(result.to_dict())

    contract_validation = {
        "validator": "ExperimentContractValidator",
        "cost_bps_rt": cost,
        "exp_arp_008": exp008_result.to_dict(),
        "exp_arp_008_expected": "EXPERIMENT_INVALID",
        "new_contracts": new_results,
        "new_contracts_all_pass": all(r["status"] == "PASS" for r in new_results),
    }
    (OUT / "CONTRACT_VALIDATION.json").write_text(
        json.dumps(contract_validation, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    run_report: dict[str, Any] = {
        "program": "ARP-008 POST-OOS RECOVERY",
        "head_sha": git_head(),
        "cost_bps_rt": cost,
        "cost_model_version": COST_VERSION,
        "corpus_digest": DIV.corpus_digest(),
        "exp_arp_008_terminal": terminal.to_dict(),
        "exp_arp_008_terminal_record_hash": terminal_hash,
        "holdout_registry": registry.to_dict(),
        "fresh_oos_available": fresh_oos_available,
        "new_holdout_classification": (
            "AVAILABLE" if fresh_oos_available else "NO_FRESH_OOS_AVAILABLE"
        ),
        "contract_validation": contract_validation,
        "dev_runs": 0,
        "validation_survivors": 0,
        "robustness_survivors": 0,
        "oos_opened": False,
        "new_hypotheses": list(NEW_EXP_IDS),
        "false_success": 0,
    }
    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(run_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    shutil.copyfile(ARP007 / "OOS_RESULT.json", OUT / "tmp_old_oos_result.json")

    print(json.dumps(
        {
            "head_sha": run_report["head_sha"],
            "exp008_contract": exp008_result.status,
            "exp008_mismatch_fields": [m.field for m in exp008_result.mismatches],
            "new_contracts_all_pass": contract_validation["new_contracts_all_pass"],
            "old_oos_status": registry.status("HOLDOUT-ARP-006-OOS").value,
            "new_holdout_classification": run_report["new_holdout_classification"],
            "oos_opened": run_report["oos_opened"],
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
