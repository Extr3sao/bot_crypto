# WP-EDGE-12 — runtime authority map

Read from the runtime in WP-EDGE-12A. The point of the table is the separation: the
scheduler does not decide what to observe, the observer does not decide what to
promote, and the verifier does not decide whether the builder was right.

| component | authority | where it is visible | what it cannot do |
| --- | --- | --- | --- |
| Windows Scheduler | when the observer starts; currently `Ready`, logon type `Interactive`, 1 trigger(s) | the registration, read from the host | nothing about the observation: it cannot seal a slot, ingest a bar or refuse a ruleset |
| the observer (`scripts/edge04_observer.py`) | one tick: fetch, classify, seal the slot, write the daily evidence | 254 run row(s) in `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04` | no order, no promotion, no risk parameter |
| the forward plan (`edge03/forward_plan.py`) | the frozen corpus and the frozen ruleset; a moved input is a refusal | the pin re-derived on every tick | cannot measure a tuned rule, by construction |
| the storage guard (`disk_space.py`) | whether a tick may make a market request at all | the refusal outcome and the free-space reading in each run row | cannot delete the store or the daily evidence to make room |
| the lease (`campaign_lock.py`) | which process may write | the lease record and the `ALREADY_RUNNING` outcome | cannot prove a pid is dead; the age rule decides |
| the coverage rule (`prospective_days`) | which days count as observation | the day classes in the coverage artefact | cannot count a backfilled day as forward |
| WP-EDGE-12F verifier | whether the builder's records are reproducible | this package's `VERIFICATION.json` | cannot promote, and shares no code with the audit it checks |
| an operator | the mechanisms that need a privilege or a credential | `OPERATOR_HANDOFF.md` | is asked, not assumed: nothing in this package is applied |

## The boundary this package does not cross

No component in this map can place an order or admit a strategy. That is not a
convention held by the people writing the code: it is the absence of an exchange
client in the import graph, which WP-EDGE-12A measures by importing every module the
lane depends on in a fresh interpreter (9/9 imported) and by reading `order_sent` and `promotion` out
of every record the lane wrote.
