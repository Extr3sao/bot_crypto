#!/usr/bin/env python
"""WP-EDGE-08A — render the pre-registration from the code that will obey it.

The registration is the contract: the parameters, the windows, the criteria, the multiplicity and
what each verdict means. Written by hand in two places it would drift, so it is written in
**one** place — ``src/trading_bot/research/edge08/registration.py`` and ``…/books.py`` — and this
script renders both artefacts from it:

* ``reports/edge-recovery/WP-EDGE-08/PREREGISTRATION.json`` — what a runner and a verifier read;
* ``reports/edge-recovery/WP-EDGE-08/PREREGISTRATION.md`` — what a human reads.

``--check`` re-renders and fails if the committed artefacts differ, which is how the verifier
proves the parameters under test are the registered ones: a parameter moved in code without a
re-render changes the JSON, and a parameter moved in the JSON fails the per-book hash check.

The registration timestamp is preserved from the committed file when one exists, so re-running this
script is idempotent and the commit order stays legible in ``git log``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge08.analysis import (  # noqa: E402
    BOOTSTRAP_BLOCK,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
)
from trading_bot.research.edge08.books import (  # noqa: E402
    CURRENT_ARMS,
    DECLARED_PARAMS,
    PROPOSED_ARMS,
    params_hash,
)
from trading_bot.research.edge08.registration import (  # noqa: E402
    COVERAGE_FLOOR_BARS,
    CRITERIA,
    EXISTING_CORPORA,
    FREQUENCY_TARGETS,
    GROSS_SCREEN,
    HOLDOUT_SYMBOLS,
    HOLDOUT_UNIVERSE,
    KNOWN_UNIVERSE,
    MIN_TRADES,
    MULTIPLICITY,
    PREREGISTRATION,
    SCHEMA_VERSION,
    VERDICTS,
    WINDOWS,
    WP,
)

JSON_PATH = PREREGISTRATION
MD_PATH = WP / "PREREGISTRATION.md"
UNIVERSE_MANIFEST = REPO_ROOT / "data" / "edge08" / "universe-1h" / "_FETCH_MANIFEST.json"


def stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build() -> dict[str, Any]:
    registered = (
        json.loads(JSON_PATH.read_text(encoding="utf-8"))["registered_utc"]
        if JSON_PATH.is_file()
        else stamp()
    )
    books: dict[str, Any] = {}
    for arm, scope in PROPOSED_ARMS.items():
        params = dict(DECLARED_PARAMS[arm])
        books[arm] = {
            "track": scope["track"],
            "timeframe": scope["timeframe"],
            "split": scope["split"],
            "horizon_minutes": scope["horizon_minutes"],
            "params": params,
            "params_hash": params_hash(params),
            "answers": scope["answers"],
        }
    current = {
        arm: {
            "track": "CURRENT",
            "source": scope["source"],
            "timeframe": scope["timeframe"],
            "horizon_minutes": scope["horizon_minutes"],
            "already": scope["already"],
        }
        for arm, scope in CURRENT_ARMS.items()
    }
    manifest = (
        json.loads(UNIVERSE_MANIFEST.read_text(encoding="utf-8"))
        if UNIVERSE_MANIFEST.is_file()
        else {}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-08",
        "rfc": "RFC-EDGE-008",
        "title": "Alpha on an unread cross-section, with ACTIVE and QUALITY kept apart",
        "registered_utc": registered,
        "registered_before_reading": (
            "this file is committed before any bar of the cross-section is aggregated or "
            "measured; the raw shards are fetched from public Binance REST, and a download is not "
            "a reading — no figure of this universe existed anywhere when this file was written"
        ),
        "authority": (
            "RFC-EDGE-008 continues the direction WP-EDGE-07's measured cost barrier pointed at: "
            "hourly books need to capture 58-86 % of the open-to-open move to pay a 23.79 bps "
            "round trip (closed by arithmetic), a daily clock needs 11-16 % (a strategy problem)."
        ),
        "universe": {
            "cross_section_symbols": list(HOLDOUT_SYMBOLS),
            "cross_section": list(HOLDOUT_UNIVERSE),
            "known_universe": list(KNOWN_UNIVERSE),
            "corpus_directory": "data/edge08/universe-1h",
            "corpus_digest": manifest.get("corpus_digest"),
            "corpora_that_must_not_hold_these_symbols": list(EXISTING_CORPORA),
            "source": manifest.get("source"),
            "claim": (
                "no committed artefact of this repository has been measured on these symbols: "
                "their history, and the whole of it, is the evidence this work package reads once"
            ),
        },
        "windows": WINDOWS,
        "coverage_floor_bars_per_asset": COVERAGE_FLOOR_BARS,
        "tracks": {
            "QUALITY": (
                "a daily clock, holds of days to weeks, few trades with a large objective each; "
                "screened on gross expectancy and on a frequency floor, never on frequency alone"
            ),
            "ACTIVE": (
                "a one-hour entry clock with multi-day holds, aiming at three trades a day across "
                "the universe; net expectancy comes before frequency and nothing is forced"
            ),
            "CURRENT": (
                "books this project already registered and measured, carried as the baseline; they "
                "change no verdict"
            ),
        },
        "books": books,
        "current_arms": current,
        "multiplicity": MULTIPLICITY,
        "costs": {
            "model": "COST_MODEL_V3",
            "venue": "BINANCE_SPOT_STANDARD_TAKER (VIP0 taker)",
            "scenarios": ["BASE", "2X_FEES", "ADVERSE"],
            "intent_usdt": 1000.0,
            "evaluated_at": "the arm's own declared horizon_minutes",
            "note": (
                "the plane is a venue-level model: it does not carry a per-symbol spread or book "
                "depth, so the cross-section's thinner names are covered by the ADVERSE scenario "
                "rather than by a claim the data cannot support"
            ),
        },
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "block_trades": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
            "why_blocks": (
                "trades inside a window are not independent; the serial-dependence reading states "
                "that rather than assuming it away"
            ),
        },
        "min_trades": MIN_TRADES,
        "criteria": CRITERIA,
        "gross_screen": GROSS_SCREEN,
        "frequency_targets_per_day": FREQUENCY_TARGETS,
        "verdicts": VERDICTS,
        "consequences_fixed_in_advance": [
            "a book that fails the gross screen (C0) is not read on the cross-section at all: its "
            "holdout rows are absent, not zero",
            "a REJECT is reported with its numbers and the family is not tuned and re-run on the "
            "same window",
            "an INSUFFICIENT_EVIDENCE is reported as no result, never as a pass",
            "no parameter, stop, target, filter or cooldown is changed after seeing a reading",
            "nothing here promotes, sizes or executes anything: promotion stays NONE and "
            "order_sent stays false for every arm",
        ],
        "what_this_cannot_say": [
            "the cross-section is six symbols: a transfer test across six names is evidence about "
            "those names, not a proof that a book generalises to every market",
            "the cost plane is venue-level; a per-symbol spread is not modelled and the ADVERSE "
            "scenario is the only sensitivity that speaks to it",
            "the decisive window's sample size is what the book's own frequency makes it; a book "
            "that trades twice a year cannot be powered by 1.8 years of six symbols",
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08 / RFC-EDGE-008 — pre-registration, written before the cross-section is read",
        "",
        f"*Registered at `{payload['registered_utc']}` (`{payload['schema_version']}`).* "
        f"{payload['registered_before_reading']}",
        "",
        "## 1. Why this work package exists",
        "",
        payload["authority"],
        "",
        "Every time-based resource of the BTC/ETH/SOL universe has been read: the `trend` OOS "
        "window was consulted by WP-EDGE-01 and WP-EDGE-02, and the `NEW_HOLDOUT` window WP-EDGE-07 "
        "created was read once and spent. What is still unread is the **symbol dimension**:",
        "",
        "| | |",
        "| --- | --- |",
        f"| Cross-section | {', '.join(payload['universe']['cross_section_symbols'])} |",
        f"| Known universe (screening ground) | {', '.join(payload['universe']['known_universe'])} |",
        f"| Corpus | `{payload['universe']['corpus_directory']}` "
        f"(1h, from `{payload['universe']['source']}`) |",
        f"| Corpus digest | `{(payload['universe']['corpus_digest'] or '')[:16]}…` |",
        f"| Claim | {payload['universe']['claim']} |",
        "",
        "A symbol with a shard in one of these corpora is not a holdout: "
        + ", ".join(
            f"`{path}`" for path in payload["universe"]["corpora_that_must_not_hold_these_symbols"]
        )
        + ". The fetch refuses such a symbol and the verifier re-checks the claim from the manifest.",
        "",
        "## 2. The two tracks, kept apart",
        "",
        "| Track | What it is |",
        "| --- | --- |",
    ]
    for track, description in payload["tracks"].items():
        lines.append(f"| **{track}** | {description} |")
    lines += [
        "",
        "## 3. The registered books",
        "",
        "| Arm | Track | Clock | Horizon (min) | Params hash | What it answers |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for arm, book in payload["books"].items():
        lines.append(
            f"| `{arm}` | {book['track']} | {book['timeframe']} | {book['horizon_minutes']:.0f} | "
            f"`{book['params_hash'][:16]}…` | {book['answers']} |"
        )
    lines += [
        "",
        "| Arm | Track | Clock | Already says |",
        "| --- | --- | --- | --- |",
    ]
    for arm, book in payload["current_arms"].items():
        lines.append(f"| `{arm}` | {book['track']} | {book['timeframe']} | {book['already']} |")
    lines += [
        "",
        "### Parameters, byte for byte",
        "",
    ]
    for arm, book in payload["books"].items():
        params = " ".join(f"{key}={value}" for key, value in sorted(book["params"].items()))
        lines.append(f"- `{arm}` — {params}")
    lines += [
        "",
        "## 4. Windows, costs and the readings a verdict uses",
        "",
        "| Window | From | To |",
        "| --- | --- | --- |",
    ]
    for name, window in payload["windows"].items():
        lines.append(
            f"| `{name}` | {datetime.fromtimestamp(window['start'] / 1000, tz=UTC):%Y-%m-%d} | "
            f"{datetime.fromtimestamp(window['end'] / 1000, tz=UTC):%Y-%m-%d} |"
        )
    lines += [
        "",
        "The decisive window is `OOS`. Coverage floor per asset on the decisive window: "
        + ", ".join(
            f"`{tf}` ≥ {floor}" for tf, floor in payload["coverage_floor_bars_per_asset"].items()
        )
        + ".",
        "",
        f"Costs: `{payload['costs']['model']}` at {payload['costs']['venue']}, scenarios "
        f"{', '.join(payload['costs']['scenarios'])}, a {payload['costs']['intent_usdt']:.0f} USDT "
        f"intent, evaluated at {payload['costs']['evaluated_at']}. {payload['costs']['note']}",
        "",
        f"Bootstrap: {payload['bootstrap']['resamples']} resamples of "
        f"{payload['bootstrap']['block_trades']}-trade blocks, seed {payload['bootstrap']['seed']} — "
        f"{payload['bootstrap']['why_blocks']}.",
        "",
        "## 5. Criteria, and what each outcome means",
        "",
        f"All of these must hold on the decisive window at `BASE` unless the statement says "
        f"otherwise. Minimum sample: **{payload['min_trades']} trades**.",
        "",
        "| # | Criterion | Decisive | Applies to |",
        "| --- | --- | --- | --- |",
    ]
    for code, criterion in payload["criteria"].items():
        lines.append(
            f"| {code} | {criterion['statement']} | {criterion['decisive']} | "
            f"{', '.join(criterion['tracks'])} |"
        )
    lines += [
        "",
        f"**Gross screen (C0).** {payload['gross_screen']['statement']} — "
        f"{payload['gross_screen']['consequence']}",
        "",
        "**Frequency targets per day across the universe.** "
        + ", ".join(
            f"`{track}` ≥ {target}"
            for track, target in payload["frequency_targets_per_day"].items()
        )
        + ".",
        "",
        "| Verdict | Means |",
        "| --- | --- |",
    ]
    for verdict, meaning in payload["verdicts"].items():
        lines.append(f"| `{verdict}` | {meaning} |")
    lines += [
        "",
        "## 6. Multiplicity",
        "",
        f"{payload['multiplicity']['proposed']} proposed books plus "
        f"{payload['multiplicity']['current_comparison']} frozen comparison books: "
        f"{payload['multiplicity']['total']} arms, every one reported. "
        f"{payload['multiplicity']['note']}.",
        "",
        "## 7. Consequences, fixed in advance",
        "",
    ]
    for consequence in payload["consequences_fixed_in_advance"]:
        lines.append(f"- {consequence}")
    lines += [
        "",
        "## 8. What this cannot say",
        "",
    ]
    for limit in payload["what_this_cannot_say"]:
        lines.append(f"- {limit}")
    lines.append("")
    return "\n".join(lines)


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the artefacts differ")
    options = parser.parse_args(argv)

    payload = build()
    json_text = render_json(payload)
    md_text = render_markdown(payload)

    if options.check:
        failures: list[str] = []
        if not JSON_PATH.is_file() or JSON_PATH.read_text(encoding="utf-8") != json_text:
            failures.append(str(JSON_PATH.relative_to(REPO_ROOT)))
        if not MD_PATH.is_file() or MD_PATH.read_text(encoding="utf-8") != md_text:
            failures.append(str(MD_PATH.relative_to(REPO_ROOT)))
        if failures:
            print(f"registration drift: {', '.join(failures)}", file=sys.stderr)
            return 1
        print("registration matches the code that obeys it")
        return 0

    WP.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json_text, encoding="utf-8")
    MD_PATH.write_text(md_text, encoding="utf-8")
    print(f"wrote {JSON_PATH.relative_to(REPO_ROOT)} and {MD_PATH.relative_to(REPO_ROOT)}")
    for arm, book in payload["books"].items():
        print(f"  {arm:<36} {book['params_hash'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
