"""arXiv searcher implementation."""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Callable
from typing import List, Optional
from xml.etree import ElementTree as ET

import requests

from findpapers.core.paper import Paper
from findpapers.core.publication import Publication
from findpapers.core.query import Query
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.arxiv import ArxivQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BASE_URL = "http://export.arxiv.org/api/query"
_PAGE_SIZE = 100
# arXiv recommends at least 3 seconds between requests
_MIN_REQUEST_INTERVAL = 3.0
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivSearcher(SearcherBase):
    """Searcher for the arXiv preprint database.

    Uses the arXiv Atom Feed API:
    https://info.arxiv.org/help/api/user-manual.html

    Rate limit: 3 seconds between requests (as recommended by arXiv).
    """

    def __init__(self, query_builder: Optional[ArxivQueryBuilder] = None) -> None:
        """Create an arXiv searcher.

        Parameters
        ----------
        query_builder : ArxivQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`ArxivQueryBuilder` is created automatically.
        """
        self._query_builder: ArxivQueryBuilder = query_builder or ArxivQueryBuilder()
        self._last_request_time: float = 0.0

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return "arXiv"

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the arXiv query builder.

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
        """Perform a rate-limited GET request to the arXiv API.

        Parameters
        ----------
        params : dict
            Query parameters.

        Returns
        -------
        requests.Response
            HTTP response object.

        Raises
        ------
        requests.HTTPError
            On non-2xx status codes.
        """
        self._rate_limit()
        response = requests.get(_BASE_URL, params=params, timeout=30)
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[str]:
        """Parse ISO-8601 date string to ``YYYY-MM-DD``.

        Parameters
        ----------
        date_str : str | None
            Raw date string from API.

        Returns
        -------
        str | None
            Formatted date or ``None`` when input is empty.
        """
        if not date_str:
            return None
        return date_str[:10]

    @staticmethod
    def _parse_paper(entry: ET.Element) -> Optional[Paper]:
        """Parse a single Atom entry element into a :class:`Paper`.

        Parameters
        ----------
        entry : ET.Element
            Atom entry XML element.

        Returns
        -------
        Paper | None
            Parsed paper or ``None`` when required fields are missing.
        """
        title_el = entry.find("atom:title", _NS)
        abstract_el = entry.find("atom:summary", _NS)
        if title_el is None or not (title_el.text or "").strip():
            return None

        title = (title_el.text or "").strip().replace("\n", " ")
        abstract = (
            (abstract_el.text or "").strip().replace("\n", " ") if abstract_el is not None else ""
        )

        # Authors
        authors = [
            (name_el.text or "").strip()
            for author_el in entry.findall("atom:author", _NS)
            for name_el in [author_el.find("atom:name", _NS)]
            if name_el is not None and (name_el.text or "").strip()
        ]

        # Published date
        published_el = entry.find("atom:published", _NS)
        pub_date_str = _parse_date_from_str(
            (published_el.text or "").strip() if published_el is not None else None
        )

        # DOI
        doi: Optional[str] = None
        doi_el = entry.find("arxiv:doi", _NS)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()

        # URL - prefer HTML link
        url: Optional[str] = None
        for link_el in entry.findall("atom:link", _NS):
            rel = link_el.get("rel", "")
            href = link_el.get("href", "")
            if rel == "alternate" and href:
                url = href
                break
        if url is None:
            id_el = entry.find("atom:id", _NS)
            if id_el is not None and id_el.text:
                url = id_el.text.strip()

        # PDF URL
        pdf_url: Optional[str] = None
        for link_el in entry.findall("atom:link", _NS):
            title_attr = link_el.get("title", "")
            href = link_el.get("href", "")
            if title_attr == "pdf" and href:
                pdf_url = href
                break

        # Journal ref → publication
        journal_ref_el = entry.find("arxiv:journal_ref", _NS)
        publication: Optional[Publication] = None
        if journal_ref_el is not None and journal_ref_el.text and journal_ref_el.text.strip():
            publication = Publication(title=journal_ref_el.text.strip())

        try:
            paper = Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                publication=publication,
                publication_date=pub_date_str,
                url=url,
                pdf_url=pdf_url,
                doi=doi,
                databases={"arXiv"},
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
        """Fetch papers from arXiv with pagination and rate limiting.

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
        arxiv_query = self._query_builder.convert_query(query)
        papers: List[Paper] = []
        offset = 0

        while True:
            remaining = (max_papers - len(papers)) if max_papers is not None else _PAGE_SIZE
            page_size = min(_PAGE_SIZE, remaining)

            params = {
                "search_query": arxiv_query,
                "start": offset,
                "max_results": page_size,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            try:
                response = self._get(params)
            except Exception:
                logger.exception("arXiv request failed (offset=%d).", offset)
                break

            tree = ET.fromstring(response.text)

            total_results_el = tree.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
            total: Optional[int] = None
            if total_results_el is not None and total_results_el.text:
                try:
                    total = int(total_results_el.text.strip())
                except ValueError:
                    pass

            entries = tree.findall("atom:entry", _NS)
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


def _parse_date_from_str(date_str: Optional[str]) -> Optional[datetime.date]:
    """Parse a date string into a :class:`datetime.date`.

    Parameters
    ----------
    date_str : str | None
        Raw date string (ISO-8601 or ``YYYY-MM-DD`` prefix).

    Returns
    -------
    datetime.date | None
        Parsed date or ``None`` when input is empty / unparseable.
    """
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str[:10])
    except ValueError:
        return None
