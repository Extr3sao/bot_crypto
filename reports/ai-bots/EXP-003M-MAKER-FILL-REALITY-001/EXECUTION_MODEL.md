# EXECUTION MODEL — EXP-003M

## Mecanismo

- Ancla del límite: reference_price (the bar open the taker paid), same instant as EXP-003L.
- Regla del límite: buy: reference/(1+improvement/1e4); sell: reference*(1+improvement/1e4).
- Mejora: half_spread_bps (per symbol, from the lane's cost model) + offset_bps.
- Cola: queue ahead of us at the limit is unobservable without an L2 feed. It is a declared multiple q of our own order quantity; fill fraction is clamp((aggressor_volume_at_or_through_limit - q*order_qty)/order_qty, 0, 1) measured from placement (decision + latency) to decision + horizon.
- Lado agresor: buy = trades with is_buyer_maker true (seller aggressed) at price <= limit; sell = trades with is_buyer_maker false (buyer aggressed) at price >= limit.
- Parciales: linear: net = fill_fraction * net_of_full_fill, fees included.
- Salidas: unchanged from EXP-003L and from the lane: stop 0.50 %, target 0.75 % off the fill price, stop_first inside a minute, exits adjudicated from the minute after the fill minute.

## Escenarios congelados

| escenario | tipo | cola (x orden) | latencia | horizonte | offset | comisiones |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `F0_touch_full` | `FILL_UPPER_BOUND` | 0.00 | 0 ms | 15 min | 0.00 bp | `spot_vip0_bnb` |
| `F1_tape_base` | `ESTIMATED` | 1.00 | 400 ms | 15 min | 0.00 bp | `spot_vip0_bnb` |
| `F2_tape_pessimistic` | `ESTIMATED` | 4.00 | 2000 ms | 5 min | 2.00 bp | `spot_vip0` |
| `F3_tape_no_queue` | `TAPE_UPPER_BOUND` | 0.00 | 400 ms | 15 min | 0.00 bp | `spot_vip0_bnb` |

Barrido de sensibilidad (misma cinta, mismas salidas, mismas comisiones):

- cola: 0.00, 0.25, 0.50, 1.00, 2.00, 4.00, 10.00, 100.00
- latencia: 0, 400, 2000 ms

## Disponibilidad real de datos

| dato | fuente | estado en el período | uso aquí |
| --- | --- | --- | --- |
| aggTrades spot | `data.binance.vision/data/spot/daily/aggTrades` | disponible todos los días usados | **sí**: es la cinta |
| klines 1 m spot | `data.binance.vision/data/spot/daily/klines` | disponible | **sí**: procedencia y validación cruzada |
| trades spot | `data.binance.vision/data/spot/daily/trades` | disponible (12.8 MiB/día BTCUSDT) | no: `aggTrades` ya contiene precio, cantidad y lado agresor |
| libro L2 spot histórico | — | **no publicado**: el listado de `data/spot/daily/` solo ofrece `aggTrades`, `klines` y `trades` | no existe, no se sintetiza |
| `bookTicker` spot | — | HTTP 404 en el archivo diario | no disponible |
| `bookDepth` USDⓈ-M | `data.binance.vision/data/futures/um/daily/bookDepth` | disponible (profundidad por bandas de porcentaje) | solo calibración: es otro instrumento |

Regla de selección de la cinta: every (symbol, UTC day) that contains at least one pre-registered signal, and inside it every trade in [decision-60 s, decision+16 min] for those signals. No filter on price, side or outcome; missed signals are impossible to hide.

Cómo se comprobó que no hay libro spot (reproducible en una línea cada paso):

```bash
curl -s 'https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/spot/daily/' \
  | grep -o 'data/spot/daily/[a-zA-Z]*/'   # solo aggTrades/, klines/, trades/
curl -sI https://data.binance.vision/data/spot/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2026-06-21.zip  # 404
curl -sI https://data.binance.vision/data/spot/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2026-06-21.zip    # 404
```

**No hay libro de spot.** El archivo público de Binance no publica profundidad spot, y la profundidad de futuros no es el libro de spot: usarla para declarar un fill sería fabricar evidencia. Por eso la cola se declara como múltiplo de nuestra propia orden y se barre, en vez de afirmarse.

## Lo que este modelo no puede ver

- displayed depth at the touch (no spot L2 published).
- our queue position when we join.
- whether a trade at our price actually matched our order.
- cancel/replace traffic that would have moved us up the queue.

Clase de evidencia declarada: `ESTIMATED_FROM_OBSERVED_TRADE_TAPE`.
