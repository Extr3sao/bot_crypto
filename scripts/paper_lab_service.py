"""Always-on Windows service wrapper for the PAPER lab, with a DPAPI secret store.

    python scripts/paper_lab_service.py --store-secret          # asks, never echoes
    python scripts/paper_lab_service.py --secret-status
    python scripts/paper_lab_service.py --run-id paper-lab-service
    python scripts/paper_lab_service.py --clear-secret

Two operational facts this file exists to make true:

* **The AI analyst key is never a file in the repository.** It is encrypted with
  Windows DPAPI (current user, this machine) under ``%LOCALAPPDATA%``, so a copy
  of the checkout — or a git push — cannot contain it, and another account on the
  host cannot decrypt it. The key is decrypted into this process's environment at
  start-up only, which is the interface ``provider_from_env`` already reads. It is
  never printed, logged, or written back to disk in clear text.
* **A reboot continues the same evidence.** The lab is started with a stable run
  id and ``--restart``, which now also archives the previous window (D-09), so
  restarting does not overwrite the report of the window that just ended.

Nothing here can reach LIVE: the children are read-only market data plus the
PAPER broker, and no other credential is read or stored.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.wintypes as wintypes
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

STORE_DIR_NAME = "TradingAgenticPortable"
KEY_FILE_NAME = "signal_analyst.key"
META_FILE_NAME = "signal_analyst.json"
SECRET_ENV = "SIGNAL_ANALYST_API_KEY"

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretStoreError(RuntimeError):
    """The store could not be read or written, said plainly."""


class _Blob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes) -> tuple[_Blob, Any]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Encrypt/decrypt for *this* Windows user on *this* machine (DPAPI)."""
    if not sys.platform.startswith("win"):
        raise SecretStoreError("the DPAPI store is Windows-only; no other platform is claimed")
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    source, source_buffer = _blob(data)
    destination = _Blob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # Both functions take (pDataIn, description, pOptionalEntropy, pvReserved,
    # pPromptStruct, dwFlags, pDataOut); only the description is read or written.
    if not function(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(destination),
    ):
        raise SecretStoreError(f"DPAPI {'protect' if protect else 'unprotect'} failed")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)
        del source_buffer


def store_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / STORE_DIR_NAME


def key_path() -> Path:
    return store_dir() / KEY_FILE_NAME


def meta_path() -> Path:
    return store_dir() / META_FILE_NAME


def save_secret(secret: str, *, model: str | None = None, base_url: str | None = None) -> Path:
    """Encrypt and persist the key; the clear text never touches the disk."""
    if not secret.strip():
        raise SecretStoreError("refusing to store an empty key")
    directory = store_dir()
    directory.mkdir(parents=True, exist_ok=True)
    blob = _dpapi(secret.strip().encode("utf-8"), protect=True)
    target = key_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(base64.b64encode(blob).decode("ascii"), encoding="ascii")
    os.replace(tmp, target)
    meta = load_meta()
    if model is not None:
        meta["model"] = model
    if base_url is not None:
        meta["base_url"] = base_url
    if meta:
        meta_path().write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return target


def load_meta() -> dict[str, Any]:
    try:
        payload = json.loads(meta_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_secret() -> str | None:
    """The decrypted key, or ``None`` when nothing is stored.

    A store that exists but cannot be decrypted is an error, not an absence:
    silently treating a corrupt store as "no key" is how an operator spends an
    afternoon wondering why the analyst keeps saying NOT_CONFIGURED.
    """
    path = key_path()
    if not path.exists():
        return None
    try:
        blob = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    except (OSError, ValueError) as exc:
        raise SecretStoreError(f"{path}: the encrypted store is unreadable ({exc})") from exc
    return _dpapi(blob, protect=False).decode("utf-8")


def clear_secret() -> bool:
    removed = False
    for path in (key_path(), meta_path()):
        if path.exists():
            path.unlink()
            removed = True
    return removed


def apply_to_environment() -> dict[str, Any]:
    """Put the stored key (and its non-secret settings) into this process's env."""
    report: dict[str, Any] = {
        "store": str(key_path()),
        "present": False,
        "model": None,
        "base_url": None,
        "applied": False,
    }
    secret = load_secret()
    if secret is None:
        return report
    report["present"] = True
    meta = load_meta()
    report["model"] = meta.get("model")
    report["base_url"] = meta.get("base_url")
    if not os.environ.get(SECRET_ENV):
        os.environ[SECRET_ENV] = secret
        report["applied"] = True
    if meta.get("model") and not os.environ.get("SIGNAL_ANALYST_MODEL"):
        os.environ["SIGNAL_ANALYST_MODEL"] = str(meta["model"])
    if meta.get("base_url") and not os.environ.get("SIGNAL_ANALYST_BASE_URL"):
        os.environ["SIGNAL_ANALYST_BASE_URL"] = str(meta["base_url"])
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="paper-lab-service")
    parser.add_argument("--store-secret", action="store_true", help="prompt, encrypt, store")
    parser.add_argument("--secret-status", action="store_true", help="say whether a key is stored")
    parser.add_argument("--clear-secret", action="store_true", help="delete the stored key")
    parser.add_argument("--model", default=None, help="with --store-secret: model name")
    parser.add_argument("--base-url", default=None, help="with --store-secret: API base URL")
    parser.add_argument("--stop", action="store_true", help="ask the named lab to stop")
    parser.add_argument(
        "launcher_args",
        nargs=argparse.REMAINDER,
        help="everything after -- is forwarded to start_paper_lab.py",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.store_secret:
        secret = getpass.getpass("Signal analyst API key (input is hidden): ")
        save_secret(secret, model=args.model, base_url=args.base_url)
        print(f"[secret] stored (DPAPI, current user): {key_path()}")
        print("[secret] the value was not printed and is not in the repository")
        return 0
    if args.clear_secret:
        removed = clear_secret()
        print(f"[secret] {'removed' if removed else 'nothing stored'}")
        return 0
    if args.secret_status:
        report = {
            "store": str(key_path()),
            "present": key_path().exists(),
            "model": load_meta().get("model"),
            "base_url": load_meta().get("base_url"),
        }
        print(json.dumps(report, indent=2))
        return 0

    applied = apply_to_environment()
    print(
        "[service] analyst key: "
        + (
            "loaded from the DPAPI store"
            if applied["applied"]
            else "absent (analysis will be NOT_CONFIGURED)"
        )
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "paper_lab_launcher", REPO_ROOT / "scripts" / "start_paper_lab.py"
    )
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    sys.modules["paper_lab_launcher"] = launcher
    spec.loader.exec_module(launcher)

    forwards = [item for item in args.launcher_args if item != "--"]
    if args.stop:
        argv_list = ["--stop", str(REPO_ROOT / "reports" / "paper-lab" / args.run_id)]
    else:
        argv_list = [
            "--run-id",
            args.run_id,
            "--restart",
            "--provider",
            "ccxt",
            "--assets",
            "BTC,ETH,SOL",
            "--symbols",
            "BTCUSDT,ETHUSDT,SOLUSDT",
            "--timeframe",
            "5m",
            "--paper-cadence",
            "bar-close",
            "--duration-hours",
            "0",
            *forwards,
        ]
    # The launcher owns its own CLI: this wrapper supplies the argv rather than
    # re-implementing it, so a new launcher option keeps working here.
    sys.argv = ["start_paper_lab.py", *argv_list]
    return int(launcher.main())


if __name__ == "__main__":
    raise SystemExit(main())
