"""medRxiv query builder."""

from __future__ import annotations

from findpapers.query.builders.rxiv import RxivQueryBuilder


class MedrxivQueryBuilder(RxivQueryBuilder):
    """Build medRxiv-compatible query payloads."""
