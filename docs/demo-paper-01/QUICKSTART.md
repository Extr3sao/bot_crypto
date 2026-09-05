# DEMO-PAPER-01 Quickstart

This demo is **paper-only**. The default provider is a deterministic committed fixture; live trading and private exchange endpoints are disabled.

## Start the deterministic fixture demo

```bash
uv run python -m trading_bot.demo.paper_multi_agent --provider fake --output-dir reports/demo-paper-01
```

The command produces:

- `reports/demo-paper-01/RUN_REPORT.json`
- `reports/demo-paper-01/RUN_REPORT.md`

The fixture intentionally exercises `NO_TRADE`, structured debate, a revised MA-4 selection, a RiskManager rejection, a PaperBroker fill, and reconciliation. It is functional evidence, not profitability evidence.

## Start with the read-only dashboard

```bash
uv run python -m trading_bot.demo.paper_multi_agent --provider fake --dashboard --output-dir reports/demo-paper-01
```

Open the printed URL, normally:

```text
http://127.0.0.1:8765
```

The dashboard exposes only `GET /` and `GET /api/status`. It has no order, risk override, or execution-control endpoint.

## Public market-data paper smoke

This mode is explicit and uses public OHLCV reads only. It fails loudly when the provider or network is unavailable; it never silently falls back to fixtures.

```bash
uv run python -m trading_bot.demo.paper_multi_agent --provider ccxt --assets BTC,ETH,SOL --cycles 1 --output-dir reports/demo-paper-01-public
```

No authenticated credentials are required by the demo path, and execution remains `PaperBroker`.

## Validate independently

```bash
uv run python scripts/validate_demo_paper_01.py --report-dir reports/demo-paper-01
```

## Stop cleanly

- Without `--dashboard`, the bounded fixture command exits on its own.
- With `--dashboard`, press `Enter` in the terminal running the command.
- For a foreground process interrupted during a longer public-data run, use `Ctrl+C`; no live broker is connected.

`DEMO-PAPER-01` is a functional paper demonstration, not a live-trading release or profitability validation.
