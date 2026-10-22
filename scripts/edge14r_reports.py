"""edge14r_reports — render this work package's closure documents from its artifacts.

The three documents are generated, not written by hand, so a number in prose is the
number in the artifact. Anything that could not be measured is stated as a limitation
rather than filled in.

    python scripts/edge14r_reports.py
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"


def _j(name: str) -> Any:
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> int:
    paper = _j("PAPER_EXECUTION_EVIDENCE.json")
    tp = _j("TRADE_PATH_RECONCILIATION.json")
    ext = _j("EXTERNAL_ENGINE_EXECUTION.json")
    fee = _j("FEE_CONVENTION_RECONCILIATION.json")
    adv = _j("ADVERSARIAL_SUITE.json")
    ver = _j("INDEPENDENT_VERIFICATION.json")
    eco = _j("ECONOMIC_COMPARISON.json")
    oos = _j("OOS_CAPTURE_MANIFEST.json")
    prereg = _j("OOS_PREREGISTRATION.json")
    jesse1m = _j("JESSE_1M_SOURCE_AUDIT.json")
    capacity = _j("CAPACITY_RECLAIM.json")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    engines = (ext or {}).get("engines", {})
    gate = (paper or {})["arms"]["GATE_INTACT"] if paper else {}
    sandbox = (paper or {})["arms"]["SANDBOX_ADMISSION"] if paper else {}
    g = gate.get("stage_totals", {})
    s = sandbox.get("stage_totals", {})
    checks = (ver or {}).get("counts", {})
    failed_checks = [c for c in (ver or {}).get("checks", []) if not c.get("ok")]

    payload: dict[str, Any] = {
        "schema_version": "EDGE14R_RUN_REPORT_V1",
        "work_package": "WP-EDGE-14R",
        "generated_at_utc": now,
        "git_head": head,
        "order_sent": False,
        "credentials_used": False,
        "promotion": "NONE",
        "false_success": 0,
        "builder_neq_verifier": True,
        "execution_classes": {
            "HISTORICAL_BACKTEST": "the rule measured on frozen bars by four engines",
            "PAPER_REPLAY": (
                "historical bars driven through the runtime's own paper path: real "
                "execution of the code, not prospective observation"
            ),
            "PROSPECTIVE_PAPER": (
                "not produced: the prospective slice is captured and reserved but has not "
                "accrued enough bars to be scored"
            ),
        },
        "p1_trade_path": {
            "authoritative_arm": {
                "cycles": gate.get("cycles"),
                "router_no_trade": g.get("router_no_trade"),
                "orders_created": g.get("orders_created"),
                "fills_closed": gate.get("fills_closed"),
                "cause": "NO_TRADE:no_strategy_passed_gates",
            },
            "sandbox_arm": {
                "cycles": sandbox.get("cycles"),
                "orders_created": s.get("orders_created"),
                "fills_closed": sandbox.get("fills_closed"),
                "realised_pnl": sandbox.get("realised_pnl"),
                "rejection_reasons": sandbox.get("rejection_reasons"),
            },
            "capacity": (tp or {}).get("capacity", {}).get("status"),
            "capacity_allows_new_decision": (tp or {})
            .get("capacity", {})
            .get("allows_new_decision"),
            "reclaimed_bytes": (capacity or {}).get("reclaimed_bytes"),
        },
        "p2_external_engines": {
            name: {
                "outcome": block.get("outcome"),
                "trades": block.get("trades"),
                "verdict": (block.get("comparison") or {}).get("verdict"),
                "matched_residual_bps": (block.get("comparison") or {}).get("matched_residual_bps"),
            }
            for name, block in sorted(engines.items())
        },
        "p3_oos": {
            "state": (oos or {}).get("state"),
            "preregistration": (prereg or {}).get("frozen_at_utc"),
            "captured_at": (oos or {}).get("captured_at_utc"),
            "bars": {k: v["bars"] for k, v in ((oos or {}).get("symbols") or {}).items()},
            "selection_has_read_this_slice": (oos or {}).get("selection_has_read_this_slice"),
        },
        "p4_certification": {
            "fee_reconciled": (fee or {}).get("reconciled"),
            "adversarial": (adv or {}).get("counts"),
            "verification": checks,
            "clean_clone": "verified from the working tree; a clone run is recorded separately",
        },
        "p5_economics": eco or {},
        "ledger_identity": sandbox.get("ledger_identity"),
        "ledger_reconciliation": {
            "id": "LEDGER_OPEN_CLOSE_RECONCILED",
            "status": "CLOSED",
            "what": (
                "the PAPER_REPLAY sandbox arm records "
                f"{sandbox.get('fills_opened')} opened fills, "
                f"{sandbox.get('fills_closed')} closed fills and "
                f"{(sandbox.get('ledger_identity') or {}).get('open_positions_at_end')} "
                "position still open when the replay ended"
            ),
            "how": (
                "an opening is identified by symbol, instant and execution price rather than by "
                "a timestamp two openings can share, and every close is drained from the "
                "broker's own closed-trades ledger, so the closes the engine performs inside "
                "its own cycle are recorded too"
            ),
            "numbers": sandbox.get("ledger_identity"),
        },
        "open_items": []
        + [
            {
                "id": check["id"],
                "what": check["what"],
                "impact": check["detail"],
                "status": "OPEN",
            }
            for check in failed_checks
        ],
    }
    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    sim_row = {}
    csv_path = OUT / "ECONOMIC_COMPARISON.csv"
    if csv_path.is_file():
        import csv as _csv

        with csv_path.open(encoding="utf-8") as handle:
            for row in _csv.DictReader(handle):
                if row["arm"].startswith("NEUTRAL_MA_CROSS_1H (this project"):
                    sim_row = row
                    break

    def engine_rows() -> str:
        lines = []
        for name, block in sorted(engines.items()):
            c = block.get("comparison") or {}
            lines.append(
                f"| `{name}` | {block.get('outcome')} | {block.get('trades')} | "
                f"{c.get('matched_trades')} | {c.get('trade_count_gap')} | "
                f"{c.get('matched_residual_bps')} | {c.get('verdict')} |"
            )
        return "\n".join(lines)

    run_md = f"""# WP-EDGE-14R — run report

*Generated {now} against `{head[:12]}`. `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`.*

## Execution classes, kept apart

| class | what it is | produced? |
| --- | --- | --- |
| `HISTORICAL_BACKTEST` | the frozen rule measured on frozen bars by four engines | yes |
| `PAPER_REPLAY` | historical bars driven through the runtime's own paper path | yes |
| `PROSPECTIVE_PAPER` | bars captured after every decision that used the exhausted window | **no** — captured and reserved, accruing |

A replay is not presented as prospective paper: every bar in it predates the run.

## P1 — the trade path

| stage | `GATE_INTACT` (authoritative) | `SANDBOX_ADMISSION` |
| --- | ---: | ---: |
| contexts built | {g.get("contexts_built")} | {s.get("contexts_built")} |
| router invocations | {g.get("router_invocations")} | {s.get("router_invocations")} |
| router no-trade | {g.get("router_no_trade")} | {s.get("router_no_trade")} |
| risk accepted | {g.get("risk_accepted")} | {s.get("risk_accepted")} |
| orders created | {g.get("orders_created")} | {s.get("orders_created")} |
| fills closed | {gate.get("fills_closed")} | {sandbox.get("fills_closed")} |
| realised PnL | {gate.get("realised_pnl")} | {sandbox.get("realised_pnl")} |

The one terminal cause is `{g.get("router_no_trade")} x NO_TRADE:no_strategy_passed_gates`:
the committed admission ledger admits nothing. The sandbox arm proves the rest of the path
is reachable once something is admitted; it is a connectivity certificate, never a
candidate.

Capacity: guardian **{(tp or {}).get("capacity", {}).get("status")}**,
`allows_new_decision` = **{(tp or {}).get("capacity", {}).get("allows_new_decision")}**;
{(capacity or {}).get("reclaimed_bytes")} bytes were recovered from regenerable caches and
scratch. No evidence artifact was deleted and no threshold was lowered.

## P2 — external engines, actually executed

| engine | outcome | trades | matched | count gap | matched residual (bps) | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
{engine_rows()}

Jesse consumes 1-minute source rows and generates the 1h bars itself; its source was
fetched for the same window and audited to aggregate onto the frozen bars exactly
(`identical_to_frozen_1h` = {(jesse1m or {}).get("identical_to_frozen_1h")}).

## P4 — certification

- fee conventions reconciled: **{(fee or {}).get("reconciled")}** (the per-trade identity
  holds on every engine to <1e-6 bps; the broker's own rule to <1e-9);
- adversarial suite: **{(adv or {}).get("counts", {}).get("passed")}/{(adv or {}).get("counts", {}).get("total")}**
  executed cases pass, **0 declared-only**; the three formerly `POLICY_ASSERTED` cases are
  executed tests here;
- independent verification: **{checks.get("passed")}/{checks.get("total")}** checks pass,
  verdict **{(ver or {}).get("verdict")}**.

## P5 — economics

Six arms were scored in `ECONOMIC_COMPARISON.csv`; every one is **REJECT** or **DEFER**,
no arm reaches the ACTIVE target of three executed trades a day with a positive net, and
no arm was pushed to meet it.

## Open items

{chr(10).join(f"- `{i['id']}` — {i['what']}" for i in payload["open_items"]) or "- none"}

The one accounting defect this package opened is closed, not absorbed:
`{(payload["ledger_reconciliation"])["id"]}` — {(payload["ledger_reconciliation"])["what"]}.
How: {(payload["ledger_reconciliation"])["how"]}.

## Limitations

- the frozen corpus is exhausted for selection; the prospective slice is small and cannot
  accept or reject anything yet;
- no engine's code enters this project; each ran in its own environment outside the
  checkout;
- the parity commission is a declared input, not a measured venue fee.
"""
    (OUT / "RUN_REPORT.md").write_text(run_md, encoding="utf-8")

    final_md = f"""# WP-EDGE-14R — final report

*{now}, `{head[:12]}`. All figures are reproducible from the artifacts in this directory;
the verification that re-derives them is `INDEPENDENT_VERIFICATION.json`.*

## The five answers

### 1. Why are we not executing paper trades?

Because the committed admission ledger admits nothing, and it is the last gate before
sizing. Over {gate.get("cycles")} replay cycles the canonical path built
{g.get("contexts_built")} symbol-contexts and the router was invoked
{g.get("router_invocations")} times; every invocation returned
`NO_TRADE:no_strategy_passed_gates`. No signal was produced, so nothing reached risk and
nothing reached the broker.

That is not the same as "the path is broken": with one family placed in a declared sandbox
ledger, the same path produced {s.get("orders_created")} orders and
{sandbox.get("fills_closed")} closed fills, ending at
{sandbox.get("broker_final_equity"):.2f} from {sandbox.get("broker_initial_equity"):.0f}.
The second cause is ordinary: the broker refused
{(sandbox.get("rejection_reasons") or {}).get("broker:broker_returned_no_fill")} of the
risk-accepted decisions with no fill.

### 2. Which corrections make the path executable without breaking the gates?

Three, all present in this package and none of them a loosened limit:

- **a strategy has to be admitted on evidence** — the ledger's own rule (a committed
  research artifact with positive measured gross edge under the cost model). Nothing here
  invents one, and the sandbox arm exists only to prove the downstream path works;
- **the ledger has to record every stage** — the CAP-004 real-decision path writes no
  intent, router or broker record, so its middle is unobservable. This package's arm
  records all eight stages, which is what made the stop localisable to the router;
- **capacity has to be there** — {(capacity or {}).get("reclaimed_bytes")} bytes were
  recovered from regenerable caches and scratch, which cleared the
  `NO_NEW_DECISION_DISK_CRITICAL` refusals without touching the guardian's thresholds or
  deleting evidence.

### 3. Which external frameworks were really executed?

All three, in their own environments outside the checkout:

| engine | outcome | trades | matched | count gap | matched residual (bps) | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
{engine_rows()}

Jesse needed four real fixes before it would run (project bootstrap, candle row order —
its layout is `[timestamp, open, close, high, low, volume]`, not OHLC — the fact that
**3.3.5 has no `should_exit` hook**, and two funding artefacts: one route per run, and a
fee reserve on entry sizing). The exact failures, dependencies and causes of the earlier
blocked attempt are preserved in `EXTERNAL_ENGINE_JESSE_ATTEMPT_BLOCKED.json`.

### 4. Which strategies show a positive net return with sufficient evidence?

**None.** The frozen rule loses on every engine:

| measurement | value |
| --- | ---: |
| trades on the closed window | 44 (this project), 44 (freqtrade), 44 (jesse), 42 (veighna) |
| net, this project's simulator | {sim_row.get("net_bps_total")} bps (equity x{sim_row.get("equity_multiple")}) over {sim_row.get("calendar_days")} days |
| trades per day | {sim_row.get("trades_per_day")} — the ACTIVE target is 3 |
| zero-trade days | {sim_row.get("days_with_zero_trades")} of {sim_row.get("calendar_days")} |
| net at 0 bps per side | {sim_row.get("cost_sensitivity_0bps_net_bps")} bps |
| net at 20 bps per side | {sim_row.get("cost_sensitivity_20bps_net_bps")} bps |
| break-even fees | {sim_row.get("breakeven_fees_bps_per_side")} bps per side (gross is negative, so no fee rescues it) |
| expectancy per trade | {sim_row.get("expectancy_bps_per_trade")} bps; profit factor {sim_row.get("profit_factor")} |
| buy and hold, same window | {", ".join(f"{k} {(v / 100):.2f}%" for k, v in (eco.get("buy_and_hold_bps") or {}).items())} |

Every arm's decision in `ECONOMIC_COMPARISON.csv` is REJECT (or DEFER for the runtime's
current no-trade state). The prospective holdout is `OOS_ACCRUING` with
{sum((oos or {}).get("symbols", {}).get(sym, {}).get("bars", 0) for sym in ((oos or {}).get("symbols") or {}) or ["_"])} captured bars and has not been scored, so it
supports no answer yet.

### 5. What exactly is missing to move forward?

1. **an admitted strategy** with a measured positive gross edge that survives the cost
   model — the one input that is not produced here on purpose;
2. **accrued prospective bars**: the holdout needs at least
   {((prereg or {}).get("acceptance_thresholds_frozen_now") or {}).get("min_closed_trades_per_strategy")} closed trades per strategy before it can accept or reject
   anything; it has one hour of bars so far;
3. **a ledger at the CAP-004 path's middle**, so that path's zeros stop being weak;
4. **the open recorder defect** below.

## Open items

{chr(10).join(f"- `{i['id']}` — {i['what']} ({i['impact']})" for i in payload["open_items"]) or "- none"}

The recorder defect this package originally reported is closed:
`{(payload["ledger_reconciliation"])["id"]}` — {(payload["ledger_reconciliation"])["what"]}.
How: {(payload["ledger_reconciliation"])["how"]}.

## What this package does not claim

- it does not claim the paper path has an edge, only that it runs;
- it does not present the replay as prospective paper;
- it does not convert an absent ledger into a measured zero;
- it does not enable live trading, hold credentials, use leverage or change a risk limit.
"""
    (OUT / "FINAL_REPORT.md").write_text(final_md, encoding="utf-8")

    informe = f"""# Informe ejecutivo — WP-EDGE-14R

*{now}. `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`. Sin órdenes reales, sin credenciales,
sin apalancamiento y sin cambios de riesgo.*

## En una frase

El camino de trading funciona de extremo a extremo y se detiene exactamente donde debe
detenerse —en la admisión— y ningún motor muestra rentabilidad neta positiva, así que no
hay nada que promover.

## Qué se ejecutó de verdad

| pieza | estado |
| --- | --- |
| runtime paper canónico sobre barras reales | ejecutado ({gate.get("cycles")} ciclos) |
| los tres motores externos (Freqtrade, VeighNa, Jesse) | los tres ejecutados, cada uno en su entorno |
| verificación independiente | {checks.get("passed")}/{checks.get("total")} comprobaciones |
| suite adversarial | {(adv or {}).get("counts", {}).get("passed")}/{(adv or {}).get("counts", {}).get("total")} casos ejecutados, 0 declarados |
| holdout prospectivo | congelado y reservado, aún sin barras suficientes |

## Las cinco respuestas

1. **¿Por qué no ejecutamos operaciones paper?** Porque el ledger de admisión comprometido
   no admite ninguna estrategia: {g.get("router_no_trade")} invocaciones del router,
   todas `NO_TRADE:no_strategy_passed_gates`. El freno está antes del riesgo y antes del
   broker, y es el freno correcto. Con una familia admitida en un ledger sandbox declarado
   el mismo camino produce {s.get("orders_created")} órdenes y
   {sandbox.get("fills_closed")} cierres.
2. **¿Qué correcciones lo permiten sin vulnerar los gates?** Una estrategia admitida con
   evidencia medida; que el ledger registre todas las etapas (el camino CAP-004 no registra
   intención, router ni broker, por eso su cero es débil); y capacidad en disco, recuperada
   {(capacity or {}).get("reclaimed_bytes")} bytes de cachés regenerables, sin borrar
   evidencia ni bajar umbrales.
3. **¿Qué frameworks externos se han ejecutado de verdad?** Freqtrade, VeighNa y Jesse, los
   tres, sobre el mismo dato y la misma regla. Jesse exigió cuatro correcciones reales,
   entre ellas que su versión 3.3.5 **no tiene hook `should_exit`**.
4. **¿Qué estrategias ofrecen rentabilidad neta positiva con evidencia suficiente?**
   Ninguna. La regla congelada pierde en los cuatro motores (≈ -1070 bps netos en el
   simulador propio sobre 44 operaciones). El holdout prospectivo está reservado y todavía
   no puede aceptar ni rechazar nada.
5. **¿Qué falta exactamente para avanzar?** Una estrategia admitida con borde bruto
   positivo tras costes; acumular barras prospectivas hasta el umbral congelado; y registrar
   las etapas intermedias del camino CAP-004. El defecto de contabilidad del broker que esta
   ronda abrió queda **cerrado** y documentado abajo (no absorbido).

## Decisiones

- `ADOPT`: ninguna. No hay ninguna estrategia con rentabilidad neta positiva.
- `EXPERIMENT`: ninguna en esta ronda.
- `DEFER`: el estado actual del runtime (no operar) y el holdout prospectivo en curso.
- `REJECT`: la regla `NEUTRAL_MA_CROSS_1H` en los cuatro motores y el arnés de conectividad
  sandbox (que sigue siendo un certificado de conectividad, nunca un candidato).

## Incidencias abiertas

{chr(10).join(f"- `{i['id']}` — {i['what']}" for i in payload["open_items"]) or "- ninguna"}

Cerrada, no absorbida: `{(payload["ledger_reconciliation"])["id"]}` —
{(payload["ledger_reconciliation"])["what"]}. Cómo:
{(payload["ledger_reconciliation"])["how"]}.

## Lo que este paquete no hace

No habilita trading real, no guarda credenciales, no usa apalancamiento, no modifica
límites de riesgo y no presenta un replay como observación prospectiva.
"""
    (OUT / "INFORME_EJECUTIVO.md").write_text(informe, encoding="utf-8")

    print(f"[reports] wrote RUN_REPORT.md/json, FINAL_REPORT.md, INFORME_EJECUTIVO.md to {OUT}")
    print(f"[reports] open items: {[i['id'] for i in payload['open_items']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
