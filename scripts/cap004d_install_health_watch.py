"""One-shot: register the CAP-004D health watch in the Windows Task Scheduler.

Idempotent. The campaign ops ledger is NOT touched (register_in_ledger=False);
the install receipt lives in reports/cap004d/HEALTH_WATCH_INSTALL.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import cap004_supervisor as sup  # noqa: E402

TASK_NAME = "TradingAgentic-CAP004D-HealthWatch"
arguments = f'"{(REPO / "scripts" / "cap004d_health_check.py").as_posix()}"'

result = sup.install_scheduler(
    task_name=TASK_NAME,
    arguments=arguments,
    interval_minutes=15,
    register_in_ledger=False,
)
task = result.get("task") or {}
print("status  :", result.get("status"))
print("enabled :", task.get("enabled"), "| state:", task.get("state"))
print("command :", task.get("command"))
print("args    :", task.get("arguments"))
print("next run:", task.get("next_run_time"))

receipt = {
    "action": "INSTALL_HEALTH_WATCH",
    "task_name": TASK_NAME,
    "interval_minutes": 15,
    "status": result.get("status"),
    "task": task,
}
receipt_path = REPO / "reports" / "cap004d" / "HEALTH_WATCH_INSTALL.json"
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n", "utf-8")
print("receipt :", receipt_path)
