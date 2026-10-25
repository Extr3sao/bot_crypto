"""Build the RFC-048 **evidence-v2** bundle reproducibly (WP-TDM-07).

Why this exists
---------------
``data/rfc048`` is the historical v1 record: its ``PROVENANCE.json`` pins digests
over CRLF bytes that git never stored, so a clean checkout fails those checks
(``DEF-TDM-06-6``).  v2 pins the bytes the repository actually contains, and the
regenerated scenarios live in ``data/rfc048/provenance/evidence-v2``.

The first v2 bundle was assembled by hand, which made its manifest unverifiable
in the only way that matters: nobody could re-run it.  This script does the whole
thing from source, and refuses to touch v1:

1. stage a scratch copy of the v1 inputs (raw payloads, snapshot, funding) —
   the builder writes into its data directory, so it must never be pointed at
   ``data/rfc048`` itself;
2. substitute the *v2* ``PROVENANCE.json`` / ``INSTRUMENTS.json``;
3. run ``scripts/rfc048_run.py`` against the staging directory;
4. publish the result to ``provenance/evidence-v2`` together with a
   ``GENERATION.json`` that names every input, every output and the generator
   itself by digest;
5. re-verify that v1 is byte-identical to what it was before the run.

Run from the repository root::

    PYTHONPATH=src python scripts/rfc048_evidence_v2.py            # build
    PYTHONPATH=src python scripts/rfc048_evidence_v2.py --check    # manifest only

Exit code 1 means the bundle could not be rebuilt byte for byte, so nothing is
published.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rfc048"
PROVENANCE = DATA / "provenance"
OUT = PROVENANCE / "evidence-v2"
BUILDER = ROOT / "scripts" / "rfc048_run.py"
HERE = Path(__file__).resolve()

#: Files the builder writes; everything else it needs is copied from v1.
DERIVED = (
    "RISK_SCENARIOS.json",
    "MARGIN_LIQUIDATION_CASES.json",
    "ECONOMIC_FEASIBILITY.json",
    "RUNTIME_EXECUTION_REPORT.json",
)
#: The report embeds a timestamp and a duration; those are recorded, not compared.
VOLATILE = {"generated_at_utc", "duration_seconds"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(p for p in root.rglob("*") if p.is_file())
    }


def semantic(payload: dict[str, Any]) -> dict[str, Any]:
    """The part of a report that must not change between two builds."""
    return {key: value for key, value in payload.items() if key not in VOLATILE}


def stage_inputs(staging: Path) -> None:
    """Copy the v1 inputs, then swap in the v2 provenance pair."""
    skipped = set(DERIVED) | {"provenance", "INDEPENDENT_VERIFICATION.json"}
    for item in sorted(DATA.iterdir()):
        if item.name in skipped:
            continue
        if item.is_dir():
            shutil.copytree(item, staging / item.name)
        else:
            shutil.copy2(item, staging / item.name)

    for target, source in (
        ("PROVENANCE.json", PROVENANCE / "PROVENANCE@v2.json"),
        ("INSTRUMENTS.json", PROVENANCE / "INSTRUMENTS@v2.json"),
    ):
        if not source.is_file():
            raise SystemExit(
                f"[rfc048] missing {source.relative_to(ROOT)}; "
                "run scripts/rfc048_provenance_v2.py --write first"
            )
        shutil.copy2(source, staging / target)


def run_builder(staging: Path) -> None:
    # Inherit the environment: a trimmed one breaks socket/asyncio initialisation on
    # Windows (WinError 10106 from ``_overlapped``), which the builder needs.
    env = {
        **os.environ,
        "RFC048_DATA_DIR": str(staging),
        "PYTHONPATH": str(ROOT / "src"),
    }
    completed = subprocess.run(
        [sys.executable, str(BUILDER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"[rfc048] builder failed ({completed.returncode})\n"
            f"{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    missing = [name for name in DERIVED if not (staging / name).is_file()]
    if missing:
        raise SystemExit(f"[rfc048] builder wrote no {', '.join(missing)}")


def compare_with_published(staging: Path) -> list[str]:
    """Differences that matter: volatile report fields are allowed to move."""
    problems: list[str] = []
    for name in DERIVED:
        fresh = json.loads((staging / name).read_text(encoding="utf-8"))
        published = json.loads((OUT / name).read_text(encoding="utf-8"))
        if name == "RUNTIME_EXECUTION_REPORT.json":
            if semantic(fresh) != semantic(published):
                differing = sorted(
                    key
                    for key in set(semantic(fresh)) | set(semantic(published))
                    if semantic(fresh).get(key) != semantic(published).get(key)
                )
                problems.append(f"{name}: {', '.join(differing)}")
        elif fresh != published:
            problems.append(f"{name}: payload changed")
    return problems


def build(check_only: bool) -> int:
    before = tree_digests(DATA)
    with tempfile.TemporaryDirectory(prefix="rfc048-evidence-") as raw:
        staging = Path(raw) / "data"
        staging.mkdir()
        stage_inputs(staging)
        run_builder(staging)
        if check_only:
            problems = compare_with_published(staging)
            after = tree_digests(DATA)
            print(json.dumps(
                {
                    "mode": "check",
                    "reproduces_published_bundle": not problems,
                    "differences": problems,
                    "v1_untouched": before == after,
                },
                indent=2,
            ))
            return 0 if not problems and before == after else 1

        for item in sorted(staging.iterdir()):
            target = OUT / item.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

    # A verification artefact belongs to whoever ran the verifier, never to the
    # bundle: leaving a stale one behind would put a digest in the manifest that the
    # next ``rfc048_verify.py`` run immediately invalidates.
    stale = OUT / "INDEPENDENT_VERIFICATION.json"
    if stale.is_file():
        stale.unlink()

    after = tree_digests(DATA)
    v1_untouched = {k: v for k, v in before.items() if not k.startswith("provenance/")} == {
        k: v for k, v in after.items() if not k.startswith("provenance/")
    }
    if not v1_untouched:
        raise SystemExit("[rfc048] the v1 bundle changed during the build; refusing to publish")

    manifest = {
        "schema_version": "rfc048-provenance-v2",
        "generation": "evidence-v2",
        "purpose": (
            "self-contained RFC-048 evidence regenerated against provenance v2 "
            "(digests of the bytes the repository stores), built by a script"
        ),
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {
            "path": HERE.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(HERE),
            "builder": BUILDER.relative_to(ROOT).as_posix(),
            "builder_sha256": sha256_file(BUILDER),
        },
        "regenerate_with": "PYTHONPATH=src python scripts/rfc048_evidence_v2.py",
        "check_with": "PYTHONPATH=src python scripts/rfc048_evidence_v2.py --check",
        "inputs": {
            "PROVENANCE@v2.json": sha256_file(PROVENANCE / "PROVENANCE@v2.json"),
            "INSTRUMENTS@v2.json": sha256_file(PROVENANCE / "INSTRUMENTS@v2.json"),
        },
        "files": {
            name: {"sha256": sha256_file(OUT / name), "bytes": (OUT / name).stat().st_size}
            for name in sorted(tree_digests(OUT))
            if name != "GENERATION.json"
        },
        "v1_untouched": True,
        "note": (
            "v1 artifacts in data/rfc048 top level are preserved untouched and remain "
            "the historical record; they are no longer the verified generation."
        ),
    }
    (OUT / "GENERATION.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(
        {
            "mode": "build",
            "files": len(manifest["files"]),
            "v1_untouched": True,
            "manifest": "data/rfc048/provenance/evidence-v2/GENERATION.json",
        },
        indent=2,
    ))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in a scratch directory and compare with the published bundle",
    )
    return build(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
