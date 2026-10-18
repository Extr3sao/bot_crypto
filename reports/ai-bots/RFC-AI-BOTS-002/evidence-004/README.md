# EVIDENCE-004 — un solo número, derivado de la evidencia

Este paquete existe por un defecto concreto y repetido: cuatro informes del RFC
AI-BOTS-002 contaban lo mismo de cuatro maneras, y una de ellas llamaba «éxito» a una
operación que REA **rechazó** porque el `exit_code` era 0.

```
logs crudos (nunca se escriben)
        │
        ▼
evidence004_ledger.py     clasifica cada operación: execution_class != exit_code
        │
        ▼
CANONICAL_RUN.json        un objeto, dos ámbitos separados, claims verificados
        │
        ├── RUN_REPORT.json / RUN_REPORT.md      (rutas estables + copia versionada)
        ├── INFORME_EJECUTIVO_NUMEROS.md
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
4. **Lo histórico no se borra: se sella.** Los informes antiguos se conservan byte a
   byte, con su hash, en `SUPERSESSION_MANIFEST.json`. Editarlos para que cuadren sería
   lavar el defecto en lugar de registrarlo.
5. **Un claim sin fuente no se publica.** `CLAIMS.json` ata cada frase numérica a un
   contador o a un `evidence_id`; si no resuelve, el generador se niega a escribir.
6. **Un solo escritor, escritura atómica.** `evidence004_generate.py` toma
   `.writer.lock` y escribe con `os.replace`; dos ejecuciones simultáneas no pueden
   intercalar un informe a medias.

## Reproducir

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. Regenerar el objeto canónico y los informes derivados
./.venv/Scripts/python.exe scripts/evidence004_generate.py --json

# 2. Verificar de forma independiente (relee los logs y recomputa)
./.venv/Scripts/python.exe scripts/evidence004_verify.py

# 3. Probar que el verificador muerde: cada mutación debe ser rechazada
./.venv/Scripts/python.exe scripts/evidence004_verify.py --mutations
```

## Cifras actuales

| contador | valor |
| --- | --- |
| `phase_v31.work.operations` | 9 |
| `phase_v31.work.executed_with_evidence_id` | 7 |
| `phase_v31.work.executed_with_verified_artifact` | 2 |
| `phase_v31.work.not_executed` | 2 |
| `all_dossiers.distinct_evidence_ids` | 12 |

Las cifras de la tabla anterior son una copia legible: el verificador exige el bloque
generado en cada informe, no este README. Si divergen, gana el bloque.

## Lo que este paquete no hace

- No toca `src/`, `tests/` ni `config/risk.yaml`: es reporting puro.
- No reejecuta REA ni llama a ningún modelo. Cuenta lo que los logs ya registraron.
- No certifica ningún patrón externo. `REAL_MODEL_CALLED = false` y
  `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION` siguen vigentes.
