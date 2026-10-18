"""ai_bots_003c_capture — corre el carril 003C sobre datos reales y publica los recibos.

Este script es el **constructor**: ejecuta ``VisionLane.run`` con el ``RiskManager`` y el
``PaperBroker`` de producción sobre OHLC real de Binance ya capturado en el repo, y deja
los artefactos que el verificador independiente leerá. No decide nada por su cuenta: la
fase de cada fila la escribe el carril, y aquí sólo se proyecta y se cuenta.

Qué produce, por escenario:

* ``evidence/<escenario>_ledger.jsonl`` — la cadena real, con hashes;
* ``evidence/<escenario>_summary.json`` — el resumen que el carril devolvió;
* ``PIT_OPEN_EVENT_TRACE.jsonl`` — las filas con fase (OPEN_GAP, OPEN_ENTRY, INTRABAR,
  DECISION) en su orden real dentro de cada instante;
* ``DATA_COVERAGE_LEDGER.jsonl`` — por símbolo: la rejilla declarada, las barras que
  existen, las que faltan y las filas que reaccionaron a cada hueco;
* ``RISK_NET_RECONCILIATION.json`` — la reconciliación del resumen y el rastro de riesgo
  de cada cierre (equidad antes/después, día y semana).

Uso:

    .venv/Scripts/python scripts/ai_bots_003c_capture.py [--out DIR] [--bars N] [--every N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import read_entries, verify_chain  # noqa: E402
from trading_bot.vision.provider import ReplayProvider, VisionResponse  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402

DATA_DIR = REPO / "data" / "edge08" / "universe-1h"
DEFAULT_OUT = REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-003" / "BLOCK-C"
HOUR_MS = 3_600_000
#: Dos activos reales distintos, uno largo y otro corto, para que la simetría de la
#: causalidad (stop de compra y stop de venta) quede ejercitada por el mismo motor.
SYMBOLS: dict[str, str] = {"UNIUSDT": "UNI/USDT", "AAVEUSDT": "AAVE/USDT"}
#: El guion no es un modelo: recorre las ramas para que la fontanería se vea trabajar.
#: Todo lo que produce queda etiquetado ``provider=replay`` en la fila RUN.
CYCLE: dict[str, tuple[str, ...]] = {
    "UNI/USDT": ("LONG", "LONG", "LONG", "CLOSE", "LONG", "NO_TRADE"),
    "AAVE/USDT": ("SHORT", "SHORT", "SHORT", "CLOSE", "SHORT", "NO_TRADE"),
}

ANSWER = (
    '{{"schema_version":"ai-vision-decision/1","symbol":"{symbol}","action":"{action}",'
    '"confidence":0.6,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":1.5,'
    '"invalidation":null,"rationale":"Scripted plumbing, not a model view."}}'
)


# ------------------------------------------------------------------ data


def load_bars(symbol: str, *, bars: int, start_monday: bool = True) -> list[Bar]:
    """Serie real de Binance 1h, recortada para empezar en un lunes 00:00 UTC."""

    rows = json.loads((DATA_DIR / f"{symbol}_2021_2026_1h.json").read_text(encoding="utf-8"))
    parsed = [
        Bar(
            ts_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
    ]
    offset = 0
    if start_monday:
        for index, bar in enumerate(parsed):
            stamp = datetime.fromtimestamp(bar.ts_ms / 1000.0, tz=UTC)
            if stamp.weekday() == 0 and stamp.hour == 0:
                offset = index
                break
    window = parsed[offset : offset + bars]
    if len(window) < bars:
        raise SystemExit(f"{symbol}: only {len(window)} bars available from the offset")
    return window


def flat_series(
    *, count: int, start_ms: int, patches: dict[int, Callable[[float], tuple[float, float, float, float]]]
) -> list[Bar]:
    """Serie plana construida, con parches explícitos: el instrumento del hueco.

    No es un dato de mercado y no se presenta como tal: ``synthetic_gap_open`` la usa
    sólo porque el hueco de apertura **no existe** en este dataset real (el mayor salto
    cierre->apertura en 3000 barras de UNI y AAVE es de 0,30 %, y ninguna de las 426
    entradas de la medida se detuvo en una apertura). Sin esta serie, el camino
    ``OPEN_GAP`` no tendría ningún recibo publicado, y un camino sin recibo es un camino
    que nadie ha visto funcionar.
    """

    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        shape = patches.get(index)
        opened, high, low, close = (
            shape(price) if shape is not None else (price, price * 1.001, price * 0.999, price)
        )
        bars.append(
            Bar(
                ts_ms=start_ms + index * HOUR_MS,
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
        price = close
    return bars


def series_digest(bars: list[Bar]) -> str:
    payload = json.dumps(
        [[int(b.ts_ms), float(b.open), float(b.high), float(b.low), float(b.close)] for b in bars],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ------------------------------------------------------------------ provider


class ScriptedTransport(ReplayProvider):
    """Transporte determinista con latencia declarada por corrida."""

    def __init__(self, *, latency_ms: int, cycles: dict[str, tuple[str, ...]]) -> None:
        super().__init__(self._answer)
        self._latency_ms = latency_ms
        self._cycles = cycles
        #: ``ReplayProvider`` already owns ``_calls`` (the list of requests), so the
        #: per-symbol counter needs its own name.
        self._seen: dict[str, int] = {}

    def _answer(self, request: Any) -> str:
        symbol = str(request.chart.symbol)
        cycle = self._cycles[symbol]
        seen = self._seen.get(symbol, 0)
        self._seen[symbol] = seen + 1
        return ANSWER.format(symbol=symbol, action=cycle[seen % len(cycle)])

    def analyze(self, request: Any) -> VisionResponse:
        return replace(super().analyze(request), latency_ms=self._latency_ms)


# ------------------------------------------------------------------ scenarios


def run_scenario(
    *,
    out_dir: Path,
    name: str,
    bars: int,
    every: int,
    latency_ms: int,
    drop_expected_bar: bool,
    policy_override: dict[str, float] | None = None,
) -> dict[str, Any]:
    series = {display: load_bars(raw, bars=bars) for raw, display in SYMBOLS.items()}
    declared = {display: len(bars_list) for display, bars_list in series.items()}
    removed: dict[str, int] = {}
    if drop_expected_bar:
        # La primera decisión cae en ``window_bars - 1`` redondeado a la cadencia, y su
        # relleno esperado es la barra siguiente. Quitarla deja el hueco exactamente en el
        # camino de la opinión: con latencia cero, y con 900 ms, la barra esperada es la
        # misma, así que el mismo hoyo se ve desde las dos corridas.
        target = ((120 - 1) // every + 1) * every + 1
        for symbol, bars_list in series.items():
            if 0 < target < len(bars_list):
                removed[symbol] = int(bars_list[target].ts_ms)
                series[symbol] = [
                    bar for index, bar in enumerate(bars_list) if index != target
                ]

    base = load_vision_config(env={})
    lane_config = base.lane.__class__(
        timeframe="1h",
        window_bars=120,
        decision_every_bars=every,
        max_calls_per_run=500,
        max_estimated_spend_usd=5.0,
    )
    config = base.__class__(provider=base.provider, lane=lane_config)
    policy = load_settings(config_dir=REPO / "config", env_file=None).risk
    #: A scenario-local override, never a change to ``config/risk.yaml``: the canonical
    #: policy stop (0.5 %) is closer than one hourly bar's range, so a position is almost
    #: always stopped inside the bar it was opened on and the open-gap path is
    #: unreachable. A wider stop is the only way to *exercise* that path on real data, and
    #: it is declared on every row that uses it.
    if policy_override:
        policy = policy.model_copy(update=policy_override)
    ledger_path = out_dir / "evidence" / f"{name}_ledger.jsonl"
    summary_path = out_dir / "evidence" / f"{name}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    #: One ledger is one run. ``DecisionLedger.open`` continues an existing chain, so a
    #: second capture into the same path would hide two runs inside one file and every
    #: "this run" check would silently become "these runs".
    ledger_path.unlink(missing_ok=True)

    lane = VisionLane(
        series=series,
        provider=ScriptedTransport(latency_ms=latency_ms, cycles=CYCLE),
        config=config,
        risk_policy=policy,
        ledger_path=ledger_path,
        book_id=f"ai-vision-paper-003c-{name}",
    )
    summary = lane.run()
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = read_entries(ledger_path)
    kinds = [line["entry"].get("kind") for line in rows]
    if kinds.count("RUN") != 1 or kinds.count("RUN_END") != 1:
        raise SystemExit(
            f"{name}: the ledger must hold exactly one run, found "
            f"RUN={kinds.count('RUN')} RUN_END={kinds.count('RUN_END')}"
        )
    return {
        "name": name,
        "ledger": ledger_path,
        "latency_ms": latency_ms,
        "book_id": lane.book_id,
        "summary": summary,
        "rows": rows,
        "declared_bars": declared,
        "removed_bar_open_ms": removed,            "series": series,
            "policy_override": policy_override,
            "chain": verify_chain(ledger_path),
    }


class ShapeTransport(ReplayProvider):
    """Responde según ``(símbolo, instante de la decisión)``, sin latencia."""

    def __init__(self, script: Callable[[str, int], str]) -> None:
        super().__init__(lambda request: script(request.chart.symbol, int(request.decision_ts_ms)))


def run_synthetic_scenario(*, out_dir: Path, name: str) -> dict[str, Any]:
    """El hueco de apertura, con la misma fontanería que la corrida real.

    Un activo entra al OPEN de la barra 20 y su stop queda al 1 %; en la barra 72 la
    apertura salta el 3 %. La propuesta del segundo activo se forma en el cierre de la
    71, así que su relleno y el hueco comparten instante: es el escenario C-01 del WP,
    ejecutado de punta a punta para que el verificador independiente lo lea del ledger.
    """

    start = int(datetime(2026, 3, 2, tzinfo=UTC).timestamp() * 1000)  # Monday 00:00 UTC
    gap_index = 72

    def gapped(natural: float) -> tuple[float, float, float, float]:
        opened = natural * 0.97
        return (opened, opened * 1.001, opened * 0.999, opened)

    series = {
        "BTC/USDT": flat_series(count=gap_index + 4, start_ms=start, patches={gap_index: gapped}),
        "ETH/USDT": flat_series(count=gap_index + 4, start_ms=start, patches={gap_index: gapped}),
    }

    def script(symbol: str, decision_ts_ms: int) -> str:
        action = "LONG"
        if symbol == "ETH/USDT" and decision_ts_ms != start + gap_index * HOUR_MS:
            action = "NO_TRADE"
        return ANSWER.format(symbol=symbol, action=action)

    base = load_vision_config(env={})
    lane_config = base.lane.__class__(
        timeframe="1h",
        window_bars=20,
        decision_every_bars=1,
        max_calls_per_run=500,
        max_estimated_spend_usd=5.0,
    )
    config = base.__class__(provider=base.provider, lane=lane_config)
    override = {"max_daily_loss_pct": 0.05}
    policy = load_settings(config_dir=REPO / "config", env_file=None).risk.model_copy(
        update=override
    )
    ledger_path = out_dir / "evidence" / f"{name}_ledger.jsonl"
    ledger_path.unlink(missing_ok=True)
    lane = VisionLane(
        series=series,
        provider=ShapeTransport(script),
        config=config,
        risk_policy=policy,
        ledger_path=ledger_path,
        book_id=f"ai-vision-paper-003c-{name}",
    )
    summary = lane.run()
    (out_dir / "evidence" / f"{name}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = read_entries(ledger_path)
    kinds = [line["entry"].get("kind") for line in rows]
    if kinds.count("RUN") != 1 or kinds.count("RUN_END") != 1:
        raise SystemExit(f"{name}: the ledger must hold exactly one run")
    return {
        "name": name,
        "ledger": ledger_path,
        "latency_ms": 0,
        "book_id": lane.book_id,
        "summary": summary,
        "rows": rows,
        "declared_bars": {symbol: len(bars) for symbol, bars in series.items()},
        "removed_bar_open_ms": {},
        "series": series,
        "policy_override": override,
        "synthetic": True,
        "chain": verify_chain(ledger_path),
    }


# ------------------------------------------------------------------ artefacts


def pit_trace(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Las filas con fase, en el orden real en que el carril las escribió."""

    out: list[dict[str, Any]] = [
        {
            "kind": "TRACE_HEADER",
            "source": "ledger 'phase' field written by VisionLane",
            "order": "ledger seq, never recomputed",
            "scenarios": [run["name"] for run in runs],
        }
    ]
    for run in runs:
        for line in run["rows"]:
            entry = line["entry"]
            if not entry.get("phase"):
                continue
            out.append(
                {
                    "scenario": run["name"],
                    "seq": line["seq"],
                    "ts_ms": entry.get("ts_ms"),
                    "phase": entry["phase"],
                    "kind": entry["kind"],
                    "symbol": entry.get("symbol"),
                    "code": entry.get("code"),
                    "intent": entry.get("intent"),
                    "exit_reason": entry.get("exit_reason"),
                    "exit_ts_resolution": entry.get("exit_ts_resolution"),
                    "gap_price_source": entry.get("gap_price_source"),
                    "data_gap_covered_by": entry.get("data_gap_covered_by"),
                    "risk_blocked_by": entry.get("risk_blocked_by"),
                }
            )
    return out


def coverage_ledger(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por símbolo y escenario: la rejilla declarada frente a la que existe."""

    out: list[dict[str, Any]] = []
    for run in runs:
        for symbol, bars in run["series"].items():
            stamps = sorted(int(bar.ts_ms) for bar in bars)
            step = HOUR_MS
            expected = list(range(stamps[0], stamps[-1] + step, step))
            missing = sorted(set(expected) - set(stamps))
            gap_rows = [
                {
                    "seq": line["seq"],
                    "kind": line["entry"]["kind"],
                    "code": line["entry"].get("code"),
                    "ts_ms": line["entry"].get("ts_ms"),
                    "decision_seq": line["entry"].get("decision_seq"),
                    "detail": line["entry"].get("detail"),
                }
                for line in run["rows"]
                if line["entry"].get("symbol") == symbol
                and line["entry"].get("code")
                in {"DATA_GAP", "NO_EXECUTABLE_PRICE", "STALE_VALUATION", "NO_QUOTE_AT_BAR"}
            ]
            out.append(
                {
                    "scenario": run["name"],
                    "synthetic": bool(run.get("synthetic")),
                    "symbol": symbol,
                    "declared_bars": run["declared_bars"][symbol],
                    "observed_bars": len(stamps),
                    "step_ms": step,
                    "first_open_ms": stamps[0],
                    "last_open_ms": stamps[-1],
                    "missing_bar_opens_ms": missing,
                    "missing_bar_opens_utc": [
                        datetime.fromtimestamp(value / 1000.0, tz=UTC).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                        for value in missing
                    ],
                    "removed_bar_open_ms": run["removed_bar_open_ms"].get(symbol),
                    "reaction_rows": gap_rows,
                    "dataset_sha256": series_digest(list(bars)),
                }
            )
    return out


def risk_reconciliation(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """La reconciliación del carril, más el rastro de riesgo de cada cierre."""

    payload: dict[str, Any] = {
        "note": (
            "builder projection: the summary block is the lane's own, the trail is read "
            "from the ledger rows; the independent verifier recomputes both"
        ),
        "scenarios": {},
    }
    for run in runs:
        payload["scenarios"][run["name"]] = {
            "summary_reconciliation": run["summary"].get("reconciliation"),
            "summary_execution": run["summary"].get("execution"),
            "closes": [
                {
                    "seq": line["seq"],
                    "trade_id": close.get("trade_id"),
                    "position_id": close.get("position_id"),
                    "symbol": close.get("symbol"),
                    "side": close.get("side"),
                    "exit_reason": close.get("exit_reason"),
                    "phase": close.get("phase"),
                    "exit_ts_resolution": close.get("exit_ts_resolution"),
                    "gap_open_price": close.get("gap_open_price"),
                    "exit_reference_price": close.get("exit_reference_price"),
                    "ts_ms": close.get("ts_ms"),
                    "pnl_net_usdt": close.get("pnl_net_usdt"),
                    "risk_equity_before": close.get("risk_equity_before"),
                    "risk_equity_after": close.get("risk_equity_after"),
                    "risk_daily_pnl_after": close.get("risk_daily_pnl_after"),
                    "risk_weekly_pnl_after": close.get("risk_weekly_pnl_after"),
                    "day_utc": close.get("day_utc"),
                }
                for line in run["rows"]
                if line["entry"]["kind"] == "CLOSE"
                for close in [line["entry"]]
            ],
        }
    return payload


def git_revision() -> dict[str, Any]:
    def capture(args: list[str]) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
            ).stdout.strip()
        except OSError:  # pragma: no cover - git missing
            return ""

    return {
        "branch": capture(["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": capture(["rev-parse", "HEAD"]),
        "dirty_paths": len(capture(["status", "--porcelain"]).splitlines()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture an AI-BOTS-003C paper run")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--bars", type=int, default=960)
    parser.add_argument("--every", type=int, default=24)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evidence").mkdir(parents=True, exist_ok=True)

    runs = [
        run_scenario(
            out_dir=out_dir,
            name="real_900ms",
            bars=args.bars,
            every=args.every,
            latency_ms=900,
            drop_expected_bar=False,
        ),
        run_scenario(
            out_dir=out_dir,
            name="real_900ms_wide_stop",
            bars=args.bars,
            every=args.every,
            latency_ms=900,
            drop_expected_bar=False,
            policy_override={"default_stop_loss_pct": 2.0, "default_take_profit_pct": 3.0},
        ),
        run_scenario(
            out_dir=out_dir,
            name="real_0ms",
            bars=args.bars,
            every=args.every,
            latency_ms=0,
            drop_expected_bar=False,
        ),
        run_scenario(
            out_dir=out_dir,
            name="real_900ms_hole",
            bars=args.bars,
            every=args.every,
            latency_ms=900,
            drop_expected_bar=True,
        ),
        run_synthetic_scenario(out_dir=out_dir, name="synthetic_gap_open"),
    ]

    def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )

    write_jsonl(out_dir / "PIT_OPEN_EVENT_TRACE.jsonl", pit_trace(runs))
    write_jsonl(out_dir / "DATA_COVERAGE_LEDGER.jsonl", coverage_ledger(runs))
    (out_dir / "RISK_NET_RECONCILIATION.json").write_text(
        json.dumps(risk_reconciliation(runs), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    capture_report = {
        "tool": "ai_bots_003c_capture",
        "python": platform.python_version(),
        "git": git_revision(),
        "bars": args.bars,
        "decision_every_bars": args.every,
        "window_bars": 120,
        "provider": "replay (scripted transport; NOT a model)",
        "real_model_called": False,
        "prospective_paper_validated": False,
        "scenarios": [
            {
                "name": run["name"],
                "latency_ms": run["latency_ms"],
                "synthetic_dataset": bool(run.get("synthetic")),
                "ledger": str(run["ledger"].relative_to(out_dir)),
                "chain": run["chain"],
                "fills": run["summary"]["fills"],
                "closed_trades": run["summary"]["closed_trades"],
                "net_realised_usdt": run["summary"]["net_realised_usdt"],
                "gap_exits": run["summary"]["execution"]["gap_exits"],
                "policy_override": run["policy_override"],
                "counters": run["summary"]["counters"],
                "identities": run["summary"]["reconciliation"]["identities"],
            }
            for run in runs
        ],
    }
    (out_dir / "CAPTURE.json").write_text(
        json.dumps(capture_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(capture_report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
