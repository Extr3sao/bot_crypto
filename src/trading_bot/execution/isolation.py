"""PAPER/OFFLINE operational isolation: deny by default, and prove it from outside.

What this module is for
-----------------------

The runtime that produces paper evidence must not be able to reach an exchange. The
existing gates answer a different question — ``--confirm-live`` plus ``runtime.mode ==
live`` plus the live trading checklist decide whether an operator *intends* to trade.
They do not stop a paper process from importing an adapter, constructing a venue client
and opening a socket, and the RFC003 incident (``ccxt.binance`` opening a session in its
constructor) is exactly that failure.

So this module adds one capability and two refusals:

* a **policy** that is strict for every mode except ``live``: no external network, no
  socket at all unless loopback was explicitly permitted, no order route;
* a **process-wide audit hook** (``sys.addaudithook``) that denies the event *before*
  the syscall happens and records the attempt — a method spy would miss a constructor;
* an **order gate** placed at the methods that actually talk to a venue, which refuses
  in a paper process even if an adapter is instantiated directly.

What it does not claim
----------------------

A hook inside one Python process is not an operating-system barrier. A child process
started without the hook, or a native extension that writes to a socket without raising
an audit event, is outside what this module can see. The laboratory declares that
residual as ``OS_SANDBOX = NOT_AVAILABLE`` and never turns it into a PASS; a false sense
of containment is worse than a named gap.

Install once, at the entry point, before constructing anything::

    from trading_bot.execution import isolation
    isolation.install_for_runtime()          # mode from TRADING_BOT_MODE, else paper
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CODE_EXTERNAL_NETWORK",
    "CODE_ORDER_ROUTE",
    "CODE_POLICY_REDEFINED",
    "Guard",
    "IsolationBlocked",
    "IsolationPolicy",
    "NetworkBlocked",
    "OrderRouteRefused",
    "PolicyRedefined",
    "active",
    "assert_order_allowed",
    "decide_network",
    "install",
    "install_for_runtime",
    "is_installed",
    "mode_from_environment",
    "policy_for_mode",
]

CODE_EXTERNAL_NETWORK: Final[str] = "ISO_EXTERNAL_NETWORK"
CODE_ORDER_ROUTE: Final[str] = "ISO_ORDER_ROUTE"
CODE_POLICY_REDEFINED: Final[str] = "ISO_POLICY_REDEFINED"

MODE_ENV: Final[str] = "TRADING_BOT_MODE"

#: Audit events that can leave the process. ``socket.bind`` and ``socket.listen`` are
#: absent on purpose: serving loopback is not an outbound connection.
NETWORK_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.sendto",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
        "socket.getnameinfo",
        "urllib.Request",
        "http.client.connect",
        "ftplib.connect",
        "smtplib.connect",
        "imaplib.open",
        "poplib.connect",
        "telnetlib.Telnet.open",
        "ssl.wrap_socket",
    }
)

#: Addresses that never leave the host. ``localhost`` is included because resolving it
#: is a local operation; the resolved address is then checked again on connect.
LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "::1", "localhost", ""})


class IsolationBlocked(RuntimeError):
    """Base refusal. Carries a stable ``code`` so evidence can name the cause."""

    code = "ISO_BLOCKED"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


class OrderRouteRefused(IsolationBlocked):
    """An order-capable method was called in a process that may not send orders."""

    code = CODE_ORDER_ROUTE


class NetworkBlocked(IsolationBlocked):
    """An outbound network event was attempted under a deny policy."""

    code = CODE_EXTERNAL_NETWORK


class PolicyRedefined(IsolationBlocked):
    """The guard was already installed and someone tried to weaken it."""

    code = CODE_POLICY_REDEFINED


@dataclass(frozen=True, slots=True)
class IsolationPolicy:
    """What this process is allowed to do. Frozen: a policy is not edited at runtime."""

    mode: str
    external_network: bool = False
    loopback_network: bool = False
    order_routes: bool = False
    source: str = "policy_for_mode"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "external_network": self.external_network,
            "loopback_network": self.loopback_network,
            "order_routes": self.order_routes,
            "source": self.source,
        }


@dataclass(slots=True)
class Guard:
    """A policy plus the record of what was attempted under it."""

    policy: IsolationPolicy
    log_path: Path | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    denied: int = 0
    allowed_loopback: int = 0

    def record(self, event: str, args: tuple[object, ...], decision: str, reason: str) -> None:
        row = {
            "event": event,
            "host": _host_of(event, args),
            "args": repr(args)[:200],
            "decision": decision,
            "reason": reason,
            "pid": os.getpid(),
        }
        self.attempts.append(row)
        if decision == "DENY":
            self.denied += 1
        elif decision == "ALLOW_LOOPBACK":
            self.allowed_loopback += 1
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=True) + "\n")
            except OSError:
                #: Losing the log must not open the door; the denial already happened.
                pass

    def summary(self) -> dict[str, Any]:
        return {
            "policy": self.policy.as_dict(),
            "attempts": len(self.attempts),
            "denied": self.denied,
            "allowed_loopback": self.allowed_loopback,
            "log_path": None if self.log_path is None else str(self.log_path),
        }


def _host_of(event: str, args: tuple[object, ...]) -> str | None:
    """The host an audited event is aimed at, when the event carries one."""
    if not args:
        return None
    if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.getnameinfo"}:
        host = args[0]
        return host if isinstance(host, str) else None
    if event in {"http.client.connect"}:
        host = args[0]
        return host if isinstance(host, str) else None
    if event == "urllib.Request":
        url = args[0]
        return url if isinstance(url, str) else None
    candidate = args[-1]
    if isinstance(candidate, tuple) and candidate:
        host = candidate[0]
        return host if isinstance(host, str) else None
    if isinstance(candidate, str):
        return candidate
    return None


def mode_from_environment(environ: dict[str, str] | None = None) -> str | None:
    """The declared runtime mode, if this process declared one."""
    source = os.environ if environ is None else environ
    value = source.get(MODE_ENV, "").strip().lower()
    return value or None


def policy_for_mode(mode: str, *, source: str = "policy_for_mode") -> IsolationPolicy:
    """Strict unless the mode is ``live``.

    ``live`` is not made safer here on purpose: the live checklist and
    ``--confirm-live`` own that decision, and duplicating it in a second place is how two
    sources of truth drift. This module only refuses what is not live.
    """
    normalised = mode.strip().lower() or "paper"
    if normalised == "live":
        return IsolationPolicy(
            mode="live",
            external_network=True,
            loopback_network=True,
            order_routes=True,
            source=source,
        )
    return IsolationPolicy(
        mode=normalised,
        external_network=False,
        loopback_network=False,
        order_routes=False,
        source=source,
    )


_STATE: Guard | None = None
_HOOK_INSTALLED = False


def decide_network(
    event: str, args: tuple[object, ...], policy: IsolationPolicy
) -> tuple[str, str]:
    """Pure decision for one audit event; the hook is a thin wrapper around this.

    Kept separate so the rule can be tested and re-read without installing anything.
    """
    if event not in NETWORK_EVENTS:
        return "IGNORE", "not a network event"
    host = _host_of(event, args)
    if policy.external_network:
        return "ALLOW", "policy permits external network"
    if policy.loopback_network:
        if host is None or host in LOOPBACK_HOSTS:
            return "ALLOW_LOOPBACK", f"loopback permitted ({host!r})"
        if isinstance(host, str) and host.startswith("/"):
            return "ALLOW_LOOPBACK", "unix socket"
    return "DENY", f"policy {policy.mode!r} denies {event}"


def install(policy: IsolationPolicy, *, log_path: Path | str | None = None) -> Guard:
    """Install the guard. Irreversible: a second, weaker policy is refused."""
    global _STATE, _HOOK_INSTALLED
    if _STATE is not None:
        if _STATE.policy != policy:
            raise PolicyRedefined(
                f"already installed as {_STATE.policy.as_dict()}, refused {policy.as_dict()}"
            )
        return _STATE
    if _HOOK_INSTALLED:  # pragma: no cover - only reachable after a manual reset
        raise PolicyRedefined("a hook is already installed but the state was cleared")
    guard = Guard(policy=policy, log_path=None if log_path is None else Path(log_path))

    def hook(event: str, args: tuple[object, ...]) -> None:
        decision, reason = decide_network(event, args, guard.policy)
        if decision == "IGNORE":
            return
        guard.record(event, args, decision, reason)
        if decision == "DENY":
            raise NetworkBlocked(f"{event} to {_host_of(event, args)!r}: {reason}")

    sys.addaudithook(hook)
    _HOOK_INSTALLED = True
    _STATE = guard
    os.environ.setdefault(MODE_ENV, policy.mode)
    return guard


def install_for_runtime(mode: str | None = None, *, log_path: Path | str | None = None) -> Guard:
    """Install the policy the process declared, defaulting to paper."""
    declared = mode or mode_from_environment() or "paper"
    return install(policy_for_mode(declared), log_path=log_path)


def active() -> Guard | None:
    return _STATE


def is_installed() -> bool:
    return _STATE is not None


def assert_order_allowed(route: str, *, detail: str | None = None) -> None:
    """Refuse an order-capable call unless this process may send orders.

    Two independent signals, whichever is stricter wins:

    * an installed guard that denies order routes (the paper runtime always does);
    * a declared runtime mode in the environment that is not ``live`` (so a child
      process that inherited the mode refuses even without the hook).

    A process with neither signal keeps the previous behaviour, because the existing
    live gate owns that decision and the connector tests exercise it without a runtime.
    """
    if _STATE is not None and not _STATE.policy.order_routes:
        raise OrderRouteRefused(
            f"{route} refused: policy {_STATE.policy.as_dict()}"
            + (f" ({detail})" if detail else "")
        )
    declared = mode_from_environment()
    if declared is not None and declared != "live":
        raise OrderRouteRefused(
            f"{route} refused: {MODE_ENV}={declared!r} cannot send orders"
            + (f" ({detail})" if detail else "")
        )
