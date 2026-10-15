"""Explicit local review boundary; importing this package opens no database or listener."""

from .service import LocalReviewService, Selection

__all__ = ["LocalReviewService", "Selection"]
