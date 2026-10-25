# G-5 — Paper end to end

**Commit:** `05b361f7bd26a4fb9d470d9ba5c68d7f967846c9`  
**Modo:** `PAPER_ONLY` · sin credenciales · sin clientes de exchange · sin órdenes reales  
**Evidencia:** `evidence.json`, `verification.json`

## 1. El comando

El entrypoint operativo es el que ya existía:

```bash
.venv/Scripts/python.exe scripts/start_paper_trading.py \
  --assets BTC --max-cycles 1 --interval 0 --provider fake \
  --fresh --state-path <run>/production/state.json \
  --run-dir <run>/production/run
```

Ejecuta el motor real y termina en `NO_TRADE` porque el ledger comprometido
`config/strategy_admission.json` no admite ninguna estrategia:

```text
[registry] paper-executable on 5m: NONE
contexts_built=1 router_invocations=1 strategy_invocations=0
orders_created=0 rejections=[NO_TRADE:no_strategy_passed_gates]
exit 0
```

Eso es un resultado legítimo, no un fallo: el runtime se niega a inventar una
estrategia. La evidencia de una operación completa usa el runner controlado:

```bash
.venv/Scripts/python.exe scripts/audit/g5_paper_e2e.py \
  --out docs/audit/runs/run-20261025T131004Z-G-5
```

El runner compone **el mismo** `build_cycle_engine` del launcher, con datos
sintéticos deterministas, un reloj fijado y un ledger de admisión controlado
(`docs/audit/fixtures/g5_paper_ledger.json`, `CONTROLLED_TEST_FIXTURE`). No es
una admisión de producción y no se presenta como evidencia de edge.

## 2. Recorrido ejecutado

```text
FakeMarketDataSource (100 velas 5m deterministas)
  → UniverseScanner (volume, spread, ATR)
  → MarketSnapshot
  → FetcherBarReader (PIT, closed-candle filter)
  → CryptoAssetAgentRegistry
  → StrategyRouter (freshness, régimen, admisión)
  → EmaCrossoverFamily
  → SignalAdapter
  → CandidatePortfolio
  → RiskManager.check_signal        → approved, size, SL/TP
  → HotStopGate.order_boundary      → lock + marker/process switch
  → PaperBroker.execute_signal      → fill, comisión, spread, slippage
  → PaperBroker.reconcile_session   → SL/TP, PnL, equity
  → PaperStateStore.save            → JSON atómico
  → StartupReconcilerV4.reconcile   → RECOVERED en el siguiente proceso
```

## 3. Escenarios y resultados

Todos los escenarios se ejecutaron en el mismo comando. El reloj está fijado en
**miércoles 2026-10-21 12:00 UTC** porque la política comprometida prohíbe
operar en fin de semana. El valor por defecto de producción sigue siendo el
reloj de pared.

| Escenario | Observación | Órdenes | Posiciones | PnL | Estado | Resultado |
|---|---|---:|---:|---:|---|---|
| `TRADE` | 1 señal, riesgo aprobado, 1 fill | 1 | 1 abierta | 0 (aún abierta) | 908 B, 1 intent | PASS |
| `RESTART` | `RECOVERED`: 1 posición + 1 intent restaurados; sin reapertura; cierre TP | 0 | 0 | +49.390016 | 1.387 B, 1 cerrada | PASS |
| `NO_TRADE` | mercado plano, `no_alpha_in_direction:ANY` | 0 | 0 | 0 | 476 B | PASS |
| `STALE` | `NO_TRADE:stale_context` | 0 | 0 | 0 | 476 B | PASS |
| `KILL_SWITCH` | marker; `risk_accepted=1`, `hot_stop_blocked=1`, broker 0 llamadas | 0 | 0 | 0 | 476 B | PASS |
| `EXCEPTION` | proveedor lanza; `scanner_errors=1`, 0 snapshots | 0 | 0 | 0 | 476 B | PASS |

### 3.1 TRADE

- `contexts_built=1`, `router_invocations=1`, `strategy_invocations=1`,
  `signals_generated=1`, `risk_accepted=1`, `orders_created=1`.
- `PaperBroker.execute_signal` llamado exactamente 1 vez.
- Posición: `BTC/USDT`, `buy`, notional 500 USDT, `stop_loss_pct=1.5038`,
  `take_profit_pct=0.75`, `position_id=pos-g5-trade-00000001`.
- Estado durable: 1 posición abierta, 1 `cloid`, equity 10.000 (la comisión de
  entrada queda devengada, no se resta dos veces).
- Latencia extremo a extremo del escenario: 9,81 ms.

### 3.2 RESTART

- Nuevo `PaperBroker`, nuevo `PaperCycleEngine`, nuevo `StartupReconcilerV4`,
  mismo fichero de estado.
- `reconciliation_before.status=RECOVERED`, `restored_open_positions=1`,
  `restored_intents=1`, `restored_equity=10.000`.
- La sesión ve la posición restaurada: `same_side_skips=1`, `orders_created=0`,
  `execute_signal=0`.
- El precio sube un 10 %; `reconcile_session` cierra por `take_profit`.
- `ClosedTrade.pnl=+49.390016`, equity `10.049.390016`; la identidad
  `equity == initial + Σ pnl` y las identidades de costes son verdaderas.
- Estado final: 0 posiciones, 1 trade cerrado, 1 intent; 1.387 B.
- Es un **reinicio lógico**: instancias nuevas y estado releído del disco, no un
  `kill -9` del proceso.

### 3.3 NO_TRADE y STALE

- Plano: el router sí ejecuta, la familia no genera señal, 0 órdenes y razón
  `no_alpha_in_direction:ANY`.
- Stale: velas 3 h por detrás del reloj de decisión; `router_no_trade=1`,
  `NO_TRADE:stale_context`, 0 órdenes y 0 llamadas al broker.

### 3.4 KILL_SWITCH

El marker se escribe **antes** de construir el gate, que lo adopta en el
constructor. La secuencia observada es la que importa:

```text
señal=1 → risk_accepted=1 → hot_stop_blocked=1
        → PaperBroker.execute_signal=0 → órdenes=0
```

El stop no se evalúa antes de riesgo ni se sustituye por un rechazo genérico:
se evalúa en el dispatch, bajo `order_boundary`, después de que riesgo apruebe.
La reducción (`close_position`) queda fuera del stop por diseño (G-4).

### 3.5 EXCEPTION

`fetch_recent` lanza `ConnectionError`; el scanner lo aísla, registra
`scanner_errors=1`, devuelve 0 snapshots y el ciclo no crea ninguna orden. El
estado queda vacío y consistente.

## 4. Contabilidad

Para cada escenario se comprobó `PaperBroker.accounting_snapshot`:

- `cash == initial_equity + realised_pnl`
- `ledger_equity == cash`
- `equity == cash + unrealised_pnl − accrued_entry_commissions`
- `closed_trade.pnl == gross_pnl − entry_commission − exit_commission`
- `closed_trade.pnl == reference_gross_pnl − execution_cost − entry − exit`

Las cinco identidades son verdaderas en los seis escenarios. En el trade
cerrado, el coste se descompone en comisión de entrada 0,25, comisión de salida
0,25 y coste de ejecución 0,104984 USDT.

## 5. Aislamiento

- `live=false`, `credentials_used=false`, `order_sent=false`.
- Ningún `BitunixFuturesClient`, `BitunixSpotClient` ni `ccxt` se construye en
  el runner.
- El ledger de evidencia declara `CONTROLLED_TEST_FIXTURE` y
  `not a production admission`.
- `hot_stop.py` sigue con SHA-256 `76cfca23…`, idéntico a G-4.
- No se modificó `config/risk.yaml`, `config/strategy_admission.json` ni
  ninguna política.

## 6. Verificación

`scripts/audit/verify_g5.py --rev HEAD` exporta el commit con `git archive`,
ejecuta la evidencia dos veces y re-deriva los criterios. Resultado:
**G5_VERIFIED, 12/12, `FALSE_SUCCESS=0`**, con replay determinista (mismos
contadores y misma economía; se excluyen session ids y timestamps).

## 7. Límites

- Datos sintéticos y admisión controlada: se demuestra el recorrido, no la
  rentabilidad de `ema_crossover`.
- El ledger de producción no admite estrategias; el comando de producción
  termina en `NO_TRADE`.
- El reinicio es lógico, no un crash real del sistema operativo.
- `paper_cycle` y `autonomous.decision` siguen siendo dos motores.
- No hay llamadas a exchange ni aceptación de venue.
- La verificación es `PROCEDURALLY_SEPARATED`, no una segunda persona.
