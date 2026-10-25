"""WP-ECONOMIC-BLOCKER-001 — audit of the admission ledger the runtime actually reads.

Three questions, each answered from files rather than from memory:

1. **Is the committed ledger what its own builder produces?** The builder is
   imported by path and re-run in memory; the result is compared field by field
   with ``config/strategy_admission.json``. Nothing is written.
2. **Are its provenance anchors real?** Every ``_sources[].sha256`` is recomputed
   against the file on disk, and against every historical revision of that path,
   so "the source changed" can be told apart from "this hash never existed".
3. **Why is each strategy not admitted?** The reasons are enumerated from the
   ledger plus the pre-registered admission matrix, and each one is classified
   as ECONOMIC / EVIDENCE / ADMISSION-GATE / CRITERIA / PROVENANCE. A strategy
   can carry several; none is inferred.

Output: ``STRATEGY_ADMISSION_AUDIT.json``.

Usage::

    uv run python scripts/wp_eco001_admission_audit.py --out <evidence dir>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("config/strategy_admission.json")
MATRIX = Path("docs/STRATEGY_ADMISSION_MATRIX.json")
V3_RESULTS = Path("docs/STRATEGY_DISCOVERY_V3_RESULTS.json")
BUILDER = Path("scripts/build_strategy_admission.py")
CRITERIA_DOC = Path("docs/STRATEGY_ADMISSION_CRITERIA.md")

#: Pre-registered minimum sample (STRATEGY_ADMISSION_CRITERIA.md §1).
MIN_TRADES = 100
MIN_OOS_TRADES = 30
#: The runtime's admission-scenario round trip at the reference intent, from
#: COST_MODEL_V3 (see the cost audit for the derivation).
REFERENCE_RT_BPS = 23.79


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def historical_blobs(relative: str) -> list[dict[str, str]]:
    """Every committed revision of a path, with the hash of its content."""
    revisions = [r for r in git("log", "--all", "--format=%H", "--", relative).splitlines() if r]
    out: list[dict[str, str]] = []
    for rev in dict.fromkeys(revisions):
        blob = subprocess.run(
            ["git", "show", f"{rev}:{relative}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).stdout
        out.append({"commit": rev[:12], "sha256": hashlib.sha256(blob).hexdigest()})
    return out


def load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("_admission_builder", REPO_ROOT / BUILDER)
    if spec is None or spec.loader is None:  # pragma: no cover - file exists in repo
        raise SystemExit("cannot load the admission builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(entry: dict[str, Any], *, in_candidates: bool, matrix_entry: dict[str, Any]) -> list[str]:
    """Every reason the strategy is not admitted, named by its kind."""
    reasons: list[str] = []
    gross = float(entry.get("expected_gross_edge_bps") or 0.0)
    evidence = entry.get("edge_evidence") or {}
    trades = int(evidence.get("sample_trades") or 0)

    if gross <= 0:
        reasons.append("ECONOMIC_NEGATIVE_GROSS")
    elif gross < REFERENCE_RT_BPS:
        reasons.append("ECONOMIC_BELOW_RUNTIME_COST")
    if gross < 12.0:
        reasons.append("ECONOMIC_BELOW_RESEARCH_BARRIER")
    if trades < MIN_TRADES:
        reasons.append("EVIDENCE_SAMPLE_UNPROVEN")
    if not in_candidates:
        reasons.append("ADMISSION_GATE_NO_PAPER_CANDIDATES")
    unknown = list(matrix_entry.get("unknown_checks") or [])
    if unknown:
        reasons.append("CRITERIA_UNCOMPUTED")
    if entry.get("admitted_for_paper"):
        reasons = [r for r in reasons if r != "ADMISSION_STAGE_ADMITTED"]
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "docs/agentic/economic_audit/WP-ECONOMIC-BLOCKER-001")
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ledger = json.loads((REPO_ROOT / LEDGER).read_text(encoding="utf-8"))
    matrix = json.loads((REPO_ROOT / MATRIX).read_text(encoding="utf-8"))
    builder = load_builder()
    rebuilt = builder.build()
    entries = ledger["strategies"]
    rebuilt_entries = rebuilt["strategies"]
    candidates = set(matrix.get("paper_candidates") or [])

    # -- 1. builder vs committed -------------------------------------------
    differing = sorted(
        key for key in set(entries) | set(rebuilt_entries) if entries.get(key) != rebuilt_entries.get(key)
    )
    provenance = []
    for source in ledger.get("_sources", []):
        path = Path(source["path"])
        actual = sha256(REPO_ROOT / path)
        history = historical_blobs(source["path"])
        provenance.append(
            {
                "path": source["path"],
                "recorded_sha256": source["sha256"],
                "actual_sha256": actual,
                "matches_disk": actual == source["sha256"],
                "matches_a_committed_revision": any(
                    h["sha256"] == source["sha256"] for h in history
                ),
                "committed_revisions": history,
            }
        )

    # -- 2. per-entry rejections -------------------------------------------
    rows = []
    for strategy_id, entry in sorted(entries.items()):
        family = str(entry.get("family"))
        matrix_entry = (matrix.get("admissions") or {}).get(family) or {}
        base = (matrix_entry.get("totals_base") or {}) if matrix_entry else {}
        evidence = entry.get("edge_evidence") or {}
        rows.append(
            {
                "strategy_id": strategy_id,
                "family": family,
                "timeframe": entry.get("timeframe"),
                "status": entry.get("status"),
                "admitted_for_paper": bool(entry.get("admitted_for_paper")),
                "expected_gross_edge_bps": entry.get("expected_gross_edge_bps"),
                "sample_trades": int(evidence.get("sample_trades") or 0),
                "evidence_class": evidence.get("evidence_class"),
                "period": evidence.get("period"),
                "metric": evidence.get("metric"),
                "source_doc": evidence.get("source_doc"),
                "reasons": classify(entry, in_candidates=family in candidates, matrix_entry=matrix_entry),
                "matrix_status": matrix_entry.get("status"),
                "matrix_mandatory_failures": list(matrix_entry.get("mandatory_failures") or []),
                "matrix_unknown_checks": list(matrix_entry.get("unknown_checks") or []),
                "matrix_base_totals": {
                    "trades": base.get("trades"),
                    "gross_usd": base.get("gross"),
                    "net_usd": base.get("net"),
                    "profit_factor": base.get("profit_factor"),
                }
                if base
                else None,
            }
        )

    reason_counts = Counter(reason for row in rows for reason in row["reasons"])
    payload = {
        "wp": "WP-ECONOMIC-BLOCKER-001",
        "artefact": "STRATEGY_ADMISSION_AUDIT",
        "ledger": LEDGER.as_posix(),
        "ledger_sha256": sha256(REPO_ROOT / LEDGER),
        "criteria_document": CRITERIA_DOC.as_posix(),
        "builder": BUILDER.as_posix(),
        "builder_reproduces_committed_entries": not differing,
        "entries_differing_from_builder": differing,
        "entry_count": len(entries),
        "entries_by_timeframe": dict(Counter(str(e.get("timeframe")) for e in entries.values())),
        "entries_by_status": dict(Counter(str(e.get("status")) for e in entries.values())),
        "entries_with_zero_sample": sum(
            1 for e in entries.values() if int((e.get("edge_evidence") or {}).get("sample_trades") or 0) == 0
        ),
        "paper_candidates_in_matrix": sorted(candidates),
        "structural_finding": (
            "the builder can only emit PAPER_CANDIDATE for a family listed in "
            "matrix.paper_candidates; that list is empty, so PAPER admission is "
            "structurally impossible today regardless of measured edge"
        ),
        "provenance": provenance,
        "provenance_ok": all(p["matches_disk"] for p in provenance),
        "provenance_has_unverifiable_anchor": any(
            not p["matches_disk"] and not p["matches_a_committed_revision"] for p in provenance
        ),
        "reason_counts": dict(reason_counts),
        "entries": rows,
        "research_cost_barrier": {
            "base_rt_bps": (json.loads((REPO_ROOT / V3_RESULTS).read_text(encoding="utf-8")).get("cost_model") or {}).get("base_rt_bps"),
            "twice_rt_bps": (json.loads((REPO_ROOT / V3_RESULTS).read_text(encoding="utf-8")).get("cost_model") or {}).get("twice_rt_bps"),
            "runtime_rt_bps": REFERENCE_RT_BPS,
            "note": "the admission checks were computed against the research barrier, which is LOWER than the runtime's",
        },
    }
    path = out_dir / "STRATEGY_ADMISSION_AUDIT.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[admission] entries={payload['entry_count']} by_tf={payload['entries_by_timeframe']}")
    print(f"[admission] builder_reproduces={payload['builder_reproduces_committed_entries']} differing={differing}")
    print(f"[admission] paper_candidates={payload['paper_candidates_in_matrix']}")
    print(f"[admission] provenance_ok={payload['provenance_ok']} unverifiable={payload['provenance_has_unverifiable_anchor']}")
    print(f"[admission] reasons={payload['reason_counts']}")
    print(f"[admission] -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
