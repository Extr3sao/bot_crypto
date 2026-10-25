"""ARP-006 §1,§15,§26 — frozen manifests, new ids, OOS firewall tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

EXP_DIR = REPO / "docs/research/alpha_diversified_v1/experiments"
NEW_IDS = ("EXP-ARP-016", "EXP-ARP-017", "EXP-ARP-018")


def test_new_experiment_manifests_exist_and_are_frozen() -> None:
    for exp_id in NEW_IDS:
        manifest = json.loads((EXP_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["experiment_id"] == exp_id
        assert manifest["frozen_before_results"] is True
        assert manifest["splits"]["oos_opened"] is False
        assert manifest["cost_model"]["version"] == "COST_MODEL_V3"
        assert (EXP_DIR / exp_id / "SPEC.md").exists()


def test_new_experiment_ids_do_not_collide_with_arp005_configurations() -> None:
    for exp_id in NEW_IDS:
        manifest = json.loads((EXP_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
        prior = manifest.get("prior_art", {}).get("experiment_id")
        assert prior in {"EXP-ARP-013", "EXP-ARP-014", "EXP-ARP-015"}
        assert prior != exp_id


def test_reversal_acknowledges_consumed_validation() -> None:
    manifest = json.loads((EXP_DIR / "EXP-ARP-017" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["validation_split_status"] == "CONSUMED_BY_EXP_ARP_014"
    assert manifest["max_achievable_verdict"] == "VALIDATION_SURVIVOR"


def test_oos_is_sealed_for_every_new_experiment() -> None:
    for exp_id in NEW_IDS:
        manifest = json.loads((EXP_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["splits"]["oos_opened"] is False


def test_split_boundaries_match_the_data_module() -> None:
    from trading_bot.research.diversified import data as D

    assert D.SPLIT_RANGES["DEV"][1] == D.DEV_END_MS
    assert D.SPLIT_RANGES["VALIDATION"][1] == D.VAL_END_MS
    assert D.DEV_VAL_RANGE[1] == D.VAL_END_MS
