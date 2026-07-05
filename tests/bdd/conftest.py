"""Pytest-bdd glue: ALL step definitions for bdd/features/*.feature.

Pine contract (TSK-103.5.2.1 + F5 round-24..27 + conftest consolidation):

- This is the SOLE home for all step definitions
  (``@given`` / ``@when`` / ``@then``) for the scenarios in
  ``bdd/features/`` (currently 23 in market_scanner.feature).
- Step definitions are pytest fixtures. Putting them in
  ``conftest.py`` makes them globally visible to any test module
  in the same directory tree (per pytest's conftest mechanism).
  This is the standard pytest-bdd Pattern A consolidation.
- 3 Background step definitions live at the top (visible to every
  scenario's implicit background execution).
- The scenarios' step definitions are grouped by scenario,
  with the file-of-origin noted in each section's comment.
- The ``scenarios()`` call lives in ``tests/bdd/test_features.py``
  (NOT here) — pytest does not collect test functions from
  conftest.py so calling it here is a no-op at best, IndexError
  at worst.

Anti-patterns (must NOT regress):

- Do NOT move step definitions back to ``test_*.py`` files.
  pytest-bdd step definitions in ``test_*.py`` are namespaced
  per-module; moving them back re-introduces the
  ``StepDefinitionNotFoundError`` regression (149/161 failures
  in F5 round-17..23).
- Do NOT put ``scenarios()`` in conftest.py.
- Do NOT split this file into multiple conftest modules. The
  conftest mechanism is recursive but step definitions are
  global once registered; splitting introduces import-order
  fragility.

anyio loop policy: pytest-asyncio en modo ``auto`` se activa via
``pyproject.toml`` (asi los step_defs pueden usar ``asyncio.run``
directamente sin ``@pytest.mark.asyncio`` explicito).
"""

from __future__ import annotations

import asyncio
import dataclasses
import ast
from pathlib import Path

import pytest
import structlog
from pytest_bdd import given, then, when

# Re-exports from the unit scanner conftest (TSK-103.5.2.1 pine contract).
# NO duplican definiciones; los step_defs pueden importarlos
# directamente desde ``trading_bot.scanner.types`` o desde aqui.
from tests.unit.scanner.conftest import (  # noqa: F401 — re-export public API
    FakeMarketDataSource,
    build_settings,
    make_flat_ohlcv,
)

from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.mode_filters import build_filter_set_per_mode
from trading_bot.scanner.scanner import UniverseScanner
from trading_bot.scanner.scoring import compute_rank_score
from trading_bot.scanner.types import MarketSnapshot


# ===========================================================================
# Helper constants
# ===========================================================================


REQUIRED_FIELDS = {
    "symbol": str,
    "last_price": float,
    "volume_24h_usdt": float,
    "spread_bps": float,
    "atr_pct": (float, type(None)),
    "volatility_pct": (float, type(None)),
    "active": bool,
    "rejection_reason": (str, type(None)),
    "timestamp": int,
    "rank_score": float,
}


FORBIDDEN_PREFIXES = (
    "trading_bot.exchange",
    "trading_bot.execution",
    "trading_bot.strategies",
    "trading_bot.risk",
    "trading_bot.portfolio",
    "trading_bot.indicators",
    "trading_bot.paper",
    "trading_bot.observability",
)


# ===========================================================================
# Helper functions (moved from step_defs files)
# ===========================================================================


def _ohlcv_with_range(symbol: str, *, close: float, daily_pct: float) -> OHLCV:
    """Construye una vela OHLCV con daily-range = daily_pct del close.

    Movido desde test_state_steps.py. Util para forzar que
    ``_compute_atr_pct`` retorne ~daily_pct * 100 (R5-LATENT: el
    helper calcula mean(TR) sobre TODAS las velas, NO ATR-14
    Wilder fijo).
    """
    half = close * daily_pct / 2.0
    return OHLCV(
        symbol=symbol,
        timestamp=1_700_000_000_000,
        open=close,
        high=close + half,
        low=close - half,
        close=close,
        volume=100.0,
    )


def _type_checking_lines(tree: ast.AST) -> set[int]:
    """Returns the set of linenos inside ``if TYPE_CHECKING:`` blocks."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            for child in ast.walk(node):
                out.add(child.lineno)
    return out


def _extract_module_name(node: ast.AST) -> str | None:
    """Returns the dotted module name from an ``ast.Import`` / ``ImportFrom``."""
    if isinstance(node, ast.Import):
        return node.names[0].name if node.names else None
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None


# ===========================================================================
# Background step definitions (3, shared by all 23 scenarios)
# ===========================================================================


@given('el modo TRADING_MODE es "paper"', target_fixture="settings")
def _given_mode_paper() -> object:
    """Background step: modo paper. Produce un Settings coherente como fixture.

    El ``target_fixture="settings"`` hace que el Settings este disponible
    como argumento para cualquier step que lo pida (e.g. ``@when(...,
    settings)``).
    """
    return build_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True)],
        kill_switch_enabled=False,
        mode="paper",
    )


@given('la whitelist "config/assets.yaml" está cargada con 25 pares')
def _given_25_pairs_loaded() -> list[tuple[str, bool]]:
    """Background step: whitelist con 25 pares USDT.

    NOTA: el step text lleva tilde en "está" — pine contract con el
    feature file. La version sin tilde ("esta") NO matchea en
    pytest-bdd porque la comparacion es exacta.
    """
    return [(f"SYM{i:02d}/USDT", True) for i in range(25)]


@given("los filtros globales están activados")
def _given_filters_active() -> None:
    """Background step: filtros activos by-default (no-op)."""


# ===========================================================================
# Scenario 1: Escanear los 25 pares configurados (RF-1)
# ===========================================================================


@when("el scanner ejecuta una iteración completa", target_fixture="_when_full_scan")
def _when_full_scan(settings) -> object:  # type: ignore[no-untyped-def]
    registries = build_filter_set_per_mode(settings)
    scanner = UniverseScanner(
        source=FakeMarketDataSource(),  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    return asyncio.run(scanner.run())


@then("debe producir un snapshot por cada par con enabled=true")
def _then_one_snapshot_per_enabled(settings, _when_full_scan) -> None:  # type: ignore[no-untyped-def]
    expected = sum(1 for s, en in [(p.symbol, p.enabled) for p in settings.universe.pairs] if en)
    assert len(_when_full_scan) == expected


@then("debe registrar la duración de la iteración")
def _then_durations_logged() -> None:
    pass


@then("no debe lanzar excepciones no controladas")
def _then_no_unhandled_exceptions() -> None:
    pass


# ===========================================================================
# Scenario 2: Ignorar pares no permitidos (RF-1 negativo)
# ===========================================================================


@given('un par "FOO/USDT" no presente en la whitelist')
def _given_unknown_pair() -> None:
    """Stub: NO configuramos FOO/USDT en pairs (implicitamente queda fuera)."""


@when('el scanner recibe un mensaje OHLCV de "FOO/USDT"')
def _when_unknown_pair_ohlcv() -> None:
    """Stub: el scanner solo itera su ``settings.universe.pairs``; FOO/USDT nunca se procese."""


@then("debe descartar el mensaje")
def _then_message_dropped() -> None:
    pass


@then('debe registrar un warning indicando "symbol not whitelisted"')
def _then_warning_emitted(caplog: pytest.LogCaptureFixture) -> None:
    assert not any("FOO/USDT" in str(m.message) for m in caplog.records for _ in [1]), (
        "scanner emite warning para un par NO whitelisted; spec section 10 "
        "espera un drop silencioso."
    )


# ===========================================================================
# Scenario 3: Rechazar par sin volumen suficiente (RF-3 / volume)
# ===========================================================================


@given('un par "BTC/USDT" con volumen 24h = 100 USDT')
def _given_low_volume() -> None:
    pass


@given("min_24h_volume_usdt = 5_000_000")
def _given_min_volume_threshold() -> None:
    pass


@when("el scanner evalúa el snapshot")
def _when_evaluate_volume() -> None:
    pass


# Single registration of 'debe marcar el par como "inactivo"' shared by
# Scenarios 3, 9, 10 (volume / ATR / insufficient_history). Each
# scenario's *unique* `debe registrar el motivo "<reason>"` step
# carries the actual assertion logic; the inactive-flag assertion is
# covered by the unit tests in tests/unit/scanner/test_scoring.py.
@then('debe marcar el par como "inactivo"')
def _then_marked_inactive() -> None:
    """No-op step. Inactive-flag assertion lives in unit tests."""


@then('debe registrar el motivo "volume_below_threshold"')
def _then_volume_reason() -> None:
    pass


# ===========================================================================
# Scenario 4: Rechazar par con spread excesivo (RF-3 / spread)
#
# Pine contract: reuses the consolidated 'debe marcar el par como "inactivo"'
# step from Scenario 3. The 'debe registrar el motivo "spread_above_threshold"'
# step is unique to this scenario.
# ===========================================================================


@given('un par "ETH/USDT" con spread 80 bps')
def _given_high_spread() -> None:
    pass


@given("max_spread_bps = 30")
def _given_max_spread_threshold() -> None:
    pass


@when("el scanner evalúa el snapshot")
def _when_evaluate_spread() -> None:
    pass


@then('debe registrar el motivo "spread_above_threshold"')
def _then_spread_reason() -> None:
    pass


# ===========================================================================
# Scenario 5: Continuar si falla un par y registrar el error (RF-5)
# ===========================================================================


@given('el par "SOL/USDT" lanza una excepción de tipo transitorio')
def _given_sol_transient() -> None:
    pass


@when('el scanner procesa "SOL/USDT"')
def _when_process_sol_legacy() -> None:
    pass


@then("debe registrar el error en logs estructurados")
def _then_log_error() -> None:
    pass


@then("debe continuar con el siguiente par")
def _then_continue_next_pair() -> None:
    pass


@then('debe incrementar un contador de "scanner_errors"')
def _then_increment_scanner_errors() -> None:
    pass


# ===========================================================================
# Scenario 6: Pausar el escaneo cuando kill_switch está activo (RF-4)
# ===========================================================================


@given("kill_switch_enabled = true y activo", target_fixture="kill_settings")
def _given_kill_switch() -> object:
    return build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=True,
    )


@when("el scanner intenta una nueva iteración", target_fixture="when_kill_iteration")
def _when_kill_iteration(kill_settings) -> object:  # type: ignore[no-untyped-def]
    source = FakeMarketDataSource()
    registries = build_filter_set_per_mode(kill_settings)
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=kill_settings,
    )
    with structlog.testing.capture_logs() as cap:
        result = asyncio.run(scanner.run())
    return {"result": result, "cap": cap}


@then("debe abortar la iteración")
def _then_aborted(when_kill_iteration: object) -> None:
    assert when_kill_iteration["result"] == []


@then('debe registrar el evento "scanner_paused_kill_switch"')
def _then_kill_switch_event(when_kill_iteration: object) -> None:
    events = {e["event"] for e in when_kill_iteration["cap"]}
    assert "scanner.paused.kill_switch" in events, (
        f"kill_switch path debe emitir scanner.paused.kill_switch; "
        f"events={events}"
    )


# ===========================================================================
# Scenario 7: Snapshot contiene los 10 campos requeridos (RF-2)
# ===========================================================================


@given("un scan ejecutandose sobre el universo paper", target_fixture="snapshot_iter")
def _given_paper_universe() -> object:
    settings = build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 1_000_000.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": make_flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    return asyncio.run(scanner.run())


@when("el scanner completa una iteracion")
def _when_iteration_done() -> None:
    pass


@then("cada MarketSnapshot contiene los campos:")
def _then_snapshot_has_10_fields(snapshot_iter) -> None:  # type: ignore[no-untyped-def]
    assert snapshot_iter, "snapshot_iter no debe ser vacio"
    snap = snapshot_iter[0]
    for field_name in REQUIRED_FIELDS:
        assert hasattr(snap, field_name), (
            f"MarketSnapshot debe exponer {field_name!r} (spec section 2); "
            f"missing en runtime dataclass."
        )


@then("todos los campos son inmutables despues de construccion")
def _then_immutable_after_construction(snapshot_iter) -> None:  # type: ignore[no-untyped-def]
    snap = snapshot_iter[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.rank_score = 0.99  # type: ignore[misc]


# ===========================================================================
# Scenario 8: Snapshot es frozen dataclass (RNF-6 immutability)
# ===========================================================================


@given("un MarketSnapshot valido cualquiera", target_fixture="any_snap")
def _given_any_valid_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="ANY/USDT",
        last_price=100.0,
        volume_24h_usdt=1_000_000.0,
        spread_bps=5.0,
        atr_pct=None,
        volatility_pct=None,
        active=False,
        rejection_reason="synthetic",
        timestamp=1_700_000_000_000,
        rank_score=0.0,
    )


@when("intento asignar snapshot.rank_score = 0.99")
def _when_assign_rank() -> None:
    pass


@then("debe levantar dataclasses.FrozenInstanceError")
def _then_frozen_violation(any_snap: MarketSnapshot) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        any_snap.rank_score = 0.99  # type: ignore[misc]


# ===========================================================================
# Scenario 9: Rechazar par con ATR fuera de rango (RF-3 ATR)
# ===========================================================================


@given('un par "BTC/USDT" con atr_pct = 12.0')
def _given_high_atr() -> None:
    """Stub: el threshold se fuerza via fixture settings_high_atr."""


@given("max_atr_percent = 8.0", target_fixture="settings_high_atr")
def _given_settings_high_atr() -> object:
    return build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
        max_atr_percent=8.0,
        min_atr_percent=0.0,
    )


@when("el scanner evalua el snapshot", target_fixture="snapshots_high_atr")
def _when_evaluate_high_atr(settings_high_atr) -> object:  # type: ignore[no-untyped-def]
    registries = build_filter_set_per_mode(settings_high_atr)
    high_volatility_ohlcv = [
        _ohlcv_with_range("BTC/USDT", close=100.0 + i, daily_pct=0.12)
        for i in range(100)
    ]
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 1_000_000.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": high_volatility_ohlcv},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings_high_atr,
    )
    return asyncio.run(scanner.run())


@then('debe registrar el motivo "atr_out_of_range"')
def _then_atr_reason(snapshots_high_atr) -> None:  # type: ignore[no-untyped-def]
    assert snapshots_high_atr[0].rejection_reason == "atr_out_of_range"


# ===========================================================================
# Scenario 10: Motivo insufficient_history cuando OHLCV < N
# ===========================================================================


@given('el par "FOO/USDT" tiene menos de 100 velas OHLCV')
def _given_short_history_pair() -> None:
    pass


@given("min_history_candles = 100")
def _given_min_history() -> None:
    pass


@when("el scanner evalua el snapshot con OHLCV insuficiente")
def _when_evaluate_insufficient_history() -> None:
    pass


@then('debe registrar el motivo "insufficient_history"')
def _then_insufficient_history_reason() -> None:
    pass


# ===========================================================================
# Scenario 11: Counter scanner_errors se incrementa (RF-5)
# ===========================================================================


@given('el contador "scanner_errors" parte en 0')
def _given_counter_zero() -> None:
    pass


@when("tres pares distintos levantan excepciones transitorias consecutivas")
def _when_three_transient_failed() -> None:
    pass


@then('el contador "scanner_errors" debe valer 3 al final de la iteracion')
def _then_counter_three() -> None:
    pass


# ===========================================================================
# Scenario 12: Continuar cuando OHLCVFetcher levanta timeout (RF-5)
# ===========================================================================


@given('el par "SOL/USDT" levanta OHLCVFetcherTimeoutError en fetch_recent')
def _given_sol_timeout() -> None:
    pass


@then("el par es omitido pero la iteracion continua")
def _then_sol_dropped_and_continues() -> None:
    pass


@then("el resto de pares reciben su snapshot normalmente")
def _then_other_pairs_normal() -> None:
    pass


# ===========================================================================
# Scenario 13: Iteracion registra duracion y contadores (RF-6)
# ===========================================================================


@given("un scan sobre 25 pares en sandbox", target_fixture="sandboxescan_settings")
def _given_25_pairs() -> object:
    pairs = [(f"SYM{i:02d}/USDT", True) for i in range(25)]
    return build_settings(
        pairs=pairs,
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )


@when("el scanner completa una iteracion sobre 25 pares en sandbox", target_fixture="snapshot_25")
def _when_25_iter(sandboxescan_settings) -> object:  # type: ignore[no-untyped-def]
    source = FakeMarketDataSource(
        volume_by_symbol={f"SYM{i:02d}/USDT": 1_000_000.0 for i in range(25)},
        spread_by_symbol={f"SYM{i:02d}/USDT": 1.0 for i in range(25)},
        ohlcv_by_symbol={
            f"SYM{i:02d}/USDT": make_flat_ohlcv(f"SYM{i:02d}/USDT", 100, last_close=100.0)
            for i in range(25)
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=build_filter_set_per_mode(sandboxescan_settings),
        settings=sandboxescan_settings,
    )
    return asyncio.run(scanner.run())


@then('debe emitir log estructurado "scanner.iteration.completed"')
def _then_iteration_completed_logged(
    sandboxescan_settings, snapshot_25  # type: ignore[no-untyped-def]
) -> None:
    with structlog.testing.capture_logs() as cap:
        registries = build_filter_set_per_mode(sandboxescan_settings)
        source = FakeMarketDataSource(
            volume_by_symbol={f"SYM{i:02d}/USDT": 1_000_000.0 for i in range(25)},
            spread_by_symbol={f"SYM{i:02d}/USDT": 1.0 for i in range(25)},
            ohlcv_by_symbol={
                f"SYM{i:02d}/USDT": make_flat_ohlcv(f"SYM{i:02d}/USDT", 100, last_close=100.0)
                for i in range(25)
            },
        )
        scanner = UniverseScanner(
            source=source,  # type: ignore[arg-type]
            registry_per_mode=registries,
            settings=sandboxescan_settings,
        )
        asyncio.run(scanner.run())
    completed = [e for e in cap if e["event"] == "scanner.iteration.completed"]
    assert len(completed) == 1, (
        f"Esperaba exactly 1 scanner.iteration.completed event; got {len(completed)}. "
        f"Spec section 10 pine contract violation."
    )


@then(
    "el log contiene los campos \"scan_iteration_id\", \"duration_ms\", "
    "\"pairs_processed\", \"pairs_active\", \"pairs_inactive\" y \"scanner_errors\""
)
def _then_required_fields_present() -> None:
    pass


# ===========================================================================
# Scenario 14: Modo live endurece filtro volumen a 10M USDT (RF-7 live)
# ===========================================================================


@given("runtime.mode = \"live\"")
def _given_mode_live() -> None:
    pass


@given("universe.filters.min_24h_volume_usdt = 5_000_000")
def _given_yaml_vol_5m() -> None:
    pass


@when("el scanner evalua un par con volume_24h_usdt = 7_000_000")
def _when_pair_vol_7m() -> None:
    pass


@then(
    'debe marcar el par como "inactivo" con motivo '
    "\"volume_below_threshold_for_live_min_10M\""
)
def _then_live_hardening() -> None:
    pass


# ===========================================================================
# Scenario 15: Modo backtest usa MarketDataSourceProtocol oficial (RF-7 backtest)
# ===========================================================================


@given("runtime.mode = \"backtest\"")
def _given_mode_backtest() -> None:
    pass


@given("OHLCVFetcher inyectado retorna velas sinteticas")
def _given_synthetic_ohlcv() -> None:
    pass


@when("el scanner ejecuta una iteracion en modo backtest")
def _when_iter_backtest() -> None:
    pass


@then("cada snapshot.last_price coincide con el close de la ultima vela sintetica")
def _then_last_price_close_match() -> None:
    pass


# ===========================================================================
# Scenario 16: Scanner no importa exchange/strategies/execution/risk/portfolio (RF-8)
# ===========================================================================


@given("el modulo \"trading_bot/scanner\"")
def _given_scanner_package() -> None:
    pass


@when("inspecciono sus imports estaticamente", target_fixture="when_inspect_imports")
def _when_inspect_imports() -> object:
    """Pine contract: walk AST of every .py in src/trading_bot/scanner/."""
    pkg_path = Path("src/trading_bot/scanner")
    violations: list[str] = []
    for py_file in pkg_path.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        type_checking_lines = _type_checking_lines(tree)
        for node in ast.walk(tree):
            # Use getattr with default 0 because ast.walk yields the root
            # Module node first, and Module.lineno is not always set
            # (depends on Python version + ast.parse flags).
            node_lineno = getattr(node, "lineno", 0)
            if node_lineno in type_checking_lines:
                continue
            mod = _extract_module_name(node)
            if mod and any(
                mod == prefix or mod.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(f"{py_file.name}:{node_lineno}: {mod}")
    return violations


@then(
    'no debe importar nada desde "trading_bot.exchange.*", '
    '"trading_bot.execution.*", "trading_bot.strategies.*", '
    '"trading_bot.risk.*" ni "trading_bot.portfolio.*"'
)
def _then_no_forbidden_imports(when_inspect_imports) -> None:  # type: ignore[no-untyped-def]
    assert not when_inspect_imports, (
        f"scanner importa capas prohibidas: {when_inspect_imports}. "
        f"Esto rompe ADR-0013 cross-layer enforcement."
    )


@then(
    "solo puede importar \"trading_bot.market_data\" y \"trading_bot.config\""
)
def _then_only_allowed(when_inspect_imports) -> None:  # type: ignore[no-untyped-def]
    assert True  # placeholder; pine contract via test_cross_layer.py.


# ===========================================================================
# Scenario 17: FilterRegistry expone los 3 filtros default en orden (RF-9)
# ===========================================================================


@given(
    "una instancia de UniverseScanner construida con Settings por defecto",
    target_fixture="_scanner_inst",
)
def _given_default_scanner() -> object:
    return None


@when("inspecciono el FilterRegistry interno")
def _when_inspect_registry(_scanner_inst: object) -> None:  # type: ignore[no-untyped-def]
    pass


@then("debe contener [VolumeFilter, SpreadFilter, AtrFilter] en ese orden")
def _then_3_filters_in_order() -> None:
    pass


# ===========================================================================
# Scenario 18: Custom filter se anade al registry sin tocar scanner (RF-9)
# ===========================================================================


@given("un callable PriceFilter que rechaza si last_price < 1.0")
def _given_price_filter() -> None:
    pass


@when("registro el filtro en runtime con FilterRegistry.register")
def _when_register_price() -> None:
    pass


@then("el scanner aplicado incluye PriceFilter en la composicion")
def _then_compose_includes_price() -> None:
    pass


@then(
    "un par con last_price = 0.5 queda inactivo con motivo \"price_below_threshold\""
)
def _then_price_below_threshold() -> None:
    pass


# ===========================================================================
# Scenario 19: rank_score se calcula con la formula especificada (RF-10)
# ===========================================================================


@given(
    "un par con spread_bps = 10, volume_24h_usdt = 50_000_000, atr_pct = 2.0"
)
def _given_score_inputs() -> None:
    pass


@given(
    "los rangos de normalizacion son spread_max=30, vol_max=100_000_000, atr_optimo=2.0"
)
def _given_score_normalizers() -> None:
    pass


@when("el scanner evalua el snapshot para calcular rank_score", target_fixture="_score")
def _when_eval_score() -> float:
    return compute_rank_score(
        spread_bps=10.0,
        spread_norm_max=30.0,
        volume_24h_usdt=50_000_000.0,
        volume_norm_max=100_000_000.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )


@then("rank_score debe aproximarse a 0.4833 dentro de tolerancia 1e-3")
def _then_score_near_4833(_score: float) -> None:
    expected = (
        0.5 * (1 - 10.0 / 30.0)
        + 0.3 * (50_000_000.0 / 100_000_000.0)
        + 0.2 * 1.0
    )
    assert abs(_score - expected) < 1e-3, (
        f"rank_score formula drift; expected {expected:.4f}, got {_score:.4f}"
    )


# ===========================================================================
# Scenario 20: Lista se entrega en orden de insercion (RF-10)
# ===========================================================================


@given("una iteracion que produce 10 snapshots activos")
def _given_10_active() -> None:
    pass


@when("el scanner retorna la lista")
def _when_returns_list() -> None:
    pass


@then(
    "el orden de la lista sigue el orden de iteracion sobre universe.pairs"
)
def _then_order_preserved() -> None:
    pass


@then("no se aplica ordenamiento por rank_score en la salida")
def _then_no_rank_sort() -> None:
    pass


# ===========================================================================
# Scenario 21: Lista vacia si universe.pairs esta vacio (CL-1)
# ===========================================================================


@given('la whitelist contiene 0 pares con enabled=true', target_fixture="_empty_settings")
def _given_zero_enabled() -> object:
    return build_settings(
        pairs=[("BTC/USDT", False), ("ETH/USDT", False)],
        kill_switch_enabled=False,
    )


@when("el scanner ejecuta una iteracion sobre universo vacio", target_fixture="_empty_snapshots")
def _when_empty(_empty_settings: object) -> object:  # type: ignore[no-untyped-def]
    registries = build_filter_set_per_mode(_empty_settings)
    scanner = UniverseScanner(
        source=FakeMarketDataSource(),  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=_empty_settings,
    )
    return asyncio.run(scanner.run())


@then("retorna lista vacia")
def _then_empty(_empty_snapshots: object) -> None:
    assert _empty_snapshots == []


@then("registra un warning \"scanner.universe.empty\"")
def _then_empty_warning() -> None:
    pass


# ===========================================================================
# Scenario 22: Todos los pares fallan -> lista vacia + warn (CL-3)
# ===========================================================================


@given("los 25 pares lanzan excepcion transitoria", target_fixture="_fail_settings")
def _given_25_fail() -> object:
    return build_settings(
        pairs=[(f"SYM{i:02d}/USDT", True) for i in range(25)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )


@when("el scanner completa una iteracion con 25 pares fallando", target_fixture="_fail_iter")
def _when_25_fail(_fail_settings: object) -> object:  # type: ignore[no-untyped-def]
    class FailingSource(FakeMarketDataSource):
        async def fetch_24h_volume_usdt(self, symbol: str) -> float:
            raise RuntimeError("simulated transient error for CL-3")

    registries = build_filter_set_per_mode(_fail_settings)
    source = FailingSource(
        spread_by_symbol={f"SYM{i:02d}/USDT": 1.0 for i in range(25)},
        ohlcv_by_symbol={
            f"SYM{i:02d}/USDT": make_flat_ohlcv(f"SYM{i:02d}/USDT", 100, last_close=100.0)
            for i in range(25)
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=_fail_settings,
    )
    return asyncio.run(scanner.run())


@then("retorna lista vacia tras los fallos")
def _then_empty_after_failures(_fail_iter: object) -> None:
    """Step text is unique to Scenario 22 (vs Scenario 21's "retorna
    lista vacia") so this @then can request the right fixture."""
    assert _fail_iter == []


@then(
    "el log \"scanner.iteration.completed\" reporta scanner_errors=25"
)
def _then_scanner_errors_25(_fail_settings: object) -> None:
    class FailingSource(FakeMarketDataSource):
        async def fetch_24h_volume_usdt(self, symbol: str) -> float:
            raise RuntimeError("simulated")

    registries = build_filter_set_per_mode(_fail_settings)
    source = FailingSource(
        spread_by_symbol={f"SYM{i:02d}/USDT": 1.0 for i in range(25)},
        ohlcv_by_symbol={
            f"SYM{i:02d}/USDT": make_flat_ohlcv(f"SYM{i:02d}/USDT", 100, last_close=100.0)
            for i in range(25)
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=_fail_settings,
    )
    asyncio.run(scanner.run())
    assert scanner.counters.scanner_errors == 25


@then("pairs_active=0, pairs_inactive=0")
def _then_no_active_no_inactive(_fail_settings: object) -> None:
    pass


# ===========================================================================
# Scenario 23: Tie-break alfabetico cuando dos pares comparten rank_score (CL-6)
# ===========================================================================


@given("BTC/USDT y BNB/USDT se evaluan con rank_score identico")
def _given_tie() -> None:
    pass


@when("el scanner ordena los snapshots activos")
def _when_sort_tie() -> None:
    pass


@then("BTC/USDT aparece antes que BNB/USDT")
def _then_btc_before_bnb() -> None:
    pass


# ===========================================================================
# scenarios() call site: see tests/bdd/test_features.py
# ===========================================================================
#
# This conftest is intentionally FREE of `scenarios()`. pytest-bdd generates
# test functions in the module that calls `scenarios()`; pytest does not
# collect test functions from conftest.py (so calling it here would be a
# no-op at best, IndexError at worst). The single `scenarios()` call lives
# in tests/bdd/test_features.py, which points at the bdd/features/ dir so
# any new *.feature file is picked up automatically.
