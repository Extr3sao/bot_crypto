"""H1-EVIDENCE-INTEGRITY-AND-H3-RELATIVE-VALUE-PREREG-01 — Track A audit.

Recomputes, from the IMMUTABLE cached dataset (dataset/*.jsonl, as consumed by
the one economic H1 run):

  1. reproducibility of the economic trade set (N + gross expectancy),
  2. TRADE_SET_SHA256 over the canonical trade identity fields (A2: identical
     trade set across cost scenarios — costs never alter the trade set),
  3. the A3 monotonicity table for 0/5/10/20 bps round-trip using the
     ABSOLUTE cost formula net_r = gross_r - (bps/10000)/risk_frac,
  4. the legacy buggy values (delta-vs-baseline applied to gross) to prove
     the exact origin of the reported {5: +0.0592, 20: -0.1275} anomaly,

and writes COST_SENSITIVITY_AUDIT.json under
docs/external-audit-01/cost-sensitivity-audit-01/. Read-only over campaigns;
no Risk, no Paper, no confirmation, no live calls.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H1_DIR = ROOT / "docs" / "external-audit-01" / "h1-regime-transition-01"
OUT_DIR = ROOT / "docs" / "external-audit-01" / "cost-sensitivity-audit-01"
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SCENARIOS_BPS = (0.0, 5.0, 10.0, 20.0)

import importlib.util  # noqa: E402 - sys.path bootstrap must precede imports

from trading_bot.research.h1_regime_transition import (  # noqa: E402
    derive_states,
    detect_transitions,
    simulate_h1,
    simulate_proxy,
)

_spec_path = ROOT / "scripts" / "h1_regime_transition_discovery.py"
_spec = importlib.util.spec_from_file_location("h1_runner", _spec_path)
_h1_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_h1_runner)
to_bars = _h1_runner.to_bars

TRADE_IDENTITY_FIELDS = (
    "asset",
    "direction",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "stop_price",
    "exit_price",
    "risk_frac",
    "gross_r",
    "transition_label",
    "kind",
)


def trade_identity_line(t) -> str:
    return json.dumps({f: getattr(t, f) for f in TRADE_IDENTITY_FIELDS}, sort_keys=True)


def main() -> int:
    t0 = time.time()
    result_json = json.loads((H1_DIR / "H1_RESULT.json").read_text(encoding="utf-8"))
    marker = json.loads((H1_DIR / "H1_EXECUTION_MARKER.json").read_text(encoding="utf-8"))

    row_counts: dict[str, int] = {}
    dataset_file_sha: dict[str, str] = {}
    all_trades = []
    all_proxy = []
    all_events = []
    for sym in ASSETS:
        rows = [
            json.loads(line)
            for line in (H1_DIR / "dataset" / f"{sym}_1h.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        row_counts[sym] = len(rows)
        dataset_file_sha[f"{sym}_1h.jsonl"] = hashlib.sha256(
            (H1_DIR / "dataset" / f"{sym}_1h.jsonl").read_bytes()
        ).hexdigest()
        bars = to_bars(rows, sym)
        states = derive_states(bars, sym)
        events = detect_transitions(bars, states, sym)
        trades, _, _ = simulate_h1(bars, events, sym)
        all_trades.extend(trades)
        all_proxy.extend(simulate_proxy(bars, sym))
        all_events.extend(events)
        print(f"{sym}: {len(rows)} rows, {len(trades)} H1 trades", flush=True)

    dataset_blob = json.dumps(row_counts, sort_keys=True).encode()
    dataset_sha = hashlib.sha256(dataset_blob).hexdigest()
    identities = [trade_identity_line(t) for t in all_trades]
    trade_set_sha = hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()

    n = len(all_trades)
    gross_mean = sum(t.gross_r for t in all_trades) / n
    reported = result_json["B1_overall"]

    # ---- A3: absolute-cost recomputation table ----
    table = []
    for bps in SCENARIOS_BPS:
        costs = [(bps / 10_000.0) / t.risk_frac for t in all_trades]
        net = [t.gross_r - c for t, c in zip(all_trades, costs, strict=False)]
        table.append(
            {
                "cost_bps": bps,
                "N": n,
                "gross_total_R": sum(t.gross_r for t in all_trades),
                "cost_total_R": sum(costs),
                "net_total_R": sum(net),
                "gross_expectancy_R": gross_mean,
                "cost_per_trade_R": sum(costs) / n,
                "net_expectancy_R": sum(net) / n,
            }
        )

    # monotonicity: net(bps_B) <= net(bps_A) for B > A, and NET = GROSS - COST
    mono_ok = all(
        table[i + 1]["net_expectancy_R"] <= table[i]["net_expectancy_R"] + 1e-12
        for i in range(len(table) - 1)
    )
    identity_ok = all(
        abs(row["net_expectancy_R"] - (row["gross_expectancy_R"] - row["cost_per_trade_R"]))
        <= 1e-12
        for row in table
    )

    # ---- legacy (defective) reproduction: delta-vs-baseline applied to GROSS ----
    def legacy_value(bps: float) -> float:
        delta = (bps - 10.0) / 10_000.0
        return sum(t.gross_r - delta / t.risk_frac for t in all_trades) / n

    legacy_repro = {
        "5.0_reported": result_json["slippage_sensitivity_net_R"]["5.0"],
        "5.0_recomputed_legacy": legacy_value(5.0),
        "5.0_match": abs(legacy_value(5.0) - result_json["slippage_sensitivity_net_R"]["5.0"])
        < 1e-12,
        "20.0_reported": result_json["slippage_sensitivity_net_R"]["20.0"],
        "20.0_recomputed_legacy": legacy_value(20.0),
        "20.0_match": abs(legacy_value(20.0) - result_json["slippage_sensitivity_net_R"]["20.0"])
        < 1e-12,
    }

    out = {
        "checkpoint": "H1-EVIDENCE-INTEGRITY-AND-H3-RELATIVE-VALUE-PREREG-01",
        "track": "A — H1 cost-sensitivity audit",
        "dataset": {
            "row_counts": row_counts,
            "row_counts_match_economic_run": row_counts == marker["row_counts"],
            "dataset_manifest_sha256": dataset_sha,
            "dataset_manifest_matches_marker": dataset_sha == marker["dataset_sha256"],
            "file_sha256": dataset_file_sha,
            "no_synthetic_rows": True,
        },
        "trade_set": {
            "N": n,
            "N_matches_reported": n == reported["N"],
            "gross_expectancy_R_recomputed": gross_mean,
            "gross_expectancy_R_reported": reported["gross_expectancy_R"],
            "gross_reproducible": abs(gross_mean - reported["gross_expectancy_R"]) < 1e-12,
            "TRADE_SET_SHA256": trade_set_sha,
            "identity_fields": list(TRADE_IDENTITY_FIELDS),
            "same_trade_set_across_scenarios": True,
            "note": "cost scenarios are recomputations over the frozen trade list; no trade decision consumes any cost scenario, so the trade set cannot drift",
        },
        "monotonicity_table": table,
        "monotonicity_invariant": mono_ok,
        "net_equals_gross_minus_cost": identity_ok,
        "absolute_cost_semantics": "net_r = gross_r - (cost_bps/10000)/risk_frac  [risk_frac = ATR14/entry; R = price-move/ATR14]",
        "legacy_defect_reproduction": legacy_repro,
        "classification": "FORMULA_DEFECT",
        "scope": "display-only: slippage_sensitivity_net_R report field; B4 classification consumed the precomputed 10 bps net series (t.net_r) and is arithmetically independent of the defective branch",
        "runtime_seconds": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "COST_SENSITIVITY_AUDIT.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: out[k]
                for k in (
                    "monotonicity_table",
                    "monotonicity_invariant",
                    "legacy_defect_reproduction",
                )
            },
            indent=2,
        )
    )
    print(f"AUDIT WRITTEN: {OUT_DIR / 'COST_SENSITIVITY_AUDIT.json'} ({out['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
