#!/usr/bin/env python
"""WP-EDGE-06 Track B — run the registered families and write the comparison.

    python scripts/edge06_research.py [--out reports/edge-recovery/WP-EDGE-06/research]
                                      [--scenarios BASE,2X_FEES,ADVERSE]
                                      [--book edge06_fade_extension] [--json]

The parameters are not arguments of this command on purpose. They are the ones
``HYPOTHESES.md`` registered, and a command line that could change them would make the
registration a suggestion: re-running with a different number is a *new* experiment and needs
its own registration, which is why it has to be a code change and a commit rather than a flag.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge06 import program as P  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06" / "research"),
    )
    parser.add_argument("--scenarios", default="BASE,2X_FEES,ADVERSE")
    parser.add_argument("--book", default=None, help="run one registered book only")
    parser.add_argument("--json", action="store_true", help="print the payload, write nothing")
    options = parser.parse_args(argv)

    scenarios = tuple(part.strip() for part in options.scenarios.split(",") if part.strip())
    if options.book:
        if options.book not in P.FAMILY_BOOKS:
            print(f"unknown book {options.book!r}; registered: {sorted(P.FAMILY_BOOKS)}", file=sys.stderr)
            return 2
        result = P.run_family(options.book, scenarios=scenarios)
        result["reading"] = P.verdict_for(result)
        payload = {
            "schema_version": P.SCHEMA_VERSION,
            "book": options.book,
            "families": {options.book: result},
            "reference": P.reference_reading(),
            "declared_params": P.DECLARED_PARAMS,
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        payload["run_id"] = "EDGE06-PROGRAM-SINGLE"
        payload["as_of_utc"] = result["splits"]["DEV"]["BASE"].get("as_of_utc") or ""
    else:
        payload = P.run_program(scenarios=scenarios)

    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    out = Path(options.out)
    written = P.write_artifacts(payload, out)
    for book, result in payload["families"].items():
        reading = result["reading"]
        print(
            f"{book:<26} {reading['verdict']:<26} oos trades="
            f"{reading['evidence'].get('oos_trades')} oos net={reading['evidence'].get('oos_net_usdt')}"
        )
    print(f"wrote {', '.join(str(path) for path in written.values())}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
