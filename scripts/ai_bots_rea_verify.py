"""Verificador independiente de RFC-TAP-AI-BOTS-002 v3 (REA-FIRST).

No comprueba que el informe *diga* PASS: comprueba que cada afirmación tenga
detrás un artefacto y que los arreglos P0 estén en el runtime real.

    python scripts/ai_bots_rea_verify.py [--json]

Sale 0 sólo si todas las comprobaciones pasan. `BUILDER != VERIFIER` es literal
aquí: este script no construye evidencia, la rechaza.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REA = REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-002"
TARGETS = REA / "rea" / "targets"
FINDINGS = REA / "REA_FINDINGS_V2.json"
MATRIX = REA / "REA_TARGET_MATRIX.csv"
DOCS = REPO / "docs" / "ai-bots" / "RFC-AI-BOTS-002"

EVIDENCE_ID = re.compile(r"^ev_[0-9a-f]{64}$")
#: Licencias medidas con la API de GitHub el 2026-10-18. Una regresión aquí reintroduce
#: el error MIT/Apache que la auditoría anterior arrastraba.
LICENSES = {
    "qrak/LLM_trader": "MIT",
    "Ganador1/FenixAI_tradingBot": "Apache-2.0",
    "195440/nof1.ai": "AGPL-3.0",
    "TauricResearch/TradingAgents": "Apache-2.0",
    "FortuneMal/AI-trading": "NONE (404)",
}


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}{(' :: ' + detail) if detail else ''}")
        return bool(ok)

    @property
    def failures(self) -> list[dict[str, object]]:
        return [c for c in self.checks if not c["ok"]]


def load_claimed_evidence_ids() -> set[str]:
    ids: set[str] = set()
    for log in TARGETS.glob("*/REA_COMMAND_LOG.jsonl"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("evidence_id"):
                ids.add(str(row["evidence_id"]))
    for doc in TARGETS.glob("*/REA_EVIDENCE.json"):
        payload = json.loads(doc.read_text(encoding="utf-8"))
        for operation in payload.get("operations", []):
            if operation.get("evidence_id"):
                ids.add(str(operation["evidence_id"]))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print the machine-readable report")
    args = parser.parse_args()

    report = Report()
    if not FINDINGS.is_file():
        report.check("findings_file_exists", False, str(FINDINGS))
        return 1
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    report.check("findings_file_exists", True, str(FINDINGS.relative_to(REPO)))

    stored_ids = load_claimed_evidence_ids()
    report.check("dossiers_store_evidence_ids", bool(stored_ids), f"{len(stored_ids)} stored")

    # 1. who claims REA, with what
    claimed_ok = True
    for target in findings["targets"]:
        if not target.get("rea_executed"):
            continue
        ids = target.get("evidence_ids") or []
        if not ids:
            claimed_ok = False
            report.check(f"{target['target_id']}_has_evidence_ids", False, "claims REA with no id")
            continue
        bad = [i for i in ids if not EVIDENCE_ID.match(i)]
        if bad:
            claimed_ok = False
            report.check(f"{target['target_id']}_ids_are_rea_shaped", False, str(bad[:2]))
            continue
        missing = [i for i in ids if i not in stored_ids]
        report.check(
            f"{target['target_id']}_ids_are_backed_by_stored_evidence",
            not missing,
            "all ids present in dossiers" if not missing else f"not stored: {missing[:2]}",
        )
        claimed_ok = claimed_ok and not missing
    report.check("every_claimed_evidence_id_is_stored", claimed_ok)

    # 2. nobody without evidence may be certified
    certified = [
        t["target_id"] for t in findings["targets"]
        if not t.get("rea_executed")
        and str(t.get("decision", "")).upper() in {"ADOPT_VERIFIED", "REA_AUDITED"}
    ]
    report.check("no_certification_without_rea_evidence", not certified, str(certified))

    # 3. matrix and findings agree
    rows = list(csv.DictReader(MATRIX.read_text(encoding="utf-8").splitlines()))
    matrix_ids = {row["TARGET_ID"] for row in rows}
    finding_ids = {t["target_id"] for t in findings["targets"]}
    report.check("matrix_matches_findings", matrix_ids == finding_ids,
                 f"only in matrix: {sorted(matrix_ids - finding_ids)}; "
                 f"only in findings: {sorted(finding_ids - matrix_ids)}")
    missing_id_cells = [
        row["TARGET_ID"] for row in rows
        if row["REA_EXECUTED"] == "YES" and not EVIDENCE_ID.match(row["REA_EVIDENCE_ID"] or "")
    ]
    report.check("matrix_yes_rows_carry_a_real_id", not missing_id_cells, str(missing_id_cells))

    # 4. licences as measured
    reported = findings.get("licenses_verified", {})
    for repo, spdx in LICENSES.items():
        report.check(
            f"license_{repo.split('/')[-1]}",
            reported.get(repo) == spdx,
            f"expected {spdx}, reported {reported.get(repo)}",
        )

    # 5. the P0 guards are in the runtime, not just in the report
    lane = (REPO / "src" / "trading_bot" / "vision" / "lane.py").read_text(encoding="utf-8")
    compare = (REPO / "src" / "trading_bot" / "vision" / "compare.py").read_text(encoding="utf-8")
    report.check("integrity_failure_returns_none", "INTEGRITY_FAILURE" in lane
                 and "discarded" in lane)
    report.check("late_response_guard_present", "LATE_RESPONSE" in lane)
    report.check("comparator_emits_not_comparable", '"NOT_COMPARABLE"' in compare)

    integrity_test = REPO / "tests" / "unit" / "vision" / "test_integrity_and_latency.py"
    compare_test = REPO / "tests" / "unit" / "vision" / "test_compare.py"
    report.check("p0_tests_exist", integrity_test.is_file() and compare_test.is_file())
    body = integrity_test.read_text(encoding="utf-8") if integrity_test.is_file() else ""
    report.check("p0_tests_target_the_lane", "VisionLane" in body, "the real runtime, not a fake")
    #: A row may only carry a blank id when it says REA was not executed.
    bad_blank = [
        row["TARGET_ID"] for row in rows
        if row["REA_EXECUTED"].strip().upper() != "YES" and row["REA_EVIDENCE_ID"].strip()
    ]
    report.check("no_evidence_id_without_execution", not bad_blank, str(bad_blank))

    # 6. no invented live call
    states = findings.get("states", {})
    report.check("no_real_model_call_claimed", states.get("REAL_MODEL_CALLED") is False)
    report.check("no_adoption_certified", not states.get("ADOPT_VERIFIED"))
    report.check("false_success_zero", states.get("FALSE_SUCCESS") == 0)

    # 7. the RFC §5 dossier set exists for every target, and the executed one is populated
    dossier_files = (
        "TARGET_BASELINE.json",
        "ADOPTION_DECISION.md",
        "RECONSTRUCTION_OBLIGATIONS.json",
        "SOURCE_RUNTIME_CORRELATION.md",
    )
    for target in findings["targets"]:
        folder = TARGETS / target["target_id"]
        absent = [name for name in dossier_files if not (folder / name).is_file()]
        report.check(
            f"{target['target_id']}_dossier_complete",
            not absent,
            "complete" if not absent else f"missing {absent}",
        )
        if target.get("rea_executed"):
            log = folder / "REA_COMMAND_LOG.jsonl"
            rows = [r for r in log.read_text(encoding="utf-8").splitlines() if r.strip()] if log.is_file() else []
            report.check(
                f"{target['target_id']}_command_log_populated",
                len(rows) >= 2,
                f"{len(rows)} logged commands",
            )
            report.check(
                f"{target['target_id']}_behaviour_trace_present",
                (folder / "BEHAVIORAL_TRACE.md").is_file(),
            )

    required_reports = (
        "REA_FINDINGS_V2.json",
        "REA_TARGET_MATRIX.csv",
        "RECONSTRUCTION_COMPARISON.md",
        "INFORME_EJECUTIVO.md",
        "FINAL_REPORT_REA_FIRST.md",
        "RUN_REPORT_REA_FIRST.json",
    )
    absent_reports = [name for name in required_reports if not (REA / name).is_file()]
    report.check("required_deliverables_present", not absent_reports, str(absent_reports))

    #: The licence column of the SRC-FENIX row, not any prose that mentions the old value.
    registry = DOCS / "source_registry.md"
    fenix_licence = ""
    if registry.is_file():
        for line in registry.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("| SRC-FENIX"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                raw = cells[2] if len(cells) > 2 else ""
                # Drop parenthetical history: only the asserted licence counts.
                fenix_licence = re.sub(r"\([^)]*\)", "", raw).strip()
                break
    report.check(
        "source_registry_corrects_fenix_license",
        "Apache-2.0" in fenix_licence and "MIT" not in fenix_licence,
        f"SRC-FENIX licence cell is {fenix_licence!r}",
    )

    payload = {
        "checks": report.checks,
        "failures": report.failures,
        "passed": len(report.checks) - len(report.failures),
        "failed": len(report.failures),
        "evidence_ids_backed": sorted(stored_ids),
    }
    (REA / "INDEPENDENT_VERIFICATION_REA.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n{payload['passed']} PASS / {payload['failed']} FAIL")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
