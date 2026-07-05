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
| `config`            | Cargador Pydantic tipado de YAML; validación; defaults; `FlatEnvAliasSource` (ADR-0010). | strategy-engineer               |
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

Estado actual: **fase 1 (Market data) en transición**. La mayoría de los
módulos siguen como `__init__.py` vacíos o `pass`. Lo entregado en
sprint-001 (cerrado vía ADR-0011):

- `src/trading_bot/config/` (M = 38 tests verdes, cobertura 95.03%):
  `Settings`, `Exchange`, `Risk`, `Runtime`, `StrategiesConfig`,
  `IndicatorsConfig`, `Universe` + `FlatEnvAliasSource` custom source.
- `tests/unit/config/` con 10 nuevos regression tests del flat-env
  alias contract (ADR-0010 firmada).

Pendiente para sprint-002: TSK-008 (CI baseline, Pri 1) + TSK-101..105
(canal de ingesta Fase 1) + TSK-110 (BDD market_scanner) como
secundario.

## Cambios recientes

- **TSK-099 cerrado** vía PR
  [#1](https://github.com/Extr3sao/bot_crypto/pull/1) squash-merge a
  `main` (cabecera merged-commit apuntada por `git log -1 origin/main`).
- **ADR-0010 firmada**: `FlatEnvAliasSource` flat-env → nested-path en
  `src/trading_bot/config/settings.py`. Cubre `TRADING_MODE`,
  `LIVE_TRADING_ENABLED`, `I_UNDERSTAND_THE_RISKS`, `EXCHANGE_ID`,
  `EXCHANGE_SANDBOX`, `LOG_LEVEL`/`LOG_FORMAT`/`LOG_TO_FILE`/
  `LOG_FILE_PATH`, `DATABASE_URL`, `SCHEDULER_TIMEZONE`,
  `ACTIVE_HOURS_START/END`.
- **ADR-0011 firmada** (cierre de sprint-001 con excepción: TSK-008
  arrastrado a sprint-002 como Pri 1).
- **sprint-001 cerrado** formalmente; **sprint-002 abierto** con
  7 tickets en scope, columna `Pri` para ordenar ejecución.

## Última actualización

2026-07-03 — context-engineer tras cierre de sprint-001 y arranque de
sprint-002 vía ADR-0011. Próximo refresh esperado post-TSK-008 (CI
baseline que anclará `Python 3.11` + `coverage 90%`).
