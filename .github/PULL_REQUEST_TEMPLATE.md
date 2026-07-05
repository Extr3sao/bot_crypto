# Resumen del PR

<!-- Título formato: chore|feat|fix|docs|refactor|test(SCOPE): short summary.
     Ejemplo: `feat(risk): add drawdown-based sizing guard`.
     Scope debe coincidir con uno de los nombres de módulo del repo. -->

## Tipo de cambio

<!-- Marca TODAS las que apliquen. La primera dominante define el
     prefijo del título. La sección de checklist que se expande abajo
     depende del título y del Tipo. -->

- [ ] Bug fix (cambio que arregla un issue sin breaking change)
- [ ] Nueva funcionalidad (cambio que añade feature sin breaking change)
- [ ] Breaking change (cambio que afecta compatibilidad hacia atrás)
- [ ] Refactor / docs / chore (sin cambio funcional)
- [ ] CI / infra
- [ ] Hotfix (parche urgente fuera de sprint, requiere ADR `excepciones`)

## Ticket relacionado

<!-- Formato: TSK-XXX con link al ticket en tasks/backlog.md. -->

- TSK: `TSK-XXX` — [tasks/backlog.md](../tasks/backlog.md)
- Estado actualizado en `tasks/backlog.md`: `[ ]` → `[x]`

## Riesgo

<!-- Marque el mayor nivel esperado. Ver `docs/risk-policy.md`. -->

- [ ] `L` (low) — typo, docs, refactor aislado.
- [ ] `M` (medium) — nueva lógica con tests.
- [ ] `H` (high) — toca secrets, risk sizing, execution orders, o
      promoción a paper/live.

## Breaking changes notables

<!-- Si marcaste Breaking change, lista los efectos aquí. Si no, "N/A"
     y borra esta sección. -->

- N/A

---

# Quality Gates (siempre)

> Ref: [`docs/ci.md`](../docs/ci.md). **Todos estos deben estar en
> verde antes de merge.** El CI los ejecuta automáticamente, pero el
> autor los corre también en local antes de pedir review.

- [ ] `uv run ruff format --check .` verde.
- [ ] `uv run ruff check .` verde.
- [ ] `uv run mypy .` verde (strict).
- [ ] `uv run pip-audit -r reqs.txt` verde (o excepción ADR firmada
      en [`tasks/decisions.md`](../tasks/decisions.md)).
- [ ] `uv run pytest -m "not slow and not market" --cov --cov-fail-under=90`
      verde — coverage ≥ 90%.
- [ ] `scripts/validate_local.ps1` (o el equivalente portable)
      verde — 7/7 OK.

## Tests añadidos / actualizados

- [ ] Unit tests cubren los cambios (`tests/unit/`).
- [ ] Si toca red o dependencias externas: integration tests
      (`tests/integration/`).
- [ ] Si documenta un caso conocido o regresión: regression test
      (`tests/regression/`).

## Documentación obligatoria

- [ ] Actualicé `docs/ci.md`, `docs/architecture.md` o
      `quality/release-gates.md` si la metodología cambia.
- [ ] Añadí/actualicé [`context/impact-analysis.md`](../context/impact-analysis.md)
      con efectos colaterales del cambio.
- [ ] Añadí/actualicé [`context/retrieval-log.md`](../context/retrieval-log.md)
      con el cierre del ticket.
- [ ] Si cambié/añadí una dependencia: `context/dependency-map.md`
      actualizado + ADR firmada (si requiere justificación).

---

# Checklists por tipo de cambio

> **Las 4 secciones de abajo son colapsables.** El autor del PR
> expande solo la(s) que apliquen según el Tipo marcado arriba y el
> scope del título. CODEOWNERS fuerza la aprobación de los reviewers
> adicionales cuando un path listado cambia (ver
> [`.github/CODEOWNERS`](../.github/CODEOWNERS)).

<details>
<summary><strong>Configuración — <code>config/*.yaml</code>, <code>src/trading_bot/config/</code>, <code>.env.example</code></strong></summary>

- [ ] `security-reviewer` firma (porque toca el flat-env alias y los
      mappings de secrets — ADR-0010).
- [ ] `flat-env keys` nuevas pineadas con test regresión en
      `tests/unit/config/`.
- [ ] No introduje secretos literales en YAML ni en código.
- [ ] Si cambié `config/risk.yaml` → `risk-manager` firma también.
- [ ] Si cambié `config/runtime.yaml` modo live →
      `I_UNDERSTAND_THE_RISKS=true` pineado por un test fail-fast.
- [ ] ADR firmada si el cambio es arquitectónico (no solo typo).

</details>

<details>
<summary><strong>Estrategia — <code>src/trading_bot/strategies/</code>, <code>config/strategies.yaml</code>, <code>bdd/features/</code></strong></summary>

- [ ] `strategy-engineer` firma.
- [ ] Backtest reproducible con slippage + comisiones
      ([`docs/backtesting-methodology.md`](../docs/backtesting-methodology.md)).
- [ ] Walk-forward ≥ 3 meses con métricas mínimas (Sharpe, max DD).
- [ ] Si promueve estado `research → paper → live_candidate → live` →
      [`docs/live-trading-checklist.md`](../docs/live-trading-checklist.md)
      se ha rellenado.
- [ ] BDD scenarios en
      [`bdd/features/signal_generation.feature`](../bdd/features/signal_generation.feature)
      actualizados (`.feature` solo cambia via `bdd-analyst` +
      `strategy-engineer`).

</details>

<details>
<summary><strong>Riesgo — <code>src/trading_bot/risk/</code>, <code>config/risk.yaml</code></strong></summary>

- [ ] `risk-manager` firma (veto obligatorio).
- [ ] [`quality/risk-quality-gates.md`](../quality/risk-quality-gates.md)
      revisado.
- [ ] Kill switch testeado (con dry-run).
- [ ] Drawdown máximo, pérdida diaria y exposición definidos
      cuantitativamente.
- [ ] Property tests con Hypothesis bajo `tests/unit/risk/`.

</details>

<details>
<summary><strong>Ejecución — <code>src/trading_bot/execution/</code>, idempotency, retries</strong></summary>

- [ ] `execution-engineer` firma.
- [ ] `client_order_id` UUIDv4 client-side, idempotente (ADR firmada
      si introduce un patrón nuevo).
- [ ] Retries con `tenacity` + backoff exponencial, max attempts
      documentados.
- [ ] Slippage configurable y pineado por test.
- [ ] `paper` mode validado antes de cualquier live.

</details>

---

# Sign-off de agentes (per `AGENTS.md`)

> Marca "Aplica" si el PR toca el dominio de ese agente. CODEOWNERS
> fuerza la aprobación cuando `Aplica: [x]` + un path del archivo
> listado cambia. El resto se firma por revisión humana o se deja
> en blanco con justificación de una línea.

| Agente                              | Aplica | Comentario |
| ----------------------------------- | ------ | ---------- |
| `context-engineer`                  | [ ]    |            |
| `quant-researcher`                  | [ ]    |            |
| `bdd-analyst`                       | [ ]    |            |
| `risk-manager`                      | [ ]    |            |
| `strategy-engineer`                 | [ ]    |            |
| `execution-engineer`                | [ ]    |            |
| `backtest-engineer`                 | [ ]    |            |
| `observability-engineer`            | [ ]    |            |
| `security-reviewer`                 | [ ]    |            |

## Comentario libre

<!-- Riesgos residuales, decisiones arquitectónicas, links a runs del
     CI/backtest/paper, evidencia de coverage, screenshots. -->

---

# Procedimiento de merge

1. CI en verde (los 5 jobs + coverage ≥ 90%).
2. CODEOWNERS reviewers aprobaron (count ≥ 1 global, ≥ 2 si path
   sensible cambió).
3. Branch protection rules aceptaron el PR.
4. Squash-merge o rebase-merge (linear history; sin merge commits).
5. Borrar feature branch tras merge (`gh pr merge --delete-branch`).
6. Confirmar que el commit merged aparece en `main` con
   `git log -1 origin/main`.
