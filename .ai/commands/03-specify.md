# Command 03 — Specify

## Objetivo
Generar la **especificación técnica** del módulo o cambio:
contratos de tipos, interfaces, errores, configuración afectada.

## Agente(s) responsable(s)
- `strategy-engineer`, `execution-engineer`, `backtest-engineer` (según módulo).
- Apoyo de `security-reviewer` si toca permisos/red/secretos.
- Apoyo de `risk-manager` si toca sizing/filtros/kill switch.

## Entradas
- Requisitos (`01-requirements.md`).
- Escenarios (`02-bdd.md`).
- Configuración existente.

## Salidas
- Documento de spec (e.g. sección en `docs/architecture.md`, doc dedicado).
- Contratos de funciones/clases en `src/trading_bot/<módulo>/...` como docstrings.
- Tabla de errores y su propagación.

## Pasos
1. Definir tipos (dataclasses/Pydantic) de entrada/salida.
2. Definir errores y excepciones custom.
3. Definir invariantes (e.g. "una orden siempre tiene `client_order_id`").
4. Definir configuración afectada y validación.
5. Definir métricas observables.
6. Listar dependencias nuevas (con justificación).

## Criterio de finalización
- Código que se escriba después puede esbozarse mentalmente sin preguntas abiertas.
- Todas las funciones públicas tienen contrato claro.

## NO
- No entrar en optimización prematura.
- No elegir dependencias pesadas "por si acaso".
