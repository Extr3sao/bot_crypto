# PAPER Dashboard (PHASE UI-01)

Real-time, **read-only** observability dashboard for the paper trading runtime.

```text
PaperOrchestrator / PaperBroker / PaperCycleEngine   (canonical runtime)
        ↓ pass-through observation taps at the composition root
DashboardEventBus → DashboardStore (in-memory read-only projection)
        ↓
PaperDashboardServer (stdlib REST + SSE, 127.0.0.1 only)
        ↓
static browser UI
```

The dashboard cannot create, modify, or cancel trades and is fail-closed outside
`runtime.mode == paper`.

## Start

Run the dedicated runtime and dashboard:

```bash
uv run python scripts/start_paper_dashboard.py --assets BTC,ETH,SOL --provider fake
```

Useful options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--assets BTC,ETH,SOL` | `BTC,ETH,SOL` | Comma-separated PAPER universe |
| `--timeframe 5m` | `5m` | Candle timeframe |
| `--interval 60` | `60` | Seconds between PAPER cycles |
| `--balance 10000` | `10000` | Initial simulated equity |
| `--max-cycles N` | unlimited | Bounded deterministic smoke run |
| `--provider fake\|ccxt` | `fake` | Fake data or read-only market source |
| `--port 8000` | `8000` | Local HTTP port |
| `--observer-only` | off | Serve only a local empty projection |

The existing PAPER entrypoint can also enable the dashboard:

```bash
uv run python scripts/start_paper_trading.py --dashboard --dashboard-port 8000
```

The default URL is `http://127.0.0.1:8000`. The server binds to loopback by
default and does not expose operator credentials, `.env` values, or exchange
secrets.

## Observer-only semantics

`--observer-only` is an alias for `--no-trading`. It starts a new local server
and does **not** attach to another process. The event bus and projection are
in-memory and there is no IPC, persistence, or network observability source in
this phase. Therefore the initial state remains empty (`STOPPED`, zero cycles,
no positions) until this process itself publishes events. To see live PAPER
events, start the full runtime with dashboard enabled in the same process.

## Read-only API

All API routes are GET-only. Non-GET methods return `405 Method Not Allowed`.

```text
GET /api/status
GET /api/portfolio
GET /api/positions
GET /api/trades
GET /api/signals
GET /api/risk-decisions
GET /api/metrics
GET /api/assets
GET /api/strategies
GET /api/events
GET /api/snapshot
GET /health
GET /ws/events       # Server-Sent Events, not a bidirectional WebSocket
```

Events include cycle completion, context/router decisions, signal rejection,
risk acceptance/rejection, position open/close, stop-loss/take-profit exits, and
runtime errors. Event payloads are presentation data only.

## Isolation and transparency

The taps are pass-through decorators installed only in the startup composition
root. They delegate canonical decisions and publish events after the call.
`DashboardEventBus.publish()` and subscriber handling are contained, the store
keeps the last valid projection, SSE disconnects are contained, and the server
runs on a daemon thread. Dashboard failure cannot stop PAPER execution.

The deterministic transparency test compares direct and tapped cycle results
for the same OHLCV history. The dashboard must not change router decisions,
signals, risk outcomes, orders, positions, or PnL. A deterministic fixture may
legitimately produce `NO_TRADE`; a trade is not forced for visualization.

## Security boundary

- Dashboard startup refuses non-PAPER settings.
- The dashboard package has no execution-gateway or live-exchange imports.
- The server has no POST/PUT/PATCH/DELETE action routes.
- Only PAPER components are composed by the launchers.
- The projection is in memory and is not canonical trading state.

Validation commands:

```bash
uv run pytest -q tests/unit/paper_dashboard
uv run ruff check scripts/start_paper_dashboard.py scripts/start_paper_trading.py src/trading_bot/paper_dashboard tests/unit/paper_dashboard
uv run mypy scripts/start_paper_dashboard.py scripts/start_paper_trading.py src/trading_bot/paper_dashboard
```
