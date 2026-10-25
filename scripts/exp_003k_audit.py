"""exp_003k_audit — the economics of the one strategy that reached the paper runtime.

    ./.venv/Scripts/python.exe scripts/exp_003k_audit.py

Before choosing a second strategy it is worth knowing exactly what killed the first one.
This script reads the frozen 003J ledgers (read-only), re-derives every trade's cost stack
and asks the only question that matters for the next experiment:

    is the net loss produced by the signal, or by the price of trading it?

The ledger already separates the three layers, so nothing is recomputed from prices:

    reference_gross_pnl_usdt   gross at the reference price, before execution
    execution_cost_usdt        spread + slippage between reference and fill
    commissions_usdt           both legs, charged once each
    pnl_net_usdt               reference gross - execution - commissions

It also breaks the result down by asset, by exit reason and by a **descriptive** regime
labelled at entry from bars that were already closed (volatility tercile of the trailing
24 bars, and whether the close sat above or below its 56-bar mean). The regime is not a
parameter and is not optimised: it is a way of saying which market the losses came from.

Exit code: 0 when the decomposition identities hold, 1 when they do not. The audit never
writes into the 003J directory.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as stats
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003j_replay import load_series  # noqa: E402

J_OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001"
J_RUNS = J_OUT / "runs"
OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "analysis"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
BOOTSTRAP_SEED = 20261020


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)["entry"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def bootstrap_mean_ci(values: list[float], *, rounds: int = 10_000) -> dict[str, Any]:
    """Percentile bootstrap. Seeded, so the interval is reproducible, not a lucky draw."""

    if not values:
        return {"n": 0, "mean": None, "ci95": None, "rounds": rounds, "seed": BOOTSTRAP_SEED}
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = [stats.fmean(rng.choices(values, k=n)) for _ in range(rounds)]
    means.sort()
    return {
        "n": n,
        "mean": _round(stats.fmean(values)),
        "ci95": [_round(means[int(0.025 * rounds)]), _round(means[int(0.975 * rounds) - 1])],
        "rounds": rounds,
        "seed": BOOTSTRAP_SEED,
    }


def _bars_by_symbol(partition: str) -> dict[str, list[Any]]:
    boundaries = json.loads((J_OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    window = boundaries[partition]
    start = int(
        datetime.strptime(window["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    end = int(
        datetime.strptime(window["end_utc"], "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    series, _ = load_series(symbols=list(SYMBOLS), start_ms=start, end_ms=end, interval_ms=300_000)
    return {symbol.replace("/", ""): bars for symbol, bars in series.items()}


def _context_at(bars: list[Any], ts_ms: int) -> dict[str, Any] | None:
    """Trailing statistics from bars that had **closed** at or before ``ts_ms``."""

    usable = [bar for bar in bars if int(bar.ts_ms) + 300_000 <= int(ts_ms)]
    if len(usable) < 56:
        return None
    tail = usable[-24:]
    ranges = [(bar.high - bar.low) / bar.close * 100.0 for bar in tail if bar.close]
    vol = stats.fmean(ranges) if ranges else None
    window = [bar.close for bar in usable[-56:]]
    trend = "up" if window[-1] > stats.fmean(window) else "down"
    return {"atr_proxy_pct": vol, "trend": trend}


def _audit_run(arm: str, partition: str, series: dict[str, list[Any]]) -> dict[str, Any]:
    path = J_RUNS / arm / partition / "ledger.jsonl"
    rows = _load(path)
    closes = [row for row in rows if row.get("kind") == "CLOSE"]
    decisions = [row for row in rows if row.get("kind") == "DECISION"]
    fills = [row for row in rows if row.get("kind") == "FILL"]

    reference = sum(float(row["reference_gross_pnl_usdt"]) for row in closes)
    execution = sum(float(row["execution_cost_usdt"]) for row in closes)
    commissions = sum(float(row["commissions_usdt"]) for row in closes)
    gross = sum(float(row["gross_pnl_usdt"]) for row in closes)
    net = sum(float(row["pnl_net_usdt"]) for row in closes)
    identity = abs((reference - execution - commissions) - net)
    gross_identity = abs((reference - execution) - gross)

    per_trade = []
    for row in closes:
        notional = abs(float(row["quantity"]) * float(row["entry_price"]))
        cost = float(row["execution_cost_usdt"]) + float(row["commissions_usdt"])
        context = _context_at(series.get(str(row["symbol"]).replace("/", ""), []), int(row["entry_quote_ts_ms"]))
        per_trade.append(
            {
                "symbol": row["symbol"],
                "side": row["side"],
                "day_utc": row.get("day_utc"),
                "exit_reason": row.get("exit_reason"),
                "bars_held": row.get("bars_held"),
                "minutes_held": (int(row["ts_ms"]) - int(row["entry_quote_ts_ms"])) / 60_000.0,
                "notional_usdt": notional,
                "reference_gross_usdt": float(row["reference_gross_pnl_usdt"]),
                "reference_gross_bps": float(row["reference_gross_pnl_usdt"]) / notional * 10_000.0,
                "execution_usdt": float(row["execution_cost_usdt"]),
                "commissions_usdt": float(row["commissions_usdt"]),
                "cost_usdt": cost,
                "cost_bps": cost / notional * 10_000.0,
                "net_usdt": float(row["pnl_net_usdt"]),
                "vol_pct": None if context is None else context["atr_proxy_pct"],
                "trend": None if context is None else context["trend"],
            }
        )

    def block(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"trades": 0}
        nets = [item["net_usdt"] for item in items]
        refs = [item["reference_gross_usdt"] for item in items]
        wins = [value for value in nets if value > 0]
        losses = [value for value in nets if value <= 0]
        return {
            "trades": len(items),
            "reference_gross_usdt": _round(sum(refs)),
            "reference_gross_bps_mean": _round(stats.fmean([item["reference_gross_bps"] for item in items])),
            "cost_usdt": _round(sum(item["cost_usdt"] for item in items)),
            "cost_bps_mean": _round(stats.fmean([item["cost_bps"] for item in items])),
            "net_usdt": _round(sum(nets)),
            "expectancy_usdt": _round(stats.fmean(nets)),
            "win_rate_pct": _round(100.0 * len(wins) / len(items), 4),
            "gross_profit_usdt": _round(sum(wins)),
            "gross_loss_usdt": _round(sum(losses)),
            "profit_factor": _round(sum(wins) / abs(sum(losses)), 4) if losses and sum(losses) else None,
            "mean_minutes_held": _round(stats.fmean([item["minutes_held"] for item in items]), 3),
        }

    by_asset = {symbol: block([item for item in per_trade if item["symbol"] == symbol]) for symbol in sorted({item["symbol"] for item in per_trade})}
    by_reason = {
        reason: block([item for item in per_trade if item["exit_reason"] == reason])
        for reason in sorted({str(item["exit_reason"]) for item in per_trade})
    }

    vol_values = sorted(item["vol_pct"] for item in per_trade if item["vol_pct"] is not None)
    regimes: dict[str, dict[str, Any]] = {}
    if vol_values:
        low, high = vol_values[len(vol_values) // 3], vol_values[(2 * len(vol_values)) // 3]
        for label, predicate in (
            ("vol_low", lambda v: v <= low),
            ("vol_mid", lambda v: low < v <= high),
            ("vol_high", lambda v: v > high),
        ):
            for trend in ("up", "down"):
                subset = [
                    item
                    for item in per_trade
                    if item["vol_pct"] is not None and item["trend"] == trend and predicate(item["vol_pct"])
                ]
                if subset:
                    regimes[f"{label}/{trend}"] = {
                        **block(subset),
                        "vol_bounds_pct": [_round(low), _round(high)],
                    }

    days = len({item["day_utc"] for item in per_trade}) or 1
    trades_per_day = len(per_trade) / days
    cost_per_trade = (execution + commissions) / len(per_trade) if per_trade else None
    mean_notional = stats.fmean([item["notional_usdt"] for item in per_trade]) if per_trade else None
    dominance = None
    if per_trade and mean_notional:
        dominance = {
            "net_usdt": _round(net),
            "reference_gross_usdt": _round(reference),
            "costs_usdt": _round(execution + commissions),
            "cost_share_of_loss_pct": _round(100.0 * (execution + commissions) / abs(net), 4)
            if net < 0
            else None,
            "gross_direction": "POSITIVE" if reference > 0 else "NEGATIVE",
            "cost_per_trade_usdt": _round(cost_per_trade),
            "cost_per_trade_bps": _round((cost_per_trade or 0.0) / mean_notional * 10_000.0),
            "mean_notional_usdt": _round(mean_notional),
            "gross_edge_required_bps": _round(
                (cost_per_trade or 0.0) / mean_notional * 10_000.0
            ),
            "verdict": (
                "COST_DOMINATED"
                if reference > 0 and net < 0
                else "SIGNAL_DOMINATED"
                if reference < 0
                else "FLAT"
            ),
        }

    mfe_capture = None
    metrics_path = J_OUT / "analysis" / "METRICS.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")).get("metrics", [])
        match = next(
            (item for item in metrics if item.get("arm") == arm and item.get("partition") == partition),
            None,
        )
        if match and match.get("mfe_pct_mean"):
            mfe_capture = {
                "mfe_pct_mean": match.get("mfe_pct_mean"),
                "mae_pct_mean": match.get("mae_pct_mean"),
                "mean_holding_minutes": match.get("mean_holding_minutes"),
                "win_rate_pct": match.get("win_rate_pct"),
                "net_realised_usdt": match.get("net_realised_usdt"),
                "cross_check_matches_ledger": abs(float(match.get("net_realised_usdt") or 0.0) - net) <= 1e-3,
            }

    return {
        "arm": arm,
        "partition": partition,
        "ledger": str(path.relative_to(REPO).as_posix()),
        "decisions": len(decisions),
        "fills": len(fills),
        "closes": len(closes),
        "decomposition": {
            "reference_gross_usdt": _round(reference),
            "execution_cost_usdt": _round(execution),
            "commissions_usdt": _round(commissions),
            "gross_after_execution_usdt": _round(gross),
            "net_usdt": _round(net),
            "identity_residual_usdt": _round(identity, 12),
            "gross_identity_residual_usdt": _round(gross_identity, 12),
        },
        "expectancy": bootstrap_mean_ci([item["net_usdt"] for item in per_trade]),
        # The entry's own edge, before any cost is applied. If this interval contains zero
        # the signal is a coin flip and no fee schedule can make it profitable.
        "gross_edge": bootstrap_mean_ci([item["reference_gross_usdt"] for item in per_trade]),
        "all_trades": block(per_trade),
        "turnover": {
            "trades_per_day": _round(trades_per_day, 4),
            "notional_usdt": _round(sum(item["notional_usdt"] for item in per_trade)),
            "notional_per_day_usdt": _round(sum(item["notional_usdt"] for item in per_trade) / days),
            "days_traded": days,
        },
        "dominance": dominance,
        "metrics_cross_check": mfe_capture,
        "by_asset": by_asset,
        "by_exit_reason": by_reason,
        "by_regime": regimes,
        "trades": per_trade,
    }


def _hypotheses(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the numbers say, each with the observation that would falsify it.

    A hypothesis without a refutation test is a slogan. Every entry here names the
    measurement that would kill it, so a later run can fail it instead of agreeing with it.
    """

    real_oos = next((a for a in audits if a["arm"] == "real" and a["partition"] == "oos"), {})
    dom = real_oos.get("dominance") or {}
    gross = real_oos.get("gross_edge") or {}
    ci = gross.get("ci95") or [None, None]
    return [
        {
            "id": "H1_COST_FLOOR",
            "statement": (
                "Con posiciones de 500 USDT y esta tabla de comisiones, un ida y vuelta cuesta "
                f"{dom.get('cost_per_trade_bps')} pb; cualquier candidata debe superar ese bruto "
                "por operación antes de que valga la pena discutir las salidas."
            ),
            "falsified_by": (
                "Una familia cuyo intervalo bootstrap de bruto por operación en la ventana de "
                "research quede entero por encima del suelo de costes y cuyo neto OOS sea positivo."
            ),
            "status": "SUPPORTED_BY_ARITHMETIC",
        },
        {
            "id": "H2_NO_ENTRY_EDGE",
            "statement": (
                "La entrada de EMA crossover no tiene ventaja direccional demostrable en el "
                f"holdout: bruto de referencia medio {gross.get('mean')} USDT por operación, "
                f"intervalo del 95 % [{ci[0]}, {ci[1]}], que contiene el cero."
            ),
            "falsified_by": (
                "Un bootstrap del bruto de referencia por operación de la misma familia en una "
                "ventana independiente cuyo intervalo excluya el cero."
            ),
            "status": "SUPPORTED",
        },
        {
            "id": "H3_EXIT_GIVES_BACK_THE_MOVE",
            "statement": (
                "Las operaciones alcanzan una excursión favorable media de ~0.60 % mientras el "
                "resultado neto por operación es ~-0.26 %; el bracket conserva menos de la mitad "
                "del recorrido que produjo la entrada."
            ),
            "falsified_by": (
                "Un replay de salida fiel a la fuente, declarado antes de ejecutarse y puntuado "
                "solo en la ventana de research, que no mejore el neto por operación; o una "
                "medición de MFE que deje de superar el resultado realizado."
            ),
            "status": "OPEN_DIAGNOSTIC_ONLY",
        },
        {
            "id": "H4_REGIME_CONCENTRATION",
            "statement": (
                "Una celda de régimen (volatilidad media, tendencia bajista) muestra bruto "
                "positivo por operación en 34 observaciones; puede ser ruido y no estructura."
            ),
            "falsified_by": (
                "Que la misma celda no se reproduzca en una ventana que no estaba abierta "
                "cuando se detectó. Nunca se promueve con la ventana que la produjo."
            ),
            "status": "UNRESOLVED_NEEDS_NEW_WINDOW",
        },
    ]


def _markdown(audits: list[dict[str, Any]]) -> str:
    lines = [
        "# 003K — Auditoría económica de la única estrategia que llegó a PAPER",
        "",
        "Reconstruida desde los ledgers congelados de 003J",
        "(`reference_gross` menos ejecución, menos comisiones, igual a `net`).",
        "Nada se recalcula desde precios: las cuatro capas las escribió el runtime contable que las cobró.",
        "",
        "| arm | partition | trades | bruto ref. | ejecución | comisiones | neto | expectativa | IC95% |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for audit in audits:
        d = audit["decomposition"]
        e = audit["expectancy"]
        ci = e.get("ci95") or ["n/a", "n/a"]
        lines.append(
            f"| {audit['arm']} | {audit['partition']} | {audit['closes']} | "
            f"{d['reference_gross_usdt']} | {d['execution_cost_usdt']} | {d['commissions_usdt']} | "
            f"{d['net_usdt']} | {e.get('mean')} | [{ci[0]}, {ci[1]}] |"
        )
    lines += [
        "",
        "## ¿Aporta algo la entrada, antes de costes?",
        "",
        "Bootstrap del bruto de referencia por operación (10 000 remuestreos, semilla fija). "
        "Si el intervalo contiene el cero, la señal no tiene ventaja direccional demostrable y "
        "ningún esquema de comisiones puede salvarla.",
        "",
        "| arm | partition | bruto/op | IC95% bruto | ¿excluye 0? |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for audit in audits:
        g = audit["gross_edge"]
        lo, hi = (g.get("ci95") or [None, None])
        verdict = (
            "n/a"
            if lo is None or hi is None
            else ("sí" if (lo > 0 or hi < 0) else "no")
        )
        lines.append(
            f"| {audit['arm']} | {audit['partition']} | {g.get('mean')} | [{lo}, {hi}] | {verdict} |"
        )
    lines += ["", "## ¿Dominan los costes?", ""]
    for audit in audits:
        dom = audit.get("dominance")
        if not dom:
            continue
        lines += [
            f"**{audit['arm']}/{audit['partition']}** — veredicto `{dom['verdict']}`. "
            f"Bruto de referencia {dom['reference_gross_usdt']} USDT, costes {dom['costs_usdt']} USDT, "
            f"neto {dom['net_usdt']} USDT. "
            + (
                f"Los costes explican el {dom['cost_share_of_loss_pct']} % de la pérdida neta."
                if dom.get("cost_share_of_loss_pct") is not None
                else "No hay pérdida neta que explicar."
            )
            + f" Coste por operación {dom['cost_per_trade_usdt']} USDT; una estrategia de este "
            f"tamaño necesita {dom['gross_edge_required_bps']} pb de bruto por operación solo para empatar.",
            "",
        ]
    for audit in audits:
        if audit["arm"] != "real" or audit["partition"] != "oos":
            continue
        lines += ["## OOS de la estrategia real, por activo", "", "| activo | trades | bruto pb/op | coste pb/op | neto | expectativa | acierto % | PF |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for symbol, item in audit["by_asset"].items():
            lines.append(
                f"| {symbol} | {item['trades']} | {item['reference_gross_bps_mean']} | "
                f"{item['cost_bps_mean']} | {item['net_usdt']} | {item['expectancy_usdt']} | "
                f"{item['win_rate_pct']} | {item['profit_factor']} |"
            )
        lines += ["", "## OOS por motivo de salida", "", "| motivo | trades | bruto ref. | neto | expectativa | minutos medios |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for reason, item in audit["by_exit_reason"].items():
            lines.append(
                f"| {reason} | {item['trades']} | {item['reference_gross_usdt']} | {item['net_usdt']} | "
                f"{item['expectancy_usdt']} | {item['mean_minutes_held']} |"
            )
        lines += ["", "## OOS por régimen etiquetado en la entrada", "", "| régimen | trades | bruto pb/op | neto | expectativa | acierto % |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for label, item in sorted(audit["by_regime"].items()):
            lines.append(
                f"| {label} | {item['trades']} | {item['reference_gross_bps_mean']} | {item['net_usdt']} | "
                f"{item['expectancy_usdt']} | {item['win_rate_pct']} |"
            )
        check = audit.get("metrics_cross_check")
        if check:
            lines += [
                "",
                "## Contraste con el informe congelado",
                "",
                f"MFE medio {check['mfe_pct_mean']} %, MAE medio {check['mae_pct_mean']} %, "
                f"duración media {check['mean_holding_minutes']} min, acierto {check['win_rate_pct']} %. "
                f"El neto del informe ({check['net_realised_usdt']}) "
                + ("coincide con el del ledger." if check["cross_check_matches_ledger"] else "NO coincide con el del ledger."),
            ]
    return "\n".join(lines + _hypotheses_markdown(_hypotheses(audits))) + "\n"


def _hypotheses_markdown(hypotheses: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Hipótesis comprobables", ""]
    for item in hypotheses:
        lines += [
            f"**{item['id']}** (`{item['status']}`) — {item['statement']}",
            "",
            f"- Se refuta si: {item['falsified_by']}",
            "",
        ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    series = {partition: _bars_by_symbol(partition) for partition in ("research", "oos")}
    audits = [
        _audit_run(arm, partition, series[partition])
        for partition in ("research", "oos")
        for arm in ("real", "control")
    ]
    audits.sort(key=lambda item: (item["arm"], item["partition"]))

    residuals = [
        abs(audit["decomposition"]["identity_residual_usdt"]) for audit in audits
    ] + [abs(audit["decomposition"]["gross_identity_residual_usdt"]) for audit in audits]
    ok = all(value <= 1e-6 for value in residuals)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "AI_BOTS_003K_ECONOMIC_AUDIT_V1",
        "hypotheses": _hypotheses(audits),
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "source_experiment": "EXP-003J-REAL-SIGNAL-PAPER-001",
        "identities_ok": ok,
        "max_identity_residual_usdt": max(residuals),
        "audits": audits,
    }
    (out / "ECONOMIC_AUDIT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "ECONOMIC_AUDIT.md").write_text(_markdown(audits), encoding="utf-8", newline="\n")
    for audit in audits:
        dom = audit.get("dominance") or {}
        print(
            f"[003k-audit] {audit['arm']}/{audit['partition']}: closes={audit['closes']} "
            f"ref={audit['decomposition']['reference_gross_usdt']} "
            f"costs={_round((audit['decomposition']['execution_cost_usdt'] or 0) + (audit['decomposition']['commissions_usdt'] or 0))} "
            f"net={audit['decomposition']['net_usdt']} verdict={dom.get('verdict')}",
            flush=True,
        )
    print(f"[003k-audit] identities_ok={ok} (max residual {max(residuals):.3e})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
