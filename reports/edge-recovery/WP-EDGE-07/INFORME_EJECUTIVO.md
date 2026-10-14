# WP-EDGE-07 — Informe ejecutivo

*Lectura única de `2026-10-14T09:43:23Z` en `DESKTOP-4CHO695`, rama `agent/edge-recovery/WP-EDGE-00-baseline` en el commit `d30d52d068c1`. Todas las cifras de este informe salen del mismo diccionario del que se renderizan RUN_REPORT y FINAL_REPORT; no hay una cuarta medición paralela.*

## 1. Veredicto

**`CLOSED_WITH_OPEN_ITEMS`**: el volumen se recuperó lo suficiente para que el carril volviera a ingerir, las tres variantes de investigación (la tendencia de salida fija y las dos ACTIVE) fueron **rechazadas por criterios registrados antes de leer los datos**, la pregunta de frecuencia quedó respondida con una medición del techo de costes, y el verificador independiente pasa 13/13 con 14 de 14 sabotajes detectados.

## 2. Track A — recuperación operativa

| Punto del encargo | Resultado |
| --- | --- |
| Qué es lo que crece en `AppData/Local` | Tabla de escritores medida y publicada (`GROWTH_EVIDENCE.md`); los mayores escritores son aplicaciones del usuario, no el repositorio |
| Espacio libre y umbrales | **2.979 GiB** de 237.5 GiB, `ABOVE_CRITICAL_BELOW_HEALTHY`; el carril rechaza por debajo de 2.0 GiB y la publicación pesada espera por debajo de 5.0 GiB |
| No borrar nada externo sin autorización | Solo se retiraron cachés propias del repositorio: 193 rutas registradas, 0 aún presentes, 12 vecinos nombrados y **no** borrados |
| Recuperar margen con acciones seguras | **2,261,922,757 bytes (2.11 GiB)** en 4 barridos aplicados, de 8 invocaciones (las de prueba en seco no borran nada) |
| Dos ticks programados reales `OBSERVED` | **4** ticks programados observados después de la recuperación, con sus slots y peticiones de mercado en `RUN_REPORT.md` §2 |
| La reconciliación integrada corre desde el scheduler | 3 recibos durables en `data/forward/edge04/derived_refresh.jsonl`; el último del slot `2026-10-14T09:30Z` con `ran: True` y 4 artefactos de reconciliación |
| Datos forward y artefactos congelados intactos | El verificador re-deriva que el log es append-only, que el almacén conserva todas las series y que los parámetros congelados siguen siendo los registrados (`9ceb20fc7d4500c3…`) |

## 3. Track B — validación económica de la tendencia con objetivo fijo 3xATR

Parámetros, datos, costes, hipótesis y criterios se registraron el `2026-10-14T08:53:54Z` (`EDGE07-PREREG-20261014T085354Z`), antes de descargar el corpus. La ventana nueva (`2026-03-01T00:00:00Z` a `2026-10-14T07:00:00Z`, 1363 barras de 4h por activo, 0 huecos) se leyó una sola vez.

### PnL neto por ventana, escenario BASE

| Ventana | Ya consultada antes | Operaciones | Neto (USDT) | Neto con 2x comisiones | Esperanza | Sharpe | Profit factor | DD max % | Concentración mayor | Coste bps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `DEV` | True | 584 | **1056.2895** | 104.2169 | 1.8087 | 0.7219 | 1.1966 | 4.0367 | 7.4 % | 23.8579 |
| `VAL` | True | 136 | **-146.1493** | -281.5418 | -1.0746 | -0.575 | 0.869 | 3.5367 | — | 23.7887 |
| `OOS_CONSULTED` | True | 113 | **230.0174** | 116.674 | 2.0356 | 0.9585 | 1.321 | 1.5329 | 22.2 % | 23.8629 |
| `NEW_HOLDOUT` | False | 65 | **-140.3041** | -205.2287 | -2.1585 | -1.2461 | 0.671 | 2.1413 | — | 23.763 |

**Veredicto `REJECT`** en la ventana nueva, con potencia (True, 65 operaciones): criterios decisivos fallidos P2, P3, P4, P5, P6, R1, R2. La ventana consultada antes de este trabajo está separada de forma explícita y no se usó para ajustar nada; su neto de referencia es 230.0174 USDT y no se lee como evidencia nueva.

Robustez y comparación: por activo y por régimen de mercado (publicados en `validation/VALIDATION.md`), en tres bloques temporales iguales (1 de 3 positivos), quitando la mejor operación (-170.085 USDT), con intervalos al 90 % por bootstrap de bloques de 20 operaciones (esperanza [-5.1501, 1.0015] (point -2.1585)) y dependencia temporal (autocorrelación lag-1 0.5073 frente a una banda de ±0.2481). La comparación trailing usa los mismos datos, costes y política de riesgo: 61.0046 USDT en 28 operaciones, insuficiente por potencia y concentración, no una admisión.

## 4. Track C — investigación ACTIVE

La tendencia se mantiene como módulo separado de baja frecuencia. Se registraron 2 candidatas ACTIVE multi-activo con objetivo de 3 operaciones diarias, y el propio filtro registrado las rechazó antes de tocar la ventana independiente: `edge07_active_fade` REJECT_NO_GROSS_EDGE; `edge07_active_thrust` REJECT_NO_GROSS_EDGE. Ninguna relajó un límite, forzó operaciones ni multiplicó exposición.

### Por qué la frecuencia alta está cerrada por aritmética, no por una mala candidata

Con un ida y vuelta de **23.7906 bps**, la fracción del movimiento open-to-open que una estrategia debe capturar solo para empatar, medida sobre las barras de la ventana independiente, es:

| Horizonte | Operaciones/día en el universo | Fracción del movimiento necesaria (BTC) |
| --- | --- | --- |
| 1 h | 72 | 86 % |
| 2 h | 36 | 60 % |
| 4 h | 18 | 43 % |
| 8 h | 9 | 30 % |
| 24 h | 3 | 16 % |

A un reloj horario hay que capturar la mayor parte del movimiento entero: prácticamente inalcanzable. A un reloj diario (una entrada por activo y día, el objetivo del encargo) la exigencia baja al 11-16 %, que sí es un problema de estrategia y no de costes. Esa es la dirección que la evidencia señala, registrada como propuesta y no ejecutada.

## 5. Qué NO se declara

- Ni `CERTIFIED`, ni `READY_FOR_PAPER`, ni `PRODUCTION_READY`: `promotion: NONE`, `order_sent: False`.
- No se acortó ningún día forward: la compuerta de 60 días sigue intacta.
- `NEW_HOLDOUT` está gastada: no se repite, no se ajusta y no se vuelve a leer.
- El volumen sigue por debajo del umbral sano de 5.0 GiB, así que la publicación pesada espera; limpiar temporales del perfil es decisión del titular del volumen, no una limpieza del repositorio.
- Ningún límite de riesgo, regla de tamaño ni compuerta de promoción se modificó; no se leyó, guardó ni imprimió ninguna credencial.

## 6. Verificación y reproducibilidad

| Comprobación | Resultado |
| --- | --- |
| Verificador independiente | **PASS**, 13/13 comprobaciones, 0 fallidas, exit `0` |
| Autoprueba del verificador | PASS: 14/14 sabotajes detectados |
| Pruebas propias | exit `0` - 26 passed in 2.17s |
| Lint, formato y tipos | exit `0`, `0`, `0` |
| Evidencia económica reproducible | El runner reprodujo cada cifra publicada que re-deriva (instrument check: True), y la ventana nueva tiene digest por fragmento `196884f9e719315e…` |
| Commits aislados y push | rama `agent/edge-recovery/WP-EDGE-00-baseline`, rango `edd4ef2..d30d52d`, el remoto leído de vuelta: True |

## 7. Decisiones abiertas

- El volumen está en 2.979 GiB: por encima de los 2.0 GiB bajo los que el carril rechaza ticks, por debajo de los 5.0 GiB que espera la publicación pesada — *el titular del volumen: limpiar temporales de más de un día*
- La variante de salida fija fue rechazada en una ventana que nadie había leído, así que '¿habría salvado algo otra salida?' queda sin responder: la comparación trailing es positiva en la misma ventana pero sin potencia — *un nuevo preregistro sobre una ventana sin leer*
- Las dos ACTIVE se detuvieron en su propio filtro registrado antes de la ventana independiente, así que el objetivo horario descansa en el techo medido y no en una candidata — *un nuevo registro en un reloj que la tabla de barrera dice que es pagable*
