# Backtesting Methodology

> Cómo se hacen backtests correctamente en este proyecto. Sin esto, el
> resto es teatro cuantitativo.

---

## 1. Principios

1. **Mismo input → misma salida (determinismo).**
2. **Walk-forward siempre.** Train y test separados.
3. **Comisiones y slippage incluidos.** Sin ellos, todo "edge" es ficticio.
4. **Out-of-sample real.** Nunca entrenar y validar sobre lo mismo.
5. **Métricas exigidas**: ver sección 4.

## 2. Data

- Origen: CCXT cuando esté disponible; alternativamente CSV en `data/raw/`.
- Timeframes: 1m, 3m, 5m, 15m por defecto.
- Mínimo recomendado: 6 meses para timeframes cortos.
- Validación de integridad: detectar gaps y velas duplicadas.

## 3. Sesgos a evitar

- **Lookahead bias**: usar solo información con timestamp <= `t`.
- **Survivorship bias**: incluir pares delistados.
- **Selection bias**: no elegir el par después de saber el resultado.
- **Optimización sobre test**: separar train y test.
- **Reuso de la misma ventana para muchos parámetros**.

## 4. Métricas exigidas en `reports/backtests/<...>.md`

| Métrica                 | Por qué                                                         |
| ----------------------- | --------------------------------------------------------------- |
| Win rate                | % de operaciones ganadoras.                                     |
| Profit factor           | Suma ganancias / suma pérdidas.                                 |
| Expectancy              | Promedio de PnL por trade.                                       |
| Max drawdown            | Peor caída peak-to-trough.                                      |
| Sharpe aprox.           | Retorno medio / desv. estándar.                                  |
| Sortino aprox.          | Retorno medio / desv. estándar de pérdidas.                      |
| Nº trades               | Tamaño muestral.                                                 |
| Tiempo medio en op.     | Liquidez operativa.                                              |
| Mejor trade             | Cola derecha.                                                    |
| Peor trade              | Cola izquierda — fundamental.                                   |
| Racha máx pérdidas      | Resiliencia psicológica y de capital.                           |
| Ratio beneficio/riesgo  | Avg win / avg loss.                                             |
| Coste total comisiones  | Cuánto se "comieron" las comisiones en PnL.                     |
| Slippage estimado       | Impacto de slippage en PnL.                                     |

## 5. Walk-forward

- Datos divididos en N ventanas.
- Train en T‑k .. T‑k+h; test en T .. T+h.
- Avanzar la ventana k.
- Reportar métricas agregadas y por ventana.
- No se acepta una métrica global que esconda degradación.

## 6. Análisis de sensibilidad

- Hacer variar los parámetros ±20% y reportar métricas.
- Si la estrategia solo "gana" con un valor puntual, sospecha de overfitting.

## 7. Validación cruzada con `quant-researcher`

`backtest-engineer` firma el informe. `quant-researcher` revisa:
- Métricas.
- Walk-forward.
- Hipótesis válidas y falsables.
- Comparación con literatura estándar.

## 8. Plantilla del informe

`reports/backtests/<estrategia>-<symbol>-<YYYY-MM-DD>.md`:

1. Resumen.
2. Data y configuración.
3. Métricas.
4. Walk-forward.
5. Análisis de sensibilidad.
6. Lista de trades (CSV/JSON).
7. Riesgos detectados.
8. Aprobación de `quant-researcher` + `risk-manager`.
