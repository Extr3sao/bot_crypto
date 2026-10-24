# BASELINE — CODEX-PAPER-SUPERVISOR-001

Fecha: 2026-10-23 (UTC). Host: `DESKTOP-4CHO695`, Windows. Ámbito: PAPER, un solo host.

## 1. Estado del repositorio en el momento de empezar

| Hecho | Valor |
| --- | --- |
| Checkout compartido | `bot freebuff` en `main` @ `1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22` |
| Linaje PAPER | `60455b460dfb805a934c4307f9778ac8b7ffb562` — **no** es ancestro de `main` |
| Rama anterior | `agent/ai-bots/RFC-TAP-AI-BOTS-003` ya no existe; `.git/logs/HEAD` solo tiene el `reset: moving to main` |
| Worktree de este trabajo | `wt-sup001`, rama `codepaper/supervisor-001`, base `60455b46` |
| Modo | PAPER únicamente; `PAPER_ADMISSION` no se toca |

`main` no contiene `src/trading_bot/vision/`, `src/trading_bot/ops/` ni
`scripts/def_run_019_prospective_run.py`: el runtime PAPER vive en el linaje de `60455b46`.
Por eso el trabajo se hizo en un worktree aislado en vez de resetear el checkout compartido,
que además tiene cambios sin commitear de otro agente (`data/st6/RFC047_RUNTIME_VERIFICATION.json`
modificado, más `_blobs.txt`, `_recover_scan.py`, `_wp308_recover/` sin seguimiento). Nada de
eso se tocó, ni se descartó, ni se commiteó.

Los tres commits que pide el encargo existen en ese linaje, en este orden:

| Commit | Asunto |
| --- | --- |
| `d9b46b72` | Keep the resume lineage so a second recovery replays the same origin |
| `98bcefe7` | Let the linter see the campaign instead of exceptions for it |
| `60455b46` | Stop authorising orders while the kill switch is engaged (tip) |

## 2. Evidencias previas

`reports/*` está en `.gitignore` (línea 55). Ningún commit del repositorio contiene
`reports/ai-bots/CODEX-PAPER-LOCK-CAMPAIGN-001/`, y el checkout reseteado no las tiene en
disco. **Las evidencias de la campaña anterior no se han podido preservar porque no existían
en este estado del repositorio.** Lo que sí sobrevive es el mecanismo y su reproducible:

* `scripts/paper_lock_campaign.py` y `scripts/paper_lock_campaign_verify.py`;
* `tests/unit/ops/test_paper_lock_campaign.py` (campaña sintética + 9 mutaciones);
* `src/trading_bot/ops/session_status.py` y `scripts/paper_session_status.py`;
* los commits `d9b46b72` / `98bcefe7`.

Esta campaña **no reutiliza** ninguna evidencia anterior: escribe su propio directorio y
rechaza uno que ya tenga `STREAM.jsonl`. La campaña previa se documenta como antecedente, no
como prueba de este trabajo.

## 3. Runtime autoritativo y mecanismo de reanudación

* Entrypoint: `scripts/def_run_019_prospective_run.py` → `ProspectiveSession` (PAPER).
  `ProspectiveSession.run()` lanza `LiveModeRefused` para cualquier modo que no sea PAPER; no
  hay ruta de orden live, ni credencial, ni endpoint de exchange privado.
* Reanudación autorizada: el mismo entrypoint con `--resume`. Antes de tocar un lock compara
  la identidad fijada (`capture_session` → `resume_reasons`); una diferencia en commit,
  bytes del runtime, configuración o entorno se rechaza con exit 4
  (`RESUME_IDENTITY_MISMATCH`). Sin procedencia fijada se rechaza (`RESUME_WITHOUT_PROVENANCE`,
  exit 5).
* Exclusión de escritores: `ops.single_writer.SingleWriter` (token + host + pid + arranque del
  proceso + fence) sobre `STREAM.jsonl`, cada `market-1m/<SYMBOL>.jsonl` y cada
  `cycles/cycle-NNNN/ledger.jsonl`. Sólo se reclama un lock cuyo dueño esté **probado** muerto
  (`OWNER_PROCESS_DEAD` / `PID_REUSED`); un dueño vivo o no atribuible se rechaza con código.
* Diagnóstico: `ops.session_status.session_status()` es estrictamente de lectura y decide
  `FAILED / RUNNING / RECOVERING / RECOVERED / READY / ABSENT` a partir de los artefactos.

## 4. Baseline de pruebas

Comando (el mismo antes y después; sin `-m slow`, sin red):

```
.venv/Scripts/python.exe -m pytest tests/unit/ops -m "not slow and not market" -q
```

| Momento | Resultado |
| --- | --- |
| Antes de este trabajo (`60455b46`) | **46 passed, 1 failed** (47 tests) |
| Después de este trabajo | **82 passed, 1 failed** (83 tests) |

El fallo es el mismo en ambos lados y **preexistente**:
`tests/unit/ops/test_windowless.py::test_no_controlled_launcher_can_start_an_unhidden_child`
denuncia `POPEN_WITHOUT_WINDOWLESS` en `scripts/exp004a_verify.py:1216` y en
`tests/unit/ops/test_session_status.py:65`. No se ha silenciado ni se ha excluido: son rutas
ajenas a este encargo y siguen fallando a la vista.

Pruebas añadidas: 31 de supervisor (`tests/unit/ops/test_paper_supervisor.py`), 4 del
verificador (`tests/unit/ops/test_paper_supervisor_verifier.py`) y 1 de diagnóstico
(`test_session_status.py`, línea truncada). Total +36.

### Defecto de entorno encontrado (no de código)

`uv sync --frozen` **no reproduce** el entorno de pruebas: `uv.lock` no contiene `matplotlib`
aunque `pyproject.toml` lo declara como dependencia directa. Frió el entorno con
`ModuleNotFoundError: matplotlib` en la fase de colección. Se resolvió instalando
`matplotlib` en el venv del worktree (`uv pip install`), sin tocar `uv.lock` ni
`pyproject.toml`. Queda registrado como bloqueo reproducible para quien reconstruya el
entorno desde el lock.

## 5. Línea base funcional del feed

Antes de la campaña se ejecutó el entrypoint real una vez (`/tmp/smoke-sup/session`,
BTCUSDT, 1m, 150 s): bootstrap completo, latencia medida (7 647 ms), `cycle 1` persistido y
exit 0. Confirma que el feed y el runtime funcionan en este host en la fecha del informe; no
es evidencia de estrategia ni de rentabilidad.
