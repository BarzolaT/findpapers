"""IEEE Xplore searcher implementation."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import Query
from findpapers.core.search import Database
from findpapers.core.source import Source, SourceType
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.ieee import IEEEQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
_PAGE_SIZE = 200  # IEEE max per request
# 200 calls/day limit — use conservative interval
_MIN_REQUEST_INTERVAL = 0.5

# Mapping from IEEE content_type values to SourceType.
_IEEE_CONTENT_TYPE_MAP: dict[str, SourceType] = {
    "journals": SourceType.JOURNAL,
    "magazines": SourceType.JOURNAL,
    "conferences": SourceType.CONFERENCE,
    "books": SourceType.BOOK,
    "ebooks": SourceType.BOOK,
    "standards": SourceType.OTHER,
    "courses": SourceType.OTHER,
    "early access": SourceType.OTHER,
}


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

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return Database.IEEE.value

    @property
    def is_available(self) -> bool:
        """Return ``True`` only when an API key has been provided.

        IEEE Xplore requires an API key for production use.  Without one the
        searcher is considered unavailable and will be skipped by the runner.

        Returns
        -------
        bool
            ``True`` if an API key is set, ``False`` otherwise.
        """
        return self._api_key is not None

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the IEEE query builder.

        Returns
        -------
        QueryBuilder
            The underlying builder instance.
        """
        return self._query_builder

    @property
    def min_request_interval(self) -> float:
        """Return the minimum seconds between HTTP requests.

        Returns
        -------
        float
            Interval in seconds.
        """
        return _MIN_REQUEST_INTERVAL

    def _prepare_params(self, params: dict) -> dict:
        """Inject the IEEE API key into query parameters when configured.

        Parameters
        ----------
        params : dict
            Raw query parameters.

        Returns
        -------
        dict
            Parameters with ``apikey`` added when a key is set.
        """
        if self._api_key:
            return {**params, "apikey": self._api_key}
        return params

    def _prepare_headers(self, headers: dict) -> dict:
        """Inject the IEEE API key header when configured.

        Parameters
        ----------
        headers : dict
            Raw HTTP headers.

        Returns
        -------
        dict
            Headers with ``X-API-Key`` added when a key is set.
        """
        if self._api_key:
            return {**headers, "X-API-Key": self._api_key}
        return headers

    def _parse_paper(self, item: Dict[str, Any]) -> Optional[Paper]:
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
        authors: list[Author] = []
        for author_entry in item.get("authors", {}).get("authors", []):
            full_name = (author_entry.get("full_name") or "").strip()
            if full_name:
                affiliation = (author_entry.get("affiliation") or "").strip() or None
                authors.append(Author(name=full_name, affiliation=affiliation))

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

        # Keywords — ieee_terms, author_terms, etc. are nested inside index_terms
        keywords: set[str] = set()
        index_terms = item.get("index_terms", {})
        for kw_group in ["ieee_terms", "author_terms", "mesh_terms"]:
            for kw_el in index_terms.get(kw_group, {}).get("terms", []):
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

        # Source
        source_title = (item.get("publication_title") or "").strip()
        raw_content_type = (item.get("content_type") or "").strip().lower()
        source: Optional[Source] = None
        if source_title:
            issn = (item.get("issn") or "").strip() or None
            isbn = (item.get("isbn") or "").strip() or None
            publisher = (item.get("publisher") or "").strip() or None
            # Map content_type to SourceType.
            source_type = _IEEE_CONTENT_TYPE_MAP.get(raw_content_type)
            source = Source(
                title=source_title,
                issn=issn,
                isbn=isbn,
                publisher=publisher,
                source_type=source_type,
            )

        # Infer paper_type from content_type.
        _IEEE_PAPER_TYPE_MAP: dict[str, PaperType] = {
            "journals": PaperType.ARTICLE,
            "magazines": PaperType.ARTICLE,
            "conferences": PaperType.INPROCEEDINGS,
            "books": PaperType.INBOOK,
            "ebooks": PaperType.INBOOK,
            "standards": PaperType.TECHREPORT,
            "courses": PaperType.MISC,
            "early access": PaperType.ARTICLE,
        }
        paper_type = _IEEE_PAPER_TYPE_MAP.get(raw_content_type)

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
                source=source,
                publication_date=pub_date,
                url=url,
                pdf_url=pdf_url,
                doi=doi,
                citations=citations,
                keywords=keywords if keywords else None,
                pages=pages,
                databases={self.name},
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
        processed = 0
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
                response = self._get(_BASE_URL, params)
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

            processed += len(articles)
            if progress_callback is not None:
                progress_callback(processed, total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            if len(articles) < page_size:
                break

            offset += len(articles)

        return papers[:max_papers] if max_papers is not None else papers
