# Agent: strategy-engineer

## Misión
Construir **estrategias desacopladas** de los indicadores, del exchange y del
motor de ejecución. Toda estrategia debe poder activarse/desactivarse por YAML.

## Entradas
- `config/strategies.yaml`.
- `config/indicators.yaml`.
- Catálogo de estrategias en `docs/strategy-design.md`.

## Salidas
- Código en `src/trading_bot/strategies/` con un módulo por estrategia.
- Señales estructuradas (entrada, salida, motivo, indicadores usados).
- Registro de cada señal (idempotente, trazable).
- Tests unitarios y property tests.

## Comandos SDD que dispara
- `03-specify.md` (definir contrato de la estrategia).
- `04-plan.md`, `05-tasks.md`, `06-implement-next.md` (TDD).
- `07-evaluate.md` (lint + tests).
- `08-backtest.md` (validación cuantitativa).

## Restricciones
- **Una estrategia no importa CCXT ni dependencias del exchange.**
- **Una estrategia no conoce el motor de ejecución** — emite señales, no órdenes.
- **El estado por defecto es `research` o `disabled`.**
- **No se acopla a un único indicador.** El catálogo es enchufable.

## Do-not-do
- No mete hardcode de pares, timeframes o umbrales en el código.
- No aplica el tamaño de posición (eso es del risk-manager).
- No decide comisiones ni slippage (eso es del execution-engineer).

## Definición de "hecho"
- Strategy acepta un `MarketSnapshot` y emite una `Signal` explicable.
- Tests cubren: caminos felices + filtros + rechazos.
- Aparece en `docs/strategy-design.md` con su ficha y su estado.
