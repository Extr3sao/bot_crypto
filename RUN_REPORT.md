# RUN REPORT — TAP-SYNC-UNBLOCK-19 · Recuperar el contrato de configuración

| | |
|---|---|
| **run_id** | `tap-sync-unblock-19-2026-10-26` |
| **rama** | `fix/tap-sync-unblock-19` (aislada, derivada de `sync/uncommitted-main-20261025`) |
| **baseline** | `6381c9f7` = `sync/uncommitted-main-20261025` = `refs/pull/19/head` (PR #19) |
| **commits de la corrección** | `23359fca`, `4cec0f0b`, `afd2c0c6` |
| **HEAD final** | `afd2c0c69e52d833705ce1641119b5ab2b4b0bcb` |
| **ficheros cambiados** | 4 (+541 / −78) |
| **modo** | sin red de trading, sin órdenes, sin claves, sin fusionar ningún PR |
| **FALSE_SUCCESS** | **0** (ningún PASS sin ejecución; los gates en rojo se declaran en rojo) |

---

## 1. DIAGNÓSTICO

### 1.1 Comparación de `src/trading_bot/config/settings.py` en tres refs

| Ref | Líneas | `YamlDirectorySource` | `Settings` | `load_settings` |
|---|---|---|---|---|
| `main` (`e67194e7`) | 346 | clase propia (L82) + `FlatEnvAliasSource` (L127) | `class Settings(BaseSettings)` (L188) + `settings_customise_sources` (L273) | impl. Pydantic real |
| `admission/integration-002` | 346 | **idéntico a `main`, byte a byte** | idéntico | idéntico |
| `sync/uncommitted-main-20261025` (`6381c9f7`, PR #19) | **27** | **ausente** (solo se re-exporta desde `types`) | plano, en `config/types.py` | delegado al stub |

`settings.py` en PR #19 se redujo a un *shim*:

```python
from .types import FLAT_ENV_ALIASES, Settings, load_settings, ROUNDTRIP_COST_BPS, STRATEGY_ADMISSION_CONFIG, ...
```

### 1.2 Consumidores revisados

`config/types.py`, `config/settings_contract.py`, `config/__init__.py`, `config/__main__.py`,
`app.py` (6 llamadas a `load_settings`), `execution/live_gate.py`, `scanner/*`, `paper/*`,
`indicators/registry.py`, `market_data/{wiring,fake,exchange_connector}.py`, y los 6 ficheros
de test que usan `load_settings`/`get_settings`.

### 1.3 Qué comportamiento **real** se había perdido (no solo símbolos)

Sonda idéntica en ambos árboles ([evidence/tap-sync-unblock-19/BEHAVIOUR_PROBE.txt](evidence/tap-sync-unblock-19/BEHAVIOUR_PROBE.txt)):

| Comportamiento | PR #19 (`6381c9f7`) | Restaurado (`afd2c0c6`) |
|---|---|---|
| Dominios `universe/exchange/risk/strategies/indicators/runtime` | **los 6 AUSENTES** (`AttributeError`) | los 6 cargados |
| Los 6 YAML llegan | **no**: `s.exchange is None`, `s.universe is None` | `universe: scalping_universe_v1, 25 pairs, ['1m','3m','5m','15m']`, `exchange: binance/sandbox=True`, `runtime: paper`, `risk.kill_switch_enabled=True` |
| Precedencia `env > YAML > defaults` | **rota**: `TRADING_MODE=live` se ignora (`mode: N/A`) | `TRADING_MODE=live` → **`ValidationError`** (bloqueo LIVE en carga) |
| Validadores de seguridad (kill switch, LIVE vs sandbox, `exchange_id`) | **no se ejecutan** (dataclass sin validadores) | se ejecutan en `load_settings()` |
| Economías inventadas | `ROUNDTRIP_COST_BPS=891`, `STRATEGY_ADMISSION_CONFIG` presentes | **ausentes** |
| Identidad de tipo | `Settings` hereda de `object` | `Settings(BaseSettings)` (Pydantic) |

---

## 2. CORRECCIÓN

| Commit | Contenido |
|---|---|
| `23359fca` | `fix(config): restore the authoritative load_settings and drop the flat stub` — reimplementa `settings.py` (346 líneas: `YamlDirectorySource`, `FlatEnvAliasSource`, `Settings(BaseSettings)`, `load_settings()` con `_Tuned`), reduce `types.py` a re-exportes |
| `4cec0f0b` | `test(config): format and fully type the new regression tests` — 156 líneas de tests de regresión |
| `afd2c0c6` | `fix(market_data): read exchange credentials from the nested settings domain` — corrige la regresión detectada en la validación (ver §5.1) |

**Diff exacto** (`git diff --numstat 6381c9f7..afd2c0c6`):

```
360  16  src/trading_bot/config/settings.py
18   59  src/trading_bot/config/types.py
7     3  src/trading_bot/market_data/exchange_connector.py
156   0  tests/unit/config/test_settings_effective_behaviour.py
```

**Compatibilidad offline mantenida y aislada:** `types.py` sigue re-exportando
`Settings`, `load_settings`, `FLAT_ENV_ALIASES` para las herramientas que importan desde ahí
(`test_settings_effective_behaviour.py::test_types_module_reexports_the_authoritative_objects`).
Ningún módulo devuelve una configuración ficticia: `ROUNDTRIP_COST_BPS` y
`STRATEGY_ADMISSION_CONFIG` desaparecieron y `load_settings()` solo devuelve lo que dicen los
YAML + `.env` + defaults.

**Preservado sin debilitar:** los seis YAML, precedencia `env > YAML > defaults`
(`FlatEnvAliasSource`), `EXCHANGE_API_KEY/SECRET/SANDBOX` (mapeo idéntico a `main`), bloqueos de
LIVE (`live_trading_enabled` + `i_understand_the_risks` + kill switch `risk.kill_switch_enabled`),
resolución de `runtime.exchange_id` contra `universe.exchanges` (fail-closed) y validaciones de
riesgo (`risk.py`, `runtime.py` intactos: **cero cambios en `config/risk*` o límites**).

**Tests de regresión añadidos** (`tests/unit/config/test_settings_effective_behaviour.py`, 7 tests):
efectividad de los 6 YAML, re-export desde `types`, keywords canónicos, `get_settings()` real y
coherente con `load_settings()`, ausencia de constantes del stub y `Settings` como agregador
Pydantic (no dataclass plano). Se comprueba **efecto**, no firma.

---

## 3. VALIDACIÓN

Checkout limpio + `uv run --frozen` (lockfile sin tocar). Tabla completa con los exit codes en
[evidence/tap-sync-unblock-19/COMMANDS.md](evidence/tap-sync-unblock-19/COMMANDS.md).

### 3.1 Importación y recolección

| Prueba | BASELINE `6381c9f7` | FIX `afd2c0c6` |
|---|---|---|
| `from trading_bot.config.settings import YamlDirectorySource, Settings, load_settings` | **`ImportError`** → colección abortada, exit **2** | **exit 0**, `Settings(BaseSettings)` |
| Recolección de `pytest -m "not slow and not market"` | imposible con `test_failfast.py` | **0 errores de colección** |
| `_ccxt_connector()` (runtime) | `…api_key='', sandbox=False` (stub) | `…sandbox=True` (desde `config/exchange.yaml`), exit 0 |

### 3.2 `tests/unit/config/` (failfast + contrato + models + settings + efectividad)

**63 passed, exit 0**, tanto en el worktree como en el clone de verificación.
Incluye `test_failfast.py` (12), `test_settings_public_api.py` (contrato de
`settings_contract.py`, 6), `test_settings.py` (carga YAML, precedencia, config inválida,
bloqueos LIVE/kill switch) y los 7 tests nuevos de efectividad.

### 3.3 Suite completa (`pytest -m "not slow and not market"`)

| Run | Árbol | failed | passed | skipped | errors | Exit |
|---|---|---|---|---|---|---|
| baseline | `6381c9f7` (sin `test_failfast.py`, no recolectable) | 275 | 3187 | 31 | 36 | 1 |
| fix r1 | `4cec0f0b` | 121 | 3352 | 34 | 36 | 1 |
| fix r2 | `4cec0f0b` | 116 | 3360 | 31 | 36 | 1 |
| verify r1 | clone `4cec0f0b` | 119 | 3357 | 31 | 36 | 1 |
| **fix final** | `afd2c0c6` | **116** | **3360** | 31 | **36** | 1 |
| **verify final** | clone `afd2c0c6` | **118** | **3358** | 31 | **36** | 1 |

### 3.4 Análisis estático (diferencias vs baseline, sin ocultar el rojo heredado)

| Gate | BASELINE | FIX | VERIFY | Δ |
|---|---|---|---|---|
| `ruff check .` | 226 (exit 1) | 197 (exit 1) | 197 (exit 1) | **−29** |
| `ruff format --check .` | 475 (exit 1) | 473 (exit 1) | 473 (exit 1) | **−2** |
| `mypy .` | 524 / 69 ficheros (exit 1) | 385 / 54 (exit 1) | 385 / 54 (exit 1) | **−139 / −15** |
| `ruff`+`format` sobre `settings.py`, `types.py`, test nuevo | — | **0 errores / 3 formateados** | idem | limpio |
| `mypy` sobre esos 3 ficheros | — | **exit 0** | idem | limpio |

Los tres gates siguen en **exit 1**: es el rojo heredado de la rama (y de `main`: 130/444/297).
`exchange_connector.py` aporta los 22 ruff + 1 formato de mis 4 ficheros y **ya los tenía**
(verificado con `git show HEAD:<fichero> | ruff format --check` y `ruff check` antes de editar).

---

## 4. VERIFICACIÓN INDEPENDIENTE (`BUILDER != VERIFIER`)

1. **Clone nuevo** `u19-verify-clone` (`git clone --no-hardlinks`, 0 ficheros sucios, `uv sync --frozen`
   propio) en `afd2c0c6`: imports exit 0, `tests/unit/config/` 63 passed, `ruff 197 / format 473 /
   mypy 385` **idénticos** al worktree, suite completa 118F/3358P/36E.
2. **Segundo clone** `u19-base-clone` en `6381c9f7` para atribución de los fallos de clone.
3. **Comparación de conjuntos** (`grep '^FAILED' … | sort -u` + `comm`), reproducible desde los
   logs: [evidence/tap-sync-unblock-19/SET_COMPARISON.txt](evidence/tap-sync-unblock-19/SET_COMPARISON.txt)

Resultado de la atribución:

- **0 fallos nuevos** en el worktree final respecto al baseline.
- **0 errores nuevos**: los 36 errores son conjuntos idénticos (22 `test_ccxt_connector` + 14
  `test_profitability_gate035`), [evidence/tap-sync-unblock-19/CCXT_PREEXISTENCE.txt](evidence/tap-sync-unblock-19/CCXT_PREEXISTENCE.txt).
- **159 fallos arreglados**.
- 115 fallos estables en los 3 primeros runs → **0 fuera de la baseline**.
- 4 fallos solo en el run1 (`monitor/test_api[PUT]`, 3× `st6_scheduler`) → **pasan aislados en
  ambos árboles** (8 passed) = dependientes de orden/estado.
- 3 fallos solo en clones (`rfc048`) → **se reproducen igual en un clone del baseline** por
  `core.autocrlf=true` = ambiental.

---

## 5. DEFECTOS

### 5.1 Regresión introducida por esta corrección y corregida aquí

`_ccxt_connector()` leía los campos planos del stub (`exchange_api_key/secret/sandbox`); con el
contrato restaurado eso era `AttributeError` (reproducido antes de corregirlo). Corregido en
`afd2c0c6` leyendo `settings.exchange.{api_key,api_secret,sandbox}` — la misma ruta anidada que
usa `app.py`. **Sin** cambios de análisis estático en el fichero (22 ruff / 23 mypy antes y
después, ambos heredados).

### 5.2 Preexistentes (no introducidos por esta rama; documentados aparte)

| # | Defecto | Evidencia |
|---|---|---|
| D1 | `test_ccxt_connector` construye `CCXTExchangeConnector(exchange_cfg)` pero `__init__` es `(api_key, secret, …)` → `TypeError` en el fixture → **22 errores** | mismo `TypeError` en BASELINE y FIX |
| D2 | 14 errores de fixture en `test_profitability_gate035.py` | igual en ambos |
| D3 | ~115 fallos estables (`tests/unit/research/**`, `monitor/test_api`, `test_ohlcv_fetcher`, admission ledger…) | todos presentes en la baseline |
| D4 | Gates estáticos en rojo en todo el repo (197/473/385) | baseline 226/475/524; `main` 130/444/297 |
| D5 | `wiring._binance_builder` pasa una instancia `Exchange` donde `_ccxt_connector` espera un callable → `TypeError: 'Exchange' object is not callable` | **idéntico en BASELINE y FIX** (sin cobertura de tests; fichero de otro carril, no tocado) |
| D6 | `data/rfc048/**` falla en un clone limpio con `core.autocrlf=true` (CRLF vs digest LF) | clone del baseline: 3 failed; worktree: 11 passed |
| D7 | Tests dependientes de orden (4) | pasan aislados en ambos árboles |
| D8 | `exchange_connector` traga el `ImportError` de `config.settings` y cae a `Settings()` | no es configuración ficticia (ese `Settings()` sigue cargando los 6 YAML vía `settings_customise_sources`), pero oculta errores de importación; **no modificado** (fuera de alcance) |

---

## 6. BLOQUEOS QUE SIGUEN ABIERTOS

1. **La rama no está publicada** (`gh` no está disponible en esta máquina y no se pidió push):
   el PR que desbloquea #19 hay que abrirlo/pushearlo desde fuera.
2. **Gates del tronco en rojo** (preexistentes): ruff 197, format 473, mypy 385 y
   `pytest` con ~116 fallos heredados; cobertura por debajo del 90 %.
3. **PR #19 sigue `BLOCKED`** hasta que su rama incorpore estos commits (esta rama parte de su
   HEAD, es fast-forward).
4. Nada de runtime certificado: `REAL_MODEL_CALLED = false`, PAPER no ejecutado, `PROFITABLE = false`.

## 7. EVIDENCIA

[evidence/tap-sync-unblock-19/](evidence/tap-sync-unblock-19/) — `COMMANDS.md`,
`PYTEST_SUMMARY.txt`, `SET_COMPARISON.txt`, `STATIC_ANALYSIS.txt`, `BEHAVIOUR_PROBE.txt`,
`COLLECTION_BASELINE.txt` (fallo de colección original), `CCXT_PREEXISTENCE.txt`.

## 8. PROHIBICIONES CUMPLIDAS

No se fusionó #18 ni #19 · no se ejecutó ninguna orden real · ningún límite de riesgo modificado
(`config/risk*` intocado) · sin `reset --hard`, `clean`, `push`, `rebase` ni borrado de
worktrees/ramas/stashes · sin secretos ni `.env` tocados · sin funcionalidad nueva · sin evidencia
inventada (todos los valores de este informe salen de logs capturados).

## 9. SIGUIENTE ACCIÓN

Publicar `fix/tap-sync-unblock-19` y abrir PR **contra `sync/uncommitted-main-20261025`**
(fast-forward, sin tocar #18/#19); con ello la colección de #19 pasa a 0 errores. En paralelo,
el carril de `main` debe atacar D1–D4 (son los que mantienen el tronco en rojo).
