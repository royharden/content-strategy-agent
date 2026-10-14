"""Domain-neutral resolver seam. No concrete resolver, cache, action or IO is provided."""

from typing import Protocol, TypeVar

from .models import EvidenceKey

EvidenceT = TypeVar("EvidenceT", covariant=True)


class EvidenceResolver(Protocol[EvidenceT]):
    def resolve(self, key: EvidenceKey) -> EvidenceT | None:
        """Resolve within a domain's trusted generation/scope; absence remains explicit."""
        ...
