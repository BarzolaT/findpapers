from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Any

from ..utils.version import package_version
from .paper import Paper


class Database(StrEnum):
    """Supported academic database identifiers.

    As a :class:`StrEnum`, each member compares equal to its string value,
    so code such as ``database == "arxiv"`` works without modification.
    """

    ARXIV = "arxiv"
    """arXiv preprint server."""

    IEEE = "ieee"
    """IEEE Xplore digital library."""

    OPENALEX = "openalex"
    """OpenAlex open scholarly graph."""

    PUBMED = "pubmed"
    """PubMed biomedical literature database."""

    SCOPUS = "scopus"
    """Elsevier Scopus abstract and citation database."""

    SEMANTIC_SCHOLAR = "semantic_scholar"
    """Semantic Scholar AI-powered research database."""


class SearchResult:
    """Represents a search configuration and results."""

    def __init__(
        self,
        query: str,
        since: datetime.date | None = None,
        until: datetime.date | None = None,
        max_papers_per_database: int | None = None,
        processed_at: datetime.datetime | None = None,
        databases: list[str] | None = None,
        papers: list[Paper] | None = None,
        runtime_seconds: float | None = None,
        runtime_seconds_per_database: dict[str, float] | None = None,
    ) -> None:
        """Create a SearchResult instance.

        Parameters
        ----------
        query : str
            Search query.
        since : datetime.date | None
            Lower bound date.
        until : datetime.date | None
            Upper bound date.
        max_papers_per_database : int | None
            Maximum papers per database.
        processed_at : datetime.datetime | None
            Processing timestamp.
        databases : list[str] | None
            Database identifiers.
        papers : list[Paper] | None
            Initial papers.
        runtime_seconds : float | None
            Total runtime of the search pipeline.
        runtime_seconds_per_database : dict[str, float] | None
            Runtime in seconds for each database.
        """
        self.query = query
        self.since = since
        self.until = until
        self.max_papers_per_database = max_papers_per_database
        processed_at = (
            processed_at if processed_at is not None else datetime.datetime.now(datetime.UTC)
        )
        if processed_at.tzinfo is None:
            processed_at = processed_at.replace(tzinfo=datetime.UTC)
        self.processed_at = processed_at
        self.databases = databases
        self.papers: list[Paper] = papers or []
        self.runtime_seconds = runtime_seconds
        self.runtime_seconds_per_database: dict[str, float] = dict(
            runtime_seconds_per_database or {}
        )

    def add_paper(self, paper: Paper) -> None:
        """Add a paper to the results.

        Parameters
        ----------
        paper : Paper
            Paper to add.
        """
        self.papers.append(paper)

    def remove_paper(self, paper: Paper) -> None:
        """Remove a paper from results.

        Parameters
        ----------
        paper : Paper
            Paper to remove.
        """
        if paper in self.papers:
            self.papers.remove(paper)

    def to_dict(self) -> dict[str, Any]:
        """Serialize search to a dictionary representation.

        Returns
        -------
        dict[str, Any]
            Dictionary representation of the search.
        """
        metadata = {
            "query": self.query,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "databases": self.databases,
            "max_papers_per_database": self.max_papers_per_database,
            "timestamp": self.processed_at.astimezone(datetime.UTC).isoformat(),
            "version": package_version(),
            "runtime_seconds": self.runtime_seconds,
            "runtime_seconds_per_database": dict(self.runtime_seconds_per_database),
        }
        return {
            "metadata": metadata,
            "papers": [paper.to_dict() for paper in self.papers],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SearchResult":
        """Reconstruct a SearchResult from a dictionary.

        Accepts the format produced by :meth:`to_dict` (and by
        :func:`~findpapers.utils.export.export_to_json`).

        Parameters
        ----------
        data : dict
            Dictionary with ``"metadata"`` and ``"papers"`` keys.

        Returns
        -------
        SearchResult
            Reconstructed instance.
        """
        metadata = data.get("metadata", {})
        raw_papers = data.get("papers", [])

        processed_at: datetime.datetime | None = None
        ts = metadata.get("timestamp")
        if isinstance(ts, str):
            try:
                processed_at = datetime.datetime.fromisoformat(ts)
            except ValueError:
                pass

        since: datetime.date | None = None
        since_str = metadata.get("since")
        if isinstance(since_str, str):
            try:
                since = datetime.date.fromisoformat(since_str)
            except ValueError:
                pass

        until: datetime.date | None = None
        until_str = metadata.get("until")
        if isinstance(until_str, str):
            try:
                until = datetime.date.fromisoformat(until_str)
            except ValueError:
                pass

        return cls(
            query=metadata.get("query", ""),
            since=since,
            until=until,
            databases=metadata.get("databases"),
            max_papers_per_database=metadata.get("max_papers_per_database"),
            processed_at=processed_at,
            papers=[Paper.from_dict(p) for p in raw_papers],
            runtime_seconds=metadata.get("runtime_seconds"),
            runtime_seconds_per_database=metadata.get("runtime_seconds_per_database"),
        )
