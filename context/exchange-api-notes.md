# Exchange API Notes

> Notas sobre los exchanges soportados y peculiaridades operativas.

---

## Default: Binance (recomendado vía CCXT)

### Sandbox / Testnet
- Binance expone `https://testnet.binance.vision` mediante `ccxt.binance({...sandbox: true})`.
- Activos y liquidez pueden diferir del real. No usar para validar fills en producción.

### Endpoints relevantes
- `fetchOHLCV(symbol, timeframe, since, limit)`: histórico por velas.
- `fetchOrderBook(symbol, limit)`: top of book + profundidad.
- `fetchTicker(symbol)`: best bid/ask y 24h stats.
- `createOrder(...)`: spot market/limit; firm keys para órdenes reales.
- `fetchBalance()` y `fetchPositions()` para reconciliación.

### Limitaciones conocidas
- Rate limit por IP y por API key — respetar (`exchange.rate_limit_ms`).
- Streams públicos y privados con claves separadas.
- Algunos símbolos cambian de nombre en maintenance.

### Permisos recomendados de la API key
- Habilitar `Enable Trading`.
- **Deshabilitar** `Enable Withdrawals`.
- IP whitelist (recomendado).
- Restringir a símbolos operables.

## Otros exchanges soportados por CCXT

Kraken, Coinbase Pro (Advanced Trade), Bitfinex, Bybit, OKX, Bitstamp.

> Cada exchange nuevo debe pasar por `03-specify.md` antes de añadirse al YAML.

## Convenciones

- `client_order_id` propio: `<prefix>-<uuid>` para idempotencia.
- Símbolos siempre en formato CCXT (`BTC/USDT`).
- Timeframes CCXT: `1m`, `3m`, `5m`, `15m`, `1h`, `4h`, `1d`.

## Pendiente

- Documentar quirks de cada exchange añadido con ticket dedicado.
- Definir cómo manejar pares suspendidos / en mantenimiento.
