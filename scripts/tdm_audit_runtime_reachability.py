"""WP-TDM-00 — prove which modules the PAPER runtime actually reaches.

Runs the canonical entrypoint (``scripts/autonomous_paper.py``) in-process for
a bounded number of cycles and records ``sys.modules`` before/after, so the
authority map in ``reports/trading-decision-monitor/preflight/`` is backed by
runtime evidence instead of a name-based guess.

    python scripts/tdm_audit_runtime_reachability.py \
        --provider fake --cycles 1 --assets BTC,ETH \
        --out reports/trading-decision-monitor/preflight/runtime_reachability.json

Read-only with respect to trading decisions: the runtime does exactly what it
would do in a normal PAPER run (including writing its own run artifacts into
``--run-root``); this tool only observes which modules were imported.
"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Modules that must be loaded for the decision path to be "reachable".
_PROBES = {
    "decision_engine": "trading_bot.autonomous.decision",
    "decision_trace": "trading_bot.autonomous.trace",
    "contracts": "trading_bot.autonomous.contracts",
    "runtime": "trading_bot.autonomous.runtime",
    "verifier": "trading_bot.autonomous.verifier",
    "risk_manager": "trading_bot.risk.manager",
    "paper_broker": "trading_bot.paper.broker",
    "reconciliation": "trading_bot.paper.reconciliation_v4",
    "strategy_router": "trading_bot.research.strategy_router",
    "reporter": "trading_bot.autonomous.reporting",
    "desk_event_store": "trading_bot.storage.event_store",
    "dashboard_app": "trading_bot.app",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["fake", "ccxt"], default="fake")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--assets", default="BTC,ETH")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-root", default=".tmp/tdm-reachability/runs")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    run_id = args.run_id or f"reachability-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    before = set(sys.modules)
    sys.argv = [
        "autonomous_paper.py",
        "--cycles",
        str(args.cycles),
        "--assets",
        args.assets,
        "--provider",
        args.provider,
        "--run-id",
        run_id,
        "--run-root",
        str((REPO_ROOT / args.run_root).resolve()),
        "--interval",
        "0",
    ]
    exit_code = 0
    error: str | None = None
    try:
        runpy.run_path(str(REPO_ROOT / "scripts" / "autonomous_paper.py"), run_name="__main__")
    except SystemExit as exc:  # the entrypoint calls raise SystemExit(main())
        exit_code = int(exc.code or 0)
    except Exception as exc:  # pragma: no cover - surfaced, never hidden
        error = f"{type(exc).__name__}: {exc}"
        exit_code = 1

    loaded = sorted(m for m in set(sys.modules) - before if m.startswith("trading_bot"))
    probes = {name: mod in sys.modules for name, mod in _PROBES.items()}
    payload = {
        "schema": "tdm-runtime-reachability-v1",
        "entrypoint": "scripts/autonomous_paper.py",
        "provider": args.provider,
        "cycles": args.cycles,
        "assets": args.assets,
        "run_id": run_id,
        "exit_code": exit_code,
        "error": error,
        "python": sys.version.split()[0],
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "probes": probes,
        "modules_imported": loaded,
        "module_count": len(loaded),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")
        print(f"[tdm-audit] wrote {out}")
        print(f"[tdm-audit] exit_code={exit_code} modules={len(loaded)}")
        for name, present in probes.items():
            print(f"[tdm-audit] {name:<18} {'REACHED' if present else 'NOT_REACHED'}")
        if error:
            print(f"[tdm-audit] ERROR {error}", file=sys.stderr)
        return exit_code
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
