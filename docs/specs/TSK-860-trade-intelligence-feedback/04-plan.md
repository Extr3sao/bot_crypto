# TSK-860 - Trade Intelligence Feedback Loop: Architectural Plan (Command 04)

> Plan incremental para implementar retroalimentacion, estructura de
> mercado, imagenes y diagnostico sin comprometer dinero real.

---

## Pre-condiciones

1. Runtime live/paper debe emitir `signal_id` o equivalente.
2. Ordenes y posiciones deben correlacionarse con `order_id` y
   `position_id`.
3. OHLCV debe estar disponible para el simbolo y timeframe principal.
4. Security-reviewer debe validar donde se guardan imagenes y sesiones.

## Fases

### F1. TSK-860.1 - Modelos y store del Trade Journal

- **Objetivo**: crear el contrato persistente antes de tocar trading.
- **Archivos**:
  - `src/trading_bot/trade_journal/types.py`
  - `src/trading_bot/trade_journal/store.py`
  - `tests/unit/trade_journal/`
- **DoD**:
  - Crear, leer y actualizar `TradeCase`.
  - Guardar tesis, zonas, snapshot y outcome.
  - SQLite WAL + migracion idempotente.
- **Gate**:
  - Unit tests store/types verdes.

### F2. TSK-860.2 - Detector de estructura de mercado

- **Objetivo**: detectar zonas tecnicas de forma determinista.
- **Archivos**:
  - `src/trading_bot/market_structure/detector.py`
  - `src/trading_bot/market_structure/types.py`
  - `tests/unit/market_structure/`
- **DoD**:
  - Soporte/resistencia por pivots.
  - Techo/suelo por extremos.
  - Order block basico por vela contraria + impulso ATR.
  - Acumulacion/distribucion por rango estrecho + volumen relativo.
- **Gate**:
  - Tests sinteticos con series conocidas.

### F3. TSK-860.3 - Entry Thesis Builder

- **Objetivo**: guardar por que se entra antes de enviar la orden.
- **Archivos**:
  - `src/trading_bot/trade_journal/thesis.py`
  - integracion minima en `app.py` o execution layer real.
- **DoD**:
  - Cada orden aceptada por riesgo tiene `trade_case_id`.
  - Tesis incluye indicadores, zonas, criterios y conflictos.
  - Si falla la orden, el caso queda como `order_rejected`.
- **Gate**:
  - Test de no-orden-sin-trade-case.

### F4. TSK-860.4 - Chart Snapshot Providers

- **Objetivo**: guardar imagen con niveles y fallback.
- **Archivos**:
  - `src/trading_bot/charting/snapshots.py`
  - `src/trading_bot/charting/local_renderer.py`
  - provider TradingView detras de feature flag.
- **DoD**:
  - Imagen incluye entry/TP/SL/zonas/direccion.
  - TradingView timeout no bloquea orden.
  - Fallback local siempre disponible.
- **Gate**:
  - Tests con provider fake + snapshot local en carpeta temporal.

### F5. TSK-860.5 - Post Trade Evaluator

- **Objetivo**: explicar aciertos/fallos tras cierre.
- **Archivos**:
  - `src/trading_bot/feedback/evaluator.py`
  - `src/trading_bot/feedback/reports.py`
  - `tests/unit/feedback/`
- **DoD**:
  - Calcular PnL neto, R, MFE y MAE.
  - Etiquetar diagnostico.
  - Generar recomendaciones no auto-aplicadas.
- **Gate**:
  - Tests de TP, SL, cierre manual y estructura invalidada.

### F6. TSK-860.6 - Frontend y APIs de revision

- **Objetivo**: que el usuario y agentes revisen casos.
- **Archivos**:
  - endpoint runtime para listar casos.
  - panel frontend de Trade Journal.
- **DoD**:
  - Filtros por simbolo, direccion, zona, outcome y tag.
  - Enlace/preview de snapshot.
  - Export JSON/CSV.
- **Gate**:
  - Smoke frontend + API local.

### F7. TSK-860.7 - BDD, seguridad y live gate

- **Objetivo**: cerrar la metodologia SDD/BDD antes de live.
- **DoD**:
  - Feature BDD creada.
  - ADR si TradingView requiere sesion local.
  - Security review de secretos.
  - Risk review confirma que feedback no auto-modifica riesgo.
- **Gate**:
  - ruff, mypy, pytest, BDD, security checks.

## Orden recomendado

```text
F1 -> F2 -> F3 -> F4 -> F5 -> F6 -> F7
```

F1 y F2 pueden avanzar en paralelo si se mantiene el contrato
`TechnicalZone`. F4 puede empezar con provider fake y local renderer
antes de conectar TradingView.

## Reparto por agentes

| Agente | Responsabilidad |
| --- | --- |
| context-engineer | Actualizar mapas, retrieval-log y ADR links. |
| quant-researcher | Definir zonas, indicadores y diagnostico tecnico. |
| strategy-engineer | Integrar tesis con senales. |
| risk-manager | Decidir como zonas afectan veto/reduccion de riesgo. |
| execution-engineer | Correlacionar `trade_case_id` con orden/posicion. |
| observability-engineer | Store, snapshots, metricas y export. |
| bdd-analyst | Feature Gherkin y step contracts. |
| security-reviewer | Secretos, sesiones TradingView, retencion de imagenes. |
| frontend-engineer | Panel de revision y filtros. |

## Criterio de salida

- Cada operacion tiene expediente completo.
- Cada cierre tiene diagnostico cuantitativo y tecnico.
- Las imagenes se guardan con niveles.
- Los agentes pueden usar historico para proponer mejoras.
- Ninguna mejora se auto-aplica en live sin gate humano.

