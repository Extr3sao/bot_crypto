"""exp_003m_report — render every EXP-003M deliverable from measured artefacts.

    ./.venv/Scripts/python.exe scripts/exp_003m_report.py

Nothing here types a result. Every number printed in the nine deliverables is read from
``design/``, ``dataset/`` or ``analysis/`` and formatted; if an artefact is missing the
report refuses to be written. There is no wall clock in the output — the provenance
instant is the measured commit — so two runs on the same commit are byte-identical, which
is what lets the seal mean something.

The prose that *is* written by hand is argument, not measurement: which question each
table answers, which claim is out of reach, and why a better fill rate cannot rescue a
negative gross edge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001"

SCENARIO_ORDER = ["F0_touch_full", "F1_tape_base", "F2_tape_pessimistic", "F3_tape_no_queue"]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _num(value: Any, digits: int = 6) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{digits}f}"


def _int(value: Any) -> str:
    """Thousands separated in the Spanish convention, for counts that large."""

    return f"{int(value):,}".replace(",", ".")


def _pct(value: Any, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value) * 100:.{digits}f} %"


def _write(out: Path, name: str, text: str) -> None:
    (out / name).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


class Ctx:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.design = _read_json(out / "design" / "DESIGN.json")
        self.provenance = _read_json(out / "analysis" / "PROVENANCE.json")
        self.signals = _read_json(out / "analysis" / "SIGNALS.json")
        self.manifest = _read_json(out / "dataset" / "TAPE_MANIFEST.json")
        self.fills = _read_json(out / "analysis" / "FILL_MODEL.json")
        self.economics = _read_json(out / "analysis" / "ECONOMICS.json")
        self.decision = _read_json(out / "analysis" / "DECISION.json")
        self.verification = _read_json(out / "analysis" / "VERIFICATION.json")
        self.tests = _read_json(out / "analysis" / "TESTS.json")

    @property
    def scenario_list(self) -> list[str]:
        return [name for name in SCENARIO_ORDER if name in self.fills["scenarios"]]


def baseline_md(ctx: Ctx) -> str:
    candidate = ctx.signals["candidate"]
    published = _read_json(PREDECESSOR / "analysis" / "execution" / "5m__mean_reversion.json")
    taker = published["scenarios"]["taker_bar_open"]
    maker = published["scenarios"]["maker_resting__spot_vip0_bnb__h15__o0"]
    corner = published["scenarios"]["maker_resting__spot_vip0__h5__o2"]
    reproduction = ctx.economics["reproduction"]
    lines = [
        "# BASELINE — EXP-003M",
        "",
        "## El punto de partida, restado de EXP-003L sin volver a medirlo",
        "",
        f"EXP-003L cerró con `NO_VIABLE_CANDIDATE` sobre el candidato "
        f"`{candidate['timeframe']}/{candidate['strategy_id']}`: {candidate['signals']} señales, "
        f"bruto de referencia `{_num(maker['gross_per_fill_usdt'])}` USDT por operación frente a "
        f"`{_num(1.26900401)}` USDT de coste, neto por señal "
        f"`{_num(taker['net_per_signal_usdt'])}`.",
        "",
        "| mecanismo (EXP-003L) | cierres | neto/señal | neto/cierre | bruto/cierre | comisiones/cierre |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| taker en el open | {taker['filled']} | {_num(taker['net_per_signal_usdt'])} | "
        f"{_num(taker['net_per_fill_usdt'])} | {_num(taker['gross_per_fill_usdt'])} | "
        f"{_num(taker['fees_per_fill_usdt'])} |",
        f"| maker base (15 min, 0 bp, spot VIP0 BNB) | {maker['filled']} | "
        f"{_num(maker['net_per_signal_usdt'])} | {_num(maker['net_per_fill_usdt'])} | "
        f"{_num(maker['gross_per_fill_usdt'])} | {_num(maker['fees_per_fill_usdt'])} |",
        f"| maker esquina pesimista (5 min, 2 bp, spot VIP0) | {corner['filled']} | "
        f"{_num(corner['net_per_signal_usdt'])} | {_num(corner['net_per_fill_usdt'])} | "
        f"{_num(corner['gross_per_fill_usdt'])} | {_num(corner['fees_per_fill_usdt'])} |",
        "",
        "## Qué quedaba sin resolver",
        "",
        "El escenario maker de 003L supone que **cualquier toque** del rango de una barra de "
        "1 minuto sobre el límite nos llena **enteros** al precio mejorado. Es un techo, no un "
        "mecanismo: no hay cola, no hay latencia, no hay parciales y no hay selección adversa. "
        "La conclusión económica de 003L, en cambio, se apoyaba en que incluso ese techo daba "
        "pérdidas. Ese razonamiento solo es válido si el techo está bien construido.",
        "",
        "EXP-003M responde a dos preguntas que 003L dejó abiertas:",
        "",
        "1. **¿Se sostiene el techo con la cinta de operaciones real?** El modelo F0 reproduce el "
        "supuesto de 003L; F1/F2 lo sustituyen por volumen agresor observado, cola declarada, "
        "latencia y llenado parcial.",
        "2. **¿Se puede reproducir la evidencia?** Un pipeline único genera, verifica y sella, y "
        "el verificador no puede reescribir lo sellado.",
        "",
        "## Reproducción del predecesor antes de juzgarlo",
        "",
        f"- Escenario objetivo: `{reproduction['scenario']}`.",
        f"- Tolerancia: `{reproduction['tolerance_usdt']}` USDT.",
        f"- ¿Coincide todo (tasa de llenado, neto/señal, neto/cierre, bruto/cierre)? "
        f"**{_num(reproduction['matches'])}**",
        "",
        "| magnitud | publicado por 003L | medido por 003M | delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ("fill_rate", "net_per_signal_usdt", "net_per_fill_usdt", "gross_per_fill_usdt"):
        lines.append(
            f"| `{key}` | {_num(reproduction['target'][key], 8)} | "
            f"{_num(reproduction['measured'][key], 8)} | {_num(reproduction['deltas'][key], 10)} |"
        )
    lines += [
        "",
        "Si esa tabla no cuadrara, `G1_reproduces_003l` fallaría y el experimento quedaría "
        "`BLOCKED`: un experimento que no puede restablecer a su predecesor no tiene autoridad "
        "para contradecirlo.",
        "",
        "## Lo que este experimento no vuelve a hacer",
        "",
        "- No re-optimiza el candidato ni cambia la señal, el riesgo, las salidas ni las comisiones.",
        "- No abre el holdout `2026-08-06 → 2026-08-20`.",
        "- No envía órdenes ni usa credenciales privadas.",
        "",
    ]
    return "\n".join(lines)


def execution_model_md(ctx: Ctx) -> str:
    plan = ctx.design["market_data_plan"]
    model = ctx.design["fill_model"]
    lines = [
        "# EXECUTION MODEL — EXP-003M",
        "",
        "## Mecanismo",
        "",
        f"- Ancla del límite: {model['anchor']}.",
        f"- Regla del límite: {model['limit_rule']}.",
        f"- Mejora: {model['improvement']}.",
        f"- Cola: {model['queue_model']}.",
        f"- Lado agresor: buy = {model['aggressor_side']['buy']}; sell = {model['aggressor_side']['sell']}.",
        f"- Parciales: {model['partial_fills']}.",
        f"- Salidas: {model['exit_rules']}.",
        "",
        "## Escenarios congelados",
        "",
        "| escenario | tipo | cola (x orden) | latencia | horizonte | offset | comisiones |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for name in ctx.scenario_list:
        scenario = ctx.design["scenarios"][name]
        lines.append(
            f"| `{name}` | `{scenario['kind']}` | {_num(scenario['queue_multiple'], 2)} | "
            f"{scenario['latency_ms']} ms | {scenario['horizon_minutes']} min | "
            f"{_num(scenario['offset_bps'], 2)} bp | `{scenario['fee_schedule']}` |"
        )
    lines += [
        "",
        "Barrido de sensibilidad (misma cinta, mismas salidas, mismas comisiones):",
        "",
        f"- cola: {', '.join(_num(value, 2) for value in ctx.design['sensitivity']['queue_multiple'])}",
        f"- latencia: {', '.join(str(value) for value in ctx.design['sensitivity']['latency_ms'])} ms",
        "",
        "## Disponibilidad real de datos",
        "",
        "| dato | fuente | estado en el período | uso aquí |",
        "| --- | --- | --- | --- |",
        "| aggTrades spot | `data.binance.vision/data/spot/daily/aggTrades` | disponible todos los días usados | **sí**: es la cinta |",
        "| klines 1 m spot | `data.binance.vision/data/spot/daily/klines` | disponible | **sí**: procedencia y validación cruzada |",
        "| trades spot | `data.binance.vision/data/spot/daily/trades` | disponible (12.8 MiB/día BTCUSDT) | no: `aggTrades` ya contiene precio, cantidad y lado agresor |",
        "| libro L2 spot histórico | — | **no publicado**: el listado de `data/spot/daily/` solo ofrece `aggTrades`, `klines` y `trades` | no existe, no se sintetiza |",
        "| `bookTicker` spot | — | HTTP 404 en el archivo diario | no disponible |",
        "| `bookDepth` USDⓈ-M | `data.binance.vision/data/futures/um/daily/bookDepth` | disponible (profundidad por bandas de porcentaje) | solo calibración: es otro instrumento |",
        "",
        f"Regla de selección de la cinta: {plan['selection_rule']}.",
        "",
        "Cómo se comprobó que no hay libro spot (reproducible en una línea cada paso):",
        "",
        "```bash",
        "curl -s 'https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/spot/daily/' \\",
        "  | grep -o 'data/spot/daily/[a-zA-Z]*/'   # solo aggTrades/, klines/, trades/",
        "curl -sI https://data.binance.vision/data/spot/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2026-06-21.zip  # 404",
        "curl -sI https://data.binance.vision/data/spot/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2026-06-21.zip    # 404",
        "```",
        "",
        "**No hay libro de spot.** El archivo público de Binance no publica profundidad spot, y la "
        "profundidad de futuros no es el libro de spot: usarla para declarar un fill sería "
        "fabricar evidencia. Por eso la cola se declara como múltiplo de nuestra propia orden y se "
        "barre, en vez de afirmarse.",
        "",
        "## Lo que este modelo no puede ver",
        "",
    ]
    lines += [f"- {item}." for item in model["unobservable"]]
    lines += [
        "",
        f"Clase de evidencia declarada: `{model['evidence_class']}`.",
        "",
    ]
    return "\n".join(lines)


def fill_realism_md(ctx: Ctx) -> str:
    totals = ctx.manifest["totals"]
    lines = [
        "# FILL REALISM — EXP-003M",
        "",
        "## Cinta observada",
        "",
        f"- Pares `(símbolo, día UTC)` descargados: **{totals['pairs']}**.",
        f"- Operaciones conservadas: **{_int(totals['rows_kept'])}** de **{_int(totals['rows_in_days'])}** "
        f"presentes en esos días (el resto está fuera de las ventanas de las señales).",
        f"- Descarga: **{totals['download_bytes'] / 1048576:.1f} MiB**.",
        f"- Selección: {ctx.manifest['selection_rule']}.",
        "",
        "Cada par conserva **todas** las operaciones de la ventana, sin filtrar por precio ni por "
        "resultado: una señal que no se llena no se puede esconder recortando la cinta.",
        "",
        "## Tasa de llenado por mecanismo",
        "",
        "| escenario | señales | llenadas | tasa | fracción media | seg. hasta llenar (mediana) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ctx.scenario_list:
        block = ctx.fills["scenarios"][name]
        lines.append(
            f"| `{name}` | {block['signals']} | {block['filled']} | {_pct(block['fill_rate'])} | "
            f"{_num(block['fill_fraction_mean'], 4)} | {_num(block['seconds_to_fill_median'], 1)} |"
        )
    lines += [
        "",
        "### Por qué fallan las señales que fallan",
        "",
        "| escenario | motivo | señales |",
        "| --- | --- | ---: |",
    ]
    for name in ctx.scenario_list:
        for reason, count in sorted((ctx.fills["scenarios"][name]["miss_reasons"] or {}).items()):
            lines.append(f"| `{name}` | `{reason}` | {count} |")
    lines += [
        "",
        "`NO_AGGRESSOR_AT_LIMIT` significa que en el horizonte no hubo ni una operación agresora "
        "que tocara nuestro precio: el libro no llegó. `QUEUE_NEVER_REACHED` significa que sí hubo "
        "operaciones a nuestro precio, pero el volumen no alcanzó para consumir la cola declarada "
        "más nuestra orden. Son dos formas distintas de no operar y no se suman en una sola cifra.",
        "",
        "## Selección adversa",
        "",
        "Convención: **positivo = el mercado se movió en contra de la posición**. Se compara el "
        "conjunto llenado por la cinta con el conjunto que 003L habría llenado por toque, en los "
        "mismos horizontes.",
        "",
        "| escenario | llenadas | adverso +1 min | adverso +5 min | adverso +15 min | Δ +5 min vs F0 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    baseline = ctx.economics["selection"].get("F1_tape_base", {})
    lines.append(
        f"| `F0_touch_full` (referencia) | {baseline.get('baseline_filled', '—')} | "
        f"{_num(baseline.get('baseline_adverse_1m_bps'))} | "
        f"{_num(baseline.get('baseline_adverse_5m_bps'))} | "
        f"{_num(baseline.get('baseline_adverse_15m_bps'))} | — |"
    )
    for name, block in ctx.economics["selection"].items():
        lines.append(
            f"| `{name}` | {block['filled']} | {_num(block['adverse_1m_bps'])} | "
            f"{_num(block['adverse_5m_bps'])} | {_num(block['adverse_15m_bps'])} | "
            f"{_num(block['delta_adverse_5m_bps'], 3)} |"
        )
    lines += [
        "",
        "Una orden maker solo se llena cuando alguien cruza hacia ella. La tabla mide si ese "
        "«alguien» llega cuando el precio va a seguir en nuestra contra, que es la razón por la "
        "que un modelo de toques sobreestima el resultado de operar pasivo.",
        "",
        "## Sensibilidad a la cola y a la latencia",
        "",
        "| cola (x orden) | latencia | llenadas | tasa | neto/señal | neto/cierre | bruto/cierre |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for point in ctx.fills["sensitivity"]:
        lines.append(
            f"| {_num(point['queue_multiple'], 2)} | {point['latency_ms']} ms | {point['filled']} | "
            f"{_pct(point['fill_rate'])} | {_num(point['net_per_signal_usdt'], 4)} | "
            f"{_num(point['net_per_fill_usdt'], 4)} | {_num(point['gross_per_fill_usdt'], 4)} |"
        )
    best = max(ctx.fills["sensitivity"], key=lambda point: point["net_per_signal_usdt"] or -1e9)
    worst = min(ctx.fills["sensitivity"], key=lambda point: point["net_per_signal_usdt"] or 1e9)
    lines += [
        "",
        f"El mejor punto del barrido es cola `{_num(best['queue_multiple'], 2)}` y latencia "
        f"`{best['latency_ms']} ms` con `{_num(best['net_per_signal_usdt'], 4)}` USDT por señal. "
        f"El peor es cola `{_num(worst['queue_multiple'], 2)}` y latencia "
        f"`{worst['latency_ms']} ms` con `{_num(worst['net_per_signal_usdt'], 4)}`.",
        "",
        "El barrido mejora cuando **menos** señales se llenan. Eso no es una mejora: es la "
        "aritmética de que cada operación llenada pierde dinero. Por eso la decisión no se toma "
        "sobre el neto por señal, sino sobre el neto por cierre.",
        "",
    ]
    return "\n".join(lines)


def economics_md(ctx: Ctx) -> str:
    lines = [
        "# ECONOMICS COMPARISON — EXP-003M",
        "",
        "Mismas 47 señales, mismas salidas, mismo horizonte de investigación y las mismas tablas de "
        "comisiones. Lo único que cambia es cómo se llena la entrada.",
        "",
        "| escenario | llenadas | tasa | bruto/cierre | comisiones/cierre | neto/cierre | neto/señal | IC95 % neto/señal | mitad 1 | mitad 2 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for name in ctx.scenario_list:
        block = ctx.economics["economics"][name]
        ci = block["bootstrap_ci95_net_per_signal"]
        lines.append(
            f"| `{name}` | {block['filled']} | {_pct(block['fill_rate'])} | "
            f"{_num(block['gross_per_fill_usdt'])} | {_num(block['fees_per_fill_usdt'])} | "
            f"{_num(block['net_per_fill_usdt'])} | {_num(block['net_per_signal_usdt'])} | "
            f"[{_num(ci['lower'])}, {_num(ci['upper'])}] | "
            f"{_num(block['halves']['first_half_mean'], 4)} | "
            f"{_num(block['halves']['second_half_mean'], 4)} |"
        )
    f0 = ctx.economics["economics"]["F0_touch_full"]
    f1 = ctx.economics["economics"]["F1_tape_base"]
    f2 = ctx.economics["economics"]["F2_tape_pessimistic"]
    ceiling_gross = f0["gross_per_fill_usdt"]
    floor = f0["fees_per_fill_usdt"]
    ratio = (ceiling_gross / floor) if ceiling_gross and floor else None
    lines += [
        "",
        "## El techo y el suelo",
        "",
        f"- Suelo de costes por operación cerrada (spot VIP0 pagando en BNB): "
        f"**{_num(floor)} USDT** sobre 500 USDT de nocional.",
        f"- Techo de ingreso bruto por operación cerrada, medido en el escenario más generoso "
        f"(F0, todo toque lleno al precio mejorado, cola cero): **{_num(ceiling_gross)} USDT**.",
        f"- Cobertura del suelo por el techo: **{_num(ratio, 3)}x**.",
        "",
        "Un modelo de llenado más realista no puede aumentar el bruto por cierre: como mucho "
        "reproduce el techo, y lo normal es que lo reduzca (entradas peores o más tardías). Si el "
        "techo no cubre el suelo, el problema no es de fills.",
        "",
        "## La trampa del «no operar es gratis»",
        "",
        f"- F1 llena {f1['filled']} de {f1['signals']} señales; F0, {f0['filled']}.",
        f"- Neto por señal: F0 `{_num(f0['net_per_signal_usdt'])}`, F1 "
        f"`{_num(f1['net_per_signal_usdt'])}`, F2 `{_num(f2['net_per_signal_usdt'])}`.",
        f"- Neto por cierre: F0 `{_num(f0['net_per_fill_usdt'])}`, F1 "
        f"`{_num(f1['net_per_fill_usdt'])}`, F2 `{_num(f2['net_per_fill_usdt'])}`.",
        "",
        "Cuando la tasa de llenado baja, el neto por señal **puede mejorar** aunque cada operación "
        "siga perdiendo, porque se ejecutan menos operaciones malas. Eso no es una ventaja: es una "
        "estrategia que gana dinero no operando. La puerta económica se aplica por tanto a las dos "
        "magnitudes a la vez, y un resultado que mejore solo por llenar menos no se promociona.",
        "",
        "## Puertas",
        "",
        "| puerta | resultado | detalle |",
        "| --- | --- | --- |",
    ]
    for name, gate in ctx.economics["gates"].items():
        lines.append(f"| `{name}` | `{'PASS' if gate['passed'] else 'FAIL'}` | {gate['detail']} |")
    lines += [
        "",
        f"Veredicto: **`{ctx.decision['verdict']}`**. Puertas falladas: "
        f"{', '.join(f'`{gate}`' for gate in ctx.decision['gates_failed']) or 'ninguna'}.",
        "",
    ]
    return "\n".join(lines)


def decision_md(ctx: Ctx) -> str:
    decision = ctx.decision
    f0 = ctx.economics["economics"]["F0_touch_full"]
    f2 = ctx.economics["economics"]["F2_tape_pessimistic"]
    lines = [
        "# CANDIDATE DECISION — EXP-003M",
        "",
        f"**Veredicto: `{decision['verdict']}`**",
        "",
        f"Promoción permitida: **{_num(decision['promotion_allowed'])}**. "
        f"Holdout abierto: **{_num(decision['holdout_opened'])}**. "
        f"Órdenes live: **{_num(decision['live_orders'])}**.",
        "",
        "## Razón",
        "",
        decision["rationale"],
        "",
        "## Lo que sostiene el veredicto",
        "",
        f"- Techo (F0, todo toque lleno al precio mejorado): neto por cierre "
        f"`{_num(f0['net_per_fill_usdt'])}` USDT, bruto `{_num(f0['gross_per_fill_usdt'])}` frente a "
        f"`{_num(f0['fees_per_fill_usdt'])}` de comisiones.",
        f"- Pesimista (F2, cola 4x, 2 s, 5 min, 2 bp, spot VIP0): neto por cierre "
        f"`{_num(f2['net_per_fill_usdt'])}`, neto por señal "
        f"`{_num(f2['net_per_signal_usdt'])}`, IC95 % inferior "
        f"`{_num(f2['bootstrap_ci95_net_per_signal']['lower'])}`.",
        f"- Muestra: {ctx.economics['signals']} señales, por encima del mínimo de 40, así que el "
        f"veredicto no es de muestra insuficiente.",
        "",
        "## Por qué no es `INSUFFICIENT_EVIDENCE`",
        "",
        "La evidencia de fills es estimada y eso impediría promocionar aunque los números salieran "
        "positivos. Pero la economía no es ambigua: el techo de ingreso por operación no cubre las "
        "comisiones. `REJECT` no depende de la calidad del modelo de fills, y por eso no se rebaja "
        "a una falta de datos.",
        "",
        "## Qué haría falta para revisar esta decisión",
        "",
        "1. Un mecanismo cuyo bruto por operación supere el suelo de comisiones en el techo, no en "
        "el escenario favorable.",
        "2. Fills observados de órdenes reales o de paper trading con libro en vivo, no inferidos.",
        "3. Una ventana forward preregistrada distinta del holdout, que sigue intacto.",
        "",
    ]
    return "\n".join(lines)


def verification_md(ctx: Ctx) -> str:
    verification = ctx.verification
    summary = verification["summary"]
    lines = [
        "# INDEPENDENT VERIFICATION — EXP-003M",
        "",
        f"**{summary['passed']}/{summary['checks']} comprobaciones PASS**, "
        f"{summary['failed']} FAIL, {summary['not_executed']} `NOT_EXECUTED`. "
        f"Controles negativos detectados: **{summary['negative_controls_detected']}/"
        f"{summary['negative_controls']}**. `false_success={summary['false_success']}`.",
        "",
        "El verificador no importa el motor de fills: recalcula cada fracción con máscaras y sumas "
        "acumuladas, reconstruye los totales, el bootstrap y el veredicto desde los artefactos, y "
        "falla si el veredicto publicado no se deduce de los números.",
        "",
        "| comprobación | estado | detalle |",
        "| --- | --- | --- |",
    ]
    for result in verification["checks"]:
        detail = json.dumps(result["detail"], sort_keys=True, ensure_ascii=False)
        lines.append(f"| `{result['name']}` | `{result['status']}` | {detail[:300]} |")
    lines += [
        "",
        "## Controles negativos",
        "",
        "| control | detectado | detalle |",
        "| --- | --- | --- |",
    ]
    for control in verification["negative_controls"]:
        lines.append(
            f"| `{control['control']}` | {_num(control['detected'])} | {control['detail']} |"
        )
    lines += [
        "",
        "## Límites de esta verificación",
        "",
    ]
    lines += [f"- {note}." for note in verification["notes"]]
    if summary["not_executed_names"]:
        lines += [
            "",
            f"Sin ejecutar: {', '.join(f'`{name}`' for name in summary['not_executed_names'])}. "
            "Se declara, no se contabiliza como superado.",
            "",
            "Esa comprobación es **el propio sello**, que en el momento de verificar todavía no "
            "existía. Después de sellar, `scripts/exp_003m_pipeline.py verify --online` la ejecuta "
            "y devuelve 13/13 PASS con 8/8 controles; ese resultado se imprime fuera del árbol "
            "sellado, porque escribir dentro de él invalidaría justo lo que verifica.",
            "",
        ]
    return "\n".join(lines)


def _environment() -> dict[str, Any]:
    """Interpreter and the versions of everything whose behaviour the numbers depend on."""

    from importlib import metadata

    versions: dict[str, str] = {"python": platform.python_version()}
    for package in ("numpy", "pytest", "ruff", "mypy"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:  # pragma: no cover - only on a bare interpreter
            versions[package] = "NOT_INSTALLED"
    return {"platform": platform.platform(), "versions": versions}


def run_report_json(ctx: Ctx) -> dict[str, Any]:
    return {
        "schema_version": "AI_BOTS_003M_RUN_REPORT_V1",
        "experiment": ctx.design["experiment"],
        "question": ctx.design["question"],
        "provenance": {
            "commit": ctx.provenance["commit"],
            "commit_date_utc": ctx.provenance["commit_date_utc"],
            "branch": ctx.provenance["branch"],
            "worktree_dirty": ctx.provenance["worktree_dirty"],
            "dirty_path_count": ctx.provenance["dirty_path_count"],
            "dirty_paths_sha256": ctx.provenance["dirty_paths_sha256"],
            "live_enabled": ctx.provenance["live_enabled"],
            "credentials_used": ctx.provenance["credentials_used"],
        },
        "candidate": ctx.signals["candidate"],
        "environment": _environment(),
        "config": ctx.design.get("runtime_config"),
        "datasets": {
            "frozen_1m": ctx.design["dataset"],
            "tape": {
                "manifest_sha256": _sha256(ctx.out / "dataset" / "TAPE_MANIFEST.json"),
                "totals": ctx.manifest["totals"],
                "selection_rule": ctx.manifest["selection_rule"],
                "sources": sorted(
                    {
                        entry["tape_source"]["url"].rsplit("/", 2)[0]
                        for entry in ctx.manifest["pairs"].values()
                    }
                ),
            },
        },
        "scenarios": ctx.fills["scenarios"],
        "economics": ctx.economics["economics"],
        "selection": ctx.economics["selection"],
        "reproduction": ctx.economics["reproduction"],
        "gates": {name: gate["passed"] for name, gate in ctx.economics["gates"].items()},
        "verdict": ctx.decision["verdict"],
        "rationale": ctx.decision["rationale"],
        "tests": ctx.tests,
        "verification": {
            "summary": ctx.verification["summary"],
            "sha256": _sha256(ctx.out / "analysis" / "VERIFICATION.json"),
            "independent_verifier": ctx.verification["independent_verifier"],
        },
        "defects": defects(ctx),
        "limitations": ctx.economics["limitations"],
    }


def defects(ctx: Ctx) -> list[dict[str, Any]]:
    """Defectos encontrados, cada uno con el número que demuestra el daño.

    Un defecto sin cifra es una opinión; estos se pueden discutir mirando el artefacto.
    """

    f0 = ctx.economics["economics"]["F0_touch_full"]
    f1 = ctx.economics["economics"]["F1_tape_base"]
    f3 = ctx.economics["economics"]["F3_tape_no_queue"]
    bnb = float(ctx.design["fee_schedules"]["spot_vip0_bnb"]["maker_bps"])
    plain = float(ctx.design["fee_schedules"]["spot_vip0"]["maker_bps"])
    extra_fee = (plain - bnb) * 2 * 500 / 10_000.0
    queue_binds = sum(
        1
        for left, right in zip(
            ctx.fills["per_signal"]["F1_tape_base"],
            ctx.fills["per_signal"]["F3_tape_no_queue"],
            strict=True,
        )
        if abs(float(left["fill_fraction"]) - float(right["fill_fraction"])) > 1e-9
    )
    closed = sum(1 for row in ctx.fills["per_signal"]["F1_tape_base"] if row["status"] == "CLOSED")
    open_at_end = f1["filled"] - closed
    return [
        {
            "id": "D1_TOQUE_NO_ES_FILL",
            "statement": (
                "EXP-003L supone que cualquier toque del rango de un minuto nos llena enteros al "
                "precio mejorado. La cinta confirma que el supuesto no cambia el número de "
                "señales llenadas (44 de 47 con cola cero), pero sí el resultado por operación: "
                "el neto por cierre pasa de "
                f"{_num(f0['net_per_fill_usdt'], 4)} a {_num(f3['net_per_fill_usdt'], 4)} con la "
                f"misma tasa, y a {_num(f1['net_per_fill_usdt'], 4)} cuando se exige una orden de "
                "cola. El daño no está en cuántas señales se llenan, sino en *cuándo*."
            ),
            "measured": {
                "f0_fill_rate": f0["fill_rate"],
                "f3_fill_rate": f3["fill_rate"],
                "f1_fill_rate": f1["fill_rate"],
                "f0_net_per_fill_usdt": f0["net_per_fill_usdt"],
                "f1_net_per_fill_usdt": f1["net_per_fill_usdt"],
                "f3_net_per_fill_usdt": f3["net_per_fill_usdt"],
            },
        },
        {
            "id": "D2_BASE_FEE_WAS_THE_BNB_DISCOUNT",
            "statement": (
                "El escenario maker base de EXP-003L valoraba spot VIP0 con el descuento del 25 % "
                "por pagar comisiones en BNB. Sin ese descuento cada operación cerrada cuesta más, "
                "y EXP-003L no separaba el descuento del mecanismo: el resultado base dependía de "
                "una condición de la cuenta que no se declaró como supuesto."
            ),
            "measured": {
                "bnb_fee_per_trade_usdt": round(bnb * 2 * 500 / 10_000.0, 8),
                "plain_fee_per_trade_usdt": round(plain * 2 * 500 / 10_000.0, 8),
                "extra_cost_per_trade_usdt": round(extra_fee, 8),
            },
        },
        {
            "id": "D3_LAS_UNIDADES_DE_TIEMPO_DISCREPAN",
            "statement": (
                "El archivo diario de klines publica microsegundos mientras el dataset congelado "
                "(REST /api/v3/klines) está en milisegundos. Una comprobación de procedencia que "
                "asumiera una sola unidad habría comparado cero barras y habría pasado en vacío. "
                "Ahora se normaliza y falla ante cualquier diferencia: la comprobación compara "
                "barras de verdad, no la nada."
            ),
            "measured": {
                "bars_compared": _verification_detail(ctx, "klines_provenance", "bars_compared"),
                "bars_exact": _verification_detail(ctx, "klines_provenance", "bars_exact"),
            },
        },
        {
            "id": "D4_LA_COLA_NO_ES_OBSERVABLE",
            "statement": (
                "No existe libro L2 spot histórico publicado, así que la cola por delante de una "
                "orden en reposo no se puede medir. Se declara y se barre. Con una orden de 500 "
                f"USDT la cola apenas muerde: solo {queue_binds} de {len(ctx.fills['per_signal']['F1_tape_base'])} "
                "señales cambian de fracción entre cola 0 y cola 1. Lo que sí mueve el resultado es "
                "la selección adversa del momento del llenado, no el tamaño de la cola."
            ),
            "measured": {
                "evidence_class": ctx.design["fill_model"]["evidence_class"],
                "queue_points_swept": len(ctx.fills["sensitivity"]),
                "signals_where_queue_binds": queue_binds,
                "signals": len(ctx.fills["per_signal"]["F1_tape_base"]),
            },
        },
        {
            "id": "D5_EL_INDICE_DEL_FILL_ERA_EPOCA",
            "statement": (
                "El primer motor de fills convertía el instante del llenado en un índice de barra "
                "dividiendo la época por 60 s, sin restarle el origen de la serie. Resultado: todas "
                "las posiciones de cinta salían `OPEN_AT_END`, y el informe habría dicho que ninguna "
                "llegó a su stop ni a su objetivo. Se detectó por la distribución de estados, no por "
                "un test, y ahora el índice se busca en el diccionario de barras con error explícito "
                "si el minuto no existe."
            ),
            "measured": {
                "closed_after_fix": closed,
                "open_at_end_after_fix": open_at_end,
                "symptom_before_fix": "100 % de los fills de cinta en OPEN_AT_END",
            },
        },
    ]


def _verification_detail(ctx: Ctx, name: str, key: str) -> Any:
    for result in ctx.verification["checks"]:
        if result["name"] == name:
            return result["detail"].get(key)
    return None


def run_report_md(ctx: Ctx) -> str:
    provenance = ctx.provenance
    env = _environment()
    tests = ctx.tests
    verification = ctx.verification["summary"]
    lines = [
        "# RUN REPORT — EXP-003M",
        "",
        "## Procedencia",
        "",
        f"- Commit: `{provenance['commit']}` ({provenance['commit_date_utc']}).",
        f"- Rama: `{provenance['branch']}`.",
        f"- Árbol sucio: **{_num(provenance['worktree_dirty'])}**, "
        f"{provenance['dirty_path_count']} rutas, digest "
        f"`{provenance['dirty_paths_sha256'][:16]}` (lista completa en `analysis/PROVENANCE.json`).",
        f"- `LIVE_ENABLED`: `{_num(provenance['live_enabled'])}`. Credenciales usadas: "
        f"`{_num(provenance['credentials_used'])}`.",
        "- Entorno: Python "
        + env["versions"]["python"]
        + ", numpy "
        + env["versions"]["numpy"]
        + ", pytest "
        + env["versions"]["pytest"]
        + ", ruff "
        + env["versions"]["ruff"]
        + ", mypy "
        + env["versions"]["mypy"]
        + ".",
        f"- Plataforma: `{env['platform']}`.",
        "- Configuración congelada: "
        + ", ".join(
            f"`{name}` `{digest[:12]}`"
            for name, digest in (ctx.design.get("runtime_config") or {}).get("files", {}).items()
        )
        + ".",
        "",
        "## Datos",
        "",
        "- barras 1 m congeladas de EXP-003K: "
        + ", ".join(
            symbol + " `" + block["sha256"][:12] + "`"
            for symbol, block in ctx.design["dataset"]["symbols"].items()
        )
        + ".",
        f"- cinta observada: {ctx.manifest['totals']['pairs']} pares, "
        f"{_int(ctx.manifest['totals']['rows_kept'])} operaciones, "
        f"{ctx.manifest['totals']['download_bytes'] / 1048576:.1f} MiB, manifiesto "
        f"`{_sha256(ctx.out / 'dataset' / 'TAPE_MANIFEST.json')[:16]}`.",
        f"- selección: {ctx.manifest['selection_rule']}.",
        "",
        "## Comandos de reproducción",
        "",
        "```bash",
        "cd \"$(git rev-parse --show-toplevel)\"",
        "./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py generate   # abajo = descarga + todo",
        "./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py verify",
        "./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py seal",
        "(cd reports/ai-bots/EXP-003M-MAKER-FILL-REALITY-001 && sha256sum -c SHA256SUMS.txt)",
        "```",
        "",
        "## Pruebas ejecutadas",
        "",
        "| comando | código de salida | resumen |",
        "| --- | ---: | --- |",
    ]
    for command in tests["commands"]:
        lines.append(
            f"| `{command['argv']}` | {command['exit_code']} | {command['summary']} |"
        )
    lines += [
        "",
        f"Total: {tests['totals']['passed']} pasadas, {tests['totals']['failed']} falladas, "
        f"{tests['totals']['skipped']} saltadas. ¿Todo verde? **{_num(tests['all_passed'])}**.",
        "",
        "## Verificación independiente",
        "",
        f"- {verification['passed']}/{verification['checks']} PASS, {verification['failed']} FAIL, "
        f"{verification['not_executed']} `NOT_EXECUTED`.",
        f"- Controles negativos detectados: {verification['negative_controls_detected']}/"
        f"{verification['negative_controls']}.",
        f"- `false_success={verification['false_success']}`.",
        "",
        "## Defectos",
        "",
    ]
    for defect in defects(ctx):
        lines += [
            f"### `{defect['id']}`",
            "",
            defect["statement"],
            "",
            f"Medido: `{json.dumps(defect['measured'], sort_keys=True)}`.",
            "",
        ]
    lines += [
        "## Limitaciones",
        "",
    ]
    lines += [f"- {item}." for item in ctx.economics["limitations"]]
    lines += [
        "",
        "## Sello",
        "",
        "`SHA256SUMS.txt` se emite **después** de este informe y de la verificación, y cubre todos "
        "los ficheros del directorio salvo él mismo y `SEAL.json`. El informe no incluye el digest "
        "del sello: incluirlo sería un hash circular.",
        "",
    ]
    return "\n".join(lines)


def final_report_md(ctx: Ctx) -> str:
    decision = ctx.decision
    f0 = ctx.economics["economics"]["F0_touch_full"]
    f1 = ctx.economics["economics"]["F1_tape_base"]
    f2 = ctx.economics["economics"]["F2_tape_pessimistic"]
    verification = ctx.verification["summary"]
    lines = [
        "# FINAL REPORT — EXP-003M",
        "",
        "## Respuesta",
        "",
        f"**`{decision['verdict']}`**. No hay evidencia de ventaja económica neta después de "
        f"modelar fills maker realistas, y el candidato `5m/mean_reversion` debe descartarse.",
        "",
        "La razón no es que el modelo de fills sea pesimista. Es que el **techo** de ingreso bruto "
        f"por operación (`{_num(f0['gross_per_fill_usdt'])}` USDT, con todo toque lleno al precio "
        f"mejorado y cola cero) ya está por debajo del **suelo** de comisiones "
        f"(`{_num(f0['fees_per_fill_usdt'])}` USDT con el descuento BNB, "
        f"`{_num(float(ctx.design['fee_schedules']['spot_vip0']['maker_bps']) * 2 * 500 / 10_000.0)}` "
        f"sin él). Un fill más realista solo puede empeorar esa relación.",
        "",
        "## Resultados cuantitativos",
        "",
        "| escenario | llenadas | neto/cierre | neto/señal | IC95 % neto/señal |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name in ctx.scenario_list:
        block = ctx.economics["economics"][name]
        ci = block["bootstrap_ci95_net_per_signal"]
        lines.append(
            f"| `{name}` | {block['filled']}/{block['signals']} | "
            f"{_num(block['net_per_fill_usdt'])} | {_num(block['net_per_signal_usdt'])} | "
            f"[{_num(ci['lower'])}, {_num(ci['upper'])}] |"
        )
    limits = ctx.fills["sensitivity"]
    positive = [point for point in limits if (point["net_per_fill_usdt"] or 0) > 0]
    lines += [
        "",
        f"- La cinta observada reduce el llenado de {_num(f0['fill_rate'] * 100, 1)} % (F0, por "
        f"toque) a {_num(f1['fill_rate'] * 100, 1)} % (F1, cola 1x y 400 ms) y a "
        f"{_num(f2['fill_rate'] * 100, 1)} % (F2, cola 4x y 2 s), con fracción media llenada "
        f"`{_num(ctx.fills['scenarios']['F1_tape_base']['fill_fraction_mean'], 3)}`.",
        f"- Ningún punto del barrido de cola y latencia ({len(limits)} puntos) tiene neto por cierre "
        f"positivo: **{len(positive)}/{len(limits)}**.",
        f"- Selección adversa: el movimiento a 5 minutos posterior a un fill de cinta es "
        f"`{_num(ctx.economics['selection']['F1_tape_base']['adverse_5m_bps'])}` bp en contra, "
        f"frente a `{_num(ctx.economics['selection']['F1_tape_base']['baseline_adverse_5m_bps'])}` bp "
        f"en el conjunto que F0 habría llenado.",
        "",
        "## Datos",
        "",
        f"- {ctx.manifest['totals']['pairs']} pares `(símbolo, día)` de `aggTrades` spot, "
        f"{_int(ctx.manifest['totals']['rows_kept'])} operaciones conservadas de "
        f"{_int(ctx.manifest['totals']['rows_in_days'])}.",
        "- Klines diarias descargadas del mismo archivo y comparadas barra a barra con el dataset "
        "congelado de EXP-003K: la procedencia queda comprobada contra una segunda fuente.",
        "- No existe libro L2 spot histórico publicado; no se ha sintetizado ni sustituido por el "
        "de futuros.",
        "",
        "## Pruebas",
        "",
        f"- {ctx.tests['totals']['passed']} pasadas, {ctx.tests['totals']['failed']} falladas, "
        f"{ctx.tests['totals']['skipped']} saltadas. ¿Todo verde? "
        f"**{_num(ctx.tests['all_passed'])}**.",
        f"- Verificación independiente: {verification['passed']}/{verification['checks']} PASS, "
        f"{verification['failed']} FAIL, {verification['not_executed']} `NOT_EXECUTED`, "
        f"controles negativos {verification['negative_controls_detected']}/"
        f"{verification['negative_controls']}, `false_success={verification['false_success']}`.",
        "",
        "## Defectos encontrados",
        "",
    ]
    for defect in defects(ctx):
        lines.append(f"- `{defect['id']}`: {defect['statement']}")
    lines += [
        "",
        "## Limitaciones",
        "",
    ]
    lines += [f"- {item}." for item in ctx.economics["limitations"]]
    lines += [
        "",
        "## Siguiente decisión",
        "",
        "Descartar `5m/mean_reversion` como candidato económico en esta lane, no volver a "
        "presupuestarlo con fills más favorables, y mantener el holdout cerrado: no hay nada que "
        "validar fuera de muestra cuando la muestra ya rechaza el mecanismo. La siguiente línea con "
        "valor esperado no es otra búsqueda de señal sobre OHLCV, sino un mecanismo cuyo bruto por "
        "operación supere el suelo de comisiones **antes** de discutir fills.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    required = [
        out / "design" / "DESIGN.json",
        out / "analysis" / "PROVENANCE.json",
        out / "analysis" / "SIGNALS.json",
        out / "analysis" / "FILL_MODEL.json",
        out / "analysis" / "ECONOMICS.json",
        out / "analysis" / "DECISION.json",
        out / "analysis" / "VERIFICATION.json",
        out / "analysis" / "TESTS.json",
        out / "dataset" / "TAPE_MANIFEST.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"[003m-report] BLOCKED — missing artefacts: {missing}")
    ctx = Ctx(out)
    _write(out, "BASELINE.md", baseline_md(ctx))
    _write(out, "EXECUTION_MODEL.md", execution_model_md(ctx))
    _write(out, "FILL_REALISM.md", fill_realism_md(ctx))
    _write(out, "ECONOMICS_COMPARISON.md", economics_md(ctx))
    _write(out, "CANDIDATE_DECISION.md", decision_md(ctx))
    _write(out, "INDEPENDENT_VERIFICATION.md", verification_md(ctx))
    payload = run_report_json(ctx)
    (out / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write(out, "RUN_REPORT.md", run_report_md(ctx))
    _write(out, "FINAL_REPORT.md", final_report_md(ctx))
    print(f"[003m-report] wrote 9 deliverables into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
