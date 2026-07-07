# Command 04 — Plan

## Objetivo
Construir un **plan de implementación incremental** que divida el cambio
en unidades pequeñas, seguras y verificables.

## Agente(s) responsable(s)
- Cualquier agente técnico concernido.

## Entradas
- Spec del comando `03-specify.md`.

## Salidas
- Plan incremental en `tasks/backlog.md` (o doc específico) con:
  - Fases.
  - Tickets por fase.
  - Para cada ticket: archivos a tocar, tests esperados, gate de aceptación.

## Pasos
1. Dividir el cambio en pasos que pueda revertirse.
2. Cada paso debe ser verificable (test, métrica o inspección).
3. Empezar por los cimientos (tipos, contratos) antes de la lógica.
4. Marcar los tickets que requieren paper trading antes de merge.

## Criterio de finalización
- Lista de tickets con criterios del estilo "Definition of Done".
- Orden claro (qué ticket desbloquea cuál).

## NO
- No incluir tickets "relleno" sin valor.
- No aplazar la seguridad a "más adelante".

## Gate TSK-013.10 — Sweep latent fixture-invalidation antes de aprobar cualquier plan

Si el plan toca constraints Pydantic v2 en `Exchange*`, `Risk`, `Runtime`, `Universe`,
`StrategiesConfig`, o `IndicatorsConfig` (e.g. endurece un `ge=`, agrega un campo bounded,
o cambia un constraint existente), ejecutar el sweep audit TSK-013.10 ANTES de aprobar:

```
code_searcher \
  -pattern "rate_limit_ms|max_backoff_ms|initial_backoff_ms|max_attempts|request_ms|recv_window_ms|max_open_positions|max_trades_per_day|max_risk_per_trade_pct|max_asset_exposure_pct|max_total_exposure_pct|min_order_notional_usdt|max_order_notional_usdt|default_stop_loss_pct|default_take_profit_pct|min_24h_volume_usdt|max_spread_bps|max_atr_percent|min_atr_percent|consecutive_loss_cooldown_minutes|prometheus_port" \
  -maxResults 30 \
  -flags "-g tests/**/*.py"
```

> **Cross-reference (REQUIRED post-sweep step)**: la lista de arriba es solo el
> **first-pass candidate**. Despues de correr el rg, el plan author DEBE ademas
> ejecutar
> ```
> grep -rnE '\b(ge|gt|le|lt|min_length|max_length|pattern)\s*=\s*[0-9]' src/trading_bot/config/*.py
> ```
> para confirmar el set canonico de bounded fields declarados en los modelos.
> Cualquier bounded field que aparezca en los modelos pero NO en el rg pattern es
> una señal de drift: agregalo al rg pattern via la Coverage evolution rule y
> re-corre el sweep para confirmar rc=0.

> **Coverage evolution**: este snapshot NO es exhaustivo. **El PR que introduzca un
> nuevo campo bounded con `Field(..., ge=)` (o `gt=`/`le=`/`lt=`/`min_length=`/
> `max_length=`/`pattern=`) en cualquier modelo bajo `src/trading_bot/config/` debe
> self-extender el rg pattern en `.ai/commands/04-plan.md` en EL MISMO COMMIT**.
> El gate de aprobacion del Plan (este comando) rechaza cualquier PR que anada un
> bounded field sin su entrada correspondiente en este pattern. Esto convierte la
> auditoria de pasiva a gate-enforced; sin esta regla, el patron se queda
> stale y reproduce la clase de drift que origino TSK-013.10.

Detalle de los triggers (si al menos uno es TRUE, ejecutar sweep):

1. El plan cambia constraints numericos bounded (`ge=`, `gt=`, `le=`, `lt=`,
   `min_length=`, `max_length=`, `pattern=`) en cualquier modelo dentro de
   `src/trading_bot/config/`.
2. El plan endurece un constraint existente (e.g. `ge=10` → `ge=50`) o lo suaviza
   (e.g. `ge=100` → `ge=10`).
3. El plan crea, renombra o elimina un campo bounded en cualquier modelo bajo
   `src/trading_bot/config/` (incluyendo sub-modelos anidados como
   `StrategiesConfig.strategies.*`, `IndicatorsConfig.indicators.*`,
   `Runtime.{logging,storage,scheduler}.*`). Si es rename, los fixtures con el
   nombre antiguo caen en triage FIELD-DEPRECATED (Pydantic `extra='ignore'` los
   traga silenciosamente; `extra='forbid'` rompe el test). Si el rename conserva
   un `Field(..., alias='old_name')` para retro-compatibilidad, los fixtures
   con el alias siguen siendo Validos (no requieren cleanup inmediato); abrir
   follow-up ticket en `tasks/backlog.md` para el alias-removal futuro (cuando
   se decida romper retro-compat).
4. El plan crea o elimina un modelo Pydantic v2 completo. El code_searcher del
   Cross-reference paso debe confirmar que ningun test importa el modelo
   eliminado.

Salida esperada del sweep: lista de hits con `file:line` + field + value + constraint.
Cualquier valor por debajo del constraint floor del modelo Pineado es una violacion
latente que debe corregirse ANTES del PR.

Triage adicional a mano:

- **Valid** (valor >= constraint floor): el test fixture respeta el modelo; OK.
- **VIOLATION** (valor < constraint floor): el fixture esta roto latente; el PR NO
  puede mergear hasta que el fixture se bumpe al floor + add headroom per reviewer
  feedback.
- **BYPASS intencional** (uses `model_construct()`): documentado en TSK-013.10 como
  deuda potencial ante futuros constraint hardenings. Si el plan los endurece,
  abrir ADR firmado para revisar TODOS los sites flagged de `model_construct` y
  decidir entre (a) bump a construct_args explicitos que respeten constraints, o
  (b) mantener el bypass con just documentada. Para trigger 4 (modelo eliminado),
  estos son los sites de mayor riesgo.
- **NEGATIVE TEST intencional** (uso de valor invalido con `pytest.raises`): OK,
  pin contract.
- **FIELD-DEPRECATED** (el fixture pasa un campo que ya no existe en el modelo):
  Pydantic lo ignora silenciosamente con `extra='ignore'` (default). Para
  `extra='forbid'` rompe el test; en cualquier caso el fixture queda muerto
  latente. Requiere cleanup del fixture.

Cataloguing source-of-truth: `tasks/backlog.md` TSK-013.10 + commits `b74c2f2`
+ `c3c30d3` en `feature/tsk-013.10-latent-fixture-audit` documentan los 4 sites
catalogued con `model_construct()` (deuda potencial) y los 2 violations latentes
originales (ya corregidos en `feature/tsk-013.8-013.9-test-fixes @ d6c9141`, pendientes
de merge a main).

Cross-link: `.ai/agents/context-engineer.md` (responsable del cataloguing activo)
+ `tasks/decisions.md` ADR-0016 (umbrella TSK-013.5..013.9 baseline remediation
que origino el patron) + ADR-0017 (TSK-013.5 escalacion que paralelamente describio
latent drift en pydantic-settings v2.14.2).

Cherry-pick durability: ver `.ai/agents/context-engineer.md` seccion "Fixture-audit
catalog maintenance" (el cross-link es bidireccional; ambos archivos deben
cherry-pickearse juntos para mantenerlo integro).
