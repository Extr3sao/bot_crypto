# FINAL REPORT — RFC-TAP-CI-003

**Reproducibilidad de evidencias y cierre de B13/B14**
Trading Agentic Portable · `Extr3sao/bot_crypto`

- **Base:** `admission/integration-002` @ `a83ac16532f2a8b5ea131b25910d4b57abf9fe0e`
- **Rama:** `fix/ci-repro-003` (6 commits sobre la base)
- **PR:** [#53](https://github.com/Extr3sao/bot_crypto/pull/53) — abierta, sin fusionar
- **Commit probado en CI:** `63950a7295d7659fffe894e49d6fa5624d1280a2`
- **Último commit de evidencia:** `eda14ae4e0aa18b9660441de31f94b1c7a6b9a61`; este informe viaja en el commit que lo contiene
- **Fecha:** 2026-10-26

---

## Estados (no heredados entre fases)

| Estado | Valor | Evidencia |
| --- | --- | --- |
| **CI_REPRO_STATUS** | **PASS** | Cost-barrier drift gate [40326169405](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169405) y recovery-determinism [40326169257](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169257) en `success` sobre `63950a72`, con todos sus pasos |
| **INTEGRATION_STATUS** | **NO_GO** (sin cambios) | Integration gate [40326169488](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169488) en `failure`: B11, el runner no tiene feed. Este RFC no lo toca |
| **PAPER_RUNTIME_STATUS** | **PARTIAL** (sin cambios) | Este RFC no ejecuta runtime. Sigue la evidencia anterior: 7 ciclos, 2 fills, 0 cierres, 0 órdenes live |
| **STRATEGY_ADMISSION_STATUS** | **NO_GO** (sin cambios) | 0/24 admitidas; 17 `NO_GROSS_EDGE`, 7 `COST_KILLED` |
| **PROFITABILITY_EVIDENCE_STATUS** | **NEGATIVE** (sin cambios) | Mejor bruto 8,912 bps; suelo observado 12,177 bps; 0 celdas lo superan; 24/24 con neto negativo |

Un `PASS` de CI_REPRO significa que la evidencia es **actual y reproducible**. No dice nada sobre
rentabilidad, admisión ni permiso de operar.

---

## 1. Qué fallaba realmente

### B13 — el test era más estricto que el contrato que decía verificar

`PRODUCER_PINS.json` declara que un consumidor debe aceptar el mismo contenido en LF **o** CRLF, y
el gate ya trataba sólo `DRIFT`/`ABSENT` como fallo (`producers:digests_match_the_pinned_manifest`
pasaba en el mismo run). Pero dos tests exigían `PIN_EXACT` para los cuatro productores. En un
runner Linux —o en cualquier checkout que presente LF para `scripts/cost_barrier.py`— el estado es
`EOL_ONLY` y los tests fallaban sin que nadie hubiera editado el fichero. La certificación se
negaba a emitirse por ese falso positivo.

### B14 — dos defectos, no uno

1. **Artefacto realmente obsoleto (`STALE_ARTIFACT`).** La auditoría se generó el 2026-10-11
   (`head 9b9a4b8a`) y registró el digest del entrypoint `scripts/start_paper_trading.py` como
   `8cd88320…`. Ese fichero cambió el 2026-10-24 en `537e4990` (añade
   `defensive_blocks=settings.risk.blocks`); el digest actual es `5d7c59cd…`. Como `entrypoints`
   forma parte de la identidad, el artefacto publicado dejó de describir el commit. No era EOL.
2. **`--check` se autocertificaba (`CHECKER_DEFECT`).** `main()` escribía el JSON y el Markdown y
   *después* leía el fichero publicado para compararlo: comparaba lo que acababa de escribir
   consigo mismo. Una auditoría obsoleta se convertía en actual y devolvía `PASS`.

### B15 — hallado en WP-04: la evidencia no se subía

Con todos los contratos ya verdes, `cost-barrier-gate` falló en el paso 10: `upload-artifact@v4`
excluye ficheros ocultos, y `.ci/` es un directorio oculto. `recovery-determinism` quedó verde pero
su artefacto perdió el stdout del rehearsal y el registro del verificador.

---

## 2. Qué se implementó

| Cambio | Fichero | Por qué |
| --- | --- | --- |
| `--check` estrictamente read-only, con `CURRENT` / `STALE_PROVENANCE` / `ECONOMIC_DRIFT` / `INCOMPLETE` / `TAMPERED`, códigos 0/1/2 y comprobación de que el rebuild no falla sus propios checks | `scripts/active_economic_audit.py` | B14b: no puede certificar lo que no ha comparado, y debe nombrar qué se movió |
| Tests de productores alineados con `admissible_byte_conventions` + regresiones de LF/CRLF y productor ausente | `tests/unit/research/test_cost_barrier_gate.py` | B13: el contenido es la autoridad; la convención de salto de línea no lo es |
| Auditoría regenerada (sólo cambia `entrypoints`; economía idéntica) | `data/recovery/ACTIVE_ECONOMIC_AUDIT.{json,md}` | B14a |
| Explorer y verificación regenerados (fijan el `state_sha256` de la auditoría) | `data/recovery/COST_BARRIER_EXPLORER.{json,md}`, `COST_BARRIER_VERIFICATION.json` | la cadena de pins debe describir el mismo commit |
| Manifiesto de productores re-pinnado en el mismo commit | `data/recovery/wp7/evidence/{INPUT_EVIDENCE,PRODUCER_PINS}.json` | el productor `active_economic_audit.py` cambió |
| Certificación re-emitida dos veces, conservando fingerprint/head/digest anteriores | `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` | el registro es autocontenido: el test lo lee, así que la primera emisión sólo puede describir el intento y la segunda certificar |
| Paso read-only en CI | `.github/workflows/recovery-determinism.yml` | el contrato se ejerce en el modo que no puede reescribir el artefacto |
| `include-hidden-files: true` + aserciones | ambos workflows y tests de paridad | B15 |
| Rehearsal re-ejecutado | `data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.{json,md}` | el informe anterior describía los artefactos viejos |

**No se tocó** ningún límite de riesgo, coste, sizing, leverage ni umbral de admisión
(`git diff --name-only a83ac165..63950a72 -- config/ src/trading_bot/risk/ docs/COST_MODEL_V3.json
…cost_model_v3.py .github/workflows/{ci,integration-gate}.yml` → vacío).

---

## 3. Tests (commit probado `63950a72`)

```
146 passed, 0 failed, 0 skipped in 168.38s   (exit 0)
```

Cubre los cuatro ficheros del carril cost-barrier, los tres del carril recovery y el rehearsal
completo (marcado `slow`, sin filtrar). Resultados por contrato:

| Comprobación | Resultado |
| --- | --- |
| `active_economic_audit.py --check` | `PASS` / `CURRENT`, exit 0, **sin escribir** (bytes y mtime idénticos) |
| Bundle de evidencia | `VERIFIED`, 6/6 checks, 4/4 productores `EXACT` |
| Gate (reproducción completa) | `FULL_REPRODUCTION_PASS`, 13/13, 0 advisories, `satisfies_full_certification: true` |
| Verificador independiente del explorer | `PASS`, 4/4 checks, 13/13 controles, `false_success 0` |
| Adversarial | 17/17 ataques detectados, 0 escapados |
| Certificación | `CERTIFIED`, fingerprint `5a79ebe3…`, `dirty_watched_paths: []` |
| Verificador independiente recovery | `PASS`, C1–C17, 13 controles, `controls_missed 0` |
| Rehearsal | `PASS` sobre `d62ecb76`, 4/4 artefactos idénticos, `published_paths_moved: []` |

Controles negativos ejecutados por `tools/verify_report.py`: digest de manifiesto alterado,
fingerprint de certificación reescrito, una celda subida +1 bps, y el estado del gate del informe
cambiado a `FAILED`. Los cuatro se detectan; `false_success = 0`.

---

## 4. Validación en GitHub Actions

| Run | Workflow | SHA | Conclusión | Pasos relevantes |
| --- | --- | --- | --- | --- |
| [40326169405](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169405) | Cost-barrier drift gate | `63950a72` | **success** | materializar ✓ · gate ✓ · adversarial ✓ · certificación ✓ · upload ✓ |
| [40326169257](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169257) | recovery-determinism | `63950a72` | **success** | bundle ✓ · invariante ✓ · **audit --check ✓** · tests ✓ · rehearsal ✓ · verificador ✓ · upload ✓ |
| [40326169295](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169295) | CI Baseline | `63950a72` | failure (B12) | Ruff format, pip-audit y setup del smoke: deuda heredada de `main` |
| [40326169488](https://github.com/Extr3sao/bot_crypto/actions/runs/40326169488) | Integration gate | `63950a72` | failure (B11) | el runner no tiene feed; la campaña no puede ejecutar un ciclo |

En la ronda previa sobre `09a137c1`, recovery-determinism ya era verde y cost-barrier falló
**sólo** en el paso de upload (todos sus contratos habían pasado); ese defecto es B15 y se corrigió
en `63950a72`. No se declara verde ningún run de otro commit ni de otra rama.

---

## 5. ¿Cambió algún resultado económico?

**No.** Comparación campo a campo entre la auditoría publicada en `a83ac165` y la regenerada:

```
identity changed sections: ['entrypoints']
economic findings identical: True
strategies True · aggregates True · cost_plane True · checks True · answers True
```

- 24 celdas, 17 `NO_GROSS_EDGE`, 7 `COST_KILLED`, 0 admitidas, 0 con neto positivo.
- Mejor bruto 8,912 bps; suelo observado 12,177 bps; suelo runtime 23,354 bps.
- El explorer reproduce los mismos 24 cells / 120 configuraciones / 7 alcanzables con el mismo
  bruto; sólo cambian sus pins y su identidad.
- No se relajó ningún umbral ni se "arregló" ninguna cifra para que cuadrara.

La re-emisión de la certificación conserva la identidad de la anterior
(`previous_fingerprint 0cfdb13e…`, luego `492146e9…`), no la sobrescribe.

---

## 6. Bloqueos y límites

| ID | Estado | Detalle |
| --- | --- | --- |
| **B11** | **ABIERTO** | El runner no tiene feed de mercado: Integration gate no puede certificar. Fuera de alcance de este RFC; no se usó ningún feed simulado. |
| **B12** | **ABIERTO** | CI Baseline nunca ha estado verde: Ruff format (444 ficheros), pip-audit y el setup del smoke (`microsoft/powershell@v1.1.0` inexistente). Fuera de alcance. |
| **B13** | **CERRADO** | Contrato y tests alineados; CI Linux verde. |
| **B14** | **CERRADO** | Auditoría actual, `--check` read-only y estricto; CI verde. |
| **B15** | **CERRADO** | Evidencia oculta subida y fijada con tests. |

Límites explícitos:

- El `PASS` de este RFC es de reproducibilidad, no de estrategia. Las conclusiones económicas
  siguen siendo negativas y ninguna estrategia queda admitida.
- La verificación local se ejecutó en Windows (`3.11.15`); la evidencia multiplataforma es el run de
  `ubuntu-latest`, que replica los mismos contratos.
- La certificación incluye en su fingerprint el momento (`generated_at_utc`) del documento de
  verificación del explorer. Volver a ejecutar `cost_barrier_verify.py` escribiendo en la ruta
  publicada cambia ese documento e invalida el registro; CI lo ejecuta en un directorio temporal y
  no lo hace. Queda anotado como fragilidad de diseño, no corregido aquí.
- El `head` de la auditoría es `a83ac165` (el commit desde el que se regeneró). La identidad excluye
  `head` por contrato, así que `--check` sigue siendo `CURRENT`; se documenta para que nadie lo lea
  como un pin de commit.

---

## 7. Evidencias

- [BASELINE.md](BASELINE.md) — diagnóstico y clasificación (`EOL_ONLY` vs `STALE_ARTIFACT` vs `CHECKER_DEFECT`).
- [CHANGELOG.md](CHANGELOG.md) — commits, ficheros y motivo.
- [TEST_RESULTS.json](TEST_RESULTS.json) — comandos, códigos de salida, conteos y runs.
- [EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json) — sha256 de cada artefacto.
- [INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json) — verificación independiente y controles.
- [evidence/](evidence/) — stdout de pytest, gate, bundle, verificadores y certificación; `ci_runs.json` con los runs.

---

## 8. Siguiente trabajo operativo recomendado

1. **B11** es el único bloqueo que impide certificar la integración: hace falta un feed reproducible
   en el runner (replay determinista de barras ya capturadas, declarado como replay, nunca como
   live). Sin eso, el Integration gate seguirá en `NO_GO` por diseño.
2. **B12**: abordar Ruff/Mypy como trabajo propio y por tramos, sin reformatear todo el repo en un
   commit; el smoke pipeline necesita una acción existente (`microsoft/powershell` no existe).
3. No tocar umbrales económicos: la evidencia sigue siendo negativa. El siguiente paso honesto es
   investigación de estrategia (nueva hipótesis), no relajar c1–c9.
4. Revisar y fusionar la PR #53 cuando el revisor acepte el diff; este RFC no fusiona nada.
