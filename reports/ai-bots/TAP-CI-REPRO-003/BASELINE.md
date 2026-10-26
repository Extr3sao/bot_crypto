# BASELINE — RFC-TAP-CI-003

**Fase:** diagnóstico y clasificación, antes de cualquier cambio.
**Commit auditado:** `a83ac16532f2a8b5ea131b25910d4b57abf9fe0e`
**Rama:** `admission/integration-002`
**Worktree:** `C:/Users/GVLLFR0035/Downloads/ff-wt-adm002` — limpio al inicio (`git status --porcelain` vacío).
**Fecha (UTC):** 2026-10-26.

> Nota de entorno: el checkout principal (`bot freebuff`, rama `feat/wp-signal-001-003`) tiene
> trabajo ajeno sin commitear. Todo el RFC se ejecutó en el worktree `ff-wt-adm002`, que es el
> que está en la base auditada. Dos ediciones iniciales se aplicaron por error al checkout
> principal y se revirtieron (`git checkout --`) sin tocar ningún otro cambio; el árbol quedó
> como estaba.

---

## 1. Workflows y contratos implicados

| Workflow | Job | Pasos que importan | Contrato |
| --- | --- | --- | --- |
| Cost-barrier drift gate | `cost-barrier-gate` | materializar inputs · reproducir (gate full) · adversarial · **certificación** · subir evidencia | `data/recovery/wp7/evidence/PRODUCER_PINS.json`, `COST_BARRIER_CERTIFICATION.json` |
| recovery-determinism | `recovery-determinism` | verificar bundle · invariante económica · **tests de contrato** · rehearsal · verificador independiente | `ACTIVE_ECONOMIC_AUDIT.json`, `CLEAN_CHECKOUT_REHEARSAL_REPORT.json` |

## 2. Baseline en GitHub Actions (commit `a83ac165`)

Los cuatro workflows del PR #18 estaban en `failure`. Los dos que este RFC debe cerrar fallan
**antes** de la evidencia:

| Run | Workflow | Paso que falla | Detalle real |
| --- | --- | --- | --- |
| [40312138206](https://github.com/Extr3sao/bot_crypto/actions/runs/40312138206) | Cost-barrier drift gate | 9 · Certification record | `contract tests` exit 1: `2 failed, 91 passed` — `test_the_pinned_producers_match_their_manifest`, `test_a_changed_producer_is_a_named_failure`. `REFUSED: the contract tests failed`. |
| [40312138093](https://github.com/Extr3sao/bot_crypto/actions/runs/40312138093) | recovery-determinism | 9 · Lane contract tests | `3 failed` — `test_audit_is_deterministic_and_committed`, `test_repeated_reproduction_is_byte_identical`, `test_the_clean_checkout_rehearsal_passes_on_this_commit`. |
| [40312138506](https://github.com/Extr3sao/bot_crypto/actions/runs/40312138506) | Integration gate | 7 · Gate | B11: el runner no tiene feed; `[wp04] BLOCKED — no cycle could be executed on the live feed`. Fuera de alcance. |
| [40312138095](https://github.com/Extr3sao/bot_crypto/actions/runs/40312138095) | CI Baseline | Ruff format · pip-audit · Smoke | B12: deuda heredada de `main` (444 ficheros Ruff, 297 Mypy) y `microsoft/powershell@v1.1.0` inexistente. Fuera de alcance. |

Los mismos dos fallos se reproducen en local sobre `a83ac165`, así que no son del runner:

```
uv run python -m pytest \
  tests/unit/research/test_active_recovery_wp.py::test_audit_is_deterministic_and_committed \
  tests/unit/research/test_cost_barrier_gate.py::test_the_pinned_producers_match_their_manifest \
  tests/unit/research/test_cost_barrier_gate.py::test_a_changed_producer_is_a_named_failure \
  -q -p no:cacheprovider
→ 3 failed, exit 1
```

## 3. Clasificación de cada fallo

| ID | Síntoma | Clasificación | Causa raíz |
| --- | --- | --- | --- |
| **B13** | En Linux (y en cualquier checkout que presente LF) dos tests de productores fallan con `DRIFT` aparente. | `CHECKER_DEFECT` | El test exigía `PIN_EXACT` para los cuatro productores, pero `PRODUCER_PINS.json` declara que se acepta el mismo contenido en forma LF **o** CRLF (`sha256_lf` / `sha256_crlf`) y el gate sólo considera fallo `DRIFT`/`ABSENT`. En un checkout LF, `scripts/cost_barrier.py` sale `EOL_ONLY` y el propio gate lo cuenta como OK (`producers:digests_match_the_pinned_manifest` PASS en el mismo run). El fallo era del test, no del contenido. |
| **B14a** | `ACTIVE_ECONOMIC_AUDIT.json` publicado con `payload_sha256 = 023b66ff…`; reconstruido `c6ea3438…`. | `STALE_ARTIFACT` | El artefacto se generó el 2026-10-11 (`head 9b9a4b8a`) y registró el digest del entrypoint `scripts/start_paper_trading.py` como `8cd88320…`. Ese fichero cambió realmente el 2026-10-24 en `537e4990` (añade `defensive_blocks=settings.risk.blocks`), así que el digest actual es `5d7c59cd…`. No es EOL: es contenido distinto. Al ser `entrypoints` parte de la identidad, la auditoría quedó obsoleta. |
| **B14b** | `active_economic_audit.py --check` devolvía `PASS` sobre una auditoría obsoleta. | `CHECKER_DEFECT` | `main()` escribía `ACTIVE_ECONOMIC_AUDIT.json` y `.md` **antes** de leer el artefacto publicado para compararlo: comparaba el fichero recién escrito consigo mismo. Además no distinguía artefacto ausente, incompleto o manipulado, ni separaba cambio económico de cambio de procedencia. |
| **B15** | Cost-barrier falla en el paso 10 *después* de pasar todos los contratos; recovery queda verde pero su artefacto no contiene `.ci/`. | `CHECKER_DEFECT` (empaquetado de evidencia) | `actions/upload-artifact@v4` excluye ficheros ocultos por defecto. `.ci/` es un directorio oculto: el upload de cost-barrier no encontró nada y falló por `if-no-files-found: error`; el de recovery subió sólo los JSON de `data/` y perdió el stdout del rehearsal y el registro del verificador. |

## 4. Estado económico antes de tocar nada

| Comprobación | Valor en `a83ac165` |
| --- | --- |
| Celdas de estrategia | 24 |
| `NO_GROSS_EDGE` / `COST_KILLED` | 17 / 7 |
| `admitted_for_paper` | 0 |
| `net_positive_count` | 0 |
| Mejor bruto | `volatility@30m` 8,912 bps |
| Suelo observado / runtime | 12,177 / 23,354 bps |
| Celdas que superan el suelo | 0 |
| Checks de la auditoría | 19/19 PASS, `checks_failed 0` |
| Gate cost-barrier (con input materializado) | `FULL_REPRODUCTION_PASS`, 13/13, 0 advisories |
| Bundle de evidencia | `VERIFIED`, 4/4 productores (3 exact, 1 EOL_ONLY) |

La auditoría obsoleta **no había cambiado ninguna cifra económica**: el diff de la identidad era
exactamente `['entrypoints']`; `strategies`, `aggregates`, `cost_plane`, `checks` y `answers`
eran idénticos. Eso se comprobó campo a campo antes de regenerar y se repitió después.

## 5. Hashes de referencia (`a83ac165`)

| Fichero | sha256 |
| --- | --- |
| `scripts/active_economic_audit.py` | `6c4fbd8093a7057a0d02d7fdcb2953dccebf11b2959746bf1ebc7bb45f0cf5ba` |
| `tests/unit/research/test_cost_barrier_gate.py` | `8c12f12459032ca6ccf3a25338ca8f2e39e21b29aac2d47bf6aa3d09c87d90d8` |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | `e05be22b1b165900368e1ffeb1aa8802c766c47c4636df4a635e1beed5efddf3` |
| `data/recovery/COST_BARRIER_EXPLORER.json` | payload `4383d812d6e18928c53894c7ee3ba063723d351ab945fcfc206373dfaa2621fb` |
| `data/recovery/COST_BARRIER_CERTIFICATION.json` | fingerprint `0cfdb13e9800a1450d7cb3736b644b862662b857f0416c12433f33e3e2499b0d` |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` (identidad) | `023b66ffd1213b069607a8844f669c0ff00c0b35533619a031d4d6a5d2fb2a53` |

## 6. Criterio de cierre adoptado

El RFC sólo se considerará cerrado cuando, sobre un commit publicado:

1. `cost-barrier-gate` y `recovery-determinism` terminen en `success` con sus contratos completos
   (sin pasos suavizados, sin tests desactivados);
2. el gate reproduzca el 100% y el certificador emita `CERTIFIED`;
3. `active_economic_audit.py --check` no escriba nada y falle ante artefacto obsoleto,
   ausente, incompleto o manipulado;
4. las pruebas adversariales sigan detectando cambios reales;
5. la verificación independiente pase y `FALSE_SUCCESS = 0`;
6. ningún límite de riesgo, coste o admisión haya cambiado.
