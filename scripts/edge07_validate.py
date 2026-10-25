#!/usr/bin/env python
"""WP-EDGE-07 Track B — read the frozen fixed-target trend book on the new holdout.

    python scripts/edge07_validate.py                 # run, write VALIDATION.json/.md + trades
    python scripts/edge07_validate.py --json          # print the payload, write nothing
    python scripts/edge07_validate.py --check         # re-run and compare with the stored verdict

The parameters are not arguments of this command, and neither is the window: both are the ones
`reports/edge-recovery/WP-EDGE-07/PREREGISTRATION.json` froze before the holdout existed. A
command line that could change them would make the registration a suggestion, and re-running
with a different number on this window is exactly what the registration forbids.

Exit codes:

    0  the run completed and the verdict is ADMIT_PAPER or REJECT (a verdict, either way)
    1  the verdict is INSUFFICIENT_EVIDENCE (no result, never a pass)
    2  the run could not be completed (missing holdout, parameters not the registered ones)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge07 import validation as V  # noqa: E402

OUT_DIR = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07" / "validation"


def summarize(payload: dict[str, Any]) -> str:
    reading = payload["reading"]
    base = payload["NEW_HOLDOUT"]["BASE"]
    lines = [
        "=" * 78,
        "WP-EDGE-07 TRACK B — fixed 3xATR target trend book, new holdout",
        "=" * 78,
        f"run                 {payload['run_id']}",
        f"params hash         {payload['params_hash'][:16]}… "
        f"(registered: {payload['registered_params_hash'][:16]}…, match="
        f"{payload['params_hash_matches_the_registration']})",
        f"new window          {payload['windows']['NEW_HOLDOUT']['start']} .. "
        f"{payload['windows']['NEW_HOLDOUT']['end']} (exclusive)",
        f"holdout             {payload['holdout']['coverage_4h_bars']} 4h bars per asset, "
        f"gaps={payload['holdout']['gaps']}, digest={(payload['holdout']['manifest_digest'] or '')[:16]}…",
        f"verdict             {reading['verdict']}",
        f"why                 {reading['why']}",
        "",
        "new window, by scenario:",
    ]
    for scenario in V.COST_SCENARIOS:
        metrics = payload["NEW_HOLDOUT"][scenario]
        lines.append(
            f"  {scenario:<9} trades={metrics.get('trades'):>4} net={metrics.get('net_usdt'):>10} "
            f"expectancy={metrics.get('expectancy_usdt')} pf={metrics.get('profit_factor')} "
            f"dd={metrics.get('max_drawdown_pct')}% sharpe={metrics.get('sharpe_annualised')}"
        )
    extras = base["extras"]
    lines.append(
        f"  bootstrap 90% CI    expectancy [{extras['expectancy_ci_90_usdt']['low']}, "
        f"{extras['expectancy_ci_90_usdt']['high']}]  net "
        f"[{extras['net_ci_90_usdt']['low']}, {extras['net_ci_90_usdt']['high']}]"
    )
    lines.append(f"  time blocks         {extras['positive_time_blocks']} of 3 positive")
    lines.append(
        f"  serial dependence   lag-1={extras['serial_dependence'].get('lag1_autocorrelation')} "
        f"band=±{extras['serial_dependence'].get('band_2_over_sqrt_n')} "
        f"runs z={extras['serial_dependence'].get('runs_z')}"
    )
    comparison = payload["comparison"]
    lines.append(
        f"  comparison (same window): trailing net={comparison['trailing']['net_usdt']} "
        f"trades={comparison['trailing']['trades']} vs fixed net="
        f"{comparison['fixed_target']['net_usdt']} trades={comparison['fixed_target']['trades']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--json", action="store_true", help="print the payload and write nothing")
    parser.add_argument(
        "--check", action="store_true", help="re-run and compare with the stored verdict"
    )
    options = parser.parse_args(argv)

    if not V.HOLDOUT_MANIFEST.is_file():
        print(
            f"missing holdout manifest at {V.HOLDOUT_MANIFEST}; "
            "run scripts/edge07_fetch_holdout.py first",
            file=sys.stderr,
        )
        return 2

    payload = V.evaluate()
    out_dir = Path(options.out)

    if options.json:
        public = {key: value for key, value in payload.items() if not key.startswith("_")}
        print(json.dumps(public, indent=2, ensure_ascii=False, sort_keys=True, default=str))
        return 0

    written = V.write_artifacts(payload, out_dir)
    print(summarize(payload))
    for name, path in written.items():
        print(f"wrote {name:<9} {path.relative_to(REPO_ROOT)}")

    if not payload["params_hash_matches_the_registration"]:
        return 2
    if options.check:
        stored_path = out_dir / "VALIDATION.json"
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        same_verdict = stored.get("reading", {}).get("verdict") == payload["reading"]["verdict"]
        same_net = stored.get("NEW_HOLDOUT", {}).get("BASE", {}).get("net_usdt") == payload[
            "NEW_HOLDOUT"
        ]["BASE"].get("net_usdt")
        print(
            json.dumps(
                {
                    "check": "verdict_and_new_window_net_stable",
                    "result": "PASS" if (same_verdict and same_net) else "FAIL",
                    "stored_verdict": stored.get("reading", {}).get("verdict"),
                    "verdict": payload["reading"]["verdict"],
                    "stored_net_usdt": stored.get("NEW_HOLDOUT", {})
                    .get("BASE", {})
                    .get("net_usdt"),
                    "net_usdt": payload["NEW_HOLDOUT"]["BASE"].get("net_usdt"),
                },
                indent=2,
            )
        )
        if not (same_verdict and same_net):
            return 2
    return 1 if payload["reading"]["verdict"] == "INSUFFICIENT_EVIDENCE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
