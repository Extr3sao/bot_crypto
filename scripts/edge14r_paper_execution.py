"""edge14r_paper_execution — drive the canonical paper path over real bars.

Executes the two arms defined by
``trading_bot.research.economic_recovery.paper_exec`` (committed admission
ledger, and a declared sandbox ledger) and writes the evidence pair:

    reports/economic-recovery/RFC-EDGE-014R/PAPER_EXECUTION_EVIDENCE.json
    reports/economic-recovery/RFC-EDGE-014R/PAPER_EXECUTION_EVIDENCE.md

Nothing here sends an order or opens a credential: the bars come from ccxt's
public endpoints and the fills come from ``PaperBroker`` in-process.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.economic_recovery import paper_exec

OUT = Path(__file__).resolve().parents[1] / "reports" / "economic-recovery" / "RFC-EDGE-014R"


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R paper execution evidence")
    parser.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--warmup-bars", type=int, default=120)
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--reduced", action="store_true", help="Do not inline per-cycle detail")
    args = parser.parse_args()

    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    payload = paper_exec.run_execution(
        symbols=symbols,
        timeframe=args.timeframe,
        limit=args.limit,
        warmup_bars=args.warmup_bars,
        balance=args.balance,
        scratch_dir=OUT / "scratch",
    )

    OUT.mkdir(parents=True, exist_ok=True)
    written = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    (OUT / "PAPER_EXECUTION_EVIDENCE.json").write_text(written, encoding="utf-8")
    (OUT / "PAPER_EXECUTION_EVIDENCE.md").write_text(
        paper_exec.render_markdown(payload), encoding="utf-8"
    )

    for name, arm in payload["arms"].items():
        totals = arm["stage_totals"]
        print(
            f"[paper-exec] {name:18s} cycles={arm['cycles']:4d} "
            f"contexts={totals['contexts_built']:4d} router_no_trade={totals['router_no_trade']:4d} "
            f"risk_accepted={totals['risk_accepted']:4d} orders={totals['orders_created']:4d} "
            f"fills_closed={arm['fills_closed']:4d} pnl={arm['realised_pnl']:.4f}"
        )
        top = list(arm["rejection_reasons"].items())[:3]
        for reason, count in top:
            print(f"[paper-exec]     {count:5d}  {reason}")
    print(f"[paper-exec] wrote {OUT / 'PAPER_EXECUTION_EVIDENCE.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
