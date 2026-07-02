# Roadmap

> Fases del proyecto. Cada fase tiene criterios de salida y dependencias.
> Backlog detallado: `tasks/backlog.md`. Estado del sprint actual:
> `tasks/sprint-001.md`. Decisiones: `tasks/decisions.md`.

---

## Fase 0 — Fundaciones ✅ Completada (2026-07-02)

- Estructura del repo.
- Documentación SDD (`.ai/methodology-hybrid.md`, `.ai/orchestration.md`).
- Configs YAML base.
- BDDS iniciales (`bdd/features/`).
- README, AGENTS, `.env.example`.
- ADR inicial `tasks/decisions.md`.

**Salida**: el repo es ejecutable y arranca en modo `paper` con
configs y BDDs aunque las implementaciones sean stubs.

## Fase 1 — Market data ⏳ En progreso (sprint-001)

- Conector CCXT.
- Descarga OHLCV para los 25 pares y timeframes 1m/3m/5m/15m.
- Normalización y validación.
- Sandbox por defecto.
- Persistencia en `data/`.
- Logs de cada fetch y error.

**Salida**: el bot puede descargar velas y validarlas para los 25
pares en sandbox sin tirar excepciones.

## Fase 2 — Indicadores

- Motor enchufable.
- EMA rápida/lenta, RSI, MACD, ATR, BB, VWAP, vol rel., spread,
  volatilidad reciente, momentum, order book imbalance.
- Property tests con series sintéticas.
- Catálogo sincronizado con `config/indicators.yaml`.

**Salida**: dado un OHLCV, el motor devuelve todos los indicadores
activados sin estado mutable global.

## Fase 3 — Scanner

- Loop por los 25 pares.
- Filtros de volumen/spread/volatilidad.
- Ranking de oportunidades.
- Manejo de errores transitorios sin tirar el loop.

**Salida**: el scanner emite snapshots filtrados para el motor de
estrategias.

## Fase 4 — Estrategias

- Interfaz `Strategy.generate(snapshot) -> Signal | None`.
- 5 estrategias candidatas implementadas en `state=research` o disabled.
- Catálogo sincronizado con `config/strategies.yaml`.
- Tests unitarios de cada una sobre snapshots sintéticos.

**Salida**: el motor de estrategias produce señales explicables y
las registra.

## Fase 5 — Risk manager

- Position sizing.
- Límites diarios (`max_daily_loss_pct`).
- Drawdown (`max_total_drawdown_pct`).
- Kill switch (`kill_switch_enabled=true`).
- Bloqueos (spread, volatilidad, latencia).
- Tests con property tests.

**Salida**: ninguna señal llega a ejecución sin pasar el risk-manager.

## Fase 6 — Backtesting

- Motor determinista.
- Comisiones y slippage.
- Walk-forward.
- Métricas obligatorias (ver `docs/backtesting-methodology.md`).
- Informes Markdown/CSV/JSON.

**Salida**: dado un dataset, una estrategia y config, produce un
informe firmado.

## Fase 7 — Paper trading

- Modo `paper` con sandbox.
- Balance simulado.
- Comisiones y slippage simulados.
- Reporte diario y comparativa con backtest.

**Salida**: una estrategia en `paper` puede operar en vivo contra el
mercado sin enviar órdenes reales.

## Fase 8 — Observabilidad

- Logs estructurados JSON con `request_id`, `signal_id`, etc.
- Métricas Prometheus (placeholder).
- Alertas desactivadas por defecto hasta validación.
- Runbook de incidentes.

**Salida**: cada evento crítico es buscable y toda desviación
queda registrada.

## Fase 9 — Live trading controlado

- Checklist (`docs/live-trading-checklist.md`).
- Validación manual humana.
- Claves API con permisos mínimos.
- Kill switch probado en condiciones reales.
- Release gate completo.

**Salida**: `LIVE_TRADING_ENABLED=true` solo disponible después de
firmar todos los gates.

## Regla de salto

Cada fase tiene una **puerta** que solo se abre si:

1. Las quality gates están verdes (`quality/code-quality.md`,
   `quality/risk-quality-gates.md`).
2. La documentación asociada está actualizada.
3. El equipo firma el "done" de la fase.
