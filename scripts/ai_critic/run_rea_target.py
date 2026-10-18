"""run_rea_target — observe the upstream-rendered HTML page with the installed REA CLI.

The page is served read-only from loopback and opened in a disposable Chrome profile.
REA (``npx rea-agents@6.4.0``) lists the CDP targets, passively inspects the page and
captures one screenshot, each with its native Evidence envelope. Every command's
stdout/stderr/exit code is preserved verbatim.

What this proves: the rendered page exists, its DOM sections are the ones the pinned
renderer wrote, and a screenshot of that page was taken through REA. What it cannot
prove: that the Python debate reasoned correctly. That is the harness's claim, and it is
labelled differently on purpose.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REA_PACKAGE = "rea-agents@6.4.0"
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def wait_http(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.35)
    return False


def find_evidence_id(envelope: Any) -> str | None:
    if isinstance(envelope, dict):
        for key, value in envelope.items():
            if key in {"evidence_id", "evidenceId"} and isinstance(value, str):
                return value
        for value in envelope.values():
            found = find_evidence_id(value)
            if found:
                return found
    elif isinstance(envelope, list):
        for value in envelope:
            found = find_evidence_id(value)
            if found:
                return found
    return None


def iter_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_dicts(value)


def find_screenshot_bytes(envelope: Any) -> bytes | None:
    """REA returns either a base64 PNG field or a path to the saved artifact."""
    if isinstance(envelope, dict):
        for key, value in envelope.items():
            if isinstance(value, str):
                lowered = key.lower()
                if "base64" in lowered and value.startswith("iVBOR"):
                    return base64.b64decode(value)
                if lowered in {"path", "artifactpath", "artifact_path", "file", "outputpath"}:
                    candidate = Path(value)
                    if candidate.exists() and candidate.suffix.lower() == ".png":
                        return candidate.read_bytes()
        for value in envelope.values():
            found = find_screenshot_bytes(value)
            if found:
                return found
    elif isinstance(envelope, list):
        for value in envelope:
            found = find_screenshot_bytes(value)
            if found:
                return found
    return None


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("http: " + (fmt % args) + "\n")


def run_rea(args: list[str], out_dir: Path, label: str, timeout: int = 180) -> dict[str, Any]:
    started = now()
    t0 = time.time()
    command = ["npx", "-y", REA_PACKAGE, *args]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                          shell=(os.name == "nt"), check=False)
    duration = round(time.time() - t0, 2)
    (out_dir / f"{label}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (out_dir / f"{label}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    envelope: Any = None
    parse_error = None
    try:
        envelope = json.loads(proc.stdout)
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"
    row = {
        "operation": label,
        "command": " ".join(f'"{c}"' if " " in c else c for c in command),
        "started_at": started,
        "ended_at": now(),
        "duration_s": duration,
        "exit_code": proc.returncode,
        "stdout_sha256": sha256_bytes(proc.stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(proc.stderr.encode("utf-8")),
        "stdout_path": f"{label}.stdout.txt",
        "stderr_path": f"{label}.stderr.txt",
        "json_parsed": envelope is not None,
        "parse_error": parse_error,
        "evidence_id": find_evidence_id(envelope),
        "not_executed": "NOT_EXECUTED" in proc.stdout or "NOT_EXECUTED" in proc.stderr,
    }
    return {"row": row, "envelope": envelope, "proc": proc}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--port", type=int, default=9184)
    parser.add_argument("--cdp-port", type=int, default=9222)
    args = parser.parse_args()

    html = Path(args.html).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    document = html.name
    origin = f"http://127.0.0.1:{args.port}"
    url = f"{origin}/{document}"
    cdp = f"http://127.0.0.1:{args.cdp_port}"

    for port in (args.port, args.cdp_port):
        if not port_free(port):
            print(json.dumps({"status": "BLOCKED_PORT_IN_USE", "port": port}))
            return 4

    handler = lambda *a, **kw: QuietHandler(*a, directory=str(html.parent), **kw)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if not wait_http(url, 15):
        server.shutdown()
        print(json.dumps({"status": "BLOCKED_LOCAL_SERVER"}))
        return 4
    served_sha = sha256_bytes(urllib.request.urlopen(url, timeout=5).read())

    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)
    if chrome is None:
        server.shutdown()
        print(json.dumps({"status": "BLOCKED_NO_BROWSER"}))
        return 4

    profile = Path(tempfile.mkdtemp(prefix="tap004-chrome-"))
    chrome_proc = None
    log_path = out / "chrome.stderr.log"
    log_handle = None
    try:
        log_handle = log_path.open("w", encoding="utf-8")
        chrome_proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--remote-debugging-port={args.cdp_port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-extensions",
                "--hide-scrollbars",
                "--window-size=1280,2000",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=log_handle,
        )
        if not wait_http(f"{cdp}/json/version", 30):
            print(json.dumps({"status": "BLOCKED_CDP_NOT_READY"}))
            return 4

        log_path_writer = out / "REA_OPERATION_LOG.jsonl"
        log_path_writer.write_text("", encoding="utf-8")

        def append(row: dict[str, Any]) -> None:
            with log_path_writer.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

        rows: list[dict[str, Any]] = []
        version = run_rea(["--version"], out, "rea_version")
        append(version["row"])
        version_text = version["proc"].stdout.strip()
        rows.append(version["row"])

        doctor = run_rea(["doctor", "--format", "json"], out, "rea_doctor")
        append(doctor["row"])
        rows.append(doctor["row"])

        targets = run_rea(
            ["list-browser-targets", cdp, "--allowed-origins", origin, "--format", "json"],
            out, "list_browser_targets",
        )
        append(targets["row"])
        rows.append(targets["row"])

        target_id = None
        candidates = [
            item for item in iter_dicts(targets["envelope"])
            if any(key in item for key in ("targetId", "target_id", "id"))
            and any(key in item for key in ("url", "pageUrl"))
        ]
        page_candidates = [c for c in candidates if document in str(c.get("url") or "")]
        chosen = page_candidates[0] if page_candidates else (candidates[0] if candidates else None)
        if isinstance(chosen, dict):
            target_id = chosen.get("targetId") or chosen.get("target_id") or chosen.get("id")

        inspect_row = {"operation": "inspect_web_page", "not_executed": True,
                       "detail": "no target id discovered", "exit_code": None}
        shot_row = {"operation": "capture_web_screenshot", "not_executed": True,
                    "detail": "no target id discovered", "exit_code": None}
        inspect_env = None
        shot_env = None
        if isinstance(target_id, str) and target_id:
            inspected = run_rea(
                ["inspect-web-page", cdp, target_id, "--allowed-origins", origin,
                 "--include-accessibility-text", "--format", "json"],
                out, "inspect_web_page",
            )
            append(inspected["row"])
            rows.append(inspected["row"])
            inspect_row, inspect_env = inspected["row"], inspected["envelope"]

            shot = run_rea(
                ["capture-web-screenshot", cdp, target_id, "--allowed-origins", origin,
                 "--format", "json"],
                out, "capture_web_screenshot",
            )
            append(shot["row"])
            rows.append(shot["row"])
            shot_row, shot_env = shot["row"], shot["envelope"]
            png = find_screenshot_bytes(shot_env)
            if png:
                png_path = out / "rea_complete_report.png"
                png_path.write_bytes(png)
                shot_row["screenshot_path"] = png_path.name
                shot_row["screenshot_sha256"] = sha256_bytes(png)
                shot_row["screenshot_bytes"] = len(png)

        # The doctor's native-engine checks (Ghidra/Hopper) are unrelated to a web page;
        # its exit code is recorded, not used to declare the web target unobservable.
        targets_ok = (targets["row"]["exit_code"] == 0
                      and not targets["row"]["not_executed"]
                      and bool(targets["row"].get("evidence_id")))
        executed = targets_ok and bool(target_id)
        inspected_ok = (inspect_row.get("exit_code") == 0
                        and not inspect_row.get("not_executed")
                        and bool(inspect_row.get("evidence_id")))
        screenshot_ok = (shot_row.get("exit_code") == 0
                         and bool(shot_row.get("screenshot_sha256"))
                         and bool(shot_row.get("evidence_id")))

        inspect_facts: dict[str, Any] = {}
        if isinstance(inspect_env, dict):
            normalized = inspect_env.get("normalized_result") or {}
            dom = normalized.get("dom") or {}
            accessibility = normalized.get("accessibility") or {}
            headings = [
                node.get("name") for node in accessibility.get("nodes", [])
                if node.get("role") == "heading" and node.get("name")
            ]
            required_headings = ["Bull Researcher", "Bear Researcher", "Research Manager"]
            inspect_facts = {
                "title": (normalized.get("target") or {}).get("title"),
                "dom_total_nodes": dom.get("total_nodes"),
                "scripts_total": (normalized.get("scripts") or {}).get("total"),
                "resources_total": len(normalized.get("resources") or []),
                "network_requests_total": len((normalized.get("network") or {}).get("requests") or []),
                "accessibility_total_nodes": accessibility.get("total_nodes"),
                "headings": headings,
                "required_headings": required_headings,
                "required_headings_present": [h for h in required_headings if h in headings],
                "required_headings_missing": [h for h in required_headings if h not in headings],
            }
        screenshot_facts: dict[str, Any] = {}
        if isinstance(shot_env, dict):
            normalized = shot_env.get("normalized_result") or {}
            artifact = normalized.get("artifact") or {}
            screenshot_facts = {
                "viewport": normalized.get("viewport"),
                "artifact_sha256": artifact.get("sha256"),
                "artifact_bytes": artifact.get("bytes"),
                "artifact_media_type": artifact.get("media_type"),
                "artifact_sha256_matches_saved": artifact.get("sha256") == shot_row.get("screenshot_sha256"),
            }
        headings_ok = not inspect_facts.get("required_headings_missing", ["not inspected"])
        no_javascript_ok = inspect_facts.get("scripts_total") == 0

        evidence = {
            "schema_version": "TAP004_REA_TARGET_EVIDENCE_V1",
            "target_id": "T-TA-CRITIC",
            "subject_url": url,
            "html_path": document,
            "html_sha256": sha256_file(html),
            "html_served_sha256": served_sha,
            "html_sha256_matches_served": sha256_file(html) == served_sha,
            "cdp_endpoint": cdp,
            "browser_target_id": target_id,
            "rea_package": REA_PACKAGE,
            "rea_version_stdout": version_text,
            "operations": rows,
            "rea_executed": executed,
            "inspect_executed": inspected_ok,
            "screenshot_executed": screenshot_ok,
            "doctor_exit_code": doctor["row"]["exit_code"],
            "doctor_healthy": (doctor["envelope"] or {}).get("healthy") if isinstance(doctor["envelope"], dict) else None,
            "doctor_note": "native analysis engines (Ghidra/Hopper) missing; unrelated to web observation",
            "inspect_facts": inspect_facts,
            "screenshot_facts": screenshot_facts,
            "headings_present_in_rendered_dom": headings_ok and inspected_ok,
            "javascript_observed": None if not inspect_facts else not no_javascript_ok,
            "visual_observation_only": True,
            "reasoning_audited_by_rea": False,
            "javascript_surface_present": False,
            "inspect_envelope_sha256": sha256_bytes(json.dumps(inspect_env, sort_keys=True).encode()),
            "screenshot_envelope_sha256": sha256_bytes(json.dumps(shot_env, sort_keys=True).encode()),
            "generated_at": now(),
        }
        if not executed:
            evidence["status"] = "BLOCKED_REA_TARGET"
        elif not (inspected_ok and screenshot_ok):
            evidence["status"] = "REA_PARTIAL"
        elif not (headings_ok and no_javascript_ok and screenshot_facts.get("artifact_sha256_matches_saved")):
            evidence["status"] = "REA_OBSERVED_MISMATCH"
        else:
            evidence["status"] = "REA_UI_OBSERVED"

        (out / "REA_TARGET_EVIDENCE.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (out / "list_browser_targets.envelope.json").write_text(
            json.dumps(targets["envelope"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if inspect_env is not None:
            (out / "inspect_web_page.envelope.json").write_text(
                json.dumps(inspect_env, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if shot_env is not None:
            (out / "capture_web_screenshot.envelope.json").write_text(
                json.dumps(shot_env, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps({
            "status": evidence["status"],
            "target_id": target_id,
            "html_sha256": evidence["html_sha256"],
            "screenshot_sha256": shot_row.get("screenshot_sha256"),
            "evidence_ids": [r.get("evidence_id") for r in rows],
        }, indent=2))
        return 0 if executed else 5
    finally:
        if chrome_proc is not None:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()
        server.shutdown()
        server.server_close()
        shutil.rmtree(profile, ignore_errors=True)
        if log_handle is not None and not log_handle.closed:
            log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
