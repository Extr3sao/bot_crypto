"""RFC-EDGE-012 — forward continuity activation and operational certification.

WP-EDGE-04R measured *why* the forward observer loses triggers: the host is up and
nobody is signed in, and the task is registered ``LogonType=InteractiveToken``. That
measurement produced a set of deliverables, and this package turns them into a
certification attempt: what depends on what, which mechanism could remove the
dependence, whether the storage can hold sixty days, whether continuity holds when
the process dies, and what the runtime actually did.

The modules are separated by the question each one answers, not by the artefact it
happens to write:

* :mod:`trading_bot.research.edge12.gate` — **12A**. What exists, what is reachable
  from the runtime, and what exists only in a document or a test. The dependency
  audit is against the running host, not against the repository's intent.
* :mod:`trading_bot.research.edge12.runner` — **12B**. Which mechanism can start the
  observer without an interactive session, what each one costs, what a preflight can
  check before an operator applies it, and how to undo it.
* :mod:`trading_bot.research.edge12.storage` — **12C**. Whether sixty days of
  observation fit, and what the forecast is allowed to say when the measured growth
  rate is not stable enough to forecast from.
* :mod:`trading_bot.research.edge12.continuity` — **12D**. What happens when the
  process dies, when the session returns, when two triggers collide and when a
  write is interrupted — exercised against the real observer, not asserted.
* :mod:`trading_bot.research.edge12.operational` — **12E**. What the lane did over a
  declared window, with the three levels kept apart: a trigger that fired, an
  observation that was made, and a day that is admissible.
* :mod:`trading_bot.research.edge12.render` — the deliverable set, rendered.

Two rules hold everywhere in this package. Nothing here promotes a strategy, sends
an order or holds a credential; every record carries ``hypothetical: true`` and
``order_sent: false``. And nothing here edits the live task: the mechanisms are
*attempted* on throwaway registrations, and applying one is an operator's decision
recorded as a proposal with a rollback.
"""

from __future__ import annotations

__all__ = ["continuity", "gate", "operational", "render", "runner", "storage"]
