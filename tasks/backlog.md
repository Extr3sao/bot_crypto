# Backlog

> Tickets vivos con su estado. Numeración estable.

---

## Estados

- `todo` — identificado pero no asignado.
- `in_progress` — alguien lo está haciendo.
- `in_review` — PR abierto pendiente de review.
- `done` — fusionado y aceptado.
- `blocked` — depende de algo externo o necesita decisión.

## Tickets Fase 0 (fundaciones)

- [x] **TSK-000** Crear estructura de carpetas. (Este scaffolding.)
- [x] **TSK-001** Crear configs YAML base (`config/*.yaml`).
- [x] **TSK-002** Crear `.ai/methodology-hybrid.md` y `.ai/orchestration.md`.
- [x] **TSK-003** Crear 9 agentes en `.ai/agents/`.
- [x] **TSK-004** Crear 12 comandos en `.ai/commands/`.
- [x] **TSK-005** Crear features BDD iniciales en `bdd/features/`.
- [x] **TSK-006** Crear documentación técnica en `docs/`.
- [x] **TSK-007** Crear `pyproject.toml`, `docker-compose.yml`,
  `.env.example`, `.gitignore`.
- [ ] **TSK-008** Baseline de calidad: ruff, mypy, pytest con markers,
  pip-audit, workflow de GitHub Actions. **Est: S**. Bloquea: TSK-099.

## Tickets Fase 1 (market data) — primeros a abordar

> **IMPORTANTE:** por recomendación del thinker (auditoría post-Fase 0),
> implementar **TSK-099 antes que TSK-101**. Sin configuración tipada,
> cualquier conector irá con strings mágicos.

- [ ] **TSK-099** Capa de configuración tipada con **Pydantic v2**
  (`src/trading_bot/config/`). **Est: M**. Depende de: TSK-008.
  - `Settings` raíz (carga `config/runtime.yaml` + `.env`).
  - Modelos para `assets.yaml`, `exchange.yaml`, `risk.yaml`,
    `strategies.yaml`, `indicators.yaml`, `runtime.yaml`.
  - `fail-fast` en el arranque: el bot no debe iniciar con
    configuración inválida.
  - Tests unitarios sobre cada modelo (incluido caso: live=true sin
    `I_UNDERSTAND_THE_RISKS=true`).
- [ ] **TSK-100** Cerrar ADR-0001 (licencia) y ADR-0002 (gestor deps)
  si se decide hacerlo en este sprint. **Est: S**. Depende de: —
- [ ] **TSK-101** Implementar `market_data/exchange_connector.py`
  con interfaz `ExchangeConnector` y adaptador CCXT. **Est: M**.
  Depende de: TSK-099.
- [ ] **TSK-102** Implementar `market_data/ohlcv.py` con `fetch`,
  validación y normalización. **Est: L**. Depende de: TSK-099,
  TSK-101.
- [ ] **TSK-103** Persistencia local de OHLCV en `data/raw/`.
  **Est: M**. Depende de: TSK-099, TSK-102.
- [ ] **TSK-104** Configurar scheduler para descarga on-demand y
  caché. **Est: M**. Depende de: TSK-099, TSK-102.
- [ ] **TSK-105** Tests:
  - [ ] unit: conector contra un CCXT mock. **Est: S**. Depende de: TSK-101.
  - [ ] integration: fetch real desde testnet, lectura de `data/raw/`.
    **Est: M**. Depende de: TSK-101, TSK-103.

## Tickets Fase 2 (indicadores)

- [ ] **TSK-200** Motor de indicadores (interface, registro, caché).
- [ ] **TSK-201** EMA, RSI, MACD, ATR, BB.
- [ ] **TSK-202** VWAP, volume_relative, spread, volatilidad, momentum.
- [ ] **TSK-203** Order book imbalance (detrás de un feature flag).
- [ ] **TSK-204** Property tests sobre series sintéticas.

## Backlog de ideas (no comprometidas)

- Indicadores adicionales (e.g. Hurst, Fractal dimension).
- Estrategias adicionales (orden-flow, market-neutral pairs).
- Dashboard web mínimo.
- Alertas por Telegram.

## Cómo añadir un ticket

1. ID siguiente disponible.
2. Descripción de una frase.
3. Archivos previstos.
4. Tests previstos.
5. Dependencias (qué ticket debe estar `done`).
