# FINAL REPORT — RFC-TAP-PAPER-ADMISSION-REPRO-001 (cierre e integración)

## Respuesta

**`VERIFIED` con integración `NO_GO`.**

El artefacto del RFC se sostiene: 12/12 gates, 4/4 controles negativos y `false_success 0`
desde un clon nuevo del mismo commit, más 135 tests y el supervisor PAPER en 33/33. El
veredicto económico sigue siendo **`NO_GO`**: 0 de 24 estrategias admitidas, ledger
byte-idéntico al base.

Pero **no se fusiona en `main`**, y la razón no es un fallo del trabajo: el RFC está apilado
sobre una lane de 301 commits que `main` no tiene. Un `cherry-pick` de los tres commits sobre
`main` falla en 7 ficheros con `deleted in HEAD and modified` — los ficheros que el RFC
repara no existen en `main`. Fusionar la rama entera arrastraría 305 commits (301 de la lane
más los 4 del RFC) ajenos a este trabajo. Ninguna de las dos cosas es una integración de este
RFC.

## Lo que la verificación independiente encontró (y el constructor no)

El rehearsal anterior corrió en un *worktree* que heredaba `core.autocrlf=false`. Un clon
real, con el valor por defecto de Git for Windows (`true`), **falló dos gates del mismo
commit `ddef6432`**:

```
V01_preserved_docs_byte_identical   drifted: 7/7
V02_manifest_matches_tree          problems: 13 de 44 digests
```

El commit era correcto. El *checkout* reescribía los finales de línea y el manifiesto pasaba
solo en el árbol que lo había producido — exactamente el defecto que el RFC existe para
denunciar, esta vez dentro del RFC. `git hash-object` coincidía con el blob; los bytes en
disco no. La evidencia cruda está en
[CLONE_ddef6432_verify_repro_FAIL.log](evidence/CLONE_ddef6432_verify_repro_FAIL.log).

Corregido en `f118e556` siguiendo la convención que el propio repositorio ya usaba para
RFC-049, EXP-003P, EXP-004A y DEF-018: `-text` en las rutas que el manifiesto digiere, más
`EOL_NORMALISED` como causa nombrada en el verificador, más un test que enumera el manifiesto
y falla por nombre si alguien añade un digest sin pin.

El test se validó en negativo: antes de los dos últimos pines falló señalando exactamente
`.gitattributes` y `tests/unit/reports/test_evidence_manifest_eol.py`, los mismos dos ficheros
que V02 marcó en el clon. Un test que nunca se ha visto fallar no prueba nada.

## Commits

| Commit | Contenido |
| --- | --- |
| `b4c8e3e2` | base medida (merge de `main` en la lane, antes de cualquier cambio) |
| `c44f912c` | diagnóstico versionado + los tres defectos cerrados |
| `ddef6432` | rehearsal de checkout limpio (método con el hueco que se describe arriba) |
| `f118e556` | pines `-text`, `EOL_NORMALISED`, test de regresión; **artefacto verificado** |
| commit de cierre | este informe, `verify_independent.py`, evidencias del clon |

## Pruebas ejecutadas y resultados reales

Clon nuevo de `f118e556`, `core.autocrlf=true`, árbol limpio, sin `.venv`:

| Comando | Resultado |
| --- | --- |
| `uv sync --frozen` | exit 0, `matplotlib 3.11.2` importable |
| `uv lock --check` | exit 0, 118 paquetes |
| `pytest tests/unit/ops tests/unit/reports/test_evidence_manifest_eol.py` | **135 passed** |
| `verify_repro.py` | **12/12 PASS**, 4/4 controles, `false_success 0` |
| `paper_supervisor_verify.py` | PASS, 33/33, 12 mutaciones, `false_success 0` |

Verificador independiente (`verify_independent.py`, escrito desde las premisas, sin importar
nada de `verify_repro.py`): **9/9**. Declara los siete digests congelados por su cuenta,
re-cuenta la admisión desde el JSON del ledger, re-ejecuta cada herramienta y comprueba por
`git check-attr` que ningún digest depende del checkout.

## Errores del propio verificador independiente

El primer intento devolvió dos fallos que eran suyos, no del artefacto: leía `refusal` como
cadena cuando el verificador de campañas publica un objeto (`{"code": ...}`), y contaba como
«sesión abierta» los `STREAM.jsonl` versionados del fixture. Ambos corregidos; el segundo
ahora distingue fixture versionado de sesión producida (sin `STREAM.jsonl` sin seguimiento ni
bajo `data/`). Se registran porque un verificador que se arregla a sí mismo hasta pasar es
justo lo que este RFC no debe aceptar en silencio: los dos fallos se corrigieron en la
definición de la comprobación, no rebajando el umbral, y el detalle quedó en
[verify_independent.py](verify_independent.py).

## Integración: por qué `NO_GO`

```
git rev-list --count main..f118e556        305   (301 lane + 4 RFC)
git rev-list --count f118e556..main          3
git cherry-pick -n c44f912c   → CONFLICT en 7 ficheros
   .gitignore, scripts/exp004a_verify.py, scripts/ops_background_audit.py,
   scripts/paper_lock_campaign_verify.py, tests/unit/ops/test_paper_lock_campaign.py,
   tests/unit/ops/test_session_status.py, tests/unit/ops/test_windowless.py
```

`main` no tiene `src/trading_bot/ops/windowless.py`, ni `test_windowless.py`, ni
`paper_lock_campaign.py`, ni `session_status.py`: todo el sujeto del RFC vive en
`codepaper/supervisor-001`, que nunca se fusionó. `main` tiene un solo merge en toda su
historia y es lineal, así que tampoco hay convención de «merge de lane» que aplicar.

**Detenido el merge** conforme a la condición 7 del mandato. El checkout compartido sigue en
`e67194e7`, `main` sigue en `e67194e7`, y sus entradas pendientes (28 en el momento de
cerrar, 26 al empezar) no se tocaron: no hay un solo fichero de mi propiedad entre ellas.

## Alcance de los cambios

`git diff --name-only b4c8e3e2` → 204 rutas: `.gitattributes`, `.gitignore`, `uv.lock`,
3 scripts, 4 tests y 193 ficheros bajo `reports/ai-bots/`. Nada bajo `data/`, `config/risk`,
`config/strategy_admission.json`, `src/trading_bot/{risk,autonomous,vision,paper}/`.

Los 141 ficheros de `reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/` son de otra lane y se
versionaron **sin editarlos**, porque el manifiesto y el gate V07 los necesitan para
reproducir la campaña desde un clon. Comprobado: **140 son byte-idénticos** al árbol de
`wt-sup001`. El que difiere, `campaign/VERIFICATION.json`, lo reescribió esa lane *después*
de la captura (16 334 → 16 833 bytes): el commit guarda la instantánea del momento, no una
copia viva, y así está declarado.

## Defectos abiertos

Los cuatro que el mandato pide registrar aparte están en [OPEN_BLOCKERS.md](OPEN_BLOCKERS.md),
con su causa, su evidencia y lo que haría falta para cerrarlos. El más importante sigue
siendo que **no existe una campaña de lock real**: el PASS de V07/V08 es sobre fixture.

## Admisión PAPER

**`NO_GO`.** 0 de 24 estrategias con `admitted_for_paper`, recalculado desde el JSON del
ledger por dos implementaciones distintas, y el fichero es byte-idéntico al de `b4c8e3e2`.
Este RFC no admite nada, no abre sesiones y no toca límites de riesgo.

## Limitaciones de esta verificación

- **La independencia es de método, no de identidad**: el verificador lo escribió el mismo
  agente que hizo las correcciones, en otra pasada y sin reutilizar el código del primero.
  Eso detectó el defecto de CRLF que el constructor había dado por bueno, y es la evidencia
  más fuerte que puedo ofrecer de que la separación funcionó; no sustituye a una persona
  distinta firmando.
- La corrida del clon sobre el commit de cierre no puede quedar dentro de ese mismo commit.
  Queda su comando, su salida y el commit exacto en `RUN_REPORT.json`.
- El PASS de V07/V08 es sobre la campaña fixture, no sobre una campaña real.
- `main` no recibe nada en esta entrega.
