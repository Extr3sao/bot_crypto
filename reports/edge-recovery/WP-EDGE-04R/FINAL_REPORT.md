# WP-EDGE-04R — closing report: the forward observer's continuity, attributed

**Reading instant:** 2026-10-15T18:31:46Z. **Window:** 55.136 h, 221 scheduled trigger instants.
**Verdict:** the observer's engineering is sound; its continuity is bounded by the session,
and that bound has been measured, priced and handed to an operator with the exact commands.

## 1. The one number this work package exists to explain

WP-EDGE-04 published "74 of 96 triggers in a window" and nothing else, because the host's
trigger history was unreadable. WP-EDGE-04R places every expected instant on a timeline and
attributes it:

```
221 expected
 195 answered by a tick        (152 consumed their slot, 43 fired and were refused by the guard)
  26 never answered by anything
      24  NO_SESSION      one 6.355 h window with the host up and nobody signed in
       1  HOST_DOWN       two reboots, 458.5 s
       1  SILENT          host up, session present, no record at all
       0  SLEEP           the host recorded no sleep
```

## 2. What WP-EDGE-04 got wrong, and how this was corrected

WP-EDGE-04 said the host "sleeps" and that the missing triggers followed from that. The
record says otherwise: **no sleep and no standby in the window** (0 sleep/resume pairs; the
Power-Troubleshooter log is empty). The corrected statement is narrower and more useful:
the triggers were lost because **no interactive session existed**, and a task registered
`LogonType=InteractiveToken` cannot start without one. A second correction: 43 of the 69
losses are **not scheduling losses at all** — the storage guard fired, refused before any
market request, and the trigger was spent.

Both corrections came from measuring, not from reasoning about the configuration.

## 3. What was implemented

* `src/trading_bot/research/edge04r/os_evidence.py` — reads what the host itself recorded
  (boots, shutdowns, session logons/logoffs, power transitions, the registered task, the
  storage estate). It never reads a credential (the autologon probe reads the switch and the
  account name only), never invents a cause, and never changes the host.
* `src/trading_bot/research/edge04r/continuity.py` — the attributed audit: phase measured
  from the launches, one-to-one matching of instants to ticks, per-instant attribution with
  an explicit precedence, per-day reconciliation, storage reading, invariants.
* `src/trading_bot/research/edge04r/session.py` — the session-independence probes, and the
  task definition that adds a `LogonTrigger` and a witness action.
* `scripts/edge04r_continuity.py` — collect, audit, render; `--offline --stored-snapshot
  --until` reproduces the reading from the committed evidence alone.
* `scripts/edge04r_verify.py` — an independent verifier that shares no code with the audit
  and pays for each of its checks with a sabotage.
* `tests/unit/research/test_edge04r_continuity.py` — 26 tests, including a regression for a
  bug this audit shipped and fixed: walking the boot list and the shutdown list separately
  reported a boot *before* its shutdown as downtime.

## 4. What would remove the session dependence, and what each one needs

| mechanism | verdict | requires |
| --- | --- | --- |
| Logon trigger (bounds recovery) | **VIABLE, exercised** | nothing new |
| Witness action (makes silences attributable) | **VIABLE, exercised** | nothing new |
| S4U task (removes the dependence) | needs elevation | the batch-logon right |
| Windows service | needs elevation | administrator rights |
| Automatic logon | needs a credential | the account password stored on the machine |
| Task Scheduler operational log | needs elevation | administrator rights |

The two mechanisms that would **remove** the dependence are both behind an administrator;
the two that are available **bound** the loss instead of preventing it. That is the honest
shape of this problem, and it is why the recommendation is not "install this and the 60
days will accrue".

## 5. Storage

The lane's tree is 12 368 125 B of its own declared 268 435 456 B budget: the lane is not
what fills the volume. There is no volume with capacity on this host to move the store to
(`NO_VOLUME_WITH_CAPACITY`): one NVMe disk, one data partition at 97 % used, and a Google
Drive FAT32 mount whose reported capacity is the host's own. Nothing was moved and no other
workstream's data was touched.

The guard's own behaviour is the part that worked: it refused 43 triggers *before* any
market request, so the volume's 97 % occupancy cost slots, never a false observation.

## 6. What the deliverables are worth

* **Re-checkable.** The reading is a function of a committed snapshot plus a declared
  instant; the verifier re-implements the arithmetic from that snapshot and reaches the same
  numbers, or says which one it cannot.
* **Adversarially tested.** The verifier's every claim is paid for with a sabotage: a
  mutated input that must make it fail. Undetected sabotages are reported as failures of the
  check, not hidden.
* **Honest about the residual.** Two instants remain unexplained (`SILENT_UNATTRIBUTABLE`)
  and one check is `NOT_EXERCISED`: no logoff, no reboot and no sign-in happened during this
  pass, because provoking one would end the session this work runs in.

## 7. What is still missing for the 60 days

1. **Time — 0 of 60 admissible days.** Nothing in this work package substitutes for it.
2. **A host that is signed in**, or an administrator who registers the task for S4U. With
   `AutoAdminLogon=0`, every reboot costs an indefinite silence until a person signs in.
3. **Volume headroom.** 10.764 h of the window sat below the guard's critical floor. That
   is not the lane's bytes; it is the volume's, and only an operator can decide what else
   lives there.
4. **Not exercised:** a real logoff/logon cycle under the proposed trigger set, an S4U task
   running with no session, and a real provider outage.

## 8. Regressions run

| suite | result |
| --- | --- |
| `tests/unit/research/test_edge04r_continuity.py` | **26 passed** |
| `tests/unit/research/test_edge04_autonomous.py` | see `GIT_STATE.json` |
| `tests/unit/research` (wider) | see `GIT_STATE.json` |
| `test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout` | **FAIL, inherited and diagnosed** — `STALE_BY_PROVENANCE`, §6 of `RUN_REPORT.md`; the cause is a one-day-later re-render by the lane that owns the artefact, not a false claim |
| `ruff` on everything added | clean |

**This work package authorises PAPER or LIVE trading under no circumstances whatsoever.**
`hypothetical: true`, `order_sent: false`, promotion `NONE` in every artefact it produced,
and the frozen ruleset digest `d073a2d6…` re-derived here, agreed by the imported constant,
by the campaign's own publication and by every tick record.

## 9. Re-checking this package

```bash
python scripts/edge04r_continuity.py --offline --stored-snapshot --until 2026-10-15T18:31:46Z
python scripts/edge04r_session.py --no-probe
python scripts/edge04r_verify.py --reports reports/edge-recovery/WP-EDGE-04R --repo . --self-test
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_edge04r_continuity.py -q
```
