# Sprint 001

> Sprint de arranque. Foco: cimientos de Fase 1 con configuracion
> tipada. No se hace fetch real todavia: CCXT queda para sprints
> posteriores, una vez TSK-099 firme.

> **Estado real**: cerrado por ADR-0011. `TSK-099` quedo mergeado en
> `main`; `TSK-008` no entro en ese merge y se arrastro a
> `sprint-002` como prioridad 1.

---

## Duracion

- **Inicio**: 2026-07-02.
- **Fin blando**: 2026-07-09.
- **Fin duro**: 2026-07-16.

## Objetivo del sprint

Poner en pie la capa de configuracion tipada con Pydantic v2
(`TSK-099`) y dejar encaminado el baseline de calidad (`TSK-008`)
sobre el que los siguientes sprints construyen CI e ingesta.

## Resultado final

- `TSK-099`: **done** y mergeado en `main` (`9eed3fd`).
- `TSK-008`: **arrastrado** a `sprint-002` por ADR-0011.
- `TSK-101` y posteriores: fuera de alcance de este sprint; su trabajo
  pertenece a `sprint-002` o backlog posterior.

## Tickets planificados

### Foundations (objetivo de este sprint)

| ID | Descripcion | Est. | Owner | Depende de | Estado final |
| --- | --- | --- | --- | --- | --- |
| TSK-008 | Baseline de calidad: ruff, mypy, pytest, pip-audit, CI en GitHub Actions | S | Mixto | - | moved_to_sprint_002 |
| TSK-099 | Capa de configuracion tipada con Pydantic v2 (`src/trading_bot/config/`) | M | Mixto | - | done |

### Fuera de alcance de cierre

| ID | Descripcion | Est. | Owner | Depende de | Estado final |
| --- | --- | --- | --- | --- | --- |
| TSK-100 | ADR firmados adicionales si se promovian en este sprint | S | Tu | - | done_or_deferred |
| TSK-101 | `ExchangeConnector` (interfaz + esqueleto sin fetch real) | M | IA | TSK-099 | moved_to_sprint_002 |
| TSK-102 | Descarga OHLCV con validacion + normalizacion | L | Mixto | TSK-099, TSK-101 | moved_to_sprint_002 |
| TSK-103 | Persistencia local OHLCV en `data/raw/` | M | Mixto | TSK-099, TSK-102 | moved_to_sprint_002 |
| TSK-104 | Scheduler on-demand + cache de velas recientes | M | IA | TSK-099, TSK-102 | moved_to_sprint_002 |
| TSK-105 | Tests: unit (CCXT mock) + integration (testnet real si hay credenciales) | M | Mixto | TSK-101 | moved_to_sprint_002 |
| TSK-110 | BDD `market_scanner.feature` ejecutado en `pytest-bdd` | S | Mixto | TSK-102 | moved_to_sprint_002 |

## Criterio de salida del sprint

- `TSK-099` cerrado con DoD verde y mergeado en `main`.
- `TSK-008` no quedo mergeado en este sprint; se arrastro a `sprint-002` mediante ADR-0011.
- ADR relevantes firmadas: `ADR-0010` y `ADR-0011`.
- El backlog y la planificacion de los siguientes tickets quedaron actualizados.

## Riesgos detectados

- **R1 - Tamano real de TSK-099**. Pydantic v2 resulto mas profundo de lo previsto.
- **R2 - CI sin consolidar**. El baseline de calidad no entro en el mismo merge que `TSK-099`.
- **R3 - Desfase documental**. Habia riesgo de seguir leyendo `sprint-001` como sprint activo aunque el trabajo vivo ya se habia movido a `sprint-002`.

## Review al cierre

- El hito de configuracion tipada se completo.
- El baseline de CI no se perdio, pero se convirtio en prioridad 1 del sprint siguiente.
- El sprint se cierra por excepcion firmada para separar claramente trabajo mergeado de trabajo local.

## Log

```
[2026-07-02] [Buffy + usuario] Sprint abierto. Scope reducido a TSK-099 + TSK-008 por recomendacion del thinker (config tipada antes de cualquier conector). TSK-10x marcados como bloqueados.

[2026-07-02] [Buffy + usuario] ADR-0009 firmado: GitHub privado, HTTPS, rama main, URL https://github.com/Extr3sao/bot_crypto.git.

[2026-07-03 19:00] [context-engineer] Cierre formal por ADR-0011. `TSK-099` queda consolidado en `main` por PR #1 / commit `9eed3fd`. `TSK-008` se arrastra a `sprint-002` como Pri 1; `TSK-101+` salen del scope de este sprint y pasan a plan activo posterior.
```
