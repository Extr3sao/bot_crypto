# TSK-860 - Trade Intelligence Feedback Loop: BDD (Command 02)

> Escenarios BDD esperados. La implementacion final puede ubicarlos en
> `bdd/features/trade_intelligence_feedback.feature`.

---

## 1. Mapeo RF -> escenarios

| RF | Escenario BDD |
| --- | --- |
| RF-1, RF-2 | Crear expediente antes de enviar orden |
| RF-3, RF-4 | Guardar zonas tecnicas y distancia a entrada |
| RF-5 | Persistir indicadores usados por la decision |
| RF-6, RF-7, RF-8 | Captura TradingView con fallback local |
| RF-9, RF-10 | Diagnostico post-cierre |
| RF-11 | Feedback no modifica live sin flag |
| RF-12 | Consulta historica por agentes |

## 2. Feature propuesta

```gherkin
Feature: Trade intelligence feedback loop
  El bot debe guardar una tesis completa antes de operar y aprender
  despues del cierre sin cambiar reglas de dinero real sin aprobacion.

  Background:
    Given el bot esta en modo "paper"
    And existe OHLCV suficiente para "BTC/USDT"
    And la captura de graficos esta habilitada

  Scenario: Crear expediente antes de enviar una orden
    Given una senal LONG pasa los filtros de estrategia
    And el risk manager acepta la senal
    When el execution engine prepara la orden
    Then se crea un TradeCase con estado "pending_order"
    And el TradeCase contiene entry_reason, direction, TP y SL
    And la orden incluye el trade_case_id como correlacion

  Scenario: Guardar soporte, resistencia y zona de entrada
    Given el mercado tiene un soporte entre 62400 y 62550
    And una resistencia entre 63300 y 63500
    When se genera la tesis de entrada
    Then el TradeCase guarda dos TechnicalZone
    And cada zona incluye kind, low, high, strength y timeframe
    And se guarda la distancia de entrada a cada zona

  Scenario: Detectar conflicto con zona de resistencia
    Given una senal LONG aparece justo bajo una resistencia fuerte
    When se evalua la tesis de entrada
    Then el criterio "near_resistance_against_long" queda registrado
    And el confidence_score baja
    And el risk manager puede vetar o reducir tamano segun configuracion

  Scenario: Capturar imagen de TradingView
    Given TradingView esta configurado y disponible
    When se acepta una senal para ejecucion
    Then se guarda una imagen con entrada, TP, SL y zonas tecnicas
    And el ChartSnapshot usa provider "tradingview"
    And el path queda asociado al TradeCase

  Scenario: Fallback si TradingView falla
    Given TradingView no responde antes del timeout
    When se acepta una senal para ejecucion
    Then la orden no queda bloqueada indefinidamente
    And se genera una imagen local con los mismos niveles
    And el ChartSnapshot usa provider "local_renderer"

  Scenario: Diagnosticar operacion ganadora
    Given una posicion cierra por take profit
    And el precio respeto la zona de soporte marcada
    When el post-trade evaluator procesa el cierre
    Then el TradeOutcome queda como "win"
    And el PostTradeDiagnosis incluye "support_respected"
    And se calcula r_multiple, MFE y MAE

  Scenario: Diagnosticar operacion fallida
    Given una posicion cierra por stop loss
    And el precio rompio el soporte marcado antes de la entrada
    When el post-trade evaluator procesa el cierre
    Then el TradeOutcome queda como "loss"
    And el PostTradeDiagnosis incluye "structure_invalidated"
    And se registra si el fallo ocurrio antes o despues de la entrada

  Scenario: No cambiar reglas live sin aprobacion
    Given hay 20 operaciones perdedoras cerca de resistencia
    When el feedback engine detecta el patron
    Then genera una recomendacion
    And no modifica config de live trading
    And la recomendacion queda pendiente de ADR o revision humana

  Scenario: Consulta historica por agente
    Given existen TradeCase ganadores y perdedores
    When un agente consulta casos de "BTC/USDT" con tag "near_resistance"
    Then recibe los casos filtrados
    And cada caso incluye tesis, outcome, diagnostico y snapshot_path
```

## 3. Gates BDD

- `pytest-bdd` debe recolectar todos los escenarios.
- Los steps no deben depender de APIs reales de TradingView.
- Las capturas se mockean o se generan en carpeta temporal.
- El escenario de seguridad debe fallar si se intenta persistir secretos.

