# RFC-TAP-MARKET-005 — Continuous Market Intelligence & Incremental Data Orchestration

**Estado:** IMPLEMENTED OFFLINE (WP-005A…G) · host activation DEFERRED (WP-005H)
**Fecha:** 2026-10-18 · **Base:** `fe9b5e2623b0d023833249e9687b753eaacd27d4`
**Rama:** `agent/market/RFC-TAP-MARKET-005`
**Relación:** continúa RFC-TAP-AI-BOTS-003 (PIT, provider, prospective) y RFC-TAP-AI-BOTS-004 (crítico shadow).

## Decisión

1. **No se apaga ninguna descarga.** Ninguna resultó redundante sin sustituto demostrado.
2. **La recarga 1000/500/500 se sustituye, no se elimina**, por un lector incremental con watermark, overlap de reparación y cobertura probada. Medido: −88,3 % peticiones, −98,9 % velas, 12/12 ventanas idénticas.
3. **La IA se dispara por evento cerrado**, nunca por tick ni por tick de scheduler. Con credencial ausente o presupuesto 0 el resultado es `MISSING_CREDENTIAL` / `BUDGET_EXHAUSTED` y **cero** llamadas.
4. **El host no se toca en este RFC.** Re-registrar las cinco tareas de consola es WP-005H y requiere autorización; el repositorio ya contiene el lanzador `windowless.py`.

## Contratos introducidos

- `Watermark(source, symbol, timeframe) -> last_verified_open_ms, last_closed_boundary_ms, seq, sha` con checksum propio y escritura atómica.
- `IngestResult` con `status`, `requests_made`, `rows_final/incomplete/rejected`, `expected/observed`, `gap_open_ms`, watermarks antes/después.
- `MarketSnapshot` con `available_at_ms`, `content_hash`, huecos por timeframe y `executable_price(at)`.
- `TriggerDecision` con `reason` (`TRIGGERED`, `NO_NEW_DATA`, `DUPLICATE_EVENT`, `COOLDOWN`, `HOURLY_CAP`, `MISSING_CREDENTIAL`, `BUDGET_EXHAUSTED`, `STALE_SNAPSHOT`, `NO_EXECUTABLE_PRICE`, `NO_MATERIAL_CHANGE`).
- `CachedResponse` ligada a `snapshot_hash + prompt_version + model_version` con TTL.

## Invariantes

```
bar.open < bar.close_boundary <= available_at_ms <= decision_ms
         <= model_request <= model_response <= executable_quote <= paper_fill
```

- Sólo se persisten velas cerradas.
- El watermark nunca cruza `closed_boundary`.
- Un hueco se reporta, no se rellena.
- Una ventana que no cubre lo pedido es `INSUFFICIENT_WINDOW` y no avanza el watermark.
- Un backlog mayor que una petición es `BACKLOG_EXCEEDS_WINDOW`; `reconcile` es explícito.
- El provider no expone `since`: el delta es *últimas N acotadas + deduplicación*, y la cobertura se prueba con `min(ts) <= first_needed`.

## Fuera de alcance

- Live trading, capital, apalancamiento, cambios de riesgo o de admisión.
- Crear, borrar, deshabilitar o re-registrar tareas del host.
- Sustituir `OHLCVStore` (sólo se añade una vista con dimensión de timeframe).
- Promocionar `forward_collector` (WebSocket, DISCOVERY PLANE) al circuito de decisión.
- Migrar `ST6` y `ALPHA002` al lector compartido.

## Evidencia

`reports/market-data/RFC-TAP-MARKET-005/` — inventario de scheduler, traza de atribución, comparación CURRENT vs PROPOSED, ledger de cobertura, ledger de triggers, verificación independiente (8/8 checks, 5/5 mutaciones), run report y final report.
