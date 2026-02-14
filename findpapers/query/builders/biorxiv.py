"""bioRxiv query builder."""

from __future__ import annotations

from findpapers.query.builders.rxiv import RxivQueryBuilder


class BiorxivQueryBuilder(RxivQueryBuilder):
    """Build bioRxiv-compatible query payloads."""
