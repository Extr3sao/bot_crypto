# VERIFIER_EVIDENCE — Whitelist Attack, Runtime Reachability, Cross-Artifact Consistency

**Audited target:** `a5487164803fb601f87f2cd4c865929c30da274e`
**Machine-readable:** `VERIFIER_EVIDENCE_whitelist_attack.json`, `VERIFIER_EVIDENCE_cross_artifact_consistency.json`
**Scripts:** `verifier_whitelist_attack.py`
**Run with:** `PYTHONPATH=<verifier>/src` (per `PYTHON_IMPORT_AUTHORITY`)

---

## PART A — `WHITELIST_ADVERSARIAL_ATTACKS`

### Verdict: **FAIL** — 28 attacks blocked / 35 attempted, 7 bypasses

The frozen contract declares `enforcement.bypass_paths_allowed = 0`. The verifier found
**2 HIGH-severity bypasses** and **5 MEDIUM-severity leaks**. Payloads were written by the verifier;
no builder test was reused.

Title-check on the frozen artifact (read from git blob bytes):
`H6_FEATURE_AUTHORITY_WHITELIST_V3.json` sha256 `c59718ca…` — allowed/forbidden field sets match
the code's `ALLOWED_H6_FIELDS` / `FORBIDDEN_H6_FIELDS` exactly.

### Blocked correctly (28)

`__getitem__`, `get()`, `in`, `getattr`, `assert_field_allowed`, `check_row_whitelist` (full
forbidden row and forbidden-only row), `iter()`, `keys()`, `values()`, `items()`, `dict(wrapped)`,
`**unpack`, `json.dumps(via items)`, `json.dumps(default=str)`, mutation of `.data`, added
attributes, and all four forbidden field names individually.

### BYPASS 1 — `.data` exposes the raw backing mapping — **HIGH**

```python
from trading_bot.research.h6.whitelist import H6FieldAccess
w = H6FieldAccess({... "count_long_short_ratio": 42, ...})
w.data["count_long_short_ratio"]          # -> 42   (forbidden value retrieved)
object.__getattribute__(w, "data")        # -> same
```

`H6FieldAccess` is a `@dataclass(frozen=True, slots=True)` with field `data`. The class defines
`__getattr__`, which raises `AttributeError` for the name `"data"` — **but that guard is dead code**:
because `slots=True` creates a real slot descriptor for `data`, normal attribute lookup succeeds and
`__getattr__` is never consulted. The raw mapping — including every forbidden column — is therefore
reachable with a single attribute access.

This contradicts the frozen artifact's `bypass_paths_allowed: 0` and defeats the documented
"fail-closed accessor" claim.

### BYPASS 2 — `repr()` / `str()` / `format()` leak forbidden names *and values* — **MEDIUM**

The dataclass-generated `__repr__` renders the whole payload:

```
H6FieldAccess(data={'sum_open_interest': 1000, …, 'count_long_short_ratio': 4242, …})
```

All four forbidden field names appear, together with their values. Any log line, traceback,
`repr()` in an assertion message, or evidence dump of a wrapper object will therefore carry
forbidden H6 feature values. Relevant to the observability and evidence-integrity gates.

### BYPASSES 3–5 — `copy.copy()` and `pickle` round-trip — **MEDIUM**

Both produce a new `H6FieldAccess` whose raw backing still contains the forbidden fields, so the
`.data` bypass above travels with the copy. (Root cause is the same as BYPASS 1.)

### Non-findings recorded for completeness

- The code's admitted set is a **superset** of the frozen `ALLOWED_FIELDS`: it additionally admits
  `timestamp_ms`, `unit_semantics`, `source_file`, `source_sha256` as PIT/bookkeeping metadata.
  These are not features, and the three feature fields match exactly. **Not a defect**, but the
  frozen artifact does not enumerate them.
- The wrapper screens **key names, not nested value structure**; a forbidden key nested inside an
  allowed field's value passes through. Documented as a limitation, LOW.

---

## PART B — `WHITELIST_RUNTIME_REACHABILITY`

### Verdict: **FAIL — NOT WIRED INTO ANY RUNTIME DATA PATH**

Independent scan of the whole `src/` tree for uses of the enforcement primitives
(`H6FieldAccess`, `check_row_whitelist`, `assert_field_allowed`):

| file | references |
|---|---|
| `src/trading_bot/research/h6/whitelist.py` | definition site |
| `src/trading_bot/research/h6/__init__.py` | **re-export only** |

No module that actually reads OI rows (`feature_engine.py`, `eligibility.py`, `oi_dataset_v2.py`,
data loaders) invokes the fail-closed accessor or `check_row_whitelist`.

Static scan also found **0** references to any forbidden field name anywhere under
`src/trading_bot/research/h6/` outside the enforcement module itself.

**Interpretation (deliberately precise):** the H6 economic execution path is currently hard-gated
OFF — `can_execute_h6()` returns `False` (observed). So there is today no live OI-reading runtime
path for the accessor to protect, and feature authority is presently enforced by two other
mechanisms:

1. the normaliser's field whitelist, which **strips** the four forbidden provider columns from the
   dataset bytes (`field_whitelist` in the frozen data authority; independently byte-verified in
   `VERIFIER_EVIDENCE_data_authority`), and
2. static-scan tests.

The runtime accessor is a control that **exists but is not reachable from any runtime data path**.
That is reported as a reachability failure rather than a pass, because a control on no live path
provides no runtime guarantee if/when execution is enabled by a later change.

---

## PART C — `CROSS_ARTIFACT_CONSISTENCY`

### Verdict: **FAIL** — the control plane is still bound to the superseded, failed **V1** prereg

Live frozen authority (V3): prereg `9f1d844…`, spec `cd354e06…`, manifest `de42e4a1…`.

`src/trading_bot/research/h6/execution_harness.py` pins:

| pinned constant | value | which generation |
|---|---|---|
| `PREREG_COMMIT` | `e683e04e5df39d0f2f5feb6097664536b93cc636` | **V1** |
| `SPEC_SHA256` | `f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148` | **V1** |
| `MANIFEST_SHA256` | `345334c3107860a5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc` | **V1** |
| `DATASET_SHA256` | `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99` | current ✅ |

`external_verifier_report.py` hard-codes the report path as
`docs/external-audit-01/oi-full-history-01/H6_EXTERNAL_VERIFIER_REPORT.json` — the **V1** folder.

Corroborating sources that `e683e04…` is V1 **and failed**:
`oi-full-history-01/H6_PREREG_COMMIT_RECORD.json`;
`oi-full-history-02/H6_MANIFEST_V2.json` → `v1_prereg_commit_historical: "e683e04… (FAILED_EXTERNAL_VERIFICATION, IMMUTABLE)"`;
`oi-full-history-02/H6_PREREG_REPAIR_DEFECT_REGISTER.json` → `old_prereg_commit: e683e04…`.

`src/trading_bot/research/h6/__init__.py` still documents
`Frozen authority: H6_SPEC.json (committed blob e683e04)` — also V1.

### Consequences

- **Fail-closed today, observed:** `can_execute_h6()` = `False` (no report file present at the V1 path).
- **Legitimately unreachable:** a genuine V3 verification report records `9f1d844` / `cd354e06…` /
  `de42e4a1…`, which `_verify_external_report()` would reject with `H6PreregMismatch`. The gate's
  enablement condition therefore cannot be satisfied for the live frozen authority at all.
- **Governance hole in principle:** a report carrying the **V1** hashes with `FINAL_VERDICT=PASS` at
  the V1 path would satisfy the gate while the live frozen authority is V3 — binding the release
  decision to a preregistration that failed external verification and was superseded.
- **Second-order weakness:** `REPORT_PATH` is a *relative* path, so the gate's outcome depends on the
  process working directory, and a satisfying file could live outside the audited worktree.

The data plane (dataset, ledger, manifest, fingerprint, whitelist artifact) is fully self-consistent
and hash-verified. The **control plane** is not.

---

## Findings register

| id | gate | severity | title | status |
|---|---|---|---|---|
| `FIND-WL-01` | WHITELIST_ADVERSARIAL_ATTACKS | **HIGH** | `H6FieldAccess.data` slot exposes the raw mapping containing all forbidden fields; the `__getattr__` guard for `"data"` is dead code | OPEN, unrepaired |
| `FIND-WL-02` | WHITELIST_ADVERSARIAL_ATTACKS | MEDIUM | dataclass `repr`/`str`/`format` leak forbidden field names **and values** | OPEN, unrepaired |
| `FIND-WL-03` | WHITELIST_ADVERSARIAL_ATTACKS | MEDIUM | `copy`/`pickle` carry the raw backing payload (same root cause as FIND-WL-01) | OPEN, unrepaired |
| `FIND-WL-04` | WHITELIST_RUNTIME_REACHABILITY | **HIGH** | fail-closed accessor is not invoked by any runtime module; no live OI-reading path uses it | OPEN, unrepaired |
| `FIND-XART-01` | CROSS_ARTIFACT_CONSISTENCY | **HIGH** | runtime execution gate bound to superseded/FAILED V1 prereg + V1 report path | OPEN, unrepaired |
| `FIND-XART-02` | CROSS_ARTIFACT_CONSISTENCY | MEDIUM | report path relative → CWD-dependent gate | OPEN, unrepaired |

Per audit rules these defects are **recorded, not repaired**. The verifier made no change to any
file under `src/`.

Because `WHITELIST_ADVERSARIAL_ATTACKS`, `WHITELIST_RUNTIME_REACHABILITY` and
`CROSS_ARTIFACT_CONSISTENCY` are failing, the final verdict of this audit cannot be `PASS`.
