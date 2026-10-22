# ABLACION DE MECANISMO - H2 (timing de entrada)

| | |
|---|---|
| experimento | `ABL-EDGE01-H2` |
| pregunta | gross is negative in DEV, VAL and OOS for the intraday breakout, so the loss is not only cost: is the entry LATE relative to the level it breaks? |
| candidato congelado | `edge_intra_01` |
| split / ventana | `intraday` / `DEV` |
| desde / hasta | `2024-10-01T00:00:00+00:00` .. `2025-06-30T00:00:00+00:00` |
| dias | 272.0 |
| escenario | `BASE` |
| HEAD al ejecutar | `ce42ca42c297fe2b6a6594a49b385ed811442666` |
| huella del codigo ejecutado (sha256) | `616a86fa7258fa9efe2faf1d3b333a87722944aef9796bfa228417014c178c5a` |
| params_hash | `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77` |
| regla congelada (sha256) | `d07e6afca08aa9b6a48e81474509dd7b5905279722ab5cbdc16dbc425b67f508` |
| veredicto | **`ENTRY_IS_LATE`** |

H2 no cambia ninguna regla: es un diagnostico sobre las operaciones que el
presupuesto de riesgo del runtime dejo pasar. `distance_atr` mide cuanto mas
arriba del nivel roto se ejecuto la entrada, en unidades de ATR del propio
candidato (el nivel es el que la senal nombra en `hard_invalidation`).

- `near` (rellenos por debajo de <0.25) frente a `far` (el resto).
- 236 of 290 fills land at or past 0.25 ATR above the broken level and their expectancy is -1.8545 USDT per trade against -1.0882 for the fills closer in

## Rellenos por distancia al nivel

| bucket (ATR sobre el nivel) | operaciones | neto | bruto | expectativa | win % | MFE mediana (bps) | MAE mediana (bps) |
|---|---|---|---|---|---|---|---|
| `<0.25` | 54 | -58.76 | 5.47 | -1.09 | 16.67% | 28.25 | 26.85 |
| `0.25-0.5` | 96 | -134.84 | -20.69 | -1.40 | 17.71% | 32.54 | 37.44 |
| `0.5-1` | 112 | -241.75 | -108.68 | -2.16 | 19.64% | 37.03 | 49.41 |
| `>=1` | 28 | -61.08 | -27.81 | -2.18 | 28.57% | 45.51 | 59.65 |

- buckets: `<0.25`, `0.25-0.5`, `0.5-1`, `>=1`; la primera es semiabierta por arriba e incluye cualquier relleno en o por debajo del nivel.
- distancia mediana de entrada: 0.50 ATR sobre el nivel.
- `near`: 54 operaciones, -1.09 USDT por operacion.
- `far`: 236 operaciones, -1.85 USDT por operacion.

## Que significa el veredicto

- **`ENTRY_IS_LATE`** — the majority of the fills happen at least one bucket edge past the level AND the minority that fills closest to the level carries the better expectancy: the edge is being paid away on the way in, so the entry rule has to move earlier (limit at or retest of the level), not the stop and not the cost model

## Artefactos de este experimento

- `ENTRY_TIMING.json` — diagnostico completo, regla congelada y veredicto
- `ENTRY_TIMING_LEVELS.csv` — tabla del join: nivel, ATR y distancia de cada operacion
- `ENTRY_TIMING_TRADES.csv` — operaciones ejecutadas, con su distancia y su bucket
- `ENTRY_TIMING_SIGNALS.csv` — senales del candidato antes de la capa de riesgo
- `ENTRY_TIMING_REFUSALS.csv` — rechazos crudos (origen y motivo)
- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion
- verificado por `scripts/edge01_mechanism_ablation_verify.py --experiment h2` en un proceso aparte

## Limites

- the diagnostic reads the trades the RISK BUDGET let through, not every signal the candidate printed; what the budget removed is the subject of H5
- two trades may share a (asset, signal_bar) key only if the simulator can re-enter on the same bar; the artefacts publish the join so the reader can see whether any were unmatched
- the level is the one the frozen candidate wrote into its own signal: this measures the timing of THIS rule, not of a re-specified breakout
- single DEV window; no historical order book; long side only (spot)
