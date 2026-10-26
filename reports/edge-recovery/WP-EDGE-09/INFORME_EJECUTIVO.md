# WP-EDGE-09 — informe ejecutivo

*Lectura única del paquete en `2026-10-15T05:56:25Z` (`EDGE09-REPORT-20261015T055625Z`). Las cuatro piezas se renderizan del mismo diccionario, así que no pueden contradecirse.*

## 1. Veredicto

**`NO_ECONOMIC_EDGE_FOUND`** — los datos de cotización forward son reales y usables, pero ninguna estructura medida cubre los 23-24 bps de ida y vuelta: el mejor bruto long-only es 1.582703 bps, el tape no ofrece ningún movimiento que cubra la barrera a 1 o 5 segundos, y la sede registrada más barata sigue costando más que el bruto medido

Decisión de adopción: **`DO_NOT_ADOPT`**. Nada de lo medido aquí se adopta: ninguna estrategia, ningún juego de parámetros y ningún cambio de sede sale de este paquete. El criterio de éxito del RFC es una decisión de investigación mejor fundada, y la decisión fundada es no adoptar ninguno de estos brazos.

| Pregunta | Respuesta |
| --- | --- |
| Coste de ida y vuelta | 22.99-24.08 bps |
| Peso de la tarifa en ese coste | 85.9 % del coste de ida y vuelta |
| Mejor movimiento bruto medido | 1.582703 bps |
| Frecuencia de movimientos que cubren la barrera (tape) | 1s: 0.0/día; 5s: 0.0/día; 60s: 48.018/día; 900s: 179.619/día; 3600s: 11.553/día |
| Frecuencia que extrae el selector de desequilibrio medido | 1s: 0.0/día long-only; 5s: 0.0/día long-only; 60s: 144.061/día long-only |
| ¿Una sede más barata lo salva? | no: MEXC_SPOT_TAKER es la más barata con 12.9866 bps, todavía por encima del mejor bruto 1.582703 |
| ¿El libro medido absorbe el tamaño cotizado? | sí para el perpetuo en el tamaño cotizado; el spot se apoya en solo 3 instantáneas |

## 2. Qué se midió de verdad

- 10 streams de la captura forward, 95913 filas de un segundo, 16626886 eventos de cotización y 287946 operaciones.
- 10.14 h de captura forward en el repositorio, con la pérdida declarada por cada manifiesto.
- El flujo de operaciones del perpetuo no existe en este entorno: el stream entregó cero mensajes y la ausencia se declara, no se sustituye.

## 3. Por qué no hay edge

La brecha es aritmética en el reloj corto e informativa en el largo: la barrera es 23-24 bps de ida y vuelta, la tarifa sola son 20 bps, y la mejor señal medida aquí es 1.582703 bps; ni la tarifa más barata registrada (MEXC_SPOT_TAKER) baja la barrera por debajo de ese bruto. A 1 y 5 segundos el propio tape no llega a moverse tanto — el límite superior es cero y ningún selector puede ayudar ahí. A 60 segundos el tape **sí** ofrece movimientos que cubren la barrera, pero el selector medido extrae 1s: 0.0/día long-only; 5s: 0.0/día long-only; 60s: 144.061/día long-only y su bruto sigue siendo 1.582703 bps frente a esa misma barrera: al reloj largo no le falta movimiento, le falta una forma medida de saber cuál es.

## 4. Qué haría falta para la siguiente fase

- una señal con al menos 35 bps brutos en un horizonte que este tape pueda entregar, o
- una sede cuyo ida y vuelta quede por debajo del bruto medido, con tarifa confirmada y no promocional, o
- un producto ejecutable con coste materialmente menor (el spot VIP0 no lo ofrece: maker igual a taker y la puerta maker ya falló).

## 5. Límites declarados

- rentabilidad de ningún libro: la promoción es NONE y no se envía ninguna orden
- nada sobre la liquidez fuera de las horas que cubre la captura forward, que se declaran en el informe
- nada sobre el flujo de operaciones del perpetuo: este entorno entregó cero mensajes aggTrade de perpetuo (SRC-15/SRC-18) y la ausencia se declara, nunca se sustituye
- nada sobre fills maker realizados: ningún mercado de este proyecto tiene un modelo de fill medido
- nada sobre mercados que el runtime excluye (los derivados son información, no producto)
- la captura abarca horas repartidas en unos pocos días, así que una tasa por día es una extrapolación de una muestra corta y se informa siempre con su span
- sin modelo de fill maker, el lado pasivo de cada mercado queda sin puntuar, y ahí es donde tendría que estar una ventaja de coste

`promotion: NONE`, `order_sent: False`, `FALSE_SUCCESS: 0`. No se declara rentabilidad ni preparación para paper o producción.
