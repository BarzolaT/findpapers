from __future__ import annotations

import datetime
from typing import List, Optional

from ..utils.export import export_to_bibtex, export_to_csv, export_to_json
from ..utils.version import package_version
from .paper import Paper


class Search:
    """Represents a search configuration and results."""

    def __init__(
        self,
        query: str,
        since: Optional[datetime.date] = None,
        until: Optional[datetime.date] = None,
        max_papers_per_database: Optional[int] = None,
        processed_at: Optional[datetime.datetime] = None,
        databases: Optional[List[str]] = None,
        paper_types: Optional[List[str]] = None,
        papers: Optional[List[Paper]] = None,
        runtime_seconds: Optional[float] = None,
        runtime_seconds_per_database: Optional[dict[str, float]] = None,
    ) -> None:
        """Create a Search instance.

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
        paper_types : list[str] | None
            Paper types filter (BibTeX-aligned, see :class:`PaperType`).
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
            processed_at
            if processed_at is not None
            else datetime.datetime.now(datetime.timezone.utc)
        )
        if processed_at.tzinfo is None:
            processed_at = processed_at.replace(tzinfo=datetime.timezone.utc)
        self.processed_at = processed_at
        self.databases = databases
        self.paper_types = paper_types
        self.papers: List[Paper] = papers or []
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

    def to_dict(self) -> dict[str, object]:
        """Serialize search to a dictionary representation.

        Returns
        -------
        dict[str, object]
            Dictionary representation of the search.
        """
        metadata = {
            "query": self.query,
            "databases": self.databases,
            "max_papers_per_database": self.max_papers_per_database,
            "timestamp": self.processed_at.astimezone(datetime.timezone.utc).isoformat(),
            "version": package_version(),
            "runtime_seconds": self.runtime_seconds,
            "runtime_seconds_per_database": dict(self.runtime_seconds_per_database),
        }
        return {
            "metadata": metadata,
            "papers": [Paper.to_dict(paper) for paper in self.papers],
        }

    def to_json(self, path: str) -> None:
        """Export search results to a JSON file.

        Parameters
        ----------
        path : str
            Output path for JSON export.

        Returns
        -------
        None
        """
        export_to_json(self, path)

    def to_csv(self, path: str) -> None:
        """Export search results to a CSV file.

        Parameters
        ----------
        path : str
            Output path for CSV export.

        Returns
        -------
        None
        """
        export_to_csv(self, path)

    def to_bibtex(self, path: str) -> None:
        """Export search results to a BibTeX file.

        Parameters
        ----------
        path : str
            Output path for BibTeX export.

        Returns
        -------
        None
        """
        export_to_bibtex(self, path)
