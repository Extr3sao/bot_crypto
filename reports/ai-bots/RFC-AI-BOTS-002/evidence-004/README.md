# EVIDENCE-004 — un solo número, derivado de la evidencia

Este paquete existe por un defecto concreto y repetido: cuatro informes del RFC
AI-BOTS-002 contaban lo mismo de cuatro maneras, y una de ellas llamaba «éxito» a una
operación que REA **rechazó** porque el `exit_code` era 0.

```text
logs crudos (nunca se escriben)
        │
        ▼
evidence004_ledger.py     clasifica cada operación: execution_class != exit_code
        │
        ▼
CANONICAL_RUN.json        un objeto, dos ámbitos separados, claims renderizados
        │
        ├── derived/<ledger>.<contenido>/RUN_REPORT.json / RUN_REPORT.md
        ├── derived/<ledger>.<contenido>/INFORME_EJECUTIVO_NUMEROS.md / CLAIMS.md
        └── bloques numéricos en FINAL_REPORT.md e INFORME_EJECUTIVO.md

evidence004_verify.py     relee los logs por su cuenta, sin importar nada del builder
```

## Reglas que el paquete hace cumplir

1. **El código de salida no es el resultado.** `compare-source-to-bundle` sale con 0 y
   devuelve `NOT_EXECUTED_INVALID_INPUT`: cuenta como *no ejecutada*.
2. **Evidencia declarada ≠ evidencia comprobada.** Un `evidence_id` en un log no prueba
   nada por sí solo; sólo es `EVIDENCE_ARTIFACT_VERIFIED` si existe un fichero en el
   dossier cuyo sha256 coincide con el digest declarado.
3. **Dos ámbitos, dos denominadores.** `phase_v31` (trabajo de esta iteración) y
   `all_dossiers` (todo lo registrado) no se suman ni se sustituyen.
4. **Lo histórico no se borra: se sella.** Los informes antiguos se conservan con su
   huella de contenido en `SUPERSESSION_MANIFEST.json`. Editarlos para que cuadren sería
   lavar el defecto en lugar de registrarlo.
5. **Un claim sin fuente no se publica.** `CLAIMS.json` ata cada frase numérica a un
   contador o a un `evidence_id`; si no resuelve, el generador se niega a escribir.
6. **Un solo escritor, publicación transaccional.** Proyección candidata completa →
   relectura y re-hash → cambio de `CURRENT_MANIFEST.json` como único punto de
   conmutación. La proyección anterior se registra en `SUPERSEDED_PROJECTIONS.json`
   antes de dejar de ser vigente y no se borra nunca.

## Dos dominios de hash, declarados

WP-TAP-EVIDENCE-004F cerró una ambigüedad real: el clasificador fijaba el sha256 de los
bytes del checkout mientras el verificador lo calculaba sobre texto normalizado. Son dos
identidades distintas y ahora se nombran.

| dominio | normalización | autoridad | lo que **no** prueba |
| --- | --- | --- | --- |
| `TEXT_CANONICAL_LF` | CRLF → LF antes de hashear | toda huella de un documento de texto, incluidos los superseded | identidad de bytes de un checkout: uno LF y uno CRLF difieren por diseño |
| `BINARY_RAW` | ninguna | procedencia de artefactos (`.png`) | fijar un documento de texto |

Consecuencia práctica: la verificación da el **mismo resultado byte a byte** en una
extracción LF y en una CRLF del mismo commit. Pedirle a un hash de texto que demuestre
identidad de bytes era la afirmación sobredimensionada que el manifiesto v1 hacía; v1 se
conserva intacto en `superseded-manifests/SUPERSESSION_MANIFEST.v1.json`.

## Reproducir

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. Regenerar el objeto canónico y los informes derivados
./.venv/Scripts/python.exe scripts/evidence004_generate.py --json

# 2. Verificar de forma independiente (relee los logs y recomputa)
./.venv/Scripts/python.exe scripts/evidence004_verify.py

# 3. Probar que el verificador muerde: cada mutación debe ser rechazada
./.venv/Scripts/python.exe scripts/evidence004_verify.py --mutations

# 4. Verificar desde una extracción del commit, no desde el árbol de trabajo
git archive HEAD | tar -x -C /tmp/ev004-lf
./.venv/Scripts/python.exe scripts/evidence004_verify.py --root /tmp/ev004-lf
```

`--root` permite verificar cualquier copia, y el generador acepta `--root` por la misma
razón: las pruebas de las cinco reparaciones construyen su propio paquete en lugar de
mutar el publicado.

## Perímetro del descubrimiento

El verificador descubre **todos** los ficheros de tipo informe bajo `reports/ai-bots/`
(`RUN_REPORT*`, `FINAL_REPORT*`, `REA_FINDINGS*`, `INFORME_*`, `INDEPENDENT_VERIFICATION*`,
`*MATRIX*`, `RECONSTRUCTION_*`) y falla si alguno no está registrado como vigente, derivado,
superseded o perteneciente a una proyección histórica registrada. Los informes de la raíz del
repositorio pertenecen a otros agentes y quedan fuera de este perímetro; decirlo es parte del
informe, no una omisión.

## Lo que este paquete no hace

- No reejecuta REA ni llama a ningún modelo: cuenta lo que los logs ya registraron.
- No convierte evidencia declarada en verificada.
- No certifica patrones externos ni mide rentabilidad.
- No toca `src/trading_bot/`, `config/risk.yaml`, brokers ni estrategias.
