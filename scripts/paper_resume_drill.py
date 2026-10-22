"""paper_resume_drill — mata el proceso, no el libro.

Qué hace, en una frase: corre la misma campaña PAPER dos veces sobre los **mismos minutos
reales** archivados por `roundtrip-5m`, la primera del tirón (A) y la segunda partiéndola
con procesos que mueren a mitad de barrido (B), y exige que las dos dejen el mismo libro.

Por qué así:

* **Los precios son reales.** Las velas de 5 m se agregan de los minutos que el collector
  grabó desde el venue (`market-1m/ETHUSDT.jsonl`, `SOLUSDT.jsonl`, `source=
  binance_spot_rest_1m`). No se inventa un tick.
* **La muerte es real.** B se ejecuta en procesos hijos que se terminan con
  ``TerminateProcess`` (el equivalente Windows de un SIGKILL): no hay ``finally``, no hay
  ``fsync`` de despedida, no hay cierre ordenado. Lo único que sobrevive es lo que ya
  estaba en disco.
* **La comparación es por estado, no por narración.** El criterio es el digest económico
  del libro (`state_digest`) más las filas de cierre y las posiciones abiertas, no un
  recuento de filas de log.

Uso (el padre orquesta; `--child` es interno):

    python scripts/paper_resume_drill.py --out reports/ai-bots/WP-PAPER-RESUME-001/drill

Salidas en `--out`:

    A/RUN.json, B/RUN.json     resúmenes de cada campaña
    A/STATE/BOOK.json          libro continuo
    B/STATE/BOOK.json          libro partido
    DRILL.json                 veredicto + hashes de datos + diferencias exactas
    DRILL.md                   lo mismo, legible

Códigos de salida: 0 el libro coincide, 1 diverge o falta evidencia, 2 no hay archivo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.durable import LaneBookStore  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.prospective import display_symbol  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402
from trading_bot.vision.signal_sources import (  # noqa: E402
    SIGNAL_SOURCE_STRATEGY,
    STRATEGY_EMA_CROSSOVER,
    build_signal_provider,
)

BAR_MS = 5 * 60_000
MINUTE_MS = 60_000
DEFAULT_ARCHIVE = (
    REPO / "reports" / "ai-bots" / "WP-PAPER-ROUNDTRIP-001" / "live" / "roundtrip-5m" / "market-1m"
)
DEFAULT_SYMBOLS = ("ETHUSDT", "SOLUSDT")


# -- datos ----------------------------------------------------------------------


def load_bars(archive: Path, symbol: str) -> list[Bar]:
    """Minutos reales del archivo → velas de 5 m, sólo grupos completos.

    Un grupo incompleto no es una vela: agregar cuatro minutos y llamarlo 5 m inventaría un
    cierre que nadie observó. Los grupos incompletos se cuentan y se declaran.
    """
    path = archive / f"{symbol}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: int(row["open_ms"]))
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        opened = int(row["open_ms"])
        used = opened - (opened % MINUTE_MS)
        bucket = used - (used % BAR_MS)
        buckets.setdefault(bucket, []).append({**row, "open_ms": used})
    bars: list[Bar] = []
    for bucket in sorted(buckets):
        minutes = sorted(buckets[bucket], key=lambda row: int(row["open_ms"]))
        expected = [bucket + index * MINUTE_MS for index in range(5)]
        if [int(row["open_ms"]) for row in minutes] != expected:
            continue
        bars.append(
            Bar(
                ts_ms=bucket,
                open=float(minutes[0]["open"]),
                high=max(float(row["high"]) for row in minutes),
                low=min(float(row["low"]) for row in minutes),
                close=float(minutes[-1]["close"]),
                volume=sum(float(row["volume"]) for row in minutes),
            )
        )
    return bars


def series_digest(bars: list[Bar]) -> str:
    payload = [
        [bar.ts_ms, round(bar.open, 8), round(bar.high, 8), round(bar.low, 8), round(bar.close, 8)]
        for bar in bars
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def minutes_digest(archive: Path, symbol: str) -> str:
    digest = hashlib.sha256()
    digest.update((archive / f"{symbol}.jsonl").read_bytes())
    return digest.hexdigest()


# -- una campaña ----------------------------------------------------------------


def run_lane(
    *,
    out: Path,
    series: dict[str, list[Bar]],
    session_id: str,
    stop_at_ms: int | None = None,
) -> dict[str, Any]:
    """Una sesión: un `VisionLane` con libro durable, continuando lo que haya en disco."""
    store = LaneBookStore(out / "STATE")
    book = store.load()
    lock = store.lock(session_id=session_id)
    try:
        truncated = {
            symbol: [bar for bar in bars if stop_at_ms is None or int(bar.ts_ms) <= stop_at_ms]
            for symbol, bars in series.items()
        }
        config = load_vision_config(env={})
        config = config.__class__(
            provider=config.provider,
            lane=config.lane.__class__(
                timeframe="5m",
                window_bars=60,
                decision_every_bars=1,
                max_calls_per_run=500,
                max_estimated_spend_usd=10.0,
                data_delay_ms=0,
            ),
        )
        provider = build_signal_provider(
            SIGNAL_SOURCE_STRATEGY,
            series=truncated,
            timeframe="5m",
            interval_ms=BAR_MS,
            window_bars=60,
            latency_ms=0,
            trace_path=out / f"{session_id}-SIGNAL_TRACE.jsonl",
            mode="PAPER",
            strategy_id=STRATEGY_EMA_CROSSOVER,
        )
        lane = VisionLane(
            series=truncated,
            provider=provider,
            config=config,
            risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
            ledger_path=out / f"{session_id}.jsonl",
            equity=10_000.0,
            book_id="paper-resume-drill",
            decision_every_bars=1,
            book_store=store,
            book=book,
            session_id=session_id,
        )
        summary = lane.run()
        summary = {
            **summary,
            "session_id": session_id,
            "resumed": bool(lane.recovery and lane.recovery.recovered),
            "recovery": None if lane.recovery is None else lane.recovery.to_dict(),
            "stop_at_ms": stop_at_ms,
        }
    finally:
        lock.release()
    sealed = store.load()
    (out / f"{session_id}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return {
        "summary": summary,
        "book_digest": None if sealed is None else sealed.state_digest,
        "integrity_digest": None if sealed is None else sealed.digest,
        "barrier_ms": None if sealed is None else sealed.barrier_ms,
        "open_positions": [] if sealed is None else sealed.open_positions,
        "closed_trades": [] if sealed is None else sealed.closed_trades,
        "session_ids": [] if sealed is None else list(sealed.body.get("session_ids") or []),
        "bars_committed": 0
        if sealed is None
        else int((sealed.body.get("barrier") or {}).get("bars_committed") or 0),
    }


# -- el padre -------------------------------------------------------------------


def _spawn_child(args: list[str], kill_after: float | None) -> dict[str, Any]:
    #: Rutas absolutas antes de cruzar la frontera de proceso: un "/tmp" de bash no es
    #: el mismo sitio para un Python de Windows, y el padre acabaría leyendo otro libro.
    command = [sys.executable, str(Path(__file__).resolve()), *args]
    started = time.time()
    process = subprocess.Popen(command, cwd=str(REPO))
    killed = False
    if kill_after is not None:
        try:
            process.wait(timeout=kill_after)
        except subprocess.TimeoutExpired:
            process.kill()  # TerminateProcess: sin finally, sin limpieza
            killed = True
            process.wait(timeout=60)
    code = process.wait(timeout=600)
    return {
        "args": args,
        "exit_code": code,
        "killed": killed,
        "seconds": round(time.time() - started, 1),
    }


def _summarise(label: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "state_digest": state["book_digest"],
        "integrity_digest": state["integrity_digest"],
        "barrier_ms": state["barrier_ms"],
        "bars_committed": state["bars_committed"],
        "sessions": state["session_ids"],
        "open_positions": state["open_positions"],
        "closed_trades": state["closed_trades"],
    }


def _compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    differences: list[str] = []
    if a["state_digest"] != b["state_digest"]:
        differences.append(
            f"state_digest A={a['state_digest']} B={b['state_digest']}"
        )
    for field in ("barrier_ms", "bars_committed"):
        if a[field] != b[field]:
            differences.append(f"{field} A={a[field]} B={b[field]}")
    if len(a["closed_trades"]) != len(b["closed_trades"]):
        differences.append(
            f"closed_trades A={len(a['closed_trades'])} B={len(b['closed_trades'])}"
        )
    for index, (left, right) in enumerate(zip(a["closed_trades"], b["closed_trades"], strict=False)):
        for key in ("position_id", "trade_id", "entry_price", "exit_price", "pnl", "exit_reason"):
            if left.get(key) != right.get(key):
                differences.append(f"close[{index}].{key} A={left.get(key)} B={right.get(key)}")
    if len(a["open_positions"]) != len(b["open_positions"]):
        differences.append(
            f"open_positions A={len(a['open_positions'])} B={len(b['open_positions'])}"
        )
    for index, (left, right) in enumerate(zip(a["open_positions"], b["open_positions"], strict=False)):
        for key in ("position_id", "symbol", "side", "entry_price", "quantity", "stop_loss_pct"):
            if left.get(key) != right.get(key):
                differences.append(f"open[{index}].{key} A={left.get(key)} B={right.get(key)}")
    return {"ok": not differences, "differences": differences}


def main() -> int:
    parser = argparse.ArgumentParser(description="crash/recovery drill for the PAPER book")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=REPO / "reports" / "ai-bots" / "WP-PAPER-RESUME-001" / "drill")
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--kill-after", type=float, default=12.0)
    parser.add_argument("--children", type=int, default=3)
    # modo hijo (interno)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--child-out", type=Path, default=None)
    parser.add_argument("--child-session", default="child")
    parser.add_argument("--stop-at-ms", type=int, default=None)
    args = parser.parse_args()
    #: Absolutas antes de cruzar la frontera de proceso: un `/tmp` de bash no es el
    #: mismo sitio para un Python de Windows, y el padre acabaría leyendo otro libro.
    args.archive = args.archive.resolve()
    args.out = args.out.resolve()
    if args.child_out is not None:
        args.child_out = args.child_out.resolve()

    if not (args.archive / f"{args.symbols[0]}.jsonl").exists():
        print(f"ARCHIVE_MISSING {args.archive}", file=sys.stderr)
        return 2

    #: El venue habla ETHUSDT; el lane habla ETH/USDT. La conversión no es cosmética:

    #: el símbolo viaja en la decisión y un contrato que no lo reconoce la rechaza.

    bars = {display_symbol(symbol): load_bars(args.archive, symbol) for symbol in args.symbols}
    if args.child:
        assert args.child_out is not None
        result = run_lane(
            out=args.child_out,
            series=bars,
            session_id=args.child_session,
            stop_at_ms=args.stop_at_ms,
        )
        print(json.dumps({"ok": True, "book_digest": result["book_digest"]}))
        return 0

    out: Path = args.out
    a_dir = out / "A"
    b_dir = out / "B"
    #: Un drill que hereda libros de la corrida anterior no mide nada: el hijo ve la barrera
    #: ya en la última vela, sale limpio en segundos y el A/B compara un libro viejo consigo
    #: mismo. Se borra lo que este script escribe y sólo eso.
    for directory in (a_dir, b_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    common = ["--archive", str(args.archive), "--out", str(out), "--symbols", *args.symbols]
    children: list[dict[str, Any]] = []

    # A — la campaña del tirón.
    a_state = run_lane(out=a_dir, series=bars, session_id="A-continuous")
    a = _summarise("A", a_state)

    # B — la misma campaña, partida por procesos que mueren.
    last_bar = max(int(bar.ts_ms) for symbol in bars for bar in bars[symbol])
    b_state: dict[str, Any] | None = None
    for index in range(1, args.children + 1):
        #: Los hijos impares se matan a mitad; los pares salen limpios entre dos velas, que
        #: es el otro borde que el contrato tiene que cubrir.
        hard = index % 2 == 1
        child_args = [
            *common,
            "--child",
            "--child-out",
            str(b_dir),
            "--child-session",
            f"B-{index}",
        ]
        outcome = _spawn_child(child_args, kill_after=args.kill_after if hard else None)
        children.append(outcome)
        sealed = LaneBookStore(b_dir / "STATE").load()
        if sealed is not None and sealed.barrier_ms == last_bar:
            break
    sealed = LaneBookStore(b_dir / "STATE").load()
    if sealed is None:
        print("B_WROTE_NO_BOOK", file=sys.stderr)
        return 1
    b_state = {
        "book_digest": sealed.state_digest,
        "integrity_digest": sealed.digest,
        "barrier_ms": sealed.barrier_ms,
        "bars_committed": int((sealed.body.get("barrier") or {}).get("bars_committed") or 0),
        "open_positions": sealed.open_positions,
        "closed_trades": sealed.closed_trades,
        "session_ids": list(sealed.body.get("session_ids") or []),
    }
    b = _summarise("B", b_state)

    comparison = _compare(a, b)
    #: El veredicto exige que el kill haya ocurrido de verdad. Un A/B donde el hijo sale
    #: limpio antes del plazo compara una campaña continua consigo misma y no prueba la
    #: reanudación, por más que los digests coincidan.
    killed = any(item["killed"] for item in children)
    verdict_ok = comparison["ok"] and len(b["sessions"]) > 1 and killed
    document = {
        "schema": "PAPER_RESUME_DRILL_V1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "PAPER",
        "live_enabled": False,
        "live_orders": 0,
        "commit": _git_commit(),
        "data": {
            "archive": str(args.archive.relative_to(REPO)) if args.archive.is_relative_to(REPO) else str(args.archive),
            "source": "archived 1m minutes recorded from the venue (binance_spot_rest_1m)",
            "symbols": {
                symbol: {
                    "venue_symbol": display_symbol(symbol),
                    "minutes_sha256": minutes_digest(args.archive, symbol),
                    "bars_5m": len(lane_bars),
                    "first_bar_utc": _iso(int(lane_bars[0].ts_ms)),
                    "last_bar_utc": _iso(int(lane_bars[-1].ts_ms)),
                    "bars_sha256": series_digest(lane_bars),
                }
                for symbol, lane_bars in ((s, bars[display_symbol(s)]) for s in args.symbols)
            },
        },
        "children": children,
        "A": a,
        "B": b,
        "comparison": comparison,
        "verdict": "PASS" if verdict_ok else "FAIL",
        "criteria": {
            "RT-07": "PASS" if comparison["ok"] and len(b["sessions"]) > 1 else "FAIL",
            "REC-04": "PASS" if killed else "NOT_EXERCISED",
            "REC-05": "PASS" if comparison["ok"] else "FAIL",
            "REC-03": "PASS"
            if len({row["position_id"] for row in b["closed_trades"]}) == len(b["closed_trades"])
            else "FAIL",
        },
    }
    if not comparison["ok"] and len(b["sessions"]) <= 1:
        document["note"] = "B never restarted: the drill proved nothing"
    elif not killed:
        document["note"] = (
            "no child was killed: B never survived a hard stop, so the A/B did not exercise "
            "the recovery it claims to measure"
        )
    (out / "DRILL.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "DRILL.md").write_text(_markdown(document), encoding="utf-8")
    print(json.dumps({"verdict": document["verdict"], **document["criteria"]}))
    return 0 if document["verdict"] == "PASS" else 1


def _iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000.0))


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _markdown(document: dict[str, Any]) -> str:
    a, b = document["A"], document["B"]
    lines = [
        "# PAPER RESUME DRILL — A/B sobre minutos reales",
        "",
        f"- commit: `{document['commit']}`",
        f"- modo: `{document['mode']}` · live_orders: {document['live_orders']}",
        f"- archivo: `{document['data']['archive']}`",
        f"- veredicto: **{document['verdict']}**",
        "",
        "| | A (continua) | B (interrumpida) |",
        "| --- | --- | --- |",
        f"| state_digest | `{(a['state_digest'] or '')[:16]}` | `{(b['state_digest'] or '')[:16]}` |",
        f"| barrera (ms) | {a['barrier_ms']} | {b['barrier_ms']} |",
        f"| velas comprometidas | {a['bars_committed']} | {b['bars_committed']} |",
        f"| sesiones | {len(a['sessions'])} | {len(b['sessions'])} |",
        f"| cierres | {len(a['closed_trades'])} | {len(b['closed_trades'])} |",
        f"| posiciones abiertas | {len(a['open_positions'])} | {len(b['open_positions'])} |",
        "",
        "## Hijos",
        "",
    ]
    for child in document["children"]:
        lines.append(
            f"- `{child['args'][-1]}` exit={child['exit_code']} "
            f"killed={child['killed']} {child['seconds']}s"
        )
    lines += ["", "## Diferencias", ""]
    lines += [f"- {item}" for item in document["comparison"]["differences"]] or ["- ninguna"]
    lines += ["", "## Criterios", ""]
    for key, value in document["criteria"].items():
        lines.append(f"- {key}: **{value}**")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
