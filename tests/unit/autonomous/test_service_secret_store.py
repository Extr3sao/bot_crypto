"""WP-TDM-015-OPS — the analyst key lives in DPAPI, not in the checkout.

Three claims, all of them about where a secret may exist:

* the key is written to ``%LOCALAPPDATA%`` as a DPAPI blob belonging to the
  current user, and the clear text never appears in the file;
* the wrapper reads it back into the *environment* (the interface
  ``provider_from_env`` already uses) without printing it;
* an unreadable store is an error, not a silent "no key" — an operator must not
  spend an afternoon wondering why every analysis says ``NOT_CONFIGURED``.

The suite runs anywhere; on a host without DPAPI the store tests skip rather
than pretend the mechanism is portable.
"""

from __future__ import annotations

import getpass
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
WINDOWS_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="the DPAPI store is Windows-only"
)


def _service() -> Any:
    spec = importlib.util.spec_from_file_location(
        "paper_lab_service_under_test", REPO / "scripts" / "paper_lab_service.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["paper_lab_service_under_test"] = module
    spec.loader.exec_module(module)
    return module


@WINDOWS_ONLY
def test_the_key_round_trips_through_dpapi_and_never_lands_in_clear_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service = _service()
    secret = "sk-test-value-that-must-not-be-readable"

    path = service.save_secret(secret, model="gpt-4o-mini")
    assert path == tmp_path / service.STORE_DIR_NAME / service.KEY_FILE_NAME
    raw = path.read_text(encoding="ascii")
    assert secret not in raw
    assert secret not in (tmp_path / service.STORE_DIR_NAME / service.META_FILE_NAME).read_text(
        encoding="utf-8"
    )
    # Only this user on this machine can read it back, and the value is intact.
    assert service.load_secret() == secret
    assert service.load_meta() == {"model": "gpt-4o-mini"}
    assert service.clear_secret() is True
    assert service.load_secret() is None
    assert service.clear_secret() is False


@WINDOWS_ONLY
def test_the_wrapper_puts_the_key_in_the_environment_without_printing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SIGNAL_ANALYST_API_KEY", raising=False)
    service = _service()
    service.save_secret("sk-test-env", model="gpt-4o-mini", base_url="https://example.invalid/v1")

    report = service.apply_to_environment()
    assert report["applied"] is True
    assert report["model"] == "gpt-4o-mini"
    import os

    assert os.environ["SIGNAL_ANALYST_API_KEY"] == "sk-test-env"
    assert os.environ["SIGNAL_ANALYST_BASE_URL"] == "https://example.invalid/v1"

    # ``--secret-status`` answers the question without the answer's value.
    assert service.main(["--secret-status"]) == 0
    printed = capsys.readouterr().out
    assert "sk-test-env" not in printed
    assert service.KEY_FILE_NAME in printed
    assert '"present": true' in printed


@WINDOWS_ONLY
def test_storing_requires_a_real_value_and_prompts_without_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service = _service()
    with pytest.raises(service.SecretStoreError):
        service.save_secret("   ")

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "sk-prompted")
    assert service.main(["--store-secret", "--model", "gpt-4o-mini"]) == 0
    out = capsys.readouterr().out
    assert "sk-prompted" not in out
    assert service.load_secret() == "sk-prompted"


@WINDOWS_ONLY
def test_a_corrupt_store_is_an_error_not_an_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service = _service()
    service.store_dir().mkdir(parents=True, exist_ok=True)
    service.key_path().write_text("not-base64-at-all!!", encoding="ascii")
    with pytest.raises(service.SecretStoreError):
        service.load_secret()


def test_the_wrapper_reads_no_other_credential() -> None:
    """A service wrapper that can read one key must not be able to read ten."""
    source = (REPO / "scripts" / "paper_lab_service.py").read_text(encoding="utf-8")
    for forbidden in (
        "BINANCE_API_KEY",
        "BINANCE_SECRET",
        "EXCHANGE_API_SECRET",
        "private_key",
        "withdraw",
    ):
        assert forbidden not in source, forbidden
    # The one key it knows about is the read-only analyst's.
    assert source.count("SIGNAL_ANALYST_API_KEY") >= 1
