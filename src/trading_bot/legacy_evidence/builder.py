"""Builds the :class:`LegacyEvidenceStore` from ingested legacy files.

Deterministic: same ZIP contents -> same evidence IDs, hashes and records
(G15). IDs are content-derived (not path- or time-derived).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .ingest import SOURCE_VERSION, LegacyEvidenceIngester
from .store import LegacyEvidenceRecord, LegacyEvidenceStore

_PERIOD_START = datetime(2026, 5, 1, tzinfo=UTC)
_PERIOD_END = datetime(2026, 8, 18, tzinfo=UTC)


def _short_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class LegacyEvidenceBuilder:
    """Parses allowlisted legacy files into immutable evidence records."""

    def __init__(
        self, ingester: LegacyEvidenceIngester, workdir: str | Any, *, require_all: bool = True
    ) -> None:
        self._ingester = ingester
        self._workdir = workdir
        self._require_all = require_all

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _record(
        *,
        evidence_id: str,
        source_sha256: str,
        kind: str,
        verdict: str,
        symbol: str | None = None,
        legacy_family: str | None = None,
        canonical_strategy_hint: str | None = None,
        sample_n: int | None = None,
        gross_expectancy_r: float | None = None,
        net_expectancy_r: float | None = None,
        profit_factor: float | None = None,
        gross_pnl: float | None = None,
        fees: float | None = None,
        net_pnl: float | None = None,
        payload: dict[str, Any] | None = None,
        source_version: str = SOURCE_VERSION,
    ) -> LegacyEvidenceRecord:
        return LegacyEvidenceRecord(
            evidence_id=evidence_id,
            source_version=source_version,
            source_sha256=source_sha256,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            symbol=symbol,
            legacy_family=legacy_family,
            canonical_strategy_hint=canonical_strategy_hint,
            sample_n=sample_n,
            gross_expectancy_r=gross_expectancy_r,
            net_expectancy_r=net_expectancy_r,
            profit_factor=profit_factor,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            verdict=verdict,
            kind=kind,
            payload=payload or {},
        )

    @staticmethod
    def _canonical_hint(family: str | None) -> str | None:
        """Map legacy families to the canonical strategy universe (hint only).

        FBS (fee-broken scalps) ~ MeanReversion; TP (trend-pullback) ~ Trend;
        BR/LSR ran zero trades in R26. Informational only: it never changes
        routing.
        """
        mapping = {
            "FBS": "MeanReversion",
            "TP": "Trend",
            "BR": "Breakout",
            "LSR": "Volatility",
        }
        if family is None:
            return None
        return mapping.get(family.upper())

    @staticmethod
    def _agg(row: dict[str, str]) -> dict[str, Any]:
        n_raw = row.get("n")
        return {
            "sample_n": int(float(n_raw)) if n_raw else None,
            "gross_expectancy_r": _num(row.get("exp_r")),
            "net_expectancy_r": _num(row.get("exp_r")),
            "profit_factor": _num(row.get("pf")),
            "gross_pnl": _num(row.get("gross_pnl")),
            "fees": _num(row.get("fees")),
            "net_pnl": _num(row.get("pnl")),
        }

    # -- parsers -----------------------------------------------------------

    def _parse_resultados(
        self, provenance: dict[str, Any]
    ) -> tuple[list[LegacyEvidenceRecord], dict[str, Any]]:
        sha = provenance["files_by_name"]["RESULTADOS_V57_R26_B.json"]["sha256"]
        data = self._ingester.load_json(self._workdir, "RESULTADOS_V57_R26_B.json")
        portfolio = data["portfolio"]
        period = data["period"]
        source_version = str(data.get("version", SOURCE_VERSION))
        record = self._record(
            evidence_id=f"legacy:r26:portfolio:{_short_hash(portfolio)}",
            source_sha256=sha,
            kind="portfolio",
            verdict=str(data.get("status", "")),
            sample_n=int(portfolio.get("n", 0)),
            net_expectancy_r=_num(portfolio.get("exp_r")),
            profit_factor=_num(portfolio.get("pf")),
            gross_pnl=_num(portfolio.get("gross_pnl")),
            fees=_num(portfolio.get("fees")),
            net_pnl=_num(portfolio.get("pnl")),
            payload={"portfolio": portfolio, "period": period},
            source_version=source_version,
        )
        sanity = {
            "trades": int(portfolio.get("n", 0)),
            "complete_days": int(period.get("complete_days_evaluated", 0)),
            "gross_pnl": _num(portfolio.get("gross_pnl")),
            "fees": _num(portfolio.get("fees")),
            "net_pnl": _num(portfolio.get("pnl")),
            "pf": _num(portfolio.get("pf")),
            "expectancy_r": _num(portfolio.get("exp_r")),
        }
        return [record], sanity

    def _parse_by_asset(self, provenance: dict[str, Any]) -> list[LegacyEvidenceRecord]:
        sha = provenance["files_by_name"]["BY_ASSET_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "BY_ASSET_V57_R26_B.csv")
        records: list[LegacyEvidenceRecord] = []
        for row in rows:
            asset = (row.get("asset") or "").upper()
            records.append(
                self._record(
                    evidence_id=f"legacy:r26:asset:{asset}:{_short_hash(row)}",
                    source_sha256=sha,
                    kind="asset_aggregate",
                    verdict="LEGACY_OBSERVATION",
                    symbol=asset,
                    payload={"raw": row},
                    **self._agg(row),
                )
            )
        return records

    def _parse_by_family(
        self, provenance: dict[str, Any]
    ) -> tuple[list[LegacyEvidenceRecord], dict[str, int]]:
        sha = provenance["files_by_name"]["BY_FAMILY_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "BY_FAMILY_V57_R26_B.csv")
        records: list[LegacyEvidenceRecord] = []
        trade_counts: dict[str, int] = {}
        for row in rows:
            family = (row.get("family") or "").upper()
            n_raw = row.get("n")
            trade_counts[family] = int(float(n_raw)) if n_raw else 0
            records.append(
                self._record(
                    evidence_id=f"legacy:r26:family:{family}:{_short_hash(row)}",
                    source_sha256=sha,
                    kind="family_aggregate",
                    verdict="LEGACY_OBSERVATION",
                    legacy_family=family,
                    canonical_strategy_hint=self._canonical_hint(family),
                    payload={"raw": row},
                    **self._agg(row),
                )
            )
        return records, trade_counts

    def _parse_daily(
        self, provenance: dict[str, Any]
    ) -> tuple[LegacyEvidenceRecord, dict[str, int]]:
        sha = provenance["files_by_name"]["DAILY_COVERAGE_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "DAILY_COVERAGE_V57_R26_B.csv")
        complete = sum(1 for r in rows if (r.get("coverage_pass") or "").lower() == "true")
        payload = {
            "days": len(rows),
            "complete_days": complete,
            "raw_days": rows,
        }
        record = self._record(
            evidence_id=(
                f"legacy:r26:daily_coverage:{_short_hash({'days': len(rows), 'complete': complete})}"
            ),
            source_sha256=sha,
            kind="daily_coverage",
            verdict="R26_FREQUENCY_PASS_108_OF_108" if complete == len(rows) else "PARTIAL_COVERAGE",
            sample_n=len(rows),
            payload=payload,
        )
        return record, {"days": len(rows), "complete_days": complete}

    def _parse_fbs(self, provenance: dict[str, Any]) -> list[LegacyEvidenceRecord]:
        sha = provenance["files_by_name"]["FBS_BY_EXIT_REASON_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "FBS_BY_EXIT_REASON_V57_R26_B.csv")
        records: list[LegacyEvidenceRecord] = []
        for row in rows:
            reason = (row.get("exit_reason") or "").upper()
            records.append(
                self._record(
                    evidence_id=f"legacy:r26:fbs_exit:{reason}:{_short_hash(row)}",
                    source_sha256=sha,
                    kind="exit_reason_aggregate",
                    verdict="LEGACY_OBSERVATION",
                    legacy_family="FBS",
                    canonical_strategy_hint="MeanReversion",
                    payload={"raw": row, "exit_reason": reason},
                    **self._agg(row),
                )
            )
        return records

    def _parse_blocked(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["BLOCKED_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "BLOCKED_V57_R26_B.csv")
        by_reason: dict[str, int] = {}
        for row in rows:
            reason = row.get("reason") or "UNKNOWN"
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return self._record(
            evidence_id=(
                f"legacy:r26:blocked:{_short_hash({'rows': len(rows), 'reasons': sorted(by_reason)})}"
            ),
            source_sha256=sha,
            kind="blocked_aggregate",
            verdict="LEGACY_OBSERVATION",
            sample_n=len(rows),
            payload={"rows": len(rows), "by_reason": by_reason},
        )

    def _parse_opportunities(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["OPPORTUNITIES_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "OPPORTUNITIES_V57_R26_B.csv")
        return self._record(
            evidence_id=f"legacy:r26:opportunities:{_short_hash({'rows': len(rows)})}",
            source_sha256=sha,
            kind="opportunity_aggregate",
            verdict="LEGACY_OBSERVATION",
            sample_n=len(rows),
            payload={"rows": len(rows)},
        )

    def _parse_trades(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["TRADES_V57_R26_B.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(self._workdir, "TRADES_V57_R26_B.csv")
        net = sum(float(r["net_pnl_usd"]) for r in rows if r.get("net_pnl_usd"))
        gross = sum(float(r["gross_pnl_usd"]) for r in rows if r.get("gross_pnl_usd"))
        fees = sum(float(r["fees_usd"]) for r in rows if r.get("fees_usd"))
        by_symbol: dict[str, int] = {}
        for row in rows:
            sym = (row.get("symbol") or "UNKNOWN").upper()
            by_symbol[sym] = by_symbol.get(sym, 0) + 1
        return self._record(
            evidence_id=(
                f"legacy:r26:trades:{_short_hash({'rows': len(rows), 'net': round(net, 6)})}"
            ),
            source_sha256=sha,
            kind="trade_aggregate",
            verdict="LEGACY_OBSERVATION",
            sample_n=len(rows),
            gross_pnl=gross,
            fees=fees,
            net_pnl=net,
            payload={"rows": len(rows), "by_symbol": by_symbol},
        )

    def _parse_r319(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["RESULTADOS_V57_R31_9_DIAGNOSTIC.json"]["sha256"]
        data = self._ingester.load_json(self._workdir, "RESULTADOS_V57_R31_9_DIAGNOSTIC.json")
        decision = data.get("pre_registered_decision", {})
        vol_ge1 = data.get("quality", {}).get("vol_ge_1", {})
        matched = bool(decision.get("vol_ge1_matched_test_justified"))
        verdict = "MATCHED_TEST_JUSTIFIED" if matched else "FAIL_NOT_PROMOTED"
        return self._record(
            evidence_id=f"legacy:r319:vol_ge_1:{_short_hash(decision)}",
            source_sha256=sha,
            kind="diagnostic",
            verdict=verdict,
            legacy_family="TP",
            canonical_strategy_hint="Trend",
            sample_n=int(vol_ge1.get("n", 0)),
            gross_expectancy_r=_num(vol_ge1.get("gross_exp_r")),
            net_expectancy_r=_num(vol_ge1.get("net_exp_r")),
            profit_factor=_num(vol_ge1.get("net_pf")),
            payload={
                "candidate": data.get("pre_registered", {}).get("candidate"),
                "pre_registered_decision": decision,
                "delta_net_exp_r_vs_subavg": data.get("delta_vol_ge1_minus_subavg_net_exp_r"),
                "guardrails": data.get("guardrails", []),
                "quality_bins": {
                    name: {
                        "n": q.get("n"),
                        "net_exp_r": q.get("net_exp_r"),
                        "net_pf": q.get("net_pf"),
                    }
                    for name, q in data.get("quality", {}).items()
                },
            },
            source_version=str(data.get("version", SOURCE_VERSION)),
        )

    def _parse_tp_volume(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv"]["sha256"]
        rows = self._ingester.load_csv_rows(
            self._workdir, "TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv"
        )
        cohorts: dict[str, int] = {}
        for row in rows:
            cohort = row.get("cohort") or "UNKNOWN"
            cohorts[cohort] = cohorts.get(cohort, 0) + 1
        return self._record(
            evidence_id=f"legacy:r319:classification:{_short_hash(cohorts)}",
            source_sha256=sha,
            kind="classification_aggregate",
            verdict="LEGACY_OBSERVATION",
            sample_n=len(rows),
            payload={"rows": len(rows), "by_cohort": cohorts},
        )

    def _parse_campaign_bcd(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["CAMPAIGN_FINAL_BCD.json"]["sha256"]
        data = self._ingester.load_json(self._workdir, "CAMPAIGN_FINAL_BCD.json")
        verdict = str(data.get("campaign_verdict", ""))
        individual = data.get("individual_results", {})
        portfolio = data.get("portfolio_results", {})
        evidence_id = (
            f"legacy:campaign:bcd:{_short_hash({'verdict': verdict, 'individual': individual})}"
        )
        return self._record(
            evidence_id=evidence_id,
            source_sha256=sha,
            kind="campaign",
            verdict=verdict,
            sample_n=len(individual),
            payload={
                "campaign_verdict": verdict,
                "individual_quality_passers": data.get("individual_quality_passers"),
                "portfolio_passers": data.get("portfolio_passers"),
                "individual_results": individual,
                "portfolio_results": portfolio,
                "consumed_development_period": data.get("consumed_development_period"),
            },
            source_version=str(data.get("version", SOURCE_VERSION)),
        )

    def _parse_registry(self, provenance: dict[str, Any]) -> LegacyEvidenceRecord:
        sha = provenance["files_by_name"]["research_registry.json"]["sha256"]
        data = self._ingester.load_json(self._workdir, "research_registry.json")
        ledger = data.get("ledger", [])
        statuses = {entry.get("id"): entry.get("status") for entry in ledger}
        return self._record(
            evidence_id=f"legacy:registry:{_short_hash(statuses)}",
            source_sha256=sha,
            kind="registry",
            verdict=str(data.get("control_plane_version", "")),
            payload={"ledger": ledger, "next_campaign": data.get("next_campaign")},
        )

    def _parse_manifests(self, provenance: dict[str, Any]) -> list[LegacyEvidenceRecord]:
        records: list[LegacyEvidenceRecord] = []
        for name in (
            "E_VOLATILITY_EXPANSION.json",
            "F_LIQUIDITY_SWEEP_REVERSION.json",
            "G_CROSS_SECTIONAL_MOMENTUM.json",
        ):
            sha = provenance["files_by_name"][name]["sha256"]
            data = self._ingester.load_json(self._workdir, name)
            records.append(
                self._record(
                    evidence_id=f"legacy:manifest:{name.split('_')[0]}:{_short_hash(data)}",
                    source_sha256=sha,
                    kind="manifest_metadata",
                    verdict="METADATA_ONLY_NOT_CODE",
                    payload={"manifest": data},
                )
            )
        return records

    # -- public API ----------------------------------------------------------

    def build(self) -> tuple[LegacyEvidenceStore, dict[str, Any]]:
        provenance = self._ingester.ingest(
            self._workdir, require_all=self._require_all
        )
        provenance["files_by_name"] = {f["name"]: f for f in provenance["files"]}
        records: list[LegacyEvidenceRecord] = []
        sanity: dict[str, Any] = {}

        r26_records, r26_sanity = self._parse_resultados(provenance)
        records += r26_records
        sanity.update(r26_sanity)

        asset_records = self._parse_by_asset(provenance)
        records += asset_records
        sanity["by_asset_rows"] = len(asset_records)

        family_records, family_counts = self._parse_by_family(provenance)
        records += family_records
        sanity["trades_by_family"] = family_counts

        daily_record, daily_counts = self._parse_daily(provenance)
        records.append(daily_record)
        sanity["complete_days"] = daily_counts["complete_days"]
        sanity["daily_rows"] = daily_counts["days"]

        records += self._parse_fbs(provenance)
        records.append(self._parse_blocked(provenance))
        opportunities_record = self._parse_opportunities(provenance)
        records.append(opportunities_record)
        sanity["opportunities"] = opportunities_record.sample_n

        trades_record = self._parse_trades(provenance)
        records.append(trades_record)
        sanity["trades_recomputed"] = trades_record.sample_n
        sanity["gross_pnl_recomputed"] = trades_record.gross_pnl
        sanity["fees_recomputed"] = trades_record.fees
        sanity["net_pnl_recomputed"] = trades_record.net_pnl
        sanity["trades_by_symbol_count"] = len(trades_record.payload.get("by_symbol", {}))

        records.append(self._parse_r319(provenance))
        records.append(self._parse_tp_volume(provenance))
        records.append(self._parse_campaign_bcd(provenance))
        records.append(self._parse_registry(provenance))
        records += self._parse_manifests(provenance)

        store = LegacyEvidenceStore(records)
        report = {
            "record_count": len(store),
            "sanity": sanity,
            "provenance": {k: v for k, v in provenance.items() if k != "files_by_name"},
        }
        return store, report
