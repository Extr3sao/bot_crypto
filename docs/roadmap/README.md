# Trading Agentic Portable — Roadmap maestro

**Fecha de corte:** 2026-10-18 · **Versión actual:** 1.4 · **Estado:** inventario de gestión, NO certificado de producción.

Este directorio conserva el seguimiento de Trading Agentic Portable en formato Excel y un espejo de datos fácilmente revisable en Git. La autoridad de cada estado viene de los commits y evidencias de las ramas, **no** de la existencia del RFC.

## Archivos

- `ROADMAP_TRADING_AGENTIC_PORTABLE.xlsx`: Excel maestro con 9 hojas (RESUMEN, ROADMAP, FASES, RFC_Y_WP, BLOQUEOS, DEPENDENCIAS, EVIDENCIAS, HISTORIAL, COMO_ACTUALIZAR), 71 tareas con ID estable, filtros, prioridades y visualizaciones.
- `ROADMAP_MASTER_DATA.json`: snapshot estructurado de fuentes/estados para actualizaciones y futuros automatismos.
- `ROADMAP_MASTER.csv`: vista de las 71 tareas para diff, búsquedas y herramientas simples.

## Regla para actualizar

1. Revisar el **runtime Git real**, fecha, rama, SHA, evidencia de ejecución y verificador independiente de cada WP.
2. Conservar el ID `TAP-xxx`; actualizar estado, porcentaje **de ejecución** (no de rentabilidad), dependencias, bloqueo, siguiente acción y URL de evidencia. No borrar historia.
3. Actualizar simultáneamente JSON/CSV, Excel (panel y demás hojas), y el `HISTORIAL`; publicar los tres en el mismo commit. No editar solo una proyección.
4. Cuando un reporte da PASS focal, dejar `VERIFICADO_FOCAL`; NO convertirlo en `CERTIFIED` ni `PRODUCTION_READY`. Si falla la suite global, mantener bloqueo.
5. Para que la actualización sea autónoma, pegar el resultado nuevo de Codex en el proyecto de ChatGPT o ejecutar la integración autorizada. **El archivo no se refresca solo sin una ejecución/solicitud.**
6. En GitHub, preferir PR y actualizaciones fast-forward de la rama `project/roadmap-trading-agentic`; no hacer push a ramas en uso por otros agentes.

## Estado destacado del corte inicial

- AI-BOTS-003A/B/C: implementación/validación focal; rama `agent/ai-bots/RFC-TAP-AI-BOTS-003` HEAD `eeb0bea`. Bloque C: 459 tests focalizados publicados, 120 checks y 53 mutaciones detectadas en 5 escenarios, `REAL_MODEL_CALLED=false`.
- EVIDENCE-004F: 42 checks y 18 mutaciones reportados, **no** CI global.
- EDGE-017F: 1× neto `−238.770489 USDT` histórico determinista; suite global `4070 PASS / 14 FAIL`. No hay estrategia admitida.
- RFC-AI-BOTS-004: BOT-CRI-01 / TradingAgents audit REA **solo propuesto**, issue #14. No se ha ejecutado REA sobre ese upstream ni se ha implantado el crítico.
- Objetivo ACTIVE de ≥3 fills/día (7/7) sigue **no demostrado**, y `weekend_trading=false` no se modifica sin autorización.

**Gobernanza:** `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`, `TEST_TARGET == RUNTIME_TARGET`, `NO_TRADE` es decisión de primera clase. No hacer live trading, gastos API, cambios de riesgo o uso de secretos sin permiso.

Issues principales: [#10](https://github.com/Extr3sao/bot_crypto/issues/10) · [#11](https://github.com/Extr3sao/bot_crypto/issues/11) · [#12](https://github.com/Extr3sao/bot_crypto/issues/12) · [#13](https://github.com/Extr3sao/bot_crypto/issues/13) · [#14](https://github.com/Extr3sao/bot_crypto/issues/14) · [#16](https://github.com/Extr3sao/bot_crypto/issues/16).

## Publicación

- La revisión v1.1 actualiza la fila `TAP-057` tras comprobar la primera subida a GitHub.
- La rama `project/roadmap-trading-agentic` conserva los archivos Excel, JSON, CSV y README; la integración a `main` requiere PR.

## Revisión v1.2 — 2026-10-18

- AI-BOTS-003C remota `0841d37`: nueva evidencia de `series_sha256` de barras consumidas, captura 1000 barras y 120 checks/53 mutaciones reportados; 459 tests de runtime NO repetidos.
- `TAP-061` / `BL-14` (P1): ventanas emergentes de bash/cmd/PowerShell en Windows; **reportadas, no corregidas**. Véase `WP_OPS_BACKGROUND_001_NO_VISIBLE_CONSOLES.md`.
- El Excel v1.2, JSON y CSV actualizan 61 entregables. La issue/PR de roadmap permanece sin merge; no tocar ramas de otros agentes.

## Revisión v1.3 — 2026-10-18

- WP-OPS-BACKGROUND-001 `fe9b5e2`: `TAP-061` marcado `VERIFICADO_FOCAL` para procesos internos, pero pantalla visual `NOT_OBSERVABLE`. `TAP-062` Freebuff/Bun externo bloqueado; `TAP-063` Task Scheduler sin activar. Inventario total 63. No confirmar popup resuelto.

## Revisión v1.4 — 2026-10-18

- RFC-TAP-MARKET-005 `PROPOSED` en issue [#16](https://github.com/Extr3sao/bot_crypto/issues/16): **datos incrementales**, MarketSnapshot PIT, disparadores IA por evento y auditoría de recargas 1000x1h/500x4h/500x1d. Se añaden `TAP-064` a `TAP-071`, bloqueos `BL-16/BL-17`, una evidencia de correlación de código `EV-018` y roadmap de 71 entregables.
- **Sin nueva ejecución:** no atribuir esas descargas a Task Scheduler solo por parecerse a `real_market_context`; falta correlacionar proceso/task/run_id. El RFC no desactiva tareas ni activa LLM real; `REAL_MODEL_CALLED=false` permanece.
- El Excel, JSON y CSV deben actualizarse juntos con este README en la rama del roadmap. El PR #15 permanece sin fusionar a `main`.
