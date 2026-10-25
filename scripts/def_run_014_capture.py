"""DEF-RUN-014 — captura del ledger del lane de visión para verificación independiente.

Corre ``VisionLane`` (el runtime de paper del bot visual) sobre barras deterministas con
tres decisiones guionizadas y deja el JSONL que ``scripts/def_run_verify.py`` vuelve a
recalcular sin importar ``lane.py`` ni ``manager.py``:

* ``WIDE``  — stop 1.0 % (100 bps): limpia el coste de ida y vuelta y se ejecuta;
* ``TIGHT`` — stop 0.2 % (20 bps): está dentro de la ida y vuelta y debe ser ``NO_TRADE``;
* ``NOSTOP``— ``LONG`` sin stop: el contrato del modelo lo rechaza en el parseo, así que
  el fallback silencioso de la política **no es alcanzable** desde el bot visual. Ese
  camino sigue existiendo para otras estrategias y está cubierto por el test del
  ``RiskManager`` (``POLICY_DEFAULT``).

Uso:
    python scripts/def_run_014_capture.py --out reports/ai-bots/RFC-DEF-RUN-014/evidence
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.provider import ReplayProvider, VisionResponse  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402

SYMBOL = "BTC/USDT"
HOUR_MS = 3_600_000
START_MS = int(datetime(2026, 10, 19, tzinfo=UTC).timestamp() * 1000)


def _answer(symbol: str, action: str, stop: float | None, take: float | None) -> str:
    stop_json = "null" if stop is None else f"{stop}"
    take_json = "null" if take is None else f"{take}"
    return (
        f'{{"schema_version":"ai-vision-decision/1","symbol":"{symbol}","action":"{action}",'
        f'"confidence":0.6,"horizon_bars":6,"stop_loss_pct":{stop_json},'
        f'"take_profit_pct":{take_json},"invalidation":null,'
        '"rationale":"DEF-RUN-014 capture."}'
    )


class Scripted(ReplayProvider):
    def __init__(self, action: str, stop: float | None, take: float | None) -> None:
        self.action = action
        self.stop = stop
        self.take = take
        self.seen = 0
        super().__init__(self._script)

    def _script(self, request: Any) -> str:
        self.seen += 1
        action = self.action if self.seen == 1 else "NO_TRADE"
        stop = self.stop if action != "NO_TRADE" else None
        take = self.take if action != "NO_TRADE" else None
        return _answer(request.chart.symbol, action, stop, take)

    def analyze(self, request: Any) -> VisionResponse:
        return replace(super().analyze(request), latency_ms=0)


def _bars(path: list[tuple[float, float]]) -> list[Bar]:
    out: list[Bar] = []
    for index, (opened, closed) in enumerate(path):
        pad = 0.0005
        out.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=opened,
                high=max(opened, closed) * (1.0 + pad),
                low=min(opened, closed) * (1.0 - pad),
                close=closed,
                volume=100.0 + index,
            )
        )
    return out


def _config() -> Any:
    base = load_vision_config(env={})
    return base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1h",
            window_bars=20,
            decision_every_bars=1,
            max_calls_per_run=50,
            max_estimated_spend_usd=1.0,
            data_delay_ms=0,
        ),
    )


FLAT = [(100.0, 100.0)] * 21
UP = [*FLAT, (100.0, 100.2), (100.2, 100.3)]

CASES = (
    ("wide", "LONG", 1.0, 2.0),
    ("tight", "LONG", 0.2, 2.0),
    ("nostop", "LONG", None, None),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-014" / "evidence",
    )
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    policy = load_settings(config_dir=REPO / "config", env_file=None).risk
    report: dict[str, Any] = {
        "schema": "DEF_RUN_014_CAPTURE/1",
        "policy": {
            "default_stop_loss_pct": float(policy.default_stop_loss_pct),
            "default_take_profit_pct": float(policy.default_take_profit_pct),
            "max_risk_per_trade_pct": float(policy.max_risk_per_trade_pct),
            "max_order_notional_usdt": float(policy.max_order_notional_usdt),
        },
        "cases": [],
    }

    for name, action, stop, take in CASES:
        ledger = out / f"LANE_{name.upper()}.jsonl"
        ledger.unlink(missing_ok=True)
        lane = VisionLane(
            series={SYMBOL: _bars(UP)},
            provider=Scripted(action, stop, take),
            config=_config(),
            risk_policy=policy,
            ledger_path=ledger,
            equity=10_000.0,
            book_id=f"def-run-014-{name}",
            decision_every_bars=1,
        )
        summary = lane.run()
        report["cases"].append(
            {
                "case": name,
                "requested_stop_pct": stop,
                "requested_take_profit_pct": take,
                "ledger": ledger.name,
                "fills": summary["fills"],
                "closed_trades": summary["closed_trades"],
                "counters": {
                    key: value
                    for key, value in summary["counters"].items()
                    if key.startswith("risk_blocked") or key.startswith("fills")
                },
            }
        )

    (out / "CAPTURE_SUMMARY.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
