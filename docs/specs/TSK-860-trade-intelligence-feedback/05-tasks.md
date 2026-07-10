# TSK-860 - Trade Intelligence Feedback Loop: Tasks (Command 05)

> Desglose ejecutable para agentes. Cada tarea debe cerrar con tests o
> evidencia local.

---

## TSK-860.1 - Trade Journal core

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.1.1 | Crear package `trade_journal`. | `src/trading_bot/trade_journal/__init__.py` | Import smoke. |
| TSK-860.1.2 | Definir tipos `TradeCase`, `EntryThesis`, `TechnicalZone`, `ChartSnapshot`, `TradeOutcome`. | `types.py` | Tests frozen/slots/campos. |
| TSK-860.1.3 | Crear store SQLite con WAL. | `store.py` | Test migracion idempotente. |
| TSK-860.1.4 | CRUD de trade cases. | `store.py` | Crear/leer/actualizar. |
| TSK-860.1.5 | Tests de no-secret persistence. | `tests/unit/trade_journal/` | Falla si aparece api key/cookie/token. |

## TSK-860.2 - Market structure

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.2.1 | Crear `market_structure` package. | `src/trading_bot/market_structure/` | Import smoke. |
| TSK-860.2.2 | Detectar pivots soporte/resistencia. | `detector.py` | Serie sintetica con niveles esperados. |
| TSK-860.2.3 | Detectar techos/suelos. | `detector.py` | Max/min con lookback. |
| TSK-860.2.4 | Detectar order block basico. | `detector.py` | Impulso ATR mockeado. |
| TSK-860.2.5 | Detectar acumulacion/distribucion. | `detector.py` | Rango estrecho + volumen alto. |
| TSK-860.2.6 | Calcular distancia entrada-zona. | `detector.py` | Distancia bps/ATR. |

## TSK-860.3 - Entry thesis integration

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.3.1 | Crear builder de tesis. | `trade_journal/thesis.py` | Unit tests criterio met/failed. |
| TSK-860.3.2 | Integrar con flujo de orden paper. | execution/app layer | Orden lleva `trade_case_id`. |
| TSK-860.3.3 | Integrar con flujo futures live detras de flag. | app/execution layer | Smoke sin orden real usando fake client. |
| TSK-860.3.4 | Marcar `order_rejected` si falla exchange. | store + execution | Test error exchange. |

## TSK-860.4 - Chart snapshots

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.4.1 | Crear interfaz `ChartSnapshotProvider`. | `charting/snapshots.py` | Contract tests. |
| TSK-860.4.2 | Crear renderer local. | `charting/local_renderer.py` | PNG existe y no esta vacio. |
| TSK-860.4.3 | Crear provider TradingView detras de flag. | `charting/tradingview_provider.py` | Tests con mock/browser fake. |
| TSK-860.4.4 | Implementar timeout + defer. | `snapshots.py` | Test provider lento. |
| TSK-860.4.5 | Guardar overlays exactos. | store + charting | Snapshot metadata coincide con tesis. |

## TSK-860.5 - Post-trade feedback

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.5.1 | Crear evaluator. | `feedback/evaluator.py` | TP/SL/manual close. |
| TSK-860.5.2 | Calcular MFE/MAE/R. | `feedback/evaluator.py` | Series sinteticas. |
| TSK-860.5.3 | Etiquetar diagnostico. | `feedback/evaluator.py` | Tags esperados. |
| TSK-860.5.4 | Crear recomendaciones. | `feedback/recommendations.py` | No auto-aplica. |
| TSK-860.5.5 | Export JSON/CSV/Markdown. | `feedback/reports.py` | Snapshot de export. |

## TSK-860.6 - Frontend/API

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.6.1 | Endpoint listar casos. | backend server/app | Smoke HTTP. |
| TSK-860.6.2 | Endpoint detalle con snapshot. | backend server/app | Smoke HTTP. |
| TSK-860.6.3 | Panel Trade Journal. | frontend | Build verde. |
| TSK-860.6.4 | Filtros por tags/resultado/simbolo. | frontend | Test manual + screenshot. |
| TSK-860.6.5 | Export desde UI. | frontend/backend | CSV/JSON descargable. |

## TSK-860.7 - Governance and gates

| ID | Tarea | Archivos | Verificacion |
| --- | --- | --- | --- |
| TSK-860.7.1 | Crear BDD feature. | `bdd/features/trade_intelligence_feedback.feature` | pytest-bdd collect. |
| TSK-860.7.2 | ADR de TradingView/sesiones si aplica. | `tasks/decisions.md` | ADR firmada. |
| TSK-860.7.3 | Actualizar docs de riesgo. | `docs/risk-policy.md` | Risk review. |
| TSK-860.7.4 | Actualizar live checklist. | `docs/live-trading-checklist.md` | Checklist incluye journal/snapshots. |
| TSK-860.7.5 | Quality gates completos. | CI/local | ruff, mypy, pytest, BDD, security. |

## Definition of Done

- `TradeCase` creado antes de cada orden.
- Snapshot guardado o fallback registrado.
- Outcome generado tras cierre.
- Diagnostico post-trade con tags.
- Export consultable por agentes.
- Feedback no modifica live sin aprobacion.

## Estado local de implementacion

2026-07-09:

- Implementado `trade_journal` core: tipos, store SQLite WAL, CRUD de
  casos, tesis, snapshots y outcomes.
- Implementado detector inicial `market_structure`: pivots de
  soporte/resistencia, rango alto/bajo, order block basico,
  acumulacion/distribucion y distancia a zona.
- Implementado `EntryThesisBuilder` para convertir una senal en tesis
  con criterios cumplidos/fallidos, zonas, indicadores y confianza.
- Implementado fallback local `charting` que genera SVG con velas,
  entrada, TP, SL y zonas.
- Implementado `feedback.evaluator` con PnL neto, R multiple, MFE,
  MAE y tags de diagnostico.
- Conectado el flujo futures live: cada nueva entrada genera
  `TradeCase`, `EntryThesis`, snapshot SVG local, `order_id` y
  `position_id` cuando Bitunix lo devuelve.
- Conectada reconciliacion live: los casos abiertos se comparan contra
  posiciones reales; los casos obsoletos se cierran con outcome
  `position_direction_mismatch_on_reconcile` o
  `position_missing_on_reconcile`.
- Verificacion local: `pytest tests\unit\trade_journal
  tests\unit\market_structure tests\unit\charting tests\unit\feedback -q`
  + `tests\unit\test_app_trade_journal.py` -> 22 passed.
- Verificacion local: `ruff check` sobre los cuatro paquetes nuevos y
  tests asociados -> All checks passed.
- Verificacion live: `/health` devuelve `tradeCaseId` y
  `chartSnapshotPath` en `last_live_event` cuando abre futures; SQLite
  contiene casos `open/closed`, tesis, snapshots y outcomes.

Pendiente para cerrar TSK-860 completo:

- Integrar `trade_case_id` en el flujo spot/manual y paper.
- Crear provider TradingView detras de feature flag y ADR de sesion.
- Exponer API/frontend de Trade Journal.
- Crear BDD feature ejecutable.
- Ejecutar gates completos del repo.
