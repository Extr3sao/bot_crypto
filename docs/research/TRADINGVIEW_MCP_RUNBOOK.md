# TRADINGVIEW MCP RUNBOOK (CAP-002 G0)

One page. No architecture. This is the only handshake the repository cannot do
for itself: the official TradingView MCP server is a tool surface for an LLM
client (ChatGPT / Codex), authenticated interactively with OAuth 2.1. The repo
owns the deterministic shell that consumes the response; it never holds tokens.

## Prerequisite

- A TradingView account with **Essential or above**. A trial does **not** include
  MCP. No API key exists for this server.

## MCP endpoint

```text
https://mcp.tradingview.com/mcp
```

Streamable HTTP MCP. In a Codex terminal:

```bash
codex mcp add tradingview --url https://mcp.tradingview.com/mcp
```

In the ChatGPT / Codex UI: `Settings -> Plugins -> Add -> MCPs -> Add MCP
Server`, name it `TradingView Official MCP Server`, transport Streamable HTTP,
paste the URL, Save, then `Plugins -> MCPs -> Authenticate`.

## Authentication

- **OAuth 2.1 interactive authorization** performed by the human in a browser.
- The client owns the session. Authorization is per user, not per repo.

## Client responsibility

- A ChatGPT/Codex-compatible MCP client is required. The repository is **not** an
  MCP client and must never become one.

## Security

- OAuth credentials and tokens **must not** enter the repository — no token, no
  client secret, no `.env` entry, no committed cache. If a token is ever written
  to disk by the client, it stays outside this working tree.
- Tool calls are read-only. Alerts and watchlist writes are out of scope.

## Success criterion

- A **real TradingView tool response** is obtained (e.g. `get_ohlcv`,
  `get_technicals_rating`, `search_symbols`) and captured as a raw evidence file.
  Only then can `G_TV_CONTEXT` be evaluated against real data.

## Next

- Run **CAP-002 G0**: raw response -> real `MarketSnapshot` -> `G_TV_CONTEXT`
  check -> `MARKET_ANALYST_V1.0` -> sealed real decision #0001.

Until a real response exists, `G_TV_CONTEXT = NOT_VERIFIED` and no RFC is
created.
