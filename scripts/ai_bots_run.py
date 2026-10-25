"""ai_bots_run — ejecuta el A/B offline de los bots y escribe sus recibos.

Uso:

    ./.venv/Scripts/python scripts/ai_bots_run.py --mode mock
    ./.venv/Scripts/python scripts/ai_bots_run.py --mode live      # exige VISION_API_KEY

``mock`` no es una ejecución de modelo: el proveedor es un guion determinista que
recorre LONG / SHORT / NO_TRADE para probar la fontanería (riesgo, broker, costes,
ledger, trazas). Todo lo que produce queda etiquetado ``MOCK_TEST`` y
``economics: NOT_EVIDENCE``. ``live`` exige una clave real; sin ella el script escribe
un RUN_REPORT con estado BLOCKED y sale con código 2, sin inventar decisiones.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.intelligence.ai_bots.bots import (  # noqa: E402
    build_structured_prompt,
    text_only_provider,
)
from trading_bot.intelligence.ai_bots.registry import default_registry  # noqa: E402
from trading_bot.intelligence.ai_bots.runner import run_bot  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.provider import (  # noqa: E402
    OpenAICompatibleVisionProvider,
    VisionRequest,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402

DEFAULT_OUT = REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-002"
DATA_DIR = REPO / "data" / "edge08" / "universe-1h"
DEFAULT_SYMBOLS = ("AAVEUSDT", "UNIUSDT")


# ----------------------------------------------------------------------- datos


def load_bars(symbol: str, *, limit: int) -> list[Bar]:
    """Serie real de Binance 1h ya capturada en el repo (no sintética)."""
    rows = json.loads((DATA_DIR / f"{symbol}_2021_2026_1h.json").read_text(encoding="utf-8"))
    if limit:
        rows = rows[-limit:]
    return [
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


def symbol_label(symbol: str) -> str:
    return f"{symbol[:-4]}/USDT" if symbol.endswith("USDT") else symbol


# ---------------------------------------------------------------------- mock


class MockScript:
    """Guion determinista: recorre las cuatro ramas sin pretender ser un modelo."""

    name = "mock-script"

    def __init__(self, *, send_image: bool = True) -> None:
        self.seen = 0
        self.send_image = send_image

    def analyze(self, request: VisionRequest) -> Any:
        from trading_bot.vision.provider import VisionResponse

        self.seen += 1
        symbol = request.chart.symbol
        action = ("LONG", "NO_TRADE", "SHORT", "NO_TRADE")[(self.seen - 1) % 4]
        payload: dict[str, Any] = {
            "schema_version": "ai-vision-decision/1",
            "symbol": symbol,
            "action": action,
            "confidence": 0.5,
            "horizon_bars": 8,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "rationale": "MOCK scripted answer, not a model opinion.",
        }
        return VisionResponse(
            text=json.dumps(payload),
            model="mock-script",
            provider=self.name,
            request_id=f"mock-{self.seen:05d}",
            latency_ms=0,
            attempts=1,
            image_sha256_in_request=(
                request.chart.sha256 if self.send_image and request.chart.png else ""
            ),
        )


class DeclaredLatency:
    """A mock transport with a declared round trip.

    The mock answers instantly, which would hide the whole point of the causal execution
    engine: with zero latency the fill lands on the very next quote and the waiting path
    is never exercised. This wrapper stamps a round trip the run *declares*, so a paper
    rehearsal shows what a real provider's delay does to fills — and it keeps the
    ``mock-script`` name so no report can ever label the result as a real model call.
    """

    def __init__(self, inner: Any, *, latency_ms: int) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "mock-script")
        self.latency_ms = int(latency_ms)

    def analyze(self, request: VisionRequest) -> Any:
        from dataclasses import replace

        response = self.inner.analyze(request)
        return replace(response, latency_ms=self.latency_ms)


class ManifestProvider:
    """Guarda el PNG exacto que se envía y anota su hash en un manifiesto."""

    def __init__(self, inner: Any, out: Path, *, send_image: bool) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "unknown")
        self.send_image = send_image
        self.dir = out / "snapshots"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rows: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def analyze(self, request: VisionRequest) -> Any:
        chart = request.chart
        image_sent = bool(self.send_image and chart.png)
        if image_sent and chart.sha256 not in self._seen:
            (self.dir / f"{chart.sha256}.png").write_bytes(chart.png)
            self._seen.add(chart.sha256)
        self.rows.append(
            {
                "decision_time_ms": int(request.decision_ts_ms),
                "symbol": getattr(chart, "symbol", ""),
                "image_sha256": chart.sha256 if image_sent else "",
                "image_attached": image_sent,
                "window_bars": chart.bar_count,
                "last_bar_ts_ms": getattr(chart, "last_ts_ms", None),
                "prompt_id": request.prompt.version,
                "prompt_sha256": request.prompt.sha256,
            }
        )
        return self.inner.analyze(request)


# ------------------------------------------------------------------- ejecución


def run_pair(
    *,
    out: Path,
    symbols: tuple[str, ...],
    limit_bars: int,
    spend_usd: float | None,
    decision_every_bars: int | None,
    max_calls: int | None,
    providers: dict[str, Any] | None = None,
    allow_disabled: bool = False,
    latency_ms: int = 0,
) -> dict[str, Any]:
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    config = load_vision_config(env={})
    series = {symbol_label(s): load_bars(s, limit=limit_bars) for s in symbols}
    registry = default_registry(env={"AI_BOTS_ENABLED": "true"})

    results: list[dict[str, Any]] = []
    snapshots = out / "snapshots"
    for bot_id, builder in (
        ("BOT-VIS-01", None),
        ("BOT-CTX-01", build_structured_prompt),
    ):
        bot_dir = out / "runs" / bot_id.lower()
        if bot_dir.exists():
            for stale in bot_dir.glob("*.jsonl"):
                stale.unlink()
        send_image = bot_id == "BOT-VIS-01"
        base = (providers or {}).get(bot_id) or MockScript(send_image=send_image)
        if latency_ms:
            base = DeclaredLatency(base, latency_ms=latency_ms)
        provider = ManifestProvider(base, bot_dir, send_image=send_image)
        summary = run_bot(
            registry=registry,
            bot_id=bot_id,
            series=series,
            provider=provider,
            risk_policy=settings.risk,
            out_dir=bot_dir,
            config=config,
            prompt_builder=builder,
            prompt_version=("aibot-ctx-prompt/1" if builder else "ai-vision-prompt/2"),
            max_spend_usd=spend_usd,
            decision_every_bars=decision_every_bars,
            max_calls=max_calls,
            allow_disabled=allow_disabled,
        )
        #: The lane's own summary, written next to the ledger it describes: the independent
        #: verifier reads both and re-derives every identity from the rows themselves.
        (bot_dir / "SUMMARY.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        manifest = {
            "bot_id": bot_id,
            "run_id": summary["run_id"],
            "image_mode": "png_attached" if send_image else "text_only",
            "prompt_version": (
                "aibot-ctx-prompt/1" if builder else "ai-vision-prompt/2"
            ),
            "snapshots": provider.rows,
        }
        (bot_dir / "VISION_SNAPSHOT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        results.append({"summary": summary, "manifest": manifest})

    if snapshots.exists() and not any(snapshots.iterdir()):
        snapshots.rmdir()
    return {"bot_runs": results, "registry": registry, "series": series, "symbols": symbols}


def benchmark_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in result["bot_runs"]:
        s = run["summary"]
        rows.append(
            {
                "bot_id": s["bot_id"],
                "symbols": "+".join(result["symbols"]),
                "model_status": s["model_status"],
                "prompt_version": s["prompt_version"],
                "calls": s["calls"],
                "fills": s["fills"],
                "closed_trades": s["closed_trades"],
                "net_realised_usdt": s["net_realised_usdt"],
                "gross_realised_usdt": s["gross_realised_usdt"],
                "costs_usdt": s["costs_usdt"],
                "final_equity_usdt": s["final_equity_usdt"],
                "drawdown_pct": s["drawdown_pct"],
                "stop_reason": s["stop_reason"],
                "images_attached": sum(
                    1 for row in run["manifest"]["snapshots"] if row["image_attached"]
                ),
            }
        )
    return rows


def write_benchmark(out: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    path = out / "BOT_BENCHMARK.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI bots offline run")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--limit-bars", type=int, default=1500)
    parser.add_argument("--spend-usd", type=float, default=None)
    parser.add_argument("--decision-every-bars", type=int, default=None)
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument(
        "--latency-ms",
        type=int,
        default=0,
        help=(
            "mock only: declared provider round trip, so the causal execution engine "
            "waits for a real quote instead of filling instantly"
        ),
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()

    registry = default_registry(env={"AI_BOTS_ENABLED": "true"})
    registry.write(out / "BOT_CAPABILITY_REGISTRY.json")

    if args.mode == "live":
        config = load_vision_config()
        key_present = bool(config.api_key())
        text = text_only_provider(config)
        if not key_present or text is None:
            report = {
                "schema_version": "AIBOT_RUN_REPORT_V1",
                "generated_at": stamp,
                "mode": "live",
                "status": "BLOCKED",
                "blocked_reason": "MISSING_CREDENTIAL",
                "detail": "VISION_API_KEY is absent; no multimodal call was made.",
                "real_model_called": False,
                "economics": "NOT_MEASURED",
            }
            (out / "RUN_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            (out / "RUN_REPORT.md").write_text(
                "# AI bots run report\n\n"
                "**STATUS: BLOCKED — MISSING_CREDENTIAL**\n\n"
                "No `VISION_API_KEY` is available in this environment, so no multimodal "
                "request was issued. Nothing in this report is a model result.\n",
                encoding="utf-8",
            )
            print("[ai-bots] BLOCKED — MISSING_CREDENTIAL (no live call was made)")
            return 2
        real_provider = OpenAICompatibleVisionProvider(
            api_key=config.api_key(),
            model=config.provider.model,
            base_url=config.provider.base_url,
            timeout_s=config.provider.timeout_s,
            max_attempts=config.provider.max_attempts,
            supports_json_object=config.provider.supports_json_object,
        )
        # El proveedor real se usa para ambas rutas: la visual adjunta PNG y la
        # estructurada pasa por ``TextOnlyVisionProvider`` con el mismo endpoint.
        result = run_pair(
            out=out,
            symbols=tuple(args.symbols),
            limit_bars=args.limit_bars,
            spend_usd=args.spend_usd,
            decision_every_bars=args.decision_every_bars,
            max_calls=args.max_calls,
            providers={"BOT-VIS-01": real_provider, "BOT-CTX-01": text},
        )
    else:
        result = run_pair(
            out=out,
            symbols=tuple(args.symbols),
            limit_bars=args.limit_bars,
            spend_usd=args.spend_usd,
            decision_every_bars=args.decision_every_bars,
            max_calls=args.max_calls,
            allow_disabled=args.mode == "mock",
            latency_ms=args.latency_ms if args.mode == "mock" else 0,
        )

    rows = benchmark_rows(result)
    write_benchmark(out, rows)
    report = {
        "schema_version": "AIBOT_RUN_REPORT_V1",
        "generated_at": stamp,
        "mode": args.mode,
        "status": "EXECUTED",
        "real_model_called": args.mode == "live",
        "data": {
            "source": "data/edge08/universe-1h (Binance 1h, committed)",
            "symbols": result["symbols"],
            "limit_bars": args.limit_bars,
        },
        "bots": rows,
        "discarded_chart_dirs": [],
        "economics": "NOT_EVIDENCE" if args.mode == "mock" else "PENDING_VERDICT",
        "limitations": [
            "Mock mode answers with a fixed script; it proves plumbing, not edge.",
            "Historical replay cannot be labelled as prospective evidence.",
        ],
    }
    (out / "RUN_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "RUN_REPORT.md").write_text(_render_md(report), encoding="utf-8")
    print(json.dumps({"status": "EXECUTED", "mode": args.mode, "bots": rows}, indent=2))
    return 0


def _render_md(report: dict[str, Any]) -> str:
    lines = [
        "# AI bots run report",
        "",
        f"**Mode:** {report['mode']}  ",
        f"**Status:** {report['status']}  ",
        f"**Real model called:** {report['real_model_called']}  ",
        f"**Economics:** {report['economics']}",
        "",
        "| bot | calls | fills | closed | net USDT | costs USDT | dd % | stop |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["bots"]:
        lines.append(
            "| {bot_id} | {calls} | {fills} | {closed_trades} | {net_realised_usdt} | "
            "{costs_usdt} | {drawdown_pct} | {stop_reason} |".format(**row)
        )
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
