"""ARP-005 §7/§12/§20 — manifest integrity, extended corpus and split firewall.

The frozen ARP-005 manifests are the pre-registration that the driver executes; the
split-firewall test proves VALIDATION/OOS are never read when an earlier gate fails.
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

from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402
from trading_bot.research.alpha_recovery import extended as E  # noqa: E402

MANIFEST_DIR = REPO / "docs/research/alpha_recovery_v1_4/experiments"
ADMISSION_CFG = REPO / "config/strategy_admission.json"
BASELINE_CORPUS = REPO / "reports/strategy-baseline/data"
EXT_CORPUS = REPO / "reports/alpha-recovery-v1-4/data"
DRIVER = REPO / "scripts/alpha_recovery_v1_4.py"

EXPERIMENTS = ("EXP-ARP-009", "EXP-ARP-011", "EXP-ARP-012")
BASELINE_FP = "9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658"
EXT_FP = "d3669d28de0014bf4299361adb9cca2c4d0de9a9b856077b8e1bff92260030e0"
BASELINE_EXPS = ("EXP-ARP-009", "EXP-ARP-011")


@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_frozen_manifest_present_and_pre_registered(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["experiment_id"] == exp_id
    assert manifest["frozen_before_results"] is True
    assert manifest["config_hash"] == C.sha256_file(ADMISSION_CFG)
    assert manifest["splits"]["oos_opened"] is False
    assert manifest["cost_model"]["version"] == "COST_MODEL_V3"


@pytest.mark.parametrize("exp_id", EXPERIMENTS)
def test_manifest_splits_match_declared_windows(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    if exp_id == "EXP-ARP-012":
        assert manifest["splits"]["DEV"] == list(E.EXT_SPLIT_WINDOWS["DEV"])
    else:
        assert manifest["splits"]["DEV"] == list(C.SPLIT_WINDOWS["DEV"])
    assert manifest["splits"]["VALIDATION"] == list(C.SPLIT_WINDOWS["VALIDATION"])
    assert manifest["splits"]["OOS_LOCK"] == list(C.SPLIT_WINDOWS["OOS_LOCK"])


@pytest.mark.skipif(not BASELINE_CORPUS.exists(), reason="frozen 5m corpus not present")
@pytest.mark.parametrize("exp_id", BASELINE_EXPS)
def test_baseline_manifests_pin_the_untouched_frozen_fingerprint(exp_id: str) -> None:
    manifest = json.loads((MANIFEST_DIR / exp_id / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["data"]["dataset_fingerprint"] == BASELINE_FP
    assert C.corpus_digest() == BASELINE_FP  # extended fetch did NOT move the baseline


@pytest.mark.skipif(not EXT_CORPUS.exists(), reason="extended corpus not present")
def test_extended_manifest_and_digest_are_reproducible() -> None:
    manifest = json.loads((MANIFEST_DIR / "EXP-ARP-012/MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["data"]["dataset_fingerprint"] == EXT_FP
    assert E.ext_corpus_digest() == EXT_FP
    assert manifest["data"]["corpus"].startswith("reports/alpha-recovery-v1-4")


@pytest.mark.skipif(not EXT_CORPUS.exists(), reason="extended corpus not present")
def test_extended_corpus_reaches_the_reversal_adequacy_band() -> None:
    from trading_bot.research.alpha_recovery.daily import daily_bars_from_5m

    days = {}
    for symbol in C.SYMBOLS.values():
        bars = []
        for window in E.EXT_SPLIT_WINDOWS["DEV"]:
            bars.extend(E.load_ext_bars(symbol, window))
        days[symbol] = len(daily_bars_from_5m(bars))
    # ARP-004 band for a 5-day hold: ~230-330 DEV days/symbol
    assert all(230 <= n <= 330 for n in days.values()), days


def _load_driver() -> Any:
    spec = importlib.util.spec_from_file_location("_arp005_driver", DRIVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_split_firewall_never_reads_validation_when_dev_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    driver = _load_driver()
    real = driver.load_daily
    monkeypatch.setattr(driver, "OUT", tmp_path)

    def guarded(symbol: str, exp_id: str, split: str) -> Any:
        if split != "DEV":
            raise AssertionError(f"forbidden split read: {split} for {exp_id}")
        return real(symbol, exp_id, split)

    monkeypatch.setattr(driver, "load_daily", guarded)
    # EXP-ARP-011 DEV = INSUFFICIENT_EVIDENCE -> must never touch VALIDATION/OOS
    res = driver.run_experiment("EXP-ARP-011")
    assert res["decision"]["final"] == "INSUFFICIENT_EVIDENCE"
    assert res["decision"]["stages"]["VALIDATION"] == "NOT_REACHED"


def test_split_firewall_never_opens_oos_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    driver = _load_driver()
    real = driver.load_daily
    monkeypatch.setattr(driver, "OUT", tmp_path)

    def guarded(symbol: str, exp_id: str, split: str) -> Any:
        if split == "OOS_LOCK":
            raise AssertionError(f"OOS must stay locked after a validation fail: {exp_id}")
        return real(symbol, exp_id, split)

    monkeypatch.setattr(driver, "load_daily", guarded)
    # EXP-ARP-012 passes DEV + COST, fails VALIDATION -> OOS must never open
    res = driver.run_experiment("EXP-ARP-012")
    assert res["decision"]["final"] == "REJECT_VALIDATION"
    assert res["decision"]["oos_opened"] is False
