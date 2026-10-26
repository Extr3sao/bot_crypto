"""RFC-049 Phase A contract tests.

These tests pin the *preparation* state of Discovery 2 without importing either
the builder or the verifier as libraries:

- every mandatory deliverable exists;
- the frozen spec hashes agree across the files, the registry and the manifest;
- the statistical contract was not weakened below RFC-049 §16;
- the result files are explicit NOT_RUN contracts with no fabricated data;
- the governance flags the campaign must not change are intact;
- the independent-verification artefact still matches the bytes it verified.

Nothing here evaluates an economic hypothesis; that is Phase B work, which is
blocked by the activation gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "rfc049"

DELIVERABLES = (
    "docs/rfc/RFC-049_PROFITABILITY_DISCOVERY_2.md",
    "docs/rfc/RFC-049_PROFITABILITY_DISCOVERY_2.json",
    "docs/research/RFC049_HYPOTHESIS_REGISTRY.md",
    "docs/research/RFC049_SOURCE_REGISTRY.md",
    "docs/architecture/RFC049_RUNTIME_FLOW.md",
    "docs/governance/RFC049_DISCOVERY_ADMISSION.md",
    "data/rfc049/BASELINE_AUDIT.json",
    "data/rfc049/HYPOTHESIS_REGISTRY.json",
    "data/rfc049/PREREGISTRATION_MANIFEST.json",
    "data/rfc049/DATA_EXPOSURE_AUDIT.json",
    "data/rfc049/ECONOMIC_RESULTS.json",
    "data/rfc049/ROBUSTNESS_REPORT.json",
    "data/rfc049/INDEPENDENT_VERIFICATION.json",
    "data/rfc049/RUN_REPORT.md",
    "data/rfc049/RUN_REPORT.json",
    "data/rfc049/FINAL_REPORT.md",
    "data/rfc049/FINAL_REPORT.json",
)

REQUIRED_THRESHOLDS = (
    "net_expectancy_positive",
    "net_profit_factor_min",
    "net_pnl_oos_positive",
    "lcb_95_net_expectancy_positive",
    "cost_stress_1_5x_net_positive",
    "positive_in_every_partition",
    "minimum_oos_round_trips_or_months",
    "incremental_over_buy_and_hold_positive",
    "incremental_over_200d_trend_baseline_positive",
)

GOVERNANCE = {
    "DISCOVERY_CAMPAIGN_FAILED": True,
    "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
    "LIVE_TRADING": "DISABLED",
    "TRADES_AUTHORIZED": 0,
    "PROFITABILITY_VERIFIED": False,
}


def load(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


def canonical_hash(obj: dict) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_deliverables_exist() -> None:
    missing = [rel for rel in DELIVERABLES if not (REPO / rel).exists()]
    assert missing == []


def test_frozen_spec_hashes_agree() -> None:
    registry = load("data/rfc049/HYPOTHESIS_REGISTRY.json")
    manifest = load("data/rfc049/PREREGISTRATION_MANIFEST.json")
    listed = {row["hypothesis_id"]: row for row in registry["hypotheses"]}
    for spec_path in sorted((DATA / "specs").glob("H-049-*.json")):
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        hid = spec["hypothesis_id"]
        assert listed[hid]["spec_canonical_sha256"] == canonical_hash(spec)
        assert manifest["spec_hashes"][hid]["spec_canonical_sha256"] == canonical_hash(spec)
        assert listed[hid]["spec_file_sha256"] == sha256_file(spec_path)


def test_frozen_specs_carry_the_rfc049_minimum_contract() -> None:
    frozen = 0
    for spec_path in sorted((DATA / "specs").glob("H-049-*.json")):
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if spec["status"] != "SPEC_FROZEN":
            continue
        frozen += 1
        thresholds = spec["acceptance_thresholds"]
        assert all(key in thresholds for key in REQUIRED_THRESHOLDS)
        assert float(thresholds["net_profit_factor_min"]) >= 1.10
        assert str(thresholds["minimum_oos_round_trips_or_months"]).startswith("20 ")
        assert spec["parameters"]["parameter_searches"] == 0
        assert spec["cost_model"]["stress_multiple"] == 1.5
    assert frozen == 2


def test_results_are_not_run_contracts() -> None:
    for rel in ("data/rfc049/ECONOMIC_RESULTS.json", "data/rfc049/ROBUSTNESS_REPORT.json"):
        payload = load(rel)
        assert payload["status"] == "NOT_RUN"
        assert not payload.get("runs")
    economic = load("data/rfc049/ECONOMIC_RESULTS.json")
    assert economic["no_result_claim"] is True
    assert economic["consolidated_state"] == "DISCOVERY2_NOT_AUTHORIZED"


def test_governance_flags_untouched() -> None:
    live = load("data/rfc048/FINAL_REPORT.json")["NEXT_GATE"]["governance_preserved"]
    assert live == GOVERNANCE
    baseline = load("data/rfc049/BASELINE_AUDIT.json")["governance_preserved"]
    assert baseline == GOVERNANCE
    final = load("data/rfc049/FINAL_REPORT.json")
    assert final["CAMPAIGN_AUTHORIZATION"]["authorized"] is False
    assert final["EXPERIMENTS_EXECUTED"] == 0


def _leaf_values(obj, key=None):
    if isinstance(obj, dict):
        for k, value in obj.items():
            yield from _leaf_values(value, k)
    elif isinstance(obj, list):
        for item in obj:
            yield from _leaf_values(item, key)
    else:
        yield key, obj


def test_final_status_is_prepared_not_certified() -> None:
    final = load("data/rfc049/FINAL_REPORT.json")
    assert final["RFC049_STATUS"] == "RFC049_PREPARED_AWAITING_CAMPAIGN_AUTHORIZATION"
    forbidden = {"CERTIFIED_ALPHA", "PRODUCTION_READY", "READY_FOR_LIVE", "PROFITABLE"}
    claims = [
        value
        for key, value in _leaf_values(final)
        if key != "labels_never_used" and isinstance(value, str) and value in forbidden
    ]
    assert claims == []


def test_verification_artefact_matches_the_bytes_it_verified() -> None:
    verification = load("data/rfc049/INDEPENDENT_VERIFICATION.json")
    assert verification["status"] == "PASS"
    assert verification["checks_failed"] == 0
    assert verification["false_success"] == 0
    assert all(c["observed"] == c["expected"] for c in verification["negative_controls"])
    stale = [
        rel
        for rel, digest in verification["verified_artifacts"].items()
        if sha256_file(REPO / rel) != digest
    ]
    assert stale == []


def test_exposure_policy_classes_history_as_exposed() -> None:
    audit = load("data/rfc049/DATA_EXPOSURE_AUDIT.json")
    assert audit["policy"]["classes"] == [
        "RESEARCH_EXPOSED",
        "VALIDATION_CONTROLLED",
        "SEALED_OOS",
    ]
    sealed = audit["declared_partition_policy"]["sealed_oos"]
    assert "forward" in sealed and "single opening" in sealed
    manifest = load("data/rfc049/PREREGISTRATION_MANIFEST.json")
    assert manifest["sealed_oos_start_utc"] > manifest["freeze_timestamp_utc"]
