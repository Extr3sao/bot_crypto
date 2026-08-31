"""Quota de lecture market-data (capacity/rate) — contrat explicite.

Limite le nombre d'appels de lecture (``fetch_ohlcv``, ``fetch_balance``,
``fetch_ticker``, ...) qu'un connecteur peut effectuer par fenêtre. Le but est
de protéger les quota API des providers sans introduire de sleep caché : quand
la capacité est épuisée, l'appel suivant échoue immédiatement avec
``QuotaExhaustedError`` (fail-closed) — c'est à l'appelant (scheduler,
backoff existant de tenacity) de décider quand réessayer.

Contrat:

- ``Quota`` (Protocol): ``check(provider_key) -> QuotaState`` (lecture sans
  effet) et ``consume(provider_key, cost=1) -> QuotaState`` (décrémente de
  façon atomique; lève ``QuotaExhaustedError`` si la capacité restante est
  insuffisante — jamais de consommation partielle ni de bypass silencieux).
- ``FixedWindowQuota``: implémentation par défaut, déterministe, fenêtre
  glissante par ticks d'horloge injectable (``clock_fn``) pour les tests.
  Un ``provider_key`` (par ex. ``"binance:spot"``) a sa propre capacité.
- ``capacity <= 0`` ou ``window_seconds <= 0`` lève ``QuotaConfigurationError``
  à la construction (fail-fast).
- Aucun sleep, aucun threading interne: le décompte est atomique sous lock,
  et le refus est immédiat.

Frontera: la quota ne concerne que les lectures market-data. Elle n'est pas
câblée dans ``create_order``/``cancel_order`` (écritures d'exécution) et ne
modifie ni ExecutionGateway ni la gouvernance risk/live.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class QuotaError(Exception):
    """Erreur de base quota."""


class QuotaConfigurationError(QuotaError):
    """Configuration de quota invalide (capacity/window <= 0, etc.)."""


class QuotaExhaustedError(QuotaError):
    """Capacité de lecture épuisée pour la fenêtre courante (fail-closed)."""

    def __init__(self, provider_key: str, retry_after_seconds: float) -> None:
        self.provider_key = provider_key
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"quota épuisée pour {provider_key!r}; "
            f"réessai possible dans ~{retry_after_seconds:.0f}s"
        )


@dataclass(frozen=True, slots=True)
class QuotaState:
    """Instantané immuable de l'état d'une quota."""

    provider_key: str
    capacity: int
    used: int

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.used)


class Quota(Protocol):
    """Contrat de capacité de lecture market-data."""

    def check(self, provider_key: str) -> QuotaState:
        """État courant sans effet de bord."""
        ...

    def consume(self, provider_key: str, cost: int = 1) -> QuotaState:
        """Décrémente atomiquement; lève QuotaExhaustedError si insuffisant."""
        ...


class FixedWindowQuota:
    """Quota à fenêtre glissante par provider, déterministe et atomique.

    ``window_seconds`` définit la fenêtre: chaque consommation est horodatée
    via ``clock_fn`` (injectable pour les tests); les consommations plus
    vieilles que la fenêtre sont évictées au calcul de capacité restante.
    """

    def __init__(
        self,
        *,
        capacity: int,
        window_seconds: float,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise QuotaConfigurationError(f"capacity doit être > 0, got {capacity}")
        if window_seconds <= 0:
            raise QuotaConfigurationError(f"window_seconds doit être > 0, got {window_seconds}")
        if not callable(clock_fn):
            raise QuotaConfigurationError("clock_fn doit être callable")
        self._capacity = capacity
        self._window_seconds = float(window_seconds)
        self._clock_fn = clock_fn
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _evict(self, events: deque[float], now: float) -> None:
        horizon = now - self._window_seconds
        while events and events[0] <= horizon:
            events.popleft()

    def check(self, provider_key: str) -> QuotaState:
        with self._lock:
            events = self._events[provider_key]
            self._evict(events, self._clock_fn())
            return QuotaState(
                provider_key=provider_key,
                capacity=self._capacity,
                used=len(events),
            )

    def consume(self, provider_key: str, cost: int = 1) -> QuotaState:
        if cost <= 0:
            raise QuotaConfigurationError(f"cost doit être > 0, got {cost}")
        with self._lock:
            events = self._events[provider_key]
            now = self._clock_fn()
            self._evict(events, now)
            if len(events) + cost > self._capacity:
                oldest = events[0] if events else now
                retry_after = max(0.0, oldest + self._window_seconds - now)
                raise QuotaExhaustedError(provider_key, retry_after)
            for _ in range(cost):
                events.append(now)
            return QuotaState(
                provider_key=provider_key,
                capacity=self._capacity,
                used=len(events),
            )


__all__ = [
    "FixedWindowQuota",
    "Quota",
    "QuotaConfigurationError",
    "QuotaError",
    "QuotaExhaustedError",
    "QuotaState",
]
