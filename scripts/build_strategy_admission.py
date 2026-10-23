"""Build the strategy admission ledger from committed research artifacts.

CLAIM → SOURCE → EVIDENCE → DECISION.

Every entry in ``config/strategy_admission.json`` is derived here, from
committed JSON results, with the source files' SHA-256 recorded so the
ledger can be rebuilt and audited:

* ``docs/STRATEGY_DISCOVERY_V3_RESULTS.json`` — per-family gross edge in
  bps/trade and the research classification (zero-cost diagnostic).
* ``docs/STRATEGY_ADMISSION_MATRIX.json`` — pre-registered admission checks
  (c1..c8) and the formal status of each family.

Rules:
* a family is ``PAPER_CANDIDATE`` only when the matrix lists it under
  ``paper_candidates`` AND its measured gross edge is positive;
* ``COST_KILLED`` is kept as the research classification when the family's
  gross edge was positive but below the cost barrier of that study;
* everything else is ``NO_GROSS_EDGE``;
* unknown families are absent on purpose — the runtime treats absence as
  UNKNOWN and refuses PAPER (fail closed);
* entries are per (family, timeframe). The 5m numbers come from the 5m
  diagnostic; 15m/30m/1h come from the pre-registered D-01 timeframe
  hypothesis evidence, which reports gross bps per trade but NOT a trade
  count → ``sample_trades=0`` on purpose, so the provenance agent raises the
  "sample below minimum" critique instead of a fabricated sample size.

Deterministic: the same inputs always produce byte-identical output.

Usage:
    uv run python scripts/build_strategy_admission.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

V3_RESULTS = Path("docs/STRATEGY_DISCOVERY_V3_RESULTS.json")
ADMISSION_MATRIX = Path("docs/STRATEGY_ADMISSION_MATRIX.json")
OUTPUT = Path("config/strategy_admission.json")

LEDGER_SCHEMA_VERSION = "strategy-admission-ledger-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    v3 = json.loads((repo_root / V3_RESULTS).read_text(encoding="utf-8"))
    matrix = json.loads((repo_root / ADMISSION_MATRIX).read_text(encoding="utf-8"))

    diagnostics: dict[str, Any] = v3.get("family_5m_diagnostic_zero_cost", {})
    admissions: dict[str, Any] = matrix.get("admissions", {})
    paper_candidates = set(matrix.get("paper_candidates", []))
    # The sample window every gross-edge number below was measured on. Carried
    # into each entry so the value can never be read as a timeless truth.
    period = str((v3.get("dataset") or {}).get("windows") or "unspecified")

    # Per-timeframe zero-cost gross edge from the D-01 hypothesis evidence.
    timeframe_evidence: dict[str, dict[str, float]] = {}
    for hypothesis in (v3.get("hypotheses") or {}).values():
        block = ((hypothesis or {}).get("evidence") or {}).get("zero_cost_gross_bps_per_trade")
        if isinstance(block, dict):
            for family, by_tf in block.items():
                if not isinstance(by_tf, dict):
                    continue
                for tf, value in by_tf.items():
                    if isinstance(value, int | float):
                        timeframe_evidence.setdefault(str(tf), {})[str(family)] = float(value)

    strategies: dict[str, Any] = {}

    def _add_entry(
        *,
        family: str,
        timeframe: str,
        gross_bps: float,
        trades: int,
        metric: str,
        rationale: str,
    ) -> None:
        if family in paper_candidates and gross_bps > 0:
            status = "PAPER_CANDIDATE"
        elif gross_bps > 0:
            status = "COST_KILLED"
        else:
            status = "NO_GROSS_EDGE"
        admitted = status == "PAPER_CANDIDATE"
        strategies[f"{family}@{timeframe}"] = {
            "family": family,
            "status": status,
            "admitted_for_paper": admitted,
            "expected_gross_edge_bps": round(gross_bps, 6),
            "edge_evidence": {
                "source_doc": V3_RESULTS.as_posix(),
                "metric": metric,
                "value_bps": round(gross_bps, 6),
                "knowledge": "ESTIMATED",
                "sample_trades": trades,
                "note": (
                    "zero-cost research diagnostic (no execution cost applied); "
                    "used ONLY as the expected gross edge of a research candidate"
                    + (
                        ""
                        if trades > 0
                        else "; trade count not published for this timeframe -> sample "
                        "size unproven (recorded as sample_trades=0)"
                    )
                ),
                "evidence_class": "HISTORICAL_ESTIMATE",
                "period": period,
                "timeframe": timeframe,
                "status": status,
            },
            "source_doc": V3_RESULTS.as_posix(),
            "rationale": rationale,
            "timeframe": timeframe,
            "known": True,
        }

    for family in sorted(diagnostics):
        diag = diagnostics[family]
        gross_bps = float(diag.get("gross_bps_per_trade", 0.0))
        trades = int(diag.get("trades", 0))
        research_class = str(diag.get("classification", "NO_GROSS_EDGE"))
        matrix_entry = admissions.get(family) or {}
        mandatory_failures = list(matrix_entry.get("mandatory_failures", []))
        oos = matrix_entry.get("oos") or {}
        rationale = (
            f"research classification {research_class}; gross {gross_bps:.2f} bps/trade over "
            f"{trades} trades; admission checks failed: {mandatory_failures or ['none']}; "
            f"oos net {oos.get('net')}"
        )
        _add_entry(
            family=family,
            timeframe="5m",
            gross_bps=gross_bps,
            trades=trades,
            metric="family_5m_diagnostic_zero_cost.gross_bps_per_trade",
            rationale=rationale,
        )

    for timeframe, by_family in sorted(timeframe_evidence.items()):
        for family, gross_bps in sorted(by_family.items()):
            if timeframe == "5m":
                continue  # the 5m diagnostic above is authoritative for 5m
            _add_entry(
                family=family,
                timeframe=timeframe,
                gross_bps=gross_bps,
                trades=0,
                metric=(
                    "D-01_timeframe_horizon.evidence."
                    f"zero_cost_gross_bps_per_trade.{family}.{timeframe}"
                ),
                rationale=(
                    f"D-01 timeframe evidence (verdict REJECT_COST_KILLED): zero-cost gross "
                    f"{gross_bps:.2f} bps/trade at {timeframe}; trade count not published in "
                    f"this artifact -> sample size unproven"
                ),
            )

    return {
        "_schema_version": LEDGER_SCHEMA_VERSION,
        "_generated_by": "scripts/build_strategy_admission.py",
        "_claim": (
            "no strategy is admitted for PAPER execution unless a committed research "
            "artifact places it under paper_candidates with measured positive gross edge"
        ),
        "_sources": [
            {"path": V3_RESULTS.as_posix(), "sha256": _sha256(repo_root / V3_RESULTS)},
            {"path": ADMISSION_MATRIX.as_posix(), "sha256": _sha256(repo_root / ADMISSION_MATRIX)},
        ],
        "_admission_cost_model": "COST_MODEL_V3 (evaluated live per cycle; never stored here)",
        "_period": period,
        "strategies": strategies,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed ledger matches the artifacts (no write)",
    )
    args = parser.parse_args(argv)

    payload = build()
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    out_path = REPO_ROOT / OUTPUT

    if args.check:
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if current != rendered:
            sys.stderr.write(
                "ADMISSION_LEDGER_STALE: regenerate with build_strategy_admission.py\n"
            )
            return 1
        print("admission ledger is up to date")
        return 0

    out_path.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(payload['strategies'])} strategies)")
    for sid, entry in payload["strategies"].items():
        print(f"  {sid:<16} {entry['status']:<14} admitted={entry['admitted_for_paper']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
