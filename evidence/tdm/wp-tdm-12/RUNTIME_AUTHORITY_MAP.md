# WP-TDM-12B — RUNTIME AUTHORITY MAP

**Commit:** `504256ec` · **Evidencia:** `.tdm12/triage.json → discovery`, `CANDIDATE_REGISTRY.json`
**Método:** descubrimiento mecánico (glob + AST + parseo de config + ledger de admisión), no memoria.

---

## 1. Entrypoints reales

| Ruta | Papel | ¿Runtime de paper? | SHA (prefijo) |
| --- | --- | --- | --- |
| `scripts/autonomous_paper.py` | runtime autónomo de paper; instancia las seis familias y las filtra por el ledger de admisión | **sí** | ver `CANDIDATE_REGISTRY.json` |
| `scripts/start_paper_trading.py` | arranque de paper; mismo registro de familias | **sí** | idem |
| `src/trading_bot/app.py` | wiring aplicación: scanner → pipeline → risk → execution | no (producción) | idem |
| `scripts/multi_family_backtest.py` | backtest de investigación de las seis familias | no | idem |
| `scripts/rfc010_baseline_replay.py` | replay de baseline (investigación) | no | idem |

El bucle de paper recibe `families={...}` con las seis familias y `strategy_map` derivado del
`AdmissionLedger`; ninguna estrategia entra al runtime sin pasar por ese ledger.

## 2. Qué es ejecutable hoy

`config/strategy_admission.json` contiene **24 entradas** (6 familias × 4 timeframes) y **ninguna** con
`admitted_for_paper = true`:

| Estado | Entradas |
| --- | --- |
| `NO_GROSS_EDGE` | 17 |
| `COST_KILLED` | 7 |
| **Admitidas** | **0** |

`_period`: W1–W7, 2026-03-01 → 2026-09-24. La propia cabecera del ledger declara su regla: ninguna
estrategia se admite sin un artefacto de investigación comprometido que la coloque en `paper_candidates`
con edge bruto positivo medido.

**Consecuencia:** el número de estrategias `RUNTIME_AUTHORITATIVE` — ejecutables de verdad en paper — es
**cero**. El runtime está cableado y es alcanzable, pero la puerta de admisión está cerrada para todas.

## 3. Clasificación de lo que existe

| Clase | Nº | Qué son |
| --- | --- | --- |
| `RUNTIME_AUTHORITATIVE` | **0** | ninguna admitida |
| `RUNTIME_REACHABLE` | **24** | las 6 familias × 4 timeframes: `breakout`, `ema_crossover`, `mean_reversion`, `momentum`, `trend`, `volatility` a 5m/15m/30m/1h |
| `RESEARCH_ONLY` (misma implementación) | 24 | esas celdas son también las que se midieron en TDM-10; la implementación es la misma, el uso es el que cambia |
| `ORPHAN` | **6** | 1 implementación del protocolo `Strategy` sin entrypoint + 5 estrategias declaradas en config sin implementación |
| `TEST_ONLY` | no inventariadas | ver §6 (cobertura declarada) |
| `EXPERIMENTAL` / `LEGACY` / `DEAD_CODE` | **0** | no se encontraron con este criterio |

### 3.1 Implementación del protocolo sin runtime

`trading_bot.strategies.ema_crossover.EmaCrossoverStrategy` implementa `evaluate(candles, indicators,
config)` — el contrato `Strategy`. **Ningún entrypoint del runtime la instancia**: solo la importa
`trading_bot/strategies/__init__.py`, y el runtime de paper usa la *familia* `EmaCrossoverFamily`, que la
envuelve. Clasificación: **`ORPHAN`** (código correcto, sin camino de ejecución).

### 3.2 Estrategias declaradas sin implementación

`config/strategies.yaml` declara cinco estrategias, todas `enabled: false`:

| Nombre | `state` | Implementación |
| --- | --- | --- |
| `trend_pullback_scalping` | research | **ninguna** |
| `range_reversion_scalping` | research | **ninguna** |
| `breakout_volume_scalping` | research | **ninguna** |
| `vwap_reclaim_scalping` | research | **ninguna** |
| `momentum_microtrend_scalping` | disabled | **ninguna** |

Son configuración con indicadores y reglas en prosa, pero sin clase que las ejecute: no entran en el
ranking. Clasificación: **`ORPHAN`** (declaradas, no implementadas). Es el hallazgo de inventario más
útil de este WP: **el catálogo de estrategias del proyecto no coincide con el código que existe.**

## 4. Familias: parámetros congelados y hash

| Familia | Clase | SHA-256 (prefijo) |
| --- | --- | --- |
| `ema_crossover` | `EmaCrossoverFamily` | `78d0625e` |
| `momentum` | `MomentumFamily` | `633a8a7f` |
| `breakout` | `BreakoutFamily` | `9825f389` |
| `trend` | `TrendFamily` | `1d88358c` |
| `mean_reversion` | `MeanReversionFamily` | `07d01911` |
| `volatility` | `VolatilityFamily` | `b1717c10` |

Ningún parámetro se modificó en este WP; el hash del módulo es el `parameter_hash` del registro.

## 5. Modelo de autoridad

```
scanner (datos)  ->  AutonomousPaperRuntime
                        |  families (6, RUNTIME_REACHABLE)
                        |  strategy_map  <- AdmissionLedger  (0 admitidas)
                        v
                   risk manager -> paper broker -> ledger
```

- **Fuente de verdad de admisión:** `config/strategy_admission.json` (no un flag en código).
- **Fuente de verdad de datos:** `data/tdm08`, `data/tdm10` (sellados, 24/24 hashes).
- **Fuente de verdad de coste:** `COST_MODEL_V3` evaluado por ciclo, nunca almacenado.
- **Ninguna** ruta de este mapa se ejecutó con órdenes: `paper_orders = 0`, `live_orders = 0`.

## 6. Cobertura declarada (ACC-04)

**Escaneado:** `src/trading_bot/strategies/*.py` (AST), `src/trading_bot/research/families/*.py`,
`config/strategies.yaml`, `config/strategy_admission.json`, los cinco entrypoints de §1.

**No escaneado, y por qué:** `tests/**` (dobles de test sin relevancia para ejecutabilidad),
`scripts/*` de campañas históricas una a una (se usaron los cinco relevantes), `docs/**` (documentación,
no código), y módulos de `research/` que no son familias (agentes, governance, microstructure).

Por tanto el inventario es **completo dentro de los entrypoints investigados** y **no** se presenta como
exhaustivo del repositorio. Un candidato que viviera solo en un script de campaña no aparecería aquí; se
mitiga porque el runtime solo instancia las seis familias de §4.
