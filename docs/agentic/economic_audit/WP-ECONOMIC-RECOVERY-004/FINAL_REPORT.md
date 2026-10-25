# WP-ECONOMIC-RECOVERY-004 — Informe final

**Estado: PASS (alcance: integridad del ledger y recertificación del lane del cost-barrier).**

No es una recuperación económica, no valida ninguna estrategia y no autoriza PAPER ni
trading. El `payload_sha256` del explorer es el mismo antes y después: ninguna cifra
económica se ha movido.

---

| campo | valor |
| --- | --- |
| `PHASE` | cerrado con PASS; `FALSE_SUCCESS = 0` |
| `COMMITS` | `7311e553` (contrato + tests) · `265d09ed` (reparación + pines) · este commit (recertificación + verificación independiente + informes) |
| `IMPLEMENTED` | contrato de identidad semántica v1 con identificador versionado; productor, verificador de gate y verificador independiente (tres implementaciones que no se importan); gate que acepta `state-exact` sólo si el estado recalcula **y** los bytes coinciden o son su render LF/CRLF; pines de estado publicados en `sources[]`; `newline="\n"` en los cinco escritores del lane |
| `TESTS` | lane: **137 passed, 0 failed** (24 del contrato, 32 gate, 34 adversarial, 17 explorer, 11 CI-parity, 15 determinismo, 4 ledger). Suite completa: **104 → 85** nodos rojos, **19 cerrados** (todos del lane), **0 introducidos**, 3270 → 3314 passed |
| `RUNTIME_VALIDATION` | gate completo real: `FULL_REPRODUCTION_PASS`, 13/13, **exit 0**; `--check`: `CHECK_ONLY_PASS`, 12/12, exit 2 (parcial por diseño); certificador: **CERTIFIED, exit 0**, 5/5 pasos, 0 rutas vigiladas sucias; ensayo de checkout limpio verde |
| `FALSE_SUCCESS` | **0** — ningún artefacto declara rentabilidad, promoción ni certificación global; `authorizes_promotion: false`, `authorizes_live_trading: false`, `NOT_AUTHORIZED`, 0 trades |
| `DEFECTS` | DEF-1 pin no reproducible → reparado; DEF-2 escritores dejaban elegir el EOL al host → reparado; DEF-3 dependencia circular `--materialize`/`--capture` → declarada; DEF-4 el certificador no puede reemitir su propio registro en una pasada → declarada; DEF-5 el informe adversarial identifica el gate en `a551fdc` → declarada, no certificante |
| `BLOCKERS` | **ninguno** para el alcance de este WP. Persisten, fuera de alcance: 85 fallos preexistentes y la ausencia total de resultados multifamilia |
| `EVIDENCE` | [`LEDGER_INTEGRITY_CONTRACT.md`](LEDGER_INTEGRITY_CONTRACT.md) · [`REPAIR_EVIDENCE.md`](REPAIR_EVIDENCE.md) · [`RECERTIFICATION_REPORT.md`](RECERTIFICATION_REPORT.md) · [`INDEPENDENT_VERIFICATION.json`](INDEPENDENT_VERIFICATION.json) · [`RUN_REPORT.json`](RUN_REPORT.json) · [`evidence/`](evidence/) |
| `FINAL_GATE_STATUS` | `FULL_REPRODUCTION_PASS` — 13/13 checks, 6/6 controles, 0 `integrity_failures`, exit 0 |
| `NEXT_STEP` | (1) cerrar DEF-4 para que reemitir el registro sea una operación de una pasada; (2) refrescar la procedencia del informe adversarial (DEF-5); (3) **no** promover ninguna estrategia: siguen sin resultados multifamilia y sin edge neto |

---

## Antes / después

| | antes (`2bd6e346`) | después (`265d09ed`) |
| --- | --- | --- |
| gate completo | no ejecutable: el pin del ledger nombraba un render CRLF inexistente | `FULL_REPRODUCTION_PASS`, 13/13, exit 0 |
| gate `--check` | `INTEGRITY_FAILURE`, 10/11, exit 5 | `CHECK_ONLY_PASS`, 12/12, exit 2 |
| `sources[].sha256` del ledger | `6c4dd0be…` (CRLF de `ddaf14d1`) | `5e2ccc57…` (blob de `HEAD`) |
| `sources[].state_sha256` del ledger | `null` | `4d1b1e6a…` (contrato v1) |
| pin de bytes del audit | `e05be22b…` (CRLF) | `8a101e88…` (LF); el pin de estado `023b66ff…` no cambió |
| escritores del lane | `Path.write_text` sin `newline` → rebuild Windows de 21 605 líneas | `newline="\n"`; rebuild = 13 líneas de contenido |
| suite completa | 104 rojos (90 F + 14 E), 3270 passed | 85 rojos (71 F + 14 E), 3314 passed |
| nodos rojos del lane | 19 | 0 |
| verificación independiente | 14/14 (WP-003, sobre el estado con deriva) | 22/22, exit 0 |
| registro de certificación | `CERTIFIED` sobre artefactos previos a la reparación | `CERTIFIED` reemitido, con cadena de supersesión |

---

## Qué se demostró, y cómo

1. **Autoridad del ledger.** Se reprodujeron los hashes de las tres revisiones candidatas:
   el pin `6c4dd0be…` es el render CRLF de `ddaf14d1`, no el blob de ninguna revisión. El
   contenido autoritativo es `HEAD`, y no porque sea el más reciente: es el único que cita
   la matriz commiteada (`4e15882c…`), el único que `build_strategy_admission.py --check`
   reproduce, y el diff con `ddaf14d1` es una sola línea —el ancla que WP-002 corrigió—
   ([`evidence/authority_reproduction.txt`](evidence/authority_reproduction.txt)).
2. **Identidad semántica reproducible.** Tres implementaciones independientes coinciden
   sobre el ledger commiteado, sobre su render CRLF y sobre variantes manipuladas; el
   digest se calcula sobre el documento parseado bajo un sobre que incluye el identificador
   del contrato, así que LF y CRLF comparten identidad y cualquier cambio semántico —valor,
   decisión, dependencia, periodo— la cambia
   ([`test_ledger_identity_contract.py`](../../../../tests/unit/research/test_ledger_identity_contract.py)).
3. **La integridad física no se relajó.** El input inmutable `COST_BARRIER.json` sigue
   comprobándose por bytes exactos (`2437f446…`); un pin de bytes que apunta a otro fichero
   sigue siendo deriva aunque el estado coincida.
4. **La reparación no movió economía.** `payload_sha256` idéntico, las 24 entradas del
   ledger idénticas, el input byte-idéntico, ningún flag de gobernanza movido.
5. **Nada se ocultó.** Los 19 nodos cerrados son exactamente el lane; los 85 fallos
   preexistentes siguen rojos y visibles; los resultados multifamilia siguen sin existir.

---

## Árbol Git

```
265d09ed fix(evidence): re-pin the ledger the commit carries and rebuild the lane at it
7311e553 feat(evidence): give the admission ledger a versioned semantic identity
5dd4a225 docs(audit): publish the economic evidence impact audit (WP-003)
2bd6e346 docs(audit): name the measured commit, not the one that carries the report
```

Las rutas vigiladas por el certificador quedaron limpias (`dirty watched paths 0`). El
único fichero sin seguimiento que las pruebas dejan es `data/st6/ST6_RUNS.jsonl`, un
subproducto de otra suite, ajeno a este WP y no commiteado.

## Límites de esta certificación

- Certifica que el lane del cost-barrier **reproduce desde sus fuentes en este commit**, no
  que la plataforma sea rentable, ni que exista edge, ni que un backtest sea válido.
- Los 85 fallos preexistentes y la ausencia de resultados históricos multifamilia siguen
  siendo el estado real del repositorio y no se han reclasificado.
- Ninguna estrategia queda admitida para PAPER: `admitted_for_paper` es `false` en las 24
  entradas del ledger.
