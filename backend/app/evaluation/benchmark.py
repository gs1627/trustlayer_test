"""Run deterministic Trust Engine scenarios and report outcomes/latency."""
from __future__ import annotations

from collections import Counter
from statistics import mean
from time import perf_counter
from typing import Any, Sequence

from app.evaluation.test_scenarios import SCENARIOS
from app.services.trust_engine import TrustEngine


def benchmark_trust_engine(scenarios: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    test_cases = list(scenarios if scenarios is not None else SCENARIOS)
    if not test_cases:
        raise ValueError("At least one scenario is required")

    engine = TrustEngine()
    rows: list[dict[str, Any]] = []
    durations_ms: list[float] = []
    counts: Counter[str] = Counter()

    for scenario in test_cases:
        started = perf_counter()
        decision = engine.evaluate(scenario["evidence"])
        duration_ms = (perf_counter() - started) * 1000.0
        durations_ms.append(duration_ms)
        counts[decision.decision] += 1
        rows.append(
            {
                "scenario": scenario.get("name", scenario["call_id"]),
                "decision": decision.decision,
                "risk_level": decision.risk_level,
                "transaction_approval_required": decision.transaction_approval_required,
                "reasons": decision.reasons,
                "latency_ms": round(duration_ms, 3),
            }
        )

    return {
        "scenario_count": len(rows),
        "mean_latency_ms": round(mean(durations_ms), 3),
        "max_latency_ms": round(max(durations_ms), 3),
        "decision_counts": dict(counts),
        "results": rows,
        "note": "Synthetic deterministic scenarios only; these are not real-world accuracy metrics.",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(benchmark_trust_engine(), indent=2))
