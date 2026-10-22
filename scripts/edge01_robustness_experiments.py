"""Run the WP-EDGE-02 robustness experiments.

    python scripts/edge01_robustness_experiments.py [--experiment trend|risk|all]

* `trend` — WP-EDGE-02A: the frozen EDGE-TREND-01 4h ruleset, unchanged, re-measured
  and read for sensitivity (largest winner removed), contribution (per asset, per
  regime, per period), adverse cost plane, uncertainty intervals that respect the
  trades' own autocorrelation, and a risk-adjusted comparison with buy & hold.
* `risk`  — WP-EDGE-02B: the audit of H6's 183 risk refusals, reconstructed with the
  state the budget saw at the moment of the touch.

Both are deterministic, offline and DEV-declared; both are verified by a separate
process (`scripts/edge01_wp02_verify.py`) that imports nothing from the package.
Neither is wired into the PAPER runtime and neither promotes anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge01.risk_audit import (  # noqa: E402
    run_risk_audit,
    write_risk_audit_artifacts,
)
from trading_bot.research.edge01.robustness import (  # noqa: E402
    run_trend_robustness,
    write_trend_robustness_artifacts,
)

OUTDIRS: dict[str, str] = {
    "trend": "reports/edge-recovery/WP-EDGE-02/trend-robustness",
    "risk": "reports/edge-recovery/WP-EDGE-02/h6-risk-audit",
}

RUNNERS = {
    "trend": (run_trend_robustness, write_trend_robustness_artifacts),
    "risk": (run_risk_audit, write_risk_audit_artifacts),
}


def run_one(name: str, *, root: Path) -> dict[str, object]:
    run, write = RUNNERS[name]
    payload = run(root=root)
    outdir = root / OUTDIRS[name]
    written = write(payload, outdir)
    verdict = payload["verdict"]["verdict"]
    print(f"[{name}] {payload['run_id']}: {len(written)} artefactos en {outdir.relative_to(root)}")
    print(f"[{name}] VEREDICTO: {verdict}")
    if name == "trend":
        for key, run_block in payload["runs"].items():
            combined = run_block["combined"]
            print(
                f"[{name}] {key:<12} trades={combined['trades']:<4} "
                f"net={combined['net_usdt']:>10,.4f} "
                f"expectancy={(combined['expectancy_usdt'] or 0.0):>9,.4f} "
                f"dd={combined['max_drawdown_pct']:>6,.4f}% "
                f"largest/Net={(combined['largest_trade_share_of_net'] or 0.0):>7,.4f}"
            )
        for key, block in payload["sensitivity"].items():
            base = block["baseline"]["net_usdt"]
            chain = ", ".join(
                f"k={item['k']}: {item['net_usdt']:,.2f}" for item in block["leave_out"]
            )
            print(f"[{name}] sensibilidad {key}: base {base:,.2f} -> {chain}")
        print(f"[{name}] reproduccion: {payload['reproduction'].get('all_equal')}")
    else:
        summary = payload["summary"]
        print(
            f"[{name}] ordenes={summary['orders_placed']} rellenos={summary['orders_filled']} "
            f"rechazos={summary['orders_refused']} motivos={summary['refusal_reasons']}"
        )
        print(
            f"[{name}] rechazos correctos: {summary['refusals_correct']}/{summary['refusals_checked']} "
            f"(primaria {summary['primary_refusals_correct']}/{summary['primary_refusals']})"
        )
        print(
            f"[{name}] acuerdo con el Risk Engine de runtime: "
            f"{summary['runtime_agreements']}/{summary['refusals_checked']}; "
            f"invariantes: {summary['invariants_checked']} comprobados, "
            f"{summary['invariants_failed']} fallos"
        )
    return {
        "experiment": name,
        "run_id": payload["run_id"],
        "verdict": verdict,
        "artifacts": sorted(written),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=("trend", "risk", "all"), default="all")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)

    names = ("trend", "risk") if args.experiment == "all" else (args.experiment,)
    for name in names:
        run_one(name, root=Path(args.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
