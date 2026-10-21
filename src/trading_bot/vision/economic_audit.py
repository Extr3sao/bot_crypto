"""economic_audit — reconstruir el dinero desde los bytes, no desde los contadores.

Este módulo es el **auditor**, no el productor. No está en el camino de ``VisionLane``:
ningún módulo de decisión o ejecución lo importa, y una prueba lo comprueba. Su única
entrada es un ledger ya escrito; su única salida, registros derivados.

Tres decisiones que explican el resto:

* **Decimal, no float.** El dinero se suma con ``Decimal`` a 8 decimales (USDT) y las
  cantidades a 12. Un ``float`` acumulado puede "cuadrar" por casualidad o dejar de cuadrar
  por redondeo; un ``Decimal`` o cuadra o no cuadra, y el resultado se puede publicar.
* **Identidades, no campos.** El PnL no se copia de ``pnl_net_usdt``: se recalcula desde
  ``entry_price``, ``exit_price``, ``quantity`` y las comisiones. Los campos del ledger se
  usan como **afirmación a contrastar**, nunca como fuente de verdad.
* **Un fallo de contrato es un valor, no una excepción silenciosa.** Cada comprobación
  devuelve un código (``DUPLICATE_CLOSE``, ``COST_DOUBLE_COUNTED``, ``RECONCILIATION_MISMATCH``
  …). Un solo fallo duro convierte el run en ``FAIL`` y el verificador independiente lo repite
  con su propia aritmética.

El emparejamiento BASELINE/CANDIDATE (``PairedEconomicDelta``) se hace por **identidad de
opinión** — el sha256 del gráfico más la decisión que salió de él —, no por proximidad
temporal: dos operaciones a la misma hora no son la misma operación.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

Q_USDT = Decimal("0.00000001")
Q_QTY = Decimal("0.000000000001")
ZERO = Decimal("0")
#: Tolerancias declaradas: un céntimo de milésima en dinero y un pelo en cantidades. No
#: son "margen para que cuadre": son el tamaño del redondeo que el propio broker escribe.
TOL_USDT = Decimal("0.00000002")
TOL_QTY = Decimal("0.000000000002")
#: La fila RUN_END publica varias cifras redondeadas a 6 decimales; contrastarlas exige
#: la tolerancia de ese redondeo explícito, no una tolerancia "para que cuadre".
ROUNDING_USDT = Decimal("0.0000005")
#: ``execution_cost_usdt`` es un campo **derivado**: el broker lo calcula como notional x
#: bps declarados, no como la diferencia exacta entre precio pagado y referencia. Coincide
#: en dirección y magnitud con los precios, pero no bit a bit; el dinero se reconcilia con
#: los precios (``LEDGER_FIELDS_MATCH_RECOMPUTATION``) y este campo se contrasta con su
#: propia tolerancia de derivación.
DERIVED_TOL_USDT = Decimal("0.0001")
GENESIS = "0" * 64
TERMINAL_KINDS = ("FILL", "GUARD_REJECT", "DECISION_OUTCOME")


class EconomicContractError(ValueError):
    """Un registro que no cumple el contrato. Lleva código para que el informe lo cite."""

    def __init__(self, code: str, detail: str, **fields: Any) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.fields = dict(fields)

    def to_row(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, **self.fields}


def dec(value: Any) -> Decimal:
    """Float/str/Decimal → Decimal exacto por su representación, nunca por binario."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise EconomicContractError("NOT_A_NUMBER", f"boolean {value!r} is not money")
    if isinstance(value, (int, float)):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise EconomicContractError("NOT_A_NUMBER", f"{value!r} is not a number") from exc
    raise EconomicContractError("NOT_A_NUMBER", f"{type(value).__name__} is not money")


def money(value: Decimal) -> str:
    #: ``format(..., 'f')`` evita el ``0E-8`` de ``str()``: un informe no debería escribir
    #: cero en notación científica.
    return format(value.quantize(Q_USDT), "f")


def qty(value: Decimal) -> str:
    return format(value.quantize(Q_QTY), "f")


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def line_hash(seq: int, prev_sha256: str, entry: dict[str, Any]) -> str:
    """El mismo formato que el escritor, reimplementado aquí a propósito.

    No es "el mismo algoritmo de contabilidad": es el formato de la cadena. Si el auditor
    no pudiera recalcularlo, no podría distinguir un ledger editado de uno íntegro.
    """
    payload = {"seq": seq, "prev_sha256": prev_sha256, "entry": entry}
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def opinion_id(entry: dict[str, Any]) -> str | None:
    """Identidad estable de una opinión: la imagen que se miró y lo que se respondió.

    El proveedor del replay es determinista y su respuesta solo depende de la ventana
    graficada, así que dos decisiones con el mismo ``chart.sha256`` y la misma acción *son*
    la misma opinión aunque caigan en números de secuencia distintos.
    """
    chart = entry.get("chart") or {}
    decision = entry.get("decision") or {}
    if not chart.get("sha256") or not decision:
        return None
    material = {
        "chart_sha256": chart.get("sha256"),
        "symbol": chart.get("symbol"),
        "timeframe": chart.get("timeframe"),
        "action": decision.get("action"),
        "horizon_bars": decision.get("horizon_bars"),
        "invalidation": decision.get("invalidation"),
        "invalidation_price": decision.get("invalidation_price"),
        "confidence": decision.get("confidence"),
    }
    return hashlib.sha256(_canonical(material).encode()).hexdigest()


@dataclass(frozen=True)
class LedgerRow:
    seq: int
    prev_sha256: str
    sha256: str
    entry: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.entry.get("kind", ""))


def read_ledger(path: Path | str) -> list[LedgerRow]:
    target = Path(path)
    if not target.is_file():
        raise EconomicContractError("MISSING_LEDGER", f"{target} does not exist")
    rows: list[LedgerRow] = []
    for number, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EconomicContractError(
                "BAD_JSON", f"line {number} is not JSON: {exc}", line=number
            ) from exc
        for key in ("seq", "prev_sha256", "sha256", "entry"):
            if key not in record:
                raise EconomicContractError(
                    "MISSING_FIELD", f"line {number} has no {key!r}", line=number
                )
        rows.append(
            LedgerRow(
                seq=int(record["seq"]),
                prev_sha256=str(record["prev_sha256"]),
                sha256=str(record["sha256"]),
                entry=dict(record["entry"]),
            )
        )
    if not rows:
        raise EconomicContractError("EMPTY_LEDGER", f"{target} has no rows")
    return rows


def verify_chain(rows: Sequence[LedgerRow]) -> dict[str, Any]:
    """Recalcula la cadena. Devuelve el primer punto donde deja de ser una cadena."""
    prev = GENESIS
    for position, row in enumerate(rows, start=1):
        if row.seq != position:
            return {"ok": False, "reason": f"SEQ_GAP_AT_{position}", "rows": len(rows)}
        if row.prev_sha256 != prev:
            return {"ok": False, "reason": f"BROKEN_LINK_AT_{position}", "rows": len(rows)}
        if line_hash(row.seq, row.prev_sha256, row.entry) != row.sha256:
            return {"ok": False, "reason": f"TAMPERED_LINE_{position}", "rows": len(rows)}
        prev = row.sha256
    return {"ok": True, "reason": "INTACT", "rows": len(rows), "head_sha256": prev}


@dataclass(frozen=True)
class EconomicRunIdentity:
    """RFC 5.1. Lo que no está en los bytes se declara ``UNKNOWN``; no se rellena."""

    run_id: str
    scenario_id: str
    source_commit: str
    worktree_state: str
    entrypoint: str
    runtime_source_hashes: dict[str, str]
    config_hash: str
    dataset_id: str
    dataset_sha256: str
    data_window_utc: dict[str, Any]
    timezone: str
    symbols: list[str]
    timeframes: list[str]
    seed: str
    fee_schedule_source: str
    slippage_model: str
    model_mode: str
    risk_config_hash: str
    accounting_policy: str
    mark_to_market_policy: str
    execution_environment: str
    unknowns: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        row = {
            key: getattr(self, key)
            for key in (
                "run_id",
                "scenario_id",
                "source_commit",
                "worktree_state",
                "entrypoint",
                "config_hash",
                "dataset_id",
                "dataset_sha256",
                "data_window_utc",
                "timezone",
                "symbols",
                "timeframes",
                "seed",
                "fee_schedule_source",
                "slippage_model",
                "model_mode",
                "risk_config_hash",
                "accounting_policy",
                "mark_to_market_policy",
                "execution_environment",
            )
        }
        row["runtime_source_hashes"] = dict(sorted(self.runtime_source_hashes.items()))
        row["unknowns"] = list(self.unknowns)
        return row

    @classmethod
    def from_run_row(
        cls,
        run: dict[str, Any],
        *,
        ledger_sha256: str,
        source_commit: str | None = None,
        runtime_hashes: dict[str, str] | None = None,
    ) -> EconomicRunIdentity:
        dataset = run.get("dataset") or {}
        symbols = sorted(dataset)
        first = next(iter(dataset.values()), {}) if dataset else {}
        provider = run.get("provider") or {}
        lane = run.get("lane") or {}
        unknowns: list[str] = []
        worktree_state = "DECLARED"
        #: DEF-RUN-019: la cabecera `RUN` puede versionar el commit que la escribió y las
        #: huellas de los ficheros que ejecutó. Cuando ese bloque existe se lee de ahí en
        #: lugar de pedírselo al llamante; cuando no existe (todo 017, todo 018) el
        #: resultado es exactamente el de antes: `UNKNOWN` y la incógnita declarada. No se
        #: rellena un commit desconocido con el actual, que sería inventar el origen.
        block = run.get("code_provenance")
        recorded: dict[str, Any] = block if isinstance(block, dict) else {}
        recorded_commit = str(recorded.get("commit") or "")
        if len(recorded_commit) != 40 or set(recorded_commit) == {"0"}:
            recorded_commit = ""
        recorded_hashes = {
            str(name): str(info.get("sha256"))
            for name, info in (recorded.get("files") or {}).items()
            if isinstance(info, dict) and info.get("sha256")
        }
        if source_commit is None and recorded_commit:
            source_commit = recorded_commit
            runtime_dirty = list((recorded.get("worktree") or {}).get("runtime_dirty") or [])
            worktree_state = "DECLARED_RUNTIME_DIRTY" if runtime_dirty else "DECLARED_RUNTIME_CLEAN"
        elif source_commit is None:
            source_commit = "UNKNOWN"
            worktree_state = "UNKNOWN"
            unknowns.append("source_commit: el ledger no versiona el commit que lo produjo")
        if not runtime_hashes and recorded_hashes:
            runtime_hashes = recorded_hashes
        if not runtime_hashes:
            unknowns.append("runtime_source_hashes: no están en el ledger")
        unknowns.append(
            "seed: el runtime es determinista por construcción y no declara semilla"
        )
        unknowns.append(
            "slippage_model: el ledger guarda el coste aplicado, no la ecuación; se audita "
            "contra los precios de referencia fila a fila"
        )
        unknowns.append("execution_environment: no se registra en la fila RUN")
        return cls(
            run_id=str(run.get("book_id", ledger_sha256[:16])),
            scenario_id=str(run.get("book_id", "UNKNOWN")),
            source_commit=source_commit,
            worktree_state=worktree_state,
            entrypoint=str(run.get("entrypoint", "vision.lane.VisionLane.run")),
            runtime_source_hashes=dict(runtime_hashes or {}),
            config_hash=hashlib.sha256(_canonical(lane).encode()).hexdigest(),
            dataset_id=str(first.get("sha256", "UNKNOWN")),
            dataset_sha256=str(first.get("sha256", "UNKNOWN")),
            data_window_utc={
                "first_open": first.get("first_open_utc"),
                "last_open": first.get("last_open_utc"),
                "bars": first.get("bars"),
            },
            timezone="UTC",
            symbols=symbols,
            timeframes=[str(lane.get("timeframe", "UNKNOWN"))],
            seed="UNKNOWN",
            fee_schedule_source=(
                "ledger FILL.commission_bps (el broker cobró esa cifra; la fuente del "
                "modelo es alpha15.cost_for)"
            ),
            slippage_model="EMBEDDED_IN_FILL_PRICE",
            model_mode="REPLAY (proveedor determinista; no se llamó a ningún modelo real)",
            risk_config_hash=hashlib.sha256(
                _canonical(run.get("risk_policy") or {}).encode()
            ).hexdigest(),
            accounting_policy="paper-accounting/2",
            mark_to_market_policy="last observable close of the run",
            execution_environment=str(provider.get("provider", "UNKNOWN")),
            unknowns=unknowns,
        )


@dataclass(frozen=True)
class FillRecord:
    position_id: str
    decision_seq: int
    opinion_id: str | None
    symbol: str
    side: str
    intent: str
    ts_ms: int
    quote_ts_ms: int
    reference_price: Decimal
    fill_price: Decimal
    quantity: Decimal
    notional_usdt: Decimal
    entry_commission: Decimal
    commission_bps: Decimal
    opinion_age_ms: int | None

    @classmethod
    def from_entry(cls, entry: dict[str, Any], *, opinions: dict[int, str | None]) -> FillRecord:
        required = (
            "position_id",
            "decision_seq",
            "quantity",
            "entry_price",
            "reference_price",
            "side",
            "intent",
        )
        missing = [key for key in required if key not in entry]
        if missing:
            raise EconomicContractError(
                "FILL_MISSING_FIELD",
                f"FILL for decision {entry.get('decision_seq')} lacks {missing}",
                missing=missing,
            )
        commission = entry.get("entry_commission_usdt", entry.get("entry_commission"))
        if commission is None:
            raise EconomicContractError(
                "FILL_MISSING_FIELD",
                f"FILL for decision {entry.get('decision_seq')} declares no entry commission",
                missing=["entry_commission_usdt"],
            )
        side = str(entry["side"]).lower()
        if side not in ("buy", "sell"):
            raise EconomicContractError("BAD_SIDE", f"side {side!r} is not buy/sell")
        quantity = dec(entry["quantity"])
        if quantity <= ZERO:
            raise EconomicContractError("NON_POSITIVE_QTY", f"quantity {quantity} <= 0")
        return cls(
            position_id=str(entry["position_id"]),
            decision_seq=int(entry["decision_seq"]),
            opinion_id=opinions.get(int(entry["decision_seq"])),
            symbol=str(entry.get("symbol", "UNKNOWN")),
            side=side,
            intent=str(entry.get("intent", "UNKNOWN")),
            ts_ms=int(entry.get("ts_ms", entry.get("quote_ts_ms", 0))),
            quote_ts_ms=int(entry.get("quote_ts_ms", entry.get("ts_ms", 0))),
            reference_price=dec(entry["reference_price"]),
            fill_price=dec(entry["entry_price"]),
            quantity=quantity,
            notional_usdt=dec(entry.get("notional_usdt", quantity * dec(entry["entry_price"]))),
            entry_commission=dec(commission),
            commission_bps=dec(entry.get("commission_bps", 0)),
            opinion_age_ms=(
                int(entry["opinion_age_ms"]) if entry.get("opinion_age_ms") is not None else None
            ),
        )

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.side == "buy" else -self.quantity


@dataclass(frozen=True)
class TradeRecord:
    """RFC 5.2. Un round trip reconstruido; el fill no es la operación, el par sí."""

    run_id: str
    opinion_id: str | None
    decision_seq: int
    asset: str
    side: str
    fill_time_utc: str | None
    fill_time_ms: int
    exit_time_ms: int
    quantity: Decimal
    fill_price: Decimal
    reference_price: Decimal
    exit_price: Decimal
    exit_reference_price: Decimal
    fees_quote: Decimal
    slippage_quote: Decimal
    funding_quote: Decimal
    gross_pnl_quote: Decimal
    realized_pnl_quote: Decimal
    unrealized_pnl_quote_at_cutoff: Decimal | None
    position_id: str
    terminal_status: str
    exit_reason: str
    bars_held: int | None
    opinion_age_ms: int | None
    evidence_offsets: tuple[int, ...]
    source_hashes: tuple[str, ...]

    def to_row(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "opinion_id": self.opinion_id,
            "decision_seq": self.decision_seq,
            "asset": self.asset,
            "side": self.side,
            "fill_time_utc": self.fill_time_utc,
            "fill_time_ms": self.fill_time_ms,
            "exit_time_ms": self.exit_time_ms,
            "quantity": qty(self.quantity),
            "fill_price": str(self.fill_price),
            "reference_price": str(self.reference_price),
            "exit_price": str(self.exit_price),
            "exit_reference_price": str(self.exit_reference_price),
            "fees_quote": money(self.fees_quote),
            "slippage_quote": money(self.slippage_quote),
            "funding_quote": money(self.funding_quote),
            "gross_pnl_quote": money(self.gross_pnl_quote),
            "realized_pnl_quote": money(self.realized_pnl_quote),
            "unrealized_pnl_quote_at_cutoff": (
                None
                if self.unrealized_pnl_quote_at_cutoff is None
                else money(self.unrealized_pnl_quote_at_cutoff)
            ),
            "position_id": self.position_id,
            "terminal_status": self.terminal_status,
            "exit_reason": self.exit_reason,
            "bars_held": self.bars_held,
            "opinion_age_ms": self.opinion_age_ms,
            "evidence_offsets": list(self.evidence_offsets),
            "source_hashes": list(self.source_hashes),
        }


def _check(code: str, ok: bool, detail: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, "ok": bool(ok), "detail": detail, **fields}


@dataclass(frozen=True)
class RunEconomics:
    """Todo lo que se puede afirmar de un run mirando solo sus bytes."""

    identity: EconomicRunIdentity
    trades: tuple[TradeRecord, ...]
    totals: dict[str, str]
    accounting: dict[str, Any]
    checks: tuple[dict[str, Any], ...]
    chain: dict[str, Any]
    ledger_sha256: str
    rows: int
    #: (decision_seq, opinion_id, clase terminal) por opinión, para poder decir qué le pasó
    #: a una opinión que un escenario rellenó y el otro no.
    terminals: tuple[dict[str, Any], ...] = ()

    def terminal_by_opinion(self) -> dict[str, str]:
        return {
            str(row["opinion_id"]): str(row["terminal"])
            for row in self.terminals
            if row.get("opinion_id")
        }

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if not check["ok"]]

    @property
    def status(self) -> str:
        return "PASS" if not self.failed else "FAIL"

    def net(self) -> Decimal:
        """Vista redondeada a 8 decimales. Para sumar entre runs, usa ``net_exact``."""
        return Decimal(self.totals["net_realised_usdt"])

    #: Sumar las vistas ya redondeadas de cinco runs acumula el error de redondeo; el
    #: agregado se calcula sobre los trades, no sobre los totales publicados.
    def net_exact(self) -> Decimal:
        return sum((trade.realized_pnl_quote for trade in self.trades), ZERO)

    def gross_exact(self) -> Decimal:
        return sum((trade.gross_pnl_quote for trade in self.trades), ZERO)

    def fees_exact(self) -> Decimal:
        return sum((trade.fees_quote for trade in self.trades), ZERO)

    def slippage_exact(self) -> Decimal:
        return sum((trade.slippage_quote for trade in self.trades), ZERO)

    def trades_by_opinion(self) -> dict[str, TradeRecord]:
        return {trade.opinion_id: trade for trade in self.trades if trade.opinion_id}

    def to_row(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_row(),
            "ledger_sha256": self.ledger_sha256,
            "rows": self.rows,
            "chain": self.chain,
            "totals": self.totals,
            "accounting": self.accounting,
            "checks": list(self.checks),
            "status": self.status,
            "failed_checks": [check["code"] for check in self.failed],
            "trades": [trade.to_row() for trade in self.trades],
        }


ACTIONABLE_INTENTS = ("OPEN_LONG", "OPEN_SHORT", "CLOSE")
TERMINAL_CLASSES = ("FILLED", "CLOSED", "BLOCKED_BY_RISK", "GATED", "REJECTED")


def _terminal_class(entry: dict[str, Any]) -> str | None:
    """A qué clase terminal pertenece esta fila, si declara alguna.

    Una entrada aprobada y ejecutada **no** es un cierre: el relleno que la sigue es el
    evento terminal. Contarla aquí sería contar la misma opinión dos veces.
    """
    kind = entry.get("kind")
    if kind == "FILL":
        return "FILLED"
    if kind == "DECISION_OUTCOME":
        if str(entry.get("intent") or "") == "CLOSE":
            executed = entry.get("executed")
            if executed is True:
                return "CLOSED"
            if executed is False:
                return "GATED"
            return None
        if entry.get("approved") is False:
            return "BLOCKED_BY_RISK"
        if entry.get("approved") is True and entry.get("executed") is False:
            return "GATED"
        return None
    if kind == "GUARD_REJECT" and entry.get("decision_seq") is not None:
        return "REJECTED"
    return None


def _ledger_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconstruct(
    path: Path | str,
    *,
    source_commit: str | None = None,
    runtime_hashes: dict[str, str] | None = None,
    mark_price: Decimal | None = None,
) -> RunEconomics:
    """Reconstruye el run completo. No lee contadores: los recalcula y los compara."""
    target = Path(path)
    rows = read_ledger(target)
    chain = verify_chain(rows)
    checks: list[dict[str, Any]] = [
        _check("CHAIN_INTACT", chain["ok"], str(chain["reason"]), rows=chain["rows"])
    ]
    run = next((row.entry for row in rows if row.kind == "RUN"), None)
    if run is None:
        raise EconomicContractError("NO_RUN_ROW", f"{target} has no RUN row")
    run_ends = [row for row in rows if row.kind == "RUN_END"]
    checks.append(
        _check("RUN_END_PRESENT", len(run_ends) == 1, f"{len(run_ends)} RUN_END rows")
    )
    checks.append(
        _check(
            "RUN_END_LAST",
            bool(run_ends) and rows[-1].kind == "RUN_END",
            "RUN_END is the last row" if run_ends and rows[-1].kind == "RUN_END" else "rows "
            "follow RUN_END",
        )
    )
    run_end = run_ends[-1].entry if run_ends else {}
    #: El precio de marca lo declara el propio run. Se usa solo si el llamante no impone
    #: uno: el corte común de una comparación no puede venir del ledger que se compara.
    declared_marks = {
        str(symbol): dec(value)
        for symbol, value in ((run_end.get("accounting") or {}).get("mark_prices") or {}).items()
    }
    identity = EconomicRunIdentity.from_run_row(
        run,
        ledger_sha256=_ledger_sha(target),
        source_commit=source_commit,
        runtime_hashes=runtime_hashes,
    )

    opinions: dict[int, str | None] = {}
    for row in rows:
        if row.kind == "DECISION" and row.entry.get("intent") in ACTIONABLE_INTENTS:
            opinions[row.seq] = opinion_id(row.entry)

    terminals: dict[int, list[tuple[str, str]]] = {}
    orphans: list[int] = []
    for row in rows:
        cls = _terminal_class(row.entry)
        if cls is None:
            continue
        seq = row.entry.get("decision_seq")
        if seq is None:
            continue
        seq = int(seq)
        if seq not in opinions:
            orphans.append(seq)
            continue
        terminals.setdefault(seq, []).append((cls, row.kind))

    counts = {name: 0 for name in TERMINAL_CLASSES}
    unrecorded = 0
    duplicated = 0
    for seq in opinions:
        events = terminals.get(seq, [])
        if not events:
            unrecorded += 1
            continue
        if len(events) > 1:
            duplicated += 1
        counts[events[0][0]] += 1

    generated = len(opinions)
    checks += [
        _check(
            "OPINIONS_BALANCED",
            generated == sum(counts.values()),
            f"generated={generated} terminals={sum(counts.values())}",
            generated=generated,
            classes=dict(counts),
        ),
        _check("UNRECORDED_ZERO", unrecorded == 0, f"{unrecorded} opinions without a terminal"),
        _check(
            "DUPLICATE_TERMINAL_ZERO",
            duplicated == 0,
            f"{duplicated} opinions with more than one terminal",
        ),
        _check(
            "ORPHAN_TERMINAL_ZERO",
            not orphans,
            f"{len(orphans)} terminal rows name no known opinion",
        ),
    ]

    fill_entries: dict[int, dict[str, Any]] = {}
    fills: list[FillRecord] = []
    for row in rows:
        if row.kind != "FILL":
            continue
        fill = FillRecord.from_entry(row.entry, opinions=opinions)
        fills.append(fill)
        fill_entries[fill.decision_seq] = row.entry
    approvals = {
        int(row.entry["decision_seq"])
        for row in rows
        if row.kind == "DECISION_OUTCOME"
        and row.entry.get("approved") is True
        and row.entry.get("executed") is not False
        and row.entry.get("decision_seq") is not None
    }
    fills_without_approval = [
        fill.decision_seq for fill in fills if fill.decision_seq not in approvals
    ]
    duplicate_fills = [
        seq
        for seq, count in (
            (seq, sum(1 for fill in fills if fill.decision_seq == seq))
            for seq in {fill.decision_seq for fill in fills}
        )
        if count > 1
    ]
    max_age = int((run.get("lane") or {}).get("max_opinion_age_ms") or 0)
    overdue = [
        fill.decision_seq
        for fill in fills
        if fill.opinion_age_ms is not None and max_age and fill.opinion_age_ms > max_age
    ]
    late = [
        fill.decision_seq
        for fill in fills
        if int(fill_entries[fill.decision_seq].get("received_at_ms", 0)) > fill.quote_ts_ms
        or int(fill_entries[fill.decision_seq].get("decision_ts_ms", 0))
        > fill.quote_ts_ms
    ]

    closes: dict[str, dict[str, Any]] = {}
    duplicate_closes: list[str] = []
    for row in rows:
        if row.kind != "CLOSE":
            continue
        position_id = str(row.entry.get("position_id"))
        if position_id in closes:
            duplicate_closes.append(position_id)
        closes[position_id] = row.entry
    closed_positions = {fill.position_id for fill in fills}
    orphan_closes = sorted(set(closes) - closed_positions)

    trades: list[TradeRecord] = []
    open_positions: list[str] = []
    quantity_mismatch: list[str] = []
    ledger_mismatch: list[str] = []
    for fill in fills:
        signed = fill.signed_quantity
        close = closes.get(fill.position_id)
        base = {
            "run_id": identity.run_id,
            "opinion_id": fill.opinion_id,
            "decision_seq": fill.decision_seq,
            "asset": fill.symbol,
            "side": fill.side,
            "fill_time_utc": fill_entries[fill.decision_seq].get("ts_utc"),
            "fill_time_ms": fill.quote_ts_ms,
            "quantity": fill.quantity,
            "fill_price": fill.fill_price,
            "reference_price": fill.reference_price,
            "position_id": fill.position_id,
            "opinion_age_ms": fill.opinion_age_ms,
            "evidence_offsets": (fill.decision_seq,),
            "source_hashes": (identity.dataset_sha256,),
        }
        if close is None:
            open_positions.append(fill.position_id)
            mark = mark_price if mark_price is not None else declared_marks.get(fill.symbol)
            unrealized = (
                None
                if mark is None
                else signed * (mark - fill.fill_price) - fill.entry_commission
            )
            trades.append(
                TradeRecord(
                    **base,
                    exit_time_ms=0,
                    exit_price=ZERO,
                    exit_reference_price=ZERO,
                    fees_quote=fill.entry_commission,
                    slippage_quote=ZERO,
                    funding_quote=ZERO,
                    gross_pnl_quote=ZERO,
                    realized_pnl_quote=ZERO,
                    unrealized_pnl_quote_at_cutoff=unrealized,
                    terminal_status="OPEN_AT_CUTOFF",
                    exit_reason="",
                    bars_held=None,
                )
            )
            continue
        exit_price = dec(close["exit_price"])
        exit_reference = dec(close.get("exit_reference_price", exit_price))
        close_qty = dec(close.get("quantity", fill.quantity))
        if (close_qty - fill.quantity).copy_abs() > TOL_QTY:
            quantity_mismatch.append(fill.position_id)
        exit_commission = dec(
            close.get("exit_commission_usdt", dec(close.get("commissions_usdt", 0))
            - fill.entry_commission)
        )
        fees = fill.entry_commission + exit_commission
        gross = signed * (exit_price - fill.fill_price)
        reference_gross = signed * (exit_reference - fill.reference_price)
        slippage = reference_gross - gross
        net = gross - fees
        declared_gross = dec(close.get("gross_pnl_usdt", net + fees))
        declared_net = dec(close.get("pnl_net_usdt", net))
        declared_slip = dec(close.get("execution_cost_usdt", slippage))
        if (
            (gross - declared_gross).copy_abs() > TOL_USDT
            or (net - declared_net).copy_abs() > TOL_USDT
            or (slippage - declared_slip).copy_abs() > DERIVED_TOL_USDT
        ):
            ledger_mismatch.append(fill.position_id)
        trades.append(
            TradeRecord(
                **base,
                exit_time_ms=int(close.get("ts_ms", 0)),
                exit_price=exit_price,
                exit_reference_price=exit_reference,
                fees_quote=fees,
                slippage_quote=slippage,
                funding_quote=ZERO,
                gross_pnl_quote=gross,
                realized_pnl_quote=net,
                unrealized_pnl_quote_at_cutoff=ZERO,
                terminal_status="CLOSED",
                exit_reason=str(close.get("exit_reason", "UNKNOWN")),
                bars_held=(
                    int(close["bars_held"]) if close.get("bars_held") is not None else None
                ),
            )
        )

    checks += [
        _check(
            "FILL_HAS_APPROVAL",
            not fills_without_approval,
            f"{len(fills_without_approval)} fills without an approving risk row",
        ),
        _check("DUPLICATE_FILL_ZERO", not duplicate_fills, f"{duplicate_fills}"),
        _check(
            "FILL_WITHIN_OPINION_TTL",
            not overdue,
            f"{len(overdue)} fills older than {max_age} ms",
        ),
        _check("FILL_AFTER_ANSWER", not late, f"{len(late)} fills priced before their answer"),
        _check("NO_DUPLICATE_CLOSE", not duplicate_closes, f"{duplicate_closes}"),
        _check("NO_ORPHAN_CLOSE", not orphan_closes, f"{orphan_closes}"),
        _check("QUANTITY_MATCHES", not quantity_mismatch, f"{quantity_mismatch}"),
        _check(
            "LEDGER_FIELDS_MATCH_RECOMPUTATION",
            not ledger_mismatch,
            f"{len(ledger_mismatch)} trades whose declared gross/net/slippage disagree with "
            "the prices",
        ),
        _check(
            "OPEN_POSITIONS_MARKED",
            all(
                trade.unrealized_pnl_quote_at_cutoff is not None
                for trade in trades
                if trade.terminal_status == "OPEN_AT_CUTOFF"
            ),
            f"{len(open_positions)} open at cutoff, marked at the cutoff price",
        ),
    ]

    closed = [trade for trade in trades if trade.terminal_status == "CLOSED"]
    gross_total = sum((trade.gross_pnl_quote for trade in closed), ZERO)
    fees_total = sum((trade.fees_quote for trade in closed), ZERO)
    slippage_total = sum((trade.slippage_quote for trade in closed), ZERO)
    net_total = sum((trade.realized_pnl_quote for trade in closed), ZERO)
    unrealized_total = sum(
        (
            trade.unrealized_pnl_quote_at_cutoff or ZERO
            for trade in trades
            if trade.terminal_status == "OPEN_AT_CUTOFF"
        ),
        ZERO,
    )
    notional_total = sum((trade.quantity * trade.fill_price for trade in closed), ZERO)
    initial = dec(
        ((run_end.get("accounting") or {}).get("initial_equity_usdt"))
        if (run_end.get("accounting") or {}).get("initial_equity_usdt") is not None
        else run.get("equity_usdt", 0)
    )
    marked_equity = initial + net_total + unrealized_total

    declared_net = dec(run_end.get("pnl_realised_usdt", net_total))
    declared_costs = dec(
        run_end.get("costs_realised_usdt", fees_total + slippage_total)
    )
    declared_marked = dec(run_end.get("marked_equity_usdt", marked_equity))
    declared_unrealised = dec(run_end.get("pnl_unrealised_usdt", unrealized_total))
    #: La fila RUN_END publica además versiones redondeadas a 6 decimales para el informe.
    #: Se contrastan aparte y con la tolerancia del redondeo declarado, no con la del dinero.
    rounded_net = dec(run_end.get("net_realised_usdt", net_total))
    rounded_gross = dec(run_end.get("gross_realised_usdt", gross_total))
    checks += [
        _check(
            "RUN_END_NET_RECONCILED",
            (net_total - declared_net).copy_abs() <= TOL_USDT,
            f"reconstructed {money(net_total)} vs declared {money(declared_net)}",
        ),
        _check(
            "RUN_END_ROUNDED_VIEW_MATCHES",
            (net_total - rounded_net).copy_abs() <= ROUNDING_USDT
            and (gross_total - rounded_gross).copy_abs() <= ROUNDING_USDT,
            f"6-decimal view: net {rounded_net} vs {money(net_total)}, gross "
            f"{rounded_gross} vs {money(gross_total)}",
        ),
        _check(
            "RUN_END_COSTS_RECONCILED",
            #: Cada operación redondea su coste derivado; la suma de n redondeos no puede
            #: medirse con la tolerancia de una sola.
            (fees_total + slippage_total - declared_costs).copy_abs()
            <= TOL_USDT * max(1, len(closed)),
            f"reconstructed {money(fees_total + slippage_total)} vs declared "
            f"{money(declared_costs)}",
        ),
        _check(
            "RUN_END_EQUITY_RECONCILED",
            (marked_equity - declared_marked).copy_abs() <= TOL_USDT
            and (unrealized_total - declared_unrealised).copy_abs() <= TOL_USDT,
            f"reconstructed {money(marked_equity)} vs declared {money(declared_marked)}",
        ),
        _check(
            "COST_NOT_DOUBLE_COUNTED",
            all(
                (trade.realized_pnl_quote - (trade.gross_pnl_quote - trade.fees_quote)).copy_abs()
                <= TOL_USDT
                for trade in closed
            )
            and (net_total - (gross_total - fees_total)).copy_abs() <= TOL_USDT,
            "net = gross - fees on every trade and in aggregate",
        ),
    ]

    costs_bps = (
        (fees_total + slippage_total) / notional_total * Decimal(10_000)
        if notional_total
        else ZERO
    )
    totals = {
        "fills": str(len(fills)),
        "closed_trades": str(len(closed)),
        "open_positions": str(len(open_positions)),
        "gross_pnl_usdt": money(gross_total),
        "fees_usdt": money(fees_total),
        "slippage_usdt": money(slippage_total),
        "costs_total_usdt": money(fees_total + slippage_total),
        "net_realised_usdt": money(net_total),
        "unrealised_at_cutoff_usdt": money(unrealized_total),
        "marked_equity_usdt": money(marked_equity),
        "notional_traded_usdt": money(notional_total),
        "costs_bps_of_notional": str(costs_bps.quantize(Decimal("0.0001"))),
        "expectancy_usdt_per_closed_trade": money(
            net_total / len(closed) if closed else ZERO
        ),
    }
    accounting = {
        "opinions": generated,
        "terminal_classes": dict(counts),
        "unrecorded": unrecorded,
        "duplicate_terminals": duplicated,
        "orphan_terminals": len(orphans),
        "identity": "generated == FILLED + CLOSED + BLOCKED_BY_RISK + GATED + REJECTED",
        "exit_reasons": dict(
            sorted(
                (reason, sum(1 for trade in closed if trade.exit_reason == reason))
                for reason in {trade.exit_reason for trade in closed}
            )
        ),
    }
    terminal_rows = tuple(
        {
            "decision_seq": seq,
            "opinion_id": opinions.get(seq),
            "terminal": (terminals.get(seq) or [("UNRECORDED", "")])[0][0],
        }
        for seq in sorted(opinions)
    )
    return RunEconomics(
        identity=identity,
        trades=tuple(trades),
        totals=totals,
        accounting=accounting,
        checks=tuple(checks),
        chain=chain,
        ledger_sha256=_ledger_sha(target),
        rows=len(rows),
        terminals=terminal_rows,
    )


@dataclass(frozen=True)
class PairedEconomicDelta:
    """RFC 5.3. El emparejamiento se hace por identidad de opinión, no por cercanía."""

    scenario: str
    match_key: str
    match_status: str
    reason: str
    decision_delta: int
    timing_delta_ms: int | None
    fill_delta: int
    cost_delta: Decimal
    realized_delta: Decimal
    unrealized_delta_at_common_cutoff: Decimal
    baseline_net: Decimal | None
    candidate_net: Decimal | None

    def to_row(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "match_key": self.match_key,
            "match_status": self.match_status,
            "reason": self.reason,
            "decision_delta": self.decision_delta,
            "timing_delta_ms": self.timing_delta_ms,
            "fill_delta": self.fill_delta,
            "cost_delta": money(self.cost_delta),
            "realized_delta": money(self.realized_delta),
            "unrealized_delta_at_common_cutoff": money(
                self.unrealized_delta_at_common_cutoff
            ),
            "baseline_net": None if self.baseline_net is None else money(self.baseline_net),
            "candidate_net": None if self.candidate_net is None else money(self.candidate_net),
        }


def pair_trades(
    baseline: RunEconomics,
    candidate: RunEconomics,
    *,
    scenario: str,
) -> list[PairedEconomicDelta]:
    """Empareja por ``opinion_id``. Los no emparejados se conservan, no se descartan."""
    base_map: dict[str, TradeRecord] = {}
    cand_map: dict[str, TradeRecord] = {}
    ambiguous: set[str] = set()
    for trade, target in (
        *((trade, base_map) for trade in baseline.trades),
        *((trade, cand_map) for trade in candidate.trades),
    ):
        if not trade.opinion_id:
            continue
        if trade.opinion_id in target:
            ambiguous.add(trade.opinion_id)
        target[trade.opinion_id] = trade
    base_terminals = baseline.terminal_by_opinion()
    cand_terminals = candidate.terminal_by_opinion()
    rows: list[PairedEconomicDelta] = []
    for key in sorted(set(base_map) | set(cand_map)):
        base_trade = base_map.get(key)
        cand_trade = cand_map.get(key)
        if key in ambiguous:
            status = "AMBIGUOUS"
            reason = "the same opinion identity appears more than once in a run"
        elif base_trade and cand_trade:
            status = "MATCHED"
            reason = "same chart bytes and same parsed decision"
        elif base_trade:
            status = "BASELINE_ONLY"
            reason = f"candidate reached {cand_terminals.get(key, 'NO_OPINION')}"
        else:
            status = "CANDIDATE_ONLY"
            reason = f"baseline reached {base_terminals.get(key, 'NO_OPINION')}"
        base_net = base_trade.realized_pnl_quote if base_trade else None
        cand_net = cand_trade.realized_pnl_quote if cand_trade else None
        base_cost = (
            base_trade.fees_quote + base_trade.slippage_quote if base_trade else ZERO
        )
        cand_cost = (
            cand_trade.fees_quote + cand_trade.slippage_quote if cand_trade else ZERO
        )
        rows.append(
            PairedEconomicDelta(
                scenario=scenario,
                match_key=key,
                match_status=status,
                reason=reason,
                decision_delta=(1 if cand_trade else 0) - (1 if base_trade else 0),
                timing_delta_ms=(
                    (cand_trade.fill_time_ms - base_trade.fill_time_ms)
                    if base_trade and cand_trade
                    else None
                ),
                fill_delta=(1 if cand_trade else 0) - (1 if base_trade else 0),
                cost_delta=cand_cost - base_cost,
                realized_delta=(cand_net or ZERO) - (base_net or ZERO),
                unrealized_delta_at_common_cutoff=(
                    (cand_trade.unrealized_pnl_quote_at_cutoff or ZERO)
                    if cand_trade
                    else ZERO
                )
                - (
                    (base_trade.unrealized_pnl_quote_at_cutoff or ZERO)
                    if base_trade
                    else ZERO
                ),
                baseline_net=base_net,
                candidate_net=cand_net,
            )
        )
    return rows


def attribute(
    baseline: dict[str, RunEconomics],
    candidate: dict[str, RunEconomics],
) -> dict[str, Any]:
    """Descompone el delta y comprueba que la descomposición cierra.

    Lo que **no** hace: afirmar causalidad. Un delta perfectamente reconciliado por
    pertenencia de operaciones sigue siendo compatible con que el cambio de calendario sea
    la causa o con que sea un artefacto del orden en que se miraron las barras.
    """
    scenarios = sorted(set(baseline) & set(candidate))
    rows: list[PairedEconomicDelta] = []
    per_scenario: dict[str, Any] = {}
    for name in scenarios:
        base = baseline[name]
        cand = candidate[name]
        paired = pair_trades(base, cand, scenario=name)
        rows.extend(paired)
        buckets: dict[str, Decimal] = {
            "MATCHED": ZERO,
            "BASELINE_ONLY": ZERO,
            "CANDIDATE_ONLY": ZERO,
            "AMBIGUOUS": ZERO,
        }
        counts: dict[str, int] = {key: 0 for key in buckets}
        for row in paired:
            buckets[row.match_status] += row.realized_delta
            counts[row.match_status] += 1
        reconstructed = sum(buckets.values(), ZERO)
        observed = cand.net_exact() - base.net_exact()
        per_scenario[name] = {
            "baseline_net_usdt": money(base.net_exact()),
            "candidate_net_usdt": money(cand.net_exact()),
            "observed_delta_usdt": money(observed),
            "reconstructed_delta_usdt": money(reconstructed),
            "residual_usdt": money(observed - reconstructed),
            "reconciled": (observed - reconstructed).copy_abs() <= TOL_USDT,
            "counts": counts,
            "buckets_usdt": {key: money(value) for key, value in buckets.items()},
            "baseline_status": base.status,
            "candidate_status": cand.status,
            "exit_reasons_baseline": base.accounting.get("exit_reasons"),
            "exit_reasons_candidate": cand.accounting.get("exit_reasons"),
        }
    total_base = sum((run.net_exact() for run in baseline.values()), ZERO)
    total_cand = sum((run.net_exact() for run in candidate.values()), ZERO)
    total_gross_base = sum((run.gross_exact() for run in baseline.values()), ZERO)
    total_gross_cand = sum((run.gross_exact() for run in candidate.values()), ZERO)
    total_fees_base = sum((run.fees_exact() for run in baseline.values()), ZERO)
    total_fees_cand = sum((run.fees_exact() for run in candidate.values()), ZERO)
    total_slip_base = sum((run.slippage_exact() for run in baseline.values()), ZERO)
    total_slip_cand = sum((run.slippage_exact() for run in candidate.values()), ZERO)
    matched = sum(
        (row.realized_delta for row in rows if row.match_status == "MATCHED"), ZERO
    )
    return {
        "scenarios": scenarios,
        "per_scenario": per_scenario,
        "pairs": [row.to_row() for row in rows],
        "totals": {
            "baseline_net_usdt": money(total_base),
            "candidate_net_usdt": money(total_cand),
            "delta_net_usdt": money(total_cand - total_base),
            "baseline_gross_usdt": money(total_gross_base),
            "candidate_gross_usdt": money(total_gross_cand),
            "delta_gross_usdt": money(total_gross_cand - total_gross_base),
            "baseline_fees_usdt": money(total_fees_base),
            "candidate_fees_usdt": money(total_fees_cand),
            "delta_fees_usdt": money(total_fees_cand - total_fees_base),
            "baseline_slippage_usdt": money(total_slip_base),
            "candidate_slippage_usdt": money(total_slip_cand),
            "delta_slippage_usdt": money(total_slip_cand - total_slip_base),
            "accounting_note": "net = gross - fees. El slippage ya está dentro de los "
            "precios de relleno, así que forma parte de gross: sumarlo otra vez lo contaría "
            "dos veces.",
            "delta_net_equals_gross_minus_fees": (
                (total_cand - total_base)
                - ((total_gross_cand - total_gross_base)
                   - (total_fees_cand - total_fees_base))
            ).copy_abs()
            <= TOL_USDT,
            "matched_pairs": sum(1 for row in rows if row.match_status == "MATCHED"),
            "baseline_only": sum(1 for row in rows if row.match_status == "BASELINE_ONLY"),
            "candidate_only": sum(
                1 for row in rows if row.match_status == "CANDIDATE_ONLY"
            ),
            "ambiguous": sum(1 for row in rows if row.match_status == "AMBIGUOUS"),
            "delta_from_matched_pairs_usdt": money(matched),
            #: Neto real de las operaciones que solo existen en una rama (no su aportación
            #: al delta, que lleva el signo contrario en el caso BASELINE_ONLY).
            "baseline_only_trades_net_usdt": money(
                sum(
                    (
                        row.baseline_net or ZERO
                        for row in rows
                        if row.match_status == "BASELINE_ONLY"
                    ),
                    ZERO,
                )
            ),
            "candidate_only_trades_net_usdt": money(
                sum(
                    (
                        row.candidate_net or ZERO
                        for row in rows
                        if row.match_status == "CANDIDATE_ONLY"
                    ),
                    ZERO,
                )
            ),
        },
    }
