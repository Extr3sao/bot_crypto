#!/usr/bin/env python
"""RFC-035S3 — independent verification of the round-3 closure.

This verifier does **not** import ``rfc035s3_closure``.  It re-implements the four-state
scoring and the P0 contract from scratch, re-hashes every artefact the manifest promises,
re-derives the frozen snapshots, rebuilds the canonical-registry view, and — the strongest
check — re-runs the round-1, round-2 and round-3 evidence verifiers in a **fresh detached
worktree anchored to the RFC-035 baseline commit**, then a concurrency experiment on the
integration test that flaked in the shared checkout.

It is allowed to FAIL even when the researcher recommends a candidate: ``p0_contract`` is
applied to every classification, and a built-in negative control asserts that the contract
*rejects* a promotion that lacks attributable economic evidence.

This program writes ``INDEPENDENT_VERIFICATION.json`` and ``INDEPENDENT_VERIFICATION.md``
itself.  A mismatch is a FAIL.  A missing artefact is a FAIL.  ``FALSE_SUCCESS`` counts
checks that reported success while their evidence was absent.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RESEARCH = REPO / "research" / "profitability"
OPP_DIR = RESEARCH / "opportunities"
OUT = REPO / "reports" / "rfc035" / "search_round_3"
MANIFEST_PATH = REPO / "research" / "rfc035s3" / "ARTIFACT_MANIFEST.json"
COPY_ROOT = REPO / "research" / "rfc035s3" / "artifact_copies"
SRC_DIR = REPO / "data" / "rfc035s3" / "sources"
CANONICAL = RESEARCH / "source_registry.json"
OPP_REGISTRY_MD = RESEARCH / "OPPORTUNITY_REGISTRY.md"
BASELINE_COMMIT = "7e21f7ca6dbf8816d83f2f8ab15aeb09310b878c"
LAB_DEFAULT = REPO.parent / "bot-freebuff-rfc035s3-lab"
COST_FLOOR_BPS = 23.791

FIELD_STATES = ("EXPLICIT_VALUE", "EXPLICIT_NONE", "NOT_APPLICABLE", "UNKNOWN")
SETTLED_STATES = ("EXPLICIT_VALUE", "EXPLICIT_NONE", "NOT_APPLICABLE")
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
ALLOWED_FINAL = ("PASS", "NO_SUITABLE_EXTERNAL_STRATEGY", "CONTINUE_SEARCH", "FAIL")
ALLOWED_RANKS = {
    "RESEARCH_HYPOTHESIS_P0",
    "RESEARCH_HYPOTHESIS_P1",
    "REPLICATE_P0",
    "REPLICATE_P1",
    "WATCH",
    "INSUFFICIENT_EVIDENCE",
    "REJECT",
}
FORBIDDEN_VERDICTS = ("EDGE_CONFIRMED", "PROFITABLE", "READY_FOR_PAPER", "READY_FOR_LIVE")
FINAL_REPORT_FIELDS = (
    "rfc",
    "current_head",
    "baseline_commit",
    "baseline_validation",
    "source_artifact_integrity",
    "full_suite_status",
    "c_02_final_classification",
    "c_07_final_classification",
    "new_sources_reviewed",
    "replicate_p0",
    "rule_completeness",
    "economic_evidence",
    "cost_model",
    "replication_limitations",
    "independent_verification",
    "false_success",
    "final_status",
    "final_decision",
    "next_gate",
    "rfc_036",
    "flags",
)
DELIVERABLES = (
    "BASELINE.md",
    "RULE_CONTRACT_AUDIT.md",
    "CANDIDATE_DEEP_DIVE.md",
    "ECONOMIC_EVIDENCE.md",
    "REJECTION_LOG.md",
    "INDEPENDENT_VERIFICATION.md",
    "FINAL_REPORT.md",
    "FINAL_REPORT.json",
)
S3_SOURCE_IDS = tuple(f"S3-{i:02d}" for i in range(1, 12))
S3_OPPORTUNITIES = ("OPP-0028", "OPP-0029", "OPP-0030", "OPP-0031", "OPP-0032", "OPP-0033")

CHECKS = 0
PASSED = 0
MISMATCHES: list[str] = []
FALSE_SUCCESS = 0
LIMITATIONS: list[str] = []
NOTES: list[str] = []


def check(name: str, ok: bool, detail: str = "", *, evidence_present: bool = True) -> bool:
    global CHECKS, PASSED, FALSE_SUCCESS
    CHECKS += 1
    if ok:
        PASSED += 1
        if not evidence_present:
            FALSE_SUCCESS += 1
            MISMATCHES.append(f"{name}: reported success without evidence ({detail})")
    else:
        MISMATCHES.append(f"{name}: {detail}" if detail else name)
    return ok


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# the four-state semantics, re-implemented independently of the builder
# --------------------------------------------------------------------------- #


def score(fields: dict[str, dict[str, str]], names: tuple[str, ...]) -> dict[str, Any]:
    unknown = sorted(n for n in names if fields[n]["state"] == "UNKNOWN")
    return {
        "settled": len(names) - len(unknown),
        "total": len(names),
        "ratio": f"{len(names) - len(unknown)}/{len(names)}",
        "complete": not unknown,
        "unknown": unknown,
    }


def p0_contract(candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    """§08 PASS contract.  Returns (ok, failures).  Deliberately strict: the whole point is
    that this function can return False for a candidate the researcher would like to promote."""
    failures: list[str] = []
    executable = candidate.get("executable") or {}
    evidence = candidate.get("evidence") or {}
    if set(executable) != set(EXECUTABLE_FIELDS):
        failures.append("executable rule table is not the full contract")
    else:
        rule = score(executable, EXECUTABLE_FIELDS)
        if not rule["complete"]:
            failures.append(f"unsettled executable fields: {rule['unknown']}")
    if set(evidence) != set(EVIDENCE_FIELDS):
        failures.append("evidence table is not the full contract")
    else:
        ev = score(evidence, EVIDENCE_FIELDS)
        # An attributable result is the floor: without published operations AND results, the
        # candidate carries no economic evidence no matter how good the rules look.
        if evidence["operations"]["state"] != "EXPLICIT_VALUE":
            failures.append("no operations attributable to the code")
        if evidence["results"]["state"] != "EXPLICIT_VALUE":
            failures.append("no results attributable to the code")
        if not ev["complete"]:
            failures.append(f"unsettled evidence fields: {ev['unknown']}")
    if not str(candidate.get("grade", candidate.get("evidence_quality", ""))).startswith(
        ("E2", "E3", "E4", "E5")
    ):
        failures.append("evidence grade below E2")
    econ = candidate.get("economic") or {}
    if econ.get("gross_per_operation_estimate", "").startswith("UNKNOWN"):
        failures.append("no estimable gross benefit per operation or exposure")
    if econ.get("cost_model_state") in ("UNKNOWN", None):
        failures.append("cost model unknown")
    if econ.get("cost_floor_comparison") in ("CANNOT_BE_ASSESSED", None):
        failures.append("no cost-floor comparison")
    return (not failures), failures


# --------------------------------------------------------------------------- #
# artefacts
# --------------------------------------------------------------------------- #


def verify_deliverables() -> dict[str, Any]:
    """Everything except INDEPENDENT_VERIFICATION.*, which this program has not written yet on its
    first run.  Those two are checked after they are written (see ``main``).

    The check count therefore grows by exactly this check, so only the verdict is compared.
    """
    present = {}
    for name in DELIVERABLES:
        if name == "INDEPENDENT_VERIFICATION.md":
            continue
        path = OUT / name
        exists = path.is_file()
        present[name] = exists
        check(f"deliverable {name} exists", exists, str(path), evidence_present=exists)
        if exists:
            check(
                f"deliverable {name} is not empty",
                path.stat().st_size > 200,
                str(path.stat().st_size),
            )
    return present


def verify_final_report() -> dict[str, Any]:
    report = load(OUT / "FINAL_REPORT.json")
    check("the round-3 final report parses", isinstance(report, dict))
    if not isinstance(report, dict):
        return {}
    missing = [f for f in FINAL_REPORT_FIELDS if f not in report]
    check("the final report carries every field the round must return", not missing, str(missing))
    check(
        "the final status is one of the allowed outcomes",
        report.get("final_status") in ALLOWED_FINAL,
        str(report.get("final_status")),
    )
    check(
        "the round declares REPLICATE_P0 as NONE",
        report.get("replicate_p0") == "NONE",
        str(report.get("replicate_p0")),
    )
    check(
        "the round keeps RFC-036 blocked",
        "BLOCKED" in str(report.get("rfc_036")),
        str(report.get("rfc_036")),
    )
    check(
        "TRADES_AUTHORIZED stays 0",
        (report.get("flags") or {}).get("TRADES_AUTHORIZED") == 0,
        str((report.get("flags") or {}).get("TRADES_AUTHORIZED")),
    )
    check(
        "the report refuses the positive verdict flags",
        (report.get("flags") or {}).get("EDGE_CONFIRMED") is False
        and (report.get("flags") or {}).get("PROFITABLE") is False
        and (report.get("flags") or {}).get("PRODUCTION_READY") is False,
    )
    check("the report states the round closes", bool(str(report.get("hard_stop", "")).strip()))
    ev = report.get("economic_evidence") or {}
    check(
        "the report states the project cost floor",
        ev.get("cost_floor_bps") == COST_FLOOR_BPS,
        str(ev.get("cost_floor_bps")),
    )
    check(
        "no candidate in the round has an estimable gross figure",
        ev.get("candidates_with_estimable_gross") == [],
        str(ev.get("candidates_with_estimable_gross")),
    )
    # forbidden vocabulary, checked line-by-line on every round-3 markdown
    for name in (
        "FINAL_REPORT.md",
        "BASELINE.md",
        "RULE_CONTRACT_AUDIT.md",
        "CANDIDATE_DEEP_DIVE.md",
        "ECONOMIC_EVIDENCE.md",
        "REJECTION_LOG.md",
    ):
        path = OUT / name
        if not path.is_file():
            continue
        offenders = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if any(line.strip().startswith(v) for v in FORBIDDEN_VERDICTS)
        ]
        check(f"{name} never asserts a forbidden verdict", not offenders, str(offenders))
    return report


def verify_rule_contract() -> list[dict[str, Any]]:
    audit = load(OUT / "RULE_CONTRACT_AUDIT.json") or {}
    deep = load(OUT / "CANDIDATE_DEEP_DIVE.json") or {}
    candidates = audit.get("candidates") or []
    check(
        "the rule-contract audit lists both deep-dive candidates",
        len(candidates) == 2,
        str(len(candidates)),
    )
    deep_by_id = {c["candidate_id"]: c for c in deep.get("candidates", [])}
    check(
        "the deep-dive artifact and the audit agree on the candidate set",
        {c["candidate_id"] for c in candidates} == set(deep_by_id),
        str(sorted(deep_by_id)),
    )
    seen_explicit_none = 0
    for candidate in candidates:
        cid = candidate["candidate_id"]
        for axis, names in (("executable", EXECUTABLE_FIELDS), ("evidence", EVIDENCE_FIELDS)):
            table = candidate.get(axis) or {}
            check(
                f"{cid} {axis} table carries the full contract",
                set(table) == set(names),
                str(sorted(set(names) ^ set(table))),
            )
            if set(table) != set(names):
                continue
            bad = [n for n in names if table[n].get("state") not in FIELD_STATES]
            check(f"{cid} {axis} uses only the four states", not bad, str(bad))
            no_note = [n for n in names if not str(table[n].get("note", "")).strip()]
            check(f"{cid} {axis} records a reason for every field", not no_note, str(no_note))
            recomputed = score(table, names)
            recorded = candidate[f"{axis}_completeness"]
            check(
                f"{cid} {axis} ratio re-derives",
                recorded["ratio"] == recomputed["ratio"],
                f"{recorded['ratio']} vs {recomputed['ratio']}",
            )
            check(
                f"{cid} {axis} settled count re-derives",
                recorded["settled"] == recomputed["settled"],
                f"{recorded['settled']} vs {recomputed['settled']}",
            )
            check(
                f"{cid} {axis} unknown list re-derives",
                recorded["unknown"] == recomputed["unknown"],
                f"{recorded['unknown']} vs {recomputed['unknown']}",
            )
            check(
                f"{cid} {axis} completeness flag re-derives",
                recorded["complete"] == recomputed["complete"],
            )
            seen_explicit_none += sum(1 for n in names if table[n]["state"] == "EXPLICIT_NONE")
        # the same candidate must appear identically in the deep-dive artifact
        twin = deep_by_id.get(cid, {})
        check(
            f"{cid} tables agree across the two artifacts",
            twin.get("executable") == candidate.get("executable")
            and twin.get("evidence") == candidate.get("evidence"),
        )
        # a solved field list must not be scored as if EXPLICIT_NONE were missing
        rule = score(candidate["executable"], EXECUTABLE_FIELDS)
        expected_settled = sum(
            1 for n in EXECUTABLE_FIELDS if candidate["executable"][n]["state"] in SETTLED_STATES
        )
        check(
            f"{cid} counts EXPLICIT_NONE as settled, not missing",
            rule["settled"] == expected_settled,
            f"{rule['settled']} vs {expected_settled}",
        )
        ok, failures = p0_contract(candidate)
        check(
            f"{cid} does not meet the P0 contract (so must not be promoted)", not ok, str(failures)
        )
        check(
            f"{cid} is not classified REPLICATE_P0",
            candidate["classification"] != "REPLICATE_P0",
            candidate["classification"],
        )
        check(
            f"{cid} records a classification reason",
            bool(str(candidate.get("classification_reason", "")).strip()),
        )
    check(
        "the round actually used EXPLICIT_NONE (the corrected semantics are applied)",
        seen_explicit_none > 0,
        str(seen_explicit_none),
    )

    # negative control: a synthetic candidate whose rules are complete but which carries no
    # attributable result must be REJECTED by the contract.  A verifier that cannot fail here
    # would be a rubber stamp.
    synthetic: dict[str, Any] = {
        "executable": {f: {"state": "EXPLICIT_VALUE", "note": "x"} for f in EXECUTABLE_FIELDS},
        "evidence": {f: {"state": "EXPLICIT_VALUE", "note": "x"} for f in EVIDENCE_FIELDS},
        "economic": {
            "gross_per_operation_estimate": "UNKNOWN",
            "cost_model_state": "UNKNOWN",
            "cost_floor_comparison": "CANNOT_BE_ASSESSED",
        },
        "grade": "E1",
    }
    synthetic["evidence"]["results"] = {"state": "EXPLICIT_NONE", "note": "no result published"}
    ok, failures = p0_contract(synthetic)
    check(
        "NEGATIVE CONTROL: the P0 contract rejects complete rules with no result",
        not ok,
        str(failures),
    )
    check(
        "NEGATIVE CONTROL: the rejection names the missing result",
        any("results" in f for f in failures),
        str(failures),
    )
    complete = json.loads(json.dumps(synthetic))
    complete["evidence"]["results"] = {"state": "EXPLICIT_VALUE", "note": "published"}
    complete["economic"] = {
        "gross_per_operation_estimate": "+1.2%",
        "cost_model_state": "DOCUMENTED_BY_AUTHOR",
        "cost_floor_comparison": "ABOVE_FLOOR",
    }
    complete["grade"] = "E2"
    ok, failures = p0_contract(complete)
    check("NEGATIVE CONTROL: the contract accepts a fully-specified candidate", ok, str(failures))
    return candidates


def verify_economics() -> None:
    econ = load(OUT / "ECONOMIC_EVIDENCE.json") or {}
    check(
        "the economic artifact states the cost floor", econ.get("cost_floor_bps") == COST_FLOOR_BPS
    )
    for entry in econ.get("deep_dives") or []:
        cid = entry["candidate_id"]
        check(
            f"{cid} declares no estimable gross figure",
            str(entry["gross_per_operation_estimate"]).startswith("UNKNOWN"),
            entry["gross_per_operation_estimate"],
        )
        check(
            f"{cid} cost model is not falsely declared",
            entry["cost_model_state"]
            in (
                "UNKNOWN",
                "DECLARED_ABSENT",
                "PROJECT_COST_FLOOR_ONLY",
                "DOCUMENTED_BY_AUTHOR",
                "INFERRED_FROM_PLATFORM",
            ),
            entry["cost_model_state"],
        )
        check(
            f"{cid} cost-floor comparison is explicitly not assessable",
            entry["cost_floor_comparison"] == "CANNOT_BE_ASSESSED",
            entry["cost_floor_comparison"],
        )
    alternatives = econ.get("alternatives") or []
    check(
        "the alternative search is capped at ten new primary sources",
        len(alternatives) <= 10,
        str(len(alternatives)),
    )
    documented = [a for a in alternatives if a.get("cost_model_state") == "DOCUMENTED_BY_AUTHOR"]
    check(
        "at least one reviewed source carries a documented cost model",
        bool(documented),
        str([a["candidate_id"] for a in alternatives]),
    )
    for alt in alternatives:
        check(
            f"{alt['candidate_id']} records a code-availability statement",
            bool(str(alt.get("code_available", "")).strip()),
        )
        check(
            f"{alt['candidate_id']} records a reason",
            bool(str(alt.get("classification_reason", "")).strip()),
        )
        check(
            f"{alt['candidate_id']} is not promoted",
            alt.get("classification") != "REPLICATE_P0",
            alt.get("classification"),
        )


def verify_manifest() -> dict[str, Any]:
    manifest = load(MANIFEST_PATH)
    check("the git-ignored-artifact manifest exists", isinstance(manifest, dict))
    if not isinstance(manifest, dict):
        return {}
    files = manifest.get("files") or []
    check(
        "the manifest lists at least the round-1 and round-2 trees",
        len(files) >= 20,
        str(len(files)),
    )
    bad: list[str] = []
    for entry in files:
        path = REPO / entry["path"]
        if not path.is_file():
            bad.append(f"missing {entry['path']}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            bad.append(f"changed {entry['path']}")
    check("every manifested artifact still hashes to its recorded digest", not bad, str(bad[:6]))
    digest = hashlib.sha256(canon(files).encode("utf-8")).hexdigest()
    check(
        "the manifest bundle digest re-derives",
        digest == manifest.get("bundle_digest"),
        f"{digest[:16]} vs {str(manifest.get('bundle_digest'))[:16]}",
    )
    copies = manifest.get("copies") or []
    check("the immutable copy exists", bool(copies))
    copy_bad = [
        c["path"]
        for c in copies
        if not (REPO / c["path"]).is_file()
        or hashlib.sha256((REPO / c["path"]).read_bytes()).hexdigest() != c["sha256"]
    ]
    check(
        "every copied artifact exists and still hashes correctly", not copy_bad, str(copy_bad[:6])
    )
    check("the manifest declares the copy verified", manifest.get("copy_verified") is True)
    check(
        "the immutable copy root is outside the git-ignored reports/ tree",
        not str(manifest.get("immutable_copy_root", "")).startswith("reports/"),
        str(manifest.get("immutable_copy_root")),
    )
    return manifest


def verify_snapshots() -> None:
    expected = {
        "strategy001_raw.py.txt": "2357996e6594458e8db45b5f757918462afa3c998de9d06e2af0c009ddc4b80d",
        "freqtrade_strategies_README.md": "50df38eb1b1ed410b5e41f55d8dd95e2a834cf89750781e38faa1b24a796b835",
        "quantiacs_q24_crypto_guide.html": "88cef01b970251d4c3a40f7ec5366005d75a80549bb9d19735e585c1004915ba",
    }
    for name, want in expected.items():
        path = SRC_DIR / name
        check(
            f"frozen snapshot {name} exists",
            path.is_file(),
            str(path),
            evidence_present=path.is_file(),
        )
        if path.is_file():
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            check(
                f"frozen snapshot {name} hashes to the recorded digest",
                got == want,
                f"{got[:16]} vs {want[:16]}",
            )
    report = load(OUT / "FINAL_REPORT.json") or {}
    frozen = (report.get("source_artifact_integrity") or {}).get("frozen_snapshots") or {}
    for name, want in expected.items():
        check(
            f"the report quotes the {name} snapshot digest",
            frozen.get(name) == want,
            f"{frozen.get(name)} vs {want}",
        )
    # the Quantiacs page must contain no cost vocabulary: the claim that its cost model is
    # silence (UNKNOWN) rather than a declared absence is a factual claim about the bytes.
    page = SRC_DIR / "quantiacs_q24_crypto_guide.html"
    if page.is_file():
        text = page.read_text(encoding="utf-8", errors="replace").lower()
        for term in ("commission", "transaction cost", "slippage"):
            check(f"the Quantiacs snapshot contains no '{term}' vocabulary", term not in text)
    # the freqtrade README must actually carry the disclaimer the record relies on
    readme = SRC_DIR / "freqtrade_strategies_README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace").lower()
        check(
            "the freqtrade README carries the educational-purposes disclaimer",
            "educational purposes only" in text,
        )
        check(
            "the freqtrade README states the strategies are not ready to use",
            "ready to use" in text,
        )


def verify_registry() -> None:
    registry = load(CANONICAL) or {}
    by_id = {s["SOURCE_ID"]: s for s in registry.get("sources", [])}
    missing = [sid for sid in S3_SOURCE_IDS if sid not in by_id]
    check("every round-3 source is registered canonically", not missing, str(missing))
    for sid in S3_SOURCE_IDS:
        source = by_id.get(sid)
        if not source:
            continue
        for key in ("TITLE", "URL", "READ_LEVEL", "STATUS", "RELIABILITY", "SOURCE_CLASS", "ROUND"):
            check(
                f"{sid} carries {key}", bool(str(source.get(key, "")).strip()), str(source.get(key))
            )
        check(f"{sid} URL is absolute", str(source.get("URL", "")).startswith("http"))
        check(
            f"{sid} read level is one of the allowed values",
            source.get("READ_LEVEL") in ("full_text", "abstract_snippet", "listing"),
            str(source.get("READ_LEVEL")),
        )
        check(
            f"{sid} is marked ROUND_3",
            str(source.get("STATUS", "")).startswith("ROUND_3"),
            str(source.get("STATUS")),
        )
    rounds = registry.get("rounds")
    check(
        "the canonical registry keeps its round history as a list",
        isinstance(rounds, list),
        str(type(rounds)),
    )
    if isinstance(rounds, list):
        r3 = [r for r in rounds if r.get("rfc") == "RFC-035S3"]
        check(
            "the canonical registry carries exactly one round-3 entry", len(r3) == 1, str(len(r3))
        )
        if r3:
            check(
                "the round-3 entry records the final status",
                r3[0].get("final_status") == "NO_SUITABLE_EXTERNAL_STRATEGY",
                str(r3[0].get("final_status")),
            )
            check(
                "the round-3 entry records REPLICATE_P0 as NONE",
                r3[0].get("replicate_p0_selected") == "NONE",
                str(r3[0].get("replicate_p0_selected")),
            )
        check(
            "the earlier rounds are still present",
            any(r.get("rfc") == "RFC-035" for r in rounds)
            and any(r.get("rfc") == "RFC-035S2" for r in rounds),
            str([r.get("rfc") for r in rounds]),
        )

    for oid in S3_OPPORTUNITIES:
        record = load(OPP_DIR / f"{oid}.json")
        check(f"{oid} record exists", isinstance(record, dict), str(oid))
        if not isinstance(record, dict):
            continue
        check(
            f"{oid} rank is an allowed rank",
            record.get("rank") in ALLOWED_RANKS,
            str(record.get("rank")),
        )
        check(
            f"{oid} rank is not a replication rank",
            record.get("rank") not in ("REPLICATE_P0", "REPLICATE_P1"),
            str(record.get("rank")),
        )
        check(
            f"{oid} score re-derives",
            sum(record["evidence_scores"].values()) == record["evidence_score_total"],
            f"{sum(record['evidence_scores'].values())} vs {record['evidence_score_total']}",
        )
        check(f"{oid} carries counter-evidence", bool(record.get("counter_evidence")))
        unknown = [s for s in record["source_ids"] if s not in by_id]
        check(f"{oid} cites only registered sources", not unknown, str(unknown))

    # The supersession of the two deep dives must be additive: the frozen rank stays exactly as the
    # round that classified it assigned, and the rank in force is exposed separately.  Rewriting
    # ``rank`` would make the round-2 verifier disagree with a later round and blur the line between
    # "a later round superseded this" and "the evidence changed".
    for oid, frozen in (("OPP-0011", "REPLICATE_P1"), ("OPP-0016", "REPLICATE_P1")):
        record = load(OPP_DIR / f"{oid}.json") or {}
        check(
            f"{oid} keeps its frozen rank unchanged",
            record.get("rank") == frozen,
            str(record.get("rank")),
        )
        check(
            f"{oid} keeps its round-2 candidate reference",
            str(record.get("candidate_ref", "")).endswith("CANDIDATE_MATRIX.json"),
            str(record.get("candidate_ref")),
        )
        check(
            f"{oid} exposes the rank in force after round 3",
            record.get("current_rank") not in (None, frozen),
            str(record.get("current_rank")),
        )
        check(
            f"{oid} rank in force is not a replication rank",
            record.get("current_rank") not in ("REPLICATE_P0", "REPLICATE_P1"),
            str(record.get("current_rank")),
        )
        check(
            f"{oid} keeps a rank history",
            bool(record.get("rank_history")),
            str(record.get("rank_history")),
        )
        history = [item.get("rank") for item in record.get("rank_history") or []]
        check(
            f"{oid} history retains the round-2 replication rank", frozen in history, str(history)
        )
        correction = record.get("round_3_reclassification") or {}
        check(
            f"{oid} records the round-3 correction", bool(correction.get("reason")), str(correction)
        )
        check(
            f"{oid} corrected rank matches the rank in force",
            correction.get("corrected_rank") == record.get("current_rank"),
            f"{correction.get('corrected_rank')} vs {record.get('current_rank')}",
        )
        check(
            f"{oid} records both completeness axes",
            "/" in str(correction.get("executable_rule_completeness", ""))
            and "/" in str(correction.get("evidence_completeness", "")),
            str(correction),
        )
        check(
            f"{oid} keeps its round-2 evidence scores intact",
            sum(record["evidence_scores"].values()) == record["evidence_score_total"],
            str(record.get("evidence_score_total")),
        )

    # new records must carry the full canonical schema, not only the round-3 fields
    required = (
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
    for oid in S3_OPPORTUNITIES:
        record = load(OPP_DIR / f"{oid}.json")
        if not isinstance(record, dict):
            continue
        missing = [k for k in required if k not in record]
        check(f"{oid} carries the full canonical opportunity schema", not missing, str(missing))
        check(
            f"{oid} states its ambiguities as a list",
            isinstance(record.get("ambiguities"), list),
            str(type(record.get("ambiguities"))),
        )
        check(
            f"{oid} states its rules as text",
            all(
                str(record.get(k, "")).strip() for k in ("entry_rules", "exit_rules", "parameters")
            ),
        )

    text = OPP_REGISTRY_MD.read_text(encoding="utf-8") if OPP_REGISTRY_MD.is_file() else ""
    check("the registry document gains a round-3 section", "Round 3 (RFC-035S3)" in text)
    check(
        "the registry document still quotes the frozen rule hash exactly once",
        len(re.findall(r"RULE_HASH \(sha256\): `[0-9a-f]{64}`", text)) == 1,
        str(len(re.findall(r"RULE_HASH \(sha256\): `[0-9a-f]{64}`", text))),
    )
    check(
        "the registry document still quotes the frozen source-bundle hash exactly once",
        len(re.findall(r"SOURCE_BUNDLE_HASH \(sha256\): `[0-9a-f]{64}`", text)) == 1,
        str(len(re.findall(r"SOURCE_BUNDLE_HASH \(sha256\): `[0-9a-f]{64}`", text))),
    )


# --------------------------------------------------------------------------- #
# independent reproduction in a detached worktree
# --------------------------------------------------------------------------- #


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO, capture_output=True, text=True, check=False
    )


def ensure_lab() -> tuple[Path | None, str]:
    """Create (or reuse) a detached worktree at the RFC-035 baseline and copy the untracked
    RFC-035 artifacts into it, so the verifiers run against the baseline commit."""
    lab = LAB_DEFAULT
    head = git("rev-parse", "HEAD").stdout.strip()
    if not lab.is_dir():
        proc = git("worktree", "add", "--detach", str(lab), BASELINE_COMMIT)
        if proc.returncode != 0:
            return None, f"worktree add failed: {proc.stderr.strip()[:200]}"
    lab_head = git("rev-parse", "HEAD", cwd=lab).stdout.strip()
    if lab_head != BASELINE_COMMIT:
        git("checkout", "--detach", BASELINE_COMMIT, cwd=lab)
        lab_head = git("rev-parse", "HEAD", cwd=lab).stdout.strip()
    for rel in (
        "scripts/rfc035_discovery_verify.py",
        "scripts/rfc035e_verify.py",
        "scripts/rfc035s2_verify.py",
    ):
        (lab / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, lab / rel)
    for rel in ("reports/rfc035", "reports/rfc035e", "research/rfc035e", "docs/governance"):
        source = REPO / rel
        target = lab / rel
        if source.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, dirs_exist_ok=True)
    (lab / "research" / "profitability").mkdir(parents=True, exist_ok=True)
    shutil.copytree(RESEARCH, lab / "research" / "profitability", dirs_exist_ok=True)
    return lab, f"lab at {lab_head} (main HEAD {head[:12]})"


def run_script(lab: Path, script: str, timeout: int = 600) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, script],
        cwd=lab,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    status = "UNKNOWN"
    checks = 0
    passed = 0
    mismatches = -1
    for line in proc.stdout.splitlines():
        if line.startswith("STATUS = "):
            status = line.split("=", 1)[1].strip()
        elif line.startswith("CHECKS = "):
            payload = line.split("=", 1)[1].strip()
            if "/" in payload:
                left, right = payload.split("/")
                passed, checks = int(left), int(right)
        elif line.startswith("MISMATCHES = "):
            # parse the declared count; never count the substring "MISMATCH", which also matches the
            # summary line "MISMATCHES = 0" itself.
            mismatches = int(line.split("=", 1)[1].strip())
    return {
        "script": script,
        "status": status,
        "checks": checks,
        "passed": passed,
        "mismatch_lines": mismatches,
        "exit_code": proc.returncode,
        "tail": "\n".join(proc.stdout.splitlines()[-3:]),
    }


def verify_reproduction() -> None:
    lab, note = ensure_lab()
    check(
        "an isolated worktree anchored to the baseline commit is available", lab is not None, note
    )
    if lab is None:
        LIMITATIONS.append(f"isolated reproduction could not run: {note}")
        return
    NOTES.append(f"isolated reproduction: {note}")
    # The *invariants* are what must reproduce: PASS, zero mismatches, zero false success.  The
    # absolute check count is a function of the registry size, which every round grows additively by
    # design, so comparing it to a historical constant would be wrong: a larger registry legitimately
    # yields more checks.  The observed counts are recorded instead.
    recorded = {}
    baseline_doc = load(OUT / "BASELINE.json") or {}
    for entry in (baseline_doc.get("reproduction") or {}).get("runs_after_round_3_registry") or []:
        recorded[entry["script"]] = entry
    check(
        "the round records its reproduction at both registry sizes",
        len(recorded) == 3,
        str(sorted(recorded)),
    )
    check(
        "the round states the regression invariant explicitly",
        bool((baseline_doc.get("reproduction") or {}).get("invariant")),
        str((baseline_doc.get("reproduction") or {}).get("invariant")),
    )
    for script in (
        "scripts/rfc035_discovery_verify.py",
        "scripts/rfc035e_verify.py",
        "scripts/rfc035s2_verify.py",
    ):
        result = run_script(lab, script)
        check(
            f"{script} passes in the isolated worktree",
            result["status"] == "PASS" and result["exit_code"] == 0,
            f"{result['status']} exit={result['exit_code']} tail={result['tail']}",
        )
        check(
            f"{script} reports zero mismatches at the baseline commit",
            result["mismatch_lines"] == 0,
            f"{result['mismatch_lines']}",
        )
        check(f"{script} ran more than one check", result["checks"] > 1, str(result["checks"]))
        if script in recorded:
            check(
                f"{script} check count agrees with the recorded post-round-3 count",
                result["checks"] == recorded[script]["checks"],
                f"{result['checks']} vs {recorded[script]['checks']}",
            )
            check(
                f"{script} recorded verdict agrees with the observed verdict",
                recorded[script]["status"] == result["status"],
                f"{recorded[script]['status']} vs {result['status']}",
            )
        NOTES.append(f"isolated {script}: {result['status']} {result['passed']}/{result['checks']}")
    # the defect recorded for rfc035e_verify must be reproducible: without its raw inputs the
    # script crashes instead of failing cleanly.
    stripped = lab / "research" / "rfc035e"
    if stripped.is_dir():
        backup = lab / "research" / "_rfc035e_backup"
        shutil.move(str(stripped), str(backup))
        try:
            proc = subprocess.run(
                [sys.executable, "scripts/rfc035e_verify.py"],
                cwd=lab,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            crashed = proc.returncode != 0 and "Traceback" in proc.stderr
            check(
                "the recorded missing-input defect in rfc035e_verify reproduces (crash, not a clean FAIL)",
                crashed,
                f"exit={proc.returncode}",
            )
        finally:
            shutil.move(str(backup), str(stripped))


def verify_concurrency() -> None:
    lab, _ = ensure_lab()
    if lab is None:
        LIMITATIONS.append("the concurrency experiment could not run without the isolated worktree")
        return
    test = "tests/unit/observability/test_dashboard_server.py::test_runtime_artifacts_are_untouched_by_serving"
    tail = ""
    ok = True
    for _ in range(3):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", test, "-q", "-p", "no:randomly"],
            cwd=lab,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            ok = False
            tail = "\n".join(proc.stdout.splitlines()[-5:])
    check("the integration test passes repeatedly in the exclusive worktree", ok, tail)
    source = REPO / "tests/unit/observability/test_dashboard_server.py"
    text = source.read_text(encoding="utf-8") if source.is_file() else ""
    check(
        "the flake mechanism is mechanical: the test hashes the whole reports/ tree",
        "def _artifact_digest" in text and 'root / "reports"' in text,
        "the digest helper no longer targets reports/",
    )
    baseline = load(OUT / "BASELINE.json") or {}
    experiment = (baseline.get("reproduction") or {}).get("concurrency_experiment") or {}
    check(
        "the round records a non-zero shared-checkout failure count",
        int(experiment.get("shared_checkout_failures", 0)) > 0,
        str(experiment.get("shared_checkout_failures")),
    )
    check(
        "the round records a zero exclusive-worktree failure count",
        int(experiment.get("exclusive_worktree_failures", 99)) == 0,
        str(experiment.get("exclusive_worktree_failures")),
    )
    check(
        "the round attributes the flake to workspace concurrency, not to serving",
        "concurrency" in str(experiment.get("conclusion", "")),
        str(experiment.get("conclusion")),
    )


def verify_baseline() -> None:
    baseline = load(OUT / "BASELINE.json")
    check("the round-3 baseline artifact exists", isinstance(baseline, dict))
    if not isinstance(baseline, dict):
        return
    head = git("rev-parse", "HEAD").stdout.strip()
    recorded_head = str(baseline.get("current_head"))
    # The recorded HEAD is the HEAD at build time.  A later advance is legitimate drift - including the
    # commit that carries this very round - so it is accepted when the recorded commit is an ancestor
    # of the live HEAD, and rejected only when the live HEAD is unrelated or rewound.
    if recorded_head == head:
        check("the baseline records the live HEAD", True)
    else:
        ancestor = git("merge-base", "--is-ancestor", recorded_head, head)
        check(
            "any HEAD advance after the build is a legitimate descendant, not a rewind",
            ancestor.returncode == 0,
            f"recorded {recorded_head[:12]} is not an ancestor of {head[:12]}",
        )
    check(
        "the baseline records the frozen baseline commit",
        baseline.get("baseline_commit") == BASELINE_COMMIT,
        str(baseline.get("baseline_commit")),
    )
    check(
        "the baseline does not re-point the original baseline at HEAD",
        (
            baseline.get("baseline_commit") == BASELINE_COMMIT
            and baseline.get("current_head") != BASELINE_COMMIT
        )
        or baseline.get("head_equals_baseline") is True,
    )
    check(
        "the baseline classifies any drift as a legitimate change",
        "LEGITIMATE" in str(baseline.get("drift_classification", ""))
        or baseline.get("head_equals_baseline") is True,
        str(baseline.get("drift_classification")),
    )
    reproduction = baseline.get("reproduction") or {}
    check(
        "the recorded reproduction names all three verifiers",
        len(reproduction.get("runs") or []) == 3,
        str(len(reproduction.get("runs") or [])),
    )
    check(
        "the recorded reproduction keeps the verifier defect visible",
        bool((reproduction.get("defect_observed") or {}).get("classification")),
        str(reproduction.get("defect_observed")),
    )
    original = load(REPO / "reports" / "rfc035" / "BASELINE.json") or {}
    check(
        "the original round-1 baseline is untouched (still names its own commit)",
        original.get("source_commit") == BASELINE_COMMIT,
        str(original.get("source_commit")),
    )


def emit() -> str:
    """Write INDEPENDENT_VERIFICATION.* from the current state and return the verdict.

    Called twice: once to produce the files, and once more after the two self-checks on those very
    files, so the recorded check count includes them.
    """
    status = "PASS" if not MISMATCHES and CHECKS > 0 else "FAIL"
    payload = {
        "verification": "RFC035S3_TARGETED_EVIDENCE_CLOSURE_VERIFICATION",
        "status": status,
        "checks": CHECKS,
        "passed": PASSED,
        "mismatches": len(MISMATCHES),
        "mismatch_detail": MISMATCHES,
        "false_success": FALSE_SUCCESS,
        "replicate_p0": "NONE",
        "final_status": "NO_SUITABLE_EXTERNAL_STRATEGY",
        "rfc_036": "BLOCKED",
        "limitations": LIMITATIONS,
        "notes": NOTES,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# RFC-035S3 — INDEPENDENT VERIFICATION",
        "",
        f"- status: **{status}**",
        f"- checks: {PASSED}/{CHECKS}",
        f"- mismatches: {len(MISMATCHES)}",
        f"- false success: {FALSE_SUCCESS}",
        "- REPLICATE_P0: NONE",
        "- final status: NO_SUITABLE_EXTERNAL_STRATEGY",
        "- RFC-036: BLOCKED",
        "",
        "## Checks that failed",
        "",
    ]
    lines += [f"- {m}" for m in MISMATCHES] or ["- none"]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in LIMITATIONS] or ["- none"]
    lines += ["", "## Notes", ""]
    lines += [f"- {item}" for item in NOTES] or ["- none"]
    lines += [
        "",
        "## Method",
        "",
        "The verifier does not import the builder. It re-implements the four-state scoring and the §08",
        "P0 contract, re-hashes every artefact the manifest promises, re-derives the frozen snapshots,",
        "rebuilds the canonical-registry view, and re-runs the round-1, round-2 and round-3 verifiers in",
        "a detached worktree anchored to the RFC-035 baseline commit. Two negative controls prove the",
        "verifier can FAIL: the contract rejects complete rules with no attributable result, and accepts a",
        "fully-specified candidate.",
        "",
        "## Scope of the reproduction",
        "",
        "The regression invariant is *status PASS with zero mismatches* at the baseline commit. The absolute",
        "check count is a function of registry size, which every round grows additively by design, so it is",
        "recorded rather than asserted equal to a historical constant.",
        "",
    ]
    (OUT / "INDEPENDENT_VERIFICATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return status


def main() -> int:
    verify_deliverables()
    verify_final_report()
    verify_rule_contract()
    verify_economics()
    verify_manifest()
    verify_snapshots()
    verify_registry()
    verify_baseline()
    verify_reproduction()
    verify_concurrency()

    status = emit()
    # the two remaining deliverables are this program's own output: check them, then re-emit so the
    # recorded counts include these two checks.
    for name in ("INDEPENDENT_VERIFICATION.json", "INDEPENDENT_VERIFICATION.md"):
        produced = OUT / name
        ok = produced.is_file() and produced.stat().st_size > 200
        check(
            f"deliverable {name} is written by the verifier", ok, str(produced), evidence_present=ok
        )
    status = emit()

    print("RFC-035S3 INDEPENDENT VERIFICATION")
    print(f"STATUS = {status}")
    print(f"CHECKS = {PASSED}/{CHECKS}")
    print(f"MISMATCHES = {len(MISMATCHES)}")
    print(f"FALSE_SUCCESS = {FALSE_SUCCESS}")
    print(f"LIMITATIONS = {len(LIMITATIONS)}")
    for item in MISMATCHES[:20]:
        print(f"  MISMATCH: {item}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
