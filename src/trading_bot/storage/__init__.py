"""Capa de persistencia.

Fase objetivo: paraleliza con Fase 7.

Componentes:
- ``Database``: ``sqlite3`` directo en arranque; migrar a SQLAlchemy
  si se requiere async (ADR-0005).
- ``Schemas``: ``signals``, ``orders``, ``fills``, ``risk_decisions``.
- ``Repository``: API explícita por agregado.
"""
