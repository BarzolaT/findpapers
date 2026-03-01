"""Semantic Scholar searcher implementation."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import Query
from findpapers.core.search_result import Database
from findpapers.core.source import Source, SourceType
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BULK_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_AUTHOR_BATCH_URL = "https://api.semanticscholar.org/graph/v1/author/batch"
_PAGE_SIZE = 100  # Semantic Scholar max per request
_AUTHOR_BATCH_SIZE = 1000  # Max authors per batch request

# Rate limits: 1000 req/s without key (shared among all unauthenticated users),
# 1 req/s with key (introductory; can be increased upon request)
_MIN_REQUEST_INTERVAL_DEFAULT = 1.1  # conservative for shared pool
_MIN_REQUEST_INTERVAL_WITH_KEY = 1.1  # respects 1 RPS introductory limit

# Fields to retrieve in each paper record
_PAPER_FIELDS = (
    "paperId,externalIds,title,abstract,authors,year,publicationDate,"
    "journal,venue,citationCount,openAccessPdf,url,fieldsOfStudy,"
    "publicationTypes,publicationVenue"
)

# Mapping from Semantic Scholar publicationVenue.type to SourceType.
_SS_VENUE_TYPE_MAP: dict[str, SourceType] = {
    "journal": SourceType.JOURNAL,
    "conference": SourceType.CONFERENCE,
    "book": SourceType.BOOK,
    "repository": SourceType.REPOSITORY,
}

# Mapping from publicationTypes list entries to SourceType (fallback).
_SS_PUB_TYPE_MAP: dict[str, SourceType] = {
    "JournalArticle": SourceType.JOURNAL,
    "Review": SourceType.JOURNAL,
    "Conference": SourceType.CONFERENCE,
    "Book": SourceType.BOOK,
    "BookSection": SourceType.BOOK,
}


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

        # Authors — affiliations are fetched in a batch request after the search.
        authors: list[Author] = []
        for author_entry in item.get("authors", []):
            name = (author_entry.get("name") or "").strip()
            if name:
                authors.append(Author(name=name))

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

        # External IDs → DOI.
        # Prefer the explicit DOI field; fall back to deriving a canonical
        # arXiv DOI (10.48550/arXiv.<id>) when only the ArXivId is available.
        external_ids = item.get("externalIds") or {}
        doi: Optional[str] = (external_ids.get("DOI") or "").strip() or None
        if doi is None:
            arxiv_id = (external_ids.get("ArXivId") or "").strip()
            if arxiv_id:
                doi = f"10.48550/arXiv.{arxiv_id}"

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

        # Source
        source: Optional[Source] = None
        journal = item.get("journal") or {}
        venue = (item.get("venue") or "").strip()
        pub_title = (journal.get("name") or venue or "").strip()

        # Determine source_type from publicationVenue.type (preferred),
        # falling back to publicationTypes list.
        source_type: Optional[SourceType] = None
        pub_venue = item.get("publicationVenue") or {}
        venue_type = (pub_venue.get("type") or "").strip().lower()
        if venue_type:
            source_type = _SS_VENUE_TYPE_MAP.get(venue_type)

        if source_type is None:
            pub_types = item.get("publicationTypes") or []
            for pt in pub_types:
                if isinstance(pt, str) and pt in _SS_PUB_TYPE_MAP:
                    source_type = _SS_PUB_TYPE_MAP[pt]
                    break

        if pub_title:
            source = Source(title=pub_title, source_type=source_type)
        elif venue:
            # Venue name present but not a formal journal — use as-is.
            source = Source(title=venue, source_type=source_type)

        # Pages from journal info
        pages: Optional[str] = None
        if journal:
            raw_pages = (journal.get("pages") or "").strip()
            if raw_pages:
                pages = raw_pages

        # Infer paper_type from publicationTypes list.
        # Full list from the Semantic Scholar API docs:
        # Review, JournalArticle, CaseReport, ClinicalTrial, Conference,
        # Dataset, Editorial, LettersAndComments, MetaAnalysis, News,
        # Study, Book, BookSection
        _SS_PAPER_TYPE_MAP: dict[str, PaperType] = {
            "JournalArticle": PaperType.ARTICLE,
            "Review": PaperType.ARTICLE,
            "CaseReport": PaperType.ARTICLE,
            "ClinicalTrial": PaperType.ARTICLE,
            "Editorial": PaperType.ARTICLE,
            "LettersAndComments": PaperType.ARTICLE,
            "MetaAnalysis": PaperType.ARTICLE,
            "Study": PaperType.ARTICLE,
            "Conference": PaperType.INPROCEEDINGS,
            "Book": PaperType.BOOK,
            "BookSection": PaperType.INBOOK,
            "Dataset": PaperType.MISC,
            "News": PaperType.MISC,
        }
        paper_type: PaperType | None = None
        pub_types = item.get("publicationTypes") or []
        for pt in pub_types:
            if isinstance(pt, str) and pt in _SS_PAPER_TYPE_MAP:
                paper_type = _SS_PAPER_TYPE_MAP[pt]
                break

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
                page_range=pages,
                databases={self.name},
                paper_type=paper_type,
            )
        except ValueError:
            return None

        return paper

    def _enrich_author_affiliations(
        self,
        author_id_to_authors: dict[str, list[Author]],
    ) -> None:
        """Batch-fetch affiliations from the Semantic Scholar Author API.

        Uses ``POST /author/batch?fields=affiliations`` to retrieve
        affiliation data for up to 1,000 authors per request, then
        updates the corresponding :class:`Author` objects in-place.

        Parameters
        ----------
        author_id_to_authors : dict[str, list[Author]]
            Mapping from Semantic Scholar author ID to :class:`Author`
            instances that share that ID across the retrieved papers.
        """
        all_ids = list(author_id_to_authors.keys())
        logger.info(
            "Fetching affiliations for %d unique authors from Semantic Scholar.",
            len(all_ids),
        )

        for start in range(0, len(all_ids), _AUTHOR_BATCH_SIZE):
            batch_ids = all_ids[start : start + _AUTHOR_BATCH_SIZE]
            try:
                response = self._post(
                    _AUTHOR_BATCH_URL,
                    json_body={"ids": batch_ids},
                    params={"fields": "affiliations"},
                )
            except Exception:
                logger.warning(
                    "Failed to fetch author affiliations batch (offset=%d).",
                    start,
                )
                continue

            results = response.json()
            for author_data in results:
                if not isinstance(author_data, dict):
                    continue
                author_id = author_data.get("authorId")
                affiliations = author_data.get("affiliations") or []
                if not author_id or not affiliations:
                    continue
                affiliation_str = "; ".join(affiliations)
                for author in author_id_to_authors.get(author_id, []):
                    if not author.affiliation:
                        author.affiliation = affiliation_str

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
        author_id_to_authors: dict[str, list[Author]] = {}
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
                    # Collect author-ID → Author mapping for batch affiliation fetch
                    raw_authors = item.get("authors", [])
                    for idx, author_entry in enumerate(raw_authors):
                        author_id = author_entry.get("authorId")
                        if author_id and idx < len(paper.authors):
                            author_id_to_authors.setdefault(author_id, []).append(
                                paper.authors[idx]
                            )

            if progress_callback is not None:
                progress_callback(len(papers), total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            token = data.get("token")
            if not token or len(items) < page_size:
                break

        result = papers[:max_papers] if max_papers is not None else papers

        # Batch-fetch author affiliations after paper retrieval
        if author_id_to_authors:
            self._enrich_author_affiliations(author_id_to_authors)

        return result
