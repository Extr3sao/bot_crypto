"""ai_vision_smoke — one real multimodal call, with the receipts.

This is the test the whole RFC stands on: does a vision model actually receive the
chart image, and does a decision come back that the pipeline can use?

It answers three questions and refuses to blur them:

1. was a call made at all? (no credential -> ``BLOCKED``, exit 2, nothing invented);
2. did the provider receive *this* image? (the request's base64 must hash to the chart's
   SHA-256, and the provider's own response id is recorded);
3. did the answer parse into a decision? (a prose answer is a ``FAIL``, not a decision).

Evidence is written next to the report: the PNG, the request shape without the base64
body, the raw response, and one line in a hash-chained ledger.

    python scripts/ai_vision_smoke.py [--symbol BTC/USDT] [--index 900]

Exit codes: 0 verified, 1 failure, 2 blocked (no credential / no network).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.economic_recovery.experiments import load_ohlcv  # noqa: E402
from trading_bot.vision.chart import render_chart_png  # noqa: E402
from trading_bot.vision.contract import DecisionParseError, parse_decision  # noqa: E402
from trading_bot.vision.ledger import DecisionLedger, verify_chain  # noqa: E402
from trading_bot.vision.prompt import build_prompt  # noqa: E402
from trading_bot.vision.provider import (  # noqa: E402
    MissingCredentialError,
    OpenAICompatibleVisionProvider,
    ProviderError,
    VisionRequest,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402

OUT = REPO / "reports" / "ai-vision" / "RFC-AI-VISION-001" / "evidence" / "smoke"
DATA = {
    "BTC/USDT": REPO / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json",
    "ETH/USDT": REPO / "data" / "edge07" / "holdout-1h" / "ETHUSDT_holdout2026.json",
    "SOL/USDT": REPO / "data" / "edge07" / "holdout-1h" / "SOLUSDT_holdout2026.json",
}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="one real multimodal decision, with evidence")
    parser.add_argument("--symbol", default="BTC/USDT", choices=sorted(DATA))
    parser.add_argument("--index", type=int, default=900, help="bar index of the decision close")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument(
        "--dry-run-payload",
        action="store_true",
        help="write the request that would be sent, without calling the provider",
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config = load_vision_config(env=__import__("os").environ)
    api_key = config.api_key()

    bars = load_ohlcv(DATA[args.symbol])
    index = max(10, min(args.index, len(bars) - 1))
    window = bars[: index + 1]
    chart = render_chart_png(window, symbol=args.symbol, window_bars=config.lane.window_bars)
    (out / "chart.png").write_bytes(chart.png)

    prompt = build_prompt(
        {
            "symbol": args.symbol,
            "timeframe": config.lane.timeframe,
            "window_bars": chart.bar_count,
            "last_close": float(bars[index].close),
            "equity": 10_000.0,
            "open_positions": 0,
            "max_open_positions": 3,
            "risk_per_trade_pct": 0.25,
            "max_weekly_loss_pct": 3.0,
            "position": None,
        }
    )
    request = VisionRequest(chart=chart, prompt=prompt, decision_ts_ms=int(bars[index].ts_ms))
    adapter = OpenAICompatibleVisionProvider(
        api_key=api_key,
        model=config.provider.model,
        base_url=config.provider.base_url,
        timeout_s=config.provider.timeout_s,
        max_attempts=config.provider.max_attempts,
        supports_json_object=config.provider.supports_json_object,
        prices=__import__("trading_bot.vision.provider", fromlist=["PriceTable"]).PriceTable(
            input_usd_per_mtok=config.provider.prices.input_usd_per_mtok,
            output_usd_per_mtok=config.provider.prices.output_usd_per_mtok,
            image_tokens_estimate=config.provider.prices.image_tokens_estimate,
        ),
    )

    payload = adapter.build_payload(request)
    payload_shape = {
        "model": payload["model"],
        "temperature": payload["temperature"],
        "max_tokens": payload["max_tokens"],
        "response_format": payload.get("response_format"),
        "messages": [
            {"role": "system", "chars": len(payload["messages"][0]["content"])},
            {
                "role": "user",
                "text_chars": len(payload["messages"][1]["content"][0]["text"]),
                "image": {
                    "data_uri_prefix": payload["messages"][1]["content"][1]["image_url"]["url"][:30],
                    "detail": payload["messages"][1]["content"][1]["image_url"]["detail"],
                    "base64_chars": len(payload["messages"][1]["content"][1]["image_url"]["url"]),
                },
            },
        ],
    }
    _write(out / "request_shape.json", {"chart": chart.fingerprint(), "payload": payload_shape})
    (out / "prompt.txt").write_text(
        f"SYSTEM\n{request.prompt.system}\n\nUSER\n{request.prompt.user}\n", encoding="utf-8"
    )

    result: dict[str, object] = {
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol": args.symbol,
        "decision_bar_utc": datetime.fromtimestamp(
            int(bars[index].ts_ms) / 1000.0, tz=UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chart": chart.fingerprint(),
        "provider_config": config.as_public_dict(),
        "request_has_image": True,
    }

    if args.dry_run_payload:
        result["status"] = "DRY_RUN"
        result["note"] = "payload built and hashed; the provider was not called"
        _write(out / "SMOKE_RESULT.json", result)
        print("[smoke] DRY_RUN — payload built, no call made")
        return 0

    if api_key is None:
        result["status"] = "BLOCKED"
        result["reason"] = "MISSING_CREDENTIAL"
        result["instructions"] = (
            f"set {config.provider.api_key_env} in the repository .env (the value never "
            "goes in chat or in git) and re-run this script"
        )
        _write(out / "SMOKE_RESULT.json", result)
        print(
            "[smoke] BLOCKED — no credential: set "
            f"{config.provider.api_key_env} in .env and re-run. No decision was invented."
        )
        return 2

    try:
        response = adapter.analyze(request)
    except MissingCredentialError as exc:
        result["status"] = "BLOCKED"
        result["reason"] = exc.code
        _write(out / "SMOKE_RESULT.json", result)
        print(f"[smoke] BLOCKED — {exc.code}")
        return 2
    except ProviderError as exc:
        result["status"] = "FAIL"
        result["reason"] = exc.code
        result["detail"] = exc.detail
        _write(out / "SMOKE_RESULT.json", result)
        print(f"[smoke] FAIL — {exc.code}: {exc.detail[:200]}")
        return 1

    (out / "response.json").write_text(
        json.dumps(response.raw, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "response.txt").write_text(response.text, encoding="utf-8")

    result.update(
        {
            "call": response.to_row(),
            "image_hash_matches_request": response.image_sha256_in_request == chart.sha256,
            "provider_echoed_model": response.model,
        }
    )

    try:
        decision = parse_decision(response.text, symbol=args.symbol)
    except DecisionParseError as exc:
        result["status"] = "FAIL"
        result["reason"] = exc.code
        result["detail"] = exc.detail
        _write(out / "SMOKE_RESULT.json", result)
        print(f"[smoke] FAIL — answer did not satisfy the contract: {exc.code} {exc.detail[:160]}")
        return 1

    result["decision"] = decision.model_dump(mode="json")

    with DecisionLedger(out / "smoke_ledger.jsonl") as ledger:
        ledger.append(
            "DECISION",
            {
                "ts_ms": int(bars[index].ts_ms),
                "symbol": args.symbol,
                "chart": chart.fingerprint(),
                "prompt": {"version": prompt.version, "sha256": prompt.sha256},
                "provider": response.to_row(),
                "raw_answer": response.text[:4000],
                "decision": decision.model_dump(mode="json"),
                "smoke": True,
            },
        )
    result["ledger"] = verify_chain(out / "smoke_ledger.jsonl")
    result["status"] = "VERIFIED"

    _write(out / "SMOKE_RESULT.json", result)
    print(
        "[smoke] VERIFIED — "
        f"{response.provider}/{response.model} id={response.request_id} "
        f"image={chart.sha256[:12]} in_request={str(response.image_sha256_in_request)[:12]} "
        f"action={decision.action} conf={decision.confidence:.2f} "
        f"{response.latency_ms}ms cost~${response.cost_usd or 0:.5f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
