# OPEN BLOCKERS — RFC-TAP-PAPER-ADMISSION-REPRO-001

Cuatro cosas que este RFC **no** cierra. Se registran aquí, separadas del veredicto, porque
un PASS de 12/12 que las oculte sería el tipo de éxito que el propio diagnóstico denuncia.
Ninguna se arregló por quedar fuera del alcance autorizado (condición 4 del mandato: solo
`test_windowless`, `schema_version` y reproducibilidad `uv`).

## B1 — `LOCK_UNATTRIBUTED`: carrera en `test_single_writer_lock`

**Síntoma.** `tests/unit/ops/test_single_writer_lock.py` falla de forma intermitente bajo
carga (1 fallo observado en una corrida completa; 3/3 en aislamiento). El fallo es de carrera
entre dos escritores, no de contenido.

**Evidencia.** El fichero no está entre los modificados por este RFC (`git diff --name-only
b4c8e3e2` no lo lista) y el fallo se reprodujo igual antes y después de los cambios. La
corrida limpia de `f118e556` pasó 86/86, que es exactamente el problema: un test que a veces
pasa no prueba nada.

**Por qué no se toca aquí.** Es una carrera del guardián de escritura único — sujeto de otra
lane, no del diagnóstico de admisión PAPER.

**Qué lo cerraría.** Reproducirlo de forma determinista (probablemente con un punto de
intercepción entre `read()` y `write()` del lock), decidir si el contrato es "último gana" o
"segundo rechazado", y un test que falle siempre ante la respuesta equivocada.

## B2 — `verify_claims.py` no es portable

**Síntoma.** El verificador de la lane de diagnóstico (`reports/ai-bots/
CODEX-PAPER-ADMISSION-DIAG-001/verify_claims.py`) solo corre desde su árbol de origen.

**Evidencia.** Se preserva byte-idéntico (hash congelado `e423ef3f…`) y se ejecuta desde el
árbol del RFC; desde un clon ajeno depende de rutas y de estado no versionado.

**Por qué no se toca aquí.** Condición 3 del mandato: los seis documentos originales se
preservan, no se corrigen. Reescribirlo cambiaría el hash que este RFC declara.

**Qué lo cerraría.** Un verificador nuevo (no una edición del original) que tome el árbol como
argumento y no asuma cwd, con el original intacto como referencia.

## B3 — `uv sync --frozen` sale 0 aunque el lock no describa el proyecto

**Síntoma.** `uv sync --frozen` devuelve 0 ante un desajuste entre `pyproject.toml` y
`uv.lock`; es `uv lock --check` quien lo detecta. El defecto original (un lock que no incluía
`matplotlib`, con lo que los verificadores morían al importar) pasaba desapercibido por eso.

**Evidencia.** `evidence/BASELINE_uv_sync_frozen.log` y
`evidence/CLONE_f118e556_uv_sync_frozen.log`: mismo exit 0, distinto contenido instalado.

**Por qué no se toca aquí.** Es comportamiento de `uv`, no del repositorio. Lo que sí se
arregló es la consecuencia: el lock ahora incluye la dependencia declarada y V10 comprueba
que se importa de verdad.

**Qué lo cerraría.** Que el procedimiento del repo encadene `uv lock --check` **antes** de
`uv sync --frozen` en cada rehearsal, y que un lock incompleto rompa el gate, no el import.

## B4 — No existe una campaña de lock real

**Síntoma.** V07 (10 mutaciones, 33 checks) y V08 (12 mutaciones, 33 checks) juzgan la
campaña **fixture** versionada en `reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/campaign/`.
Ninguna sesión PAPER real con su lock se ha ejecutado y verificado.

**Evidencia.** `scripts/paper_lock_campaign.py` existe y sabe lanzar la campaña, pero no hay
`CAMPAIGN.json` producido por una corrida real en el árbol. El PASS es sobre un fixture
preparado para el verificador.

**Por qué no se toca aquí.** Condición 8: prohibido ejecutar operaciones PAPER o LIVE.

**Qué lo cerraría.** Una única corrida PAPER autorizada, corta, con su `CAMPAIGN.json`,
`STREAM.jsonl` y `STREAM.jsonl.lock` reales, verificada por el mismo verificador sin mutar el
criterio. Hasta entonces, "el verificador juzga bien un fixture" es todo lo que se puede
afirmar.

---

## Además, una anomalía de método (no un defecto del artefacto)

**A3 — El rehearsal de `ddef6432` no era un checkout limpio de verdad.** Corrió en un
worktree que comparte `.git` con el checkout principal y hereda `core.autocrlf=false`; por eso
no vio que un clon real fallaba 2 gates. Corregido en `f118e556` y sustituido por clones
reales (`git clone --no-hardlinks`) para toda la evidencia de cierre. Se registra porque el
método anterior producía PASS legítimos en su árbol e inválidos fuera de él.
