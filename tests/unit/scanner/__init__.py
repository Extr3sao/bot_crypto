"""Paquete de tests para ``src/trading_bot/scanner/``.

Convención del repo: los tests replican la jerarquía de ``src/``
para que pytest discovery funcione consistentemente y para que
futuros ``ast`` parsers (TSK-103.4 cross-layer enforcement) puedan
inferir el árbol completo sin configuración adicional.

Cualquier test específico del scanner entra en este paquete:
- ``test_types.py`` (TSK-103.1) — frozen dataclass + Literal.
- ``test_protocols.py`` (TSK-103.1) — Protocol estructural.
"""
