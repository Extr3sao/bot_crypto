# Codebase Map

> Mapa vivo de la estructura `src/trading_bot/`. Refrescado por
> `context-engineer` (comando `00-context-scan.md`).

---

## Visión general

```
src/trading_bot/
├── __init__.py            # paquete raíz
├── app.py                 # entrypoint CLI/Rich + scheduler
├── config/                # cargado tipado (Pydantic) desde /config
├── market_data/           # conector CCXT, descarga OHLCV, normalización
├── indicators/            # motor enchufable de indicadores técnicos
├── strategies/            # estrategias; emiten señales, no órdenes
├── scanner/               # escaneo multi-activo + ranking
├── risk/                  # risk manager, sizing, drawdown, kill switch
├── execution/             # órdenes, retries, idempotencia
├── portfolio/             # estado de posiciones, balances, PnL
├── backtesting/           # motor de backtest, walk-forward, métricas
├── paper/                 # paper trading: órdenes simuladas
├── observability/         # logs estructurados, métricas, alertas
├── storage/               # persistencia (SQLite inicial)
└── utils/                 # helpers (time, math, IO, ids)
```

## Por módulo

| Módulo              | Responsabilidad                                              | Agente(s) responsable(s)        |
| ------------------- | ------------------------------------------------------------- | ------------------------------- |
| `app`               | Entrypoint CLI; argparse/Rich; arma scheduler; modos.         | App-level                       |
| `config`            | Cargador Pydantic tipado de YAML; validación; defaults.       | strategy-engineer               |
| `market_data`       | Conector CCXT; OHLCV; validación de pares; sandbox.          | execution-engineer              |
| `indicators`        | Implementación de EMA, RSI, MACD, ATR, BB, VWAP, vol rel., spread, volatilidad, momentum, OB imbalance. | strategy-engineer |
| `strategies`        | Catálogo de estrategias; interfaz `Strategy.generate(snapshot) -> Signal?`. | strategy-engineer       |
| `scanner`           | Loop de escaneo; ranking; filtros de mercado.                 | strategy-engineer + risk-manager|
| `risk`              | Veredicto de señal; sizing; drawdown; kill switch.            | risk-manager                    |
| `execution`         | Órdenes con `client_order_id`; retries; slippage.            | execution-engineer              |
| `portfolio`         | Posiciones; balances; reconciliación.                        | risk-manager + execution-engineer |
| `backtesting`       | Motor determinista; comisiones; slippage; métricas; walk-forward. | backtest-engineer            |
| `paper`             | Órdenes simuladas con comisión y slippage configurables.      | execution-engineer              |
| `observability`     | Logger JSON; métricas Prometheus placeholder; alertas.        | observability-engineer          |
| `storage`           | ORM ligero (SQLAlchemy o `sqlite3`); migraciones mínimas.     | observability-engineer          |
| `utils`             | helpers (timestamps, ids, math).                             | —                               |

## Reglas arquitectónicas (no negociables)

1. **`strategies` no sabe del exchange**, `indicators` ni `execution`.
2. **`execution` no decide tamaño** — eso viene de `risk`.
3. **`risk` no envía órdenes** — solo veredictos.
4. **`market_data` no calcula señales** — solo datos normalizados.
5. **`observability` no muta estado** — solo lo describe.
6. **`config` no contiene secretos** — solo defaults leídos desde `.env` en runtime.

## Estado

Estado actual: **fase 0 (Fundaciones)** — los módulos están como `__init__.py`
vacíos o `pass`. El código real se construye siguiendo `tasks/roadmap.md`.

## Última actualización

Pendiente. Será regenerada por `context-engineer` tras cada PR grande.
