"""Tests unitarios para ``CCXTExchangeConnector``.

Estrategia: parchear ``ccxt.<exchange>`` al nivel de ``ccxt`` namespace
para devolver una ``MagicMock`` configurable. Determinístico, sin red.

Los fixtures JSON live en ``fixtures/`` bajo este mismo directorio:
  - ``binance_ohlcv.json``: array of candles.

El cliente CCXT real NO se ejecuta — está completamente aislado por el
patch a nivel de módulo.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import ccxt
import pytest

from trading_bot.config.exchange import (
    Exchange,
    ExchangeRetries,
    ExchangeTimeouts,
)
from trading_bot.market_data.exchange_connector import (
    CCXTExchangeConnector,
    MULTI_EXCHANGE_SCOPE,
    SUPPORTED_EXCHANGES_FOR_TSK_101,
    ExchangeConnector,
    UnmappedOrderStatusError,
    _KNOWN_STATUS_MAP,
)
from trading_bot.market_data.types import OrderStatus
from typing import get_args  # noqa: I001  (kept near first Literal usage for clarity)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def exchange_cfg() -> Exchange:
    return Exchange(
        id="binance",
        sandbox=True,
        account_type="spot",
        rate_limit_ms=250,
        options={"defaultType": "spot"},
        timeouts=ExchangeTimeouts(request_ms=15000, recv_window_ms=5000),
        retries=ExchangeRetries(
            max_attempts=5, initial_backoff_ms=500, max_backoff_ms=8000
        ),
        default_type="spot",
        time_in_force_default="GTC",
        post_only_default=True,
    )


@pytest.fixture
def mocked_connector(
    monkeypatch: pytest.MonkeyPatch, exchange_cfg: Exchange
) -> tuple[CCXTExchangeConnector, MagicMock]:
    """Parchea ``ccxt.binance`` y devuelve (connector, ccxt_instance_mock)."""
    instance = MagicMock(spec=ccxt.Exchange)
    monkeypatch.setattr(ccxt, "binance", lambda *args: instance)
    connector = CCXTExchangeConnector(exchange_cfg)
    return connector, instance


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_connector_is_exchange_connector(mocked_connector: tuple[CCXTExchangeConnector, MagicMock]) -> None:
    connector, _ = mocked_connector
    assert isinstance(connector, ExchangeConnector)


def test_sandbox_mode_enabled_at_init(mocked_connector: tuple[CCXTExchangeConnector, MagicMock]) -> None:
    connector, instance = mocked_connector
    instance.set_sandbox_mode.assert_called_once_with(True)
    assert connector.sandbox_enabled is True


def test_rate_limit_and_timeout_propagated(mocked_connector: tuple[CCXTExchangeConnector, MagicMock]) -> None:
    _, instance = mocked_connector
    assert instance.rateLimit == 250
    assert instance.timeout == 15000


def test_load_markets_calls_ccxt(mocked_connector: tuple[CCXTExchangeConnector, MagicMock]) -> None:
    _, instance = mocked_connector
    connector, _ = mocked_connector
    connector.load_markets()
    instance.load_markets.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_ohlcv
# ---------------------------------------------------------------------------
def test_fetch_ohlcv_maps_to_ohlcv_dataclass(mocked_connector: tuple[CCXTExchangeConnector, MagicMock]) -> None:
    connector, instance = mocked_connector
    instance.fetch_ohlcv.return_value = [
        [1672531200000, 16500.0, 16600.0, 16400.0, 16550.0, 100.5],
        [1672534800000, 16550.0, 16650.0, 16510.0, 16620.0, 120.3],
    ]
    rows = connector.fetch_ohlcv("BTC/USDT", "1h", 2)
    assert len(rows) == 2
    assert rows[0].timestamp == 1672531200000
    assert rows[0].close == 16550.0
    assert rows[1].volume == 120.3
    # P1 round-2 (TSK-102): el connector inyecta ``symbol=symbol`` para
    # que el store pueda persistir la PK compuesta ``(symbol, timestamp)``.
    # Sin esto, el dataclass OHLCV y la tabla SQL estan desincronizados
    # (TSK-102 P1).
    assert rows[0].symbol == "BTC/USDT"
    assert rows[1].symbol == "BTC/USDT"
    instance.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1h", limit=2)


# ---------------------------------------------------------------------------
# create_order: idempotencia y retries
# ---------------------------------------------------------------------------
def test_create_order_uses_caller_supplied_client_order_id_reused_on_retry(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    connector, instance = mocked_connector
    instance.create_order.side_effect = [
        ccxt.NetworkError("transient 1"),
        ccxt.NetworkError("transient 2"),
        {
            "id": "EX-1234",
            "symbol": "BTC/USDT",
            "status": "open",
            "side": "buy",
            "type": "limit",
            "price": 16000.0,
            "amount": 0.5,
            "filled": 0.0,
        },
    ]

    result = connector.create_order(
        "BTC/USDT", "buy", "limit", 0.5, 16000.0, client_order_id="MY-DETERMINISTIC-ID"
    )

    assert result.id == "EX-1234"
    assert result.client_order_id == "MY-DETERMINISTIC-ID"
    assert result.side == "buy"
    assert result.type == "limit"
    assert instance.create_order.call_count == 3

    # Pinea idempotencia: el MISMO client_order_id en CADA intento.
    call_kwargs = [c.kwargs for c in instance.create_order.call_args_list]
    assert all(kw["params"]["clientOrderId"] == "MY-DETERMINISTIC-ID" for kw in call_kwargs)


def test_create_order_generates_uuid_when_caller_omits(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    connector, instance = mocked_connector
    instance.create_order.return_value = {
        "id": "EX-9",
        "symbol": "ETH/USDT",
        "status": "closed",
        "side": "sell",
        "type": "market",
        "price": 1200.0,
        "amount": 1.0,
        "filled": 1.0,
    }

    result = connector.create_order("ETH/USDT", "sell", "market", 1.0)
    # client_order_id fue generado, presente en result y en params.
    assert result.client_order_id != ""
    call_kwargs = instance.create_order.call_args.kwargs
    assert call_kwargs["params"]["clientOrderId"] == result.client_order_id


def test_create_order_does_not_retry_on_invalid_order(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    connector, instance = mocked_connector
    instance.create_order.side_effect = ccxt.InvalidOrder("Insufficient funds")

    with pytest.raises(ccxt.InvalidOrder):
        connector.create_order("BTC/USDT", "buy", "market", 100)

    # fail-fast: 1 sola llamada pese a retries.max_attempts=5.
    assert instance.create_order.call_count == 1


def test_create_order_retries_then_succeeds_on_rate_limit(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    connector, instance = mocked_connector
    instance.create_order.side_effect = [
        ccxt.RateLimitExceeded("slow down"),
        ccxt.RateLimitExceeded("still slow"),
        {
            "id": "EX-RL",
            "symbol": "BTC/USDT",
            "status": "open",
            "side": "buy",
            "type": "limit",
            "price": 16000.0,
            "amount": 0.1,
            "filled": 0.0,
        },
    ]
    result = connector.create_order("BTC/USDT", "buy", "limit", 0.1, 16000.0, "cid-rl")
    assert result.id == "EX-RL"
    assert instance.create_order.call_count == 3


def test_create_order_with_partial_fill_does_not_raise(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    """REGRESSION crítica (P1 — entry 2026-07-04 02:00).

    Una orden EXITOSA con partial fill NO debe elevar
    UnmappedOrderStatusError: si la respuesta del exchange dice
    ``partially_filled``, el caller debe recibir ``OrderResult`` con
    ``status='partially_filled'`` y NO excepción, porque en otro caso
    podría reintentar y duplicar la posición en vivo.
    """
    connector, instance = mocked_connector
    instance.create_order.return_value = {
        "id": "EX-PARTIAL",
        "symbol": "BTC/USDT",
        "status": "partially_filled",
        "side": "buy",
        "type": "limit",
        "price": 16000.0,
        "amount": 1.0,
        "filled": 0.4,
    }
    result = connector.create_order(
        "BTC/USDT", "buy", "limit", 1.0, 16000.0, client_order_id="cid-partial"
    )
    assert result.id == "EX-PARTIAL"
    assert result.status == "partially_filled"
    assert result.filled == 0.4
    assert result.amount == 1.0


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------
def test_cancel_order_retries_on_network_error(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    connector, instance = mocked_connector
    instance.cancel_order.side_effect = [
        ccxt.NetworkError("blip"),
        None,  # éxito
    ]
    connector.cancel_order("EX-1", "BTC/USDT")
    assert instance.cancel_order.call_count == 2


# ---------------------------------------------------------------------------
# fetch_balance
# ---------------------------------------------------------------------------
def test_fetch_balance_maps_to_balance_dataclass(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    connector, instance = mocked_connector
    instance.fetch_balance.return_value = {
        "BTC": {"free": 0.5, "used": 0.1, "total": 0.6},
        "USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0},
        "info": {"ignored": "internal ccxt metadata"},
    }
    balances = connector.fetch_balance()
    by_asset = {b.asset: b for b in balances}
    assert by_asset["BTC"].total == 0.6
    assert by_asset["USDT"].free == 1000.0
    # `info` no es asset → filtrado.
    assert "info" not in by_asset


# ---------------------------------------------------------------------------
# _normalize_status exhaustiveness (TSK-101 reviewer fix + ADR lock)
# ---------------------------------------------------------------------------
def test_normalize_status_known_statuses() -> None:
    """Direct mapping: cada key conocida produce el valor esperado del Literal."""
    assert CCXTExchangeConnector._normalize_status("open") == "open"
    assert CCXTExchangeConnector._normalize_status("partially_filled") == "partially_filled"
    assert CCXTExchangeConnector._normalize_status("closed") == "closed"
    assert CCXTExchangeConnector._normalize_status("canceled") == "canceled"
    assert CCXTExchangeConnector._normalize_status("rejected") == "rejected"
    assert CCXTExchangeConnector._normalize_status("expired") == "expired"


def test_normalize_status_case_insensitive_and_synonyms() -> None:
    """ccxt canonicaliza lower, pero toleramos variaciones ruidosas."""
    assert CCXTExchangeConnector._normalize_status("OPEN") == "open"
    assert CCXTExchangeConnector._normalize_status("PARTIALLY_FILLED") == "partially_filled"
    assert CCXTExchangeConnector._normalize_status("FILLED") == "closed"
    assert CCXTExchangeConnector._normalize_status("cancelled") == "canceled"  # US/UK
    assert CCXTExchangeConnector._normalize_status("new") == "open"  # Binance alias


@pytest.mark.parametrize(
    "bad", [None, "", "    ", "unknown_xyz", "pending", "partial-canceled", "partial_fill"]
)
def test_normalize_status_invalid_inputs_raise(bad: str | None) -> None:
    """None, vacío, whitespace-only y status no contemplado rompen loud.

    NOTA round-7: ``partial_fill`` vuelve a estar aquí — el code-reviewer
    round-6 identificó que el alias defensivo era código muerto (CCXT v4
    canonicaliza via ``unify_order_status``); si un adapter buggy emite
    ``partial_fill``, debe romper loud per ADR lock convention.
    """
    with pytest.raises(UnmappedOrderStatusError):
        CCXTExchangeConnector._normalize_status(bad)


def test_normalize_status_partially_filled() -> None:
    """REGRESSION P1: status de ejecución parcial debe mapearse, NO raise.

    Sin esto, una orden EXITOSA con partial fill se eleva como
    excepción post-POST y el caller puede reintentar y duplicar la
    posición en el exchange (riesgo de dinero real).
    """
    assert CCXTExchangeConnector._normalize_status("partially_filled") == "partially_filled"
    assert CCXTExchangeConnector._normalize_status("PARTIALLY_FILLED") == "partially_filled"


def test_known_status_map_covers_all_order_status_literal_values() -> None:
    """ADR lock bidireccional:
    - Cada valor de OrderStatus Literal debe ser alcanzable via _KNOWN_STATUS_MAP.
    - Cada valor en el map debe ser un Literal válido (sin extras obsoletos).

    Si añades un valor a OrderStatus y olvidas mapearlo, o si añades un
    mapeo a un Literal obsoleto, este test FALLA antes de mergear.
    """
    expected = set(get_args(OrderStatus))
    actual = set(_KNOWN_STATUS_MAP.values())
    missing_letters = expected - actual
    stale_mappings = actual - expected
    assert not missing_letters, (
        f"_KNOWN_STATUS_MAP missing values for: {sorted(missing_letters)}"
    )
    assert not stale_mappings, (
        f"_KNOWN_STATUS_MAP has stray mappings to deprecated Literals: "
        f"{sorted(stale_mappings)}"
    )


def test_logger_attribution_uses_module_name(
    mocked_connector: tuple[CCXTExchangeConnector, MagicMock],
) -> None:
    """Verifica que el connector exponga `_log_name` atributable a su módulo.

    Importante: NO inspeccionar ``self._log.__class__.__module__`` porque
    structlog devuelve un wrapper (``BoundLogger``) cuyo ``__class__``
    vive en ``structlog.types`` o ``structlog._config`` — no en el
    módulo del connector. La atribuibilidad correcta se valida con el
    atributo explícito ``_log_name``.
    """
    connector, _ = mocked_connector
    # `.endswith()` en vez de equality estricta: tolera refactors del
    # package layout sin perder validación de atribuibilidad del módulo.
    assert connector._log_name.endswith(".market_data.exchange_connector")


# ---------------------------------------------------------------------------
# P2 — Soporte de exchanges whitelist (TSK-101 = solo Binance sandbox-tested)
# ---------------------------------------------------------------------------
def test_supported_exchanges_contains_only_binance_at_tsk_101() -> None:
    """Pinea el alcance actual: TSK-101 sólo cubre Binance. Cualquier
    ampliación (Coinbase, Bybit, OKX, Kraken...) requiere un ticket
    dedicado con sandbox testing — ver ``MULTI_EXCHANGE_SCOPE``."""
    assert SUPPORTED_EXCHANGES_FOR_TSK_101 == frozenset({"binance"})


def test_multi_exchange_scope_string_is_self_descriptive() -> None:
    """El scope multi-exchange NO depende del ID literal TSK-105: si el
    ticket se reabre bajo otro ID, el mensaje sigue dando una pista
    semántica útil al caller (resiliencia ante renumeraciones)."""
    assert "multi-exchange" in MULTI_EXCHANGE_SCOPE.lower()
    assert "verification" in MULTI_EXCHANGE_SCOPE.lower()


@pytest.mark.parametrize(
    "bad_id, expected_msg",
    [
        # Caso 1: rechazo genérico + nombre del TSK actual.
        ("coinbase", "no está cubierto por TSK-101"),
        # Caso 2: referencia al scope multi-exchange (no al ticket ID).
        ("okx", MULTI_EXCHANGE_SCOPE),
    ],
)
def test_unsupported_exchange_rejected_at_init(
    exchange_cfg: Exchange, bad_id: str, expected_msg: str
) -> None:
    """P2 (entry 2026-07-04 02:00): un exchange NO presente en el
    whitelist debe fallar en ``__init__`` ANTES de cualquier
    ``getattr(ccxt, ...)``. El mensaje incluye tanto la razón del
    rechazo como la referencia al scope donde se ampliará soporte.

    Si este chequeo se moviera DESPUÉS del getattr, el test necesitaría
    parchear ``ccxt.coinbase``/``ccxt.okx`` (necesario en futuros PRs
    multi-exchange).
    """
    bad = exchange_cfg.model_copy(update={"id": bad_id})
    with pytest.raises(ValueError, match=expected_msg):
        CCXTExchangeConnector(bad)


# ---------------------------------------------------------------------------
# Smoke tests (cierre cobertura 89.x% -> 90%+ via pytest --cov).
#
# Cubre los except blocks + log.error + reraise de los metodos read
# que NO estaban previamente pineados y son criticos para TSK-104+
# scheduler: una regresion que silencie el error (try/except ``pass``
# accidental) seria invisible hasta que el scheduler vea slots de retry
# colgados sin causa.
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_retry_exchange_cfg() -> Exchange:
    """Variante de ``exchange_cfg`` con retries agresivos para smoke
    tests de error-path.

    El conector normal usa ``max_attempts=5`` y 0.5-8s de backoff
    exponencial con jitter; para verificar que la excepcion se
    reraisa (en lugar de quedar atrapada en un loop de retry que
    tarde segundos), necesitamos ``max_attempts=2`` + backoff minimo.
    Los tests que SI prueban happy-path con retries reales usan
    ``exchange_cfg``.

    Notes TSK-013.9 (latent fixture invalidity discovered en route):

    + ``rate_limit_ms`` usa 50 (no 10) porque el modelo ``Exchange``
      en ``src/trading_bot/config/exchange.py:45`` exige ``ge=50``.
      En este fixture ambos valores son metadata que el connector
      pasa al ``ccxt.Exchange`` mock; el connector NO llama a CCXT
      real, asi que 50ms vs 10ms no impacta wall-clock.

    + ``max_backoff_ms`` usa 200 (no 50, ni 100) porque:

      1. El modelo ``ExchangeRetries`` exige ``ge=100`` — 50 rompe
         loud en pytest SETUP con ``ValidationError``.
      2. 100 seria el MINIMO valido pero sits exactly on the
         constraint boundary: cualquier tightening futuro (e.g. a
         ``ge=200`` para escenarios invariants mas estrictos) rompe
         este fixture silenciosamente. 200 deja 100ms de headroom.
      3. Worst-case total wall-clock del retry sigue siendo ~200ms
         (max_attempts=2), despreciable para la duracion del test.

      Bajar el param exige tocar los constraints del modelo (scope
      src/, fuera de este ticket test-only).
    """
    return Exchange(
        id="binance",
        sandbox=True,
        account_type="spot",
        rate_limit_ms=50,
        options={"defaultType": "spot"},
        timeouts=ExchangeTimeouts(request_ms=1000, recv_window_ms=500),
        retries=ExchangeRetries(
            max_attempts=2, initial_backoff_ms=10, max_backoff_ms=200
        ),
        default_type="spot",
        time_in_force_default="GTC",
        post_only_default=True,
    )


@pytest.mark.parametrize(
    "method_name, method_args",
    [
        ("fetch_ohlcv", ("BTC/USDT", "1h", 5)),
        ("fetch_balance", ()),
    ],
)
def test_read_methods_retries_then_reraise(
    monkeypatch: pytest.MonkeyPatch,
    fast_retry_exchange_cfg: Exchange,
    method_name: str,
    method_args: tuple,
) -> None:
    """Smoke (coverage gate): ``fetch_ohlcv`` y ``fetch_balance``
    reintentan hasta ``max_attempts`` y propagan el error original sin
    swap.

    Cubre:
      - except block de ``fetch_ohlcv`` (log.error + reraise).
      - except block de ``fetch_balance`` (log.error + reraise).
      - ``reraise=True`` del decorator tenacity tras agotar
        ``max_attempts`` (no swallow).

    El parametrize explicito (``method_name, method_args``) con ``getattr``
    elimina el if/else interno y deja pytest reportar cada caso por
    separado. Tras el rename del param name ``args`` a ``method_args``
    (TSK-013.9), pytest genera ids descriptivos:
      - ``test_read_methods...reraise[fetch_ohlcv-method_args0]``
      - ``test_read_methods...reraise[fetch_balance-method_args1]``
    Anadir un tercer read method futuro (e.g. ``fetch_ticker``)
    requiere extender SOLO el parametrize; si se olvida, pytest emite
    un parametrize id faltante en el reporte, NO un branch silencioso.
    """
    instance = MagicMock(spec=ccxt.Exchange)
    instance.fetch_ohlcv.side_effect = ccxt.NetworkError("simulated outage")
    instance.fetch_balance.side_effect = ccxt.NetworkError("simulated outage")
    # TSK-013.9 fix: ``args`` colisionaba con pytest fixtures/builtin
    # ``args``. ``method_args`` es descriptivo + evita la colision. La
    # lambda ``lambda *factory_args`` mantiene su propio scope local
    # (factory args de ``ccxt.binance(...)`` factory call) — son
    # variables distintas en Python por ser argumentos, no nombres.
    monkeypatch.setattr(ccxt, "binance", lambda *_factory_args: instance)
    connector = CCXTExchangeConnector(fast_retry_exchange_cfg)

    method = getattr(connector, method_name)
    with pytest.raises(ccxt.NetworkError, match="simulated outage"):
        method(*method_args)
    # max_attempts=2 -> 2 intentos antes del reraise=True.
    assert getattr(instance, method_name).call_count == 2


def test_load_markets_logs_and_reraises_on_failure(
    monkeypatch: pytest.MonkeyPatch, exchange_cfg: Exchange
) -> None:
    """Smoke (coverage gate): ``load_markets`` falla sin retry y reraisa
    el original tras ``log.error(load_markets_failed)``.

    A diferencia de los read methods, ``load_markets`` NO reintenta
    por diseno: un fallo aqui suele ser auth invalida o region
    bloqueada, y un retry enmascararia el problema y dejaria al bot
    operando contra URLs cacheadas de produccion. Pinear fail-fast.
    """
    instance = MagicMock(spec=ccxt.Exchange)
    instance.load_markets.side_effect = ccxt.NetworkError("simulated outage")
    monkeypatch.setattr(ccxt, "binance", lambda *args: instance)
    connector = CCXTExchangeConnector(exchange_cfg)
    with pytest.raises(ccxt.NetworkError, match="simulated outage"):
        connector.load_markets()
    # load_markets sin retry: 1 sola llamada pese a retries.max_attempts=5.
    assert instance.load_markets.call_count == 1
