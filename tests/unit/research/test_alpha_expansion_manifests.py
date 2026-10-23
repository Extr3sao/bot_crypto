"""ARP-005 ALPHA EXPANSION §18/§24/§31 — manifest integrity + split firewall.

The frozen manifests are the pre-registration the driver executes. The split
firewall proves the OOS window is never read when an earlier gate fails.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_expansion import data as D  # noqa: E402
from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402

MANIFEST_DIR = REPO / "docs/research/alpha_expansion_v1/experiments"
ADMISSION_CFG = REPO / "config/strategy_admission.json"
BASELINE_FP = "9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658"
EXPANSION_FP = "2ce6e6b5ff1c84d6b365934ab9fbcb0b2ee987a4f041354c454ec6aca952e04a"
DRIVER = REPO / "scripts/alpha_expansion_v1.py"
EXPERIMENTS = ("EXP-ARP-013", "EXP-ARP-014", "EXP-ARP-015")


def _driver() -> Any:
    spec = importlib.util.spec_from_file_location("alpha_expansion_v1_driver", DRIVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_frozen_manifest_present_and_pre_registered(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["experiment_id"] == exp_id
    assert manifest["frozen_before_results"] is True
    assert manifest["config_hash"] == C.sha256_file(ADMISSION_CFG)
    assert manifest["splits"]["oos_opened"] is False
    assert manifest["cost_model"]["version"] == "COST_MODEL_V3"


@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_manifest_splits_match_declared_ranges(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    for split in ("DEV", "VALIDATION", "OOS_LOCK"):
        assert manifest["splits"][split] == list(D.SPLIT_RANGES[split])


@pytest.mark.skipif(not D.EXPANSION_CORPUS.exists(), reason="expansion corpus not present")
@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_manifest_records_the_expansion_digest_and_untouched_baseline(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["data"]["dataset_fingerprint"] == EXPANSION_FP
    assert D.expansion_corpus_digest() == EXPANSION_FP
    assert manifest["data"]["baseline_fingerprint_untouched"] == BASELINE_FP
    if (REPO / "reports/strategy-baseline/data").exists():
        assert C.corpus_digest() == BASELINE_FP  # the expansion never moved the baseline


@pytest.mark.skipif(not D.EXPANSION_CORPUS.exists(), reason="expansion corpus not present")
def test_split_firewall_oos_is_never_read_when_dev_fails() -> None:
    drv = _driver()
    seen: list[str] = []

    def fake_metrics(
        exp_id: str, split: str, cfg: Any, cost_bps_rt: float, subset: Any = None
    ) -> dict[str, Any]:
        seen.append(split)
        return {
            "trades": 40,
            "expectancy_gross_bps": -50.0,
            "expectancy_net_bps": -73.0,
            "profit_factor": 0.5,
            "concentration": {"top1_share": 0.2},
        }

    drv.metrics = fake_metrics  # type: ignore[assignment]
    drv.duplicate_check = lambda exp_id, cfg: {"result": "PASS"}  # type: ignore[assignment]
    drv.write_json = lambda path, doc: "x"  # type: ignore[assignment]

    res = drv.run_experiment("EXP-ARP-013")
    assert "OOS_LOCK" not in seen
    assert "VALIDATION" not in seen
    assert res["decision"]["oos_opened"] is False
    assert res["decision"]["final"] == "REJECT_NO_EDGE"


@pytest.mark.skipif(not D.EXPANSION_CORPUS.exists(), reason="expansion corpus not present")
def test_dev_daily_depth_meets_frozen_horizon_bands() -> None:
    # EXP-ARP-006 needs 230-330 DEV days; EXP-ARP-008 needs 830-1230 DEV days.
    dev = D.load_lower_bars("BTCUSDT", "DEV")
    days = {ts // 86_400_000 for ts in (b.timestamp for b in dev)}
    assert len(days) >= 1230  # comfortably past the 20-day-hold band
