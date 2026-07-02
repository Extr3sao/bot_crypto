# Command 04 — Plan

## Objetivo
Construir un **plan de implementación incremental** que divida el cambio
en unidades pequeñas, seguras y verificables.

## Agente(s) responsable(s)
- Cualquier agente técnico concernido.

## Entradas
- Spec del comando `03-specify.md`.

## Salidas
- Plan incremental en `tasks/backlog.md` (o doc específico) con:
  - Fases.
  - Tickets por fase.
  - Para cada ticket: archivos a tocar, tests esperados, gate de aceptación.

## Pasos
1. Dividir el cambio en pasos que pueda revertirse.
2. Cada paso debe ser verificable (test, métrica o inspección).
3. Empezar por los cimientos (tipos, contratos) antes de la lógica.
4. Marcar los tickets que requieren paper trading antes de merge.

## Criterio de finalización
- Lista de tickets con criterios del estilo "Definition of Done".
- Orden claro (qué ticket desbloquea cuál).

## NO
- No incluir tickets "relleno" sin valor.
- No aplazar la seguridad a "más adelante".
