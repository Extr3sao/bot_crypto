# `trading_bot.config` — Configuración tipada con Pydantic v2

Capa de carga y validación de los 6 archivos YAML en `config/*.yaml` más los
overrides en `.env`. Cualquier arranque del bot pasa por aquí — el sistema es
**fail-fast**: si la configuración no valida, el bot NO arranca.

## Uso rápido

```python
from trading_bot.config import load_settings

settings = load_settings()             # config/*.yaml + .env
settings = load_settings(env_file=None) # solo YAML, sin .env
settings = load_settings(config_dir="alt_config/")
```

API flat (sin wrappers intermedios):

```python
settings.universe.base_currency     # 'USDT'
settings.exchange.id                # 'binance'
settings.risk.max_risk_per_trade_pct # 0.25
settings.runtime.mode               # TradingMode.PAPER
settings.strategies.strategies      # dict[str, StrategyConfig]
settings.indicators.indicators       # dict[str, IndicatorConfig]
```

## CLI

```bash
# Valida y muestra resumen
python -m trading_bot.config --validate

# Serializa la configuración resuelta a JSON
python -m trading_bot.config --dump-json > resolved_config.json

# Apunta a otro directorio o ignora el .env
python -m trading_bot.config --config-dir cfg2/ --env-file
```

Exit codes:

- `0` — la configuración carga, valida y resuelve.
- `1` — `pydantic.ValidationError`; el mensaje JSON se imprime en stderr.

## Precedencia de overrides

De mayor a menor prioridad (pydantic-settings v2):

1. Argumentos explícitos al constructor (`Settings(...)`).
2. Variables de entorno del proceso (`TRADING_MODE`, `EXCHANGE_ID`, etc.).
3. Archivo `.env` (cargado automáticamente si existe en el cwd).
4. Archivos `config/*.yaml` (merge superficial por `YamlDirectorySource`).
5. Defaults declarados en los modelos (`Field(default=...)`).

## Modelos disponibles

| Módulo              | Modelo raíz        | YAML                     |
| ------------------- | ------------------ | ------------------------ |
| `universe.py`       | `Universe`         | `config/assets.yaml`     |
| `exchange.py`       | `Exchange`         | `config/exchange.yaml`   |
| `risk.py`           | `Risk`             | `config/risk.yaml`       |
| `strategies.py`     | `StrategiesConfig` | `config/strategies.yaml` |
| `indicators.py`     | `IndicatorsConfig` | `config/indicators.yaml` |
| `runtime.py`        | `Runtime`          | `config/runtime.yaml`    |

`Settings` (en `settings.py`) los compone todos en un único root tipo
`pydantic_settings.BaseSettings`.

## Gates de live trading

DoD exige fail-fast cuando `live_trading_enabled=True` pero la variable
`I_UNDERSTAND_THE_RISKS` no está puesta a `true`. Validación en
`Runtime._check_live_gates` (model validator). Un check adicional de
`mode='live' ⟹ kill_switch_enabled=True` vive en
`Settings._check_cross_domain_live_invariants`. El error sale como
`ValidationError` legible al arrancar el bot.
