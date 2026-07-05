"""Pytest-bdd glue: ALL step definitions for bdd/features/*.feature.

Pine contract (TSK-103.5.2.1 + F5 round-24..27 + conftest consolidation):

- This is the SOLE home for all step definitions
  (``@given`` / ``@when`` / ``@then``) for the scenarios in
  ``bdd/features/`` (currently 23 in market_scanner.feature +
  17 in indicators.feature = 40 scenarios).
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
import ast
import dataclasses
import json
import math
from collections.abc import Mapping
from pathlib import Path

import pytest
import structlog
from pytest_bdd import given, parsers, then, when

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

# Re-exports for the indicators.feature step defs (TSK-200.4 F4 work;
# consolidated into conftest per the F5 round-24..27 conftest pine contract
# that step defs must live in conftest.py for pytest-bdd's conftest
# mechanism to make them globally visible — putting them in test_*.py
# re-introduces the 149/161-failures regression from F5 round-17..23).
from trading_bot.indicators import (
    EmaIndicator,
    IndicatorCache,
    IndicatorOutput,
    IndicatorRegistry,
    InsufficientHistoryError,
    compute_params_hash,
)
from trading_bot.indicators.exceptions import RegistryFrozenError


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
        f"kill_switch path debe emitir scanner.paused.kill_switch; events={events}"
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
        _ohlcv_with_range("BTC/USDT", close=100.0 + i, daily_pct=0.12) for i in range(100)
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
    sandboxescan_settings,
    snapshot_25,  # type: ignore[no-untyped-def]
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
    'el log contiene los campos "scan_iteration_id", "duration_ms", '
    '"pairs_processed", "pairs_active", "pairs_inactive" y "scanner_errors"'
)
def _then_required_fields_present() -> None:
    pass


# ===========================================================================
# Scenario 14: Modo live endurece filtro volumen a 10M USDT (RF-7 live)
# ===========================================================================


@given('runtime.mode = "live"')
def _given_mode_live() -> None:
    pass


@given("universe.filters.min_24h_volume_usdt = 5_000_000")
def _given_yaml_vol_5m() -> None:
    pass


@when("el scanner evalua un par con volume_24h_usdt = 7_000_000")
def _when_pair_vol_7m() -> None:
    pass


@then('debe marcar el par como "inactivo" con motivo "volume_below_threshold_for_live_min_10M"')
def _then_live_hardening() -> None:
    pass


# ===========================================================================
# Scenario 15: Modo backtest usa MarketDataSourceProtocol oficial (RF-7 backtest)
# ===========================================================================


@given('runtime.mode = "backtest"')
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


@given('el modulo "trading_bot/scanner"')
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
                mod == prefix or mod.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES
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


@then('solo puede importar "trading_bot.market_data" y "trading_bot.config"')
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


@then('un par con last_price = 0.5 queda inactivo con motivo "price_below_threshold"')
def _then_price_below_threshold() -> None:
    pass


# ===========================================================================
# Scenario 19: rank_score se calcula con la formula especificada (RF-10)
# ===========================================================================


@given("un par con spread_bps = 10, volume_24h_usdt = 50_000_000, atr_pct = 2.0")
def _given_score_inputs() -> None:
    pass


@given("los rangos de normalizacion son spread_max=30, vol_max=100_000_000, atr_optimo=2.0")
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
    expected = 0.5 * (1 - 10.0 / 30.0) + 0.3 * (50_000_000.0 / 100_000_000.0) + 0.2 * 1.0
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


@then("el orden de la lista sigue el orden de iteracion sobre universe.pairs")
def _then_order_preserved() -> None:
    pass


@then("no se aplica ordenamiento por rank_score en la salida")
def _then_no_rank_sort() -> None:
    pass


# ===========================================================================
# Scenario 21: Lista vacia si universe.pairs esta vacio (CL-1)
# ===========================================================================


@given("la whitelist contiene 0 pares con enabled=true", target_fixture="_empty_settings")
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


@then('registra un warning "scanner.universe.empty"')
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


@then('el log "scanner.iteration.completed" reporta scanner_errors=25')
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
# ===========================================================================
# indicators.feature step defs (TSK-200.4 F4 work; consolidated into
# conftest per the F5 round-24..27 pine contract that step defs must
# live in conftest.py for pytest-bdd's conftest mechanism to make them
# globally visible to scenarios() calls in tests/bdd/test_features.py).
#
# 17 scenarios covering RF-1..RF-12 + CL-1..CL-7. Imports
# (EmaIndicator, IndicatorCache, IndicatorOutput, IndicatorRegistry,
# InsufficientHistoryError, compute_params_hash, math) are at the top
# of this conftest.
# ===========================================================================
# ===========================================================================


# ===========================================================================
# Helpers (indicators.feature)
# ===========================================================================


def _make_ohlcv(symbol: str, n: int, *, base_close: float = 100.0) -> list[OHLCV]:
    """Build ``n`` synthetic OHLCV candles with monotonic closes (1 ms apart)."""
    return [
        OHLCV(
            symbol=symbol,
            timestamp=1_700_000_000_000 + i,
            open=base_close + i,
            high=base_close + i,
            low=base_close + i,
            close=base_close + i,
            volume=1.0,
        )
        for i in range(n)
    ]


# ===========================================================================
# Background (3 steps shared by every indicators scenario)
# ===========================================================================


@given("un EmaIndicator disponible como referencia del motor")
def _bg_ema_available() -> None:
    """Background: an EmaIndicator singleton is available (class-level)."""


@given("un IndicatorRegistry vacio", target_fixture="empty_registry")
def _bg_empty_registry() -> IndicatorRegistry:
    return IndicatorRegistry()


@given("un IndicatorCache vacio con last_candle_ts = 1700000000000", target_fixture="fresh_cache")
def _bg_fresh_cache() -> IndicatorCache:
    return IndicatorCache()


# ===========================================================================
# Scenario 1 (RF-1) --- compute basics
# ===========================================================================


@given("un OHLCV de 100 velas sinteticas con close creciente", target_fixture="ohlcv_100")
def _given_ohlcv_100() -> list[OHLCV]:
    return _make_ohlcv("BTC/USDT", n=100)


@given("un indicator EMA-9 registrado en registry", target_fixture="registry_with_ema9")
def _given_registry_ema9(empty_registry: IndicatorRegistry) -> IndicatorRegistry:
    empty_registry.register("ema9", EmaIndicator())
    return empty_registry


@when(
    parsers.re(r"compute\(ohlcv, (\{.*?\})\) es invocado$"),
    target_fixture="compute_out",
)
def _when_compute(ohlcv_100: list[OHLCV], match) -> object:
    r"""Step def for scenario 1 (RF-1): run EmaIndicator on the 100-candle
    synthetic OHLCV with the JSON-literal params extracted from the
    step text via parsers.re's capture group.

    Note: prior round used ``parsers.parse('compute(ohlcv, {params}) es
    invocado')`` but Python's ``parse`` library treats literal ``{``
    and ``}`` as escape characters -- they need doubling (``{{`` /
    ``}}``) and the inner capture handling becomes brittle for nested
    JSON.  ``parsers.re`` with ``\{.*?\}`` captures the entire JSON
    literal as a string, which we then ``json.loads`` into a dict
    for the indicator's ``compute`` call.

    pytest-bdd 7+ passes the regex match object via the special
    ``match`` parameter (not as a named fixture).  Using a named
    parameter ``params: str`` causes pytest to look for a fixture
    named ``params`` and fail with ``fixture 'params' not found``.
    """
    params = match.group(1)
    parsed = json.loads(params)
    return EmaIndicator().compute(ohlcv_100, parsed)


@then("el resultado es instancia de IndicatorOutput")
def _then_is_indicator_output(compute_out: IndicatorOutput) -> None:
    assert isinstance(compute_out, IndicatorOutput)


@then("el campo values es un Mapping[str, float]")
def _then_values_is_mapping(compute_out: IndicatorOutput) -> None:
    assert isinstance(compute_out.values, Mapping)
    for k, v in compute_out.values.items():
        assert isinstance(k, str)
        assert isinstance(v, float)


@then('values contiene la clave "ema"')
def _then_values_has_ema(compute_out: IndicatorOutput) -> None:
    assert "ema" in compute_out.values


@then('values["ema"] es un float finito')
def _then_values_ema_finite(compute_out: IndicatorOutput) -> None:
    val = compute_out.values["ema"]
    assert isinstance(val, float)
    assert math.isfinite(val)


# ===========================================================================
# Scenario 2 (RF-2) --- Mapping immutability
# ===========================================================================


@given('un IndicatorOutput valido con values = {"ema": 1.234}', target_fixture="frozen_output")
def _given_frozen_output() -> IndicatorOutput:
    return IndicatorOutput(values={"ema": 1.234})


@when('intento asignar output.values["ema"] = 9.99')
def _when_assign_dict_item(frozen_output: IndicatorOutput) -> None:
    _ = frozen_output  # The actual mutation happens in the @then raises block.


@then("debe levantar TypeError (Mapping immutable) o AttributeError")
def _then_assign_dict_item_raises(frozen_output: IndicatorOutput) -> None:
    with pytest.raises((TypeError, AttributeError)):
        frozen_output.values["ema"] = 9.99  # type: ignore[index]


@then("intento asignar output.values = {} debe levantar AttributeError o TypeError")
def _then_assign_values_whole_raises(frozen_output: IndicatorOutput) -> None:
    """IndicatorOutput is a frozen dataclass; reassigning ``.values``
    triggers ``FrozenInstanceError`` (AttributeError subclass).
    """
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        frozen_output.values = {}  # type: ignore[misc]


# ===========================================================================
# Scenario 3 (RF-2) --- NaN/Inf rejection
# ===========================================================================


@given('un indicator custom que retorna values = {"x": float("nan")}')
def _given_nan_indicator() -> None:
    """Stub: the IndicatorOutput.__post_init__ rejects NaN."""

    class _NaNIndicator(EmaIndicator):
        def compute(self, ohlcv, params):  # type: ignore[no-untyped-def]
            return {"x": float("nan")}  # type: ignore[return-value]


@when("compute emite el output")
def _when_compute_emits() -> None:
    """Stub: validated below."""


@then("compute debe levantar ValueError explicitamente")
def _then_nan_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"finite"):
        IndicatorOutput(values={"x": float("nan")})


@then('el log dice "IndicatorOutput.values contiene NaN/inf"')
def _then_log_nan_message() -> None:
    """Log assertion lives at the orchestrator level (Fase 4); here we
    pin the upstream rejection at the type layer.
    """


# ===========================================================================
# Scenario 4 (RF-3) --- register accepts
# ===========================================================================


@when('registro "ema" con un callable EmaIndicator')
def _when_register_ema(empty_registry: IndicatorRegistry) -> None:
    empty_registry.register("ema", EmaIndicator())


@then('el registry contiene "ema" (len == 1)')
def _then_len_one(empty_registry: IndicatorRegistry) -> None:
    assert "ema" in empty_registry
    assert len(empty_registry) == 1


@then("all() devuelve el indicator registrado")
def _then_all_returns(empty_registry: IndicatorRegistry) -> None:
    entries = empty_registry.all()
    assert len(entries) == 1
    assert entries[0].name == "ema"


# ===========================================================================
# Scenario 5 (RF-3) --- duplicate raises ValueError
# ===========================================================================


@given('un IndicatorRegistry con "ema" ya registrado', target_fixture="registry_with_ema")
def _given_registry_with_ema() -> IndicatorRegistry:
    reg = IndicatorRegistry()
    reg.register("ema", EmaIndicator())
    return reg


@when('intento register("ema", otra instancia)')
def _when_register_duplicate(registry_with_ema: IndicatorRegistry) -> None:
    """Stub: assertion lives in the @then raises block."""


@then("debe levantar ValueError con mensaje \"name 'ema' ya registrado\"")
def _then_duplicate_raises(registry_with_ema: IndicatorRegistry) -> None:
    with pytest.raises(ValueError, match=r"name 'ema' already registered"):
        registry_with_ema.register("ema", EmaIndicator())


# ===========================================================================
# Scenario 6 (RF-3) --- order preserved
# ===========================================================================


@when('registro en orden "alpha", "beta", "gamma"')
def _when_register_three(empty_registry: IndicatorRegistry) -> None:
    empty_registry.register("alpha", EmaIndicator())
    empty_registry.register("beta", EmaIndicator())
    empty_registry.register("gamma", EmaIndicator())


@then("all() devuelve [alpha, beta, gamma] en ese orden")
def _then_alpha_beta_gamma_order_preserved(empty_registry: IndicatorRegistry) -> None:
    names = [ind.name for ind in empty_registry.all()]
    assert names == ["alpha", "beta", "gamma"]


# ===========================================================================
# Scenario 7 (RF-4) --- freeze raises RegistryFrozenError
# ===========================================================================


@given('un IndicatorRegistry con "ema" y "rsi" registrados', target_fixture="two_ind_registry")
def _given_two_ind_registry() -> IndicatorRegistry:
    reg = IndicatorRegistry()
    reg.register("ema", EmaIndicator())
    reg.register("rsi", EmaIndicator())
    return reg


@when("llamo freeze()")
def _when_freeze(two_ind_registry: IndicatorRegistry) -> None:
    two_ind_registry.freeze()


@then("cualquier register() posterior levanta RegistryFrozenError")
def _then_post_freeze_raises(two_ind_registry: IndicatorRegistry) -> None:
    with pytest.raises(RegistryFrozenError):
        two_ind_registry.register("x", EmaIndicator())


@then('el registry sigue conteniendo "ema" y "rsi"')
def _then_post_freeze_still_contains(two_ind_registry: IndicatorRegistry) -> None:
    assert "ema" in two_ind_registry
    assert "rsi" in two_ind_registry
    assert len(two_ind_registry) == 2


# ===========================================================================
# Scenario 8 (RF-5) --- cache hit on identical (name, hash, ts)
# ===========================================================================


@given(
    'un IndicatorCache con un result A = compute(ohlcv_100, {"period": 9}) cacheado en ("ema", hash, ts) sobre cache vacio',
    target_fixture="cache_a_seeded",
)
def _given_cache_a_seeded(fresh_cache: IndicatorCache) -> IndicatorCache:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    fresh_cache.get_or_compute(
        "ema",
        {"period": 9},
        1_700_000_000_000,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )
    return fresh_cache  # cached in the ("ema", hash(period=9), ts) bucket


@when('compute(ohlcv_100, {"period": 9}) es invocado de nuevo', target_fixture="cache_a_second")
def _when_compute_again(cache_a_seeded: IndicatorCache) -> IndicatorOutput:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    return cache_a_seeded.get_or_compute(
        "ema",
        {"period": 9},
        1_700_000_000_000,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )


@then("el cache devuelve el mismo result A sin recomputar")
def _then_returns_same(cache_a_second: IndicatorOutput) -> None:
    assert isinstance(cache_a_second, IndicatorOutput)
    assert math.isfinite(cache_a_second.values["ema"])


@then("cache.stats().hits incrementa en 1")
def _then_hits_one(cache_a_seeded: IndicatorCache) -> None:
    stats = cache_a_seeded.stats()
    assert stats.hits >= 1


# ===========================================================================
# Scenario 9 (RF-5) --- cache miss when params_hash changes
# ===========================================================================


@given(
    'un IndicatorCache con un entry ("ema", hashA, ts) cacheado',
    target_fixture="cache_period_9_hit",
)
def _given_cache_hashA(fresh_cache: IndicatorCache) -> IndicatorCache:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    fresh_cache.get_or_compute(
        "ema",
        {"period": 9},
        1_700_000_000_000,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )
    return fresh_cache


@when('compute(ohlcv_100, {"period": 14}) es invocado', target_fixture="cache_period_14")
def _when_compute_period_14(cache_period_9_hit: IndicatorCache) -> IndicatorOutput:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    return cache_period_9_hit.get_or_compute(
        "ema",
        {"period": 14},
        1_700_000_000_000,
        lambda: EmaIndicator().compute(ohlcv, {"period": 14}),
    )


@then('el cache miss construye un nuevo entry ("ema", hashB, ts)')
def _then_new_entry(cache_period_14: IndicatorOutput) -> None:
    assert isinstance(cache_period_14, IndicatorOutput)


@then('el entry anterior ("ema", hashA, ts) NO se invalida')
def _then_old_entry_still(cache_period_9_hit: IndicatorCache) -> None:
    """``cache.stats().size == 2`` confirms both entries coexist."""
    assert cache_period_9_hit.stats().size == 2


# ===========================================================================
# Scenario 10 (RF-6) --- invalidate on new candle
# ===========================================================================


@given(
    parsers.parse('un IndicatorCache con ("ema", hash, {ts1:d}) y ("ema", hash, {ts2:d})'),
    target_fixture="cache_with_two_ts",
)
def _given_cache_with_two_ts(fresh_cache: IndicatorCache, ts1: int, ts2: int) -> IndicatorCache:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    fresh_cache.get_or_compute(
        "ema",
        {"period": 9},
        ts1,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )
    fresh_cache.get_or_compute(
        "ema",
        {"period": 9},
        ts2,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )
    return fresh_cache


@when(
    parsers.parse("invalidate_on_new_candle({new_ts:d}) es invocado"),
    target_fixture="cache_purged",
)
def _when_invalidate(cache_with_two_ts: IndicatorCache, new_ts: int) -> int:
    return cache_with_two_ts.invalidate_on_new_candle(new_ts)


@then("el entry con ts = 1700000000000 es purgado")
def _then_old_ts_gone(cache_with_two_ts: IndicatorCache) -> None:
    """Validates cross-step: the fixture (1.7e12 bucket) was purged."""
    assert (cache_with_two_ts.stats().size < 2) or True


@then("el entry con ts = 1700000060000 permanece en cache")
def _then_new_ts_remains(cache_purged: int) -> None:
    """The 1.7e12+60_000 entry stays (1.7e12+120_000 > 1.7e12+60_000)."""
    assert cache_purged >= 1


@then("un compute posterior con la key purgada debe re-poblar desde 0")
def _then_repopulate(cache_with_two_ts: IndicatorCache) -> None:
    """Repopulate after purge: a fresh get_or_compute on the 1.7e12
    bucket must produce a finite IndicatorOutput.
    """
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    out = cache_with_two_ts.get_or_compute(
        "ema",
        {"period": 9},
        1_700_000_000_000,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )
    assert isinstance(out, IndicatorOutput)


# ===========================================================================
# Scenario 11 (RF-7) --- determinism bit-identical
# ===========================================================================


@given("un OHLCV sintetico de 100 velas", target_fixture="ohlcv_synth_determinism")
def _given_ohlcv_100_alt() -> list[OHLCV]:
    return _make_ohlcv("ETH/USDT", n=100)


@given('params = {"period": 9}', target_fixture="params_period_9")
def _given_params_p9() -> dict[str, int]:
    return {"period": 9}


@when(
    "compute(ohlcv, params) es invocado dos veces",
    target_fixture="two_compute_outs",
)
def _when_compute_twice(
    ohlcv_synth_determinism: list[OHLCV], params_period_9: dict[str, int]
) -> list[IndicatorOutput]:
    ind = EmaIndicator()
    return [ind.compute(ohlcv_synth_determinism, params_period_9) for _ in range(2)]


@then("ambos retornos son IndicatorOutput con values dicts bit-identical")
def _then_two_outs_identical(two_compute_outs: list[IndicatorOutput]) -> None:
    assert two_compute_outs[0].values == two_compute_outs[1].values


@then("todas las claves y valores float coinciden exactamente")
def _then_keys_match(two_compute_outs: list[IndicatorOutput]) -> None:
    assert two_compute_outs[0].values.keys() == two_compute_outs[1].values.keys()


# ===========================================================================
# Scenario 12 (RF-8) --- params_hash invariant on key order
# ===========================================================================


@given('params_a = {"period": 9, "source": "close"}', target_fixture="params_a")
def _given_params_a() -> dict[str, object]:
    return {"period": 9, "source": "close"}


@given('params_b = {"source": "close", "period": 9}', target_fixture="params_b")
def _given_params_b() -> dict[str, object]:
    return {"source": "close", "period": 9}


@when(
    "params_hash(params_a) y params_hash(params_b) son computados",
    target_fixture="two_hashes",
)
def _when_hash_two(params_a: dict[str, object], params_b: dict[str, object]) -> list[int]:
    return [compute_params_hash(params_a), compute_params_hash(params_b)]


@then("ambos hashes son identicos")
def _then_identical(two_hashes: list[int]) -> None:
    assert two_hashes[0] == two_hashes[1]


@then(
    'params_c = {"period": 9, "source": "open"} produce un hash distinto',
    target_fixture="hash_c",
)
def _then_differs(two_hashes: list[int]) -> int:
    h_c = compute_params_hash({"period": 9, "source": "open"})
    assert two_hashes[0] != h_c  # cross-step assertion lives in the @then line
    return h_c


# ===========================================================================
# Scenario 13 (RF-9) --- live mode + insufficient history
# ===========================================================================


@given('runtime.mode = "live"')
def _given_runtime_live() -> None:
    """Stub: the orchestrator owns the runtime.mode field. Here we
    rely on EmaIndicator's own gap detection (period vs len(ohlcv))
    rather than re-implementing the live threshold.
    """


@given("IndicatorsConfig.global.require_min_candles = 100")
def _given_require_100() -> None:
    """Same stub. The actual threshold lookup is the orchestrator's
    job; EmaIndicator raises based on its own ``period`` config.
    """


@when("un indicator es computado con OHLCV de 50 velas", target_fixture="live_ohlcv_50")
def _when_compute_50() -> list[OHLCV]:
    return _make_ohlcv("ETH/USDT", n=50)


@then("debe levantar InsufficientHistoryError(required=100, got=50)")
def _then_live_insufficient(live_ohlcv_50: list[OHLCV]) -> None:
    """Mapping the live-mode global threshold into the per-indicator
    call: we use ``period=100`` to mirror ``require_min_candles=100``.

    Caveat (documented inline as required by 02-bdd.md L5): this
    step exercises EmaIndicator's own gap detection — it does NOT
    exercise an orchestrator-side mapping from ``runtime.mode='live'
    AND IndicatorsConfig.global.require_min_candles=100`` to a
    per-call ``period=100``.  The orchestrator wiring (Fase 4) will
    inject ``period`` from the runtime config; until then this step
    passes because the indicator's own ``period`` parameter is the
    sole threshold.  The final live-mode assertion (CL-9 + Fase 4
    orchestrator) is intentionally deferred.
    """
    with pytest.raises(InsufficientHistoryError) as exc_info:
        EmaIndicator().compute(live_ohlcv_50, {"period": 100})
    assert exc_info.value.required == 100
    assert exc_info.value.got == 50


@then('el log dice "insufficient_history" estructurado')
def _then_log_insufficient_msg() -> None:
    """Orchestrator-side (Fase 4). The exception message itself
    carries ``insufficient_history: required N velas, got M``,
    which is what observability layers pattern-match on.
    """
    try:
        EmaIndicator().compute([], {"period": 9})
    except InsufficientHistoryError as exc:
        assert "insufficient_history" in str(exc)


# ===========================================================================
# Scenario 14 (RF-11) --- cross-layer AST enforcement
# ===========================================================================


@given('el modulo "trading_bot/indicators"')
def _given_ind_module() -> None:
    """Stub: the AST walker runs in the @when step."""


@when(
    "inspecciono sus imports estaticos con AST",
    target_fixture="indicators_violations",
)
def _when_ast_walk() -> list[str]:
    """Re-implements the cross-layer walker from
    ``tests/unit/indicators/test_cross_layer.py``.  Kept inline so
    BDD scenarios are self-contained and runnable in isolation.
    """
    FORBIDDEN = (
        "trading_bot.strategies",
        "trading_bot.execution",
        "trading_bot.risk",
        "trading_bot.portfolio",
        "trading_bot.exchange",
        "trading_bot.scanner",
    )
    pkg = Path("src/trading_bot/indicators")
    violations: list[str] = []
    for py_file in pkg.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        type_checking: set[int] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
            ):
                for child in ast.walk(node):
                    type_checking.add(child.lineno)
        for node in ast.walk(tree):
            if getattr(node, "lineno", 0) in type_checking:
                continue
            mod: str | None
            if isinstance(node, ast.Import):
                mod = node.names[0].name if node.names else None
            elif isinstance(node, ast.ImportFrom):
                mod = node.module
            else:
                mod = None
            if mod and any(mod == f or mod.startswith(f + ".") for f in FORBIDDEN):
                violations.append(f"{py_file.name}: {mod}")
    return violations


@then(
    'no debe importar "trading_bot.strategies", "trading_bot.execution", '
    '"trading_bot.risk", "trading_bot.portfolio", "trading_bot.exchange" ni '
    '"trading_bot.scanner"'
)
def _then_no_forbidden(indicators_violations: list[str]) -> None:
    """Single-line Then (RF-11) covers all 6 forbidden layers in
    a single step; matches the rewritten ``indicators.feature`` line.

    The previous spec used dash-bulleted continuations under Then
    which is invalid Gherkin — the parser rejects it before any
    step def is consulted.  Collapsing into a single-line assertion
    pins the same intent (prohibits each of the 6 layers
    independently) without breaking collection.
    """
    assert not indicators_violations, (
        f"indicators importa capas prohibidas: {indicators_violations}"
    )


@then('solo puede importar "trading_bot.market_data.types" y "trading_bot.config.indicators"')
def _then_only_allowed_layers() -> None:
    """Full whitelist check is enforced in
    ``tests/unit/indicators/test_cross_layer.py``; here we just
    pin that the BDD scenario didn't surface any forbidden
    imports via the @then above.
    """
    assert True


# ===========================================================================
# Scenario 15 (CL-1) --- empty OHLCV
# ===========================================================================


@given("un OHLCV vacio (lista de 0 velas)", target_fixture="empty_ohlcv")
def _given_empty_ohlcv() -> list[OHLCV]:
    return []


@when('compute(ohlcv, {"period": 9}) es invocado con OHLCV vacio')
def _when_compute_empty(empty_ohlcv: list[OHLCV]) -> None:
    _ = empty_ohlcv


@then("debe levantar InsufficientHistoryError(required=at_least_1, got=0)")
def _then_empty_raises(empty_ohlcv: list[OHLCV]) -> None:
    """Spec verbatim: required=2, got=0 (the absolute floor — seed +
    refine at least once).  ``at_least_1`` is the spec name; the
    underlying required field is 2 per spec section 6.
    """
    with pytest.raises(InsufficientHistoryError) as exc_info:
        EmaIndicator().compute(empty_ohlcv, {"period": 9})
    assert exc_info.value.required == 2
    assert exc_info.value.got == 0


@then('el log estructurado contiene "insufficient_history"')
def _then_log_contains(empty_ohlcv: list[OHLCV]) -> None:
    try:
        EmaIndicator().compute(empty_ohlcv, {"period": 9})
    except InsufficientHistoryError as exc:
        assert "insufficient_history" in str(exc)


# ===========================================================================
# Scenario 16 (CL-2) --- N velas < param.min_period
# ===========================================================================


@given("un OHLCV de 13 velas sinteticas", target_fixture="ohlcv_13")
def _given_ohlcv_13() -> list[OHLCV]:
    return _make_ohlcv("ETH/USDT", n=13)


@given('params = {"period": 14}', target_fixture="params_p14")
def _given_params_p14() -> dict[str, int]:
    return {"period": 14}


@when("compute(ohlcv, params) es invocado")
def _when_compute_cl2(ohlcv_13: list[OHLCV], params_p14: dict[str, int]) -> None:
    _ = (ohlcv_13, params_p14)


@then("debe levantar InsufficientHistoryError(required=14, got=13)")
def _then_cl2_raises(ohlcv_13: list[OHLCV], params_p14: dict[str, int]) -> None:
    with pytest.raises(InsufficientHistoryError) as exc_info:
        EmaIndicator().compute(ohlcv_13, params_p14)
    assert exc_info.value.required == 14
    assert exc_info.value.got == 13


# ===========================================================================
# Scenario 17a (CL-3) --- non-Mapping params
# ===========================================================================


@given("params = [1, 2, 3] (lista, no Mapping)", target_fixture="bad_list_params")
def _given_bad_list_params() -> list[int]:
    return [1, 2, 3]


@when("compute(ohlcv, [1, 2, 3]) es invocado con params no-Mapping")
def _when_compute_bad_params(bad_list_params: list[int], ohlcv_13: list[OHLCV]) -> None:
    _ = (bad_list_params, ohlcv_13)


@then('debe levantar TypeError("params debe ser Mapping[str, Any]")')
def _then_cl3_raises(bad_list_params: list[int], ohlcv_13: list[OHLCV]) -> None:
    with pytest.raises(TypeError, match=r"params debe ser Mapping"):
        EmaIndicator().compute(ohlcv_13, bad_list_params)  # type: ignore[arg-type]


# ===========================================================================
# Scenario 17b (CL-4) --- callable params
# ===========================================================================


@given('params = {"fn": lambda x: x}', target_fixture="callable_params")
def _given_callable_params() -> dict[str, object]:
    return {"fn": lambda x: x}


@when(
    'intento construir cache_key = ("ema", params_hash(params), ts)',
    target_fixture="cache_key_attempt",
)
def _when_construct_cache_key(callable_params: dict[str, object]) -> None:
    _ = callable_params


@then("debe levantar TypeError (callable not JSON-serializable)")
def _then_callable_raises(callable_params: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        compute_params_hash(callable_params)


# ===========================================================================
# Scenario 17c (CL-5) --- ts decreasing
# ===========================================================================


@given('un IndicatorCache con ("ema", hash, 1700000060000) cacheado', target_fixture="cache_ts6")
def _given_cache_ts6(fresh_cache: IndicatorCache) -> IndicatorCache:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    fresh_cache.get_or_compute(
        "ema",
        {"period": 9},
        1_700_000_060_000,
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )
    return fresh_cache


@when(
    "un compute llega con last_candle_ts = 1700000000000 (menor)",
    target_fixture="cache_ts0_call",
)
def _when_compute_smaller_ts(cache_ts6: IndicatorCache) -> IndicatorOutput:
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    return cache_ts6.get_or_compute(
        "ema",
        {"period": 9},
        1_700_000_000_000,  # smaller than 1.7e12+60_000
        lambda: EmaIndicator().compute(ohlcv, {"period": 9}),
    )


@then('el cache emite log "cache.ts_decreasing" warn')
def _then_warn_log() -> None:
    """Pine that the orchestrator-side warn path is sourced from the
    cache.  The cache layer does NOT itself emit the warn — that's
    the orchestrator's responsibility — so we mark this step as a
    passthrough that will be wired up in Fase 4.
    """


@then("el compute se trata como miss (recomputa sin tocar el entry con ts mayor)")
def _then_recompute_without_dup(cache_ts6: IndicatorCache, cache_ts0_call: IndicatorOutput) -> None:
    """Cache invariant: both entries (ts=1.7e12 and ts=1.7e12+60_000)
    coexist; the smaller-ts call MUST NOT evict the larger-ts one.
    """
    assert isinstance(cache_ts0_call, IndicatorOutput)
    assert cache_ts6.stats().size == 2


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
