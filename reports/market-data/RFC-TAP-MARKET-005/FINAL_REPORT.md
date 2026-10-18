# FINAL_REPORT — RFC-TAP-MARKET-005

## Veredicto

**Ingeniería offline: DONE (WP-005A…G). Activación en el host: NO EJECUTADA (WP-005H).**

El runtime ya se estaba descargando 1 000 / 500 / 500 velas por activo para decidir, pero **no cada 15 minutos**: el supervisor de CAP004 pasa el 99,9 % de sus ciclos en `NOOP` sin tocar la red. La tarea que sí corre cada 15 minutos y sí descarga es ALPHA002 (derivados, retención de 30 días en el venue) y ya es windowless. Las ventanas que molestan vienen de las **cinco tareas que aún lanzan `python.exe`**, no de Freebuff, y el repositorio ya contiene el lanzador que lo evita: lo que falta es re-registrar las tareas, que es una modificación del host y por tanto está detrás de autorización.

La descarga 1000/500/500 no se apaga: se sustituye por un lector incremental que **demuestra** que devuelve la misma ventana cerrada leyendo un 88,3 % menos de peticiones y un 98,9 % menos de velas (99,92 % menos bytes en régimen estable).

## Lo que se entrega

| Entregable | Estado |
|---|---|
| `RUNTIME_FETCH_AUTHORITY_MAP.md` | 6 tareas, 9 orígenes, atribución `NOT_ATTRIBUTABLE` donde no hay prueba |
| `SCHEDULER_INVENTORY.json` | inventario real + bytes medidos por forma de petición |
| `FETCH_PROCESS_TRACE.jsonl` | 9 trazas con `atribución`, `consumer`, `verdict` y `screenshot_match` |
| `CURRENT_VS_PROPOSED.json` | 12 series, misma ventana, equivalencia 12/12 |
| `COVERAGE_LEDGER.jsonl` | 1 164 ciclos con watermark antes/después y huecos |
| `AI_TRIGGER_LEDGER.jsonl` | 4 decisiones, 0 triggers, 0 llamadas, hash por fila |
| `INDEPENDENT_VERIFICATION.json` | 8 PASS / 0 FAIL, 5/5 mutaciones detectadas |
| `RUN_REPORT.json` / `RUN_REPORT.md` | métricas, tests, límites, plan WP-005H |
| `docs/runtime/RUNTIME_FETCH_AUTHORITY_MAP.md`, `docs/rfc/RFC-TAP-MARKET-005.md` | mapa de autoridad y registro de decisión |
| Excel maestro | actualizado en `project/roadmap-trading-agentic` (TAP-064…TAP-071) |

## Números que sostienen la decisión

```
CURRENT   1 164 peticiones   770 312 velas   133,32 MiB/día
PROPOSED    136 peticiones     8 496 velas     1,47 MiB/día (incluye bootstrap)
                                              108,6 KiB/día en régimen estable  (−99,92 %)
equivalencia de la ventana cerrada: 12/12 series idénticas
snapshots PIT: 4/4 causales · available_at_ms ≤ decision_ms
IA: 4 decisiones, 0 triggers, 0 llamadas de modelo (credencial ausente)
```

## Lo que este informe **no** dice

- No dice que la captura de pantalla del usuario viniera de la tarea CAP004. No hay `req_id` persistido ni proceso vivo: `NOT_ATTRIBUTABLE`. Lo demostrado es qué código puede producir esa forma y cuál no.
- No dice que el bot gane dinero. El lector incremental reduce coste y error; no crea ventaja.
- No dice que la IA esté validada: `REAL_MODEL_CALLED=false`, gate verificado sólo offline.
- No dice que las ventanas hayan desaparecido. Siguen ahí hasta que se autorice re-registrar las tareas.
- **REA no se ejecutó en este RFC, y se declara el motivo:** aquí no se adopta código de terceros. Las únicas fuentes son la API pública del exchange (medida con `curl` y capturada en el fixture) y el runtime local. No hay candidato GitHub que clasificar, así que no se repitió ni se amplió ninguna investigación REA previa; el `source_registry` de AI-BOTS-002/003D no se tocó.

## Fallos encontrados durante la construcción (y corregidos)

1. El overlap del delta emitía una petición por ciclo aunque no hubiera vela nueva → ahora `NO_NEW_DATA` hace 0 peticiones.
2. `OHLCVStore` no tiene dimensión de timeframe: 1h/4h/1d del mismo símbolo se sobrescribían y el snapshot devolvía una serie mezclada → `OHLCVTimeframeStore` sin tocar el esquema.
3. La frescura absoluta habría invalidado siempre la vela diaria → la regla es `age > max_age + duración_del_timeframe`.

## Riesgos abiertos

- **Concurrencia:** el CLI no tiene lease propio. Dos invocaciones simultáneas competirían por el watermark. Por eso WP-005H exige un diseño de exclusión antes de programar nada.
- **Backlog:** sin `since`, una caída de más de 1 000 velas se rechaza (`BACKLOG_EXCEEDS_WINDOW`) y exige `reconcile` explícito. Es deliberado: no se rellena un hueco en silencio.
- **Suite completa:** `NOT_RUN`. Se ejecutaron 158 + 21 + 59 + 28 tests y las comprobaciones estáticas; no se declara nada más.

## Frase para el roadmap

> El problema no era "la IA necesita datos": era que el runtime no distinguía entre *tener* datos y *volver a pedirlos*. Ahora lo distingue, lo mide y se niega a avanzar cuando no puede probar la cobertura.
