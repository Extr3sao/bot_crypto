# WP-EDGE-09 — informe ejecutivo

*Lectura única del paquete en `2026-10-15T05:24:06Z` (`EDGE09-REPORT-20261015T052406Z`). Las cuatro piezas se renderizan del mismo diccionario, así que no pueden contradecirse.*

## 1. Veredicto

**`NO_ECONOMIC_EDGE_FOUND`** — the forward quote data is real and usable, but no measured structure covers the 23-24 bps round trip: the best long-only gross is 1.582703 bps, the tape offers no barrier-clearing move at a 1 or 5 second horizon, and the cheapest registered venue still costs more than the measured gross

Decisión de adopción: **`DO_NOT_ADOPT`**. nothing measured here is adopted: no strategy, no parameter set and no venue change leaves this package. The RFC's success criterion is a better-founded research decision, and the founded decision is to adopt none of these arms.

| Pregunta | Respuesta |
| --- | --- |
| Coste de ida y vuelta | 22.99-24.08 bps |
| Peso de la tarifa en ese coste | 85.9% of the barrier |
| Mejor movimiento bruto medido | 1.582703 bps |
| Frecuencia de movimientos que cubren la barrera (tape) | 1s: 0.0/day; 5s: 0.0/day; 60s: 48.018/day; 900s: 179.619/day; 3600s: 11.553/day |
| Frecuencia que extrae el selector de desequilibrio medido | 1s: 0.0/day long-only; 5s: 0.0/day long-only; 60s: 144.061/day long-only |
| ¿Una sede más barata lo salva? | no: MEXC_SPOT_TAKER is the cheapest at 12.9866 bps, still above the best gross 1.582703 |
| ¿El libro medido absorbe el tamaño cotizado? | yes for perp at the quoted size, spot rests on 3 snapshots only |

## 2. Qué se midió de verdad

- 10 streams de la captura forward, 95913 filas de un segundo, 16626886 eventos de cotización y 287946 operaciones.
- 10.14 h de captura forward en el repositorio, con la pérdida declarada por cada manifiesto.
- El flujo de operaciones del perpetuo no existe en este entorno: el stream entregó cero mensajes y la ausencia se declara, no se sustituye.

## 3. Por qué no hay edge

La brecha es aritmética en el reloj corto e informativa en el largo: la barrera es 23-24 bps de ida y vuelta, la tarifa sola son 20 bps, y la mejor señal medida aquí es 1.582703 bps; ni la tarifa más barata registrada (MEXC_SPOT_TAKER) baja la barrera por debajo de ese bruto. A 1 y 5 segundos el propio tape no llega a moverse tanto — el límite superior es cero y ningún selector puede ayudar ahí. A 60 segundos el tape **sí** ofrece movimientos que cubren la barrera, pero el selector medido extrae 1s: 0.0/day long-only; 5s: 0.0/day long-only; 60s: 144.061/day long-only y su bruto sigue siendo 1.582703 bps frente a esa misma barrera: al reloj largo no le falta movimiento, le falta una forma medida de saber cuál es.

## 4. Qué haría falta para la siguiente fase

- una señal con al menos 35 bps brutos en un horizonte que este tape pueda entregar, o
- una sede cuyo ida y vuelta quede por debajo del bruto medido, con tarifa confirmada y no promocional, o
- un producto ejecutable con coste materialmente menor (el spot VIP0 no lo ofrece: maker igual a taker y la puerta maker ya falló).

## 5. Límites declarados

- profitability of any book: promotion is NONE and no order is sent
- anything about liquidity outside the 4.16 h the forward capture covers
- anything about the perp trade flow: this environment delivered zero perp aggTrade messages (SRC-15/SRC-18) and the absence is declared, never substituted
- anything about realised maker fills: no venue in this project has a measured fill model
- anything about markets the runtime excludes (derivatives are information, not product)
- the capture spans hours across a handful of days, so a rate per day is an extrapolation from a short sample and is reported with its span
- no venue in this project has a measured maker fill model, so a passive product cannot be scored here at all

`promotion: NONE`, `order_sent: False`, `FALSE_SUCCESS: 0`. No se declara rentabilidad ni preparación para paper o producción.
