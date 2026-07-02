# Command 02 — BDD

## Objetivo
Traducir los requisitos en **escenarios Gherkin ejecutables**.

## Agente(s) responsable(s)
- `bdd-analyst`

## Entradas
- Requisitos del comando `01-requirements.md`.

## Salidas
- Archivos `.feature` en `bdd/features/`.
- Tabla de mapeo requisito → escenario.

## Pasos
1. Definir el `Feature:` con propósito legible.
2. Definir el `Background:` con estado común (modo `paper`, capital inicial, pares).
3. Crear `Scenario:` por comportamiento observable.
4. Añadir casos límite y negativos (rechazos, errores).
5. Validar que cada escenario tiene `Given/When/Then`.
6. Mantener los escenarios independientes entre sí.

## Criterio de finalización
- Cada escenario es ejecutable.
- Cobertura de requisitos = 100% en casos felices + los casos límite relevantes.
- Sin escenarios que dependan de la implementación interna.

## NO
- No escribir tests unitarios directamente aquí.
- No usar jerga técnica interna (solo lenguaje de negocio).
