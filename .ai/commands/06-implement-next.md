# Command 06 — Implement Next

## Objetivo
Implementar **una única tarea aprobada**, preferiblemente con TDD.

## Agente(s) responsable(s)
- Implementador (humano o LLM), supervisado por el agente técnico del módulo.

## Entradas
- Ticket `TSK-NNN` aprobado en `tasks/backlog.md`.

## Salidas
- Commit pequeño (idealmente un solo cambio coherente) con:
  - Tests (cuando aplique: TDD: rojo → verde).
  - Cambios mínimos en `src/trading_bot/`.
  - Documentación actualizada si cambian contratos.

## Pasos
1. Leer contexto (`00-context-scan.md` mínimo).
2. Crear test(s) primero (cuando TDD).
3. Implementar lo mínimo para pasar.
4. Refactorizar.
5. Pasar lint+mypy+tests.
6. Commit referenciando el ticket.

## Criterio de finalización
- Tests en verde.
- `ruff` y `mypy` limpios.
- Commit con mensaje `[TSK-NNN] <descripción>`.

## NO
- No mezclar varios tickets en un commit.
- No introducir dependencias sin ADR.
- No tocar configuración sin actualizar el YAML correspondiente.
