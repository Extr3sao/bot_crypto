"""Capa de persistencia (TSK-102 + TSK-100 roadmap).

TSK-102 (este paquete, scope actual):
- ``OHLCVStore``: SQLite crudo con ``PRAGMA user_version`` v1.
  Soporta URL ``sqlite:///<path>`` (relativo) y ``sqlite:////<path>``
  (absoluto). Upsert ``INSERT ... ON CONFLICT DO UPDATE`` last-write-wins.
  Sin dependencias externas (stdlib only). WAL habilitado para
  concurrencia futura.

TSK-100 (futuro, Pri 8 sprint-002):
- Migracion a SQLAlchemy core + Alembic.
- Nuevas tablas: ``signals``, ``orders``, ``fills``, ``risk_decisions``
  (per ADR-0005 firmado en sprint-001).
- TSK-102 NO introduce SQLAlchemy para mantener scope narrow y no anadir
  deps antes de tiempo. TSK-100 absorbera OHLCVStore + nuevas tablas
  bajo el ORM.
"""

from trading_bot.storage.ohlcv_store import (
    CURRENT_SCHEMA_VERSION,
    OHLCVStore,
)

__all__ = ["CURRENT_SCHEMA_VERSION", "OHLCVStore"]
