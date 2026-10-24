# FINAL REPORT — RFC-TAP-PAPER-ADMISSION-REPRO-001

## Respuesta

**`IMPLEMENTED_VERIFIED`.** El diagnóstico ya está en Git con sus hashes, los tres defectos
demostrados están corregidos y un verificador independiente en método da **12/12 gates PASS con
`false_success = 0`**, repetido desde un **checkout limpio** creado en el commit que se publica.

**La admisión PAPER sigue en `NO_GO`.** Este RFC no cambia el veredicto económico, ni el ledger,
ni los límites de riesgo, ni los criterios de admisión: **0 de 24 estrategias admitidas**. Lo que
cambia es que ahora eso se puede comprobar desde un clon, no solo en este disco.

## 1. Commits

| Rol | Commit | Qué contiene |
| --- | --- | --- |
| Base (antes de cualquier cambio) | `b4c8e3e2` | merge de `main` en `codepaper/supervisor-001`, sin conflictos |
| **Artefacto verificado** | **`c44f912c2fa7e25a9765323aa0032a23425446ab`** | correcciones + diagnóstico versionado + evidencia + manifiesto + verificador |
| Informes | commit siguiente a `c44f912c` | los ficheros que estás leyendo y el log del rehearsal |

`git log --oneline -- reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/FINAL_REPORT.md` nombra el
último sin que el informe tenga que citar su propio hash.

El checkout compartido no se modificó. El trabajo vive en la rama `repro/paper-admission-001`,
en un worktree aparte; el worktree `wt-sup001` de la otra lane sigue en `3b758e22` con el árbol
limpio.

## 2. Cambios realizados

| Defecto | Corrección | Efecto medido |
| --- | --- | --- |
| `test_windowless`: 3 offenders `HIGH` | los dos tests arrancan su hijo con `windowless.spawn`; `exp004a_verify.py` esconde el suyo con `CREATE_NO_WINDOW` + `STARTUPINFO/SW_HIDE` porque **no puede** importar el runtime que audita (RFC-051 §5); la auditoría acepta esa excepción **solo mientras el mecanismo esté ahí**, y si desaparece emite `DECLARED_LOCAL_HIDING_MISSING` | `HIGH 3 → 0`; 14/14 tests |
| `paper_lock_campaign_verify` juzgaba campañas ajenas | `judge()` lee **solo** `CAMPAIGN.json.schema_version`; si no es `TAP_PAPER_LOCK_CAMPAIGN_V1`, devuelve `UNSUPPORTED_CAMPAIGN_SCHEMA`, **0 checks puntuados** y **0 mutaciones** | `FAIL 28/32 + false_success 2` → rechazo nombrado, `false_success 0` |
| `uv.lock` sin `matplotlib` | lock regenerado; `uv sync --frozen` ya no puede construir un entorno sin el runtime | `lock --check 1 → 0`; checkout limpio importa `matplotlib 3.11.2` |
| Diagnóstico fuera de Git | bloques de `.gitignore` para los tres directorios; se versionan los 6 documentos, `verify_claims.py`, su evidencia y la campaña del supervisor | los 7 hashes fijados en el verificador; V03 demuestra que **no** estaban en el commit base |

La auditoría no se ablandó: sigue siendo un escaneo por fichero con las mismas severidades, y la
excepción nueva tiene su propio control negativo. Lo único que cambió es que ahora un lanzador
puede demostrar que esconde su hijo sin importar el helper.

## 3. Pruebas ejecutadas y resultados reales

| Prueba | Antes | Después |
| --- | --- | --- |
| `pytest tests/unit/ops` | 1 failed, 82 passed | **86 passed** |
| `pytest tests/unit/ops/test_windowless.py` | 1 failed, 12 passed | **14 passed** |
| `ops_background_audit.py` | HIGH 3 | **HIGH 0, CLEAN** |
| `uv lock --check` | exit 1 | **exit 0** |
| `uv sync --frozen` (checkout limpio) | exit 0 **sin `matplotlib`**: los verificadores morían con `ModuleNotFoundError` | **111 paquetes, `matplotlib` importable, lock intacto** |
| `paper_lock_campaign_verify` sobre campaña ajena | FAIL 28/32, `false_success 2` | **rechazo, 0 checks, `false_success 0`** |
| `paper_lock_campaign_verify` sobre campaña propia | PASS con 9 mutaciones | **PASS 33/33, 10 mutaciones, 0 invalid, 0 undetected** |
| `paper_supervisor_verify` (código ajeno, sin tocar) | PASS 33/33 | **PASS 33/33** |
| `test_exp004a_verify_adversarial.py` | — | **20 passed** |
| `verify_repro.py` | — | **12/12 gates, 4/4 controles, `false_success 0`** |

Checkout limpio en `c44f912c`, sin `.venv`, `--detach`: 5 comandos, **5 exit 0**.
Transcripción: `evidence/CLEAN_CHECKOUT_REHEARSAL.log`.

## 4. Verificación independiente

`verify_repro.py` recalcula los hashes desde bytes (los seis documentos están **congelados dentro
del verificador**, no leídos del manifiesto que audita), ejecuta cada gate como subproceso y lee
el payload de la herramienta. Cuatro controles negativos demuestran que sabe fallar: byte
alterado, campaña sin schema, excepción de ventana sin mecanismo, manifiesto manipulado.

Dos verificadores que **no escribí** siguen dando el mismo veredicto que antes de tocar nada:
`ops_background_audit.py` (V04) y `paper_supervisor_verify.py` (V08, 33/33 sobre la campaña
real). Es la parte de la independencia que sí está fuera de mis manos.

**Límite declarado:** `BUILDER != VERIFIER` se cumple en **método**, no en identidad. El
verificador lo escribió el mismo agente que hizo las correcciones; con los agentes disponibles
en esta sesión no hay forma de cerrar esa brecha, y no la presento como cerrada.

## 5. Errores y defectos abiertos

**Encontrados y corregidos durante el trabajo** (los tres, por el rehearsal o por el propio
verificador, no por revisión a ojo):

1. El manifiesto nombraba **20 logs que Git no llevaba** (la regla global `*.log` los excluía).
   V02 lo detectó en el checkout limpio y el commit se rehízo.
2. El manifiesto **se hasheaba a sí mismo** y quedaba obsoleto al escribirse.
3. Un control negativo salía `false` por un bug del control (módulo sin registrar en
   `sys.modules` antes de un `dataclass`).

**Abiertos, con evidencia** (`RUN_REPORT.md` §4): `verify_claims.py` no es portable (resuelve
`ROOT/wt-sup001`); `test_single_writer_lock` tiene una carrera sensible a la carga
(`LOCK_UNATTRIBUTED`, 1 fallo en suite completa, 3/3 en aislamiento, fichero no tocado por este
RFC); `uv sync --frozen` sigue saliendo 0 ante un desajuste pyproject/lock aunque el gate V09 lo
detecte; rechazo y fallo comparten exit code 1; drift preexistente de `mypy`/`ruff format` en
`scripts/`; y **no hay campaña de lock real** versionada, así que el `PASS` de la campaña propia
es sobre fixture, no sobre seis crashes ejecutados.

## 6. Estado de admisión PAPER

- **Veredicto: `NO_GO`.** 24 estrategias en el ledger, **0** con `admitted_for_paper`.
- Recalculado por el verificador desde `config/strategy_admission.json` (V12), no citado de un
  informe, y con el fichero byte-idéntico al commit base: este RFC no tocó ni el ledger ni
  `docs/STRATEGY_ADMISSION_CRITERIA.md`.
- La razón sigue siendo económica, no de ingeniería: el mejor bruto por operación (**+8.912 bps**
  en `volatility@30m`) no cubre la línea de costes (**12.177 bps** medidos; **23.354 bps** de
  admisión). Nada de lo hecho aquí acerca esa brecha.
- El siguiente experimento con valor esperado sigue siendo `EXP-COST-LINE-001`
  (`reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001/NEXT_EXPERIMENT.md`): medir la línea maker real
  con el motor de fills de EXP-003M. Este RFC lo deja **medible**, no medido.

## 7. Desviaciones del mandato

1. **El cuerpo del RFC no estaba en el workspace.** Se recibió como mandato; `RFC.md` lo
   transcribe y lo descompone en WP-00…WP-04 sin añadir criterios. Si el RFC original dice otra
   cosa, este paquete se rebasa contra él, no al revés.
2. **Se versionó la campaña del supervisor (3,8 MB, 140 ficheros).** El mandato pedía versionar
   el diagnóstico; sin los artefactos que sus verificadores leen, la corrección del
   `schema_version` solo se podría probar en la máquina que los generó. Se excluyeron los logs de
   proceso (ruido de ejecución), no la evidencia de estado.
3. **No se reformatearon** los cuatro ficheros con drift de `ruff format` ni se corrigió el
   `no-untyped-def` preexistente: habría enterrado el diff real bajo ruido ajeno al mandato.
4. **`verify_claims.py` se preservó sin tocar** aunque no sea portable. Reescribirlo habría
   invalidado los hashes que el RFC debía conservar.

## 8. Resumen para revisión externa

Un revisor puede, desde un clon:

```bash
git checkout c44f912c
uv sync --frozen
.venv/Scripts/python.exe reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/verify_repro.py
```

y obtener el mismo `12/12 PASS, false_success 0` sin confiar en nada de este documento. Si algo
de lo anterior cambia, `V01`/`V02` fallan: los hashes del diagnóstico y del árbol están
comprobados, no prometidos.
