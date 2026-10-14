"""App-specific current-snapshot adapter; the portable grounded module never imports it."""

from ..shared.grounded.models import EvidenceKey, Metric, MetricSnapshot


class MetricsResolver:
    def __init__(self, snapshot: MetricSnapshot):
        self.snapshot = MetricSnapshot.model_validate(snapshot.model_dump(mode="python"))
        self._metrics = {metric.metric_id: metric for metric in self.snapshot.metrics}

    def current_generation(self, scope: str) -> str | None:
        return (
            self.snapshot.snapshot_id
            if any(m.scope == scope for m in self._metrics.values())
            else None
        )

    def resolve(self, key: EvidenceKey) -> Metric | None:
        if key.generation != self.current_generation(key.scope):
            return None
        metric = self._metrics.get(key.evidence_id)
        return metric if metric is not None and metric.scope == key.scope else None
