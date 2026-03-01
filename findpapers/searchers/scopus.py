"""Scopus searcher implementation."""

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
from findpapers.query.builders.scopus import ScopusQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.elsevier.com/content/search/scopus"
_PAGE_SIZE = 25  # Scopus max results per request (in standard view)
# Conservative interval — actual limit varies by institution
_MIN_REQUEST_INTERVAL = 0.5

# Mapping from Scopus prism:aggregationType values to SourceType.
_SCOPUS_AGGREGATION_TYPE_MAP: dict[str, SourceType] = {
    "journal": SourceType.JOURNAL,
    "conference proceeding": SourceType.CONFERENCE,
    "book": SourceType.BOOK,
    "book series": SourceType.BOOK,
    "trade journal": SourceType.JOURNAL,
}


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

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return Database.SCOPUS.value

    @property
    def is_available(self) -> bool:
        """Return ``True`` only when an API key has been provided.

        Scopus requires an API key for production use.  Without one the
        searcher is considered unavailable and will be skipped by the runner.

        Returns
        -------
        bool
            ``True`` if an API key is set, ``False`` otherwise.
        """
        return self._api_key is not None

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the Scopus query builder.

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

    def _prepare_headers(self, headers: dict) -> dict:
        """Inject Scopus-required HTTP headers including Accept type and API key.

        Parameters
        ----------
        headers : dict
            Raw HTTP headers.

        Returns
        -------
        dict
            Headers with ``Accept`` set to JSON and optionally
            ``X-ELS-APIKey`` added.
        """
        updated = {**headers, "Accept": "application/json"}
        if self._api_key:
            updated["X-ELS-APIKey"] = self._api_key
        return updated

    def _parse_paper(self, entry: Dict[str, Any]) -> Optional[Paper]:
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

        # Authors — Scopus search API returns only the first author in dc:creator.
        raw_creator = entry.get("dc:creator") or ""
        if isinstance(raw_creator, list):
            authors: list[Author] = [
                Author(name=a.strip()) for a in raw_creator if (a or "").strip()
            ]
        elif raw_creator:
            authors = [Author(name=raw_creator.strip())]
        else:
            authors = []

        # Affiliation — Scopus provides entry-level affiliations. When a single
        # author is returned we assign the first affiliation to that author.
        if len(authors) == 1:
            raw_affiliation = entry.get("affiliation")
            if isinstance(raw_affiliation, list) and raw_affiliation:
                affilname = (raw_affiliation[0].get("affilname") or "").strip()
                if affilname:
                    authors[0] = Author(name=authors[0].name, affiliation=affilname)

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

        # Source
        pub_title = (
            entry.get("prism:publicationName") or entry.get("prism:issueName") or ""
        ).strip()
        source: Optional[Source] = None
        if pub_title:
            issn = (entry.get("prism:issn") or entry.get("prism:eIssn") or "").strip() or None
            # prism:isbn may be a list of dicts in some responses
            raw_isbn = entry.get("prism:isbn")
            if isinstance(raw_isbn, list):
                isbn = raw_isbn[0].get("$", "").strip() if raw_isbn else None
            else:
                isbn = (raw_isbn or "").strip() or None
            publisher = (entry.get("dc:publisher") or "").strip() or None
            # Map aggregationType to SourceType.
            raw_agg_type = (entry.get("prism:aggregationType") or "").strip().lower()
            source_type = _SCOPUS_AGGREGATION_TYPE_MAP.get(raw_agg_type)
            source = Source(
                title=pub_title,
                issn=issn,
                isbn=isbn,
                publisher=publisher,
                source_type=source_type,
            )

        # Infer paper_type from subtypeDescription.
        # Full Scopus subtypeDescription values:
        # Article, Abstract Report, Book, Book Chapter, Business Article,
        # Conference Paper, Conference Review, Data Paper, Editorial,
        # Erratum, Letter, Note, Press Release, Report, Retracted, Review,
        # Short Survey, Undefined
        _SCOPUS_PAPER_TYPE_MAP: dict[str, PaperType] = {
            "article": PaperType.ARTICLE,
            "review": PaperType.ARTICLE,
            "short survey": PaperType.ARTICLE,
            "letter": PaperType.ARTICLE,
            "note": PaperType.ARTICLE,
            "editorial": PaperType.ARTICLE,
            "erratum": PaperType.ARTICLE,
            "business article": PaperType.ARTICLE,
            "conference paper": PaperType.INPROCEEDINGS,
            "conference review": PaperType.INPROCEEDINGS,
            "book": PaperType.BOOK,
            "book chapter": PaperType.INBOOK,
            "report": PaperType.TECHREPORT,
            "data paper": PaperType.MISC,
        }
        raw_subtype = (entry.get("subtypeDescription") or "").strip().lower()
        paper_type = _SCOPUS_PAPER_TYPE_MAP.get(raw_subtype)

        # Pages
        pages: Optional[str] = (entry.get("prism:pageRange") or "").strip() or None

        try:
            paper = Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                source=source,
                publication_date=pub_date,
                url=url,
                doi=doi,
                citations=citations,
                page_range=pages,
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
        processed = 0
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
                response = self._get(_BASE_URL, params)
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

            processed += len(entries)
            if progress_callback is not None:
                progress_callback(processed, total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            if len(entries) < page_size:
                break

            offset += len(entries)

        return papers[:max_papers] if max_papers is not None else papers
