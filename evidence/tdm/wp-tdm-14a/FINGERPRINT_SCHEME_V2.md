# FINGERPRINT_SCHEME_V2 — identidad canónica del código ejecutado

**RFC:** RFC-TDM-014A · **WP:** WP-14B · **Corrige:** D-01 (TDM-12/TDM-13)
**Implementación:** [src/trading_bot/research/source_fingerprint.py](../../../../src/trading_bot/research/source_fingerprint.py)
**Tests:** [tests/unit/research/test_source_fingerprint.py](../../../../tests/unit/research/test_source_fingerprint.py)

## 1. Qué cambia y por qué

`v1` (histórico) calculaba `sha256` de **los bytes que el archivo tenía en disco**
después de los filtros de checkout. Dos checkouts del mismo commit con
`core.autocrlf` distinto producían dos identidades para el mismo código: 4.640
bytes LF frente a 4.776 CRLF, **mismo blob de Git** `03fbb1bf…`. Eso es D-01.

`v2` calcula `sha256` de **los bytes del blob de Git** del archivo en el commit que
se está ejecutando. La identidad sigue al contenido que Git almacena, no al
checkout.

## 2. Definición

```text
source_fingerprint = SHA-256( git cat-file blob <source_commit>:<source_relpath> )
```

Sin normalización propia: no se reescriben finales de línea, no se recortan
espacios, no se canonicaliza nada antes de hashear. La única conversión que
interviene es la de Git, porque el hash se toma del objeto que Git ya guardó.

`source_commit` se registra al lado como **procedencia** y queda deliberadamente
**fuera del digest**: contenido idéntico en commits distintos produce la misma
identidad, que es lo que se quiere cuando el código no cambió.

## 3. Campos publicados

| Campo | Tipo | Significado |
| --- | --- | --- |
| `parameter_hash` | string(16) | **Alias de compatibilidad**: `source_fingerprint[:16]`. Conserva el ancho del campo histórico para no romper consumidores de tipo string. |
| `source_fingerprint` | string(64) | Digest canónico completo. |
| `fingerprint_scheme` | `"v2"` \| `"v1"` \| `"not_applicable"` | Qué algoritmo produjo el valor. Sin este campo, un lector no puede saber qué está comparando. |
| `source_relpath` | string | Ruta relativa a la raíz del repositorio, en forma POSIX. |
| `source_commit` | string(40) | Commit del que se leyó el blob. En `v2` es `git rev-parse HEAD`, **no** un literal. |
| `source_blob_oid` | string(40) | OID del blob hasheado. Permite auditar contra el objeto real de Git. |
| `working_tree_clean_verified` | bool | `true` solo si el preflight demostró que el contenido del checkout es el del commit. |

Artefacto que los contiene:
`evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json`, versión
`tdm12-candidate-registry-v2`, con `fingerprint_scheme`, `source_commit`,
`fingerprint_algorithm` y `run_id` en la cabecera del documento.

## 4. Preflight: cuándo se niega a emitir una huella

Fail-closed, con error tipado por causa:

| Condición | Error | Comprobación |
| --- | --- | --- |
| El archivo no está en el commit | `SourceNotCommittedError` | `git cat-file blob <commit>:<path>` |
| El índice difiere del commit (cambio *staged*) | `WorkingTreeDirtyError` | `git diff-index --cached --quiet <commit> -- <path>` |
| El archivo no está rastreado | `WorkingTreeDirtyError` | `git ls-files --error-unmatch` |
| El archivo no existe en el checkout | `WorkingTreeDirtyError` | `Path.is_file()` |
| El contenido difiere del blob | `WorkingTreeDirtyError` | `git hash-object --path=<path> -- <path>` ≠ OID del commit |
| Git no responde | `GitUnavailableError` | `OSError` al invocar |

### 4.1 Por qué `git status` **no** es el oráculo

Medido con git 2.51.1: en un checkout CRLF, `git status --porcelain` responde
` M module.py` de forma persistente (`git update-index --refresh` sale 1) mientras
`git diff HEAD -- module.py` sale 0 y `git hash-object --path=module.py module.py`
devuelve **exactamente** `HEAD:module.py`. El índice tiene la caché de stat sucia;
el contenido es idéntico.

Usar `status` habría producido los dos errores posibles a la vez:

- **falso rechazo** del único checkout que el RFC manda aceptar (la transformación
  de fin de línea que Git reconoce);
- **falsa aceptación** en el caso simétrico, si se hubiera usado al revés.

Por eso el preflight pregunta por contenido, a través de los filtros de Git: «si
confirmaras este archivo ahora, ¿obtendrías el blob que el commit ya guarda?».

## 5. Alcance: lo que la huella protege y lo que no

Protege **exactamente un archivo**: el nombrado en `source_relpath`, en el commit
`source_commit`.

No protege, y no se afirma que proteja:

- los parámetros que la familia lee en tiempo de ejecución (vienen de `config/`);
- sus importaciones transitivas;
- los datos que consume (de eso responde `DATASET_MANIFEST.json` y su SHA-256);
- el resto del repositorio.

El nombre histórico `parameter_hash` inducía a error; por eso el campo nuevo se
llama `source_fingerprint` y `parameter_hash` queda declarado como *alias truncado*,
no como la identidad de los parámetros de la estrategia.

## 6. Compatibilidad

- Un artefacto histórico sin `fingerprint_scheme` se lee como `v1`
  (`read_fingerprint`) y **no se reescribe**.
- `assert_comparable(v1, v2)` lanza `IncompatibleFingerprintScheme`. Un digest de
  checkout y un digest de blob no son dos valores de una misma identidad.
- `verify_fingerprint(v1, …)` se niega a recalcular: `v1` no es re-derivable
  canónicamente.
- El inventario conserva un modo `--fingerprint-scheme v1` que reproduce el
  artefacto publicado **byte a byte** (probado en `v1_compat.json`: 0
  diferencias, CSV idéntico), con el literal histórico `source_commit: 504256ec`
  conservado solo para esa reproducción.

## 7. Ejemplo trabajado (el propio D-01)

| | Checkout LF | Checkout CRLF |
| --- | --- | --- |
| bytes en disco | 4.640 | 4.776 |
| `sha256` del archivo (`v1`) | `9825f38950c5b975…` | `359ba1b773defee8…` |
| blob de Git | `03fbb1bf67939a76…` | `03fbb1bf67939a76…` |
| **`source_fingerprint` (`v2`)** | `sha256(blob)` | `sha256(blob)` — **idéntico** |

## 8. Migración de consumidores

| Consumidor | Cambio |
| --- | --- |
| `scripts/tdm12_inventory.py` | emite `v2` por defecto; `--fingerprint-scheme v1` para reproducir historia; `--out-dir` y `--run-id` para no sobrescribir evidencia publicada |
| `scripts/tdm13_independent_verify.py` | sin cambios: no lee `parameter_hash` como gate |
| `scripts/tdm12_publish.py` | sin cambios: publica el fichero que recibe |
| Lectores futuros | deben leer `fingerprint_scheme` antes de comparar |

## 9. Límite conocido

La huella no dice si el código es *correcto*, solo *cuál* es. Que dos replays
produzcan el mismo `source_fingerprint` demuestra identidad de fuente, no validez
del pipeline.
