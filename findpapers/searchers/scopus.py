"""Scopus searcher implementation."""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Callable
from typing import Any, Dict, List, Optional

import requests

from findpapers.core.paper import Paper
from findpapers.core.publication import Publication
from findpapers.core.query import Query
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.scopus import ScopusQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.elsevier.com/content/search/scopus"
_PAGE_SIZE = 25  # Scopus max results per request (in standard view)
# Conservative interval — actual limit varies by institution
_MIN_REQUEST_INTERVAL = 0.5


class ScopusSearcher(SearcherBase):
    """Searcher for the Elsevier Scopus database.

    Requires a Scopus API key:
    https://dev.elsevier.com/sc_search_tips.html

    Rate limit: varies by institution (typically 2-9 req/s).
    """

    def __init__(
        self,
        query_builder: Optional[ScopusQueryBuilder] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Create a Scopus searcher.

        Parameters
        ----------
        query_builder : ScopusQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`ScopusQueryBuilder` is created automatically.
        api_key : str | None
            Elsevier API key (required for production use).
        """
        self._query_builder: ScopusQueryBuilder = query_builder or ScopusQueryBuilder()
        self._api_key = api_key
        self._last_request_time: float = 0.0

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return "Scopus"

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the Scopus query builder.

        Returns
        -------
        QueryBuilder
            The underlying builder instance.
        """
        return self._query_builder

    def _rate_limit(self) -> None:
        """Enforce minimum interval between HTTP requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    def _get(self, params: dict) -> requests.Response:
        """Perform a rate-limited GET request to the Scopus API.

        Parameters
        ----------
        params : dict
            Query parameters.

        Returns
        -------
        requests.Response
            HTTP response.

        Raises
        ------
        requests.HTTPError
            On non-2xx status codes.
        """
        self._rate_limit()
        headers = {
            "Accept": "application/json",
        }
        if self._api_key:
            headers["X-ELS-APIKey"] = self._api_key
        response = requests.get(_BASE_URL, params=params, headers=headers, timeout=30)
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_paper(entry: Dict[str, Any]) -> Optional[Paper]:
        """Parse a single Scopus search result entry.

        Parameters
        ----------
        entry : dict
            Entry dictionary from Scopus JSON response.

        Returns
        -------
        Paper | None
            Parsed paper or ``None`` when required fields are missing.
        """
        title = (entry.get("dc:title") or "").strip()
        if not title:
            return None

        abstract = (entry.get("dc:description") or entry.get("prism:teaser") or "").strip()

        # Authors — Scopus provides a string or list
        raw_creator = entry.get("dc:creator") or ""
        if isinstance(raw_creator, list):
            authors = [a.strip() for a in raw_creator if (a or "").strip()]
        elif raw_creator:
            authors = [raw_creator.strip()]
        else:
            authors = []

        # Publication date
        cover_date = (entry.get("prism:coverDate") or "").strip()
        pub_date: Optional[datetime.date] = None
        if cover_date:
            try:
                pub_date = datetime.date.fromisoformat(cover_date[:10])
            except ValueError:
                pass

        # DOI / URL
        doi: Optional[str] = (entry.get("prism:doi") or "").strip() or None
        url: Optional[str] = None
        for link_item in entry.get("link", []):
            if isinstance(link_item, dict) and link_item.get("@ref") == "scopus":
                url = (link_item.get("@href") or "").strip() or None
                break

        # Citations
        citations: Optional[int] = None
        cite_count = entry.get("citedby-count")
        if cite_count is not None:
            try:
                citations = int(cite_count)
            except (ValueError, TypeError):
                pass

        # Publication
        pub_title = (
            entry.get("prism:publicationName") or entry.get("prism:issueName") or ""
        ).strip()
        publication: Optional[Publication] = None
        if pub_title:
            issn = (entry.get("prism:issn") or entry.get("prism:eIssn") or "").strip() or None
            # prism:isbn may be a list of dicts in some responses
            raw_isbn = entry.get("prism:isbn")
            if isinstance(raw_isbn, list):
                isbn = raw_isbn[0].get("$", "").strip() if raw_isbn else None
            else:
                isbn = (raw_isbn or "").strip() or None
            publisher = (entry.get("dc:publisher") or "").strip() or None
            pub_type = (entry.get("prism:aggregationType") or "").strip() or None
            publication = Publication(
                title=pub_title,
                issn=issn,
                isbn=isbn,
                publisher=publisher,
                category=pub_type,
            )

        # Pages
        pages: Optional[str] = (entry.get("prism:pageRange") or "").strip() or None

        try:
            paper = Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                publication=publication,
                publication_date=pub_date,
                url=url,
                doi=doi,
                citations=citations,
                pages=pages,
                databases={"Scopus"},
            )
        except ValueError:
            return None

        return paper

    def _fetch_papers(
        self,
        query: Query,
        max_papers: Optional[int],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> List[Paper]:
        """Fetch papers from Scopus with pagination.

        Parameters
        ----------
        query : Query
            Validated query object.
        max_papers : int | None
            Maximum papers to retrieve.
        progress_callback : Callable[[int, int | None], None] | None
            Progress callback.

        Returns
        -------
        list[Paper]
            Retrieved papers.
        """
        scopus_query = self._query_builder.convert_query(query)
        papers: List[Paper] = []
        offset = 0
        total: Optional[int] = None

        while True:
            remaining = (max_papers - len(papers)) if max_papers is not None else _PAGE_SIZE
            page_size = min(_PAGE_SIZE, remaining)

            params = {
                "query": scopus_query,
                "start": offset,
                "count": page_size,
                "sort": "-coverDate",
                "view": "STANDARD",
            }

            try:
                response = self._get(params)
            except Exception:
                logger.exception("Scopus request failed (offset=%d).", offset)
                break

            data = response.json()
            search_results = data.get("search-results", {})

            if total is None:
                total_str = search_results.get("opensearch:totalResults", "0")
                try:
                    total = int(total_str)
                except (ValueError, TypeError):
                    total = None

            entries = search_results.get("entry", [])
            if not entries:
                break

            for entry in entries:
                paper = self._parse_paper(entry)
                if paper is not None:
                    papers.append(paper)

            if progress_callback is not None:
                progress_callback(len(papers), total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            if len(entries) < page_size:
                break

            offset += len(entries)

        return papers[:max_papers] if max_papers is not None else papers
