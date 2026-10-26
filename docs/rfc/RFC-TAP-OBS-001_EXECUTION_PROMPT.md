# Prompt de ejecución para Codex — RFC-TAP-OBS-001

Implementa en el repositorio **autoritativo** de Trading Agentic Portable el RFC adjunto `RFC-TAP-OBS-001_TRADING_DECISION_MONITOR.md`. Objetivo: **Trading Decision Monitor PAPER** con gráfico de velas tipo TradingView, marcadores de señales/decisiones/riesgo/fills, timeline de motivos verificables y `DecisionTrace` enlazado.

**Autonomía:** avanza por WP-TDM-00 a WP-TDM-05 sin solicitar confirmaciones triviales; documenta gaps, corrige fallos reversibles y valida antes de avanzar. No hagas trading LIVE, cambios de riesgo/sizing, movimientos de capital, actualizaciones de software sin permiso o acciones destructivas.

**Prioridad absoluta de la primera ejecución:** WP-TDM-00, auditoría read-only con evidencia de runtime real.

1. Identifica repositorio, `AGENTS.md`, entrypoints y procesos reales. Clasifica código en `RUNTIME_AUTHORITATIVE`, `RUNTIME_REACHABLE`, `TEST_ONLY`, `RESEARCH_ONLY`, `EXPERIMENTAL`, `LEGACY`, `ORPHAN` y `DEAD_CODE`. Captura baseline `git`, tests, runtime PAPER y event store.
2. **Usa MCP REA en Codex:** verifica `rea doctor --json`, `rea capabilities --json`, descubre `tools/list`, versión y capacidades reales. Elige herramientas REA aplicables para investigar la UI/bundle y validar escenarios de navegador, captura de proceso cuando sea seguro, inspección de artefactos y exportación/comparación de Evidence. No supongas APIs o nombres de tools; revisa los esquemas anunciados y el skill instalado. Exporta Evidence IDs, hash, coverage y unknowns; sanea secretos. Herramientas nativas/binaries solo si el objetivo lo exige; de lo contrario `NOT_APPLICABLE`.
3. Si REA no se expone en la sesión, diagnostica y deja constancia (`REA_MCP_UNAVAILABLE`), sin inventar resultados ni inventar un PASS. No instales/actualices REA a espaldas del usuario. Puedes continuar con inspección tradicional y marcar el gate REA pendiente.
4. Dibuja el flujo real: market data → strategy/router → proposal → decision → verifier → risk → paper execution → reconciliation → DecisionTrace. Demuestra cada arista con llamada/código/ruta y ejecución. Detecta en qué punto registrar una proyección de eventos sin modificar decisión ni rendimiento crítico.
5. Solo después del preflight, implementa los WPs siguiendo el RFC: contrato normalizado, API read-only y stream (preferir SSE o reutilizar WS), Lightweight Charts, timeline, drilldown, replay, tests y verificador independiente.
6. **No confundir** `SIGNAL`, `DECISION_ACCEPTED`, `ORDER_SUBMITTED` y `ORDER_FILLED`. `NO_TRADE` primera clase; todo texto basado en `reason_codes` y evidence; `data_time <= decision_time` obligatorio.
7. Compara `CURRENT vs PROPOSED` con mismos datos, configuración y constraints. Igualdad de decisiones/señales/órdenes/PnL, excepto event tracking. Prueba errores, gaps, stale, reconnect, replay y multiasset. Para validar el frontend, combina pruebas E2E con REA (cuando disponible).
8. Para cada WP genera `RUN_REPORT.md` y `.json` con comandos exactos, commits, estado, resultados, evidencia y defectos. Final independiente en `FINAL_REPORT.md` con `FALSE_SUCCESS=0` demostrado, no asumido.

**Entrega en respuesta:** matriz `WP → estado → tests → evidencia`, rutas de los reportes, comandos para iniciar monitor PAPER y una explicación visible de qué motivos provocaron rechazo o aceptación en una ejecución real. Nunca usar fixtures para declarar que el runtime está operando de verdad.
