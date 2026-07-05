"""Tests unitarios para ``src/trading_bot/market_data/``.

Convención "tests-as-package":
- Cada subdirectorio ``tests/unit/<modulo>/`` espeja la jerarquía de
  ``src/trading_bot/<modulo>/`` para descubrimiento claro por pytest.
- ``pytest`` descubre automáticamente ``test_*.py`` bajo este paquete
  sin necesidad de imports relativos explícitos.

Anti-patrón evitado (ref ``docs/architecture.md`` §14, regla 1):
- Sin lógica de side-effects al importar. Este ``__init__.py`` SOLO
  contiene docstring; cualquier helper global de tests debe ir bajo
  ``tests/unit/market_data/conftest.py``.
"""
