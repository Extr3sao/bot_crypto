# Release Gates

> Gates de release (paper y live). Si una sola caja no está verde,
> el release NO procede.

---

## Bloque 1 — Calidad de código

- [ ] Code quality gates: `quality/code-quality.md`.
- [ ] Risk quality gates: `quality/risk-quality-gates.md`.
- [ ] `pytest` en verde.
- [ ] `mypy` en verde.
- [ ] `ruff` en verde.

## Bloque 2 — Estrategia / backtest / paper

- [ ] Estrategia en estado correcto (paper o live_candidate).
- [ ] Backtest firmado por `backtest-engineer` y `quant-researcher`.
- [ ] Walk-forward con métricas mínimas.
- [ ] Paper con métricas mínimas (si promoción a live).

## Bloque 3 — Riesgo y seguridad

- [ ] `risk-manager` y `security-reviewer` firmaron.
- [ ] Sin secretos en el repo.
- [ ] `safety` y `pip-audit` limpios.

## Bloque 4 — Operación

- [ ] Logs estructurados funcionando.
- [ ] Health checks activos.
- [ ] Runbook de incidentes disponible.

## Bloque 5 — Promoción a LIVE

> Bloque adicional si el release promueve a `live`.

- [ ] `docs/live-trading-checklist.md` completo y firmado.
- [ ] `LIVE_TRADING_ENABLED=true` y `I_UNDERSTAND_THE_RISKS=true` confirmados.
- [ ] Operador principal + peer firmaron.
- [ ] ADR firmado y publicado.

## Procedimiento

1. Copiar este checklist al inicio del PR/release.
2. Marcar cada ítem con `[x]`, `[ ]` o `NO_APLICA` con justificación.
3. Adjuntar evidencias (enlaces a informes, logs, ADR).
4. Firmar cada bloque.
5. Sin firmas NO hay release.

## Política de excepción

No hay excepción. Si un ítem falla, se documenta en `tasks/decisions.md`
con:
- Justificación escrita.
- Mitigación propuesta.
- Plan de remediación con fecha.
- Firma humana.

---

## Bloque 6 — Branch Protection Rules (TSK-009)

> Reglas recomendadas para `main` en GitHub. Aplicar via GitHub UI o
> `gh api` con un PAT admin. Ninguna se aplica automáticamente al bot
> si el repo no concede permisos de admin — son **recomendaciones**
> operadas por humanos con permisos de owner.

### Required status checks (alineados a `docs/ci.md` §3)

| Job name (en `.github/workflows/ci.yml`) | Gate que pinea                          |
| ---------------------------------------- | -------------------------------------- |
| `format-and-lint`                        | `ruff format --check` + `ruff check`   |
| `type-check`                             | `mypy .` strict                        |
| `pip-audit`                              | `pip-audit -r reqs.txt`                |
| `tests-and-coverage`                     | `pytest --cov --cov-fail-under=90`     |
| `validate-local` (opcional)              | `python -m trading_bot.config --validate` |

Todos estos jobs deben tener `Required: ✅` para que un PR pueda
mergear a `main`. Si un job renombra, hay que actualizar aquí y en
`docs/ci.md` simultáneamente — pinear consistencia entre los 3
archivos.

### Required reviewers (alineados a `.github/CODEOWNERS`)

- `required_approving_review_count = 1` mínimo globalmente.
- **2 required reviewers** para paths sensibles (CODEOWNERS fuerza
  automáticamente la doble firma cuando un path listado cambia):
  - `src/trading_bot/risk/`
  - `src/trading_bot/execution/`
  - `src/trading_bot/config/`
  - `.env.example`, secrets handlers
  - `.github/workflows/`
  - `config/risk.yaml`, `config/runtime.yaml`
  - `pyproject.toml`, `uv.lock`, `.python-version`

### Restrictions extra (binarias)

- `require_code_owner_reviews: true` (CODEOWNERS es el gate humano).
- `dismiss_stale_reviews_on_push: true` (reviews caducan al recibir
  nuevos commits en el PR).
- `require_linear_history: true` (no merge commits).
- `allow_force_pushes: false` (salvo rama admin-only con justificación
  explícita en ADR).
- `allow_deletions: false`.
- `block_creations: false` (PRs desde forks permitidos para externos).
- `required_conversation_resolution: false` durante bootstrap
  (muchos bots dejan hilos abiertos en PRs hasta madurar). Activar
  a `true` solo cuando los bots auto-resuelvan sus propios comentarios
  (ADR firmada cuando se cambie).
- `lock_branch: false` (no se freeze main durante hotfixes; el kill
  switch existe a nivel runtime, no a nivel git).
- `required_signatures: false` (signed commits opcionales en fase
  temprana; activar en fase de review de seguridad con ADR firmada).

### Comandos `gh api` para aplicar las reglas

> Pre-flight: confirma que `gh auth status` reporta scope `repo` +
> `admin:org`. Si no, `gh auth refresh -s admin:org,repo`.

```powershell
# 1. (Opcional) Ver estado actual antes de tocar
gh api /repos/Extr3sao/bot_crypto/branches/main/protection `
  --jq '{required_status_checks, required_pull_request_reviews, allow_force_pushes, required_linear_history}'

# 2. Aplicar protection rules vía PUT con JSON inline
$rules = @'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "format-and-lint",
      "type-check",
      "pip-audit",
      "tests-and-coverage"
    ]
  },
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "bypass_pull_request_allowances": {
      "users": [],
      "teams": ["Extr3sao/maintainers"]
    }
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
'@
$rules | gh api --method PUT `
  -H "Accept: application/vnd.github+json" `
  /repos/Extr3sao/bot_crypto/branches/main/protection `
  --input -
```

Si prefieres desde bash:

```bash
cat > branch-protection.json <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["format-and-lint", "type-check", "pip-audit", "tests-and-coverage"]
  },
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": false
}
EOF

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/Extr3sao/bot_crypto/branches/main/protection \
  --input branch-protection.json
```

### Post-apply validation

```powershell
# Confirmar que las reglas quedaron aplicadas
gh api /repos/Extr3sao/bot_crypto/branches/main/protection `
  --jq '.required_status_checks.contexts, .required_pull_request_reviews.required_approving_review_count, .required_linear_history, .allow_force_pushes'

# Smoke test: abrir un PR dummy y verificar que el job `format-and-lint`
# es required. NO mergear — cerrarlo inmediatamente.
gh pr create --base main --title "chore(test): branch protection smoke test" --body "Will be closed immediately. Validates branch-protection rules only."
```

### Riesgos y mitigaciones (CODEOWNERS + branch protection)

| Riesgo                                                              | Mitigación                                                                                              |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Equipos CODEOWNERS no existen aún en el org → CODEOWNERS no bloquea | Pre-flight: `gh api /orgs/Extr3sao/teams --jq '.[].slug'` antes de mergear `.github/CODEOWNERS`.        |
| Status check names no coinciden entre `ci.yml` y branch protection  | Tras aplicar protection, abrir PR dummy de prueba. Cerrarlo sin mergear. Validar manualmente.          |
| `main` queda infranqueable si CODEOWNERS no tiene aprobador         | Consortium role (CODEOWNERS fallback `@Extr3sao/maintainers`) con 2-3 personas como miembros.          |
| Force-push sigue permitido para admins                               | Cambiar `enforce_admins: true` en `required_pull_request_reviews` cuando se quiera veto absoluto.       |
| CODEOWNERS pierde track tras renombre de usuario                   | Validar handles con `gh api /repos/{org}/{repo}/codeowners/errors` post-merge del archivo CODEOWNERS.   |

### Procedimiento de revisión periódica

Cada cierre de sprint, revisar:

1. ¿Las reglas aplicadas coinciden con las de este documento y
   `.github/CODEOWNERS`?
2. ¿Los status check jobs todavía existen (no fueron renombrados)?
3. ¿Los equipos CODEOWNERS siguen existiendo con miembros activos?
4. ¿Algún path crítico nuevo en el repo necesita estar listado?

Desviaciones → ADR firmada y actualización simultánea de los 3 archivos:
`.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`,
`quality/release-gates.md`.

---

## Bloque 7 — Credentials rotation

> Policy de rotación de credenciales pineadas en repos. Cross-cutting
> security, análoga a Bloque 6 (Branch Protection). Ninguna se aplica
> automáticamente al bot si el repo no concede permisos de admin al org
> owner — son **recomendaciones** operadas por humanos con permisos de
> owner (mismo precedente que Bloque 6 / ADR-0017).

### Cadence

- **90 días para PAT service-account `PR_PIPELINE_SMOKE_PAT`** (alineado
  a **NIST SP 800-57 Part 1 Rev. 5 §5.3.6 Cryptographic Period**; cadencia
  revisable vía ADR cuando NIST o el equipo decida ajustarla; complementa
  OWASP ASVS V14.1 *Configuration & Secrets Management* para la policy
  general). El anchor exacto V2.10.4 NO cubre rotation cadence; el sistema
  reminder del code-reviewer detectó la imprecisa original y este wording
  fine-tuning ancla la autoridad normativa correcta.
- Trigger adicional: cualquier cambio de role en el org-admin team que
  afecte el onboarding de un nuevo owner requiere rotación inmediata del
  PAT y revalidación del dry-run smoke job.
- Trigger adicional: incidente de seguridad sospechado per
  `docs/risk-policy.md` Bloque 5 (respuesta a incidentes).

> **Cross-link**: la rotación automática NO dispara validación de CI per
> sprint; la dependencia es revisión humana en cada sprint review (ver
> Procedimiento).

### Roles

- **org-admin** (GitHub `Settings → Secrets and variables → Actions →
  New repository secret` UI rotation flow, o `gh api
  repos/Extr3sao/bot_crypto/actions/secrets/PR_PIPELINE_SMOKE_PAT` PUT
  method con scope `repo` only — NO requiere `admin:org`):
  - Ejecuta la rotación física del secret en GitHub.
  - Pinear nueva SHA en una retrieval-log entry taggeada
    `event=secret-rotation` dentro de `context/retrieval-log.md` apenas
    completed (es la única señal autoritativa de que el secret rotó —
    bloquea cualquier race condition con el dry-run smoke job).
- **context-engineer** (rol orquestador en
  `.ai/agents/context-engineer.md`):
  - Lee las entries taggeadas `event=secret-rotation` en cada sprint
    review y valida que: (a) la SHA nueva difiere de la previa (no
    rotación vacía), (b) el dry-run smoke job pine contract sigue
    verde post-rotación, (c) cross-link explícito a `.github/CODEOWNERS
    strategy-team` reválido.
  - Pinear el resultado de la revisión en una nueva retrieval-log entry
    taggeada `event=secret-rotation-review` (audit-trail del ciclo).

### Procedimiento

1. Org-admin inicia rotación via GitHub UI (o `gh api` con scope `repo`
   only, sin `admin:org`).
2. Org-admin añade nueva retrieval-log entry en `context/retrieval-log.md`
   con timestamp + tag `event=secret-rotation` + diff metadata (SHA
   nueva vs previa).
3. PR-pipeline smoke job se re-ejecuta automáticamente en cada PR
   abierto (per `.github/workflows/ci.yml` step `Smoke: dry-run the
   PR-pipeline script`):
   - Si el secret está activo: dry-run exit 0, smoke OK path full.
   - Si el secret es revocado durante rotación (ventana de ~5-30
     minutos): dry-run exit 1, smoke OK path parse-tripwire.
4. En el siguiente sprint review, context-engineer abre la
   retrieval-log entry taggeada `event=secret-rotation` y cross-linkea
   con:
   - `.github/CODEOWNERS` section `STRATEGY-TEAM` (valida que el equipo
     sigue pineado y con miembros reales en el org, no phantom team).
   - Last entry `[2026-07-09 16:00]` de `context/retrieval-log.md`
     (PR-pipeline context que pinea el dry-run smoke job wired con
     `env: GH_TOKEN: ${{ secrets.PR_PIPELINE_SMOKE_PAT }}`).
   - ADR-0017 (precedente auth-gated — el patrón de "agente no ejecuta
     ops que requieren scope superior al suyo queda pineado como
     policy").

### Validación en CI

- Smoke job step-level pine contract sobre `feat/tsk-0204-…` ramas: el
  inline annotation pineado por `cf35049` (`does not yet carry a
  dedicated credentials-rotation section`) puede ser refrescado a
  `cross-link back to release-gates.md #credentials-rotation` solo
  DESPUÉS de que esta sección esté pineada en `quality/release-gates.md`
  Y el cambio se mergee a `main` (cross-link bidireccional previene
  stale-relation).
- `pytest tests/unit/market_data/test_ccxt_connector.py -q` y similares
  NO dependen de `PR_PIPELINE_SMOKE_PAT` (los test mocks parchearán
  `ccxt.binance` al namespace level — pine contract per retrieval-log
  `[2026-07-03 23:00]` round-6 fix).
- Si `pytest` tests o cualquier other CI step detecta uso hardcodeado
  del PAT, falla loud (`violation of ADR-0017`).

### Riesgos y mitigaciones

| Riesgo                                                            | Mitigación                                                                                            |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Secret rotation silenciosa sin retrieval-log entry por org-admin  | Sprint review per `release-gates.md Procedimiento de revisión periódica` valida bcrypt presence.       |
| Drift entre `.github/CODEOWNERS strategy-team` y realidad del org | Pre-flight periodico: `gh api /orgs/Extr3sao/teams/strategy-team/members --jq '.[].login'`.            |
| Cadence >90d porque sprint review sleeps                          | Audit-trail GitHub API via `gh secret list-events` (cron externo pine contract sprint review sleeper). |
| Smoke job pierde exit 0 después de rotación (ventana 5-30min)     | Parse-tripwire smoke exit 1 está pineado como smoke-passing per `release-gates.md Bloque 1`.         |
| `GH_TOKEN` troceado accidentalmente con scope `workflow`          | ADR-0020 mantiene pwsh-only y prohibe scope `workflow` en este secret (per retrieval-log context).     |

### Cross-link pine contract

- `context/retrieval-log.md [2026-07-09 16:00]` — PR-pipeline context
  que origina la policy (comit `6182493` in `feat/tsk-0204-fase2-f3b-structlog`).
- `.github/CODEOWNERS` — section `STRATEGY-TEAM` (valida que el team
  sigue pineado y con miembros reales).
- `tasks/decisions.md` — ADR-0017 (precedente auth-gated), ADR-0012
  (precedente pip-audit ignore-vuln policy), ADR-0020 (precedente pine
  contract style).
- `.github/workflows/ci.yml` smoke job step-level inline annotation de
  `cf35049` refresh (pendiente turno siguiente al merge).

> **Nota sobre numeración**: si esta policy madura y requiere
> formalización como ADR, abrir **ADR-0021** (siguiente libre después de
> ADR-0020 per ADR-0020 numbering note). Esta Bloque 7 es living
> documentation operativa; ADR eleva a decisión arquitectónica cuando se
> quiera trazabilidad cross-cutting mayor (e.g. cross-multi-repo o
> signing key rotation).
