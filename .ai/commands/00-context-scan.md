# Command 00 — Context Scan

## Objetivo
Refrescar el mapa del repositorio y registrar lo encontrado. Es el
**primer paso obligatorio de cualquier cambio relevante**.

## Agente(s) responsable(s)
- `context-engineer`

## Entradas
- Estado actual del repo (archivos bajo `src/`, `config/`, `tests/`, `docs/`, `bdd/`, `.ai/`, `context/`, `tasks/`).
- Cambios desde el último context-scan (git diff contra rama base).

## Salidas
Actualizar:
- `context/codebase-map.md`
- `context/dependency-map.md`
- `context/impact-analysis.md`
- `context/exchange-api-notes.md` (si aplica)
- `context/trading-domain-notes.md` (si aplica)
- `context/retrieval-log.md` (append-only, siempre).

## Pasos
1. Leer `AGENTS.md` y `.ai/methodology-hybrid.md`.
2. Listar `src/trading_bot/<módulo>/` y resumir rol público.
3. Identificar puntos calientes: risk, execution, strategies, backtesting.
4. Comprobar `pyproject.toml` y dependencias declaradas.
5. Detectar nuevas dependencias añadidas sin ADR.
6. Detectar archivos con cambios no documentados.
7. Si hay cambios pendientes, preparar `impact-analysis.md`.
8. Anotar en `retrieval-log.md`.

## Criterio de finalización
- Todos los mapas actualizados.
- `retrieval-log.md` tiene la entrada con timestamp y resumen de hallazgos.
- Cualquier hallazgo crítico se reporta al PR (no se silencia).

## NO
- No modificar código.
- No eliminar entradas de `retrieval-log.md`.
