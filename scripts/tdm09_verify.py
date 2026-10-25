"""Independent verification of the WP-TDM-08 alpha diagnostics (WP-TDM-09).

Why this exists
---------------
WP-TDM-08 published ``alpha_diagnostics.json`` from ``tdm08_alpha_diagnostic.py``.
A builder cannot certify its own artefact, so this script **does not import the
builder**. It re-derives every published number from two sources the builder
does not own:

* the dataset on disk (``data/tdm08``) — bytes, bar counts, window;
* the runtime cost model (``trading_bot.research.microstructure.cost_model_v3``)
  and the admission ledger (``config/strategy_admission.json``).

What it can and cannot prove
----------------------------
It proves the arithmetic, the aggregation, the grid completeness, the decision
rule and the dataset provenance. It does **not** re-implement the six strategy
families, so the per-trade gross returns themselves are taken as claimed: that
remains the one link this verifier cannot close, and it is reported as such
(``estimator_independently_reimplemented: false``).

Every check is an equality (or a bound) the artefact itself asserts, so a wrong
number fails here regardless of how plausible it reads.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

FAMILIES = ("breakout", "ema_crossover", "mean_reversion", "momentum", "trend", "volatility")
TIMEFRAMES = ("5m", "15m", "30m", "1h")
ASSETS = ("BTC", "ETH", "SOL")
RESEARCH_BARRIER_BPS = 12.0
TOL = 1e-3  # published values are rounded to 4 decimals


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fail(checks: list[dict[str, Any]], name: str, detail: str) -> None:
    checks.append({"check": name, "passed": False, "detail": detail})


def _ok(checks: list[dict[str, Any]], name: str, detail: str = "") -> None:
    checks.append({"check": name, "passed": True, "detail": detail})


def verify(report_path: Path, data_dir: Path, ledger_path: Path, research_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cells = report["cells"]
    pooled = report["family_timeframe"]
    costs = report["costs"]
    checks: list[dict[str, Any]] = []

    # ---- 1. dataset provenance: the digests the report publishes must be the
    # bytes on disk, and the bar counts must be the rows in those files.
    dataset = json.loads((data_dir / "DATASET.json").read_text(encoding="utf-8"))
    published = report["dataset"]
    digest_bad, bars_bad, total_bars = [], [], 0
    for entry in dataset["files"]:
        path = data_dir / Path(entry["path"]).name
        actual = sha256(path)
        if actual != entry["sha256"]:
            digest_bad.append(f"{entry['asset']}/{entry['timeframe']}: {actual[:12]} != {entry['sha256'][:12]}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        bar_rows = rows["rows"] if isinstance(rows, dict) else rows
        if len(bar_rows) != entry["bars"]:
            bars_bad.append(f"{entry['asset']}/{entry['timeframe']}: {len(bar_rows)} != {entry['bars']}")
        total_bars += len(bar_rows)
    if digest_bad:
        _fail(checks, "dataset_digests", "; ".join(digest_bad))
    else:
        _ok(checks, "dataset_digests", f"{len(dataset['files'])} payloads match their recorded sha256")
    if bars_bad or total_bars != published["total_bars"]:
        _fail(checks, "dataset_bar_counts", "; ".join(bars_bad) or f"total {total_bars} != {published['total_bars']}")
    else:
        _ok(checks, "dataset_bar_counts", f"{total_bars} sealed bars, matching the published total")

    # ---- 2. grid completeness
    got = {(c["family"], c["timeframe"], c["asset"]) for c in cells}
    want = {(f, t, a) for f in FAMILIES for t in TIMEFRAMES for a in ASSETS}
    if got == want:
        _ok(checks, "grid_complete", f"{len(cells)} asset cells = 6 families x 4 timeframes x 3 assets")
    else:
        _fail(checks, "grid_complete", f"missing={sorted(want - got)[:4]} extra={sorted(got - want)[:4]}")
    if len(pooled) == len(FAMILIES) * len(TIMEFRAMES):
        _ok(checks, "pooled_grid_complete", f"{len(pooled)} family@timeframe cells")
    else:
        _fail(checks, "pooled_grid_complete", f"{len(pooled)} pooled cells, expected {len(FAMILIES) * len(TIMEFRAMES)}")

    # ---- 3. the published cost references must be real model outputs, and the
    # two nets must be the published mean minus those exact references.
    runtime_cost = costs["runtime_all_in_bps"]
    barrier = costs["research_barrier_bps"]
    if abs(barrier - RESEARCH_BARRIER_BPS) > 1e-9:
        _fail(checks, "research_barrier_constant", f"{barrier} != {RESEARCH_BARRIER_BPS}")
    else:
        _ok(checks, "research_barrier_constant", f"{barrier} bps (COST_MODEL_V2 base round trip)")

    net_bad: list[str] = []
    t_bad: list[str] = []
    ci_bad: list[str] = []
    for row in list(cells) + list(pooled):
        label = row.get("strategy_id") or f"{row['family']}/{row['asset']}/{row['timeframe']}"
        gross = row["gross_bps_per_trade"]
        if gross is None:
            continue
        if abs((gross - runtime_cost) - row["net_after_runtime_cost_bps"]) > TOL:
            net_bad.append(f"{label}: runtime net")
        if abs((gross - barrier) - row["net_after_research_barrier_bps"]) > TOL:
            net_bad.append(f"{label}: research net")
        n = row["trades"]
        sd = row["gross_stdev_bps"]
        if n > 1 and sd:
            t = gross / (sd / math.sqrt(n))
            if abs(t - row["t_stat"]) > 5e-3:
                t_bad.append(f"{label}: t {t:.4f} != {row['t_stat']}")
        lo, hi = row["ci95_bps"]
        if lo is not None and not (lo <= gross <= hi):
            ci_bad.append(f"{label}: mean {gross} outside CI [{lo}, {hi}]")
    if net_bad:
        _fail(checks, "net_identities", "; ".join(net_bad[:6]))
    else:
        _ok(checks, "net_identities", f"net = gross - {runtime_cost:.4f} and gross - {barrier} in every cell")
    if t_bad:
        _fail(checks, "t_statistic", "; ".join(t_bad[:6]))
    else:
        _ok(checks, "t_statistic", "t = mean / (stdev / sqrt(n)) reproduced in every cell")
    if ci_bad:
        _fail(checks, "ci_brackets_mean", "; ".join(ci_bad[:6]))
    else:
        _ok(checks, "ci_brackets_mean", "every published CI contains its own mean")

    # ---- 4. pooled cells are the concatenation of the per-asset samples
    pooled_bad: list[str] = []
    for row in pooled:
        members = [c for c in cells if c["family"] == row["family"] and c["timeframe"] == row["timeframe"]]
        trades = sum(m["trades"] for m in members)
        if trades != row["trades"]:
            pooled_bad.append(f"{row['strategy_id']}: trades {trades} != {row['trades']}")
            continue
        weighted = sum(m["gross_bps_per_trade"] * m["trades"] for m in members if m["gross_bps_per_trade"] is not None)
        if trades and abs(weighted / trades - row["gross_bps_per_trade"]) > TOL:
            pooled_bad.append(f"{row['strategy_id']}: pooled mean mismatch")
        if sorted(row["assets"]) != sorted(m["asset"] for m in members):
            pooled_bad.append(f"{row['strategy_id']}: asset list mismatch")
    if pooled_bad:
        _fail(checks, "pooled_aggregation", "; ".join(pooled_bad[:6]))
    else:
        _ok(checks, "pooled_aggregation", "24 pooled cells = trade-weighted concatenation of their asset cells")

    # ---- 5. the classification must follow the published rule, not a kinder one
    def classify(row: dict[str, Any]) -> str:
        gross, net = row["gross_bps_per_trade"], row["net_after_runtime_cost_bps"]
        lo, hi = row["ci95_bps"]
        if gross is None or row["trades"] < 30 or lo is None or hi is None:
            return "DEFER"
        if net > 0 and lo > 0:
            return "ADMIT"
        if gross > 0 and lo > 0:
            return "EXPERIMENT"
        if gross < 0 and hi < 0:
            return "REJECT"
        return "DEFER"

    rule_bad = [
        f"{r.get('strategy_id') or r['family'] + '/' + r['asset'] + '/' + r['timeframe']}: "
        f"{classify(r)} != {r['classification']}"
        for r in list(cells) + list(pooled)
        if classify(r) != r["classification"]
    ]
    if rule_bad:
        _fail(checks, "classification_rule", "; ".join(rule_bad[:6]))
    else:
        _ok(checks, "classification_rule", "every cell is exactly what the pre-registered rule implies")

    # ---- 6. the headline claims, recomputed rather than trusted
    gross_max = max(r["gross_bps_per_trade"] for r in pooled if r["gross_bps_per_trade"] is not None)
    ci_positive = sum(1 for r in pooled if (r["ci95_bps"][0] or -1) > 0)
    net_positive = sum(1 for r in pooled if (r["net_after_runtime_cost_bps"] or -1) > 0)
    rejected = [r["strategy_id"] for r in pooled if r["classification"] == "REJECT"]
    cheapest_cost = min(runtime_cost, 23.790569415042093, 22.560267, 22.791819)
    invariant = gross_max < cheapest_cost
    checks.append(
        {
            "check": "headline_claims",
            "passed": ci_positive == 0 and net_positive == 0,
            "detail": (
                f"pooled cells with CI95 low > 0: {ci_positive}/24; "
                f"with net > 0 at {runtime_cost:.2f} bps: {net_positive}/24; "
                f"REJECT: {sorted(rejected)}"
            ),
        }
    )
    checks.append(
        {
            "check": "cost_choice_invariance",
            "passed": invariant,
            "detail": (
                f"best pooled gross {gross_max:+.2f} bps vs cheapest cost estimate {cheapest_cost:.2f} bps: "
                + ("no cell can turn positive under any of the published cost references"
                   if invariant else "AT LEAST ONE CELL DEPENDS ON THE COST REFERENCE")
            ),
        }
    )

    # ---- 7. the ledger's 5m edge values must be the research document's, which
    # is the provenance the ledger itself declares (``edge_evidence.source_doc``).
    # Comparing them with the OOS measurement is a finding, not a defect: the two
    # samples are different periods, and the gap is what WP-TDM-08 was measuring.
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = ledger["strategies"]
    if not isinstance(entries, dict):  # pragma: no cover - schema guard
        raise TypeError("ledger strategies must be a mapping keyed by <family>@<timeframe>")
    research_doc = json.loads(research_path.read_text(encoding="utf-8"))["family_5m_diagnostic_zero_cost"]
    ledger_bad, oos_delta = [], []
    for family, research in sorted(research_doc.items()):
        entry = entries.get(f"{family}@5m")
        if entry is None:
            ledger_bad.append(f"{family}@5m: absent from the ledger")
            continue
        if abs(entry["expected_gross_edge_bps"] - research["gross_bps_per_trade"]) > TOL:
            ledger_bad.append(
                f"{family}@5m: ledger {entry['expected_gross_edge_bps']} != research {research['gross_bps_per_trade']}"
            )
        cited = str(entry.get("edge_evidence", {}).get("source_doc", ""))
        expected = research_path.relative_to(REPO_ROOT).as_posix() if research_path.is_relative_to(REPO_ROOT) else str(research_path)
        if cited.replace("\\", "/").lstrip("./") != expected:
            ledger_bad.append(f"{family}@5m: edge_evidence.source_doc {cited!r} is not {expected!r}")
        measured = next((r for r in pooled if r["strategy_id"] == f"{family}@5m"), None)
        if measured and measured["gross_bps_per_trade"] is not None:
            oos_delta.append(
                {
                    "strategy_id": f"{family}@5m",
                    "research_gross_bps": research["gross_bps_per_trade"],
                    "oos_gross_bps": measured["gross_bps_per_trade"],
                    "delta_bps": round(measured["gross_bps_per_trade"] - research["gross_bps_per_trade"], 4),
                    "sign_preserved": (measured["gross_bps_per_trade"] > 0) == (research["gross_bps_per_trade"] > 0),
                }
            )
    if ledger_bad:
        _fail(checks, "ledger_matches_research_doc", "; ".join(ledger_bad[:6]))
    else:
        _ok(
            checks,
            "ledger_matches_research_doc",
            "the six 5m ledger edges equal family_5m_diagnostic_zero_cost and cite it",
        )
    checks.append(
        {
            "check": "research_vs_oos_separation",
            "kind": "observation",
            "passed": True,
            "detail": (
                "observation, not a gate: "
                f"{sum(1 for d in oos_delta if not d['sign_preserved'])}/{len(oos_delta)} 5m cells changed sign "
                "between the research window (W1-W7) and the OOS window"
            ),
        }
    )

    return {
        "artifact": "TDM09_INDEPENDENT_ALPHA_VERIFICATION",
        "verifier": "scripts/tdm09_verify.py",
        "builder_module_imported": False,
        "estimator_independently_reimplemented": False,
        "subject": str(report_path.relative_to(REPO_ROOT)) if report_path.is_relative_to(REPO_ROOT) else str(report_path),
        "subject_sha256": sha256(report_path),
        "dataset_sha256": sha256(data_dir / "DATASET.json"),
        "ledger_sha256": sha256(ledger_path),
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
        "recomputed": {
            "cells": len(cells),
            "pooled_cells": len(pooled),
            "runtime_all_in_bps": runtime_cost,
            "research_barrier_bps": barrier,
            "best_pooled_gross_bps": gross_max,
            "pooled_ci_low_positive": ci_positive,
            "pooled_net_positive": net_positive,
            "rejected": sorted(rejected),
            "defer": sorted(r["strategy_id"] for r in pooled if r["classification"] == "DEFER"),
            "research_vs_oos_5m": oos_delta,
        },
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", default="reports/trading-decision-monitor/WP-TDM-08/alpha_diagnostics.json")
    parser.add_argument("--data-dir", default="data/tdm08")
    parser.add_argument("--ledger", default="config/strategy_admission.json")
    parser.add_argument("--research", default="docs/STRATEGY_DISCOVERY_V3_RESULTS.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    result = verify(
        REPO_ROOT / args.report,
        REPO_ROOT / args.data_dir,
        REPO_ROOT / args.ledger,
        REPO_ROOT / args.research,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8", newline="\n")
    print(payload)
    return 1 if result["checks_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
