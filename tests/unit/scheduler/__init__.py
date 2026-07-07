"""Paquete de tests para ``src/trading_bot/scheduler/``.

Convencion del repo (mismo patron que ``tests/unit/scanner/__init__.py``):
los tests replican la jerarquia de ``src/`` para que pytest
discovery funcione consistentemente y para que futuros ``ast`` parsers
(TSK-104.3b.5 cross-layer enforcement) puedan inferir el arbol
completo sin configuracion adicional.

Cualquier test especifico del scheduler entra en este paquete:
- ``test_types.py`` (TSK-104.1) — frozen dataclass + Literal + invariante.
- ``test_protocols.py`` (TSK-104.1) — Protocol estructural + runtime_checkable.
- ``test_cache.py`` (TSK-104.2) — cache predicate parametrizado.
- ``test_filters.py`` (TSK-104.2) — kill switch + active hours parametrizados.
- ``test_scheduler_skeleton.py`` (TSK-104.3a) — orquestador skeleton.
- ``test_reentrancy.py`` (TSK-104.3a) — guard contra reentrada.
- ``test_retry.py`` (TSK-104.3b) — retry/jitter + Retry-After.
- ``test_run_loop.py`` (TSK-104.3b) — CancelledError + graceful shutdown.
- ``test_connector_reinjector.py`` (TSK-104.3b) — mode-flip R1 opcion b.
- ``test_structlog_events.py`` (TSK-104.3b) — 7 eventos + single-emission point.
- ``test_cross_layer.py`` (TSK-104.3b) — integridad cross-layer via AST.
"""
