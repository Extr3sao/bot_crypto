# TSK-022 - Multi-Exchange Adapter: BDD (Command 02)

> Documento de escenarios Gherkin ejecutables para TSK-022.
> Consumido por `03-specify.md`, `04-plan.md`, `05-tasks.md`.
> Metodología: `.ai/commands/02-bdd.md`.
> Cross-link pine contract: `tasks/decisions.md ADR-0022 Q5` +
> `tasks/decisions.md ADR-0022 Q4` + `tasks/decisions.md ADR-0013`
> + `docs/specs/TSK-022-multi-exchange-adapter/01-requirements.md` (source).
> Pine contract conftest: step_resolutions viven exclusivamente en
> `tests/bdd/conftest.py` (consolidated home per F5 round-24..27 pine
> contract); este archivo **NO** declara definiciones de step.

---

## 1. Resumen ejecutivo

TSK-022 scenario set cubre los 8 RF-MX- y los 8 CL-N del documento
`01-requirements.md` (sección 4 + sección 6). El set se organiza en
5 categorías:

1. **Resolución**: un id mapea a su adapter correcto (RF-MX-1, RF-MX-2).
2. **Configuración y wiring**: el hub respeta `assets.yaml`'s
   `exchanges:` y `runtime.yaml`'s `exchange_id` (RF-MX-3, RF-MX-6).
3. **Cross-layer enforcement**: scanner / execution / strategies nunca
   ven subclases concretas (RF-MX-4, CL-6).
4. **Integridad contract**: OHLCV retorna `int | float` correctos
   (mirror ADR-0022 Q5); guardas de runtime guardan shape malformado
   (RF-MX-8, CL-3, CL-7).
5. **Modos y sandbox**: paper vs live + sandbox flag per `assets.yaml`
   (RF-MX-3, CL-8).

El Background unifica: 3 BDD scenarios compartidos entre las 16
escenarios del Feature.

## 2. Alcance behaviour-level

### 2.1 En scope (16 scenarios en `bdd/features/multi_exchange.feature`)

- Resolución de id válido y runtime precedence (Scenarios 1, 2, 3).
- Coexistencia de múltiples exchanges + no instanciación eager
  (Scenarios 4, 11).
- Contrato OHLCV rows `int | float` post-Q5 (Scenario 5).
- Cross-layer semantic — Protocol-only at boundaries (Scenarios 6, 14).
- Rate-limit independiente + observabilidad por id (Scenarios 7, 8).
- Reuso de guardas runtime contra shape malformado (Scenarios 9, 15).
- Modos paper y live + sandbox flags (Scenario 16).
- Configuración vacía + error reporting (Scenarios 12, 13, 14).

### 2.2 Fuera de scope (queda para SDD posteriores, no se BDD-ea ahora)

- Casos de arbitraje triangular / smart order routing — quedan
  para Fase 7 (post-TSK-022).
- Live trading real con capital — gateado por Fase 9 release live.
- Multi-tenant API keys cross-exchange.
- Order book imbalance cross-exchange — TSK-203 single-exchange coverage.

## 3. Mapeo de requisitos → escenarios

| ID | Requisito / CL | Scenario(s) en `multi_exchange.feature` | Prioridad |
| - | - | - | - |
| RF-MX-1 | `MultiExchangeConnector` Protocol unificado + typing nativo | #1 + #5 (mirror int+float post-Q5) | P1 (core) |
| RF-MX-2 | Subclases concretas por destino (Binance/Bitunix spot/futures) | #1 + #4 + #11 | P1 |
| RF-MX-3 | Feature flags en `config/assets.yaml` `exchanges:` | #4 + #12 + #13 + #16 | P1 |
| RF-MX-4 | Cross-layer AST pine contract | #6 + #14 | P1 |
| RF-MX-5 | Tests de integración con sandbox per exchange | #16 + #4 (parcial) | P1 |
| RF-MX-6 | `runtime.exchange_id` precedence sin fallback silencioso | #3 + #13 | P1 |
| RF-MX-7 | `MultiExchangeConnector.resolve(id)` lazy-built | #11 | P2 (perf) |
| RF-MX-8 | Reusar `narrow_ccxt_payload` / `narrow_ccxt_ohlcv` runtime guards | #5 + #9 + #15 | P1 |
| CL-1 | Rate-limits divergentes entre exchanges | #7 | P2 (perf) |
| CL-2 | Id no registrado / mal escrito → fail-fast | #2 + #14 (caso paralelo) | P1 |
| CL-3 | ccxt upstream malformado → guard runtime | #9 + #15 | P1 |
| CL-4 | `runtime.exchange_id` vacío durante boot | #13 | P1 |
| CL-5 | Id no soportado por ccxt → ConfigurationError | #14 | P1 |
| CL-6 | Subclase concreta importa `ccxt` directo (no escapa via Protocol) | #6 + #14 (AST + behavioral) | P1 |
| CL-7 | Shape conflict entre subclases para misma ccxt pin | #15 | P2 |
| CL-8 | Sandbox flag mismatched entre modo y per-exchange config | #16 | P1 |

## 4. Métrica de cobertura objetivo

- **RF coverage**: cada uno de los 8 RF-MX- cubierto por ≥ 1 scenario
  → total ≥ 8 scenario-RF mappings; el table de la sección 3 documenta
  ≥ 1 entry per RF.
- **CL coverage**: cada uno de los 8 CL- cubierto por ≥ 1 scenario
  → total ≥ 8 scenario-CL mappings; el table de la sección 3 documenta
  ≥ 1 entry per CL.
- **Background coverage**: 3 step_definitions compartidas (modo paper
  / RUNTIME_EXCHANGE_ID / SUPPORTED_EXCHANGES) — pine contract con
  `tests/bdd/conftest.py`.
- **Independencia entre scenarios**: cada scenario define Given/When/Then
  self-contained. No scenario depende del output de otro.
- **Step resolution**: todas las step_definitions se consolidan en
  `tests/bdd/conftest.py` (Pine contract F5 round-24..27). Step text
  exact match (incluyendo acentos: "está" no "esta").

## 5. Estructura del archivo Gherkin

`<root>/bdd/features/multi_exchange.feature`:

- **Feature:** Multi-exchange adapter (título + descripción de negocio).
- **Background:** 3 Given s compartidos (modo paper + RUNTIME_EXCHANGE_ID
  + SUPPORTED_EXCHANGES).
- **16 Scenarios** (ordenados por categoría, no por ID):
  - Categoría A (Resolución): #1, #2, #3.
  - Categoría B (Config + wiring): #4, #11, #12, #13.
  - Categoría C (Cross-layer + contract): #6, #14, #5.
  - Categoría D (Integridad runtime): #9, #15, #7, #8.
  - Categoría E (Modos + sandbox): #16.

Sin tags `@…` decorativos — pytest-bdd no los necesita para discovery
(`tests/bdd/test_features.py` ya recoge todo `bdd/features/*.feature`
vía `scenarios()`).

## 6. Verificación previa al hand-off `03-specify.md`

Cada uno de los 16 scenarios debe:

1. Ser **ejecutable** end-to-end (no @skip stubs persistentes).
2. Cubrir un RF-MX- o CL- exclusivo (sin doble-mapping; mismo RF
   no aparece dos veces en el table de cobertura).
3. Mantener Given/When/Then en **lenguaje de negocio** (no jerga
   interna como "Protocol", "ccxt", "Protocol wrapper" — querer
   refactor observable del hub es válido siempre que no exponga
   internal class names).
4. Ser **independiente** de otros scenarios (cualquier order debe
   producir el mismo resultado).
5. Tener **step_text exact match** con `tests/bdd/conftest.py`
   (acento + quotes + espacios pine contract).

## 7. Siguiente fase (handoff a `03-specify.md`)

El hand-off a `03-specify.md` recoge los contratos firmes que emergen
del cross-validation entre el set de scenarios aquí y el `01-requirements.md`:

- **Contrato de ids válidos**: ids deben coincidir con los registrados
  en `ccxt.exchanges` y debe existir al menos 1 implementación por
  id (RF-MX-2 + CL-5 pine contract).
- **Contrato de sandbox**: `runtime.mode=paper` + `exchange.sandbox=true`
  debe ser el default; cualquier override requiere ADR nueva.
- **Contrato de guard runtime**: cualquier respuesta malformada
  (RF-MX-8 + CL-3) debe ser atrapada en la frontera del exchange
  antes de propagarse downstream.
- **Contrato cross-layer**: scanner / execution / strategies no pueden
  importar subclases concretas; el test AST lo enforcement (RF-MX-4).

`03-specify.md` traduce estos contratos a tipos frozen y firmas de
método del hub.

## 8. Cross-link pine contract

- `tasks/decisions.md ADR-0022 Q5` — type widening `int | float` per
  Scenario #5 (int+float validation step) + CCXTOHLCVProtocol acceptance.
- `tasks/decisions.md ADR-0022 Q4` — Protocol + runtime guard design
  reused in Scenarios #6, #9, #15.
- `tasks/decisions.md ADR-0013` — cross-layer AST enforcement model
  mirrored in Scenario #14 (CL-6) + #6 (RF-MX-4).
- `tasks/decisions.md ADR-0016` — atomicity of BDD hand-off (single
  file `multi_exchange.feature`, no split per exchange).
- `tasks/decisions.md ADR-0010` — flat-env alias for `RUNTIME_EXCHANGE_ID`
  precedence via Scenario #3 + #13 (RF-MX-6 + CL-4).
- `docs/specs/TSK-022-multi-exchange-adapter/01-requirements.md` —
  source RF/CL inventory reused 1:1 in section 3 mapping table.
- `docs/specs/TSK-103-universe-scanner/02-bdd.md` — template estructural
  para este artifact.
- `tests/bdd/conftest.py` — Pine contract consolidation de step
  resolutions (cualquier step nuevo se anade allá, NO acá).
