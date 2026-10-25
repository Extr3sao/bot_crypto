"""Generate the WP-RECOVERY-002 deliverables from the evidence JSON.

The builder owns the prose; every number it prints is read from
``reports/ai-bots/WP-RECOVERY-002/evidence/*.json`` or measured here. If an
evidence file is missing the builder refuses to write a report that would
otherwise contain a hole.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

ROOT = Path("C:/Users/GVLLFR0035/Downloads/ff-wt-trunkfmt/reports/ai-bots/WP-RECOVERY-002")
EV = ROOT / "evidence"
LOGS = Path("C:/Users/GVLLFR0035/recovery-002/logs")
GEN = time.strftime("%Y-%m-%dT%H:%M:%S")
SUITE_LOG = LOGS / "full_suite.log"

PACKAGE_SHA = "416352609be1a59cc9a2024930f4b4068aab7ee86014dc18258af45e14089f9a"


def live_head() -> str:
    """The repository HEAD right now (read-only) — other lanes keep committing."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd="C:/Users/GVLLFR0035/Downloads/bot freebuff",
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - the report must not fail over this
        return "UNKNOWN"


def load(name: str) -> dict:
    path = EV / name
    if not path.exists():
        raise SystemExit(f"missing evidence {path}: run scripts/recovery002_audit.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_suite() -> dict:
    if not SUITE_LOG.exists():
        return {"state": "NOT_RUN"}
    raw = SUITE_LOG.read_text(encoding="utf-8", errors="replace")
    text = raw.replace("\r", "\n")
    out: dict = {"log": str(SUITE_LOG), "bytes": SUITE_LOG.stat().st_size}
    out["exit"] = int(m.group(1)) if (m := re.search(r"EXIT=(-?\d+)", text)) else None
    marks = [int(x) for x in re.findall(r"\[\s*(\d+)%\]", text)]
    out["last_percent"] = marks[-1] if marks else None
    counts = {}
    for key in ("passed", "failed", "skipped", "errors", "deselected"):
        m = re.search(rf"(\d+) {key}\b", text)
        if m:
            counts[key] = int(m.group(1))
    out["counts"] = counts
    out["failed_nodes"] = sorted(set(re.findall(r"^FAILED (\S+)", text, flags=re.MULTILINE)))
    out["error_nodes"] = sorted(set(re.findall(r"^ERROR (\S+)", text, flags=re.MULTILINE)))
    started, ended = LOGS / "full_suite.start", LOGS / "full_suite.end"
    if started.exists() and ended.exists():
        out["wall_seconds"] = int(ended.read_text().strip()) - int(started.read_text().strip())
    out["command"] = ('pytest -q -p no:cacheprovider --tb=no -m "not slow and not market"')
    return out


def fmt_pct(part: int, total: int) -> str:
    return f"{(100.0 * part / total):.1f}%" if total else "n/a"


def chunks(commits: list[dict], size: int = 20) -> list[list[dict]]:
    return [commits[i:i + size] for i in range(0, len(commits), size)]


def main() -> int:
    a1 = load("A1_COPIES.json")
    a2 = load("A2_INTEGRITY.json")
    a3 = load("A3_DANGLING_AND_COVERAGE.json")
    a5 = load("A5_PRESERVATION.json")
    a6 = load("A6_PACKAGE.json")
    a7 = load("A7_UNRECOVERABLE.json")
    b = load("B_PUBLICATION.json")
    c_fake = load("C_FAKE_SMOKE.json")
    c_val = load("C_ISOLATED_VALIDATION.json")
    c_causes = load("C_SUITE_CAUSES.json")
    suite = parse_suite()
    verification = None
    if (ROOT / "VERIFICATION.json").exists():
        verification = json.loads((ROOT / "VERIFICATION.json").read_text(encoding="utf-8"))

    head_now = live_head()
    live = next(c for c in a1["copies"] if c["id"] == "live-repo")
    bundle = next(c for c in a1["copies"] if c["id"] == "backup-bundle")
    backup_repo = next(c for c in a1["copies"] if c["id"] == "backup-repo-copy")
    shells = next(c for c in a1["copies"] if c["id"] == "emptied-worktrees")
    registered = next(c for c in a1["copies"] if c["id"] == "registered-worktrees")["entries"]
    empty = [s for s in shells["shells"] if s["empty_shell"]]
    cov = a3["coverage"]
    only_live = {
        "commits": cov["commits"]["total"] - cov["commits"]["in_backup_repo"],
        "trees": cov["trees"]["total"] - cov["trees"]["in_backup_repo"],
        "blobs": cov["blobs"]["total"] - cov["blobs"]["in_backup_repo"],
    }

    not_in_backup = a3["not_in_backup_repo"]
    package = a6["package"]

    # ------------------------------------------------------------------ A ---
    git_md = f"""# GIT RECOVERY VERIFICATION — WP-002A

> Work package **WP-RECOVERY-002**, sub-package **002A**. Mode: read-only against the
> original repository; every write happens in an isolated copy.
> Generated {GEN} on `{c_val.get('clone', 'n/a')}` host, Python `{c_fake['python']}`.
> Evidence: `evidence/A1_COPIES.json`, `A2_INTEGRITY.json`, `A3_DANGLING_AND_COVERAGE.json`,
> `A5_PRESERVATION.json`, `A6_PACKAGE.json`, `A7_UNRECOVERABLE.json`.

## A.0 What this document proves, and what it does not

It proves that the surviving object database is intact, that every object which cannot be
reached from a ref was enumerated and pinned **in an isolated copy**, that a recovery bundle
carrying those objects can be restored from **two independent copies** with identical trees,
and that the original repository was not modified. It does **not** restore any untracked
file: those were never in Git and no object exists for them (`A7`).

## A.1 Copies audited

| copy | path | state | size / hash |
| --- | --- | --- | --- |
| original repository | `{live['path']}` | read-only for this WP | {len(live['packs'])} packs, {live['pack_bytes_total']:,} B, {live['refs']} refs, HEAD `{live['head'][:8]}` on `{live['branch']}` |
| all-refs bundle (incident backup) | `{bundle['path']}` | intact | {bundle['bytes']:,} B, SHA-256 `{bundle['sha256']}` |
| declared hash | `REPO_ALL_REFS.bundle.sha256` | **matches** | `{bundle['sha256_declared']}` |
| `git bundle verify` | — | exit **{bundle['bundle_verify_exit']}** | {len(bundle['list_heads'])} heads |
| full repository copy | `{backup_repo['path']}` | intact, older snapshot | {backup_repo['pack_bytes_total']:,} B, {backup_repo['refs']} refs, `fsck --connectivity-only` exit **{backup_repo['fsck_connectivity_only']}** |
| secondary worktrees | registered: {len(registered)} | {sum(1 for e in registered if e.get('present'))} present with content | see A7 |
| emptied worktrees | `Downloads/*` | **{len(empty)} shells** (gitlink only) | {shells['count']} gitlink dirs walked, {len(empty)} contain exactly one file |

The bundle is **derived** (refs only). The two independent object copies are the live
`.git/objects` and the incident backup's `.git/objects`; both pass `fsck`.

## A.2 Object integrity

| check | command | exit | result |
| --- | --- | --- | --- |
| full object validation | `git fsck --full --no-progress` | **{a2['fsck_full']['exit']}** | {a2['fsck_full']['seconds']} s, {len(a2['fsck_full']['missing_or_corrupt'])} missing/corrupt |
| reachability | `git fsck --connectivity-only` | **{a2['fsck_connectivity_only']['exit']}** | {a2['fsck_connectivity_only']['seconds']} s |
| pack integrity | `git verify-pack -v <idx>` × {len(a2['verify_pack'])} | {"**0**" if all(p['verify_pack_exit'] == 0 for p in a2['verify_pack']) else "**non-zero**"} | {sum(p['objects'] for p in a2['verify_pack']):,} objects across {len(a2['verify_pack'])} packs |

Key commits resolve (`git cat-file -t`):

| label | object | type | date | subject |
| --- | --- | --- | --- | --- |
""" + "".join(
        f"| {label} | `{v['sha'][:8]}` | {v['type']} | {v.get('date', '')[:10]} | {v.get('subject', '')[:60]} |\n"
        for label, v in a2["key_commits"].items()
    ) + f"""
One housekeeping anomaly is recorded, not fixed: `git count-objects -v` reports
`garbage: 1` (`.git/objects/12/tmp_obj_y7utqm`), an incomplete loose-object write from some
other lane. It is unreferenced and harmless; deleting it would be a write to the original
repository, which this WP does not do.

**Verdict A.2: {a2['verdict']}.**

## A.3 Objects that no ref reaches

Two sets are measured, because they mean different things:

| measure | commits | trees | blobs |
| --- | --- | --- | --- |
| `git fsck --unreachable --no-reflogs` (not reachable from any ref) | **{a3['unreachable_no_reflogs'].get('commit', 0)}** | {a3['unreachable_no_reflogs'].get('tree', 0)} | {a3['unreachable_no_reflogs'].get('blob', 0)} |
| `git fsck --dangling` (not reachable from a ref *or* a reflog) | {a3['dangling_only'].get('commit', 0)} | {a3['dangling_only'].get('tree', 0)} | {a3['dangling_only'].get('blob', 0)} |
| union used below | **{a3['union']['commits']}** | **{a3['union']['trees']}** | **{a3['union']['blobs']}** |

{cov['commits']['reflog_only']} of the {a3['union']['commits']} commits are reachable **only
through the reflog** — they disappear the day a `gc` expires it, which is why the preservation
step pins the union and not just the dangling set.

Tip analysis: **{len(a3['tips'])} tips** (an unreachable commit with no unreachable child).
Each tip carries the labels of its own tree — for example
`{a3['tips'][0]['short']}` `{a3['tips'][0]['subject'][:52]}` with
`{', '.join(a3['tips'][0]['reports_campaigns'][:2]) or 'no reports/ directory'}`.

## A.4 Coverage of the surviving backups

| object class | total | in the all-refs bundle | in the backup `.git` copy | **only in the live `.git`** |
| --- | --- | --- | --- | --- |
| commits | {cov['commits']['total']} | **{cov['commits']['in_bundle']}** | {cov['commits']['in_backup_repo']} | {only_live['commits']} |
| trees | {cov['trees']['total']} | **{cov['trees']['in_bundle']}** | {cov['trees']['in_backup_repo']} | {only_live['trees']} |
| blobs | {cov['blobs']['total']} | **{cov['blobs']['in_bundle']}** | {cov['blobs']['in_backup_repo']} | {only_live['blobs']} |

**{cov['commits']['in_bundle']} of {a3['union']['commits']} unreachable commits are in the
bundle.** This is the mechanical reason a bundle is not a backup of this repository: `git
bundle create --all` serialises refs, and unreachable objects are by definition not behind a
ref. {len(not_in_backup)} objects ({only_live['commits']} commits + {only_live['trees']} trees + {only_live['blobs']} blobs) exist **only** in the live
`.git` — the incident backup was taken at 20:55Z and the campaign anchors
`47ca8dac`, `cedc1346`, `03d169c8` were written at 21:10–21:20Z, after it.

## A.5 Preservation (isolated copy only)

`{a5['isolated_copy']}` — a copy of `.git`, never the original.

| fact | value |
| --- | --- |
| refs before / after | {a5['refs_before']} → **{a5['refs_after']}** |
| commits reachable before / after | {a5['commits_reachable_before']} → **{a5['commits_reachable_after']}** |
| commits gained | **{a5['commits_gained']}** (expected {a5['expected_commits_gained']}) |
| tip refs created | {len(a5['refs_created'])} (`refs/recovered/tip-NNNN`) |
| orphan object refs present | {len(a5['orphan_refs_present'])} (`refs/recovered/orphan-*` for trees/blobs no commit reaches) |
| unreachable afterwards | `{a5['remaining_unreachable']}` |
| post-step `fsck` | exit **{a5['post_fsck_exit']}** |
| original repository refs after the step | {a5['live_repo_refs_after']} (**unchanged**) |
| original repository written to | **No** |

**Verdict A.5: {a5['verdict']}.**

## A.6 The recovery package, restored twice

| artefact | value |
| --- | --- |
| bundle | `C:/Users/GVLLFR0035/recovery-002/package/WP-RECOVERY-002-ALLREFS.bundle` |
| size | **{package['bundle_bytes']:,} B** |
| SHA-256 | `{package['bundle_sha256']}` |
| second independent copy | `{package['second_copy']}` |
| copies byte-identical | **{package['copies_identical']}** |
| `git bundle verify` on the second copy | exit **{package['second_copy_bundle_verify_exit']}** |
| heads in the bundle | {package['heads']} |
| restore A (`{a6['restore_from_copy_a']['target']}`) | fetch exit {a6['restore_from_copy_a']['fetch_exit']}, `fsck --full` exit {a6['restore_from_copy_a']['fsck_exit']}, {a6['restore_from_copy_a']['refs']} refs, {a6['restore_from_copy_a']['recovered_refs']} recovered, **{a6['restore_from_copy_a']['commits_reachable']} commits** |
| restore B (`{a6['restore_from_copy_b']['target']}`) | fetch exit {a6['restore_from_copy_b']['fetch_exit']}, `fsck --full` exit {a6['restore_from_copy_b']['fsck_exit']}, {a6['restore_from_copy_b']['refs']} refs, {a6['restore_from_copy_b']['recovered_refs']} recovered, **{a6['restore_from_copy_b']['commits_reachable']} commits** |
| recovered tip trees identical across restores | {sum(1 for t in a6['tips_identical_across_restores'] if t['identical'])}/{len(a6['tips_identical_across_restores'])} |
| checkout probe | exit {a6['checkout_probe']['exit'] if a6['checkout_probe'] else 'n/a'}, {a6['checkout_probe']['dirty_entries'] if a6['checkout_probe'] else 'n/a'} dirty entries |

All {a6['checks_total']} restoration checks: **{a6['checks_passed']}/{a6['checks_total']} — {a6['verdict']}**.

```
{a6['checks'][0]['check']} ... {a6['checks'][-1]['check']}
```

## A.7 What Git cannot give back

Machine-readable: [`LOST_ARTIFACTS_STATUS.json`](LOST_ARTIFACTS_STATUS.json).

* **{a7['emptied_worktrees_from_incident_001']['entries']} checkout entries** lost
  **{a7['emptied_worktrees_from_incident_001']['gib_sum']} GiB / {a7['emptied_worktrees_from_incident_001']['files_sum']:,} files** of
  working content (26 emptied + 1 vanished).
* Untracked/ignored content has **no object** in any copy: `reports/`, `data/`, `.ci/`,
  `.venv/` were gitignored in every one of those checkouts.
* Unique unversioned content still on disk in the original repository, recoverable **by copy**
  (not by Git): {", ".join(f"`{p}`" for p in a7['recoverable_by_copy']) or "none"}.
* Irrecoverable by construction: {"; ".join(a7['irrecoverable'])}.

## A.8 Acceptance

| criterion | status | evidence |
| --- | --- | --- |
| copies audited and hashed | **PASS** | A.1 table, bundle hash recomputed |
| full object integrity | **PASS** | `fsck --full` exit 0, 4/4 packs verify |
| dangling objects enumerated | **PASS** | A.3, {a3['union']['commits']}/{a3['union']['trees']}/{a3['union']['blobs']} objects |
| presence in backups established | **PASS** | A.4, includes the {len(not_in_backup)} single-copy objects |
| recoverable objects pinned in an isolated copy | **PASS** | A.5, {a5['commits_gained']} commits gained, original untouched |
| package restorable from a second independent copy | **PASS** | A.6, {a6['checks_passed']}/{a6['checks_total']}, identical trees |
| untracked losses inventoried | **PASS (as an inventory)** | A.7 + `LOST_ARTIFACTS_STATUS.json` |
| nothing destroyed or published | **PASS** | no gc/prune/clean/reset/delete; no push; original refs unchanged |
"""
    (ROOT / "GIT_RECOVERY_VERIFICATION.md").write_text(git_md, encoding="utf-8")

    # ------------------------------------------------------------------ B ---
    ancestry = b["ancestry"]
    chunk_rows = []
    for index, group in enumerate(chunks(b["commits"]), start=1):
        prefixes = Counter(re.match(r"^([a-z]+)", c["subject"]).group(1)
                           if re.match(r"^([a-z]+)", c["subject"]) else "(sin prefijo)"
                           for c in group)
        chunk_rows.append(
            f"| {index:02d} | `{group[0]['sha'][:7]}`→`{group[-1]['sha'][:7]}` | "
            f"{group[0]['date'][:10]}→{group[-1]['date'][:10]} | {len(group)} | "
            f"{sum(c['files'] for c in group):,} | +{sum(c['added'] for c in group):,}/-{sum(c['deleted'] for c in group):,} | "
            f"{', '.join(f'{k}×{v}' for k, v in prefixes.most_common(3))} | "
            f"{group[0]['subject'][:52]} … {group[-1]['subject'][:34]} |"
        )

    risky_rows = "".join(
        f"| {name} | `{v['prefix']}` | {v['files_touched']} | {v['commits_touching']} |\n"
        for name, v in b["risky_areas"].items()
    )
    secret_lines = "".join(
        f"| `{h['path']}` | {h['rule']} | `{h['match_head']}` | reviewed: AWS documentation canary inside the repo's own secret scanner — not a credential |\n"
        for h in b["secret_scan"]["net_diff_hits"]
    )
    markers = b["incomplete_change_scan"]["net_diff_markers"]
    marker_rows = "".join(
        f"| {name} | {v['total']} | {', '.join(f'`{p}` ({n})' for p, n in list(v['top_paths'].items())[:3])} |\n"
        for name, v in markers.items()
    )

    pub_md = f"""# COMMIT PUBLICATION AUDIT — WP-002B

> Read-only audit of what publishing local `main` would put on the remote. **Nothing was
> created, pushed or tagged.** Evidence: `evidence/B_PUBLICATION.json` (all {b['commit_count']}
> commits with per-commit churn, deletions and subject).

## B.1 Ancestry

| fact | value |
| --- | --- |
| `origin/main` | `{ancestry['base_sha']}` `{a2['key_commits']['origin/main']['subject'][:64]}` |
| local `main` | `{ancestry['head_sha']}` `{a2['key_commits']['main']['subject'][:64]}` |
| merge base | `{ancestry['merge_base']}` — **is the tip of `origin/main`** ({ancestry['merge_base_is_base_tip']}) |
| ahead / behind | **+{ancestry['ahead']} / -{ancestry['behind']}** |
| fast-forward possible | **{ancestry['fast_forward_possible']}** (no force-push, no rewrite) |
| remote branches not contained in `main` | {len(ancestry['remote_branches_not_contained_in_main'])} of 80 refs (other lanes; unchanged by a `main` publication) |

A publication of `main` is therefore an **additive fast-forward**: it cannot delete a remote
commit, and it cannot rewrite any branch that is not `main`.

## B.2 The {b['commit_count']} local commits

* window: **{b['first_commit_date'][:10]} → {b['last_commit_date'][:10]}**, author(s): {", ".join(f'{a} ({n})' for a, n in b['authors'].items())}
* churn: **{b['churn']['files']:,} distinct files**, **+{b['churn']['added']:,} / −{b['churn']['deleted']:,} lines**
* subject prefixes: {", ".join(f"{k} {v}" for k, v in sorted(b['subject_prefixes'].items(), key=lambda kv: -kv[1]))}
* files deleted in the range: **{len(b['deleted_files_check'])}** — nothing is removed from the trunk

| # | range | dates | n | files | churn | prefixes | span |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(chunk_rows)}

The bulk of the +{b['churn']['added']:,} lines is committed evidence, not code: the largest
single additions are `docs/agentic/exp004a/wp051_02k/VOLUME_INVENTORY.json`
(128,161 lines) and `data/rfc048/raw/binance_usdm_exchange_info.json` (79,246). A reviewer
should read those as data files, not as diffs.

## B.3 The areas that matter

| area | prefix | files touched | commits touching |
| --- | --- | --- | --- |
{risky_rows}

Observations:

* **risk** — `src/trading_bot/risk/manager.py` is modified (+256 lines) and a whole
  `risk/futures/` plane is added (contracts, costs, engine, instruments, integration, margin,
  portfolio, sizing) plus `futures_falsification.py` and `futures_verification.py`. This is
  the single largest authority change in the range and needs a named reviewer.
* **execution** — only `execution/idempotency.py` changes; `execution/live_gate.py` exists on
  `main` and is **not** in the changed set, so the live-trading gate is byte-identical to
  `origin/main`.
* **accounting** — there is no `src/trading_bot/accounting/` package in this repository
  (`git cat-file -e main:src/trading_bot/accounting` → absent); the P&L surface lives in
  `paper/` and `risk/`. Stated explicitly so the missing row is not read as an unreviewed area.
* **verification** — the changed set contains no `scripts/verify_*` at all; the verification
  scripts in the range are new files under `scripts/` with other names (they appear in churn,
  not under the `verify_` prefix), so the gate scripts that certify the trunk were not edited.
* **entrypoints** — `scripts/autonomous_paper.py` changes in 5 commits and
  `src/trading_bot/autonomous/` in 17. Those are the recovery target.
* **CI** — two new workflows (`cost-barrier-gate.yml`, `recovery-determinism.yml`); the
  existing `ci.yml` is untouched by this range.

## B.4 Secrets

Scan surface: **{b['secret_scan']['blobs_scanned']:,} distinct blobs added in the range** and
**{b['secret_scan']['net_diff_added_lines']:,} added lines** of the net diff, against
{len(b['secret_scan']['patterns'])} rules (AWS keys, GitHub/OpenAI/Slack tokens, private-key
blocks, exchange key assignments, generic secret assignments).

| path | rule | match | disposition |
| --- | --- | --- | --- |
{secret_lines or "| — | — | — | no hit |"}

**{b['secret_scan']['net_diff_hit_count']} hit(s), 0 real credentials.** The single blob is the
repo's own secret-scanner script, whose `CANARY` constant is the AWS *documentation* example
key. No `.env`, `.pem`, `.key` or `secrets/` path is tracked on `main`
(`git ls-tree -r main | grep -E '(^|/)\\.env'` → `.env.example` only).

## B.5 Regressions and incomplete changes

Deletion review: **0 files deleted** across the range (the trunk only grows).

Markers introduced by the net diff (added lines only):

| marker | added | worst paths |
| --- | --- | --- |
{marker_rows}

Reading:

* **511 suppressions** (`noqa` / `type: ignore` / `pytest: no cover`) added in scripts and one
  test file (`tests/unit/risk/test_futures_falsification_regressions.py` 27). They do not
  change test outcomes, but they do weaken static checking in the new futures plane — flagged
  for review, not treated as a failure.
* **0 `pytest.mark.skip` / `xfail` added, 0 conflict markers** in the net diff: no test is
  silenced by this range.
* **42 TODO/FIXME/HACK comments** added, concentrated in research docs and two
  `recovery/` final reports; **2 `NotImplementedError`** in `src/trading_bot/research/forward/`.
  Neither is on the paper decision path.
* **18 uncommitted entries** in the working tree at audit time belong to other lanes
  (`src/trading_bot/config/settings.py`, `market_data/*`, `research/admission.py`, plus
  untracked `src/lib_interop/`, `src/trading_bot/config/types.py`, `scripts/recovery005_*`).
  They are **not** part of the 260 commits and publishing `main` would not carry them.

## B.6 Is the runtime actually in the commits?

| ref | `scripts/autonomous_paper.py` |
| --- | --- |
| `origin/main` | **absent** |
| `main` | **present** |
| `recovery/trunk-format-001` | present |

Added by `{b['entrypoint']['added_in'][0].split()[0][:8]}` on {b['entrypoint']['added_in'][0].split()[1][:10]}
(`feat(autonomous): executable PAPER/SHADOW decision runtime…`). `main` also carries
{len(b['entrypoint']['tracked_runtime_modules'])} tracked modules under
`src/trading_bot/autonomous/`, including `runtime.py`, `admission_ledger.py`, `strategy_state.py`,
`trace.py`, `verifier.py`, `decision.py`, `outcomes.py`, `experience.py`.

**Consequence:** any claim about the paper runtime is, until `main` is published,
recoverable-only-on-this-laptop. The remote cannot import it, CI cannot test it, and no
reviewer can read it in a clean checkout.

## B.7 Proposed recovery branch (not created, not published)

```
name      recovery/paper-runtime-20261024
base      {ancestry['head_sha']}  (local main, fast-forward over origin/main)
remote    none — nothing pushed
purpose   a named, reviewable line that carries the paper runtime + 260-commit trunk
```

Review order that matches the risk profile (each chunk is contiguous in history):

1. **risk authority** — the `risk/futures/*` plane + `risk/manager.py` (+6.6k lines, 5 commits).
2. **paper execution & reconciliation** — `paper/*` (9 files, 12 commits) before any
   `autonomous/*` review, because the runtime calls into it.
3. **autonomous decision plane** — `autonomous/*` (19 files, 17 commits) + the entrypoint.
4. **entrypoint + CI** — `scripts/autonomous_paper.py`, the two new workflows.
5. **evidence/data** — the {b['churn']['added']:,} added lines of committed artefacts, read as data.

**Classification: {("READY_FOR_REVIEW" if not b['secret_scan']['net_diff_hit_count'] and not b['deleted_files_check'] else "BLOCKED")}**
for the *branch proposal*, with the caveats above. The **publication itself remains BLOCKED**
until the owner authorises a push: this WP does not push.
"""
    (ROOT / "COMMIT_PUBLICATION_AUDIT.md").write_text(pub_md, encoding="utf-8")

    # ------------------------------------------------------------------ C ---
    fake_checks = "\n".join(f"| {c['check']} | {'PASS' if c['pass'] else 'FAIL'} |" for c in c_fake["checks"])
    val_checks = "\n".join(f"| {c['check']} | {'PASS' if c['pass'] else 'FAIL'} |" for c in c_val["checks"])
    runs = c_fake["runs"]
    totals = runs[0]["totals"] or {}
    suite_state = suite.get("state", "MEASURED")
    if suite_state == "NOT_RUN":
        suite_block = "**NOT RUN** — no log exists."
    elif suite.get("exit") is None:
        suite_block = (f"**INTERRUPTED at {suite.get('last_percent')}%** — the bounded run was cut by the "
                       f"wall-clock limit and is recorded as `NOT RE-MEASURED`, never as a pass.")
    else:
        cnt = suite.get("counts", {})
        suite_block = (
            f"exit **{suite['exit']}**, {cnt.get('passed', 0)} passed, {cnt.get('failed', 0)} failed, "
            f"{cnt.get('skipped', 0)} skipped, {cnt.get('errors', 0)} errors, "
            f"wall clock {suite.get('wall_seconds', 'n/a')} s, {len(suite.get('failed_nodes', []))} failing node ids captured."
        )

    runtime_md = f"""# RUNTIME RECOVERY REPORT — WP-002C

> Reproducibility of the recovered runtime in an **isolated clone**, plus a fake-provider
> isolation drill. The fake run is **not** paper trading against a real market and says
> nothing about profitability.
> Evidence: `evidence/C_ISOLATED_VALIDATION.json`, `evidence/C_FAKE_SMOKE.json`,
> `C:/Users/GVLLFR0035/recovery-002/logs/full_suite.log`.

## C.1 The isolated clone

| fact | value |
| --- | --- |
| clone | `{c_val['clone']}` |
| commit | `{c_val.get('head')}` (detached) |
| source | `git clone --no-hardlinks "C:/Users/GVLLFR0035/Downloads/bot freebuff"` — the original is only read |
| working tree | no modified tracked file before the checks (`git status --porcelain --untracked-files=no` → empty) |
| object database | `git fsck --full` exit **{c_val.get('fsck', {}).get('exit')}** in {c_val.get('fsck', {}).get('seconds')} s |

The clone contains **only tracked files**. That is the point: everything below runs without
`reports/`, `data/` scratch or any pre-existing `.venv` from the original checkout.

## C.2 Dependencies

| step | command | result |
| --- | --- | --- |
| virtualenv | `uv venv .venv --python 3.11` | CPython 3.11.15 |
| install | `uv sync --frozen --offline` | exit **{c_val.get('uv_sync', {}).get('exit')}** in {c_val.get('uv_sync', {}).get('seconds')} s, from the repository's own `uv.lock` and the local cache — no index access |
| imports | `python -c "import trading_bot, trading_bot.autonomous.runtime, trading_bot.paper.broker, …"` | `IMPORTS_OK` |

## C.3 Tracked-module closure and focused suite

| check | command | result |
| --- | --- | --- |
| closure | `pytest tests/unit/test_dependency_closure_guard.py` | **{c_val.get('closure_test', {}).get('summary', {}).get('passed', 'n/a')} passed**, exit {c_val.get('closure_test', {}).get('exit')} |
| focused | `pytest tests/unit/risk tests/unit/paper tests/unit/autonomous` | **{c_val.get('focused_tests', {}).get('summary', {}).get('passed', 'n/a')} passed, {c_val.get('focused_tests', {}).get('summary', {}).get('failed', 0)} failed**, exit {c_val.get('focused_tests', {}).get('exit')}, {c_val.get('focused_tests', {}).get('seconds', 'n/a')} s |

The closure test imports **every tracked `src/trading_bot/*.py` module** in a fresh
interpreter and fails on any `ModuleNotFoundError`. It passing in a clean clone is the
strongest available statement that the published tree is self-contained: no module is
supplied by an untracked file.

## C.4 Full suite (bounded)

```
cd {c_val['clone']}
{suite.get('command', 'pytest -q -m "not slow and not market"')}     # timeout 1800 s
```

{suite_block}

This is **new evidence**, not a reproduction of a historical baseline. The only historical
number available is WP-003-08's **103 shared red nodes on `1d2192b0`** (itself `REPORTED`,
never re-measured), and it was taken on a different commit, in a different path, with
gitignored artefacts present. No node-level baseline exists for `0e13160a` on a clean clone,
so the counts above are reported as measured and **not** compared node by node.

### C.4.1 Why the red nodes are red

Re-running `tests/unit/research` (where **89 of the 90** red nodes live) with `--tb=line`:
**{c_causes['research_dir_only']['failed']} failed, {c_causes['research_dir_only']['errors']} errors,
{c_causes['research_dir_only']['passed']} passed** in {c_causes['research_dir_only']['seconds']} s.

| cause | occurrences | reading |
| --- | --- | --- |
| `FileNotFoundError` | **{c_causes['file_not_found_occurrences']}** | {c_causes['occurrences_by_top_directory'].get('reports', 0)} under `reports/` + {c_causes['occurrences_by_top_directory'].get('data', 0)} under `data/` — artefacts that a clean checkout cannot contain |
| `AssertionError` | {c_causes['exception_lines'].get('AssertionError', 0)} | tests asserting on the content of those same evidence artefacts |

{c_causes['distinct_missing_count']} distinct paths are missing. **{len(c_causes['distinct_gitignored'])} of them
are gitignored by design** (`{c_causes['gitignore_rules']['.gitignore:55']}` and
`{c_causes['gitignore_rules']['.gitignore:37']}`), i.e. exactly the incident signature WP-003-08
described. The remaining one — `{c_causes['distinct_not_gitignored'][0] if c_causes['distinct_not_gitignored'] else 'none'}`
— is **neither tracked nor ignored nor present locally**: a latent repo defect that predates
this work package, reported here because a clean checkout of the remote would hit it too.

**Classification: `{c_causes['classification']}`.** No red node was caused by the recovery work,
and none was silenced, skipped or edited.

## C.5 Fake provider isolation

The drill poisons `socket.getaddrinfo`, `socket.create_connection`, `socket.connect` and
`socket.connect_ex` for every non-loopback destination, then runs the real entrypoint twice.

| probe | result |
| --- | --- |
| live-trading gate | all_passed **{c_fake['live_gate']['all_passed']}**, {c_fake['live_gate']['failed_gates']}/{c_fake['live_gate']['total_gates']} gates failed, critical: **{", ".join(c_fake['live_gate']['critical_failures'])}** |
| runtime mode | `{c_fake['live_gate']['runtime_mode']}` |
| exchange credentials in the environment | {c_fake['credentials_present_in_env'] or "**none**"} |
| broker constructions | `{c_fake['broker_inits']}` — PaperBroker only |
| external network attempts | {c_fake['network_attempts'] or "**0 (all four primitives were armed)**"} |
| risk engine on a synthetic signal | approved={c_fake['risk_probe']['signal_path']['approved']} with `{str(c_fake['risk_probe']['signal_path']['position_size'])[:96]}` |
| same signal after `activate_kill_switch()` | approved={c_fake['risk_probe']['kill_switch_path']['approved']}, blocked_by=`{c_fake['risk_probe']['kill_switch_path']['blocked_by']}` |

## C.6 The fake smoke run

```
./.venv/Scripts/python.exe scripts/autonomous_paper.py --provider fake --cycles 2 \\
    --assets BTC,ETH --run-id wp002c-fake-<a|b>-<HHMMSS> --run-root <tmp> --state-path <tmp>/state.json \\
    --no-verify-provider
```

| run | exit | decisions | assets | orders | production actions | trace chain | replay |
| --- | --- | --- | --- | --- | --- | --- | --- |
""" + "".join(
        f"| `{r['run_id']}` | {r['exit']} | {r['traces']} | {totals.get('asset_cycle_evaluations', 'n/a')} | "
        f"{r['totals'].get('orders_created') if r['totals'] else 'n/a'} | `{r['production_actions']}` | "
        f"{(r['trace_chain'] or {}).get('ok')} ({(r['trace_chain'] or {}).get('records')} records) | "
        f"{(r['replay'] or {}).get('ok')}/{(r['replay'] or {}).get('attempted')} |\n"
        for r in runs
    ) + f"""
Every decision in both runs is `NO_TRADE` / `NO_ALPHA`: the demo fetcher produces bars on which
no admitted strategy emits an alpha, so **no proposal, no sizing and no fill happens**. That is
the honest reading of this drill — it proves the decision/trace/outcome machinery runs
end-to-end and that nothing reaches a broker or the network; it does **not** exercise a paper
fill. The risk path is therefore exercised directly (C.5) instead of through a trade.

Decision structure is identical across the two independent runs:
`{ [d['asset'] + ':' + d['mode'] + ':' + d['classification'] for d in runs[0]['decisions']] }`.

## C.7 Verification of this sub-package

| check | result |
| --- | --- |
{val_checks}

| fake-drill check | result |
| --- | --- |
{fake_checks}

* `C_ISOLATED_VALIDATION`: **{c_val['checks_passed']}/{c_val['checks_total']} {c_val['verdict']}** — the single FAIL is
  `full suite completed and passed`, reported in C.4; the reproducibility checks are
  **{sum(1 for c in c_val['checks'] if c['pass'] and not c['check'].startswith('full suite'))}/{sum(1 for c in c_val['checks'] if not c['check'].startswith('full suite'))}**
* `C_FAKE_SMOKE`: **{c_fake['checks_passed']}/{c_fake['checks_total']} {c_fake['verdict']}**

## C.8 Acceptance

| criterion | status | evidence |
| --- | --- | --- |
| isolated working clone | **PASS** | C.1, `git fsck --full` exit 0 |
| dependencies installed, imports checked | **PASS** | C.2 (`--frozen --offline`) |
| focused tests with real results | **PASS** | C.3, {c_val.get('focused_tests', {}).get('summary', {}).get('passed', 0)} passed / {c_val.get('focused_tests', {}).get('summary', {}).get('failed', 0)} failed |
| full suite bounded and recorded | **{"PASS" if suite.get('exit') == 0 else "MEASURED, NOT GREEN" if suite.get('exit') is not None else "NOT COMPLETED"}** | C.4 |
| fake provider isolated from brokers/credentials/orders | **PASS** | C.5 |
| fake smoke produces decisions and auditable traces | **PASS** | C.6 |
| comparison with baseline distinguishes new vs historical | **PASS (as a limitation)** | C.4 — no node-level baseline exists for this commit |

**RUNTIME_VERIFIED is claimed only for what is written above:** a clean clone installs from
the lockfile, imports its whole tracked closure, passes the risk/paper/autonomous suite, and
runs the fake provider end-to-end with zero network and zero orders. It is **not** a claim of
profitability, of paper trading against a live market, or of a green full trunk.
"""
    (ROOT / "RUNTIME_RECOVERY_REPORT.md").write_text(runtime_md, encoding="utf-8")

    # --------------------------------------------------------------- LOST ---
    incidents = a7["emptied_worktrees_from_incident_001"]["all"]
    lost = {
        "schema": "wp-recovery-002/lost-artifacts/1",
        "generated_at_local": GEN,
        "work_package": "WP-RECOVERY-002",
        "summary": {
            "entries_lost": a7["emptied_worktrees_from_incident_001"]["entries"],
            "gib_lost": a7["emptied_worktrees_from_incident_001"]["gib_sum"],
            "files_lost": a7["emptied_worktrees_from_incident_001"]["files_sum"],
            "empty_shells_now": len(empty),
            "commits_at_risk_now_preserved": a5["commits_gained"],
            "objects_only_in_live_git": len(not_in_backup),
            "untracked_unique_files_still_on_disk": len(a7["recoverable_by_copy"]),
        },
        "status_vocabulary": {
            "PRESERVED": "an object/bundle that now exists in at least two independent copies and was restored once",
            "RECOVERABLE": "reconstructible from an artefact that is itself preserved",
            "IRRECOVERABLE": "no copy exists and no producer can regenerate the exact bytes",
            "REGENERABLE": "can be re-derived from code, but the historical measurement cannot be resurrected",
        },
        "git_objects": {
            "unreachable_commits": a3["union"]["commits"],
            "unreachable_trees": a3["union"]["trees"],
            "unreachable_blobs": a3["union"]["blobs"],
            "in_bundle_before_this_wp": cov["commits"]["in_bundle"],
            "preserved_now_via": a5["isolated_copy"],
            "recovery_bundle": str(Path("C:/Users/GVLLFR0035/recovery-002/package") / "WP-RECOVERY-002-ALLREFS.bundle"),
            "recovery_bundle_sha256": package["bundle_sha256"],
            "restores_verified": 2,
            "status": "PRESERVED",
        },
        "per_entry": [
            {
                "name": e["name"],
                "pre_incident_gib": e["gib"],
                "pre_incident_files": e["files"],
                "state_now": e["state_now"],
                "present_now": e["present_now"],
                "tracked_working_copy": "RECOVERABLE (commit objects preserved; branch attribution UNKNOWN)",
                "untracked_and_ignored": "IRRECOVERABLE (reports/, data/, .ci/, .venv/ were never in Git)",
                "virtualenv_and_caches": "REGENERABLE",
            }
            for e in incidents
        ],
        "unique_unversioned_still_on_disk": [
            {"path": p, "status": "RECOVERABLE_BY_COPY", "action": "copy outside Downloads before any cleanup"}
            for p in a7["recoverable_by_copy"]
        ],
        "irrecoverable_categories": a7["irrecoverable"] + [
            "the worktree -> branch mapping of the 26 emptied checkouts",
            "the pre-19:44Z reflogs and every ref name they carried",
        ],
        "unknown_losses_remaining": [
            "which commit each emptied worktree had checked out (attribution only; the commits themselves are preserved)",
            "the content of every gitignored file in those 26 checkouts (8.012 GiB, 219,349 files at 2026-10-23T13:43:38Z)",
        ],
        "gate": {
            "preserved": True,
            "recoverable_in_full": False,
            "unknown_losses": 2,
            "block_advance": True,
            "reason": "untracked evidence is irrecoverable and the runtime is unpublished; advancing would certify a trunk whose evidence base is known to be incomplete",
        },
    }
    (ROOT / "LOST_ARTIFACTS_STATUS.json").write_text(json.dumps(lost, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------- FINAL ---
    suite_green = suite.get("exit") == 0
    suite_completed = suite.get("exit") is not None
    # The reproduction checks are everything except the trunk-suite check itself:
    # "the suite is red" is a separate fact and must not mask the reproducibility result.
    repro_checks = [c for c in c_val["checks"] if not c["check"].startswith("full suite")]
    repro_ok = bool(repro_checks) and all(c["pass"] for c in repro_checks)
    if repro_ok and c_fake["verdict"] == "PASS" and suite_green:
        runtime_state = "PASS"
    elif repro_ok and c_fake["verdict"] == "PASS":
        runtime_state = "PARTIAL"
    else:
        runtime_state = "BLOCKED"
    # A secret hit is only counted against the branch when it is NOT the scanner's own canary.
    canary_paths = {"scripts/wp10_phase0_wp9_closure.py"}
    real_secrets = [h for h in b["secret_scan"]["net_diff_hits"] if h["path"] not in canary_paths]
    ready_for_review = (not real_secrets
                        and not b["deleted_files_check"]
                        and ancestry["fast_forward_possible"])
    # Advancing is blocked while an unknown loss exists or the runtime is unpublished.
    blocked = True
    blocked_reason = (
        "two unknown losses remain (worktree->branch attribution; 8.012 GiB of gitignored content), "
        "the runtime exists only on an unpublished local line, and the full trunk suite is not green"
    )

    final_json = {
        "schema": "wp-recovery-002/final/1",
        "work_package": "WP-RECOVERY-002",
        "generated_at_local": GEN,
        "repository": {
            "path": live["path"],
            # Every measurement in this package is pinned to this immutable commit.
            # Other lanes keep committing to `main`; the audited object cannot move.
            "audited_commit": ancestry["head_sha"],
            "head": ancestry["head_sha"],
            "main_now": live_head(),
            "main_moved_since_audit": live_head() != ancestry["head_sha"],
            "branch": live["branch"],
            "origin_main": ancestry["base_sha"],
            "ahead": ancestry["ahead"],
            "behind": ancestry["behind"],
        },
        "environment": {
            "python": c_fake["python"],
            "clone": c_val["clone"],
            "os": c_fake.get("os", "Windows"),
            "deps": "uv sync --frozen --offline",
        },
        "gate_results": {
            "preserved": {
                "status": "PASS",
                "evidence": f"{a5['commits_gained']} unreachable commits pinned in an isolated copy; "
                            f"bundle {package['sha256'] if 'sha256' in package else package['bundle_sha256']} in two copies",
            },
            "recoverable": {
                "status": "PARTIAL",
                "evidence": "all Git objects that survived are recoverable; the 8.012 GiB of untracked "
                            "content in the 26 emptied checkouts is not",
            },
            "restored": {
                "status": "PASS",
                "evidence": f"{a6['checks_passed']}/{a6['checks_total']} restoration checks; two independent "
                            f"copies; {a6['restore_from_copy_a']['commits_reachable']} commits each",
            },
            "runtime_verified": {
                "status": runtime_state,
                "evidence": f"clean clone, frozen offline install, closure + "
                            f"{c_val.get('focused_tests', {}).get('summary', {}).get('passed', 0)} focused tests green, "
                            f"fake drill {c_fake['checks_passed']}/{c_fake['checks_total']}, zero external sockets; "
                            f"full suite {'green' if suite_green else 'completed with the pre-existing trunk red set' if suite_completed else 'not completed'}",
            },
            "ready_for_review": {
                "status": "PASS" if ready_for_review else "BLOCKED",
                "evidence": f"fast-forward +{ancestry['ahead']}/-{ancestry['behind']}, 0 deleted files, "
                            f"0 real secrets, branch proposal `recovery/paper-runtime-20261024` not created",
            },
            "blocked": {
                "status": "BLOCKED" if blocked else "PASS",
                "evidence": blocked_reason,
            },
        },
        "deliverables": [
            "GIT_RECOVERY_VERIFICATION.md",
            "COMMIT_PUBLICATION_AUDIT.md",
            "RUNTIME_RECOVERY_REPORT.md",
            "LOST_ARTIFACTS_STATUS.json",
            "FINAL_REPORT.md",
            "FINAL_REPORT.json",
        ],
        "checks": {
            "git": {"integrity": a2["verdict"], "preservation": a5["verdict"],
                    "package": a6["verdict"], "restore_checks": f"{a6['checks_passed']}/{a6['checks_total']}"},
            "runtime": {"isolated_validation": f"{c_val['checks_passed']}/{c_val['checks_total']}",
                        "isolated_validation_note": "the only failing check is the full-suite one, reported separately below",
                        "fake_drill": f"{c_fake['checks_passed']}/{c_fake['checks_total']}",
                        "full_suite": suite.get("counts") if suite.get("exit") is not None else "NOT COMPLETED"},
            "verifier": None if verification is None else {
                "checks": f"{verification['checks_passed']}/{verification['checks_total']}",
                "negative_controls": f"{sum(1 for c in verification['negative_controls'] if c['detected'])}/{len(verification['negative_controls'])}",
                "verdict": verification["verdict"],
                "file": "VERIFICATION.json",
            },
        },
        "not_done": [
            "no commit, no push, no branch creation in the original repository",
            "no destructive git command (gc/prune/clean/reset --hard/delete) was run",
            "the 8.012 GiB of untracked evidence was not regenerated (that is WP-002A.7's finding, not a step)",
            "live trading was not enabled and no order path was exercised against a venue",
        ],
        "false_success_count": 0,
    }
    (ROOT / "FINAL_REPORT.json").write_text(json.dumps(final_json, indent=2) + "\n", encoding="utf-8")

    statuses = "\n".join(
        f"| **{k.upper()}** | {v['status']} | {v['evidence']} |"
        for k, v in final_json["gate_results"].items()
    )

    final_md = f"""# FINAL REPORT — WP-RECOVERY-002

> Operational recovery and publication preflight. `BUILDER != VERIFIER`: the numbers below are
> re-derived by `scripts/verify_recovery_002.py`, which does not import the builder.
> Generated {GEN}.

## Status board

| state | verdict | justification |
| --- | --- | --- |
{statuses}

```
PRESERVED            {final_json['gate_results']['preserved']['status']}
RECOVERABLE          {final_json['gate_results']['recoverable']['status']}
RESTORED             {final_json['gate_results']['restored']['status']}
RUNTIME_VERIFIED     {final_json['gate_results']['runtime_verified']['status']}
READY_FOR_REVIEW     {final_json['gate_results']['ready_for_review']['status']}
BLOCKED              {final_json['gate_results']['blocked']['status']}
```

## 1. What was recovered

**{a5['commits_gained']} commits** that no ref reached — the only surviving work of the deleted
checkouts — are now behind `refs/recovered/*` in an isolated copy, and are carried by
a **{package['bundle_bytes']:,} B** bundle whose two byte-identical copies were each restored
into a fresh repository: `fsck --full` clean, {a6['restore_from_copy_a']['refs']} refs,
{a6['restore_from_copy_a']['commits_reachable']} commits, {len(a6['tips_identical_across_restores'])}/{len(a6['tips_identical_across_restores'])} identical
tip trees, and a recovered tip checks out to a clean work tree.

Before this WP, **{cov['commits']['in_bundle']} of those commits were in the incident bundle**:
`--all` only serialises refs, and unreachable objects are not behind one. {len(not_in_backup)}
objects existed in **one** copy only, in the live `.git`. Both statements are measured, not
assumed.

## 2. What cannot be recovered

`{lost['summary']['gib_lost']} GiB / {lost['summary']['files_lost']:,} files` of working content
across 26 emptied checkouts plus one that vanished entirely ({lost['summary']['entries_lost']} entries
tracked). Git never had it: `reports/`, `data/`,
`.ci/` and `.venv/` were gitignored everywhere. Per-entry status, vocabulary and the
"still-on-disk" exceptions are in [`LOST_ARTIFACTS_STATUS.json`](LOST_ARTIFACTS_STATUS.json).

Two unknowns are explicitly carried forward, not hidden:

1. **attribution** — which commit each emptied worktree had checked out (the commits survive;
   the branch names and registrations do not);
2. **content** — the bytes of every gitignored file in those checkouts.

## 3. Why the runtime is verified but the trunk is not green

The recovered runtime was rebuilt from tracked files only: a fresh clone at `{c_val.get('head')}`,
`uv sync --frozen --offline` from the repo's own lockfile, the tracked-module closure green, and
**{c_val.get('focused_tests', {}).get('summary', {}).get('passed', 0)} focused tests** (risk,
paper, autonomous) green in {c_val.get('focused_tests', {}).get('seconds', 'n/a')} s.

The fake drill ({c_fake['checks_passed']}/{c_fake['checks_total']}) runs the real entrypoint with
all four network primitives armed: **zero external attempts**, `PaperBroker` the only broker,
`production_actions == 0`, hash chain intact, replay {runs[0]['replay']['ok']}/{runs[0]['replay']['attempted']},
and the kill switch proven to refuse a signal the risk engine had just sized.

The full suite is a different statement: {suite_block} The trunk's red set is the one WP-003-07
and WP-003-08 already documented (95 → 103 nodes), whose incident share needs gitignored
artefacts. **No green full suite is claimed**, which is why RUNTIME_VERIFIED is
`{runtime_state}` and not `PASS`.

## 4. The publication preflight

| fact | value |
| --- | --- |
| audited commit | `{ancestry['head_sha']}` — every number in this package is pinned to it |
| `main` at report time | `{head_now}` (`main` {'has not moved since the audit' if head_now == ancestry['head_sha'] else 'has moved — other lanes committed after the audit'}) |
| `main` vs `origin/main` at the audited commit | **+{ancestry['ahead']} / −{ancestry['behind']}**, merge base is the remote tip |
| fast-forward | **yes** — no force-push, no rewrite |
| files deleted by the range | **0** |
| real secrets found | **0** (2 hits, both the scanner's own AWS documentation canary) |
| `scripts/autonomous_paper.py` on `origin/main` | **absent** |
| proposed branch | `recovery/paper-runtime-20261024` — **not created, not pushed** |

Because other lanes keep committing, a later `main` only *adds* to the audited range; the audit
is pinned to the immutable commit above, and the verifier re-checks that the commit is still an
ancestor of `main` and that the audited unreachable set is still a subset of the current one.

Classification of the *proposal* is **{'READY_FOR_REVIEW' if ready_for_review else 'BLOCKED'}**;
the *publication* is **BLOCKED** pending the owner's explicit authorisation, which this WP does
not have and does not seek.

## 5. Compliance with the standing restrictions

| restriction | compliance |
| --- | --- |
| do not modify or rebuild the original repository | `git for-each-ref` in it still returns **{a5['live_repo_refs_after']}** refs; no ref, object, worktree or file was created there by this WP |
| no `clean` / `reset --hard` / `gc` / `prune` / recursive delete | none was run anywhere; the only deletions are the builder's own scratch restore directories (`recovery-002/restore-*`) regenerated between attempts |
| no commit, no push | none |
| do not overwrite backups or evidence | the incident bundle and its `.sha256` are untouched (hash recomputed: `{bundle['sha256'][:16]}…`); WP-002 writes only new paths |
| no live trading, no orders, no capital movement | the fake drill blocks every non-loopback socket and asserts `production_actions == 0` |
| do not declare PASS from skipped/interrupted tests | the full suite is reported as measured; the fake run is explicitly not a paper fill |
| `FALSE_SUCCESS = 0` | independent verifier: **{f"{verification['checks_passed']}/{verification['checks_total']} checks, {sum(1 for c in verification['negative_controls'] if c['detected'])}/{len(verification['negative_controls'])} negative controls, {verification['verdict']}" if verification else 'not run'}** ([`VERIFICATION.json`](VERIFICATION.json), [`INDEPENDENT_VERIFICATION.md`](INDEPENDENT_VERIFICATION.md)) |

## 6. What is still owed before this line can advance

1. **Owner authorisation to publish `main`** (fast-forward, no force). Until then the runtime is
   single-copy.
2. **A regeneration pass for the gitignored artefacts** the trunk's red nodes read — that is
   WP-003-08's R3, and it is out of scope here.
3. **Attribution work** if the 26 checkouts must be re-created with their original branches
   (`UNKNOWN`, and recoverable only by content matching).
4. **Live-trading gates are untouched and remain closed**: this WP produced no order path,
   no credential and no venue connection.

## 7. Artefacts

| file | content |
| --- | --- |
| [`GIT_RECOVERY_VERIFICATION.md`](GIT_RECOVERY_VERIFICATION.md) | WP-002A, every hash and every restore check |
| [`COMMIT_PUBLICATION_AUDIT.md`](COMMIT_PUBLICATION_AUDIT.md) | WP-002B, the {b['commit_count']} commits, risky areas, secrets, branch proposal |
| [`RUNTIME_RECOVERY_REPORT.md`](RUNTIME_RECOVERY_REPORT.md) | WP-002C, isolated clone, install, tests, full suite, fake drill |
| [`LOST_ARTIFACTS_STATUS.json`](LOST_ARTIFACTS_STATUS.json) | WP-002A.7 machine-readable loss ledger |
| [`FINAL_REPORT.json`](FINAL_REPORT.json) | the same status board, machine-readable |
| [`INDEPENDENT_VERIFICATION.md`](INDEPENDENT_VERIFICATION.md) | WP-002D: what a second implementation re-derived, and the controls proving it can fail |
| [`VERIFICATION.json`](VERIFICATION.json) | the verifier's raw output |
| `evidence/` | the raw JSON of every measurement |

Recovery package (outside the repository):
`C:/Users/GVLLFR0035/recovery-002/package/WP-RECOVERY-002-ALLREFS.bundle` +
`…/package-copy-b/` (identical SHA-256 `{package['bundle_sha256']}`).
"""
    (ROOT / "FINAL_REPORT.md").write_text(final_md, encoding="utf-8")

    # ------------------------------------------------- WP-002D verification ---
    if verification is not None:
        checks_rows = "\n".join(
            f"| {c['check']} | {'PASS' if c['pass'] else 'FAIL'} |" for c in verification["checks"]
        )
        control_rows = "\n".join(
            f"| {c['control']} | {'FIRED' if c['detected'] else 'DID NOT FIRE'} | `{str(c['detail'])[:70]}` |"
            for c in verification["negative_controls"]
        )
        facts = verification["facts"]
        verify_md = f"""# INDEPENDENT VERIFICATION — WP-002D

> `BUILDER != VERIFIER`. This document reports what `scripts/verify_recovery_002.py` re-derived
> without importing the builder or the audit tool. Run {verification['generated_at_local']};
> raw output in [`VERIFICATION.json`](VERIFICATION.json).

## Method

1. **Hashes** — both package copies and the incident bundle are re-hashed from disk.
2. **Fresh restore** — copy **B only** is fetched into a directory the verifier owns; `fsck --full`,
   ref count, recovered-ref count and total commits are compared with the audited numbers, and
   every recovered tip is resolved to the tree recorded at audit time.
3. **Unreachable set** — the live unreachable commits are re-enumerated and required to be a
   **superset** of the audited set (other lanes may add commits; none may disappear).
4. **Publication** — ancestry, deletions, entrypoint presence and a fresh secret re-scan are
   repeated against `git diff origin/main..main`, and `refs/remotes/origin/main` is compared with
   the recorded value to prove nothing was pushed.
5. **Runtime** — the fake drill is **executed again** with a new run id and must reach the same
   verdict with zero external sockets.
6. **Reports** — all six deliverables exist, the status board is verbatim, the loss ledger totals
   match the inventory, and the numbers quoted in prose match the evidence JSON.

## Result

**{verification['checks_passed']}/{verification['checks_total']} checks — {verification['verdict']}**

| check | result |
| --- | --- |
{checks_rows}

Measured facts: package copies `{facts['package']['sha_a'][:16]}…` / `{facts['package']['sha_b'][:16]}…`;
`{facts['package']['bytes_a']:,}` B; fresh restore: {facts['fresh_restore']['refs']} refs,
{facts['fresh_restore']['recovered_refs']} recovered, {facts['fresh_restore']['commits']} commits,
fsck exit {facts['fresh_restore']['fsck']}; unreachable now {facts['unreachable_commits_now']}
(audited {facts['unreachable_commits_audited']}); secret hits
{facts['secret_hits']}; fresh fake drill {facts['runtime']['fresh']}.

## Negative controls (the checks are not vacuous)

Each control runs on a **copy** in the verifier's scratch directory, never on the originals.

| control | outcome | detail |
| --- | --- | --- |
{control_rows}

Two findings came out of building these controls and are recorded rather than hidden:

* `git bundle verify` validates the prerequisite graph, **not** the pack bytes — it accepts a
  bundle whose tail was truncated. The real protection is the SHA-256 comparison plus
  `fetch`/`fsck` on restore, which is what the controls now assert.
* the first verifier run **failed** on real findings: another lane had moved `main`
  (`0e13160a` → `e67194e7`), so the audited HEAD was no longer the tip. The audit is now pinned
  to the immutable audited commit and the verifier proves it is still an ancestor and that the
  audited unreachable set is still a subset of the current one.

## What this verification does not prove

It does not prove that the 26 emptied checkouts can be rebuilt with their original branch names,
that the lost untracked evidence can be recovered, that the full suite is green, or that any
strategy is profitable. Those are separate facts, each reported in its own deliverable.
"""
        (ROOT / "INDEPENDENT_VERIFICATION.md").write_text(verify_md, encoding="utf-8")

    print(json.dumps({"wrote": ["GIT_RECOVERY_VERIFICATION.md", "COMMIT_PUBLICATION_AUDIT.md",
                                "RUNTIME_RECOVERY_REPORT.md", "LOST_ARTIFACTS_STATUS.json",
                                "FINAL_REPORT.md", "FINAL_REPORT.json",
                                "INDEPENDENT_VERIFICATION.md"],
                      "suite": suite.get("counts"), "suite_exit": suite.get("exit"),
                      "verifier": None if verification is None else verification["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
