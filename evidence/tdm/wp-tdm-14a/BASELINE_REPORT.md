# BASELINE_REPORT — RFC-TDM-014A (WP-14A)

**run_id:** `tdm14a-baseline-manual`
**Generado:** ver `generated_at_utc` en [BASELINE_REPORT.json](BASELINE_REPORT.json)
**Autoridad:** runtime ejecutado > evidencia de ejecución > tests > código > RFC > suposiciones.

Todo lo de este informe se re-derivó de Git y de los bytes en disco mediante
[scripts/tdm14a_baseline.py](../../../scripts/tdm14a_baseline.py). Lo que TDM-13 publicó
y este WP no reejecutó queda etiquetado `REPORTED_NOT_VERIFIED`.

## 1. Baseline y linaje

| Hecho | Valor medido | Estado |
| --- | --- | --- |
| `04fb8bc8` existe | sí, tipo `commit` | PASS |
| SHA completo | `04fb8bc8a0900c278cd72c5e3478a45b66fcbc03` | PASS |
| Asunto | *Carry commands and duration in the verification result* | — |
| Padre inmediato | `d7819188cf9c8cb6257bc99e82a828bbe6d6c746` (= el declarado) | PASS |
| Ramas que lo contienen | `evidence/tdm13` (y `fix/tdm14a`, creada desde él) | PASS |
| Árbol | ver `baseline.tree` en el JSON | — |

La baseline declarada por el RFC coincide, así que el preflight no se bloquea. No se eligió
otro commit ni se "arregló" la discrepancia: no hubo discrepancia.

## 2. Aislamiento

- Worktree nuevo `ff-wt-tdm14a`, rama `fix/tdm14a`, creada con
  `git worktree add -b fix/tdm14a <path> 04fb8bc8`.
- Checkout compartido `bot freebuff` en `e67194e7` (rama `main`), **intacto**: 62 entradas de
  `git status`, de las cuales **17 son modificaciones rastreadas ajenas** y 45 son directorios
  sin seguimiento. Huella SHA-256 del `status` ordenado registrada antes y después del trabajo.
- Evidencias `wp-tdm-11`, `wp-tdm-12` y `wp-tdm-13` son de solo lectura para este RFC.

## 3. Entorno y configuración EOL

| Elemento | Valor |
| --- | --- |
| Python | 3.11.15 (venv del checkout compartido) |
| Git | 2.51.1.windows.1 |
| Plataforma | Windows 10.0.26200 |
| `core.autocrlf` en el worktree | `false` |
| `.gitattributes` con reglas que cubran `src/**` o `scripts/**` | no |

Consecuencia medida, no supuesta: sin regla de atributos, los bytes físicos de un módulo
Python dependen solo de `core.autocrlf`, que es exactamente el terreno donde vive D-01.

## 4. D-01 reproducido (ACC-02)

Dos checkouts reales del **mismo commit** `04fb8bc8`, el mismo módulo
`src/trading_bot/research/families/breakout_family.py`:

| | LF (`core.autocrlf=false`) | CRLF (`core.autocrlf=true`) |
| --- | --- | --- |
| bytes en disco | 4.640 | 4.776 |
| finales `\r\n` | 0 | 136 |
| `sha256` del archivo | `9825f38950c5b975…` | `359ba1b773defee8…` |
| **huella v1 publicada** (`parameter_hash`) | `9825f38950c5b975` | `359ba1b773defee8` |
| blob de Git (`rev-parse 04fb8bc8:<path>`) | `03fbb1bf67939a76c942e4adb5b9e7e411f6b0b1` | **idéntico** |
| `git hash-object` del archivo | `03fbb1bf…` | `03fbb1bf…` |
| `git status --porcelain <path>` | limpio | **limpio** |

Es decir: mismo contenido lógico, mismo blob, mismo `git` que considera limpio el checkout,
y **dos `parameter_hash` distintos**. Los valores coinciden dígito a dígito con los que
TDM-13 registró en `EOL_FINGERPRINT_FINDING.json`, pero aquí se regeneraron desde cero; no se
copiaron del informe anterior.

La tolerancia que el RFC permite es exactamente la que Git reconoce: diferencia física que
Git mapea de vuelta al mismo blob. Cualquier otra diferencia es contenido distinto.

## 5. Entradas selladas (ACC-05, base)

- Manifiesto de TDM-13: 26 datasets, 10.310.475 bytes.
- Medido ahora: 26 archivos, 10.310.475 bytes, **26/26 SHA-256 coinciden** con el bundle.
- Reparto: 13 HOLD (`data/tdm08`) + 13 DEV (`data/tdm10`), ambos manifiestos incluidos.
- Estado: `AVAILABLE`.

`data/tdm08` y `data/tdm10` **no están en Git** (0 archivos rastreados): el replay debe
restaurarlos desde el bundle sellado antes de ejecutar, y esa restauración se verifica por hash.

## 6. Entrypoints y contratos

Producidos/consumidos localizados por lectura de código, con digest del blob de HEAD:

| Ruta | Rol |
| --- | --- |
| `scripts/tdm12_review.py` | review PIT: ledger, dependencia, controles |
| `scripts/tdm12_inventory.py` | **aquí vive D-01** (`family_classes` → `sha(module.__file__)`) |
| `scripts/tdm13_inputs.py` | sellar/verificar/restaurar los 26 inputs |
| `scripts/tdm13_replay.py` | replay de un solo intento (pre-014A) |
| `scripts/tdm13_independent_verify.py` | verificador independiente de TDM-13 |
| `scripts/tdm13_negative_controls.py` | controles negativos de TDM-13 |
| `scripts/tdm13_report.py` | redacción de RUN_REPORT/verification_result |

Productores y consumidores de los dos contratos que el RFC nombra:

- **`parameter_hash`** — producido en `tdm12_inventory.py::family_classes` y ensamblado en
  `main()`. Consumido por el verificador de TDM-13 (recuentos y re-derivación), por
  `tdm12_publish.py` y por el esquema documentado en `RFC-TDM-012.md`. **No gobierna ninguna
  métrica, gate ni veredicto**: es identidad, y por eso D-01 no cambió el dictamen de mercado.
- **`REPLAY_REPORT.json`** — producido por `tdm13_replay.py`; consumido por el verificador y
  por el redactor de informes como insumo del veredicto.

## 7. Resultados previos (heredados, no reejecutados)

Etiqueta: `REPORTED_NOT_VERIFIED`.

- Veredicto TDM-13: `VERIFIED_REPRODUCIBLE`, con `D-01` abierto y con el segundo intento del
  replay reutilizando `review.json` y métricas por celda del primero.
- Tiempos declarados por fase: review ≈ 262 s, inventory ≈ 454 s sin caché.

Estos tiempos se usarán solo como presupuesto inicial de timeout; los definitivos son los
medidos en WP-14C.

## 8. Mapa de alcance declarado antes de editar

**Modificar**

- `scripts/tdm12_inventory.py` — esquema de huella versionado (`v1` compatibilidad, `v2`
  canónico), `--out-dir`, `--run-id`, procedencia real en lugar del literal `504256ec`.

**Añadir**

- `src/trading_bot/research/source_fingerprint.py` — huella canónica de blob, preflight
  fail-closed, adaptador de lectura v1.
- `scripts/tdm14a_baseline.py`, `scripts/tdm14a_replay.py`, `scripts/tdm14a_verify.py`,
  `scripts/tdm14a_negative_controls.py`.
- `tests/unit/research/test_source_fingerprint.py`,
  `tests/unit/research/test_tdm14a_replay_contract.py`.
- `evidence/tdm/wp-tdm-14a/**`.

**Nunca tocar**

- Evidencias `wp-tdm-11/12/13`, rutas de trading en producción, checkout compartido.

**Rutas de trading modificadas:** `[]` (vacío, y se re-verificará en el cierre).

## 9. Defecto adicional detectado en la auditoría (D-02)

`tdm12_inventory.py` escribe `"source_commit": "504256ec"` como **literal en el código**, no
como procedencia del ejecutable. Ningún artefacto de TDM-12 registra en qué commit corrió de
verdad. No se corrige retroactivamente (la evidencia histórica es inmutable); el esquema v2
lo sustituye por `git rev-parse HEAD` medido en el preflight, y el modo `v1` conserva el
literal solo para reproducir el artefacto publicado, declarándolo como tal.

## 10. Veredicto WP-14A

`PASS` — 7/7 comprobaciones de baseline, D-01 `REPRODUCED`, 26/26 inputs disponibles,
checkout compartido intacto. Se autoriza promover a WP-14B.
