# TAP-SYNC-UNBLOCK-19 — comandos ejecutados y exit codes reales

Todos los comandos se ejecutaron con `uv run --frozen` (lockfile intacto) desde la rama/árbol
indicado. Los `EXIT=` están capturados **sin tuberías** (redirección a fichero + `$?`), salvo
donde se indica explícitamente `PIPESTATUS`.

- **BASELINE** = worktree `u19-baseline-wt` @ `6381c9f7` (= `sync/uncommitted-main-20261025` = `refs/pull/19/head`)
- **FIX** = worktree `sync-unblock19-wt` @ `afd2c0c6` (rama `fix/tap-sync-unblock-19`)
- **VERIFY** = `git clone --no-hardlinks` nuevo `u19-verify-clone` @ `afd2c0c6` (`BUILDER != VERIFIER`)
- **BASE-CLONE** = `git clone` nuevo `u19-base-clone` @ `6381c9f7` (solo para atribución)

## 1. Diagnóstico (solo lectura)

| Comando | Árbol | Exit |
|---|---|---|
| `git show <ref>:src/trading_bot/config/settings.py` para `e67194e7`, `admission/integration-002`, `6381c9f7` | main checkout | 0 |
| `grep -rn "load_settings(\|get_settings(" src tests` | FIX/BASE | 0 |
| `git ls-remote origin refs/pull/19/head` → `6381c9f7` | main checkout | 0 |
| `grep -c YamlDirectorySource <ref>:settings.py` → main 5 / admission 5 / sync 1 (re-export) | main checkout | 0 |

## 2. Recolección e importación

| Comando | Árbol | Resultado | Exit |
|---|---|---|---|
| `uv run --frozen pytest -m "not slow and not market" -q` (con `test_failfast.py`) | BASELINE | `ImportError: cannot import name 'YamlDirectorySource'` → `3 deselected, 1 error` | **2** |
| `uv run --frozen python -c "from trading_bot.config.settings import YamlDirectorySource, Settings, load_settings, get_settings"` | VERIFY | `YamlDirectorySource= YamlDirectorySource \| Settings bases= ['BaseSettings']` | **0** |
| `uv run --frozen python -c "…_ccxt_connector()"` | VERIFY | `CCXTExchangeConnector(name='ccxt', sandbox=True, api_key='', secret='', options=None)` | **0** |

## 3. Suite de tests

Todos: `uv run --frozen pytest -m "not slow and not market" -q`.

| Run | Árbol/commit | Resultado | Exit | Duración |
|---|---|---|---|---|
| baseline | BASELINE `6381c9f7`, con `--ignore=tests/unit/config/test_failfast.py` (imposible de recolectar) | 275 failed, 3187 passed, 31 skipped, 3 deselected, **36 errors** | 1 | 473 s |
| fix r1 | FIX `4cec0f0b` | 121 failed, 3352 passed, 34 skipped, 3 deselected, 36 errors | 1 | 460 s |
| fix r2 | FIX `4cec0f0b` | 116 failed, 3360 passed, 31 skipped, 3 deselected, 36 errors | 1 | 664 s |
| verify r1 | VERIFY clone `4cec0f0b` | 119 failed, 3357 passed, 31 skipped, 3 deselected, 36 errors | 1 | 760 s |
| **fix final** | FIX `afd2c0c6` | **116 failed, 3360 passed, 31 skipped, 3 deselected, 36 errors** | 1 | 701 s |
| **verify final** | VERIFY clone `afd2c0c6` | **118 failed, 3358 passed, 31 skipped, 3 deselected, 36 errors** | 1 | 692 s |

| Comando dirigido | Árbol | Resultado | Exit |
|---|---|---|---|
| `pytest tests/unit/config/ -q` | FIX `afd2c0c6` | **63 passed** | **0** |
| `pytest tests/unit/config/ -q` | VERIFY clone `afd2c0c6` | **63 passed** | **0** |
| `pytest tests/unit/config/ -v --tb=short` | VERIFY clone | 63 passed (failfast + contrato/public_api + models + settings + efectividad) | 0 |
| `pytest tests/unit/market_data/ -q --tb=no` | FIX | 25 failed, 56 passed, 22 errors | 1 |
| `pytest tests/unit/market_data/ -q --tb=no` | BASELINE | 39 failed, 42 passed, 22 errors | 1 |
| `pytest tests/unit/risk/test_rfc048_provenance_integrity.py -q` | FIX | 11 passed | 0 |
| `pytest tests/unit/risk/test_rfc048_provenance_integrity.py -q` | BASE-CLONE | 3 failed, 8 passed (autocrlf) | 1 |
| `pytest tests/unit/market_data/test_ccxt_connector.py::test_connector_is_exchange_connector -q --tb=line` | FIX y BASELINE | `TypeError: CCXTExchangeConnector.__init__() missing 1 required positional argument: 'secret'` en **ambos** | 1 / 1 |
| `pytest` de los 4 tests que solo fallaban en el run1 (monitor PUT, 3× st6) | FIX y BASELINE | **8 passed en ambos** | 0 / 0 |

## 4. Análisis estático

| Comando | Árbol | Resultado | Exit |
|---|---|---|---|
| `ruff check .` | BASELINE | 226 errors | 1 |
| `ruff check .` | FIX `afd2c0c6` | **197 errors** | 1 |
| `ruff check .` | VERIFY clone `afd2c0c6` | **197 errors** | 1 |
| `ruff format --check .` | BASELINE | 475 a reformatear / 387 OK | 1 |
| `ruff format --check .` | FIX `afd2c0c6` | **473 a reformatear / 390 OK** | 1 |
| `ruff format --check .` | VERIFY clone `afd2c0c6` | **473 / 390** | 1 |
| `mypy .` | BASELINE | 524 errors en 69 ficheros (856 comprobados) | 1 |
| `mypy .` | FIX `afd2c0c6` | **385 errors en 54 ficheros** (857 comprobados) | 1 |
| `mypy .` | VERIFY clone `afd2c0c6` | **385 / 54** | 1 |
| `ruff check settings.py types.py exchange_connector.py test_settings_effective_behaviour.py` | FIX | 22 errors, **todos de `exchange_connector.py` (heredados)** | 1 |
| `ruff format --check` (mismos 4 ficheros) | FIX | 1 a reformatear (`exchange_connector.py`, heredado) / 3 OK | 1 |
| `ruff check settings.py types.py test_settings_effective_behaviour.py` | FIX | `All checks passed` | 0 |
| `ruff format --check` (esos 3) | FIX | `3 files already formatted` | 0 |
| `mypy settings.py types.py test_settings_effective_behaviour.py` | FIX y VERIFY | `Success: no issues found in 3 source files` | 0 |

## 5. Git (solo local)

| Comando | Exit | Nota |
|---|---|---|
| `git worktree add --detach u19-baseline-wt 6381c9f7` | 0 | baseline aislado |
| `git worktree add fix/... sync-unblock19-wt` | 0 | rama aislada derivada de `sync/uncommitted-main-20261025` |
| `git merge-base --is-ancestor sync/uncommitted-main-20261025 HEAD` | 0 | `ANCESTRO_SI`, +3 commits |
| `git commit` (×3) | 0 | `23359fca`, `4cec0f0b`, `afd2c0c6` |
| `git clone --no-hardlinks <repo> u19-verify-clone` | 0 | verificación independiente |

**No ejecutado (prohibido / fuera de alcance):** `git push`, `git merge`, `gh pr create`,
`reset --hard`, `clean -fd`, `push --force`, `rebase`, borrado de worktrees/ramas/stashes,
cualquier orden real de trading, modificación de `config/*.yaml` o de límites de riesgo.
