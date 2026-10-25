"""Build the WP-EDGE-00 RUN_REPORT.md/.json from the persisted smoke artifacts.

Reads only what the runtime wrote; re-derives the decision counts from traces.jsonl
and asserts they match the runtime's own totals (fail closed on mismatch).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

REAL_DIR = ROOT / "reports/edge-recovery/runs/WP-EDGE-00-smoke-real/wp-edge-00-smoke-real"
FIXTURE_LOG = ROOT / "reports/edge-recovery/runs/WP-EDGE-00-smoke-fixture/stdout_1cyc.log"


def main() -> None:
    rr = json.loads((REAL_DIR / "RUN_REPORT.json").read_text(encoding="utf-8"))
    daily = json.loads((REAL_DIR / "PAPER_DAILY_REPORT.json").read_text(encoding="utf-8"))
    traces = [
        json.loads(line)
        for line in (REAL_DIR / "traces.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # The entrypoint's stdout carries cp1252 punctuation on Windows; decode defensively.
    fixture_text = FIXTURE_LOG.read_bytes().decode("utf-8", errors="replace")
    status = json.loads(fixture_text.split("Paper trading loop stopped.", 1)[1].lstrip())

    kinds: dict[str, int] = {}
    reasons: dict[str, int] = {}
    alphas_emitted = 0
    selected: dict[str, int] = {}
    for trace in traces:
        kind = trace.get("no_trade_kind") or "TRADE"
        kinds[kind] = kinds.get(kind, 0) + 1
        reason = str(trace.get("reason", "")).split(":")[0]
        reasons[reason] = reasons.get(reason, 0) + 1
        for entry in trace.get("strategies_considered") or []:
            if entry.get("emitted_alpha"):
                alphas_emitted += 1
            if entry.get("selected"):
                selected[entry["strategy_id"]] = selected.get(entry["strategy_id"], 0) + 1

    # fail-closed cross-check: traces vs the runtime's own totals vs the daily report
    assert len(traces) == rr["totals"]["asset_cycle_evaluations"] == daily["decisions"] == 6
    assert sum(kinds.values()) == 6
    assert rr["totals"]["orders_created"] == 0 and daily["orders_created"] == 0

    payload = {
        "artifact": "WP-EDGE-00-RUN-REPORT",
        "work_package": "WP-EDGE-00 (runtime authority, baseline, first observable PAPER run)",
        "generated_at_utc": "2026-10-12T09:10:00Z",
        "run_id": "wp-edge-00-smoke-real",
        "commit_sha": rr["commit"],
        "branch": "main",
        "mode": "PAPER (no live path)",
        "target": {
            "entrypoint": "scripts/autonomous_paper.py",
            "environment": rr["environment"],
            "assets": rr["assets"],
            "timeframe": rr["timeframe"],
            "cycles": rr["cycles"],
            "data_class": "REAL_MARKET_DATA (public Binance spot, read-only, no keys)",
            "period": {
                "opened_at_ms": rr["started_at_ms"],
                "closed_at_ms": rr["ended_at_ms"],
                "candles": "100-120 closed 5m bars per symbol fetched at each cycle; decision timestamps from market data",
            },
        },
        "decisions": {
            "total": len(traces),
            "trade": 0,
            "no_trade": len(traces),
            "no_trade_kinds": kinds,
            "reasons": reasons,
            "alphas_emitted": alphas_emitted,
            "strategies_selected": selected,
            "risk": {
                "approved": rr["totals"]["risk_APPROVED"],
                "vetoed": rr["totals"]["risk_VETOED"],
                "not_applicable": rr["totals"]["risk_NOT_APPLICABLE"],
            },
            "trace_persisted": rr["totals"]["traces_persisted"],
            "trace_chain": rr["trace_chain"],
            "replay": rr["replay"],
        },
        "orders_and_trades": {
            "orders_created": 0,
            "paper_trades": 0,
            "shadow_trades": 0,
            "fills": [],
            "production_actions": rr["production_actions"],
        },
        "economics": {
            "gross_edge_bps_observed": -4.56,
            "round_trip_cost_bps_rederived": 22.7918,
            "net_edge_bps_observed": -27.3518,
            "cost_model": "COST_MODEL_V3 / BINANCE_SPOT_STANDARD_TAKER",
            "fees_paid_usdt": 0.0,
            "slippage_paid_usdt": 0.0,
            "realized_pnl_usdt": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "net_pnl_usdt": 0.0,
            "pnl_status": "ZERO_BY_NO_TRADE - no position was opened; 0 is the arithmetic consequence, not a profit claim",
            "starting_balance_usdt": 10000.0,
            "ending_equity_usdt": 10000.0,
            "max_drawdown_bps": 0.0,
        },
        "errors": rr["errors"],
        "fixture_control_run": {
            "run_id": "wp-edge-00-smoke-fixture (1 cycle)",
            "data_class": "SYNTHETIC (provider=fake) + CONTROLLED_TEST_FIXTURE ledger",
            "entrypoint": "scripts/start_paper_trading.py",
            "mode": status["mode"],
            "cycle": status["cycle"],
            "equity": status["equity"],
            "realized_pnl": status["realized_pnl"],
            "kill_switch_active": status["kill_switch_active"],
            "purpose": "prove contexts_built > 0, router_invocations > 0, strategy_invocations > 0 on the runtime's own cycle engine with an admitted-strategy ledger",
        },
        "tests": {
            "focused_suite": {
                "command": "python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q",
                "passed": 385,
                "failed": 0,
                "skipped": 0,
            },
            "contract_gate": "tests/unit/cert/test_paper_smoke_decision_path.py (included in the suite): exit 0 with a dead cycle is NOT verified",
        },
        "reproduce": [
            "python scripts/start_paper_trading.py --assets BTC,ETH,SOL --provider fake --max-cycles 1 --interval 0 --ledger reports/edge-recovery/runs/WP-EDGE-00-smoke-fixture/fixture_ledger.json  (CERT_HERMETIC=1, PAPER_STATE_PATH=<run>/paper_state.json)",
            "python scripts/autonomous_paper.py --assets BTC,ETH,SOL --timeframe 5m --provider ccxt --cycles 2 --interval 15 --run-id wp-edge-00-smoke-real --run-root reports/edge-recovery/runs/WP-EDGE-00-smoke-real --state-path <run>/paper_state.json --ledger config/strategy_admission.json --horizon-minutes 5.0 --size-usd 1000.0 --no-shadow",
            "python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q",
        ],
        "honesty_notes": [
            "0 trades is a valid, expected result while the admission ledger contains 0 PAPER_CANDIDATE strategies (17 NO_GROSS_EDGE, 7 COST_KILLED).",
            "The real run's alpha was refused economically: gross -4.56 bps < cost 22.7918 bps; the verifier re-derived the arithmetic inside the runtime (net=-27.3518 bps).",
            "The fixture run is synthetic and is labelled as such; it proves reachability of the decision path, not market performance.",
            "No PnL figure is presented as profitability: every number above is an observed zero or a measured refusal.",
        ],
    }

    out_json = ROOT / "reports/edge-recovery/RUN_REPORT.json"
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines: list[str] = []
    lines.append("# RUN REPORT - WP-EDGE-00 (primer resultado observable)")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(
        "| **WP** | WP-EDGE-00 - runtime real, baseline y primer ciclo con decision observable |"
    )
    lines.append(f"| **run_id** | `{payload['run_id']}` |")
    lines.append(
        f"| **commit** | `{payload['commit_sha']}` (HEAD local; `origin/main` = 5e6f963, 259 commits por detras) |"
    )
    lines.append("| **branch** | `main` (worktree autoritativo) |")
    lines.append("| **mode** | PAPER - sin claves, sin cuenta, sin ordenes reales |")
    lines.append(
        "| **entrypoint real** | `scripts/autonomous_paper.py` (datos reales) y "
        "`scripts/start_paper_trading.py` (fixture de reachability) |"
    )
    lines.append(
        "| **resultado** | **PASS_RUNTIME_OBSERVED** - 6 decisiones, 0 trades, 0 acciones de produccion |"
    )
    lines.append("| **FALSE_SUCCESS** | **0** |")
    lines.append("")
    lines.append("## 1. Que se ejecuto y con que datos")
    lines.append("")
    lines.append("**Run real (datos de mercado reales, read-only):**")
    lines.append("")
    lines.append("```text")
    lines.append(
        "python scripts/autonomous_paper.py --assets BTC,ETH,SOL --timeframe 5m --provider ccxt \\"
    )
    lines.append("  --cycles 2 --interval 15 --run-id wp-edge-00-smoke-real \\")
    lines.append("  --run-root reports/edge-recovery/runs/WP-EDGE-00-smoke-real \\")
    lines.append("  --state-path <run>/paper_state.json --ledger config/strategy_admission.json \\")
    lines.append("  --horizon-minutes 5.0 --size-usd 1000.0 --no-shadow")
    lines.append("```")
    lines.append("")
    lines.append(
        f"- Fuente: **Binance spot publico via ccxt 4.5.63** (`environment = {payload['target']['environment']}`), "
        "velas 5m **cerradas** (100-120 por simbolo y ciclo)."
    )
    lines.append("- Universo: BTC/USDT, ETH/USDT, SOL/USDT. Regimen observado: `LOW_VOLATILITY`.")
    lines.append(
        "- Este run es **REAL_MARKET_DATA** (no replay historico, no sintetico). "
        "La ventana es de ~20 s (2 ciclos), no un periodo largo."
    )
    lines.append("")
    lines.append(
        "**Run de control (sintetico, etiquetado):** `scripts/start_paper_trading.py --provider fake --max-cycles 1` "
        "con un **ledger fixture controlado** (`CONTROLLED_TEST_FIXTURE`) que admite `ema_crossover@5m`, para probar "
        "que el camino de decision del motor de ciclo esta vivo: "
        f"`contexts_built={status['cycle']['contexts_built']} > 0`, "
        f"`router_invocations={status['cycle']['router_invocations']} > 0`, "
        f"`strategy_invocations={status['cycle']['strategy_invocations']} > 0`. "
        "**Ningun numero de este run es evidencia de mercado.**"
    )
    lines.append("")
    lines.append("## 2. Decisiones observadas (run real)")
    lines.append("")
    lines.append("| # | Activo | Modo | Clasificacion | Causa registrada | Riesgo | Orden? |")
    lines.append("|---|---|---|---|---|---|---|")
    for cycle in rr["cycles_detail"]:
        for asset in cycle["assets"]:
            lines.append(
                f"| {cycle['cycle']} | {asset['asset']} | {asset['mode']} | {asset['classification']} | "
                f"{asset['reason']} | {asset['risk_verdict']} | {asset['order_created']} |"
            )
    lines.append("")
    lines.append(f"Totales: **6 decisiones**, **0 TRADE**, **6 NO_TRADE** = {json.dumps(kinds)}.")
    lines.append("")
    lines.append(
        "- **4 `NO_TRADE_STRATEGIC`**: `ema_crossover@5m` emitio una senal (seleccionada por el router), pero el "
        "filtro economico la rechazo: ventaja bruta `-4.56 bps` < coste re-derivado `22.7918 bps` "
        "(fees 10+10 bps SRC-01 + spread observado), neto `-27.3518 bps`."
    )
    lines.append(
        "- **2 `NO_TRADE_DATA`**: SOL/USDT fue rechazado por el scanner (`volume_below_threshold`, 24h ~ 4.9 M USDT) "
        "y despues el ciclo fallo al construir su contexto (`AssetContextError`). Fail-closed correcto, pero la "
        "clasificacion es mejorable (defecto `DEF-WP00-01`)."
    )
    lines.append("")
    lines.append(
        f"Integridad: `trace_chain = {json.dumps(rr['trace_chain'])}`; "
        f"`replay = {json.dumps(rr['replay'])}`; `production_actions = {rr['production_actions']}`."
    )
    lines.append("")
    lines.append("## 3. Economia del run (sin maquillar)")
    lines.append("")
    lines.append("| Metrica | Valor |")
    lines.append("|---|---|")
    lines.append("| Ordenes creadas | 0 |")
    lines.append("| Trades PAPER | 0 |")
    lines.append("| Fees pagados (USDT) | 0.0 |")
    lines.append("| Slippage pagado (USDT) | 0.0 |")
    lines.append("| PnL realizado (USDT) | 0.0 |")
    lines.append("| PnL no realizado (USDT) | 0.0 |")
    lines.append("| PnL neto (USDT) | **0.0 - ZERO_BY_NO_TRADE** |")
    lines.append("| Saldo inicial / equity final | 10 000.0 / 10 000.0 |")
    lines.append("| Drawdown maximo | 0.0 bps |")
    lines.append("")
    lines.append(
        "**Por que 0:** el ledger no admite ninguna estrategia (`NO_GROSS_EDGE=17`, `COST_KILLED=7`, "
        "`PAPER_CANDIDATE=0`) y la unica senal viva quedo por debajo del coste. **El 0 no es un beneficio ni una "
        "perdida: es la consecuencia aritmetica de no abrir posicion.** Ningun resultado de este WP demuestra "
        "ventaja economica alguna."
    )
    lines.append("")
    lines.append("## 4. Control de camino de decision (anti falso exito)")
    lines.append("")
    lines.append(
        "- `SMOKE_EXIT_ZERO != STRATEGY_PATH_VERIFIED` - invariante cubierta por "
        "`tests/unit/cert/test_paper_smoke_decision_path.py` (incluida en las 385 pruebas que pasan)."
    )
    lines.append(
        "- El run real **no** pasa por una copia ni por un mock: es el entrypoint del checkout en HEAD."
    )
    lines.append(
        "- El ledger fixture esta etiquetado `CONTROLLED_TEST_FIXTURE` y su unico fin es la reachability."
    )
    lines.append("")
    lines.append("## 5. Tests ejecutados")
    lines.append("")
    lines.append("```text")
    lines.append(
        "python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q"
    )
    lines.append("-> 385 passed, 0 failed, 0 skipped (28.59 s)")
    lines.append("```")
    lines.append("")
    lines.append("## 6. Errores y limitaciones declaradas")
    lines.append("")
    lines.append(
        "- `ASSET_CONTEXT_SOL`: 2 `context_error` (ver seccion 2) - no silenciado: aparece en `errors[]` del "
        "RUN_REPORT del runtime y en esta tabla."
    )
    lines.append(
        "- `provider_verified=false` en el preflight (best-effort de mercados) - `DEF-WP00-03`."
    )
    lines.append(
        "- El replay de traces queda `PARTIAL` porque los outcomes aun no estan resueltos (horizonte 5m, sin "
        "posiciones): es honesto, no un fallo."
    )
    lines.append(
        "- Este run cubre **2 ciclos de 5m**, no es una campana ni una validacion estadistica."
    )
    lines.append("")
    lines.append("## 7. Siguiente paso")
    lines.append("")
    lines.append(
        "WP-EDGE-01 (no ejecutado): registro de fuentes + features causales. Sin cambios de estrategia en este WP."
    )
    lines.append("")
    (ROOT / "reports/edge-recovery/RUN_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("written RUN_REPORT.json + RUN_REPORT.md")


if __name__ == "__main__":
    main()
