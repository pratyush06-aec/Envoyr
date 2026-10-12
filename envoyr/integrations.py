"""Ecosystem Integrations for Envoyr.

1. Neatlogs: Structured telemetry and operational event streaming.
2. CFO.ai: Unit economics model calculating execution costs and compute savings.
"""

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from envoyr.models import Task


@dataclass
class EconomicsReport:
    task_id: str
    duration_ms: int
    adapter: str
    estimated_cost_usd: float
    cost_saved_usd: float
    summary: str


class NeatlogsTracer:
    """Streams structured execution traces to neatlogs or writes to local audit log."""

    def __init__(self, api_key: str | None = None, endpoint: str | None = None):
        self.api_key = api_key or os.getenv("NEATLOGS_API_KEY")
        self.endpoint = endpoint or os.getenv("NEATLOGS_ENDPOINT")

    def record_event(self, event_type: str, task_id: str, data: dict[str, Any]) -> bool:
        """Emit a structured neatlogs trace event."""
        payload = {
            "source": "envoyr",
            "event": event_type,
            "task_id": task_id,
            "data": data,
        }

        if not self.endpoint or not self.api_key:
            # Graceful offline mode: no remote credentials configured
            return False

        try:
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status < 300
        except Exception:
            return False


class EconomicsCalculator:
    """Calculates unit compute economics and cost savings modeled after cfo.ai."""

    # Baseline cloud rate: ~$0.04/hour for a 2 vCPU / 4GB RAM remote Linux worker ($0.000011/sec)
    REMOTE_COMPUTE_RATE_PER_SEC = 0.000011

    # Alternative managed developer sandbox baseline: ~$0.15/hour ($0.000042/sec)
    MANAGED_CLOUD_BENCHMARK_RATE = 0.000042

    @classmethod
    def calculate_cost(cls, task: Task) -> EconomicsReport:
        total_duration_ms = sum(s.duration_ms for s in task.steps)
        duration_sec = total_duration_ms / 1000.0

        if task.adapter == "remote":
            compute_cost = duration_sec * cls.REMOTE_COMPUTE_RATE_PER_SEC
            benchmark_cost = duration_sec * cls.MANAGED_CLOUD_BENCHMARK_RATE
            savings = max(0.0, benchmark_cost - compute_cost)
        else:
            # Local / WSL runs on existing developer hardware (zero marginal cloud cost)
            compute_cost = 0.0
            benchmark_cost = duration_sec * cls.MANAGED_CLOUD_BENCHMARK_RATE
            savings = benchmark_cost

        summary = (
            f"Compute: ${compute_cost:.5f} | "
            f"Benchmark Baseline: ${benchmark_cost:.5f} | "
            f"Estimated Savings: ${savings:.5f}"
        )

        return EconomicsReport(
            task_id=task.id,
            duration_ms=total_duration_ms,
            adapter=task.adapter,
            estimated_cost_usd=compute_cost,
            cost_saved_usd=savings,
            summary=summary,
        )
