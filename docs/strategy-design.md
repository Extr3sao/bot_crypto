# Strategy Design

> Cómo se diseñan, prueban y promueven las estrategias. Cada estrategia
> tiene su ficha en este documento y su código en `src/trading_bot/strategies/`.

---

## 1. Filosofía

1. **Hipótesis ≠ resultado.** Toda estrategia tiene una sección "Hipótesis"
   y otra "Resultados validados". Hasta que la segunda exista, la estrategia
   NO debe pasar de `research`.
2. **Una estrategia no contiene indicadores hardcodeados**. El catálogo de
   indicadores vive en `config/indicators.yaml`.
3. **Las estrategias son configurables** desde `config/strategies.yaml`.
4. **El tamaño de posición NO es parte de la estrategia**. Es del risk-manager.

## 2. Interfaz de estrategia (contrato)

```python
class Strategy(Protocol):
    name: str
    version: str

    def generate(self, snapshot: MarketSnapshot) -> Signal | None: ...
```

- `MarketSnapshot`: estado de mercado OHLCV + indicadores + order book (opcional).
- `Signal`: side (`BUY|SELL`), entry_type (`MARKET|LIMIT`), reason (texto),
  expected_stop_loss (precio), expected_take_profit (precio),
  indicators_used (mapping), strategy (nombre).
- Si devuelve `None`, no hay señal y debe registrarse el motivo.

## 3. Estados de estrategia

`disabled → research → paper → live_candidate → live`.

Una estrategia solo cambia de estado por ADR + paper valido.

| Estado           | Puede recibir ticks? | Puede ejecutar? | Comentario                          |
| ---------------- | -------------------- | --------------- | ----------------------------------- |
| disabled         | No                   | No              | Solo existe el código.              |
| research         | Sí (con data sintética) | No           | Hipótesis y backtests.              |
| paper            | Sí (sandbox)         | No              | Compara vs mercado real.            |
| live_candidate   | Sí                   | No              | Pendiente de release gate.          |
| live             | Sí                   | Sí              | Solo tras todos los gates.          |

## 4. Fichas iniciales

> Las 5 estrategias candidatas están definidas en `config/strategies.yaml`.
> Estado por defecto: `disabled` o `research`. Ninguna se promueve sin gates.

### 4.1 trend_pullback_scalping
- **Hipótesis**: en tendencia micro (EMA9 > EMA21), un pullback a VWAP
  ofrece entrada óptima con profit en 1–2%.
- **Edge supuesto**: comportamiento recurrente de los participantes en
 短期内, pero que puede no existir fuera de un régimen de mercado.
- **Riesgo**: trabajar contra-tendencia con ATR alto puede producir
  stop-out frecuente.
- **Hipótesis inversa**: si BTC pierde VWAP en 5m con volumen, no es
  pullback sino cambio de régimen.
- **Estado actual**: research.
- **Pendiente**: walk-forward de 3 meses antes de paper.

### 4.2 range_reversion_scalping
- **Hipótesis**: en rango lateral (Bollinger estable), los toques a las
  bandas con RSI extremo permiten entradas en reversión.
- **Edge supuesto**: reversión a la media en mercados sin tendencia clara.
- **Riesgo**: en mercado con tendencia, las "reversiones" son trampas.
- **Estado actual**: research.
- **Pendiente**: añadir filtro de régimen (ADX < 25).

### 4.3 breakout_volume_scalping
- **Hipótesis**: las rupturas de rango con volumen relativo alto son entradas
  en momentum.
- **Edge supuesto**: las rupturas con volumen son más durables.
- **Riesgo**: rupturas falsas (fake breakouts) en zonas de baja liquidez.
- **Estado actual**: research.

### 4.4 vwap_reclaim_scalping
- **Hipótesis**: en horario de alta liquidez, reclamar VWAP después de
  una偏离 menor produce un trade corto con edge.
- **Edge supuesto**: los formadores de mercado defienden VWAP.
- **Riesgo**: en horarios de baja liquidez la reclaim es menos fiable.

### 4.5 momentum_microtrend_scalping
- **Hipótesis**: momentum micro + order book imbalance permiten anticipar
  continuación.
- **Riesgo**: requiere feed de order book estable. Desactivada por defecto.

## 5. Métricas mínimas para promoción

Para pasar de `research` → `paper`:
- Walk-forward con métricas mínimas:
  - Profit factor > 1.1 out-of-sample.
  - Expectancy > 0.
  - Max drawdown < 2% del capital.
  - Número de trades > 200.
  - Sharpe aprox. > 0.5.

Para pasar de `paper` → `live_candidate`:
- Mínimo N sesiones (`docs/paper-trading-methodology.md`).
- Win rate y profit factor no degradados más de un X% vs backtest.

Para pasar de `live_candidate` → `live`:
- **Todos los gates** de `11-release-live.md`.

## 6. Anti-patrones

1. **No empezar con una sola estrategia y optimizarla obsesivamente.**
2. **No usar SL/TP fuera de orden con la estrategia.** El SL es la
   primera línea de defensa, no la última.
3. **No mezclar múltiples estrategias en un mismo módulo** — cada una
   aislada y testeable.
4. **No modificar parámetros en producción** salvo ADR.
