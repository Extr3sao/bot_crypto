# T-NF-NOF1 · decisión de adopción

**Decisión: `REJECT` para código, `REJECT_ANTI_PATTERN` para sus dos rasgos centrales,
`EXPERIMENT` para el único rasgo reutilizable.**

| eje | estado | base |
| --- | --- | --- |
| `REA_EXECUTED` | **YES** — `ev_4b2bf9c5c313530cc7e1e399d4cde5c175ecdd0018a9f608ee12782522ea9ade` | análisis del `public/` del commit exacto, exit 0 |
| `REA_EVIDENCE_APPLICABLE` | parcial | artefacto estático; la cadena de decisión es TypeScript que REA no ejecuta |
| `UPSTREAM_RUNTIME_REPRODUCED` | NO | sin `npm ci`, sin provider, sin órdenes |
| `LICENSE_DECISION` | AGPL-3.0 | estudiar sí; copiar/derivar, no |
| `ADOPT` | ninguno | — |

## Por qué `REJECT` de código

AGPL-3.0 y una arquitectura en la que el modelo mueve el apalancamiento. Importar algo
obligaría a arrastrar ambas cosas.

## Por qué `EXPERIMENT` en un solo rasgo

Su contexto multi-timeframe es el único elemento que nuestra `BOT-CTX-01` ya cubre de forma
parcial. Ampliar a 6 timeframes es una hipótesis, no una mejora: sin medida económica no se
toca el runtime.

## Qué haría falta para cambiar de decisión

Un escenario reproducible en el que la extensión de contexto multi-timeframe mejore el
resultado neto del mismo libro, con el mismo reloj y costes. Hoy no existe.
