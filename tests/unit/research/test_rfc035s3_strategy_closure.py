"""Offline guards for the RFC-035S3 targeted-evidence-closure artifacts.

These tests do not touch the network and do not re-implement the round-3 verifier. They assert the
properties a later edit is most likely to break: the four-state semantics, the separation between
executable-rule completeness and evidence completeness, the additive-only supersession of the two
deep-dive candidates, the integrity manifest, and the canonical registry's append-only history.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RESEARCH = REPO / "research" / "profitability"
OPP_DIR = RESEARCH / "opportunities"
OUT = REPO / "reports" / "rfc035" / "search_round_3"
MANIFEST = REPO / "research" / "rfc035s3" / "ARTIFACT_MANIFEST.json"
SRC_DIR = REPO / "data" / "rfc035s3" / "sources"

STATES = ("EXPLICIT_VALUE", "EXPLICIT_NONE", "NOT_APPLICABLE", "UNKNOWN")
SETTLED = ("EXPLICIT_VALUE", "EXPLICIT_NONE", "NOT_APPLICABLE")
EXECUTABLE_FIELDS = (
    "assets_and_universe",
    "timeframe_and_calendar",
    "data_and_indicators",
    "entry",
    "exit",
    "sizing_and_allocation",
    "parameters",
    "warmup",
    "order_semantics_and_execution",
    "completion_conditions",
)
EVIDENCE_FIELDS = (
    "primary_source",
    "version_or_snapshot",
    "period",
    "operations",
    "results",
    "fees_and_costs",
    "data_quality_and_provenance",
)
FORBIDDEN = ("EDGE_CONFIRMED", "PROFITABLE", "READY_FOR_LIVE")
S3_SOURCES = tuple(f"S3-{i:02d}" for i in range(1, 12))
ROUND3_OPPORTUNITIES = ("OPP-0028", "OPP-0029", "OPP-0030", "OPP-0031", "OPP-0032", "OPP-0033")
OPP_REQUIRED = (
    "opportunity_id",
    "title",
    "source_ids",
    "economic_hypothesis",
    "market",
    "assets",
    "timeframe",
    "entry_rules",
    "exit_rules",
    "risk_rules",
    "parameters",
    "claimed_period",
    "claimed_metrics",
    "transaction_cost_model",
    "required_data",
    "external_code",
    "external_results",
    "forward_evidence",
    "live_evidence",
    "counter_evidence",
    "ambiguities",
    "replication_difficulty",
    "evidence_quality",
    "selection_bias_risk",
    "overfitting_risk",
    "lookahead_risk",
    "implementation_risk",
    "status",
    "evidence_scores",
    "evidence_score_total",
    "rank",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _audit() -> dict:
    return _load(OUT / "RULE_CONTRACT_AUDIT.json")


def _candidates() -> list[dict]:
    return _audit()["candidates"]


def _score(fields: dict[str, dict[str, str]], names: tuple[str, ...]) -> int:
    return sum(1 for n in names if fields[n]["state"] in SETTLED)


@pytest.mark.parametrize(
    "name",
    [
        "BASELINE.json",
        "RULE_CONTRACT_AUDIT.json",
        "CANDIDATE_DEEP_DIVE.json",
        "ECONOMIC_EVIDENCE.json",
        "REJECTION_LOG.json",
        "FINAL_REPORT.json",
        "INDEPENDENT_VERIFICATION.json",
    ],
)
def test_round3_artifacts_are_parseable(name: str) -> None:
    assert _load(OUT / name)


def test_the_eight_required_deliverables_exist() -> None:
    for name in (
        "BASELINE.md",
        "RULE_CONTRACT_AUDIT.md",
        "CANDIDATE_DEEP_DIVE.md",
        "ECONOMIC_EVIDENCE.md",
        "REJECTION_LOG.md",
        "INDEPENDENT_VERIFICATION.md",
        "FINAL_REPORT.md",
        "FINAL_REPORT.json",
    ):
        path = OUT / name
        assert path.is_file(), f"missing deliverable {name}"
        assert path.stat().st_size > 200, f"empty deliverable {name}"


def test_the_round_never_asserts_a_forbidden_verdict() -> None:
    for path in OUT.glob("*.md"):
        offenders = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if any(line.strip().startswith(v) for v in FORBIDDEN)
        ]
        assert not offenders, (path.name, offenders)


def test_final_status_blocks_rfc_036() -> None:
    report = _load(OUT / "FINAL_REPORT.json")
    assert report["final_status"] == "NO_SUITABLE_EXTERNAL_STRATEGY"
    assert report["replicate_p0"] == "NONE"
    assert "BLOCKED" in str(report["rfc_036"])
    assert report["flags"]["TRADES_AUTHORIZED"] == 0
    assert report["flags"]["EDGE_CONFIRMED"] is False


def test_every_field_uses_one_of_the_four_states() -> None:
    for candidate in _candidates():
        for axis, names in (("executable", EXECUTABLE_FIELDS), ("evidence", EVIDENCE_FIELDS)):
            table = candidate[axis]
            assert set(table) == set(names), (candidate["candidate_id"], axis)
            for name in names:
                assert table[name]["state"] in STATES, (candidate["candidate_id"], name)
                assert table[name]["note"].strip(), (candidate["candidate_id"], name)


def test_an_explicit_absence_is_settled_not_missing() -> None:
    """The defect round 3 corrected: a source that fixes an absence must not be scored as missing."""
    for candidate in _candidates():
        for axis, names in (("executable", EXECUTABLE_FIELDS), ("evidence", EVIDENCE_FIELDS)):
            recomputed = _score(candidate[axis], names)
            assert candidate[f"{axis}_completeness"]["settled"] == recomputed
            unknown = sorted(n for n in names if candidate[axis][n]["state"] == "UNKNOWN")
            assert candidate[f"{axis}_completeness"]["unknown"] == unknown
    used = [c["evidence"][n]["state"] for c in _candidates() for n in EVIDENCE_FIELDS]
    assert "EXPLICIT_NONE" in used, "the corrected semantics were never exercised"


def test_rule_completeness_and_evidence_completeness_are_reported_separately() -> None:
    for candidate in _candidates():
        rule = candidate["executable_completeness"]
        evidence = candidate["evidence_completeness"]
        assert rule["total"] == len(EXECUTABLE_FIELDS)
        assert evidence["total"] == len(EVIDENCE_FIELDS)
        assert "ratio" in rule and "ratio" in evidence


def test_no_candidate_is_promoted_to_replication() -> None:
    """A replication rank asserts an external strategy exists *and* carries evidence; neither does.

    The test fails if a candidate is ever promoted while its operations or results are not an explicit
    value in the source, which is the exact confusion round 2 fell into.
    """
    for candidate in _candidates():
        promoted = candidate["classification"] in ("REPLICATE_P0", "REPLICATE_P1")
        has_attributable_result = (
            candidate["evidence"]["operations"]["state"] == "EXPLICIT_VALUE"
            and candidate["evidence"]["results"]["state"] == "EXPLICIT_VALUE"
        )
        assert not (promoted and not has_attributable_result), candidate["candidate_id"]
        assert not (promoted and not candidate["executable_completeness"]["complete"]), candidate[
            "candidate_id"
        ]
        assert not (promoted and not candidate["evidence_completeness"]["complete"]), candidate[
            "candidate_id"
        ]


def test_the_two_deep_dives_are_superseded_additively() -> None:
    for oid in ("OPP-0011", "OPP-0016"):
        record = _load(OPP_DIR / f"{oid}.json")
        assert record["rank"] == "REPLICATE_P1", (
            "the frozen rank was rewritten instead of superseded"
        )
        assert record["current_rank"] not in ("REPLICATE_P0", "REPLICATE_P1")
        assert record["candidate_ref"].endswith("CANDIDATE_MATRIX.json")
        assert "REPLICATE_P1" in [item["rank"] for item in record["rank_history"]]
        correction = record["round_3_reclassification"]
        assert correction["corrected_rank"] == record["current_rank"]
        assert correction["reason"].strip()
        assert "/" in correction["executable_rule_completeness"]
        assert "/" in correction["evidence_completeness"]


@pytest.mark.parametrize("oid", ROUND3_OPPORTUNITIES)
def test_round3_opportunity_records_carry_the_full_schema(oid: str) -> None:
    record = _load(OPP_DIR / f"{oid}.json")
    missing = [k for k in OPP_REQUIRED if k not in record]
    assert not missing, (oid, missing)
    assert isinstance(record["ambiguities"], list)
    assert sum(record["evidence_scores"].values()) == record["evidence_score_total"]
    assert record["rank"] in {"WATCH", "INSUFFICIENT_EVIDENCE", "REJECT"}


def test_the_integrity_manifest_re_derives() -> None:
    manifest = _load(MANIFEST)
    assert manifest["file_count"] == len(manifest["files"]) >= 20
    for entry in manifest["files"]:
        path = REPO / entry["path"]
        assert path.is_file(), entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]
    canonical = json.dumps(
        manifest["files"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == manifest["bundle_digest"]
    assert manifest["copy_verified"] is True
    for copy in manifest["copies"]:
        target = REPO / copy["path"]
        assert target.is_file()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == copy["sha256"]


def test_the_frozen_snapshots_hash_to_their_recorded_digests() -> None:
    expected = {
        "strategy001_raw.py.txt": "2357996e6594458e8db45b5f757918462afa3c998de9d06e2af0c009ddc4b80d",
        "freqtrade_strategies_README.md": "50df38eb1b1ed410b5e41f55d8dd95e2a834cf89750781e38faa1b24a796b835",
        "quantiacs_q24_crypto_guide.html": "88cef01b970251d4c3a40f7ec5366005d75a80549bb9d19735e585c1004915ba",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((SRC_DIR / name).read_bytes()).hexdigest() == digest, name


def test_the_quantiacs_page_declares_no_cost_model_at_all() -> None:
    """The record claims the page's cost model is silence, not a declared absence."""
    text = (
        (SRC_DIR / "quantiacs_q24_crypto_guide.html")
        .read_text(encoding="utf-8", errors="replace")
        .lower()
    )
    for term in ("commission", "transaction cost", "slippage"):
        assert term not in text, term


def test_the_canonical_registry_gained_round_3_without_losing_history() -> None:
    registry = _load(RESEARCH / "source_registry.json")
    by_id = {s["SOURCE_ID"]: s for s in registry["sources"]}
    for sid in S3_SOURCES:
        assert sid in by_id, sid
        assert by_id[sid]["EVIDENCE_LEVEL"] in (
            "REAL_EXECUTION",
            "FORWARD_PAPER",
            "INDEPENDENT_REPLICATION",
            "REPRODUCIBLE_CODE",
            "ACADEMIC_PAPER",
            "AUTHOR_BACKTEST",
            "UNVERIFIED_CLAIM",
        )
        assert by_id[sid]["READ_LEVEL"] in ("full_text", "abstract_snippet", "listing")
    rounds = {r["rfc"]: r for r in registry["rounds"]}
    assert rounds["RFC-035S3"]["final_status"] == "NO_SUITABLE_EXTERNAL_STRATEGY"
    assert rounds["RFC-035S3"]["replicate_p0_selected"] == "NONE"
    assert "RFC-035" in rounds and "RFC-035S2" in rounds


def test_the_independent_verification_is_green_and_can_fail() -> None:
    verification = _load(OUT / "INDEPENDENT_VERIFICATION.json")
    assert verification["status"] == "PASS"
    assert verification["mismatches"] == 0
    assert verification["false_success"] == 0
    assert verification["checks"] == verification["passed"]
    notes = " ".join(verification["notes"])
    assert "isolated" in notes, "the isolated reproduction did not run"
