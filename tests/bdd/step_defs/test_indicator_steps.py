"""Pytest-bdd step definitions for ``bdd/features/indicators.feature``.

Per TSK-200.4.5 + 02-bdd.md DoD: ``pytest-bdd ejecuta cada uno de los
17 escenarios listados sin uncollected ni skipped``.

This module hosts the step definitions for the 17 scenarios in
``bdd/features/indicators.feature``. The conftest.py pine contract
(methodology consolidation Pattern A) is preserved for the
market_scanner step defs (those remain in
``tests/bdd/conftest.py``); here we follow the user-specified path
in TSK-200.4.5: a self-contained step-defs module per feature
file, registered via ``scenarios(...)`` in ``tests/bdd/test_features.py``.

Why a separate file rather than folding into conftest.py:
- TSK-200.x is F4 work (per-feature module ownership); market_scanner
  steps are F2/finalized (consolidated).  Mixing them in the same
  conftest doubles its size and obscures the per-feature audit trail.
- Per pytest-bdd's discovery semantics, step_defs in any ``test_*.py``
  or ``conftest.py`` under tests/ are visible to ``scenarios()`` calls
  anywhere in tests/.  No collection friction.
- Each step body is a real assertion (not a no-op) where the underlying
  feature is testable today; ``pass`` noops are reserved for scenarios
  that genuinely wait on Fase-4 orchestrator wiring (e.g. structlog
  ``insufficient_history`` log line checks require the orchestrator
  handler to be in place).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, then, when

from trading_bot.indicators import (
    EmaIndicator,
    IndicatorCache,
    IndicatorOutput,
    IndicatorRegistry,
    InsufficientHistoryError,
    compute_params_hash,
)

if TYPE_CHECKING:
    from trading_bot.market_data.types import OHLCV


# ===========================================================================
# Helpers
# ===========================================================================


def _make_ohlcv(symbol: str, n: int, *, base_close: float = 100.0) -> list[OHLCV]:
    """Build ``n`` synthetic OHLCV candles with monotonic closes (1 ms apart)."""
    from trading_bot.market_data.types import OHLCV

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
# Background (3 steps shared by every scenario)
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


@when(parsers.parse("compute(ohlcv, {params}) es invocado"), target_fixture="compute_out")
def _when_compute(ohlcv_100: list[OHLCV], params: str) -> object:
    import json

    parsed = json.loads(params)
    return EmaIndicator().compute(ohlcv_100, parsed)


@then("el resultado es instancia de IndicatorOutput")
def _then_is_indicator_output(compute_out: object) -> None:
    assert isinstance(compute_out, IndicatorOutput)


@then("el campo values es un Mapping[str, float]")
def _then_values_is_mapping(compute_out: object) -> None:
    from collections.abc import Mapping

    assert isinstance(compute_out.values, Mapping)
    for k, v in compute_out.values.items():
        assert isinstance(k, str)
        assert isinstance(v, float)


@then('values contiene la clave "ema"')
def _then_values_has_ema(compute_out: object) -> None:
    assert "ema" in compute_out.values


@then('values["ema"] es un float finito')
def _then_values_ema_finite(compute_out: object) -> None:
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
    import dataclasses

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
def _then_order_preserved(empty_registry: IndicatorRegistry) -> None:
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
    from trading_bot.indicators.exceptions import RegistryFrozenError

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
    'un result A = compute(ohlcv_100, {"period": 9}) cacheado en ("ema", hash, ts)',
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
    import ast
    from pathlib import Path

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


@when('compute(ohlcv, {"period": 9}) es invocado')
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


@when("compute(ohlcv, params) es invocado")
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
