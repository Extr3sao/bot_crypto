# WP-051-02C — C-015: generador declarado de phase 2

**Estado**: `FAIL / BLOCKED` (parcialmente resuelto)
**Defecto original** (WP-051-02B, WP02B-DEF-02): las cuatro entradas de
`config/preregistrations/EXP-004A.datasets.json` declaran como generador
`python scripts/exp004a_capture.py --slice …`, pero ese path nunca existió en ninguna ref, y
`generator_code_commit` es el SHA cero en las cuatro.

---

## 1. Lo que se verificó (antes de escribir código)

| Comprobación | Comando | Resultado |
| --- | --- | --- |
| El script declarado no existía en ninguna ref | `git log --all --oneline -- scripts/exp004a_capture.py` | sin commits |
| Ninguna entrada es una captura ya hecha | lectura de `EXP-004A.datasets.json` | 4 entradas `PENDING_CAPTURE`, `raw_sha256`/`normalized_sha256` `null`, `period_start_utc = 2026-10-22T00:00:00Z` |
| No existen datasets phase-2 en disco | `find` sobre `data/` | ningún `EXP-004A-1H-*` ni `EXP-004A-ST6-TAPE*` |
| Productor real de barras | `src/trading_bot/market_data/minute_collector.py` | observa y **append**-ea en `data/forward/edge03/<intervalo>/<ACTIVO>.jsonl` |
| Lector real de esas barras | `scripts/exp004a_verify.py:588` | `data/forward/edge03/{interval}/{asset}.jsonl` |
| Esquema de fila | `src/trading_bot/research/prospective/store.py` | `ts` (apertura, ms), `interval`, `closed`, `fetched_at_ms`; lag = `fetched_at_ms - (ts + intervalo)` |

Conclusión de la investigación: no hubo nunca una captura phase-2 que se presentara como original y
luego se perdiera. Lo que hubo fue una **declaración por adelantado** de una ventana futura, con el
nombre de un generador que nadie escribió. Eso cambia la corrección: no hay que reconstruir datos, hay
que hacer que el comando declarado exista **antes** de que la ventana abra, y negarse a producir
cualquier cosa que el contrato no defina.

## 2. Lo que se implementó

`scripts/exp004a_capture.py` — el comando exacto que la declaración ya cita:

- resuelve `--slice <intervalo>:<ACTIVO>` **contra la propia declaración** (no contra una tabla
  paralela), de modo que un slice no declarado se rechaza;
- lee la serie con `index_series`, es decir **con el mismo parser que usa la admisión**: un fichero
  corrupto, un intervalo mentido o una fila sin `ts`/`fetched_at_ms` abortan el slice;
- selecciona por frontera `period_start_utc <= apertura < period_end_utc` (el instante de cierre de la
  ventana no pertenece a ningún día declarado);
- copia **los bytes originales** de cada línea seleccionada: no re-serializa, no normaliza, no
  descarga;
- **conserva las barras tardías** y las cuenta (`bars_outside_lag_bound`): si el extractor las tirase,
  convertiría «observada tarde» en «ausente» y la aritmética de cobertura admitiría un día que
  RFC-050 §3 exige rechazar;
- escribe un manifiesto con `sha256` del slice, `prefix_bytes`/`prefix_sha256` del origen, digests del
  fichero de declaración y del propio script, y `script_sha256` — sin timestamp, para que re-extraer
  un origen sin cambios produzca bytes idénticos;
- **se niega** a: escribir un slice vacío (exit 3), sobrescribir un dataset existente, incluir barras
  no cerradas, aceptar duplicados o desorden, o producir `st6:tape` (exit 2).

Pruebas: `tests/unit/research/test_exp004a_capture.py`, **20 passed**, incluidas las de rechazo
(ventana vacía = error y no crea directorio, duplicado, desorden, barra no cerrada, línea corrupta
fuera de la ventana, escritura única, manifiesto determinista, CLI con exit 3 y exit 2).

```
$ .venv/Scripts/python.exe scripts/exp004a_capture.py --slice 1h:BTC --dry-run ; echo $?
3
$ .venv/Scripts/python.exe scripts/exp004a_capture.py --slice st6:tape --dry-run ; echo $?
2
```

## 3. Por qué sigue `FAIL / BLOCKED`

1. **`st6:tape` no tiene contrato de slice.** La entrada declara `timeframe: "4h slot, 3 rounds of
   15s"` y `row_count: 2700`, pero ninguna fuente dice qué rondas pertenecen a qué ventana ni cómo se
   tratan huecos o rondas repetidas. Implementarlo habría fijado, unilateralmente, una regla de
   selección dentro del pre-registro. Se rechaza y se documenta.
2. **La declaración sigue con `generator_code_commit` a cero.** No se ha editado
   `config/preregistrations/EXP-004A.datasets.json`: cambiar ese fichero después de haberlo citado en
   la auditoría sería exactamente la «corrección retroactiva de sellos phase-2» que el WP prohíbe. El
   comando declarado ya es ejecutable, pero la procedencia queda formalmente abierta hasta que la
   gobernanza re-emita la declaración citando el commit real.
3. **No se ha generado ningún dataset.** La ventana abre el `2026-10-22T00:00:00Z`; hoy no hay barras
   dentro de ella y el extractor devuelve exit 3. No se han fabricado ficheros de 2160 filas.

## 4. Lo que falta para cerrar C-015

1. **Gobernanza**: re-emitir `EXP-004A.datasets.json` (o un anexo versionado) con
   `generator_code_commit` = commit de `scripts/exp004a_capture.py` y `generator_command` verificado
   por ejecución, antes de que la ventana cierre.
2. **Contrato del tape**: definir por escrito (a) la unidad de ventana, (b) cuántas rondas por ventana
   son obligatorias, (c) cómo se tratan rondas faltantes o duplicadas, (d) qué columnas son
   obligatorias. Solo entonces puede implementarse `st6:tape` con tests.
3. **Primer slice real**: ejecutar `--slice 1h:BTC --slice 1h:ETH --slice 1h:SOL` cuando existan barras
   dentro de la ventana y sellar los manifiestos con el commit vigente.

Nada de esto autoriza a presentar reconstrucciones tardías como capturas prospectivas.
