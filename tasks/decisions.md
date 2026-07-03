# Decisions (ADR)

> Log append-only de decisiones arquitectónicas y excepciones firmadas.
> Cada ADR tiene: contexto, opciones, decisión, consecuencias.

---

## ADR-0001 — Licencia del proyecto

- **Estado**: Decidido.
- **Contexto**: el repositorio necesita una licencia de código abierta
  o propietario.
- **Opciones**:
  - MIT.
  - Apache-2.0.
  - Licencia propietaria.
- **Decisión**:  Licencia propietaria / uso interno privado.
- **Consecuencias**: impacto legal y de adopción externa.
- **Razón**: el proyecto es un bot de trading automático y debe mantenerse privado hasta validar seguridad, riesgos, arquitectura y cumplimiento.
- **Consecuencia**: no se permite distribución externa ni publicación open source sin un nuevo ADR.

## ADR-0002 — Gestor de dependencias

- **Estado**: Decidido.
- **Contexto**: hay que decidir entre `pip + venv`, `poetry`, `uv`,
  o `pdm`.
- **Opciones**:
  - `pip + venv`: simple, estándar.
  - `poetry`: lockfile robusto, ya extendido.
  - `uv`: rápido, moderno, compatible con `pyproject.toml`.
- **Decisión**: usar `uv` como gestor de dependencias.
- **Consecuencias**: afecta onboarding, CI y velocidad de resolución.
- **Razón**: es rápido, moderno, compatible con `pyproject.toml` y permite lockfile reproducible.
- **Consecuencia**: el onboarding y CI deben documentar comandos con `uv`.

## ADR-0003 — Dashboard

- **Estado**: Decidido.
- **Contexto**: ¿se implementa un dashboard web? ¿cuándo?
- **Opciones**:
  - Grafana + Prometheus en Fase 8.
  - Streamlit como dashboard rápido.
  - CLI avanzadas con `rich` + exportar CSVs.
- **Decisión**: pendiente, no antes de Fase 8.
- **Consecuencias**: requiere infraestructura y mantenimiento.

## ADR-0004 — Telemetría

- **Estado**: Decidido.
- **Contexto**: ¿Prometheus, OpenTelemetry, ninguno?
- **Opciones**:
  - Prometheus + Grafana.
  - OpenTelemetry → backend externo.
  - Logs JSON como única fuente.
- **Decisión**: usar logs JSON estructurados como fuente inicial de observabilidad. Prometheus + Grafana queda reservado para Fase 8.
- **Razón**: reduce complejidad operacional en fases tempranas.
- **Consecuencias**:todos los eventos importantes deben registrarse como logs estructurados.

## ADR-0005 — Persistencia (DAL/ORM)

- **Estado**: Decidido.
- **Contexto**: ¿SQLAlchemy, `sqlite3` directo, Tortoise, ORM ligero?
- **Opciones**:
  - `SQLAlchemy 2.x` con `aiosqlite` opcional.
  - `sqlite3` directo en primera iteración.
- **Decisión**: usar `sqlite3` directo para Fase 6/Fase 7, especialmente backtesting y paper trading. Revisar migración a SQLAlchemy antes de Fase 9 (live) si se requiere concurrencia/async.
- **Razón**: reduce dependencias y permite avanzar rápido con persistencia local, alineado con el principio de "no añadir complejidad prematuramente".
- **Consecuencia**: si se requiere concurrencia, async, multiusuario o live trading robusto, se abrirá nuevo ADR para migrar a SQLAlchemy/PostgreSQL.


## ADR-0006 — Exchange y modo iniciales

- **Estado**: Decidido. Revisable vía nuevo ADR que lo reemplace.
- **Contexto**: ¿qué exchange y modo por defecto?
- **Decisión**: **Binance vía CCXT**, modo `paper`, sandbox `true`.
- **Razones**: liquidez alta, documentación abundante,
  testnet público.
- **Consecuencias**: cualquier exchange nuevo requiere ADR.
- **Revisión**: si se decide cambiar, abrir ADR-0008 con la nueva
  decisión; este ADR se mantiene para trazabilidad pero queda
  marcado como superseded.

## ADR-0007 — Política de "no overfitting"

- **Estado**: Decidido.
- **Contexto**: ¿cómo se evita promouvoir una estrategia sobreajustada?
- **Decisión**: walk-forward obligatorio + `min_trades_for_promotion`.
- **Consecuencias**: cualquier estrategia que no supere la promoción
  por N trades sigue en `research`.

## ADR-0009 — Hosting y repositorio remoto

- **Estado**: Decidido.
- **Contexto**: el repositorio necesita hosting versionado con CI/CD y
  control de acceso coherente con ADR-0001 (licencia propietaria).
- **Opciones**:
  - GitHub (público).
  - GitHub (privado).
  - GitLab self-hosted.
  - Sin remoto (local únicamente).
- **Decisión**:
  - **GitHub** como hosting del repositorio.
  - Repositorio **estrictamente privado** (cumple ADR-0001).
  - Protocolo **HTTPS** para `fetch` / `push`.
  - Rama principal **`main`** desde el inicio.
  - Remoto inicial: `https://github.com/Extr3sao/bot_crypto.git`.
- **Razón**: GitHub Actions cubre el CI/CD del baseline (TSK-008)
  sin coste y se integra con la mayoría de herramientas.
  La privacidad aísla el bot de trading hasta validar la
  propiedad intelectual.
- **Consecuencia**:
  - No se inyectan *Secrets* de GitHub Actions para claves de
    exchange hasta que se requiera CI real con testnet.
  - El CI inicial solo ejecuta chequeos estáticos y de tests
    locales (ruff, mypy, pytest, pip-audit).
  - Cualquier migración a GitLab u otro hosting requiere un
    ADR que reemplace este.
- **Nota sobre numeración**: `ADR-0008` se reservó como
  forward-reference en ADR-0006 para una posible
  sustitución del exchange. Esta ADR-0009 asume hosting
  sin colisionar con esa reserva.

---

## ADR-0010 — Alias de variables planas → rutas anidadas en Settings

- **Estado**: Decidido.
- **Contexto**: El cargador de Settings usa `env_nested_delimiter="__"` porque los submodelos (Runtime, Risk, Exchange, etc.) tienen varios niveles de anidamiento y necesitamos pisar keys profundas via env vars sin aplanar manualmente cada subpath. Sin embargo, la documentacion publica que sigue el operador (`.env.example`, `docker-compose.yml`, `docs/live-trading-checklist.md` y los BDDs en `bdd/features/*.feature`) usa exclusivamente nombres planos: `TRADING_MODE`, `LIVE_TRADING_ENABLED`, `I_UNDERSTAND_THE_RISKS`, `EXCHANGE_ID`, `EXCHANGE_SANDBOX`, `LOG_LEVEL`, etc.
- **Problema**: Sin intervencion, los nombres planos se ignoran silenciosamente y `load_settings()` devuelve los defaults del YAML. Riesgo critico en los release gates: un operador que siga la doc existente para activar live trading (`TRADING_MODE=live` + `LIVE_TRADING_ENABLED=true` + `I_UNDERSTAND_THE_RISKS=true`) acabaria con el bot arrancando en `paper` por el conflicto de defaults ignorados.
- **Opciones**:
  - Eliminar `env_nested_delimiter="__"`: docs y modelos convergen a plano, pero rompe la capacidad de pisar paths profundos a dos+ niveles (`Runtime.scheduler.active_hours.start`) y obliga a refactorizar cada submodelo a `BaseSettings`.
  - Renombrar las variables planas en docs/compose/BDDs a la forma anidada: churn masivo en docs y operadores. Confuso para lectores novatos.
  - **Custom `PydanticBaseSettingsSource` (`FlatEnvAliasSource`)** que re-mapea un conjunto estable y curado de nombres planos a su path anidado en `Settings`. La precedencia es: process env > .env > flat-alias > YAML > defaults; la forma anidada sigue ganando sobre la plana cuando ambas estan definidas.
- **Decision**: opcion 3. Implementada en `src/trading_bot/config/settings.py` mediante el dict `FLAT_ENV_ALIASES` y la clase `FlatEnvAliasSource`, exportada en `trading_bot.config.__init__` para introspection.
- **Mantenimiento**:
  - Cualquier nuevo nombre plano agregado a `.env.example` / `docker-compose.yml` / `docs/live-trading-checklist.md` / `bdd/features/*.feature` TIENE que aparecer tambien en `FLAT_ENV_ALIASES` (en `settings.py`). Sin esa entrada, `load_settings()` lo ignora y devuelve el default del YAML — el mismo bug que el original.
  - Los nombres anidados siguen siendo la fuente canonica para automation, fixtures y tests; la forma plana es solo un wrapper de compatibilidad hacia los operadores humanos y hacia la documentacion historica.
  - Cualquier refactor que retire `env_nested_delimiter="__"` de `model_config` rompe la coexistencia plano/anidado: los docs serian ambiguos. Si se hace, requiere un ADR de remplazo.
- **Consecuencias**:
  - `FLAT_ENV_ALIASES` es un single point of failure para la doc publica. Cubierto por tests de regresion en `tests/unit/config/test_settings.py` (process-env, dotenv, case-insensitive, empty-skip, invalid-value, boolean-coercion, extra-ignore, deep-path-passthrough).
  - El tiempo de carga de `Settings` aumenta marginalmente (un dict comprehension extra); despreciable.
  - Publicar esta decision como ADR convierte el contrato plano → anidado en una decision visible y buscable, no en una convencion oculta en el codigo. Documenta tambien el checklist para el siguiente contribuidor.

---

## Excepciones firmadas

> Aquí se documentan desviaciones del flujo SDD o del release gate.
> Sin entrada aquí = la desviación no existió.

```
ADR-XXXX | fecha | contexto | desviación | mitigación | firmas
```

(Por ahora vacío.)
