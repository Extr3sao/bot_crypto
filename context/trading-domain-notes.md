# Trading Domain Notes

> Lenguaje y supuestos del dominio. Evita ambigüedades.

---

## Términos

- **Scalping**: estrategia de muy corto plazo, profit objetivo pequeño (bps), duración de posición segundos–minutos.
- **Spread**: diferencia entre best bid y best ask.
- **Slippage**: diferencia entre precio esperado al enviar y precio realmente ejecutado.
- **Maker / Taker**: si la orden añade o quita liquidez.
- **VWAP**: volume-weighted average price.
- **ATR**: average true range.
- **Drawdown**: caída desde el peak de equity.
- **Walk-forward**: validación que avanza en el tiempo.
- **Kill switch**: capacidad de detener el bot inmediatamente.
- **Risk-on / Risk-off**: condiciones de mercado (no es un toggle de estrategia).

## Modos del sistema

| Modo         | Descripción                                                                |
| ------------ | -------------------------------------------------------------------------- |
| `research`   | Solo generación de hipótesis, sin órdenes ni paper.                         |
| `backtest`   | Datos históricos. Comisiones y slippage incluidos.                         |
| `paper`      | Órdenes simuladas, contra datos reales del mercado.                        |
| `shadow-live`| Órdenes simuladas + comparación con órdenes equivalentes que se mandarían en real; ayuda a calibrar slippage. |
| `live`       | Órdenes reales. **Bloqueado por defecto.**                                 |

## Supuestos iniciales (a validar)

1. **Capital inicial**: 10 000 USDT en `paper` para todas las pruebas.
2. **Latencia objetivo**: < 200 ms desde señal a orden enviada.
3. **Spread máximo aceptable**: configurable en `risk.yaml`.
4. **Volatilidad extrema**: ATR% > `extreme_atr_pct` → bloqueo.
5. **No se opera en weekends si la volatilidad es errática** (configurable).

## Anti-patrones (a evitar)

- Curve fitting sobre parámetros.
- Sobre-ponderar win rate sin considerar payoff.
- Ignorar colas (peor trade, peor racha).
- "Edge" creíble sin walk-forward.
- Confundir **backtest rentable** con **paper rentable** con **live rentable**.

## Glosario de estados de estrategia

`disabled` → `research` → `paper` → `live_candidate` → `live`.
Una estrategia NO puede saltarse estados. Cada promoción queda en `tasks/decisions.md`.

---

## Estado post-sprint-001 (2026-07-03)

- TSK-099 (configuración tipada con Pydantic v2 + `FlatEnvAliasSource` ADR-0010) cerrado y mergeado a `main` como PR #1.
- TSK-008 (CI baseline, sprint-002 Pri 1) arranca con spec `docs/ci.md`.
- todavia sin trabajo de Fase 1 implementado (TSK-101..105 sigue `blocked-priority-2..7` a TSK-008). Los términos conceptuales arriba siguen siendo guia; los modulos concretos se construiran en sprint-002.
