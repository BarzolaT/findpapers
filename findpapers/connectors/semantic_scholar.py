"""Semantic Scholar searcher implementation."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any

from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.connectors.search_base import SearchConnectorBase
from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import Query
from findpapers.core.search_result import Database
from findpapers.core.source import Source, SourceType
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder

logger = logging.getLogger(__name__)

_BULK_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"
_AUTHOR_BATCH_URL = "https://api.semanticscholar.org/graph/v1/author/batch"
_PAGE_SIZE = 100  # Semantic Scholar max per request
_CITATION_PAGE_SIZE = 1000  # Max per page for citations/references endpoints
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

# Mapping from Semantic Scholar publicationTypes entries to PaperType.
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


class SemanticScholarConnector(SearchConnectorBase, CitationConnectorBase):
    """Connector for the Semantic Scholar research corpus.

    Uses the Bulk Search endpoint:
    https://api.semanticscholar.org/api-docs/#tag/Paper-Data/operation/bulk_paper_search

    Rate limits:
    - Without API key: up to 1000 req/s (shared among all unauthenticated users)
    - With API key: 1 req/s (introductory; can be increased upon request)
    """

    def __init__(
        self,
        query_builder: SemanticScholarQueryBuilder | None = None,
        api_key: str | None = None,
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

        if not api_key:
            logger.warning(
                "No API key provided for Semantic Scholar. "
                "Without a key, requests share the unauthenticated pool "
                "(up to 1000 req/s shared among all anonymous users). "
                "Request a key at https://www.semanticscholar.org/product/api "
                "for a dedicated quota."
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
        updated = super()._prepare_headers(headers)
        if self._api_key:
            updated["x-api-key"] = self._api_key
        return updated

    # ------------------------------------------------------------------
    # Citation methods (CitationConnectorBase)
    # ------------------------------------------------------------------

    def _fetch_citation_page(
        self,
        doi: str,
        endpoint: str,
        offset: int,
    ) -> tuple[list[Paper], int]:
        """Fetch one page of references or citations for a paper.

        Parameters
        ----------
        doi : str
            DOI of the paper.
        endpoint : str
            ``"references"`` or ``"citations"``.
        offset : int
            Pagination offset.

        Returns
        -------
        tuple[list[Paper], int]
            Parsed papers from this page and the total ``next`` offset
            (``-1`` when there are no more pages).
        """
        url = f"{_PAPER_URL}/DOI:{doi}/{endpoint}"
        params: dict[str, Any] = {
            "fields": _PAPER_FIELDS,
            "limit": _CITATION_PAGE_SIZE,
            "offset": offset,
        }
        try:
            response = self._get(url, params)
        except Exception:
            logger.warning(
                "Semantic Scholar: failed to fetch %s for DOI %s (offset=%d).",
                endpoint,
                doi,
                offset,
            )
            return [], -1

        data = response.json()
        items = data.get("data") or []
        papers: list[Paper] = []
        for item in items:
            # The citations/references endpoints wrap each paper in
            # {"citedPaper": {...}} or {"citingPaper": {...}}.
            nested_key = "citedPaper" if endpoint == "references" else "citingPaper"
            paper_data = item.get(nested_key) or item
            paper = self._parse_paper(paper_data)
            if paper is not None:
                papers.append(paper)

        next_offset = data.get("next")
        if next_offset is None or len(items) < _CITATION_PAGE_SIZE:
            next_offset = -1

        return papers, next_offset

    def _fetch_all_citation_pages(self, doi: str, endpoint: str) -> list[Paper]:
        """Paginate through all references or citations for a paper.

        Parameters
        ----------
        doi : str
            DOI of the paper.
        endpoint : str
            ``"references"`` or ``"citations"``.

        Returns
        -------
        list[Paper]
            All papers from the paginated endpoint.
        """
        all_papers: list[Paper] = []
        offset = 0

        while offset >= 0:
            page_papers, next_offset = self._fetch_citation_page(doi, endpoint, offset)
            all_papers.extend(page_papers)
            offset = next_offset

        return all_papers

    def fetch_references(self, paper: Paper) -> list[Paper]:
        """Return papers cited *by* the given paper (backward snowballing).

        Uses the Semantic Scholar ``/paper/{id}/references`` endpoint.

        Parameters
        ----------
        paper : Paper
            The paper whose references should be fetched.  Must have a DOI.

        Returns
        -------
        list[Paper]
            Papers referenced by *paper*, or empty list on failure.
        """
        if not paper.doi:
            return []

        logger.debug("Semantic Scholar: fetching references for DOI %s.", paper.doi)
        return self._fetch_all_citation_pages(paper.doi, "references")

    def fetch_cited_by(self, paper: Paper) -> list[Paper]:
        """Return papers that cite the given paper (forward snowballing).

        Uses the Semantic Scholar ``/paper/{id}/citations`` endpoint.

        Parameters
        ----------
        paper : Paper
            The paper whose citing papers should be fetched.  Must have a DOI.

        Returns
        -------
        list[Paper]
            Papers that cite *paper*, or empty list on failure.
        """
        if not paper.doi:
            return []

        logger.debug("Semantic Scholar: fetching citations for DOI %s.", paper.doi)
        return self._fetch_all_citation_pages(paper.doi, "citations")

    def _parse_paper(self, item: dict[str, Any]) -> Paper | None:
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
        pub_date: datetime.date | None = None
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
        doi: str | None = (external_ids.get("DOI") or "").strip() or None
        if doi is None:
            arxiv_id = (external_ids.get("ArXivId") or "").strip()
            if arxiv_id:
                doi = f"10.48550/arXiv.{arxiv_id}"

        # URL
        url: str | None = (item.get("url") or "").strip() or None

        # PDF URL
        pdf_url: str | None = None
        open_access_pdf = item.get("openAccessPdf")
        if isinstance(open_access_pdf, dict):
            pdf_url = (open_access_pdf.get("url") or "").strip() or None

        # Citations
        citations: int | None = item.get("citationCount")

        # Keywords from fields of study
        keywords: set[str] = set()
        for field in item.get("fieldsOfStudy") or []:
            if isinstance(field, str) and field.strip():
                keywords.add(field.strip())

        # Source
        source: Source | None = None
        journal = item.get("journal") or {}
        venue = (item.get("venue") or "").strip()
        pub_title = (journal.get("name") or venue or "").strip()

        # Determine source_type from publicationVenue.type (preferred),
        # falling back to publicationTypes list.
        source_type: SourceType | None = None
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
        pages: str | None = None
        if journal:
            raw_pages = (journal.get("pages") or "").strip()
            if raw_pages:
                pages = raw_pages

        # Infer paper_type from publicationTypes list.
        # Full list from the Semantic Scholar API docs:
        # Review, JournalArticle, CaseReport, ClinicalTrial, Conference,
        # Dataset, Editorial, LettersAndComments, MetaAnalysis, News,
        # Study, Book, BookSection
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
        max_papers: int | None,
        progress_callback: Callable[[int, int | None], None] | None,
        since: datetime.date | None = None,
        until: datetime.date | None = None,
    ) -> list[Paper]:
        """Fetch papers from Semantic Scholar bulk search with pagination.

        Parameters
        ----------
        query : Query
            Validated query object.
        max_papers : int | None
            Maximum papers to retrieve.
        progress_callback : Callable[[int, int | None], None] | None
            Progress callback.
        since : datetime.date | None
            Only return papers published on or after this date.
        until : datetime.date | None
            Only return papers published on or before this date.

        Returns
        -------
        list[Paper]
            Retrieved papers.
        """
        ss_params = self._query_builder.convert_query(query)

        # Semantic Scholar supports publicationDateOrYear range filter.
        if since or until:
            from_part = since.isoformat() if since else ""
            to_part = until.isoformat() if until else ""
            ss_params["publicationDateOrYear"] = f"{from_part}:{to_part}"
        papers: list[Paper] = []
        author_id_to_authors: dict[str, list[Author]] = {}
        token: str | None = None  # Semantic Scholar uses token-based pagination
        total: int | None = None

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
