# Roadmap

> Fases del proyecto. Cada fase tiene criterios de salida y dependencias.
> Backlog detallado: `tasks/backlog.md`. Estado del sprint actual:
> `tasks/sprint-002.md`. Decisiones: `tasks/decisions.md`.

---

## Fase 0 - Fundaciones

- Estructura del repo.
- Documentacion SDD (`.ai/methodology-hybrid.md`, `.ai/orchestration.md`).
- Configs YAML base.
- BDDs iniciales (`bdd/features/`).
- README, AGENTS, `.env.example`.
- ADR iniciales.

**Estado**: completada.

## Fase 1 - Market data

- Conector CCXT.
- Descarga OHLCV.
- Normalizacion y validacion.
- Sandbox por defecto.
- Persistencia en `data/`.
- Logs de cada fetch y error.

**Salida**: el bot puede descargar velas y validarlas en sandbox sin tirar excepciones.

**Estado real a 2026-07-04**:
- `TSK-099` (prerrequisito de configuracion) ya esta mergeado en `main`.
- `TSK-008`, `TSK-101` y `TSK-102` tienen implementacion activa en el worktree local, pendiente de PR/merge.
- `TSK-103+` siguen dependiendo de consolidar esa base en `main`.
- Sprint activo: `sprint-002`.

## Fase 2 - Indicadores

- Motor enchufable.
- EMA rapida/lenta, RSI, MACD, ATR, BB, VWAP, vol rel., spread,
  volatilidad reciente, momentum, order book imbalance.
- Property tests con series sinteticas.
- Catalogo sincronizado con `config/indicators.yaml`.

## Fase 3 - Scanner

- Loop por los pares.
- Filtros de volumen/spread/volatilidad.
- Ranking de oportunidades.
- Manejo de errores transitorios sin tirar el loop.

## Fase 4 - Estrategias

- Interfaz `Strategy.generate(snapshot) -> Signal | None`.
- Estrategias candidatas implementadas en `state=research` o disabled.
- Catalogo sincronizado con `config/strategies.yaml`.
- Tests unitarios de cada una sobre snapshots sinteticos.

## Fase 5 - Risk manager

- Position sizing.
- Limites diarios.
- Drawdown.
- Kill switch.
- Bloqueos.
- Tests con property tests.

## Fase 6 - Backtesting

- Motor determinista.
- Comisiones y slippage.
- Walk-forward.
- Metricas obligatorias.
- Informes Markdown/CSV/JSON.

## Fase 7 - Paper trading

- Modo `paper` con sandbox.
- Balance simulado.
- Comisiones y slippage simulados.
- Reporte diario y comparativa con backtest.

## Fase 8 - Observabilidad

- Logs estructurados JSON con `request_id`, `signal_id`, etc.
- Metricas Prometheus.
- Alertas desactivadas por defecto hasta validacion.
- Runbook de incidentes.

## Fase 9 - Live trading controlado

- Checklist de live.
- Validacion manual humana.
- Claves API con permisos minimos.
- Kill switch probado en condiciones reales.
- Release gate completo.

## Regla de salto

Cada fase tiene una puerta que solo se abre si:

1. Las quality gates estan verdes.
2. La documentacion asociada esta actualizada.
3. El equipo firma el `done` de la fase.
