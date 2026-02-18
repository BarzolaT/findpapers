"""IEEE Xplore searcher implementation."""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Callable
from typing import Any, Dict, List, Optional

import requests

from findpapers.core.paper import Paper, PaperType
from findpapers.core.publication import Publication
from findpapers.core.query import Query
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.ieee import IEEEQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
_PAGE_SIZE = 200  # IEEE max per request
# 200 calls/day limit — use conservative interval
_MIN_REQUEST_INTERVAL = 0.5


def _ieee_content_type_to_paper_type(content_type: Optional[str]) -> Optional[PaperType]:
    """Map an IEEE ``content_type`` string to a :class:`PaperType`.

    Parameters
    ----------
    content_type : str | None
        Raw ``content_type`` value from the IEEE API.

    Returns
    -------
    PaperType | None
        Matching paper type, or ``None`` when the value cannot be mapped.
    """
    if not content_type:
        return None
    lowered = content_type.strip().lower()
    if lowered in {"journals", "early access articles"}:
        return PaperType.ARTICLE
    if lowered == "conferences":
        return PaperType.INPROCEEDINGS
    if lowered == "books":
        return PaperType.INCOLLECTION
    if lowered == "standards":
        return PaperType.TECHREPORT
    return None


class IEEESearcher(SearcherBase):
    """Searcher for the IEEE Xplore database.

    Requires an IEEE API key:
    https://developer.ieee.org/docs/read/Metadata_API_details

    Rate limit: up to 200 requests/day (conservative).
    """

    def __init__(
        self,
        query_builder: Optional[IEEEQueryBuilder] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Create an IEEE Xplore searcher.

        Parameters
        ----------
        query_builder : IEEEQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`IEEEQueryBuilder` is created automatically.
        api_key : str | None
            IEEE Xplore API key (required for production use).
        """
        self._query_builder: IEEEQueryBuilder = query_builder or IEEEQueryBuilder()
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
        return "IEEE"

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the IEEE query builder.

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
        """Perform a rate-limited GET request to the IEEE API.

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
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
            params = {**params, "apikey": self._api_key}
        response = requests.get(_BASE_URL, params=params, headers=headers, timeout=30)
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_paper(item: Dict[str, Any]) -> Optional[Paper]:
        """Parse a single IEEE API result item.

        Parameters
        ----------
        item : dict
            Article metadata dictionary from IEEE JSON response.

        Returns
        -------
        Paper | None
            Parsed paper or ``None`` when required fields are missing.
        """
        title = (item.get("title") or "").strip()
        if not title:
            return None

        abstract = (item.get("abstract") or "").strip()

        # Authors
        authors: list[str] = []
        for author_entry in item.get("authors", {}).get("authors", []):
            full_name = (author_entry.get("full_name") or "").strip()
            if full_name:
                authors.append(full_name)

        # Publication date
        pub_date: Optional[datetime.date] = None
        pub_year = item.get("publication_year")
        if pub_year:
            try:
                pub_date = datetime.date(int(pub_year), 1, 1)
            except (ValueError, TypeError):
                pass

        # DOI / URL
        doi: Optional[str] = (item.get("doi") or "").strip() or None
        url: Optional[str] = (item.get("html_url") or item.get("pdf_url") or "").strip() or None
        pdf_url: Optional[str] = (item.get("pdf_url") or "").strip() or None

        # Keywords
        keywords: set[str] = set()
        for kw_group in ["index_terms", "ieee_terms", "author_terms", "mesh_terms"]:
            for kw_el in item.get(kw_group, {}).get("terms", []):
                kw = kw_el.strip()
                if kw:
                    keywords.add(kw)

        # Citations
        citations: Optional[int] = None
        citation_count = item.get("citing_paper_count")
        if citation_count is not None:
            try:
                citations = int(citation_count)
            except (ValueError, TypeError):
                pass

        # Publication
        publication_title = (item.get("publication_title") or "").strip()
        publication: Optional[Publication] = None
        if publication_title:
            issn = (item.get("issn") or "").strip() or None
            isbn = (item.get("isbn") or "").strip() or None
            publisher = (item.get("publisher") or "").strip() or None
            publication = Publication(
                title=publication_title,
                issn=issn,
                isbn=isbn,
                publisher=publisher,
            )

        # Paper type derived from content_type
        paper_type = _ieee_content_type_to_paper_type(item.get("content_type"))

        # Pages
        start_page = item.get("start_page") or ""
        end_page = item.get("end_page") or ""
        pages: Optional[str] = None
        if start_page and end_page:
            pages = f"{start_page}-{end_page}"
        elif start_page:
            pages = str(start_page)

        try:
            paper = Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                publication=publication,
                publication_date=pub_date,
                url=url,
                pdf_url=pdf_url,
                doi=doi,
                citations=citations,
                keywords=keywords if keywords else None,
                pages=pages,
                databases={"IEEE"},
                paper_type=paper_type,
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
        """Fetch papers from IEEE Xplore with pagination.

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
        ieee_params = self._query_builder.convert_query(query)
        papers: List[Paper] = []
        offset = 1  # IEEE uses 1-based pagination
        total: Optional[int] = None

        while True:
            remaining = (max_papers - len(papers)) if max_papers is not None else _PAGE_SIZE
            page_size = min(_PAGE_SIZE, remaining)

            params = {
                **ieee_params,
                "start_record": offset,
                "max_records": page_size,
                "sort_field": "article_number",
                "sort_order": "desc",
            }

            try:
                response = self._get(params)
            except Exception:
                logger.exception("IEEE request failed (offset=%d).", offset)
                break

            data = response.json()
            total = data.get("total_records")

            articles = data.get("articles", [])
            if not articles:
                break

            for item in articles:
                paper = self._parse_paper(item)
                if paper is not None:
                    papers.append(paper)

            if progress_callback is not None:
                progress_callback(len(papers), total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            if len(articles) < page_size:
                break

            offset += len(articles)

        return papers[:max_papers] if max_papers is not None else papers
