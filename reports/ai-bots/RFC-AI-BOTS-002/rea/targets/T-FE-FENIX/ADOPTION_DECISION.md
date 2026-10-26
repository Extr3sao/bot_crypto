# T-FE-FENIX · decisión de adopción

**Decisión: `DEFER` para código, `EXPERIMENT` para el preflight de prompt,
`REJECT_ANTI_PATTERN` para el transporte de imagen.**

| eje | estado | base |
| --- | --- | --- |
| `REA_EXECUTED` | **YES** — 3 operaciones, 3 `evidence_id` | `ev_be8c7d74bb6ed79011e4d135ba011c7df95df4d50fcdfc4086223f8fb5931cc6`, `ev_fc2b6552ff6ca513ad2cfcf4563e44b5d50354c61453bb999a4088cb3116d5c8`, `ev_b3b1e8374c0403d7b7c2cd9c4af9dbb33144920f515de8cd95d647b4d73527a7` |
| `REA_EVIDENCE_APPLICABLE` | sí para el frontend; no para el pipeline Python | bundle 256.917 nodos, `complete` |
| `UPSTREAM_RUNTIME_REPRODUCED` | NO | backend no arrancado; sin claves |
| `LICENSE` | Apache-2.0 (corregido desde MIT) | compatible con aviso |
| `ADOPT` | ninguno | — |

## Por qué `DEFER` y no `ADOPT`

Su frontend sí se construye y se observa, pero lo que nos interesa de FenixAI —cómo
convierte velas en PNG y lo manda a un modelo— está en Python y no se puede ejecutar aquí sin
claves ni servicios. Lo que se leyó por fuente no supera a nuestro lane en ningún invariante
crítico.

## Qué haría falta

Autorización de proveedor y presupuesto para reproducir un ciclo real, o un harness en el que
su `ChartService` corra con velas sintéticas y sin exchange. Hasta entonces, `DEFER`.
