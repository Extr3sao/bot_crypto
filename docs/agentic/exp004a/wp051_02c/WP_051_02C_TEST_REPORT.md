# WP-051-02C — informe de pruebas

**Run**: `wp051-02c/EXP-004A/2026-10-21`
**Código bajo prueba**: `c280a1fe43743577abf22ba6d86223197e1c858c`
**Python**: 3.11 (`C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe`)
**Host**: Windows, Git Bash

Todos los comandos se ejecutaron desde la raíz del repositorio. Los códigos de salida se capturaron
con `PIPESTATUS[0]`, no con el exit del `tail`.

---

## 1. Pruebas de la corrección (admisión prospectiva)

```
$ .venv/Scripts/python.exe -m pytest tests/unit/research/test_prospective_admission.py \
      tests/unit/research/test_exp004a_capture.py -q
........................................................                 [100%]
56 passed in 2.39s
EXIT=0
```

36 casos de admisión/ledger + 20 del extractor de slices.

### 1.1 Casos adversariales exigidos por el WP

| Requisito del WP | Test | Resultado |
| --- | --- | --- |
| 22/24 puntuales + 2 tardías, cobertura nominal ≥ 90 % → **rechazo por lag** | `test_two_late_bars_reject_a_dense_day_inside_the_coverage_budget` (24 almacenadas, 22 puntuales, `prospective_coverage = 0.916667`, `all_bars_prospective is False`, `DENSE_BUT_BACKFILLED`) | PASS |
| 24/24 puntuales → admitido si el resto de puertas cumple | `test_observed_day_is_admissible` | PASS |
| 22/24 presentes y puntuales → lag pasa, decide la cobertura | `test_missing_bars_are_incomplete_not_backfilled`, `test_ninety_percent_coverage_is_the_threshold` | PASS |
| Cobertura bajo el mínimo con todas puntuales → rechazo por cobertura | `test_missing_bars_are_incomplete_not_backfilled` | PASS |
| Barra exactamente en el límite y una unidad por encima | `test_lag_boundary_is_inclusive` (`0 <= lag <= bound`) | PASS |
| Escala 15m en el día conjunto (1 barra tardía de 96) | `test_one_late_fifteen_minute_bar_rejects_the_joint_day` | PASS |
| Presencia y tardanza no se compensan | `test_presence_and_lateness_are_not_traded_against_each_other` | PASS |
| Barra no cerrada → no es observación | `test_an_unclosed_bar_rejects_the_day_even_when_coverage_is_full`, `test_unclosed_bars_are_not_prospective` | PASS |
| Lag negativo → no es observación | `test_a_negative_lag_is_not_observation` | PASS |
| Duplicado de instante de apertura → fail closed | `test_a_duplicated_bar_makes_the_day_incomplete` | PASS |
| Serie ausente no se omite silenciosamente | `test_a_missing_series_is_not_silently_skipped` | PASS |
| Versión de regla registrada para el sidecar | `test_the_rule_version_is_recorded_for_the_sidecar` (`RFC-050-S3-UNIVERSAL-LAG/V2`) | PASS |

### 1.2 Cobertura por activo / timeframe / día / barra

`scripts/wp051_02c_recalculate.py` reconstruye **248 registros** (234 `1h` + 14 `1h+15m`) desde el
prefijo atestado de cada registro en `data/exp004a/admission_*.jsonl`, no desde agregados previos, y
contrasta el resultado con `classify_day` sobre el store vivo (`runtime_verdict`).

```
$ .venv/Scripts/python.exe scripts/wp051_02c_recalculate.py
{
  "records": 248,
  "changed": 5,
  "changed_days": ["2026-10-15", "2026-10-17", "2026-10-19", "2026-10-20"],
  "changed_before_capture_start": 5,
  "changed_inside_capture_window": 0,
  "runtime_agrees_with_sidecar": true,
  "recorded_admissible_total": 9,
  "corrected_admissible_total": 4
}
EXIT=0
```

- `prefix_digest_ok = true` en las 248 filas: cada prefijo atestado se recomputó y coincide.
- Reproducción independiente de la referencia 1h **5 → 3** y joint **4 → 1**: coincide con WP-051-02B.
  No hay discrepancia que explicar.
- `runtime_agrees_with_sidecar = true`: la implementación corregida y la reconstrucción desde bytes
  crudos dan el mismo veredicto en los 248 registros. Sin este acuerdo el sidecar no se habría
  publicado como corrección.

## 2. No regresión de admisión, PIT, sellos y trazabilidad

```
$ .venv/Scripts/python.exe -m pytest tests/unit/research/test_exp004a_verify_adversarial.py \
      tests/unit/research/test_prereg_gate_two_phase.py \
      tests/unit/research/test_prereg_gate.py \
      tests/unit/research/test_prereg_gate_escape.py -q
89 passed, 1 skipped in 143.85s (0:02:23)
EXIT=0
SKIPPED tests/unit/research/test_prereg_gate.py:591: symlinks unavailable in this environment
```

El único skip es una limitación del entorno (creación de symlinks en Windows sin privilegios), no un
fallo del código bajo prueba.

```
$ timeout 240 .venv/Scripts/python.exe -m pytest tests/unit/research/test_edge03_forward.py -q
33 passed in 207.60s (0:03:27)
EXIT=0
```

Cubre el observador forward y el contrato del store (`index_series`, prefijos, errores de proveedor).

## 3. Inmutabilidad de la evidencia original

```
$ sha256sum data/exp004a/admission_1h.jsonl data/exp004a/admission_1h+15m.jsonl
73f8ba7b5716a725d166578bc7bfb629aefc0f31c306772e7fba5d83dd90c4b2 *data/exp004a/admission_1h.jsonl
1f10efb48f1c1272e9ef3fcf2e95f3d9c5ba5ccf2907d261196e7ee9e7e044d1 *data/exp004a/admission_1h+15m.jsonl
```

Idénticos a `docs/agentic/exp004a/wp051_02c/evidence/pre_change_hashes.txt` (capturados **antes**
de tocar código). Ni el ledger, ni los prefijos, ni `prospective/`, ni `execution_cost/`, ni
`data/exp004a/`, ni los sellos, ni los informes `independent/` se han reescrito. El sidecar es un
fichero nuevo; no sustituye a nada.

## 4. Lint y formato

```
$ .venv/Scripts/python.exe -m ruff check scripts/exp004a_capture.py \
      tests/unit/research/test_exp004a_capture.py src/trading_bot/research/prospective/admission.py
All checks passed!
EXIT=0
```

`ruff format --check` sobre `admission.py` sigue reportando diferencias **preexistentes** en bloques
que este WP no toca (líneas 164, 246, 322); no se reformateó el fichero para no mezclar ruido de
formato con la corrección. Los dos ficheros nuevos sí se formatearon.

## 5. Prueba del comando declarado de phase 2

```
$ .venv/Scripts/python.exe scripts/exp004a_capture.py --slice 1h:BTC --dry-run
EXIT=3
{"ok": false, "error": "no bar of BTC.jsonl opens inside the declared window; an empty slice is not a
 dataset (the capture window may not have started yet)", "slice": "1h:BTC"}

$ .venv/Scripts/python.exe scripts/exp004a_capture.py --slice st6:tape --dry-run
EXIT=2
{"ok": false, "error": "EXP-004A-ST6-TAPE declares timeframe '4h slot, 3 rounds of 15s', which is not
 a bar series; a slice rule for it is not defined by the declaration. Refusing rather than inventing
 one (this is the st6:tape case).", "slice": "st6:tape"}
```

Pruebas del extractor: `20 passed` (selección por frontera `start <= open < end`, bytes verbatim,
ventana vacía = error, duplicado/desorden/no cerrado/corrupto = fail closed, escritura única,
manifiesto determinista, CLI con exit 3/2).

## 6. Limitaciones registradas

1. **`tests/unit/research` completo no terminó en 600 s** y se abortó por timeout del tool. Se
   ejecutaron en su lugar los conjuntos afectados (148 casos) y el observador forward (33). No se
   declara la suite completa como superada.
2. **No hay ejecución prospectiva nueva** posterior al parche: la ventana de captura abre en
   `2026-10-22T00:00:00Z`. Por tanto no se valida ningún periodo de 90 días y `PAPER_VALIDATION`
   sigue sin ser PASS.
3. **`st6:tape`** no tiene contrato de slice definido; el extractor lo rechaza en lugar de fijar una
   regla unilateral (ver `WP_051_02C_C015_VERDICT.md`).
4. La verificación de symlinks con escape de privilegios del host sigue `NOT_EXECUTED/UNPROVEN`.
