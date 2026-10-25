# FINAL_REPORT — RFC-TAP-AI-BOTS-003G

**Veredicto:** `PARTIAL`
**Puertas G1–G4, G7:** PASS · **G5:** PASS en el vacío (0 cierres) · **G6:** 1 fallo ambiental
declarado · **Puerta económica de 003F:** `INSUFFICIENT_SAMPLE`
**Independencia:** `INDEPENDENT_VERIFICATION_PENDING`
**LIVE:** no habilitado · **`REAL_MODEL_CALLED=false`** · **`FALSE_SUCCESS=0`**

---

## 1. Qué se ha demostrado

El motor causal que 003B–003F validó con datos históricos **se ha ejecutado prospectivamente
contra el mercado real en PAPER**, sin reconstrucción y sin look-ahead, y la capacidad sub-bar
ha rellenado una orden a un precio que existió después de que llegara la respuesta.

| Hecho | Número | Evidencia |
| --- | --- | --- |
| Sesión real de 1 m | 276 minutos × 2 símbolos, 0 gaps | `session/market-1m/` + `MANIFEST.json` |
| Ciclos prospectivos | 8 (07:29 → 08:00 UTC) | `session/SUMMARY.json` |
| Decisiones | 14 | ledgers acumulados |
| Rellenos sub-bar | **1** (BTC/USDT, apertura 07:31:00) | `FILL` en el ledger |
| `data_time <= decision_time` | 8/8 ciclos | `CYCLE` rows |
| Retardo de entrega medido | 2 956 ms (p95) | `DELAY_MEASURED` |
| Ciclos bloqueados | 0 | `STREAM.jsonl` |
| Órdenes LIVE | 0 (sin ruta de orden en el runtime) | verificador, check 5 y 23 |
| Coste de IA | 0,00 USD | `paper-script` |

La diferencia medible entre CURRENT y PROPOSED **no es de rentabilidad**: es de **capacidad de
ejecución**. Con la misma serie, el mismo guion y la misma latencia declarada de 30 s,
**CURRENT no rellena ninguna de las 14 decisiones** porque sólo acepta la apertura de la vela
siguiente, que ya ha pasado cuando llega la respuesta. **PROPOSED rellena 1** usando la primera
apertura de 1 m posterior a la respuesta. Ese es el hallazgo del WP, y es exactamente el que
motivaba el RFC.

## 2. Puertas

| Puerta | Umbral | Medido | Estado |
| --- | --- | --- | --- |
| G1 causalidad | 0 rellenos con `quote_ts < received_at` | 0 (1/1 relleno con `quote_lag` 27 044 ms > 0) | **PASS** |
| G2 frescura | 0 ciclos stale/gap/skew | 0 de 8; 0 gaps en 552 minutos | **PASS** |
| G3 no-look-ahead | 0 decisiones con `data_time > decision_time` | 0 de 8 | **PASS** |
| G4 precio real | 100 % a apertura 1 m observada | 1/1 (`binance_spot_1m_klines`) | **PASS** |
| G5 costes | identidad en cada cierre | 0 cierres → cierto en el vacío | **PASS (vacuo)** |
| G6 regresión | 0 fallos nuevos | 657 pass / 1 fail ambiental (dashboard vs. escritor concurrente, aislado 14/14) | **PARCIAL** |
| G7 LIVE | 0 órdenes y 0 rutas | 0 en stream, 0 endpoints en runtime | **PASS** |
| Económica 003F | ≥ 30 cierres, Δneto > 0, ΔDD ≤ +0,10 pp | 0 cierres | **INSUFFICIENT_SAMPLE** |

**G5 es la puerta más débil y así se declara:** con 0 cierres, la identidad de PnL no se ha
ejercitado ni una vez en esta sesión. No es un PASS ganado; es un PASS no falsable con esta
muestra.

## 3. Por qué `PARTIAL` y no `PAPER_VALIDATED`

El criterio de terminación del RFC exige **verificación independiente por un tercero**. El
verificador de bytes existe, no importa el runtime y detecta las 4 mutaciones probadas, pero lo
escribió el mismo agente que construyó el carril: `BUILDER == VERIFIER`. Presentarlo como
`PAPER_VALIDATED` sería exactamente el `FALSE_SUCCESS` que el método prohíbe. Falta, además,
la muestra mínima (≥ 30 cierres) para el veredicto económico.

Nada de esto invalida el trabajo: la sesión, sus minutos, sus hashes, sus ledgers y su
verificación son reproducibles con los comandos de `RUN_REPORT.md` §8.

## 4. Defectos encontrados y su tratamiento

| ID | Defecto | Tratamiento |
| --- | --- | --- |
| D1 | El grupo de 5 m cortado por el inicio de la ventana se trataba como hueco | **Corregido** + test + evidencia del fallo |
| D2 | El venue revisó una vela ya cerrada (ETH 07:18) | **Corregido por política** (`settle_ms`); el dato no se reescribió; bloqueo fail-closed |
| D3 | El propio verificador tenía el defecto D1 | **Corregido**; la mutación interior sigue detectada |
| D4 | Test del dashboard falla con un escritor concurrente en `reports/` | **Declarado**, fuera de alcance de este WP |
| D5 | `costs_usdt` sólo agrega operaciones cerradas; la comisión de la posición abierta (0,5 USDT) no aparece en ese campo | **Declarado**, no corregido (código congelado para la sesión) |

D2 es la lección más útil del WP: la fuente pública **sí** puede devolver una vela cerrada con
OHLC distinto minutos después, y el sistema hizo lo correcto — bloquear en vez de reescribir.
Cualquier diseño que acepte "la vela de 1 m al cerrar" como definitiva hereda ese riesgo.

## 5. Qué falta para cerrar

1. **Verificador humano/segundo agente** sobre `session/` (criterio de terminación).
2. **≥ 30 cierres** prospectivos para la puerta económica (con este guion hace falta una sesión
   mucho más larga o un proveedor real).
3. **Proveedor real de visión** con autorización de gasto (`REAL_MODEL_CALLED=false` hoy).
4. Decidir si `costs_usdt` debe ser realizado o total (D5) antes de publicar cualquier métrica
   de coste agregada.

## 6. Índice de artefactos

- [RFC-TAP-AI-BOTS-003G.md](../../../RFC-TAP-AI-BOTS-003G.md)
- [RUN_REPORT.md](RUN_REPORT.md) · [RUN_REPORT.json](RUN_REPORT.json)
- [INDEPENDENT_VERIFICATION.md](INDEPENDENT_VERIFICATION.md) · [session/VERIFICATION.md](session/VERIFICATION.md)
- [STATE_AUDIT.md](STATE_AUDIT.md) · [runtime_authority_map.md](runtime_authority_map.md)
- [session/SUMMARY.json](session/SUMMARY.json) · [session/STREAM.jsonl](session/STREAM.jsonl)
- [session/compare/COMPARISON.json](session/compare/COMPARISON.json) · [session/compare-full/COMPARISON.json](session/compare-full/COMPARISON.json)
- Fallos conservados: [session-aborted-aggregation/](session-aborted-aggregation) · [session-venue-revision/](session-venue-revision)
