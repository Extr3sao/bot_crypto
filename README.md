# crypto-scalping-agentic-bot

> **Bot de scalping algorítmico de criptomonedas — sistema SDD/BDD/CDD híbrido, auditable y seguro.**

---

## ⚠️ Aviso importante

Este proyecto **es un sistema de software**, **no una recomendación de inversión**. Ninguna estrategia incluida está validada como rentable. Las criptomonedas son activos volátiles y el scalping es una de las modalidades de trading de mayor riesgo. Operar con dinero real puede producir pérdidas totales. Antes de habilitar cualquier modo real deben completarse todos los *quality gates* definidos en `quality/release-gates.md` y `docs/live-trading-checklist.md`.

---

## 🎯 Objetivo

Construir un **sistema modular de trading automático de criptomonedas orientado a scalping**, capaz de:

- Escanear un mercado configurable (por defecto, una whitelist de 25 activos).
- Evaluar oportunidades con indicadores técnicos configurables.
- Producir señales explicables y auditables.
- Operar estrictamente por fases: `research` → `backtest` → `paper` → `shadow-live` → `live`.
- Registrar cada decisión, error, orden y resultado para auditoría completa.
- Añadir nuevas estrategias, indicadores, exchanges y filtros sin rehacer la arquitectura.

## 🧠 Modo de operación obligado

El sistema **nunca debe operar dinero real por defecto**. El modo `live` está **bloqueado** por defecto y solo se libera tras cumplir:

- Backtests documentados.
- Paper trading con métricas mínimas.
- Validación de drawdown, comisiones, slippage y latencia.
- Riesgo, kill switch y logs activos.
- Confirmación manual explícita mediante variables de entorno.

Ver `docs/live-trading-checklist.md`.

## 🧱 Stack propuesto

| Capa            | Propuesta                                  | Justificación resumida                                                       |
| --------------- | ------------------------------------------ | ---------------------------------------------------------------------------- |
| Lenguaje        | Python 3.11+                               | Ecosistema maduro para data + trading algorítmico.                            |
| Exchange        | CCXT                                       | Abstracción multi-exchange; permite añadir/quitar brokers sin cambiar core.  |
| Datos           | Pandas + NumPy                             | Maduro y suficiente para timeframe 1m–15m; polars queda opcional.            |
| Configuración   | Pydantic v2                                | Validación tipada estricta; evita configs inválidos en runtime.              |
| Persistencia    | SQLite → PostgreSQL (futuro)                | Comienza simple, sin servidor; upgrade sin migraciones breaking.            |
| CLI / UX        | Rich                                       | Mejor DX en consola para logs y reportes.                                    |
| Scheduling      | APScheduler                                | Tick scheduler, odd-even jobs, mercado-aware.                                |
| Observabilidad | Logging estructurado JSON + Loguru (opcional) | Logs ingestables por cualquier agregador externo.                       |
| Testing         | pytest + hypothesis                        | Pruebas unitarias, property-based y de regresión.                            |
| Calidad         | Ruff + Mypy                                | Lint rápido + tipado estático estricto.                                      |
| Contenedores    | Docker + docker-compose                    | Reproducibilidad local y despliegues limpios.                                |

## 🗂️ Estructura

Ver la sección "Estructura del repositorio" más abajo. Las decisiones de arquitectura se documentan en `docs/architecture.md`.

## 🚦 Fases (ver `tasks/roadmap.md`)

0. Fundaciones (este scaffolding).
1. Market data + conector CCXT.
2. Motor de indicadores enchufable.
3. Scanner multi-activo.
4. Estrategias (interfaz + 5 candidatas desactivadas por defecto).
5. Risk manager.
6. Backtesting (con comisiones/slippage, walk-forward).
7. Paper trading.
8. Observabilidad y métricas.
9. Live trading controlado (gated).

## 🚀 Quick start (modo `backtest`/`paper`)

> Requiere Python 3.11+ y `uv` (ADR-0002).

```bash
# 1. Clonar
git clone <repo> && cd crypto-scalping-agentic-bot

# 2. Copiar variables de entorno
cp .env.example .env

# 3. Instalar dependencias
uv sync --all-extras --dev

# 4. Validar configuración
uv run python -m trading_bot.app config-check

# 5. Ejecutar una iteracion demo segura
uv run python -m trading_bot.app scan --demo
```

## 🛠️ Quality gates (CI local)

> Los mismos gates que GitHub Actions aplica en cada PR se ejecutan
> 100% en local antes de pushear. Ref: [`docs/ci.md`](docs/ci.md) como
> runbook canónico y `.github/workflows/ci.yml` como implementación
> exacta.

```bash
# Setup (asume `uv` instalado + `.python-version` presente)
uv sync --all-extras --dev

# Format + lint
uv run ruff format --check .
uv run ruff check .

# Type check (strict)
uv run mypy .

# Auditoria de CVEs
uv run pip-audit -r <(uv export --all-extras --no-hashes)

# Tests con coverage ≥ 90% (excl. markers slow + market para PR feedback < 5 min)
uv run pytest -m "not slow and not market" --cov --cov-fail-under=90
```

En Windows, `scripts/validate_local.ps1` ejecuta los 7 gates
secuencialmente con timeout y reporta OK/KO por gate. Antes de abrir
un PR, valida en local; después CI ejecuta los mismos pasos en
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) sobre
`ubuntu-latest`.

## 🛡️ Seguridad

- Nunca commitees `.env`. Ver `.gitignore`.
- Las claves API deben tener **solo permisos de trading**, **sin permisos de retiro**.
- `safety`-style checks se ejecutan en CI en cada PR (ver `quality/code-quality.md`).

## 📚 Documentación esencial

- `docs/architecture.md` — decisiones técnicas.
- `docs/risk-policy.md` — política de riesgo.
- `docs/strategy-design.md` — diseño y estado de estrategias.
- `docs/backtesting-methodology.md` — cómo se hace backtesting correctamente.
- `docs/paper-trading-methodology.md` — paper trading y comparación.
- `docs/live-trading-checklist.md` — checklist obligatorio antes de live.
- `.ai/methodology-hybrid.md` — metodología SDD/BDD/CDD/TDD aplicada.
- `.ai/orchestration.md` — orquestación de los 9 agentes.

## 🧩 Estructura del repositorio

```
crypto-scalping-agentic-bot/
├─ README.md
├─ AGENTS.md
├─ .env.example
├─ pyproject.toml
├─ docker-compose.yml
├─ .gitignore
├─ config/                              # Configuración YAML (assets, risk, exchange, ...)
├─ .ai/                                 # Metodología, agentes y comandos SDD
│  ├─ methodology-hybrid.md
│  ├─ orchestration.md
│  ├─ agents/                           # 9 agentes especializados
│  ├─ commands/                         # 12 comandos SDD numerados
│  └─ skills/
├─ bdd/features/                        # Escenarios Gherkin
├─ context/                             # Mapas de código, dependencias e impacto
├─ docs/                                # Arquitectura, riesgo, estrategia, ...
├─ src/trading_bot/                     # Código fuente
│  ├─ app.py
│  ├─ config/
│  ├─ market_data/
│  ├─ indicators/
│  ├─ strategies/
│  ├─ scanner/
│  ├─ risk/
│  ├─ execution/
│  ├─ portfolio/
│  ├─ backtesting/
│  ├─ paper/
│  ├─ observability/
│  ├─ storage/
│  └─ utils/
├─ tests/{unit,integration,regression}/
├─ evals/{strategy-evals,risk-evals,execution-evals}/
├─ quality/                             # Gates de calidad, riesgo y release
├─ notebooks/                           # Investigación exploratoria
├─ data/{raw,processed,backtests}/
├─ logs/
├─ reports/
└─ tasks/                               # Roadmap, backlog, sprint y decisiones
```

## 🤝 Contribución

Lee `.ai/methodology-hybrid.md` antes de proponer cambios. Toda nueva estrategia, indicador o exchange debe pasar por el flujo SDD: requisitos → BDD → spec → plan → tareas → implementación con TDD → evaluación → revisión de riesgo → release gate.

## ⚖️ Licencia

Licencia propietaria / uso interno privado. No se permite distribucion
externa ni publicacion open source sin un nuevo ADR (ver ADR-0001 en
`tasks/decisions.md`).
