# Command 05 — Tasks

## Objetivo
Generar **tareas pequeñas, trazables y ejecutables** una a una. Cada
tarea cabe en un commit.

## Agente(s) responsable(s)
- Cualquier agente (a veces el mismo que escribió el plan).

## Entradas
- Plan del comando `04-plan.md`.

## Salidas
- `tasks/backlog.md` con tickets.
- IDs estables (`TSK-001`, …). Cada ticket tiene:
  - Descripción.
  - Archivos previstos.
  - Tests previstos.
  - Dependencias (qué ticket debe estar cerrado antes).
  - Estado (`todo | in_progress | in_review | done | blocked`).

## Pasos
1. Partir cada ticket del plan en 1–N tareas.
2. Asignar a un agente responsable.
3. Definir checks (lint, type, tests).
4. Definir criterios de aceptación.

## Criterio de finalización
- Cualquier desarrollador/agente puede tomar un ticket sin preguntas.

## NO
- No crear tickets sin criterios.
- No agrupar tickets que mezclen áreas no relacionadas.
