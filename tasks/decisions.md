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

## Excepciones firmadas

> Aquí se documentan desviaciones del flujo SDD o del release gate.
> Sin entrada aquí = la desviación no existió.

```
ADR-XXXX | fecha | contexto | desviación | mitigación | firmas
```

(Por ahora vacío.)
