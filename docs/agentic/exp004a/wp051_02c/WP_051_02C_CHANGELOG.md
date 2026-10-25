# WP-051-02C — changelog de la corrección C-004

**Run**: `wp051-02c/EXP-004A/2026-10-21`
**Código bajo prueba**: `c280a1fe43743577abf22ba6d86223197e1c858c` (ancestro de `HEAD` en el momento del run)
**Rama**: `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Deadline contractual**: `2026-10-22T00:00:00Z` — la corrección se ha fijado **antes** del inicio de la
ventana de captura (que empieza exactamente en esa marca), por lo que no hay datos observados bajo la
regla defectuosa dentro de la ventana.

---

## 1. Requerimiento

RFC-050 §3 exige **dos condiciones independientes** para admitir una jornada:

1. **Presencia**: cobertura mínima (90 %) sobre las barras que el calendario del timeframe debería
   contener.
2. **Validez temporal**: **todas** las barras realmente almacenadas que entran en el conjunto
   evaluado están cerradas y dentro de su límite de lag (`fetched_at_ms - (ts + intervalo) <= bound`).

La cobertura decide **ausencias**; el lag decide **tardanzas**. Ninguna de las dos puede compensar a
la otra, y el presupuesto del 90 % no se aplica al predicado de lag.

## 2. Defecto (C-004 / WP02B-DEF-01)

`classify_day` calculaba:

```python
prospective = sum(1 for bar in bars if bar.closed and 0 <= bar.lag_ms <= bound)
```

y admitía la jornada cuando el **agregado** `prospective / expected >= 0.90`. Es decir, aplicaba el
presupuesto de presencia a la condición temporal: un día con 24 barras almacenadas, 22 puntuales y 2
llegadas horas después **pasaba** como `PROSPECTIVELY_OBSERVED`. Eso permitía que una barra
backfilled se contabilizase como observada mientras el total de puntuales siguiera por encima del
umbral.

Impacto medido sobre la evidencia sellada (248 registros, sidecar `WP_051_02C_RECALCULATION.json`):

| Lane | Registros | Admitidos registrados | Admitidos corregidos | Días corregidos |
| --- | --- | --- | --- | --- |
| `1h` | 234 | 5 | 3 | 2026-10-15, 2026-10-17 |
| `1h+15m` | 14 | 4 | 1 | 2026-10-17, 2026-10-19, 2026-10-20 |
| **Total** | **248** | **9** | **4** | **5 registros / 4 días** |

Los cinco registros corregidos caen **antes** de `capture_start` (`2026-10-22T00:00:00Z`):
`changed_inside_capture_window = 0`.

## 3. Cambio acotado

`src/trading_bot/research/prospective/admission.py`:

- nueva propiedad `SeriesDay.all_bars_prospective` = `stored > 0 and prospective == stored`
  (universal sobre las barras almacenadas, no ratio);
- `classify_day` separa las dos condiciones: `dense` (cobertura) y `observed` (universal);
- la duplicación de un instante de apertura continúa fallando cerrado (`INCOMPLETE`), porque dos
  registros para el mismo slot no son dos observaciones;
- `as_dict()` publica `all_bars_prospective` y `duplicate_bars` para que el sidecar pueda auditar la
  decisión sin recalcularla.

No se modificó ningún umbral (`coverage_required = 0.90` sigue siendo el pre-registrado), ni la
definición de lag, ni la frontera inclusiva `0 <= lag <= bound`, ni el tratamiento de barras no
cerradas o con lag negativo, ni las reglas de sellado.

`classify_day` no se aplicó retroactivamente a la evidencia: el ledger, los prefijos atestados y los
ficheros `prospective/` quedan intactos. La reevaluación vive en un sidecar versionado
(`rule_version = RFC-050-S3-UNIVERSAL-LAG/V2`) que conserva `recorded_verdict` y `corrected_verdict`
lado a lado.

## 4. Rationale

- **Universal, no ratio.** «22 de 24 barras puntuales» no es «91,7 % observado»; es un día en el que
  dos barras llegaron tarde. Un ratio sobre el lag convierte una violación puntual en un promedio y
  hace que el tamaño del día decida la admisión.
- **Dos condiciones, dos contadores.** Mantener `stored`/`prospective` por serie permite que el
  sidecar explique *por qué* una jornada cambió de veredicto (2 barras tardías con lag de 3 h 56 min
  frente a un bound de 2 h) en lugar de publicar solo el cambio de etiqueta.
- **Sin re-sellado.** Reescribir el ledger habría convertido una corrección en una pérdida de la
  traza de que la regla anterior existió. El sidecar conserva ambas lecturas y el commit del runtime.

## 5. Ficheros

| Fichero | Cambio |
| --- | --- |
| `src/trading_bot/research/prospective/admission.py` | universal de lag + campos de auditoría |
| `tests/unit/research/test_prospective_admission.py` | 7 casos adversariales nuevos (2 barras tardías, 1 barra 15m tardía en el día conjunto, presencia vs tardanza, barra no cerrada, lag negativo, duplicado, versión de regla) |
| `scripts/wp051_02c_recalculate.py` | reconstrucción por prefijo atestado desde bytes crudos, sin mutar evidencia |
| `docs/agentic/exp004a/wp051_02c/WP_051_02C_RECALCULATION.json` | sidecar `recorded`/`corrected`/`runtime` por lane, día y serie |

## 6. Lo que este WP **no** hace

- No declara `PAPER_VALIDATION=PASS`: no existe una nueva ejecución prospectiva posterior al parche.
- No modifica `config/preregistrations/EXP-004A.json`, ni `EXP-004A.datasets.json`, ni el umbral.
- No re-sella días, no reescribe `data/exp004a/admission_*.jsonl`, no toca `data/st6/`.
- No promueve nada: `NO_PROMOTION`, cero órdenes, cero cambios de riesgo o capital.
