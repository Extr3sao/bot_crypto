"""Tests for market-data read quota (``trading_bot.market_data.quota``).

Cubre el contrato de ``quota.py``:

- ``Quota`` Protocol: ``check`` (sin efecto) y ``consume`` (atómico).
- ``FixedWindowQuota``: capacidad por ``provider_key``, consumo determinista
  (``clock_fn`` inyectable), agotamiento fail-closed con
  ``QuotaExhaustedError``, configuración inválida fail-fast.
- Sin bypass silencioso: ``consume`` nunca consume parcialmente y nunca
  devuelve éxito sin decremento.
- Concurrencia: el conteo es atómico bajo lock (``ThreadPoolExecutor``).

Sin red, sin sleeps reales: el reloj es inyectable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from trading_bot.market_data.quota import (
    FixedWindowQuota,
    QuotaConfigurationError,
    QuotaExhaustedError,
    QuotaState,
)


class FakeClock:
    """Reloj determinista inyectable (segundos monotónicos simulados)."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_quota_state_remaining_never_negative() -> None:
    state = QuotaState(provider_key="x", capacity=3, used=5)
    assert state.remaining == 0
    assert QuotaState(provider_key="x", capacity=3, used=1).remaining == 2


def test_check_has_no_side_effect() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=2, window_seconds=60, clock_fn=clock)
    quota.consume("binance:spot")
    before = quota.check("binance:spot")
    again = quota.check("binance:spot")
    assert before.used == 1 and again.used == 1
    assert before.remaining == 1


def test_consume_decrements_capacity() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=3, window_seconds=60, clock_fn=clock)
    s1 = quota.consume("binance:spot")
    s2 = quota.consume("binance:spot")
    assert (s1.used, s2.used) == (1, 2)
    assert s2.remaining == 1


def test_exhaustion_raises_quota_exhausted_fail_closed() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=2, window_seconds=60, clock_fn=clock)
    quota.consume("binance:spot")
    quota.consume("binance:spot")
    with pytest.raises(QuotaExhaustedError) as exc:
        quota.consume("binance:spot")
    # El estado NO cambió tras el rechazo (sin consumo parcial).
    assert quota.check("binance:spot").used == 2
    assert exc.value.provider_key == "binance:spot"
    assert exc.value.retry_after_seconds > 0


def test_multiple_requests_then_refuse_then_window_recovery() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=3, window_seconds=60, clock_fn=clock)
    for _ in range(3):
        quota.consume("binance:spot")
    with pytest.raises(QuotaExhaustedError):
        quota.consume("binance:spot")
    # Avanza el reloj más allá de la ventana: la capacidad se recupera.
    clock.advance(61)
    state = quota.consume("binance:spot")
    assert state.used == 1


def test_provider_keys_are_isolated() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=1, window_seconds=60, clock_fn=clock)
    quota.consume("binance:spot")
    # Otro provider tiene su propia capacidad.
    state = quota.consume("bybit:spot")
    assert state.used == 1
    with pytest.raises(QuotaExhaustedError):
        quota.consume("binance:spot")


def test_invalid_configuration_fails_fast() -> None:
    clock = FakeClock()
    with pytest.raises(QuotaConfigurationError):
        FixedWindowQuota(capacity=0, window_seconds=60, clock_fn=clock)
    with pytest.raises(QuotaConfigurationError):
        FixedWindowQuota(capacity=-1, window_seconds=60, clock_fn=clock)
    with pytest.raises(QuotaConfigurationError):
        FixedWindowQuota(capacity=5, window_seconds=0, clock_fn=clock)
    with pytest.raises(QuotaConfigurationError):
        FixedWindowQuota(capacity=5, window_seconds=-1, clock_fn=clock)
    with pytest.raises(QuotaConfigurationError):
        FixedWindowQuota(capacity=5, window_seconds=60, clock_fn=None)  # type: ignore[arg-type]


def test_invalid_cost_rejected() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=5, window_seconds=60, clock_fn=clock)
    with pytest.raises(QuotaConfigurationError):
        quota.consume("binance:spot", cost=0)
    with pytest.raises(QuotaConfigurationError):
        quota.consume("binance:spot", cost=-1)


def test_no_silent_bypass_on_partial_cost() -> None:
    """Cost mayor que la capacidad: rechazo completo, sin consumo parcial."""
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=2, window_seconds=60, clock_fn=clock)
    quota.consume("binance:spot")
    with pytest.raises(QuotaExhaustedError):
        quota.consume("binance:spot", cost=5)
    assert quota.check("binance:spot").used == 1


def test_determinism_same_clock_same_result() -> None:
    def run() -> list[int]:
        clock = FakeClock()
        quota = FixedWindowQuota(capacity=3, window_seconds=60, clock_fn=clock)
        used = []
        for _ in range(5):
            try:
                used.append(quota.consume("binance:spot").used)
            except QuotaExhaustedError:
                used.append(-1)
            clock.advance(1)
        return used

    assert run() == run() == [1, 2, 3, -1, -1]


def test_concurrent_consumption_is_atomic() -> None:
    """Sin condiciones de carrera: exactamente ``capacity`` consumes ganan."""
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=10, window_seconds=60, clock_fn=clock)
    ok, refused = [], []

    def worker() -> None:
        try:
            quota.consume("binance:spot")
            ok.append(1)
        except QuotaExhaustedError:
            refused.append(1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(50)))

    assert len(ok) == 10
    assert len(refused) == 40
    assert quota.check("binance:spot").used == 10


def test_retry_after_hint_is_window_bounded() -> None:
    clock = FakeClock()
    quota = FixedWindowQuota(capacity=1, window_seconds=60, clock_fn=clock)
    quota.consume("binance:spot")
    clock.advance(10)
    with pytest.raises(QuotaExhaustedError) as exc:
        quota.consume("binance:spot")
    # La vencida expira en 60-10=50s.
    assert 0 < exc.value.retry_after_seconds <= 60
