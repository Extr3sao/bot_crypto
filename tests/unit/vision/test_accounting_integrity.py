"""003H — la contabilidad de una posición abierta se nombra, no se omite.

003G-D5, medido en la sesión real del 2026-10-19: la sesión terminó con una posición abierta
que ya debía 0,5 USDT de comisión de entrada, y ``costs_usdt`` publicaba 0 mientras el equity
marcado era 9 998,371187. Las dos cifras describían el mismo libro.

Estos tests atacan ``VisionLane.run`` con el ``PaperBroker`` y el ``RiskManager`` de producción
—``TEST_TARGET == RUNTIME_TARGET``— y fijan tres propiedades:

1. **Contractual.** ``costs_usdt`` mantiene su significado (coste realizado de operaciones
   cerradas) y las nuevas claves dicen, cada una, qué mitad del libro describen; el esquema va
   versionado (``paper-accounting/2``).
2. **Total.** ``costs_total_usdt = costs_usdt + comisiones devengadas de posiciones abiertas`` y
   ``marked_equity_usdt = equity inicial + PnL realizado + PnL no realizado neto``.
3. **Sin doble conteo.** Al cerrar, la comisión deja de estar devengada y pasa a realizada
   exactamente una vez; ninguna posición abierta comparte ``position_id`` con una cerrada.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import ACCOUNTING_SCHEMA_VERSION, COST_MEANINGS, VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = int(datetime(2026, 3, 6, tzinfo=UTC).timestamp() * 1000)
REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":0.5,"take_profit_pct":0.75,'
    '"invalidation":null,"rationale":"Continuation."}'
)
NO_TRADE = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"NO_TRADE",'
    '"confidence":0.3,"horizon_bars":6,"stop_loss_pct":null,"take_profit_pct":null,'
    '"invalidation":null,"rationale":"No level."}'
)

#: Lo que este guion declara y lo que la política de riesgo de producción también usa: 0,5 %
#: de stop. DEF-RUN-014: la distancia declarada es la que se arriesga, así que el guion
#: declara la que el escenario necesita (antes declaraba 1,0 % y el lane la descartaba).
POLICY_STOP_PCT = 0.5


class ScriptedProvider(ReplayProvider):
    def __init__(self, script: Callable[[str, int], str], *, latency_ms: int = 0) -> None:
        super().__init__(
            lambda request: script(request.chart.symbol, int(request.decision_ts_ms))
        )
        self._latency_ms = latency_ms

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        from dataclasses import replace

        return replace(super().analyze(request), latency_ms=self._latency_ms)


def policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def vision_config(**lane_overrides):
    base = load_vision_config(env={})
    merged = {
        "timeframe": "1h",
        "window_bars": 20,
        "decision_every_bars": 1,
        "max_calls_per_run": 200,
        "max_estimated_spend_usd": 10.0,
        **lane_overrides,
    }
    return base.__class__(provider=base.provider, lane=base.lane.__class__(**merged))


def flat_bars(
    *, count: int = 40, patches: dict[int, tuple[float, float, float, float]] | None = None
) -> list[Bar]:
    """Precio plano con parches opcionales (open, high, low, close) en índices concretos."""

    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        opened = high = low = close = price
        high, low = price * 1.001, price * 0.999
        if patches and index in patches:
            opened, high, low, close = patches[index]
        bars.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
        price = close
    return bars


def run_lane(tmp_path: Path, *, series: list[Bar], script: Callable[[str, int], str]):
    lane = VisionLane(
        series={SYMBOL: series},
        provider=ScriptedProvider(script),
        config=vision_config(),
        risk_policy=policy(),
        ledger_path=tmp_path / "accounting.jsonl",
    )
    summary = lane.run()
    rows = [
        dict(line["entry"], seq=line["seq"]) for line in read_entries(tmp_path / "accounting.jsonl")
    ]
    return lane, summary, rows


def of_kind(rows, kind: str) -> list[dict]:
    return [row for row in rows if row.get("kind") == kind]


def long_then_flat(symbol: str, ts: int) -> str:
    #: Una sola entrada, en la ventana inicial; el resto calla para que el libro quede vivo.
    return LONG % symbol if ts <= START_MS + 20 * HOUR_MS else NO_TRADE % symbol


# --------------------------------------------------------------------- contrato


def test_accounting_contract_is_versioned_and_every_term_defined(tmp_path: Path) -> None:
    _, summary, _ = run_lane(tmp_path, series=flat_bars(), script=long_then_flat)

    block = summary["accounting"]
    assert block["schema_version"] == ACCOUNTING_SCHEMA_VERSION == "paper-accounting/2"
    for key in (
        "costs_usdt",
        "costs_realised_usdt",
        "costs_total_usdt",
        "entry_commissions_accrued_open_usdt",
        "pnl_realised_usdt",
        "pnl_unrealised_usdt",
        "pnl_total_usdt",
        "marked_equity_usdt",
    ):
        assert key in summary, key
        assert block["meanings"][key], f"{key} must be defined, not inferred"
    assert COST_MEANINGS["costs_usdt"].endswith("it does NOT include open positions.")


# ------------------------------------------------- posición abierta al cierre


def test_open_position_commissions_are_named_and_totalled(tmp_path: Path) -> None:
    lane, summary, rows = run_lane(tmp_path, series=flat_bars(), script=long_then_flat)

    assert summary["fills"] == 1
    assert summary["closed_trades"] == 0

    # El significado viejo no cambia: sin cierres, el coste realizado es cero.
    assert summary["costs_usdt"] == 0
    assert summary["costs_realised_usdt"] == 0

    open_row = summary["open_positions_at_end"][SYMBOL]
    accrued = summary["entry_commissions_accrued_open_usdt"]
    assert accrued == pytest.approx(open_row["entry_commission_usdt"])
    assert accrued > 0, "una entrada en PAPER paga comisión: omitirla era el defecto D5"

    # El total sí la incluye, y se puede reconstruir desde el broker sin el resumen.
    assert summary["costs_total_usdt"] == pytest.approx(
        summary["costs_usdt"] + accrued, abs=1e-9
    )
    assert lane.broker.accrued_entry_commissions() == pytest.approx(accrued, abs=1e-9)

    # La identidad económica completa: capital inicial + realizado + no realizado neto.
    assert summary["pnl_unrealised_usdt"] == pytest.approx(
        open_row["unrealised_pnl_usdt"] - accrued, abs=1e-9
    )
    assert summary["pnl_total_usdt"] == pytest.approx(
        summary["pnl_realised_usdt"] + summary["pnl_unrealised_usdt"], abs=1e-9
    )
    assert summary["marked_equity_usdt"] == pytest.approx(
        10_000.0 + summary["pnl_total_usdt"], abs=1e-6
    )
    # El FILL del ledger es la evidencia cruda de que la posición existe.
    fills = of_kind(rows, "FILL")
    assert len(fills) == 1 and fills[0]["position_id"] == open_row["position_id"]


def test_reconciliation_identities_cover_the_open_half(tmp_path: Path) -> None:
    _, summary, _ = run_lane(tmp_path, series=flat_bars(), script=long_then_flat)
    identities = summary["reconciliation"]["identities"]

    assert identities["total_costs_equal_realised_plus_accrued"]
    assert identities["realised_costs_equal_closed_trade_legs"]
    assert identities["marked_equity_rebuilds_from_open_position"]
    assert identities["total_pnl_moves_the_marked_book"]
    assert identities["open_positions_are_disjoint_from_closed_trades"]
    assert summary["reconciliation"]["open_positions_at_end"] == 1
    assert summary["reconciliation"]["open_position_ids_at_end"] == [
        summary["open_positions_at_end"][SYMBOL]["position_id"]
    ]


# -------------------------------------------------------- cierre: una sola vez


def test_a_close_moves_the_commission_from_accrued_to_realised_once(tmp_path: Path) -> None:
    """La barra 25 perfora el stop del 0,5 %, así que la posición cierra dentro de la serie."""

    stop_price = 100.0 * (1.0 - POLICY_STOP_PCT / 100.0)
    bars = flat_bars(patches={25: (100.0, 100.0, stop_price - 0.2, 99.6)})
    _, summary, rows = run_lane(tmp_path, series=bars, script=long_then_flat)

    assert summary["closed_trades"] == 1
    assert summary["entry_commissions_accrued_open_usdt"] == 0
    assert summary["open_positions_at_end"] == {}

    close = of_kind(rows, "CLOSE")[0]
    legs = (
        close["entry_commission_usdt"]
        + close["exit_commission_usdt"]
        + close["execution_cost_usdt"]
    )
    # ``costs_usdt`` se publica con 6 decimales (contrato pre-existente); los términos
    # nuevos llevan 8. La tolerancia es el redondeo, no una holgura de cuadre.
    assert summary["costs_usdt"] == pytest.approx(legs, abs=1e-6)
    assert summary["costs_realised_usdt"] == pytest.approx(legs, abs=1e-9)
    assert summary["costs_total_usdt"] == pytest.approx(legs, abs=1e-9)
    assert summary["costs_total_usdt"] < 2 * legs, "la misma comisión no puede contarse dos veces"

    # El PnL realizado es el neto de esos tres términos, y el marcado ya no añade nada.
    assert summary["pnl_realised_usdt"] == pytest.approx(close["pnl_net_usdt"], abs=1e-9)
    assert summary["pnl_unrealised_usdt"] == pytest.approx(0.0, abs=1e-9)
    assert summary["marked_equity_usdt"] == pytest.approx(
        10_000.0 + summary["pnl_realised_usdt"], abs=1e-6
    )
    assert summary["reconciliation"]["identities"]["open_positions_are_disjoint_from_closed_trades"]


def test_a_run_with_no_trades_publishes_zeroed_terms_not_missing_ones(tmp_path: Path) -> None:
    _, summary, _ = run_lane(
        tmp_path, series=flat_bars(), script=lambda symbol, ts: NO_TRADE % symbol
    )

    assert summary["fills"] == 0 and summary["closed_trades"] == 0
    assert summary["costs_total_usdt"] == 0.0
    assert summary["entry_commissions_accrued_open_usdt"] == 0.0
    assert summary["pnl_unrealised_usdt"] == 0.0
    assert summary["marked_equity_usdt"] == pytest.approx(10_000.0, abs=1e-6)
    assert all(summary["reconciliation"]["identities"].values())
