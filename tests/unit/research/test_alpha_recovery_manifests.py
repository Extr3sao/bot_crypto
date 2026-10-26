"""ARP-004 §30 — manifest-integrity, cost-model and split-integrity tests.

The frozen ARP-003 manifests for EXP-ARP-007/010 are the pre-registration that
ARP-004 executes; these tests fail loudly if they drift. Data-fingerprint
assertions are skipped when the (git-ignored) corpus is not present.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402

MANIFEST_DIR = REPO / "docs/research/alpha_recovery_v1_2/experiments"
ADMISSION_CFG = REPO / "config/strategy_admission.json"
CORPUS = REPO / "reports/strategy-baseline/data"

EXPERIMENTS = ("EXP-ARP-007", "EXP-ARP-010")


def _lf_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_frozen_manifest_is_present_and_pre_registered(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["experiment_id"] == exp_id
    assert manifest["frozen_before_results"] is True
    assert manifest["status"] == "PREREGISTERED_NOT_IMPLEMENTED"
    assert manifest["config_hash"] == C.sha256_file(ADMISSION_CFG)
    assert manifest["splits"]["DEV"] == list(C.SPLIT_WINDOWS["DEV"])
    assert manifest["splits"]["VALIDATION"] == list(C.SPLIT_WINDOWS["VALIDATION"])
    assert manifest["splits"]["OOS_LOCK"] == list(C.SPLIT_WINDOWS["OOS_LOCK"])
    assert manifest["splits"]["oos_opened"] is False


@pytest.mark.skipif(not CORPUS.exists(), reason="frozen 5m corpus not present")
@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_frozen_manifest_data_and_cost_still_match(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["data"]["dataset_fingerprint"] == C.corpus_digest()
    assert manifest["cost_model"]["round_trip_bps"] == pytest.approx(C.cost_model_v3_rt_bps())


def test_cost_model_v3_is_authoritative_and_stable() -> None:
    from trading_bot.autonomous.costs import COST_MODEL_VERSION, CostEngine

    bps = C.cost_model_v3_rt_bps()
    engine = CostEngine().evaluate(size_usd=500.0, horizon_minutes=30.0)
    assert COST_MODEL_VERSION == "COST_MODEL_V3"
    assert bps == pytest.approx(float(engine.round_trip_bps))
    assert bps == pytest.approx(23.559016994374947, rel=1e-12)


def test_splits_are_disjoint_and_oos_is_separate() -> None:
    dev, val, oos = (set(C.SPLIT_WINDOWS[k]) for k in ("DEV", "VALIDATION", "OOS_LOCK"))
    assert not dev & val and not dev & oos and not val & oos
    assert oos == {"W7_2026-09"}


def test_manifest_lf_digest_matches_recorded_value() -> None:
    # a stable, line-ending-independent label for each frozen pre-registration
    recorded = {
        "EXP-ARP-007": "b338beeea154df1c8a304e913e03bfe61f7371617ecc4739cad134734e48c642",
        "EXP-ARP-010": "d8dc71a32daab27e11455ecf94181ae724e4c541c6c839c1d487b6261821eb07",
    }
    for exp_id, expected in recorded.items():
        assert _lf_digest(MANIFEST_DIR / exp_id / "MANIFEST.json") == expected
