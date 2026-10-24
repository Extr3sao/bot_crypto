# RUN_REPORT — WP-EDGE04-RECOVERY-15M

Árbol: `C:\Users\GVLLFR0035\Downloads\exp004a-recovery-02k`
Rama: `recovery/exp004a-02k-9983b050`
Modo: **PAPER/OFFLINE ONLY**. Sólo lectura de datos públicos de mercado. Ninguna orden, ningún
límite de riesgo tocado, ninguna credencial leída.

## 1. Ejecución, en orden

| # | Comando | Salida | Qué estableció |
|---|---|---|---|
| 1 | `git rev-list --all` + `git ls-tree -r` filtrando `data/raw/alpha003/price` | 0 objetos | los shards nunca estuvieron versionados |
| 2 | `git rev-list --objects --all \| grep _15m.json` | 1 (mi propio informe) | ningún blob del corpus en el historial |
| 3 | `git lfs ls-files` / `.gitattributes` | vacío / sin `filter=lfs` | LFS no guardó nada |
| 4 | `git fsck --lost-found` | 155 blobs huérfanos, mayor 3,58 MB | ni siquiera un blob suelto del tamaño de un shard (≈4,5 MB) |
| 5 | `find ~ -name "*_15m.json"` | 15 nombres compatibles | todos de ALPHA-002 (ratios), ninguno sirve |
| 6 | `find /g …` | 0 | la unidad `G:` tampoco tiene |
| 7 | papelera `C:\$Recycle.Bin` | 12 archivos, 41 entradas ilegibles | nada del corpus |
| 8 | `python scripts/edge04_15m_audit.py --out …/raw/SOURCE_AUDIT.json` | **exit 1** (`NO_BYTE_IDENTICAL_COPY_FOUND`) | 136.888 archivos barridos, 15 hasheados, 0 coincidencias |
| 9 | `python scripts/edge04_15m_refetch.py --out .tmp15m/candidates --control-5m` | **exit 0** | replay del productor: estructura exacta, bytes distintos |
| 10 | `python scripts/edge03_verify.py --json-out …` | **exit 1** | aborta en `check_frozen_corpus` con `FileNotFoundError` |
| 11 | `python scripts/edge04_verify.py --state-root data/forward/edge04r01 --json-out …` | **exit 1**, `VERIFY_FAIL` 7/15 | los 8 fallos son de «ningún slot consumido» |
| 12 | `schtasks //query //tn TradingAgentic-EDGE04-Forward //xml` | `<Enabled>false</Enabled>` | la tarea sigue aparcada, con el lanzador correcto |
| 13 | `python scripts/edge04_15m_verify.py … --out …/VERIFIER.json` | **exit 0**, `EVIDENCE_CONSISTENT_WITH_BLOCKED` 13/13 | el par builder≠verifier sobre las pruebas 8–12 |

## 2. El replay, con sus números

`scripts/edge04_15m_refetch.py` reproduce el productor `scripts/alpha003_run.py` sin tocar el
experimento: mismo endpoint (`ccxt.binanceusdm`), mismo `since` (`2024-10-01T00:00:00Z`), misma
paginación (`last_ts + 1`, corta en lote incompleto), mismo serializador (`json.dumps(rows)`,
separadores por defecto).

```
BTC 15m: 70703 rows <= cut, 4497889 bytes (recorded 4497888), sha match=False
ETH 15m: 70703 rows <= cut, 4466467 bytes (recorded 4466466), sha match=False
SOL 15m: 70703 rows <= cut, 4095008 bytes (recorded None), sha match=False
control 5m: 212109 rows, 13389298 bytes (recorded 13389298, delta 0)
```

El corte del control a las 11:40 está **ajustado** y se declara como tal: el tamaño registrado
excede en 124 bytes (dos filas de 62) al corte de las 11:30, lo que fija la última fila del
archivo original en la barra de las 11:40. Con ese corte el tamaño sale exacto y el hash sigue
difiriendo — que es justo lo que se quería medir: la receta es fiel, los valores no.

## 3. Gate y no-sustitución

```
assert_frozen_corpus()  →  FileNotFoundError: …\data\raw\alpha003\price\BTCUSDT_15m.json
rehearsal (root aislado) →  AssertionError: the frozen 15m corpus for BTC changed:
                            shard digest is b21d66e3aa2292ea, the frozen value is cd1d2ea256a97f7c
```

La prueba de sustitución copia los shards recién descargados a un directorio temporal y parchea
`edge01.data.CORPUS_15M` **en ese proceso**; `data/` no se toca en ningún momento. Si alguien
«recuperase» el corpus escribiendo el shard descargado, este test lo caza.

## 4. Qué no se ejecutó, y por qué

- **Tick forward**: no se lanzó. El criterio 3 del WP exige que el pin pase antes; forzar el
  tick sólo produciría otra fila de fallo y una falsa señal de actividad.
- **Habilitar la tarea**: no se hizo. Requiere corpus exacto (paso 7 del WP).
- **Re-congelar**: prohibido por el WP y por la RFC; no se ha tocado ningún umbral ni hash.

## 5. Lint, tests y alcance del cambio

- `ruff check scripts/edge04_15m_*.py` → **All checks passed** (`exit 0`). El árbol no exige
  `ruff format` en `scripts/` (los verificadores existentes tampoco lo cumplen), así que no se
  reformatea lo ajeno.
- No se añadieron ni modificaron tests unitarios: el WP no toca `src/`, y los tres scripts son
  herramientas de diagnóstico cuyo contrato es el verificador independiente, no un mock.
- No se modificó ni una línea del experimento congelado: `git diff --stat` de este WP son sólo
  tres scripts nuevos y esta carpeta.

## 6. Trazabilidad

HEAD al ejecutar: `688c5805`. El commit de entrega es el que introduce
`docs/agentic/exp004a/wp_edge04_15m/` (un informe no puede nombrar su propio commit: eso lo
haría distinto de lo que describe; `git log --oneline -- docs/agentic/exp004a/wp_edge04_15m`
lo resuelve sin circularidad).

| Script | sha256 (16) |
|---|---|
| `scripts/edge04_15m_audit.py` | `4cdb39e125f19802` |
| `scripts/edge04_15m_refetch.py` | `257a23e6b62a82b8` |
| `scripts/edge04_15m_verify.py` | `98c5ac4c8da4e06e` |

Candidatos descargados: `.tmp15m/candidates/` (51 MB, **sin seguimiento**), nunca en `data/raw`.
