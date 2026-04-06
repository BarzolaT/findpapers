"""Search result container that aggregates papers from multiple databases."""

from __future__ import annotations

import contextlib
import datetime
from typing import Any

from findpapers.core.paper import Paper
from findpapers.utils.dedup import _are_years_compatible
from findpapers.utils.version import package_version


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
        failed_databases: list[str] | None = None,
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
        failed_databases : list[str] | None
            Database identifiers that failed during search (network error,
            connector error, etc.).  ``None`` means the information was not
            recorded (e.g. loaded from an older save).
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
        self.failed_databases: list[str] = list(failed_databases or [])

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
            "failed_databases": self.failed_databases,
        }
        return {
            "metadata": metadata,
            "papers": [paper.to_dict() for paper in self.papers],
        }

    @classmethod
    def from_dict(cls, data: dict) -> SearchResult:
        """Reconstruct a SearchResult from a dictionary.

        Accepts the format produced by :meth:`to_dict` (and by
        :func:`~findpapers.utils.persistence.save_to_json`).

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
            with contextlib.suppress(ValueError):
                processed_at = datetime.datetime.fromisoformat(ts)

        since: datetime.date | None = None
        since_str = metadata.get("since")
        if isinstance(since_str, str):
            with contextlib.suppress(ValueError):
                since = datetime.date.fromisoformat(since_str)

        until: datetime.date | None = None
        until_str = metadata.get("until")
        if isinstance(until_str, str):
            with contextlib.suppress(ValueError):
                until = datetime.date.fromisoformat(until_str)

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
            failed_databases=metadata.get("failed_databases"),
        )

    def _deduplicate_and_merge(self, metrics: dict[str, int | float]) -> None:
        """Collapse duplicate papers in two passes.

        **Pass 1** groups papers by their primary key (DOI when available,
        otherwise a normalised ``title|year`` string).  This resolves exact
        duplicates found within the same database or between databases that
        share the same DOI.

        **Pass 2** groups the results of pass 1 by normalised title and
        merges entries whose publication years are *compatible* — i.e. they
        share the same year, at least one has no year (incomplete metadata),
        or at least one entry carries a preprint DOI and their years differ by
        at most one (to handle both the case of the same preprint deposited to
        two servers across the Dec/Jan calendar boundary and the common
        preprint-to-published transition, e.g. Zenodo 2026 + book chapter
        2025).  Papers with the same title and *different known years* where
        neither is from a preprint server are intentionally kept separate.

        This correctly handles the common cross-database case where the same
        work is indexed with different DOIs (e.g. an arXiv preprint DOI vs a
        publisher DOI) and one of the database records lacks a publication
        date.

        When two papers are deemed duplicates their data is merged using
        :meth:`~findpapers.core.paper.Paper.merge` (most-complete strategy).

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict (currently unused; reserved for future statistics).

        Returns
        -------
        None
        """
        # Pass 1: primary key dedup (DOI > title|year > title).
        pass1: dict[str, Paper] = {}
        for paper in self.papers:
            key = self._dedupe_key(paper)
            if key in pass1:
                pass1[key].merge(paper)
            else:
                pass1[key] = paper

        # Pass 2: title-based dedup that handles missing year metadata.
        # Group survivors from pass 1 by normalised title, then within each
        # title group greedily merge papers whose years are compatible.
        by_title: dict[str, list[Paper]] = {}
        untitled: list[Paper] = []
        for paper in pass1.values():
            norm_title = paper.title.strip().lower() if paper.title else ""
            if norm_title:
                by_title.setdefault(norm_title, []).append(paper)
            else:
                untitled.append(paper)

        result: list[Paper] = list(untitled)
        for candidates in by_title.values():
            # Greedily merge into the first compatible representative.
            groups: list[Paper] = []
            for paper in candidates:
                paper_year = getattr(paper.publication_date, "year", None)
                merged_into: Paper | None = None
                for representative in groups:
                    rep_year = getattr(representative.publication_date, "year", None)
                    if _are_years_compatible(rep_year, paper_year, representative.doi, paper.doi):
                        merged_into = representative
                        break
                if merged_into is not None:
                    merged_into.merge(paper)
                else:
                    groups.append(paper)
            result.extend(groups)

        self.papers = result

    def _dedupe_key(
        self, paper: Paper
    ) -> str | None:  # TODO I think it should be a method of paper
        """Build a stable primary deduplication key for a paper.

        Uses the DOI when available; otherwise falls back to a normalised
        ``title|year`` combination.

        Parameters
        ----------
        paper : Paper
            Paper to key.

        Returns
        -------
        str
            Dedupe key string.
        """
        if paper.doi:
            return paper._identity_key()
        return paper._title_year_key()
