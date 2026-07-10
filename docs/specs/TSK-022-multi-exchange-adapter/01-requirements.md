# TSK-022 - Multi-Exchange Adapter: Requirements (Command 01)

> Documento de requisitos elicitados para el adaptador multi-exchange.
> Consumido por `02-bdd.md`, `03-specify.md`, `04-plan.md`, `05-tasks.md`.
> Metodología: `.ai/commands/01-requirements.md`.
> Estado del ticket: `tasks/backlog.md` (sección "Tickets Fase 1").
> Cross-link pine contract: `tasks/decisions.md ADR-0022 Q5` Consecuencias
> `Forward-looking unblock` block + `ADR-0013` cross-layer precedent +
> `ADR-0006` baseline + `ADR-0008` forward-reference (este ticket materializa
> la reserva histórica de "sustitución del exchange" firmada en ADR-0006).

---

## 1. Resumen ejecutivo

TSK-022 expande la capa de inyección de market data y ejecución de órdenes
para soportar el enrolamiento dinámico de múltiples exchanges en paralelo.
Retira el acoplamiento a una única instancia de `CCXTExchangeConnector`
delegando a un patrón `MultiExchangeConnector(Protocol)` con subclases
concretas por exchange (`BinanceConnector`, `BitunixSpotConnector`,
`BitunixFuturesConnector`). El trabajo queda formalmente **desbloqueado**
por la resolución del workaround de tipos base — `CCXTOHLCVProtocol`
acepta `int | float` rows nativamente tras `b4b543d` (ADR-0022 Q5) — lo
que retira el `cast(list[list[float]])` que era el headline blocker.

## 2. Reconciliación del ID (Decision D1)

El user invocó la sugerencia previa de abrir la entrada como `TSK-105`,
pero `TSK-105` en `tasks/backlog.md` está **ya ocupado**:

```bash
$ grep -nA3 '\*\*TSK-105\*\*' tasks/backlog.md
- [ ] **TSK-105** Tests:
  - [ ] unit: conector contra un CCXT mock. **Est: S**. Depende de: TSK-101.
  - [ ] integration: fetch real desde testnet y lectura de datos. **Est: M**.
        Depende de: TSK-101, TSK-103.
```

`TSK-105` está scoped exclusivamente a **paper-trading tests** (unit +
integration con testnet Binance). Reutilizar el ID fusionaría silenciosamente
dos alcances desvinculados — anti-pattern explícitamente prohibido bajo
`ADR-0016` ("un PR grande acumula risk" + el corollary "dos scopes al mismo
ID acumulan drift"). Slots fundacionales libres en la serie pre-100 tras
el cierre de `TSK-021` (credentials rotation, firmado en ADR-0021):

- `TSK-011` through `TSK-020`: libres (siguen al TSK-013.X sweep ya cerrado).
- `TSK-021`: ocupado (credentials rotation ticket retroactivo PineABLE per
  ADR-0021).
- `TSK-022`: primer slot fundacional libre post-TSK-021.

Series ≥ TSK-100 reservadas para scope de sprint (`TSK-100..TSK-105`,
`TSK-200..TSK-204`, `TSK-860`). Para un ticket estructural Fase 1
cross-cutting que pine el pre-100 slot, **TSK-022 es el siguiente ID
fundacional libre**.

**Decision**: opcion D1-b — abrir como **TSK-022 - Multi-exchange adapter**.
Esta ADR firmada (ADR-0022 Q5 ya cita el ticket futuro como TSK-105
multi-exchange; renumeramos a TSK-022 acá) + cross-link pine contract
per ADR-0020 numbering note precedent.

## 3. Alcance

### 3.1 En scope (TSK-022 F1–F4)

- Sustitución del actual `CCXTExchangeConnector` genérico por un
  `MultiExchangeConnector(Protocol)` que unifique tipos estandarizados.
- Implementación de subclases de extension: `BinanceConnector`,
  `BitunixSpotConnector`, `BitunixFuturesConnector` (3 hoy; espacio
  para futuras per `config/assets.yaml`).
- Router dinámico basado en un `frozenset[str] SUPPORTED_EXCHANGES`
  configurado por YAML (no hardcoded per ADR-0006).
- Endurecimiento del cross-layer enforcement: scanner / strategies /
  execution solo importan el Protocol abstracto, nunca las subclases
  concretas (mirror ADR-0013 AST pine contract).
- Wiring con `Settings` real + `runtime.mode` (paper | live) per
  `ADR-0010` flat-env alias context.
- Tests de integración con sandbox por exchange habilitado (ccxt
  sandboxed instances o fake exchange mock).
- Reserva robusta de `runtime.exchange_id` precedence: el hub toma el
  exchange_id del modo activo del runtime, sin fallback silencioso a
  Binance.

### 3.2 Fuera de scope (TSK-022, sigue en tickets posteriores)

- Lógica de arbitraje real triangular/cross-exchange.
- Smart order routing con scoring (e.g. mejor precio para una misma
  pair entre exchanges). Queda para Fase 7 (risk routing) ticket
  posterior.
- Live trading directo con capital real — sigue gateado bajo Fase 9
  (`docs/live-trading-checklist.md` + release gate per `11-release-live.md`).
- Nueva capa de seguridad para API keys multi-tenant (queda para Fase 8
  cuando entre live trading).
- Order book imbalance cross-exchange aggregation (TSK-203 cubre single
  exchange; multi-exchange queda para Fase 8+).

### 3.3 In scope cross-layer changes (acotados)

- `src/trading_bot/market_data/exchange_connector.py` — refactor: el
  actual `CCXTExchangeConnector` se renombra / extrae a
  `BinanceConnector(ccxt.binance)`, mantiene logic.
- `src/trading_bot/market_data/bitunix.py` — `BitunixAPI` se rebautiza
  via subclass `BitunixSpotConnector`.
- `src/trading_bot/market_data/bitunix_futures.py` — `BitunixFutures`
  se rebautiza via subclass `BitunixFuturesConnector`.
- `src/trading_bot/market_data/__init__.py` — re-exports para los
  3 connectors concretos (behind `if TYPE_CHECKING:`).
- `src/trading_bot/market_data/types.py` — nueva entry
  `MultiExchangeConnector(Protocol)` con `BinanceConnector`, etc.,
  declaradas como `runtime_checkable` para uso de `isinstance` checks
  en tests.
- `tests/unit/market_data/test_cross_layer.py` (NEW per ADR-0013
  pattern) — AST parse test que falla si scanner / execution /
  strategies importan subclases concretas; permite solo el Protocol.
- `config/assets.yaml` — sección `exchanges:` (lista con id + enabled
  flag + sandbox flag + type ["spot"|"futures"]).
- `config/runtime.yaml` — `mode` (paper | live) ya existe; nuevo
  campo `exchange_id` opcional con override precedence per ADR-0010.

## 4. Requisitos funcionales (RF)

| ID | Requisito | Criterio de aceptación |
| - | - | - |
| RF-MX-1 | Un único `MultiExchangeConnector(Protocol)` provee el wrapper agnóstico de `place_order / fetch_ohlcv / fetch_balance / create_order` sobre múltiples orígenes. | Módulo define base Protocol con typing nativo (int+float en OHLCV rows heredado de Q5). |
| RF-MX-2 | Subclases adaptadoras explícitas por destino: `BinanceConnector`, `BitunixSpotConnector`, `BitunixFuturesConnector`. | Cada subclase hereda el Protocol + abstrae sus IDs propios de cliente (clientOid, positionId, etc.). |
| RF-MX-3 | Las habilitaciones por exchange descansan en feature-flags dentro de `config/assets.yaml` con prefijo `exchanges: [{id: ..., enabled: ..., sandbox: ..., type: ...}]`. | `SUPPORTED_EXCHANGES` se computa per `frozenset([e["id"] for e in assets_yaml["exchanges"] if e["enabled"]])`; missing required key → config fail-fast en `Settings._check_cross_domain_live_invariants`. |
| RF-MX-4 | Cross-layer AST pine contract: módulos superiores (`scanner`, `execution`, `strategies`) solo ven el Protocol abstracto, no orígenes concretos. | Test `tests/unit/market_data/test_cross_layer.py` parsea AST y falla build si encuentra `import trading_bot.market_data.bitunix` o similar dentro de scanner/execution/strategies (mirror ADR-0013 enforcement). |
| RF-MX-5 | Tests de integración con un sandbox encendido por cada exchange habilitado (ccxt sandboxed instances o fake exchange mock). | Verificación fixture con mock payload real por subclase. Coverage ≥ 90% sobre los 3 connectors. |
| RF-MX-6 | `runtime.exchange_id` (per `config/runtime.yaml`) selecciona el adapter para una session; sin fallback silencioso. | `RuntimeError("No matching exchange_id")` si el id no está en `SUPPORTED_EXCHANGES` + clear remediation message. |
| RF-MX-7 | `MultiExchangeConnector.resolve(id)` retorna una instancia concretada lazy-built (no eager-instanciación global) para evitar cost-of-connection en tests no-live. | Test verifica que `pytest --last-failed` no deja conexiones residuales entre runs. |
| RF-MX-8 | Reuso de los `narrow_ccxt_payload` / `narrow_ccxt_ohlcv` runtime guards pineados en Q4. | Ningún site site específico puede saltarse el narrow post-Q5; el nuevo Protocol reusa los guards. |

## 5. Requisitos no funcionales (RNF)

| ID | Requisito | Criterio |
| - | - | - |
| RNF-1 | Conformidad estricta Mypy bajo `"strict"` (`pyproject.toml`). | Sin usar `cast(...)` coercitivos en OHLCV (gracias a ADR-0022 Q5 acepta `int | float` nativo). |
| RNF-2 | Rate-Limit transparency. | Envolver llamadas en decorators tenacity idempotentes per exchange, respetando `options.enableRateLimit` del gateway ccxt elegido. |
| RNF-3 | Reproducibilidad determinística bit-exact (mirror F3 mirror contract). | Tests reproducibles con `seed=42` per `ADR-0018` precedent. |
| RNF-4 | Logging estructurado por exchange + por session_id. | structlog binding con `event=multi_exchange.*` tag + `exchange_id` field always present. |
| RNF-5 | `mypy_residual == 0` post-F4 — sin re-introducir `disable_error_code = ["no-any-return"]` ni otros override blocks per Q4 discipline. | Override-removal discipline heredada de ADR-0022 Q4. |
| RNF-6 | Sin bloqueos I/O cross-exchange: `asyncio` coherente con ADR-0006. | `await connector.fetch_ohlcv(...)` para futuros use-cases async. |
| RNF-7 | Memoria por session < 80 MB (4 connectors activos simultáneos). | `tracemalloc` snapshot al boot. |

## 6. Casos límite y modos de fallo (CL)

| ID | Caso | Mitigación |
| - | - | - |
| CL-1 | Múltiples exchanges con rate-limits divergentes. | Cada subclase mantiene su propia instancia ccxt y su propio decorador retry independizado (decorator pino por exchange, no compartido). |
| CL-2 | Solicitud a exchange no registrado / mal escrito. | Fail fast durante `MultiExchangeConnector.resolve(id)` → `RuntimeError` con remediation message ("valid ids: {sorted(SUPPORTED_EXCHANGES)}"). |
| CL-3 | ccxt upstream malformado (shape mismatch per Q4 + Q5). | `narrow_ccxt_payload` / `narrow_ccxt_ohlcv` runtime guards activan en el Protocol wrapper y lanzan `RuntimeError("protocol violation")` antes de propagar al consumer (mirror Q4 Consecuencias). |
| CL-4 | `runtime.exchange_id` vacío durante boot. | `_check_cross_domain_live_invariants` rejects en failfast per ADR-0010 + ADR-0016 R1. |
| CL-5 | `config/assets.yaml` lista un id que ccxt no soporta (`exchanges: [{id: "fanta-exchange"}]`). | `__init__` del HubRaises `ConfigurationError` con listado de supported ids per `ccxt.exchanges` API. |
| CL-6 | Subclase concreta importa `ccxt` directamente (violates ADR-0013). | AST test cross-layer reviewed en CI: subclass imports `ccxt` allowed; scanner/strategies/execution imports of class concreto banned. |
| CL-7 | Dos subclases retornan shape conflict para misma ccxt version pin. | Hub normaliza via runtime guards `narrow_ccxt_*` antes de delivery. |
| CL-8 | `runtime.mode=paper` + `exchange_id=binance` vs `bitunix` → sandbox flag mismatched. | Sandbox fallback per exchange by `assets_yaml["exchanges"][i]["sandbox"]`, validated at boot. |

## 7. Dependencias y asunciones

- **`tasks/decisions.md ADR-0022 Q5`** (commit `b4b543d`) — type widening
  unblocks the Protocol design sin `cast()`, formal forward-looking
  reference. Esta entrada es el sub-ticket planeado.
- **`tasks/decisions.md ADR-0022 Q4`** — Protocol + runtime guard pattern
  se reusa; la nueva `MultiExchangeConnector` los envuelve.
- **`tasks/decisions.md ADR-0013`** — cross-layer enforcement pine contract
  (AST test pattern) se hereda para los nuevos Per-exchange subclasses.
- **`tasks/decisions.md ADR-0016`** — method (`cast()` preferida sobre
  `# type: ignore`) y atomic-chore per-file batching se respeta.
- **`tasks/decisions.md ADR-0010`** — flat-env alias context para
  `runtime.exchange_id` precedence.
- **`tasks/decisions.md ADR-0006`** — Binance via CCXT baseline, no se
  invalida; este ticket lo superset-multiplica.
- **`tasks/decisions.md ADR-0008`** — reserva "sustitución del exchange"
  firmada en 2026-07; este ticket materializa ese design forward.
- **`docs/specs/TSK-103-universe-scanner/01-requirements.md`** — template
  estructural; secciones RF / RNF / CL / DoD replicadas.

**Asunciones**:

- El scheduler (TSK-104) invocará al scanner que a su vez selectará el
  exchange via `runtime.exchange_id`. TSK-022 expone
  `MultiExchangeConnector.resolve(id) -> PerExchangeConnector` y NO
  incluye connection-pool scheduler interno.
- Las estrategias (Fase 4, tickets `TSK-4xx`) consumirán datos de
  cualquier connector subsumido en el Protocol; los `MarketSnapshot`
  no llevan `exchange_id` field — se transporta via runtime context.
- La capa `paper/broker.py` (TSK-105 paper trading harness) consume
  el connector seleccionado via `runtime.exchange_id` — el refactor
  no rompe contratos existentes si `RF-MX-6` resuelve limpio.

## 8. Criterios de aceptación global

1. RF-MX-1..RF-MX-8 implementados + verificados con tests sentinels
   (≥ 1 sentinel por RF).
2. RNF-1..RNF-7 satisfied: mypy strict verde, ruff clean, pytest ≥ 90%
   coverage sobre `src/trading_bot/market_data/`.
3. CL-1..CL-8 covered sentinels explicitos.
4. Cross-layer AST test (`tests/unit/market_data/test_cross_layer.py`)
   verde: scanner / execution / strategies NO importan subclases
   concretas.
5. `config/assets.yaml` documenta con un ejemplo de 3 exchanges habilitados
   (binance + bitunix_spot + bitunix_futures con sandbox=true para paper).
6. `config/runtime.yaml` con `exchange_id: binance` (paper baseline +
   default explicito per ADR-0010 precedence).
7. Reviewer verdict = clean (sin P0).
8. PR abierto con dual-review per `.github/CODEOWNERS`
   (`market_data/` + `config/` paths sensibles).
9. SPRINT-003 transition plan: tickets TSK-104 (engine) + TSK-105 (paper
   harness) consume via nuevo hub sin breakage.

## 9. Siguiente fase (handoff a `02-bdd.md`)

Los RF-MX-1..RF-MX-8 y CL-1..CL-8 se traducen a escenarios Gherkin en
`bdd/features/multi_exchange.feature` (nuevo file) — escenarios de éxito
(un id mapea a su connector correcto + un OHLCV row valido), escenarios
de fallback (id mal escrito rechaza loud), escenarios cross-layer
(scanner pide datos sin saber el exchange_id specifics), y escenarios de
runtime guard (`narrow_ccxt_*` activado ante payload malformado).

El ID-shift rationale (TSK-105→TSK-022) queda documentado también en la
sección `Nota de colisión de ID` de `tasks/backlog.md` para que futuros
oncall/TFs entiendan por qué el ticket "multi-exchange adapter" no es el
TSK-105 paper-trading tests.
