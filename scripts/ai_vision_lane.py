"""ai_vision_lane — the model trades the same book as the deterministic lane.

What makes the comparison fair is that almost nothing is parameterised twice:

* the bars are the same files and the same 2 000-bar window the EDGE-016 lenv uses;
* the broker is the same ``PaperBroker`` with the same ``cost_for`` schedule at 1x;
* the risk engine is the same ``RiskManager`` built from ``config/risk.yaml``;
* the capital is the same 10 000 USDT and the same one-position-per-symbol rule.

What differs is only who decides, and how often: the deterministic machines propose on
every bar, while the model is asked every ``decision_every_bars`` (24 by default, once a
day on 1h bars). That cadence is declared in the evidence and in the comparison, because
a difference in trade count is a difference in opportunity, not only in skill.

    # live: needs VISION_API_KEY in .env
    python scripts/ai_vision_lane.py --mode live

    # replay of recorded answers, keyed by image hash
    python scripts/ai_vision_lane.py --mode replay --fixtures evidence/fixtures.json

Exit codes: 0 run completed, 2 blocked (no credential or no fixtures), 1 error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import load_ohlcv  # noqa: E402
from trading_bot.vision.compare import comparison  # noqa: E402
from trading_bot.vision.lane import PORTFOLIO_EQUITY_USDT, VisionLane  # noqa: E402
from trading_bot.vision.provider import (  # noqa: E402
    FixtureProvider,
    OpenAICompatibleVisionProvider,
    PriceTable,
    load_fixture_answers,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402

OUT = REPO / "reports" / "ai-vision" / "RFC-AI-VISION-001"
UNIVERSE = {
    "BTC/USDT": REPO / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json",
    "ETH/USDT": REPO / "data" / "edge07" / "holdout-1h" / "ETHUSDT_holdout2026.json",
    "SOL/USDT": REPO / "data" / "edge07" / "holdout-1h" / "SOLUSDT_holdout2026.json",
}
WINDOW_BARS = 2_000
BASELINE = REPO / "reports" / "economic-recovery" / "RFC-EDGE-017" / "NET_RISK_REPLAY.json"


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, Any]:
    """The deterministic 1x run, from the published net-risk replay."""
    document = json.loads(path.read_text(encoding="utf-8"))
    run = (document.get("runs") or {}).get("1x")
    if run is None:
        raise SystemExit(f"{path} has no runs.1x; refusing to compare against nothing")
    return {
        "fills": int(run.get("fills", 0)),
        "net_realised_usdt": float(run.get("net_realised_usdt", 0.0)),
        "drawdown_pct": run.get("drawdown_pct"),
        "start_equity_usdt": float((document.get("baseline") or {}).get("equity", 10_000.0)),
        "source": str(path.relative_to(REPO)),
        "cost_model": "cost_for net, 1x",
    }


def build_provider(mode: str, config, fixtures: Path | None):
    if mode == "replay":
        if fixtures is None or not fixtures.exists():
            return None, "REPLAY_REQUIRES_FIXTURES", (
                "replay mode needs a fixtures file of answers recorded from a real run; "
                "without it there is no model to replay"
            )
        return FixtureProvider(load_fixture_answers(fixtures)), None, None

    api_key = config.api_key(os.environ)
    if api_key is None:
        return None, "MISSING_CREDENTIAL", (
            f"set {config.provider.api_key_env} in the repository .env; no decision is "
            "invented in its absence"
        )
    return (
        OpenAICompatibleVisionProvider(
            api_key=api_key,
            model=config.provider.model,
            base_url=config.provider.base_url,
            timeout_s=config.provider.timeout_s,
            max_attempts=config.provider.max_attempts,
            supports_json_object=config.provider.supports_json_object,
            prices=PriceTable(
                input_usd_per_mtok=config.provider.prices.input_usd_per_mtok,
                output_usd_per_mtok=config.provider.prices.output_usd_per_mtok,
                image_tokens_estimate=config.provider.prices.image_tokens_estimate,
            ),
        ),
        None,
        None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="vision lane vs deterministic lane")
    parser.add_argument("--mode", choices=("live", "replay"), default="live")
    parser.add_argument("--fixtures", type=Path, default=None)
    parser.add_argument("--symbols", nargs="*", default=sorted(UNIVERSE))
    parser.add_argument("--bars", type=int, default=WINDOW_BARS)
    parser.add_argument("--decision-every", type=int, default=None)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--tag", default="run")
    args = parser.parse_args()

    out = Path(args.out)
    evidence = out / "evidence" / args.tag
    evidence.mkdir(parents=True, exist_ok=True)

    #: RFC-PAPER-ISOLATION-005: ``replay`` es el runtime paper/offline (fixtures, sin
    #: proveedor externo), así que se aísla antes de construir lane o provider. ``live``
    #: llama a un proveedor de visión por red y queda declarado fuera de la afirmación
    #: de aislamiento, no dentro de ella con una excepción silenciosa.
    if args.mode == "replay":
        from trading_bot.execution import isolation

        isolation.install_for_runtime("paper", log_path=evidence / "isolation_network.jsonl")

    config = load_vision_config(env=os.environ)
    provider, blocked_code, blocked_reason = build_provider(args.mode, config, args.fixtures)
    if provider is None:
        _write(
            evidence / "VISION_LANE_RESULT.json",
            {
                "status": "BLOCKED",
                "code": blocked_code,
                "reason": blocked_reason,
                "mode": args.mode,
                "generated_at_utc": _utc_now(),
                "provider": config.as_public_dict(),
            },
        )
        print(f"[vision-lane] BLOCKED — {blocked_code}: {blocked_reason}")
        return 2

    series = {
        symbol: load_ohlcv(UNIVERSE[symbol])[-args.bars:] for symbol in args.symbols
    }
    policy = load_settings(config_dir=REPO / "config", env_file=None).risk
    lane = VisionLane(
        series=series,
        provider=provider,
        config=config,
        risk_policy=policy,
        ledger_path=evidence / "VISION_DECISIONS.jsonl",
        equity=PORTFOLIO_EQUITY_USDT,
        decision_every_bars=args.decision_every,
    )

    summary = lane.run()
    summary = {
        **summary,
        "mode": args.mode,
        "generated_at_utc": _utc_now(),
        "bars_per_symbol": {symbol: len(bars) for symbol, bars in series.items()},
        "window": {
            "first_open_utc": min(str(bars[0].ts_ms) for bars in series.values()),
            "last_open_utc": max(str(bars[-1].ts_ms) for bars in series.values()),
        },
        "equity_curve_points": len(lane.equity_curve),
    }
    (evidence / "EQUITY_CURVE.json").write_text(
        json.dumps(lane.equity_curve, indent=1) + "\n", encoding="utf-8"
    )

    result: dict[str, Any] = {
        "status": "COMPLETED",
        "mode": args.mode,
        "provider": config.as_public_dict(),
        "summary": summary,
    }

    if BASELINE.exists() and args.mode == "live":
        baseline = load_baseline(BASELINE)
        result["baseline"] = baseline
        result["comparison"] = comparison(
            {
                "net_realised_usdt": summary["net_realised_usdt"],
                "fills": summary["fills"],
                "drawdown_pct": summary["drawdown_pct"],
                "final_equity_usdt": summary["final_equity_usdt"],
                "decisions": summary["calls"],
                "estimated_spend_usd": summary["estimated_spend_usd"],
            },
            baseline,
            same_inputs={
                "bars": True,
                "capital": True,
                "cost_model": True,
                "risk_policy": True,
                "decision_cadence": False,  # declared: 24 bars vs every bar
            },
            caveats=[
                "the deterministic lane proposes on every bar; the model every "
                f"{lane.decision_every} bars, so trade count is not like-for-like",
            ],
        )
    elif args.mode == "replay":
        result["comparison"] = {
            "verdict": "NOT_EVIDENCE",
            "reading": (
                "replayed answers prove the pipeline, not the model. Economic value can "
                "only be claimed from live decisions."
            ),
        }

    _write(evidence / "VISION_LANE_RESULT.json", result)

    comparison_doc = result.get("comparison") or {}
    print(
        f"[vision-lane] {result['status']} mode={args.mode} calls={summary['calls']} "
        f"fills={summary['fills']} closed={summary['closed_trades']} "
        f"net={summary['net_realised_usdt']:+.2f} "
        f"dd={summary['drawdown_pct']} spend=${summary['estimated_spend_usd']:.4f}"
    )
    if comparison_doc.get("verdict"):
        print(f"[vision-lane] verdict={comparison_doc['verdict']}: {comparison_doc.get('reading')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
