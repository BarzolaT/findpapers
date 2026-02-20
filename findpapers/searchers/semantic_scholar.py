"""Semantic Scholar searcher implementation."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import Query
from findpapers.core.search import Database
from findpapers.core.source import Source
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BULK_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_PAGE_SIZE = 100  # Semantic Scholar max per request

# Rate limits: 1000 req/s without key (shared among all unauthenticated users),
# 1 req/s with key (introductory; can be increased upon request)
_MIN_REQUEST_INTERVAL_DEFAULT = 1.1  # conservative for shared pool
_MIN_REQUEST_INTERVAL_WITH_KEY = 1.1  # respects 1 RPS introductory limit

# Fields to retrieve in each paper record
_PAPER_FIELDS = (
    "paperId,externalIds,title,abstract,authors,year,publicationDate,"
    "journal,venue,citationCount,openAccessPdf,url,fieldsOfStudy,publicationTypes"
)


def _semantic_scholar_types_to_paper_type(
    publication_types: Optional[list],
) -> Optional[PaperType]:
    """Map a Semantic Scholar ``publicationTypes`` list to a :class:`PaperType`.

    The function applies a priority order so the most specific type wins when
    multiple labels are present.

    Parameters
    ----------
    publication_types : list | None
        List of publication type strings from the Semantic Scholar API.

    Returns
    -------
    PaperType | None
        Matching paper type, or ``None`` when the list is empty / unmappable.
    """
    if not publication_types:
        return None

    # Normalise to lower-case for comparison.
    types_lower = {t.lower() for t in publication_types if isinstance(t, str)}

    # Priority: specific academic entry types first.
    if "thesis" in types_lower:
        return PaperType.PHDTHESIS
    if "booksection" in types_lower:
        return PaperType.INCOLLECTION
    if "book" in types_lower:
        return PaperType.INBOOK
    if "conference" in types_lower:
        return PaperType.INPROCEEDINGS
    if "journalarticle" in types_lower:
        return PaperType.ARTICLE
    if types_lower & {"review", "clinicaltrial", "lettersandcomments"}:
        return PaperType.ARTICLE
    return None


class SemanticScholarSearcher(SearcherBase):
    """Searcher for the Semantic Scholar research corpus.

    Uses the Bulk Search endpoint:
    https://api.semanticscholar.org/api-docs/#tag/Paper-Data/operation/bulk_paper_search

    Rate limits:
    - Without API key: up to 1000 req/s (shared among all unauthenticated users)
    - With API key: 1 req/s (introductory; can be increased upon request)
    """

    def __init__(
        self,
        query_builder: Optional[SemanticScholarQueryBuilder] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Create a Semantic Scholar searcher.

        Parameters
        ----------
        query_builder : SemanticScholarQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`SemanticScholarQueryBuilder` is created automatically.
        api_key : str | None
            Semantic Scholar API key (optional; provides a dedicated 1 RPS quota,
            decoupled from the shared unauthenticated pool, and can be increased
            upon request).
        """
        self._query_builder: SemanticScholarQueryBuilder = (
            query_builder or SemanticScholarQueryBuilder()
        )
        self._api_key = api_key
        self._request_interval = (
            _MIN_REQUEST_INTERVAL_WITH_KEY if api_key else _MIN_REQUEST_INTERVAL_DEFAULT
        )

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return Database.SEMANTIC_SCHOLAR.value

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the Semantic Scholar query builder.

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
            Interval in seconds (varies with API key).
        """
        return self._request_interval

    def _prepare_headers(self, headers: dict) -> dict:
        """Inject the Semantic Scholar API key header when configured.

        Parameters
        ----------
        headers : dict
            Raw HTTP headers.

        Returns
        -------
        dict
            Headers with ``x-api-key`` added when a key is set.
        """
        if self._api_key:
            return {**headers, "x-api-key": self._api_key}
        return headers

    def _parse_paper(self, item: Dict[str, Any]) -> Optional[Paper]:
        """Parse a single Semantic Scholar paper record.

        Parameters
        ----------
        item : dict
            Paper metadata dictionary from Semantic Scholar API.

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
        for author_entry in item.get("authors", []):
            name = (author_entry.get("name") or "").strip()
            if name:
                authors.append(name)

        # Publication date
        pub_date: Optional[datetime.date] = None
        _pub_date_str = (item.get("publicationDate") or "").strip()
        if _pub_date_str:
            try:
                pub_date = datetime.date.fromisoformat(_pub_date_str[:10])
            except ValueError:
                pass
        if pub_date is None and item.get("year"):
            try:
                pub_date = datetime.date(int(item["year"]), 1, 1)
            except (ValueError, TypeError):
                pass

        # External IDs → DOI
        external_ids = item.get("externalIds") or {}
        doi: Optional[str] = (external_ids.get("DOI") or "").strip() or None

        # URL
        url: Optional[str] = (item.get("url") or "").strip() or None

        # PDF URL
        pdf_url: Optional[str] = None
        open_access_pdf = item.get("openAccessPdf")
        if isinstance(open_access_pdf, dict):
            pdf_url = (open_access_pdf.get("url") or "").strip() or None

        # Citations
        citations: Optional[int] = item.get("citationCount")

        # Keywords from fields of study
        keywords: set[str] = set()
        for field in item.get("fieldsOfStudy") or []:
            if isinstance(field, str) and field.strip():
                keywords.add(field.strip())

        # Publication
        source: Optional[Source] = None
        journal = item.get("journal") or {}
        venue = (item.get("venue") or "").strip()
        pub_title = (journal.get("name") or venue or "").strip()
        if pub_title:
            source = Source(title=pub_title)

        # Pages from journal info
        pages: Optional[str] = None
        if journal:
            raw_pages = (journal.get("pages") or "").strip()
            if raw_pages:
                pages = raw_pages

        # Paper type from publicationTypes list
        paper_type = _semantic_scholar_types_to_paper_type(item.get("publicationTypes"))

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
        """Fetch papers from Semantic Scholar bulk search with pagination.

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
        ss_params = self._query_builder.convert_query(query)
        papers: List[Paper] = []
        token: Optional[str] = None  # Semantic Scholar uses token-based pagination
        total: Optional[int] = None

        while True:
            remaining = (max_papers - len(papers)) if max_papers is not None else _PAGE_SIZE
            page_size = min(_PAGE_SIZE, remaining)

            params: dict = {
                **ss_params,
                "fields": _PAPER_FIELDS,
                "limit": page_size,
                "sort": "publicationDate:desc",
            }
            if token:
                params["token"] = token

            try:
                response = self._get(_BULK_SEARCH_URL, params)
            except Exception:
                logger.exception("Semantic Scholar request failed (token=%s).", token)
                break

            data = response.json()
            if total is None:
                total = data.get("total")

            items = data.get("data") or []
            if not items:
                break

            for item in items:
                paper = self._parse_paper(item)
                if paper is not None:
                    papers.append(paper)

            if progress_callback is not None:
                progress_callback(len(papers), total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            token = data.get("token")
            if not token or len(items) < page_size:
                break

        return papers[:max_papers] if max_papers is not None else papers
