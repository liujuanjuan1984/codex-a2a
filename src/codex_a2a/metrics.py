from __future__ import annotations

from threading import Lock

A2A_STREAM_REQUESTS_TOTAL = "a2a_stream_requests_total"
A2A_STREAM_ACTIVE = "a2a_stream_active"
CODEX_STREAM_RETRIES_TOTAL = "codex_stream_retries_total"
TOOL_CALL_CHUNKS_EMITTED_TOTAL = "tool_call_chunks_emitted_total"
INTERRUPT_REQUESTS_TOTAL = "interrupt_requests_total"
INTERRUPT_RESOLVED_TOTAL = "interrupt_resolved_total"
A2A_REQUEST_BODY_REJECTED_TOTAL = "a2a_request_body_rejected_total"
A2A_OPERATION_REJECTED_TOTAL = "a2a_operation_rejected_total"
A2A_OPERATION_ACTIVE = "a2a_operation_active"
A2A_RATE_LIMIT_REJECTED_TOTAL = "a2a_rate_limit_rejected_total"
A2A_STREAM_BUDGET_REJECTED_TOTAL = "a2a_stream_budget_rejected_total"

_COUNTER_NAMES = (
    A2A_STREAM_REQUESTS_TOTAL,
    CODEX_STREAM_RETRIES_TOTAL,
    TOOL_CALL_CHUNKS_EMITTED_TOTAL,
    INTERRUPT_REQUESTS_TOTAL,
    INTERRUPT_RESOLVED_TOTAL,
    A2A_REQUEST_BODY_REJECTED_TOTAL,
    A2A_OPERATION_REJECTED_TOTAL,
    A2A_RATE_LIMIT_REJECTED_TOTAL,
    A2A_STREAM_BUDGET_REJECTED_TOTAL,
)
_GAUGE_NAMES = (A2A_STREAM_ACTIVE, A2A_OPERATION_ACTIVE)
_METRIC_HELP = {
    A2A_STREAM_REQUESTS_TOTAL: "Total A2A streaming requests started.",
    A2A_STREAM_ACTIVE: "Current active A2A streaming requests.",
    CODEX_STREAM_RETRIES_TOTAL: "Total Codex stream retry attempts.",
    TOOL_CALL_CHUNKS_EMITTED_TOTAL: "Total tool call chunks emitted.",
    INTERRUPT_REQUESTS_TOTAL: "Total interrupt requests received.",
    INTERRUPT_RESOLVED_TOTAL: "Total interrupt requests resolved.",
    A2A_REQUEST_BODY_REJECTED_TOTAL: "Total requests rejected by the body size limit.",
    A2A_OPERATION_REJECTED_TOTAL: "Total requests rejected by operation capacity.",
    A2A_OPERATION_ACTIVE: "Current operations admitted by the capacity limit.",
    A2A_RATE_LIMIT_REJECTED_TOTAL: "Total requests rejected by the sliding-window rate limit.",
    A2A_STREAM_BUDGET_REJECTED_TOTAL: "Total streaming responses rejected by output budgets.",
}


class InMemoryMetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters = {name: 0 for name in _COUNTER_NAMES}
        self._gauges = {name: 0 for name in _GAUGE_NAMES}

    def inc_counter(self, name: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def inc_gauge(self, name: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        with self._lock:
            self._gauges[name] = self._gauges.get(name, 0) + amount

    def dec_gauge(self, name: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        with self._lock:
            current = self._gauges.get(name, 0)
            self._gauges[name] = max(0, current - amount)

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters = {name: 0 for name in _COUNTER_NAMES}
            self._gauges = {name: 0 for name in _GAUGE_NAMES}

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        lines: list[str] = []
        for metric_type, values in (
            ("counter", snapshot["counters"]),
            ("gauge", snapshot["gauges"]),
        ):
            for name, value in values.items():
                lines.extend(
                    (
                        f"# HELP {name} {_METRIC_HELP[name]}",
                        f"# TYPE {name} {metric_type}",
                        f"{name} {value}",
                    )
                )
        return "\n".join(lines) + "\n"


_registry = InMemoryMetricsRegistry()


def get_metrics_registry() -> InMemoryMetricsRegistry:
    return _registry
