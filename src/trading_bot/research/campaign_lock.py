"""CAP-004 — single-instance lease and the graceful STOP convention.

Two runners writing the same ledger would still be safe (the ledger refuses
duplicates) but they would waste work and blur the audit trail: a reader could
not tell whether a missed slot was a real miss or simply a second process that
happened not to be the one that sealed it.  So the runner takes a lease first.

The repository has no generic lock helper (no ``O_EXCL``, ``fcntl`` or
``msvcrt`` usage anywhere), but it does have a clear idiom: a long-running local
process publishes a *heartbeat* and watches for a ``STOP`` file.  This module
keeps that idiom and adds the missing piece:

* the lease records ``pid``, ``acquired_at`` and ``renewed_at``;
* it is **renewable** and considered abandoned once it stops being renewed, which
  is portable across platforms and survives a hard kill (a dead process cannot
  renew, so a crashed run never wedges the campaign forever);
* ``pid`` liveness is probed as a *hint* only — where the platform cannot answer
  (``os.kill`` semantics differ on Windows), the age rule decides, so the check
  is never a guess dressed up as a fact.

A second process sees ``ALREADY_RUNNING`` and exits without touching the ledger.
``STOP`` ends continuous mode gracefully at the next cycle boundary.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from trading_bot.research.campaign_reporting import write_json_atomic

__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "LEASE_VERSION",
    "LOCK_FILENAME",
    "STOP_FILENAME",
    "CampaignLock",
]

LOCK_FILENAME = "CAMPAIGN_LOCK.json"
STOP_FILENAME = "STOP"
LEASE_VERSION = "CAMPAIGN_LEASE_V1"
DEFAULT_STALE_AFTER_SECONDS = 1_800


def _pid_probe(pid: int) -> bool | None:
    """``True`` alive, ``False`` gone, ``None`` when the platform cannot say.

    A probe that cannot answer must *say so*, never raise: the caller is deciding whether to
    reclaim a lease, and a platform that refuses to answer is exactly the case the lease's own
    age rule exists for. Raising here turns a stale lease into a crashed process.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except SystemError:
        # Windows answers a pid it cannot map with ``WinError 87`` raised as ``SystemError``,
        # which is not an ``OSError`` and so would otherwise escape both handlers below.
        return None
    except OSError:
        return None
    return True


class CampaignLock:
    """A renewable lease over one campaign directory."""

    def __init__(
        self,
        root: Path,
        *,
        campaign_id: str,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
        host: str | None = None,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be > 0")
        self.root = Path(root)
        self.campaign_id = campaign_id
        self.stale_after_seconds = int(stale_after_seconds)
        self.host = host or socket.gethostname()

    # -- paths ------------------------------------------------------------ #

    @property
    def path(self) -> Path:
        return self.root / LOCK_FILENAME

    @property
    def stop_path(self) -> Path:
        return self.root / STOP_FILENAME

    # -- lease state ------------------------------------------------------ #

    def holder(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        try:
            loaded: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"corrupt": True}
        return loaded

    def is_stale(self, holder: Mapping[str, Any] | None, *, now: int) -> bool:
        if holder is None:
            return True
        if holder.get("corrupt"):
            return True
        if str(holder.get("campaign_id", "")) != self.campaign_id:
            return True
        renewed = holder.get("renewed_at")
        if not isinstance(renewed, int):
            return True
        if int(now) - renewed > self.stale_after_seconds:
            return True
        pid = holder.get("pid")
        if isinstance(pid, int) and pid != os.getpid():
            return _pid_probe(pid) is False
        return False

    def acquire(self, *, now: int) -> dict[str, Any]:
        """Take the lease, or report who holds it.  Never blocks, never waits."""
        holder = self.holder()
        if holder is not None and not self.is_stale(holder, now=now):
            return {
                "acquired": False,
                "status": "ALREADY_RUNNING",
                "holder": holder,
                "lease_age_seconds": int(now) - int(holder.get("renewed_at", now)),
            }
        reclaimed = holder is not None
        record = {
            "lease_version": LEASE_VERSION,
            "campaign_id": self.campaign_id,
            "pid": os.getpid(),
            "host": self.host,
            "acquired_at": int(now),
            "renewed_at": int(now),
            "stale_after_seconds": self.stale_after_seconds,
        }
        write_json_atomic(self.path, record)
        return {
            "acquired": True,
            "status": "STALE_LEASE_RECLAIMED" if reclaimed else "ACQUIRED",
            "holder": record,
            "previous_holder": holder if reclaimed else None,
        }

    def renew(self, *, now: int) -> dict[str, Any]:
        holder = self.holder()
        if holder is None or str(holder.get("campaign_id")) != self.campaign_id:
            return {"renewed": False, "status": "NO_LEASE"}
        if holder.get("pid") != os.getpid():
            return {"renewed": False, "status": "NOT_THE_HOLDER", "holder": holder}
        updated = {**holder, "renewed_at": int(now)}
        write_json_atomic(self.path, updated)
        return {"renewed": True, "status": "RENEWED", "holder": updated}

    def release(self) -> dict[str, Any]:
        holder = self.holder()
        if holder is None:
            return {"released": False, "status": "NO_LEASE"}
        if holder.get("pid") != os.getpid():
            return {"released": False, "status": "NOT_THE_HOLDER", "holder": holder}
        self.path.unlink(missing_ok=True)
        return {"released": True, "status": "RELEASED"}

    # -- graceful stop ---------------------------------------------------- #

    def stop_requested(self) -> bool:
        return self.stop_path.is_file()

    def request_stop(self, *, reason: str = "operator") -> Path:
        self.stop_path.parent.mkdir(parents=True, exist_ok=True)
        self.stop_path.write_text(f"{reason}\n", encoding="utf-8")
        return self.stop_path

    def clear_stop(self) -> None:
        self.stop_path.unlink(missing_ok=True)
