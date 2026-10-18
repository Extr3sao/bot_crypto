# Trading Agentic Portable — Roadmap maestro

**Fecha de corte:** 2026-10-18 · **Versión actual:** 1.1 · **Estado:** inventario de gestión, NO certificado de producción.

Este directorio conserva el seguimiento de Trading Agentic Portable en formato Excel y un espejo de datos fácilmente revisable en Git. La autoridad de cada estado viene de los commits y evidencias de las ramas, **no** de la existencia del RFC.

## Archivos

- `ROADMAP_TRADING_AGENTIC_PORTABLE.xlsx`: Excel maestro con 9 hojas (RESUMEN, ROADMAP, FASES, RFC_Y_WP, BLOQUEOS, DEPENDENCIAS, EVIDENCIAS, HISTORIAL, COMO_ACTUALIZAR), 60 tareas con ID estable, filtros, prioridades y visualizaciones.
- `ROADMAP_MASTER_DATA.json`: snapshot estructurado de fuentes/estados para actualizaciones y futuros automatismos.
- `ROADMAP_MASTER.csv`: vista de las 60 tareas para diff, búsquedas y herramientas simples.

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

Issues principales: [#10](https://github.com/Extr3sao/bot_crypto/issues/10) · [#11](https://github.com/Extr3sao/bot_crypto/issues/11) · [#12](https://github.com/Extr3sao/bot_crypto/issues/12) · [#13](https://github.com/Extr3sao/bot_crypto/issues/13) · [#14](https://github.com/Extr3sao/bot_crypto/issues/14).

## Publicación

- La revisión v1.1 actualiza la fila `TAP-057` tras comprobar la primera subida a GitHub.
- La rama `project/roadmap-trading-agentic` conserva los archivos Excel, JSON, CSV y README; la integración a `main` requiere PR.
