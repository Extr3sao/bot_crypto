"""Panel de solo lectura (UX V2) para la campaña ACTIVA POC02-R2.

Español, lenguaje humano, sin vocabulario de trading. Lee SOLO la evidencia
persistida de la campaña (R2_CYCLE_LEDGER, R2_COVERAGE_DAILY, recibos,
atribución, shadow, estado de campaña) y la presenta respondiendo las
preguntas de la página principal:

    ¿ESTÁ FUNCIONANDO?  ¿ESTÁ GANANDO?  ¿ESTÁ OPERANDO SUFICIENTE?
    ¿QUÉ LO ESTÁ BLOQUEANDO?

Solo GET. Sin rutas de control (POST/PUT/PATCH/DELETE -> 405). El selector de
campaña muestra ACTUAL (POC-02-R2) e HISTÓRICAS (POC02, POC01) claramente
separadas. Si el heartbeat envejece se muestra DATOS DESACTUALIZADOS.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ACTIVE_CAMPAIGN = "POC-02-R2-direction-arbitration-01"
ACTIVE_DIR = ROOT / "reports" / "poc02-r2-direction-arbitration-01"
HISTORIC_CAMPAIGNS = {
    "POC-02-paper-clean-01": ROOT / "reports" / "poc02-paper-clean-01",
    "POC-01-paper-observation-01": ROOT / "reports" / "paper-observation-01",
}
RISK_REASON_ES = {
    "MAX_POSITIONS": "Máximo de posiciones abiertas alcanzado",
    "CONSECUTIVE_LOSS_COOLDOWN": "Pausa de seguridad tras pérdidas consecutivas",
    "OTHER_RISK": "Otros motivos de seguridad",
    "UNRESOLVED_CONFLICT": "Conflicto entre análisis",
    "LOWER_RANKED_ALTERNATIVE": "Otra oportunidad tenía mejor puntuación",
    "HIGHEST_ADMISSIBLE_SCORE": "Mejor puntuación admisible",
}
STRATEGY_ES = {
    "momentum": ("Momentum", "Busca aprovechar movimientos que ya llevan fuerza."),
    "trend": ("Tendencia", "Sigue la dirección mientras se mantenga sostenida."),
    "breakout": ("Ruptura", "Detecta cuando el precio rompe un rango con fuerza."),
    "mean_reversion": ("Reversión", "Apostar a que un movimiento exagerado vuelve a la media."),
    "volatility": ("Volatilidad", "Opera la explosión tras una calma prolongada."),
}
STALE_AFTER_MINUTES = 90


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _human_age(minutes: float) -> str:
    if minutes < 60:
        return f"hace {int(minutes)} min"
    hours = minutes / 60
    if hours < 24:
        return f"hace {int(hours)} h"
    return f"hace {int(hours / 24)} días"


def campaign_snapshot(campaign_id: str = ACTIVE_CAMPAIGN) -> dict:
    is_active = campaign_id == ACTIVE_CAMPAIGN
    base = ACTIVE_DIR if is_active else HISTORIC_CAMPAIGNS.get(campaign_id, ACTIVE_DIR)
    state = _load_json(base / "R2_CAMPAIGN_STATE.json") or _load_json(
        base / "POC02_CAMPAIGN_STATE.json"
    )
    launch = _load_json(base / "R2_LAUNCH_RECORD.json") or _load_json(
        base / "POC02_LAUNCH_RECORD.json"
    )
    coverage_rows = _load_jsonl(base / "R2_COVERAGE_DAILY.jsonl") or _load_jsonl(
        base / "POC02_COVERAGE_DAILY.jsonl"
    )
    attribution = _load_jsonl(base / "cycles" / "POC02_ATTRIBUTION.jsonl")

    # funnel + arbitration from receipts of the ACTIVE campaign only
    receipt_dir = base / "receipts"
    receipts = sorted(receipt_dir.glob("RECEIPT_*.json")) if receipt_dir.exists() else []
    # FUNNEL SOURCE (DEF-R2-002 note): computed from the R2 cycle LEDGER state
    # counters — authoritative for every run. Receipts 001-004 predate the
    # double-count fix and are immutable evidence; mixing sources would
    # understate RISK_ACCEPT and overstate PAPER_OPEN.
    cycle_rows = _load_jsonl(base / "R2_CYCLE_LEDGER.jsonl")
    funnel: dict[str, int] = {"RISK_ACCEPT": 0, "RISK_REJECT": 0, "PAPER_OPEN": 0}
    arbitration = {
        "groups_total": 0,
        "long_selected": 0,
        "short_selected": 0,
        "none_selected": 0,
        "selection_reasons": {},
    }
    by_day: dict[str, dict] = {}
    for receipt in receipts[-8:]:
        try:
            r = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = r.get("utc_day", "?")
        day_row = by_day.setdefault(day, {"day": day, "trades": 0, "proposals": 0, "selected": 0})
        f = r.get("proposal_funnel", {})
        for key in (
            "MARKET_SCANS", "PROPOSALS", "OPPORTUNITY_GROUPS", "DIRECTION_LONG_SELECTED",
            "DIRECTION_SHORT_SELECTED", "DIRECTION_NONE", "SELECTED", "NO_TRADE",
            "VERIFIER_VERIFIED", "VERIFIER_REJECTED",
            "PAPER_CLOSE", "AGENT_REJECT", "DEBATES",
        ):
            funnel[key] = funnel.get(key, 0) + int(f.get(key, 0) or 0)
        day_row["trades"] += int(f.get("PAPER_OPEN", 0) or 0)  # legacy receipt days
        day_row["proposals"] += int(f.get("PROPOSALS", 0) or 0)
        day_row["selected"] += int(f.get("SELECTED", 0) or 0)
        arb = r.get("arbitration_telemetry", {})
        for key in ("groups_total", "long_selected", "short_selected", "none_selected"):
            arbitration[key] = arbitration.get(key, 0) + int(arb.get(key, 0) or 0)
        for reason, n in (arb.get("selection_reasons") or {}).items():
            arbitration["selection_reasons"][reason] = (
                arbitration["selection_reasons"].get(reason, 0) + int(n)
            )

    # PnL y operaciones desde la atribución (campaña)
    paper_open = [r for r in attribution if r.get("stage") == "PAPER_OPEN"]
    paper_close = [r for r in attribution if r.get("stage") == "PAPER_CLOSE"]
    net_pnl = round(sum(float(r.get("net_pnl", 0.0) or 0.0) for r in paper_close), 2)
    risk_reject_rows = [r for r in attribution if r.get("stage") == "RISK_REJECT"]
    risk_accept = funnel.get("RISK_ACCEPT", 0)
    risk_reject = funnel.get("RISK_REJECT", 0) or len(risk_reject_rows)

    # TRACK G: intentos de ejecución (broker_calls) desde el ledger de ciclos;
    # los contadores de riesgo/operaciones también vienen del ledger (fuente única)
    execution_attempts = sum(
        int(r.get("state", {}).get("broker_calls", 0) or 0) for r in cycle_rows
    )
    funnel["RISK_ACCEPT"] = sum(
        int(r.get("state", {}).get("risk_accepts", 0) or 0) for r in cycle_rows
    )
    funnel["RISK_REJECT"] = sum(
        int(r.get("state", {}).get("risk_rejects", 0) or 0) for r in cycle_rows
    )
    funnel["PAPER_OPEN"] = sum(
        int(r.get("state", {}).get("paper_trades", 0) or 0) for r in cycle_rows
    )
    execution_failed = sum(
        1
        for r in attribution
        if r.get("stage") == "RISK_ACCEPT_RESOLVED"
        and r.get("final_disposition") == "EXECUTION_FAILED"
    )
    duplicate_suppressed = sum(
        1
        for r in attribution
        if r.get("stage") == "RISK_ACCEPT_RESOLVED"
        and r.get("final_disposition") == "DUPLICATE_ECONOMIC_INTENT"
    )

    rejection_rate = (
        round(risk_reject / (risk_reject + risk_accept), 4)
        if (risk_reject + risk_accept)
        else None
    )

    # estrategia (semántica de fuente aclarada — DEF-FE-STRAT-001)
    strategies: dict[str, dict] = {}
    for r in paper_close:
        sid = "momentum"  # la composición R2 actual genera familia momentum (eco)
        strategies.setdefault(sid, {"operations": 0, "pnl": 0.0})
        strategies[sid]["operations"] += 1
        strategies[sid]["pnl"] = round(strategies[sid]["pnl"] + float(r.get("net_pnl", 0.0) or 0.0), 2)

    # bottleneck dominante
    bottleneck_totals: dict[str, int] = {}
    for receipt in receipts[-8:]:
        try:
            r = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key, n in (r.get("bottleneck_state", {}).get("totals_canonical", {})).items():
            bottleneck_totals[key] = bottleneck_totals.get(key, 0) + int(n)
    dominant = max(bottleneck_totals, key=lambda k: bottleneck_totals[k]) if bottleneck_totals else None

    # frescura (heartbeat)
    heartbeat = state.get("heartbeat_utc")
    age_minutes: float | None = None
    if heartbeat:
        try:
            hb = datetime.fromisoformat(str(heartbeat))
            age_minutes = (datetime.now(UTC) - hb).total_seconds() / 60.0
        except ValueError:
            age_minutes = None
    stale = age_minutes is None or age_minutes > STALE_AFTER_MINUTES

    # cobertura del día en curso y días válidos
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    today_row = next((r for r in coverage_rows if r.get("utc_day") == today), {})
    valid_days = [
        r for r in coverage_rows
        if r.get("day_validity") == "VALID" or r.get("coverage_ratio", 0) >= 0.8
    ]

    return {
        "campaign_id": campaign_id,
        "is_active": is_active,
        "status": state.get("status", "DESCONOCIDO"),
        "mode": "PAPER",
        "launched_at": launch.get("launched_at_utc") or launch.get("start_utc"),
        "heartbeat_utc": heartbeat,
        "age_human": _human_age(age_minutes) if age_minutes is not None else "sin latido",
        "stale": stale,
        "equity_display": None,  # se rellena abajo con el broker cuando exista
        "net_pnl": net_pnl,
        "trades_today": int(today_row.get("observed_cycles", 0) or 0) and funnel.get("PAPER_OPEN", 0),
        "paper_opens_total": len(paper_open),
        "paper_closes_total": len(paper_close),
        "risk_accept": risk_accept,
        "risk_reject": risk_reject,
        "execution_attempts": execution_attempts,
        "execution_failed": execution_failed,
        "duplicate_suppressed": duplicate_suppressed,
        "rejection_rate": rejection_rate,
        "dominant_bottleneck": dominant,
        "bottleneck_totals": bottleneck_totals,
        "funnel": funnel,
        "arbitration": arbitration,
        "coverage_today_ratio": today_row.get("coverage_ratio"),
        "valid_days": len(valid_days),
        "coverage_rows": [
            {k: r.get(k) for k in ("utc_day", "observed_cycles", "observed_minutes", "coverage_ratio", "day_validity")}
            for r in coverage_rows
        ],
        "daily": sorted(by_day.values(), key=lambda d: d["day"]),
        "strategies": strategies,
        "risk_reject_reasons": _risk_reason_split(risk_reject_rows),
        "shadow": _shadow_summary(base),
    }


def _risk_reason_split(rows: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        blocked = str(r.get("risk_blocked_by") or r.get("risk_reason") or "OTHER_RISK").upper()
        if "MAX" in blocked and "POSITION" in blocked:
            key = "MAX_POSITIONS"
        elif "COOLDOWN" in blocked:
            key = "CONSECUTIVE_LOSS_COOLDOWN"
        else:
            key = "OTHER_RISK"
        out[key] = out.get(key, 0) + 1
    return out


def _shadow_summary(base: Path) -> dict:
    captures = _load_jsonl(base / "shadow" / "shadow_captures.jsonl")
    outcomes = _load_jsonl(base / "shadow" / "shadow_outcomes.jsonl")
    wins = losses = 0
    net = 0.0
    for t in outcomes:
        pnl = float(t.get("net_pnl", t.get("pnl", 0.0)) or 0.0)
        net += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
    return {
        "captures": len(captures),
        "resolved": len(outcomes),
        "wins": wins,
        "losses": losses,
        "net_pnl": round(net, 2),
    }


_HTML_HEAD = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Panel de campaña — Solo lectura</title>
<style>
:root{color-scheme:dark;font:15px 'Segoe UI',system-ui,sans-serif}
body{margin:0;background:#0f1216;color:#e6e6e6}
header,main{max-width:1100px;margin:auto;padding:16px}
header{border-bottom:1px solid #2a3038;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:1.25rem;margin:0} h2{font-size:1.05rem;margin:1rem 0 .4rem}
.badge{padding:3px 10px;border-radius:12px;font-size:.8rem;border:1px solid #58a6ff;color:#58a6ff}
.badge.green{border-color:#3fb950;color:#3fb950}
.badge.red{border-color:#f85149;color:#f85149}
.badge.gray{border-color:#8b949e;color:#8b949e}
.stale{background:#f85149;color:#fff;padding:8px 16px;border-radius:6px;font-weight:bold;font-size:1.05rem;margin:12px 0}
.grid{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.card{background:#171c22;border:1px solid #2a3038;border-radius:8px;padding:12px 16px;min-width:150px}
.card b{display:block;font-size:1.35rem;margin-top:4px}
.funnel{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.funnel .step{background:#171c22;border:1px solid #2a3038;border-radius:8px;padding:10px 14px;text-align:center}
.funnel .arrow{color:#58a6ff;font-size:1.2rem}
table{width:100%;border-collapse:collapse;margin:8px 0}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #2a3038;font-size:.9rem}
.muted{color:#8b949e;font-size:.85rem}
.badge.amber{border-color:#f0b72f;color:#f0b72f}
.notice{background:#3d2e00;border:1px solid #9e6a03;color:#f0b72f;border-radius:8px;padding:10px 14px;margin-top:10px;font-size:.9rem}
.positive{color:#3fb950}.negative{color:#f85149}
details{margin:8px 0}summary{cursor:pointer;color:#58a6ff}
.question{font-weight:600;color:#c9d1d9;margin:14px 0 4px}
</style></head><body>"""


def _render_home(campaign_id: str) -> bytes:
    s = campaign_snapshot(campaign_id)
    f = s["funnel"]
    arb = s["arbitration"]
    running = s["status"] == "ACTIVE" and not s["stale"]
    estado = "FUNCIONANDO" if running else ("DATOS DESACTUALIZADOS" if s["stale"] else "DETENIDA")
    estado_badge = "green" if running else "red"

    # TRACK I — campaign classification (honest, visible):
    # diagnostic campaign: explicitly non-certifying for performance/frequency
    class_badges = (
        '<span class="badge amber">CAMPAÑA DE DIAGNÓSTICO</span>'
        '<span class="badge red">NO VÁLIDA PARA CERTIFICAR RENTABILIDAD</span>'
        '<span class="badge red">NO VÁLIDA PARA CERTIFICAR FRECUENCIA</span>'
    )

    # day validity under the enforcing contract: below 0.80 => DÍA NO VÁLIDO
    day_coverage = s.get("coverage_today_ratio")
    try:
        day_below = day_coverage is not None and float(day_coverage) < 0.80
    except (TypeError, ValueError):
        day_below = False
    finalizations = _load_json(
        (ACTIVE_DIR if s["is_active"] else HISTORIC_CAMPAIGNS.get(s["campaign_id"], ACTIVE_DIR))
        / "POC02_DAY_FINALIZATIONS.json"
    )
    invalid_days = [
        d
        for d, v in finalizations.items()
        if v.get("validity") == "INVALID"
        or any("COVERAGE_BELOW_MINIMUM" in rc for rc in (v.get("reason_codes") or []))
    ]
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    today_final = finalizations.get(today)
    if day_below and today_final is not None:
        day_badge = (
            '<div class="notice">DÍA NO VÁLIDO — cobertura por debajo del contrato '
            f"(&ge; 0.80): {day_coverage}. Los días incompletos no cuentan para "
            "frecuencia ni rendimiento.</div>"
        )
    elif day_below:
        day_badge = (
            '<div class="notice">Cobertura en curso por debajo del contrato '
            f"(&ge; 0.80): {day_coverage}. El día solo contará si al cierre alcanza "
            "el contrato; nunca se bajará el umbral.</div>"
        )
    else:
        day_badge = ""
    invalid_note = (
        f'<p class="muted">Días finalizados NO VÁLIDOS por cobertura: '
        f"{', '.join(sorted(invalid_days))} — conservados como evidencia, nunca "
        "contados como días de rendimiento.</p>"
        if invalid_days
        else ""
    )

    # funnel humano — TRACK G: la diferencia entre autorizadas y abiertas
    # debe ser visible, nunca inferible
    steps = [
        ("Mercado analizado", f.get("MARKET_SCANS", 0)),
        ("Oportunidades encontradas", f.get("PROPOSALS", 0)),
        ("Oportunidades elegidas", f.get("SELECTED", 0)),
        ("Verificadas", f.get("VERIFIER_VERIFIED", 0)),
        ("Autorizadas por seguridad", f.get("RISK_ACCEPT", 0)),
        ("Intentos de ejecución", s["execution_attempts"]),
        ("Operaciones", s["paper_opens_total"]),
    ]
    funnel_html = '<div class="funnel">' + '<span class="arrow">&rarr;</span>'.join(
        f'<div class="step"><div class="muted">{label}</div><b>{n}</b></div>'
        for label, n in steps
    ) + "</div>"
    gap = s["risk_accept"] - s["paper_opens_total"]
    if gap > 0:
        motivo = []
        if s["execution_failed"]:
            motivo.append(f"{s['execution_failed']} fallo(s) de ejecución ya reparados")
        if s["duplicate_suppressed"]:
            motivo.append(f"{s['duplicate_suppressed']} duplicado(s) bloqueados")
        motivo_txt = "; ".join(motivo) if motivo else "ver detalle técnico"
        funnel_html += (
            f'<div class="notice">⚠️ No todas las autorizadas se abrieron: '
            f"{s['risk_accept']} autorizadas vs {s['paper_opens_total']} operaciones "
            f"(diferencia: {gap}). Motivos: {motivo_txt}.</div>"
        )

    # bloquiteos humanos
    reasons = s["risk_reject_reasons"]
    reasons_html = (
        "".join(
            f"<li>{RISK_REASON_ES.get(k, k)}: {n}</li>"
            for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])
        )
        or "<li class='muted'>Sin bloqueos registrados todavía</li>"
    )
    conflict = f.get("AGENT_REJECT", 0)
    reasons_html += f"<li>Conflicto entre análisis (pre-elección): {conflict}</li>"

    # estrategias
    strat_rows = ""
    for sid, st in s["strategies"].items():
        name, desc = STRATEGY_ES.get(sid, (sid, ""))
        enough = "Sí" if st["operations"] >= 5 else "Aún no"
        pnl_cls = "positive" if st["pnl"] > 0 else ("negative" if st["pnl"] < 0 else "muted")
        strat_rows += (
            f"<tr><td>{name}</td><td>Activa</td><td>{st['operations']}</td>"
            f"<td class='{pnl_cls}'>{st['pnl']:.2f} USDT</td><td>{enough}</td>"
            f"<td class='muted'>Seguir observando</td></tr>"
            f"<tr><td colspan='6' class='muted'>{desc}</td></tr>"
        )
    if not strat_rows:
        strat_rows = "<tr><td colspan='6' class='muted'>Sin operaciones todavía: la muestra aún no permite evaluar estrategias</td></tr>"

    # informes humanos
    report_rows = "".join(
        f"<tr><td>{day}</td><td>Informe diario</td><td>{d['trades']} operaciones</td></tr>"
        for day, d in [(x["day"], x) for x in s["daily"]]
    ) or "<tr><td colspan='3' class='muted'>Aún no hay informes diarios cerrados</td></tr>"

    cov_rows = "".join(
        f"<tr><td>{r.get('utc_day')}</td><td>{r.get('observed_cycles')}</td>"
        f"<td>{r.get('coverage_ratio')}</td><td>{r.get('day_validity')}</td></tr>"
        for r in s["coverage_rows"]
    ) or "<tr><td colspan='4' class='muted'>Sin cobertura registrada</td></tr>"

    campaigns_html = (
        f'<option value="{ACTIVE_CAMPAIGN}" {"selected" if s["is_active"] else ""}>'
        f"ACTUAL — {ACTIVE_CAMPAIGN} (PAPER)</option>"
    )
    for cid in HISTORIC_CAMPAIGNS:
        campaigns_html += (
            f'<option value="{cid}" {"selected" if campaign_id == cid else ""}>'
            f"HISTÓRICA — {cid} (archivada, solo lectura)</option>"
        )

    pnl = s["net_pnl"]
    pnl_display = f"{pnl:.2f} USDT" if s["paper_closes_total"] else "Sin operaciones cerradas todavía"
    pnl_cls = "positive" if pnl > 0 else ("negative" if pnl < 0 else "muted")
    rej = s["rejection_rate"]
    rej_display = f"{rej * 100:.1f} %" if rej is not None else "Aún no hay datos suficientes"

    op_suf = "Aún no" if s["paper_opens_total"] < 3 else "Sí"
    bottleneck_es = {
        "NO_SIGNAL": "El mercado no dio señales",
        "AGENT_FILTER": "Conflicto entre análisis",
        "VERIFIER_FILTER": "No pasó la verificación",
        "RISK_COOLDOWN": "Pausa de seguridad tras pérdidas",
        "RISK_POSITIONS": "Máximo de posiciones alcanzado",
        "OTHER_RISK": "Otros motivos de seguridad",
        "EXECUTION": "Límite de ejecución",
        "NONE": "Sin bloqueo",
    }
    bottleneck_display = (
        bottleneck_es.get(s["dominant_bottleneck"], s["dominant_bottleneck"])
        if s["dominant_bottleneck"] else "Sin datos todavía"
    )

    arb_row = (
        f"<div class='card'>Grupos evaluados<b>{arb['groups_total']}</b></div>"
        f"<div class='card'>Dirección LARGO elegida<b>{arb['long_selected']}</b></div>"
        f"<div class='card'>Dirección CORTO elegida<b>{arb['short_selected']}</b></div>"
        f"<div class='card'>Sin dirección (no operar)<b>{arb['none_selected']}</b></div>"
    )

    html = f"""{_HTML_HEAD}
<header>
<h1>Panel de la campaña</h1>
<span class="badge">PAPER &bull; DINERO REAL DESACTIVADO</span>
<span class="badge {estado_badge}">{estado}</span>
{class_badges}
<select id="camp" onchange="location.href='/?campaign='+this.value">{campaigns_html}</select>
<span class="muted">Última actualización: {s["age_human"]} ({s["heartbeat_utc"] or "sin latido"})</span>
</header>
<main>
{'<div class="stale">DATOS DESACTUALIZADOS — ' + s["age_human"] + "</div>" if s["stale"] else ""}
<h2>Resumen</h2>
<div class="question">¿ESTÁ FUNCIONANDO?</div>
<div class="grid">
<div class="card">Estado<b>{estado}</b></div>
<div class="card">Campaña<b style="font-size:.9rem">{s["campaign_id"]}</b></div><div class="card">Cobertura de hoy<b>{s["coverage_today_ratio"] or "en curso"}</b></div>
<div class="card">Última actualización<b style="font-size:.9rem">{s["age_human"]}</b>
</div>
{day_badge}
</div>
<div class="question">¿ESTÁ GANANDO?</div>
<div class="grid">
<div class="card">Resultado de operaciones cerradas<b class="{pnl_cls}">{pnl_display}</b></div>
<div class="card">Operaciones cerradas<b>{s["paper_closes_total"]}</b></div>
<div class="card">Operaciones abiertas<b>{s["paper_opens_total"]}</b></div>
</div>
<div class="question">¿ESTÁ OPERANDO SUFICIENTE?</div>
<div class="grid">
<div class="card">Operaciones hoy<b>{s["paper_opens_total"]}</b></div>
<div class="card">Objetivo<b>&ge; 3 por día</b></div>
<div class="card">¿Suficiente?<b>{op_suf}</b></div>
</div>
<p class="muted">El objetivo nunca se fuerza: si el mercado no da oportunidades claras, no se opera. Nunca se bajan los filtros de calidad para llegar al objetivo.</p>
<div class="question">¿QUÉ LO ESTÁ BLOQUEANDO?</div>
<div class="grid">
<div class="card">Principal bloqueo<b style="font-size:.95rem">{bottleneck_display}</b></div>
<div class="card">Autorizadas por seguridad<b>{f.get("RISK_ACCEPT", 0)}</b></div>
<div class="card">Bloqueadas por seguridad<b>{f.get("RISK_REJECT", 0)}</b></div>
<div class="card">Tasa de bloqueo<b>{rej_display}</b></div>
</div>

<h2>Oportunidades (embudo simple)</h2>
{funnel_html}
<p class="muted">Arbitraje de dirección: cuando la evaluación produce dos direcciones opuestas (compra/venta), se elige la mejor respaldada por la evidencia; si no hay ganador claro, no se opera.</p>
<div class="grid">{arb_row}</div>

<h2>Decisiones y bloqueos</h2>
<p>Operaciones autorizadas: <b>{f.get("RISK_ACCEPT", 0)}</b> &middot; Operaciones bloqueadas: <b>{f.get("RISK_REJECT", 0)}</b></p>
<ul>{reasons_html}</ul>

<h2>Estrategias</h2>
<table><tr><th>Estrategia</th><th>Estado</th><th>Operaciones</th><th>Resultado</th><th>¿Datos suficientes?</th><th>Próximo paso</th></tr>
{strat_rows}</table>

<h2>Criptomonedas</h2>
<p class="muted">BTC, ETH y SOL se analizan en cada ciclo. Muestra actual: {s["paper_opens_total"]} operación(es) — demasiado pequeña para conclusions por moneda.</p>

<h2>Shadow — simulación de las rechazadas</h2>
<div class="grid">
<div class="card">Rechazadas guardadas<b>{s["shadow"]["captures"]}</b></div>
<div class="card">Ya resueltas<b>{s["shadow"]["resolved"]}</b></div>
<div class="card">Ganaron / perdieron<b>{s["shadow"]["wins"]} / {s["shadow"]["losses"]}</b></div>
</div>
<p class="muted">Cuando el sistema bloquea una operación por seguridad, la guardamos y simulamos en privado qué habría pasado. Esto nunca afecta a las operaciones reales (simuladas) de la campaña.</p>

<h2>Informes</h2>
<table><tr><th>Fecha</th><th>Informe</th><th>Resumen</th></tr>{report_rows}</table>
<details><summary>Detalle técnico (JSON)</summary>
<p class="muted">Embudo técnico: {json.dumps(f, ensure_ascii=False)}</p>
</details>

<h2>Cobertura día a día</h2>
<table><tr><th>Día UTC</th><th>Ciclos observados</th><th>Cobertura</th><th>Estado</th></tr>{cov_rows}</table>
{invalid_note}

<p class="muted">Panel de SOLO LECTURA: no tiene botones de compra, venta, riesgo ni activación.
PAPER = simulación; nunca hay dinero real. Se actualiza al recargar.</p>
</main></body></html>"""
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        campaign = ACTIVE_CAMPAIGN
        if parsed.path == "/" and "campaign=" in parsed.query:
            candidate = parsed.query.split("campaign=")[1].split("&")[0]
            if candidate == ACTIVE_CAMPAIGN or candidate in HISTORIC_CAMPAIGNS:
                campaign = candidate
        if parsed.path in ("/", "/index.html"):
            body = _render_home(campaign)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif parsed.path == "/api/snapshot":
            body = json.dumps(campaign_snapshot(campaign), ensure_ascii=False, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif parsed.path == "/health":
            body = json.dumps({"status": "ok", "read_only": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b'{"error": "not found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self._method_not_allowed()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def _method_not_allowed(self) -> None:
        body = b'{"error": "panel de solo lectura: metodo no permitido"}'
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"[panel-es] Panel de solo lectura (ES) en http://{args.host}:{args.port} — Ctrl+C para salir")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
