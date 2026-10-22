"""isolation_inventory — what can place an order, and what can open a socket.

The inventory is derived from the source with ``ast`` rather than from a list a human
maintains, because a list a human maintains is exactly the artefact that goes stale while
the report stays green. Each entry carries its file, its class and its line so the
verifier can re-read the same definition from the git blob of the source commit.

    python scripts/isolation_inventory.py --json reports/.../ISOLATION_INVENTORY.json
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: A method whose name starts with one of these can move money at an exchange.
ORDER_VERBS = ("create_order", "place_order", "cancel_order", "amend_order", "withdraw")
#: Modules whose import is itself a capability, not a detail.
NETWORK_MODULES = {
    "socket": "raw sockets",
    "ssl": "TLS",
    "http": "http.client",
    "urllib": "urllib.request",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "websockets": "websockets",
    "ccxt": "ccxt (venue SDK; opens a session in the constructor)",
}
#: Probe hosts: if any of them appears in the runtime, the inventory says so.
PROBE_HOSTS = ("api.binance.com", "fapi.binance.com", "api.bybit.com", "api.bitunix.com")


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _classify(path: Path) -> str:
    text = str(path.relative_to(REPO)).replace("\\", "/")
    if text.startswith("src/"):
        return "RUNTIME_REACHABLE"
    if text.startswith("scripts/"):
        return "ENTRYPOINT"
    if text.startswith("tests/"):
        return "TEST_ONLY"
    return "OTHER"


def scan() -> dict[str, Any]:
    order_routes: list[dict[str, Any]] = []
    network_capabilities: list[dict[str, Any]] = []
    hosts: list[dict[str, Any]] = []
    entrypoints: list[dict[str, Any]] = []

    for path in sorted((REPO / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        module = _module_name(path)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module.split(".")[0])
        for module_name in sorted(set(imported) & set(NETWORK_MODULES)):
            network_capabilities.append(
                {
                    "module": module,
                    "imports": module_name,
                    "capability": NETWORK_MODULES[module_name],
                    "file": str(path.relative_to(REPO)).replace("\\", "/"),
                    "authority": _classify(path),
                }
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in ast.walk(node):
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith(
                    ORDER_VERBS
                ):
                    route = f"{module}.{node.name}.{item.name}"
                    if any(row["route"] == route for row in order_routes):
                        continue
                    order_routes.append(
                        {
                            "route": route,
                            "module": module,
                            "class": node.name,
                            "method": item.name,
                            "line": item.lineno,
                            "file": str(path.relative_to(REPO)).replace("\\", "/"),
                            "authority": _classify(path),
                        }
                    )

    for path in sorted((REPO / "scripts").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "__main__" not in text and "def main" not in text:
            continue
        entrypoints.append(
            {
                "script": str(path.relative_to(REPO)).replace("\\", "/"),
                "constructs_lane": "VisionLane(" in text,
                "imports_ccxt": "ccxt" in text,
                "mentions_place_order": "place_order" in text or "create_order" in text,
            }
        )

    for path in sorted((REPO / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for host in PROBE_HOSTS:
            if host in text:
                hosts.append(
                    {
                        "host": host,
                        "file": str(path.relative_to(REPO)).replace("\\", "/"),
                        "authority": _classify(path),
                    }
                )

    return {
        "schema": "rfc005-isolation-inventory/1",
        "source_commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "counts": {
            "order_routes": len(order_routes),
            "network_capabilities": len(network_capabilities),
            "entrypoints": len(entrypoints),
        },
        "order_routes": order_routes,
        "network_capabilities": network_capabilities,
        "hosts": hosts,
        "entrypoints": entrypoints,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory order and network capability.")
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    payload = scan()
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    print(
        f"order_routes={payload['counts']['order_routes']} "
        f"network={payload['counts']['network_capabilities']} "
        f"entrypoints={payload['counts']['entrypoints']} -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
