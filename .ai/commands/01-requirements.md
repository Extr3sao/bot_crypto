# Command 01 — Requirements

## Objetivo
Elicitar y documentar **requisitos funcionales y no funcionales** antes de
escribir código.

## Agente(s) responsable(s)
- `quant-researcher` (cuando aplica a estrategia/indicador).
- `bdd-analyst` (cuando se requieren escenarios).
- Cualquier agente técnico concernido como apoyo.

## Entradas
- Idea de cambio / ticket en `tasks/backlog.md`.
- Documentación existente (`docs/architecture.md`, `docs/risk-policy.md`).
- BDD existente.

## Salidas
- Sección "Requisitos" en el PR/ADR (e.g. `tasks/decisions.md` ADR-NNN).
- Cambios en `tasks/backlog.md` con criterios de aceptación.
- Borrador de escenarios BDD (entregado luego a `02-bdd.md`).

## Pasos
1. Listar requisitos funcionales (verbos, observables).
2. Listar requisitos no funcionales (seguridad, rendimiento, mantenibilidad).
3. Definir criterios de aceptación (medibles).
4. Definir casos límite y modos de fallo.
5. Identificar dependencias y asunciones.
6. Pasar el borrador a `02-bdd.md`.

## Criterio de finalización
- Toda requisito escrita tiene al menos un criterio de aceptación.
- Modos de fallo y mitigaciones listados.
- El equipo puede decir "sí, eso es lo que queríamos".

## NO
- No escribir código todavía.
- No firmar requisitos sin criterios de aceptación objetivos.
