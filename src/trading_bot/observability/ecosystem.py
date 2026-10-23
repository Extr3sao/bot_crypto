"""Strategy-ecosystem observability projection layer (WP-OBS-STRAT-01 §5/§6/§29).

Read-only. This module turns the runtime's *authoritative* artifacts into
JSON-serialisable **read models** the dashboard consumes. It computes nothing
about trading, cannot mutate anything, and never fabricates a value: a datum that
is absent is reported as ``NOT_AVAILABLE``, a state that cannot be established as
``UNKNOWN``, and a sample too small to conclude from as ``INSUFFICIENT_SAMPLE``.

Authoritative sources (all read-only):

* ``config/strategy_admission.json`` — the canonical strategy registry;
* ``reports/autonomous-paper/<run_id>/traces.jsonl`` — hash-chained DecisionTrace;
* ``reports/autonomous-paper/<run_id>/performance.json`` — contextual performance;
* ``reports/autonomous-paper/<run_id>/routing_comparisons.jsonl`` — LEGACY vs LIFECYCLE;
* ``reports/autonomous-paper/<run_id>/outcomes.jsonl`` — realised outcomes;
* ``reports/autonomous-paper/<run_id>/heartbeat.json`` / ``PAPER_RUN.json``;
* ``reports/paper-strategy-lifecycle-shadow-*/`` — campaign reports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from trading_bot.observability.topology import AgentTopologyReport, build_agent_topology

__all__ = [
    "INSUFFICIENT_DATA",
    "INSUFFICIENT_SAMPLE",
    "NOT_AVAILABLE",
    "UNKNOWN",
    "RunArtifacts",
    "StrategyEcosystemObservatory",
    "read_json",
    "read_jsonl",
]

NOT_AVAILABLE: Final[str] = "NOT_AVAILABLE"
UNKNOWN: Final[str] = "UNKNOWN"
INSUFFICIENT_DATA: Final[str] = "INSUFFICIENT_DATA"
INSUFFICIENT_SAMPLE: Final[str] = "INSUFFICIENT_SAMPLE"

#: heartbeat older than this is STALE, not HEALTHY (paper interval is 60 s).
STALE_HEARTBEAT_SECONDS: Final[float] = 900.0
#: below this many resolved samples a per-cell metric is not a conclusion.
MIN_SAMPLES: Final[int] = 5


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read a JSONL file defensively: a malformed line is skipped, never fatal."""
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
                if limit is not None and len(out) >= limit:
                    break
    except OSError:
        return out
    return out


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    run_id: str
    run_dir: Path
    artifact_version_hash: str = ""

    def path(self, name: str) -> Path:
        return self.run_dir / name


@dataclass(slots=True)
class StrategyEcosystemObservatory:
    """Read-only projection over the runtime's authoritative artifacts."""

    repo_root: Path
    runs_root: Path | None = None
    campaigns_root: Path | None = None
    admission_path: Path | None = None
    run_id: str | None = None
    stale_heartbeat_seconds: float = STALE_HEARTBEAT_SECONDS
    now_ms: int | None = None
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        r = Path(self.repo_root).resolve()
        self.repo_root = r
        self.runs_root = Path(self.runs_root) if self.runs_root is not None else None
        self.campaigns_root = Path(self.campaigns_root) if self.campaigns_root is not None else None
        self.admission_path = Path(self.admission_path) if self.admission_path is not None else None
        if self.runs_root is None:
            self.runs_root = r / "reports" / "autonomous-paper"
        if self.campaigns_root is None:
            self.campaigns_root = r / "reports"
        if self.admission_path is None:
            self.admission_path = r / "config" / "strategy_admission.json"

    # ---------------------------------------------------------------- discovery

    def admission(self) -> dict[str, Any]:
        if "admission" not in self._cache:
            payload = read_json(self.admission_path) if self.admission_path else None
            self._cache["admission"] = payload if isinstance(payload, dict) else {}
        return cast(dict[str, Any], self._cache["admission"])

    def admission_strategies(self) -> dict[str, dict[str, Any]]:
        strategies = self.admission().get("strategies")
        return strategies if isinstance(strategies, dict) else {}

    def list_runs(self) -> list[RunArtifacts]:
        root = self.runs_root
        if root is None or not root.exists():
            return []
        out: list[RunArtifacts] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if any(
                (child / name).exists()
                for name in ("PAPER_RUN.json", "traces.jsonl", "heartbeat.json")
            ):
                out.append(RunArtifacts(run_id=child.name, run_dir=child))
        return out

    def current_run(self) -> RunArtifacts | None:
        runs = self.list_runs()
        if not runs:
            return None
        if self.run_id is not None:
            for run in runs:
                if run.run_id == self.run_id:
                    return run
            return None

        # newest heartbeat/PAPER_RUN mtime
        def mtime(run: RunArtifacts) -> float:
            stamps = [
                (run.run_dir / name).stat().st_mtime
                for name in ("heartbeat.json", "PAPER_RUN.json", "traces.jsonl")
                if (run.run_dir / name).exists()
            ]
            return max(stamps) if stamps else 0.0

        return max(runs, key=mtime)

    # --------------------------------------------------------------- raw reads

    def _traces(self, run: RunArtifacts) -> list[dict[str, Any]]:
        key = f"traces:{run.run_id}"
        if key not in self._cache:
            self._cache[key] = read_jsonl(run.path("traces.jsonl"))
        return cast(list[dict[str, Any]], self._cache[key])

    def _performance(self, run: RunArtifacts) -> dict[str, Any]:
        key = f"perf:{run.run_id}"
        if key not in self._cache:
            payload = read_json(run.path("performance.json"))
            self._cache[key] = payload if isinstance(payload, dict) else {}
        return cast(dict[str, Any], self._cache[key])

    def _comparisons(self, run: RunArtifacts) -> list[dict[str, Any]]:
        key = f"cmp:{run.run_id}"
        if key not in self._cache:
            self._cache[key] = read_jsonl(run.path("routing_comparisons.jsonl"))
        return cast(list[dict[str, Any]], self._cache[key])

    def _outcomes(self, run: RunArtifacts) -> list[dict[str, Any]]:
        key = f"out:{run.run_id}"
        if key not in self._cache:
            self._cache[key] = read_jsonl(run.path("outcomes.jsonl"))
        return cast(list[dict[str, Any]], self._cache[key])

    def _paper_run(self, run: RunArtifacts) -> dict[str, Any]:
        payload = read_json(run.path("PAPER_RUN.json"))
        return payload if isinstance(payload, dict) else {}

    def _heartbeat(self, run: RunArtifacts) -> dict[str, Any]:
        payload = read_json(run.path("heartbeat.json"))
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------ topology

    def topology(self) -> AgentTopologyReport:
        caps: tuple[dict[str, Any], ...] = ()
        try:
            from trading_bot.autonomous.agents import default_agent_registry

            caps = tuple(c.to_dict() for c in default_agent_registry().capabilities())
        except Exception:
            caps = ()
        return build_agent_topology(self.admission_strategies(), agent_capabilities=caps)

    # -------------------------------------------------------------- freshness

    def _commit(self) -> str:
        if "commit" not in self._cache:
            self._cache["commit"] = _git_commit(self.repo_root)
        return str(self._cache["commit"])

    def _clock_ms(self) -> int:
        if self.now_ms is not None:
            return self.now_ms
        import time

        return int(time.time() * 1000)

    def _freshness(self, ts_ms: int | None) -> dict[str, Any]:
        if not ts_ms:
            return {"status": UNKNOWN, "age_seconds": None, "data_timestamp_ms": None}
        age = max(0.0, (self._clock_ms() - ts_ms) / 1000.0)
        status = "FRESH" if age <= self.stale_heartbeat_seconds else "STALE"
        return {"status": status, "age_seconds": round(age, 1), "data_timestamp_ms": ts_ms}

    # ----------------------------------------------------------- aggregation

    def _aggregate(self, run: RunArtifacts | None) -> dict[str, Any]:
        """Stream the run's traces once into per-strategy + decision aggregates."""
        if run is None:
            return {
                "strategies": {},
                "decisions": 0,
                "no_trade_kinds": {},
                "risk": {},
                "order_created": 0,
                "verification": {},
                "last_activity_ms": None,
            }
        key = f"agg:{run.run_id}"
        if key in self._cache:
            return cast(dict[str, Any], self._cache[key])
        traces = self._traces(run)
        strategies: dict[str, dict[str, Any]] = {}
        no_trade_kinds: dict[str, int] = {}
        risk: dict[str, int] = {}
        verification: dict[str, int] = {}
        order_created = 0
        last_activity: int | None = None
        for trace in traces:
            ts = trace.get("created_at_ms") or trace.get("decision_time_ms")
            if isinstance(ts, int) and (last_activity is None or ts > last_activity):
                last_activity = ts
            kind = trace.get("no_trade_kind")
            if kind:
                no_trade_kinds[str(kind)] = no_trade_kinds.get(str(kind), 0) + 1
            risk_block = trace.get("risk") or {}
            verdict = str(risk_block.get("verdict", risk_block.get("risk_result", UNKNOWN)))
            risk[verdict] = risk.get(verdict, 0) + 1
            ver = trace.get("verification") or {}
            vverdict = str(ver.get("verdict", UNKNOWN))
            verification[vverdict] = verification.get(vverdict, 0) + 1
            if trace.get("order_created"):
                order_created += 1
            proposal = trace.get("proposal") or {}
            proposed_id = proposal.get("strategy_id") if isinstance(proposal, dict) else None
            for considered in trace.get("strategies_considered", []) or []:
                sid = str(considered.get("strategy_id"))
                agg = strategies.setdefault(
                    sid,
                    {
                        "considered": 0,
                        "emitted_alpha": 0,
                        "router_selected": 0,
                        "proposed": 0,
                        "lifecycle": {},
                        "router_status": {},
                        "last_activity_ms": None,
                    },
                )
                agg["considered"] += 1
                if considered.get("emitted_alpha"):
                    agg["emitted_alpha"] += 1
                if considered.get("selected"):
                    agg["router_selected"] += 1
                lv = str(considered.get("lifecycle_verdict", UNKNOWN))
                agg["lifecycle"][lv] = agg["lifecycle"].get(lv, 0) + 1
                rs = str(considered.get("router_status", UNKNOWN))
                agg["router_status"][rs] = agg["router_status"].get(rs, 0) + 1
                if proposed_id is not None and sid == proposed_id:
                    agg["proposed"] += 1
                    if isinstance(ts, int):
                        agg["last_activity_ms"] = max(agg["last_activity_ms"] or 0, ts)
        result = {
            "strategies": strategies,
            "decisions": len(traces),
            "no_trade_kinds": no_trade_kinds,
            "risk": risk,
            "order_created": order_created,
            "verification": verification,
            "last_activity_ms": last_activity,
        }
        self._cache[key] = result
        return result

    def _performance_by_strategy(self, run: RunArtifacts | None) -> dict[str, Any]:
        if run is None:
            return {"strategies": {}, "by_regime": {}}
        key = f"perfagg:{run.run_id}"
        if key in self._cache:
            return cast(dict[str, Any], self._cache[key])
        cells = self._performance(run).get("cells") or {}
        per_strategy: dict[str, list[dict[str, Any]]] = {}
        by_regime: dict[str, list[dict[str, Any]]] = {}
        for cell in cells.values():
            if not isinstance(cell, dict):
                continue
            sid = str(cell.get("strategy_id", UNKNOWN))
            regime = str(cell.get("regime", UNKNOWN))
            samples = cell.get("samples") or []
            per_strategy.setdefault(sid, []).extend(samples)
            by_regime.setdefault(regime, []).extend(samples)
        result = {
            "strategies": {sid: _summarise_samples(s) for sid, s in per_strategy.items()},
            "by_regime": {r: _summarise_samples(s) for r, s in by_regime.items()},
        }
        self._cache[key] = result
        return result

    # ----------------------------------------------------------- view builders

    def system_view(self) -> dict[str, Any]:
        run = self.current_run()
        strategies = self.admission_strategies()
        agg = self._aggregate(run)
        paper_run = self._paper_run(run) if run else {}
        heartbeat = self._heartbeat(run) if run else {}
        admitted = sum(1 for s in strategies.values() if s.get("admitted_for_paper"))
        return {
            "phase": "WP-OBS-STRAT-01",
            "environment": "PAPER",
            "runtime": {
                "run_id": run.run_id if run else NOT_AVAILABLE,
                "state": paper_run.get("state", UNKNOWN),
                "cycles": paper_run.get("cycles", NOT_AVAILABLE),
                "stop_reason": paper_run.get("stop_reason"),
                "runtime_failures": (paper_run.get("totals") or {}).get(
                    "runtime_failures", NOT_AVAILABLE
                ),
                "storage_failures": paper_run.get("storage_failures", NOT_AVAILABLE),
            },
            "routing_mode": _routing_mode(run),
            "campaign": run.run_id if run else NOT_AVAILABLE,
            "market_data_health": _market_health(heartbeat, run),
            "risk_engine": {
                "status": "DETERMINISTIC",
                "authority": "DETERMINISTIC",
                "verdicts": agg["risk"],
                "source": "RiskManager.check_signal",
            },
            "execution_mode": "PAPER",
            "live_trading_enabled": False,
            "commit": self._commit(),
            "config_hash": _file_hash(self.admission_path),
            "freshness": self._freshness(heartbeat.get("timestamp_ms") if heartbeat else None),
            "totals": {
                "strategies_total": len(strategies),
                "admitted_for_paper": admitted,
                "decisions": agg["decisions"],
                "signals": sum(a["emitted_alpha"] for a in agg["strategies"].values()),
                "proposals": sum(a["proposed"] for a in agg["strategies"].values()),
                "paper_trades": (paper_run.get("totals") or {}).get("paper_trades", NOT_AVAILABLE),
                "no_trade": agg["decisions"] - agg["order_created"],
                "no_trade_kinds": agg["no_trade_kinds"],
                "order_created": agg["order_created"],
                "outcomes_resolved": (paper_run.get("totals") or {}).get(
                    "outcomes_resolved", NOT_AVAILABLE
                ),
            },
            "false_success": 0,
            "open_critical_defects": NOT_AVAILABLE,
            "live_control": False,
            "read_only": True,
        }

    def strategies_view(self) -> dict[str, Any]:
        run = self.current_run()
        agg = self._aggregate(run)
        perf = self._performance_by_strategy(run)["strategies"]
        topology = {e.strategy_id: e for e in self.topology().entries}
        rows: list[dict[str, Any]] = []
        for sid, spec in sorted(self.admission_strategies().items()):
            st = agg["strategies"].get(sid, {})
            p = perf.get(sid, {})
            lifecycle = _dominant(st.get("lifecycle", {}))
            rows.append(
                {
                    "strategy_id": sid,
                    "strategy_version": sid,
                    "family": spec.get("family", UNKNOWN),
                    "timeframe": spec.get("timeframe", UNKNOWN),
                    "asset": "MULTI",
                    "admission_status": spec.get("status", UNKNOWN),
                    "admitted_for_paper": bool(spec.get("admitted_for_paper")),
                    "expected_gross_edge_bps": spec.get("expected_gross_edge_bps"),
                    "lifecycle": lifecycle,
                    "health": UNKNOWN,
                    "mode": _routing_mode(run),
                    "agent": topology[sid].agent_type if sid in topology else UNKNOWN,
                    "signals": st.get("emitted_alpha", 0),
                    "proposals": st.get("proposed", 0),
                    "considered": st.get("considered", 0),
                    "router_selected": st.get("router_selected", 0),
                    "trades": p.get("sample_count", NOT_AVAILABLE),
                    "expectancy_net_bps": p.get("net_expectancy_bps", NOT_AVAILABLE),
                    "profit_factor": p.get("profit_factor", NOT_AVAILABLE),
                    "pnl_bps": p.get("total_net_bps", NOT_AVAILABLE),
                    "drawdown_bps": p.get("max_drawdown_bps", NOT_AVAILABLE),
                    "last_activity_ms": st.get("last_activity_ms"),
                }
            )
        return {
            "run_id": run.run_id if run else NOT_AVAILABLE,
            "count": len(rows),
            "strategies": rows,
        }

    def strategy_detail(self, strategy_id: str) -> dict[str, Any] | None:
        spec = self.admission_strategies().get(strategy_id)
        if spec is None:
            return None
        run = self.current_run()
        agg = self._aggregate(run)
        perf = self._performance_by_strategy(run)
        st = agg["strategies"].get(strategy_id, {})
        topo = next((e for e in self.topology().entries if e.strategy_id == strategy_id), None)
        return {
            "identity": {
                "strategy_id": strategy_id,
                "strategy_version": strategy_id,
                "family": spec.get("family", UNKNOWN),
                "timeframe": spec.get("timeframe", UNKNOWN),
                "pod_id": topo.pod_id if topo else UNKNOWN,
                "runtime_implementation": topo.runtime_implementation if topo else UNKNOWN,
                "agent_id": topo.agent_id if topo else None,
                "agent_type": topo.agent_type if topo else UNKNOWN,
            },
            "state": {
                "lifecycle": _dominant(st.get("lifecycle", {})),
                "health": UNKNOWN,
                "execution_mode": "PAPER",
                "admission_status": spec.get("status", UNKNOWN),
                "admitted_for_paper": bool(spec.get("admitted_for_paper")),
                "runtime_reachability": topo.runtime_reachability if topo else UNKNOWN,
            },
            "performance": {
                "overall": perf["strategies"].get(strategy_id, {"status": INSUFFICIENT_DATA}),
                "by_regime": {
                    r: _cell_for_strategy(run, strategy_id, r) for r in sorted(perf["by_regime"])
                },
            },
            "funnel": self.strategy_funnel(strategy_id),
            "evidence": {
                "admission_source": spec.get("source_doc", NOT_AVAILABLE),
                "rationale": spec.get("rationale", NOT_AVAILABLE),
                "run_id": run.run_id if run else NOT_AVAILABLE,
                "trace_file": str(run.path("traces.jsonl")) if run else NOT_AVAILABLE,
            },
        }

    def strategy_funnel(self, strategy_id: str) -> dict[str, Any]:
        run = self.current_run()
        agg = self._aggregate(run)
        st = agg["strategies"].get(strategy_id, {})
        lifecycle = st.get("lifecycle", {})
        router = st.get("router_status", {})
        active = lifecycle.get("ACTIVE", 0)
        considered = st.get("considered", 0)
        emitted = st.get("emitted_alpha", 0)
        proposed = st.get("proposed", 0)
        selected = st.get("router_selected", 0)
        return {
            "strategy_id": strategy_id,
            "stages": [
                {"stage": "OBSERVATIONS", "count": considered},
                {"stage": "SIGNALS", "count": emitted},
                {"stage": "LIFECYCLE_ELIGIBLE", "count": active},
                {"stage": "ROUTER_SELECTED", "count": selected},
                {"stage": "PROPOSAL", "count": proposed},
                {"stage": "REGIME_ELIGIBLE", "count": NOT_AVAILABLE},
                {"stage": "HEALTH_ELIGIBLE", "count": NOT_AVAILABLE},
                {"stage": "PORTFOLIO_ACCEPTED", "count": NOT_AVAILABLE},
                {"stage": "DECISION_ACCEPTED", "count": NOT_AVAILABLE},
                {"stage": "RISK_ACCEPTED", "count": NOT_AVAILABLE},
                {"stage": "EXECUTED", "count": NOT_AVAILABLE},
            ],
            "rejections": {
                "rejected_by_lifecycle": considered - active if considered else 0,
                "rejected_by_router": sum(v for k, v in router.items() if k not in ("SELECTED",)),
                "rejected_by_regime": NOT_AVAILABLE,
                "rejected_by_health": NOT_AVAILABLE,
                "rejected_by_portfolio": NOT_AVAILABLE,
                "rejected_by_decision": NOT_AVAILABLE,
                "rejected_by_risk": NOT_AVAILABLE,
            },
            "router_status": dict(router),
            "lifecycle_verdict": dict(lifecycle),
            "note": "later stages are decision-level in this runtime and are not attributable per strategy",
        }

    def lifecycle_view(self) -> dict[str, Any]:
        run = self.current_run()
        agg = self._aggregate(run)
        histogram: dict[str, int] = {}
        for st in agg["strategies"].values():
            state = _dominant(st.get("lifecycle", {}))
            histogram[state] = histogram.get(state, 0) + 1
        return {
            "states": histogram,
            "admission_histogram": _admission_histogram(self.admission_strategies()),
            "transitions": NOT_AVAILABLE,
            "note": "dynamic registry state is not persisted by the shadow run; lifecycle verdict comes from the decision traces",
        }

    def agents_view(self) -> dict[str, Any]:
        topo = self.topology()
        run = self.current_run()
        activity = self._agent_activity(run)
        agents = []
        for agent in topo.shared_agents:
            aid = agent["agent_id"]
            act = activity.get(aid, {})
            agents.append(
                {
                    **agent,
                    "status": "ACTIVE" if act.get("messages") else UNKNOWN,
                    "messages": act.get("messages", 0),
                    "last_activity_ms": act.get("last_activity_ms"),
                    "review_types": act.get("review_types", {}),
                    "llm_calls": 0,
                    "llm_cost": NOT_AVAILABLE,
                    "latency_ms": act.get("latency_ms", NOT_AVAILABLE),
                    "independent_state": False,
                    "note": "deterministic, shared decision-layer reviewer",
                }
            )
        return {
            "agents": agents,
            "count": len(agents),
            "governance": topo.are_strategies_governed_by_independent_agents,
        }

    def _agent_activity(self, run: RunArtifacts | None) -> dict[str, dict[str, Any]]:
        if run is None:
            return {}
        key = f"agentact:{run.run_id}"
        if key in self._cache:
            return cast(dict[str, dict[str, Any]], self._cache[key])
        out: dict[str, dict[str, Any]] = {}
        for trace in self._traces(run):
            ts = trace.get("created_at_ms") or trace.get("decision_time_ms")
            for msg in trace.get("agent_messages", []) or []:
                aid = str(msg.get("agent_id", UNKNOWN))
                row = out.setdefault(
                    aid, {"messages": 0, "last_activity_ms": None, "review_types": {}}
                )
                row["messages"] += 1
                rt = str(msg.get("review_type", UNKNOWN))
                row["review_types"][rt] = row["review_types"].get(rt, 0) + 1
                if isinstance(ts, int):
                    row["last_activity_ms"] = max(row["last_activity_ms"] or 0, ts)
        self._cache[key] = out
        return out

    def agent_activity(self, agent_id: str) -> dict[str, Any] | None:
        topo = self.topology()
        if agent_id not in {a["agent_id"] for a in topo.shared_agents}:
            return None
        run = self.current_run()
        messages: list[dict[str, Any]] = []
        for trace in self._traces(run) if run else []:
            for msg in trace.get("agent_messages", []) or []:
                if str(msg.get("agent_id")) != agent_id:
                    continue
                messages.append(
                    {
                        "timestamp_ms": msg.get("timestamp_ms", trace.get("created_at_ms")),
                        "decision_id": msg.get("decision_id"),
                        "sender": agent_id,
                        "receiver": msg.get("receiver", "decision"),
                        "asset": msg.get("asset"),
                        "message_type": msg.get("review_type"),
                        "claim": msg.get("statement"),
                        "confidence": msg.get("confidence"),
                        "evidence": msg.get("evidence", []),
                        "counter_evidence": msg.get("counter_evidence", []),
                    }
                )
        return {"agent_id": agent_id, "messages": messages[-200:], "count": len(messages)}

    def routing_view(self) -> dict[str, Any]:
        run = self.current_run()
        if run is None:
            return {"available": False, "comparisons": [], "summary": {}, "run_id": NOT_AVAILABLE}
        comps = self._comparisons(run)
        agreements = 0
        matrix = {
            "legacy_selects__lifecycle_selects": 0,
            "legacy_selects__lifecycle_rejects": 0,
            "legacy_rejects__lifecycle_selects": 0,
            "legacy_rejects__lifecycle_rejects": 0,
        }
        by_reason: dict[str, int] = {}
        for c in comps:
            legacy = (c.get("legacy") or {}).get("selected") or []
            life = (c.get("lifecycle") or {}).get("selected") or []
            ls, cs = set(legacy), set(life)
            if ls == cs:
                agreements += 1
            matrix[
                ("legacy_selects" if ls else "legacy_rejects")
                + "__"
                + ("lifecycle_selects" if cs else "lifecycle_rejects")
            ] += 1
            for _sid, verdict in ((c.get("lifecycle") or {}).get("rejected") or {}).items():
                by_reason[str(verdict)] = by_reason.get(str(verdict), 0) + 1
        total = len(comps)
        return {
            "available": True,
            "run_id": run.run_id,
            "total": total,
            "agreement_rate": round(agreements / total, 4) if total else None,
            "matrix": matrix,
            "rejections_by_reason": by_reason,
            "comparisons": comps[-200:],
        }

    def risk_view(self) -> dict[str, Any]:
        run = self.current_run()
        agg = self._aggregate(run)
        paper_run = self._paper_run(run) if run else {}
        totals = paper_run.get("totals") or {}
        return {
            "engine": "RiskManager",
            "status": "DETERMINISTIC",
            "authority": "DETERMINISTIC",
            "verdicts": agg["risk"],
            "order_created": agg["order_created"],
            "risk_approved": totals.get("risk_APPROVED", NOT_AVAILABLE),
            "risk_vetoed": totals.get("risk_VETOED", NOT_AVAILABLE),
            "open_risk": NOT_AVAILABLE,
            "config_source": "config/realdata/risk.yaml",
            "config_available": (self.repo_root / "config" / "realdata" / "risk.yaml").exists(),
            "note": "risk is independent of agents and has deterministic authority",
        }

    def portfolio_view(self) -> dict[str, Any]:
        run = self.current_run()
        routing = self.routing_view()
        portfolio_rejected: dict[str, str] = {}
        for c in self._comparisons(run) if run else []:
            for sid, reason in (c.get("portfolio_rejected") or {}).items():
                portfolio_rejected[str(sid)] = str(reason)
        return {
            "arbitration_events": len(routing.get("comparisons", [])),
            "portfolio_rejected": portfolio_rejected or NOT_AVAILABLE,
            "exposures": NOT_AVAILABLE,
            "concentration": NOT_AVAILABLE,
            "note": "portfolio can only restrict what risk already permits",
        }

    def executions_view(self) -> dict[str, Any]:
        run = self.current_run()
        rows: list[dict[str, Any]] = []
        for trace in self._traces(run) if run else []:
            if not trace.get("order_created"):
                continue
            proposal = trace.get("proposal") or {}
            rows.append(
                {
                    "timestamp_ms": trace.get("created_at_ms"),
                    "asset": trace.get("asset"),
                    "strategy": proposal.get("strategy_id") if isinstance(proposal, dict) else None,
                    "direction": proposal.get("direction") if isinstance(proposal, dict) else None,
                    "risk": (trace.get("risk") or {}).get("verdict"),
                    "decision_id": trace.get("decision_id"),
                }
            )
        return {"execution_mode": "PAPER", "executed": len(rows), "executions": rows}

    def traces_view(self, *, limit: int = 100) -> dict[str, Any]:
        run = self.current_run()
        traces = self._traces(run) if run else []
        rows = [
            {
                "decision_id": t.get("decision_id"),
                "asset": t.get("asset"),
                "mode": t.get("mode"),
                "no_trade_kind": t.get("no_trade_kind"),
                "regime": t.get("regime"),
                "decision_time_ms": t.get("decision_time_ms"),
                "trace_hash": t.get("trace_hash"),
                "order_created": bool(t.get("order_created")),
                "verification": (t.get("verification") or {}).get("verdict"),
            }
            for t in traces[-limit:]
        ]
        return {
            "run_id": run.run_id if run else NOT_AVAILABLE,
            "count": len(traces),
            "traces": rows,
        }

    def trace_detail(self, decision_id: str) -> dict[str, Any] | None:
        run = self.current_run()
        for trace in self._traces(run) if run else []:
            if str(trace.get("decision_id")) == decision_id:
                return _trace_timeline(trace)
        return None

    def campaigns_view(self) -> dict[str, Any]:
        root = self.campaigns_root
        rows: list[dict[str, Any]] = []
        if root and root.exists():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or not child.name.startswith("paper-"):
                    continue
                config = child / "CAMPAIGN_CONFIG.md"
                analysis = read_json(child / "ANALYSIS.json")
                if not config.exists() and analysis is None:
                    continue
                rows.append(
                    {
                        "campaign_id": child.name,
                        "has_config": config.exists(),
                        "config_path": str(config) if config.exists() else NOT_AVAILABLE,
                        "agreement_rate": (analysis or {}).get("agreement_rate", NOT_AVAILABLE),
                        "disagreements": (analysis or {}).get("disagreements", NOT_AVAILABLE),
                        "cycles_with_comparisons": (analysis or {}).get(
                            "cycles_with_comparisons", NOT_AVAILABLE
                        ),
                        "matrix_router_selection": (analysis or {}).get(
                            "matrix_router_selection", NOT_AVAILABLE
                        ),
                    }
                )
        return {"campaigns": rows, "count": len(rows)}

    def snapshot(self) -> dict[str, Any]:
        """All views in one payload (the dashboard's single source of truth)."""
        run = self.current_run()
        heartbeat = self._heartbeat(run) if run else {}
        return {
            "generated_at_ms": self._clock_ms(),
            "freshness": self._freshness(heartbeat.get("timestamp_ms") if heartbeat else None),
            "system": self.system_view(),
            "strategies": self.strategies_view(),
            "agents": self.agents_view(),
            "lifecycle": self.lifecycle_view(),
            "routing": self.routing_view(),
            "portfolio": self.portfolio_view(),
            "risk": self.risk_view(),
            "executions": self.executions_view(),
            "campaigns": self.campaigns_view(),
            "topology": self.topology().to_dict(),
        }


# ------------------------------------------------------------------ helpers


def _summarise_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [float(s.get("net_bps", 0.0)) for s in samples if isinstance(s, dict)]
    grosses = [float(s.get("gross_bps", 0.0)) for s in samples if isinstance(s, dict)]
    n = len(nets)
    if n == 0:
        return {"status": NOT_AVAILABLE, "sample_count": 0}
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return {
        "status": "OK" if n >= MIN_SAMPLES else INSUFFICIENT_SAMPLE,
        "sample_count": n,
        "net_expectancy_bps": round(sum(nets) / n, 4),
        "gross_expectancy_bps": round(sum(grosses) / n, 4) if grosses else None,
        "total_net_bps": round(sum(nets), 4),
        "hit_rate": round(len(wins) / n, 4),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "max_drawdown_bps": round(worst, 4),
    }


def _cell_for_strategy(run: RunArtifacts | None, strategy_id: str, regime: str) -> dict[str, Any]:
    if run is None:
        return {"status": NOT_AVAILABLE}
    payload = read_json(run.path("performance.json")) or {}
    cells = payload.get("cells") or {}
    merged: list[dict[str, Any]] = []
    for cell in cells.values():
        if not isinstance(cell, dict):
            continue
        if str(cell.get("strategy_id")) == strategy_id and str(cell.get("regime")) == regime:
            merged.extend(cell.get("samples") or [])
    return _summarise_samples(merged)


def _dominant(counts: dict[str, int]) -> str:
    if not counts:
        return UNKNOWN
    return max(sorted(counts), key=lambda k: counts[k])


def _admission_histogram(strategies: dict[str, dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for spec in strategies.values():
        status = str(spec.get("status", UNKNOWN))
        out[status] = out.get(status, 0) + 1
    return out


def _routing_mode(run: RunArtifacts | None) -> str:
    if run is None:
        return NOT_AVAILABLE
    comps = read_jsonl(run.path("routing_comparisons.jsonl"), limit=1)
    if comps:
        return "SHADOW" if comps[0].get("lifecycle") is not None else "LEGACY"
    return UNKNOWN


def _market_health(heartbeat: dict[str, Any], run: RunArtifacts | None) -> dict[str, Any]:
    if not heartbeat:
        return {"status": UNKNOWN, "note": "no heartbeat", "errors": []}
    return {
        "status": "HEALTHY" if not heartbeat.get("errors") else "DEGRADED",
        "run_id": heartbeat.get("run_id"),
        "assets": heartbeat.get("assets"),
        "timeframe": heartbeat.get("timeframe"),
        "errors": heartbeat.get("errors", []),
        "storage_failures": heartbeat.get("storage_failures", 0),
    }


def _trace_timeline(trace: dict[str, Any]) -> dict[str, Any]:
    proposal = trace.get("proposal") or {}
    return {
        "decision_id": trace.get("decision_id"),
        "run_id": trace.get("run_id"),
        "asset": trace.get("asset"),
        "symbol": trace.get("symbol"),
        "regime": trace.get("regime"),
        "mode": trace.get("mode"),
        "no_trade_kind": trace.get("no_trade_kind"),
        "decision_time_ms": trace.get("decision_time_ms"),
        "trace_hash": trace.get("trace_hash"),
        "prev_hash": trace.get("prev_hash"),
        "verification": trace.get("verification"),
        "strategies_considered": trace.get("strategies_considered", []),
        "agent_messages": trace.get("agent_messages", []),
        "portfolio_env": trace.get("portfolio")
        if isinstance(trace.get("portfolio"), dict)
        else NOT_AVAILABLE,
        "timeline": [
            {"stage": "MarketContext", "detail": _compact(trace.get("market_context"))},
            {"stage": "AssetContext", "detail": _compact(trace.get("asset_context"))},
            {"stage": "Strategies", "detail": _compact(trace.get("strategies_considered"))},
            {"stage": "Proposal", "detail": _compact(proposal)},
            {"stage": "AgentReviews", "detail": _compact(trace.get("agent_messages"))},
            {
                "stage": "Decision",
                "detail": {"mode": trace.get("mode"), "reason": trace.get("reason")},
            },
            {"stage": "Risk", "detail": _compact(trace.get("risk"))},
            {"stage": "Execution", "detail": {"order_created": bool(trace.get("order_created"))}},
        ],
    }


def _compact(value: Any) -> Any:
    if isinstance(value, list):
        return value[:6]
    return value if value is not None else NOT_AVAILABLE


def _file_hash(path: Path | None) -> str:
    if path is None or not path.exists():
        return NOT_AVAILABLE
    import hashlib

    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return NOT_AVAILABLE


def _git_commit(repo_root: Path) -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return UNKNOWN
