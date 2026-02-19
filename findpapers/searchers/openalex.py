"""OpenAlex searcher implementation."""

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
from findpapers.query.builders.openalex import OpenAlexQueryBuilder
from findpapers.searchers.base import SearcherBase

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openalex.org/works"
_PAGE_SIZE = 200  # OpenAlex max per_page
# Polite pool: ~10 req/s with email in User-Agent → use 0.1s interval
_MIN_REQUEST_INTERVAL = 0.15
_USER_AGENT = "findpapers/1.0 (mailto:findpapers@example.com)"


def _openalex_work_type_to_paper_type(work_type: Optional[str]) -> Optional[PaperType]:
    """Map an OpenAlex ``type`` field to a :class:`PaperType`.

    Parameters
    ----------
    work_type : str | None
        Raw ``type`` value from the OpenAlex works API.

    Returns
    -------
    PaperType | None
        Matching paper type, or ``None`` when the value cannot be mapped.
    """
    if not work_type:
        return None
    lowered = work_type.strip().lower()
    if lowered in {"article", "review", "editorial", "letter", "erratum"}:
        return PaperType.ARTICLE
    if lowered == "book-chapter":
        return PaperType.INCOLLECTION
    if lowered == "book":
        return PaperType.INBOOK
    if lowered == "preprint":
        return PaperType.UNPUBLISHED
    if lowered == "dissertation":
        return PaperType.PHDTHESIS
    if lowered in {"proceedings-article", "proceedings"}:
        return PaperType.INPROCEEDINGS
    if lowered in {"report", "standard"}:
        return PaperType.TECHREPORT
    return None


class OpenAlexSearcher(SearcherBase):
    """Searcher for the OpenAlex open catalog of academic works.

    https://docs.openalex.org/how-to-use-the-api

    Rate limit: max 100 req/s for all users.
    Without an API key the daily budget is $0.01/day (~10 requests,
    recommended for testing and demos only).  With a free API key the budget
    is $10/day (~10,000 requests/day). Singleton requests are free.
    """

    def __init__(
        self,
        query_builder: Optional[OpenAlexQueryBuilder] = None,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        """Create an OpenAlex searcher.

        Parameters
        ----------
        query_builder : OpenAlexQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`OpenAlexQueryBuilder` is created automatically.
        api_key : str | None
            OpenAlex API key (optional but highly recommended; free keys
            available at https://openalex.org/settings/api).  Without a key
            the daily budget is $0.01/day, suitable for testing only.
        email : str | None
            Contact email for the polite pool (recommended by OpenAlex).
        """
        self._query_builder: OpenAlexQueryBuilder = query_builder or OpenAlexQueryBuilder()
        self._api_key = api_key
        self._email = email
        self._last_request_time: float = 0.0

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return "OpenAlex"

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the OpenAlex query builder.

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

    def _build_headers(self) -> dict:
        """Build HTTP headers including the User-Agent for polite pool access.

        Returns
        -------
        dict
            HTTP headers.
        """
        user_agent = _USER_AGENT
        if self._email:
            user_agent = f"findpapers/1.0 (mailto:{self._email})"
        return {"User-Agent": user_agent}

    def _get(self, params: dict) -> requests.Response:
        """Perform a rate-limited GET request to the OpenAlex API.

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
        if self._api_key:
            params = {**params, "api_key": self._api_key}
        response = requests.get(
            _BASE_URL,
            params=params,
            headers=self._build_headers(),
            timeout=30,
        )
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_paper(work: Dict[str, Any]) -> Optional[Paper]:
        """Parse a single OpenAlex work object into a :class:`Paper`.

        Parameters
        ----------
        work : dict
            OpenAlex work metadata dictionary.

        Returns
        -------
        Paper | None
            Parsed paper or ``None`` when required fields are missing.
        """
        title = (work.get("title") or work.get("display_name") or "").strip()
        if not title:
            return None

        # Abstract — stored as inverted index in OpenAlex
        abstract = ""
        inverted_index = work.get("abstract_inverted_index")
        if inverted_index:
            abstract = _reconstruct_abstract(inverted_index)

        # Authors
        authors: list[str] = []
        for authorship in work.get("authorships", []):
            author_info = authorship.get("author") or {}
            name = (author_info.get("display_name") or "").strip()
            if name:
                authors.append(name)

        # Publication date
        pub_date: Optional[datetime.date] = None
        _pub_date_str = (work.get("publication_date") or "").strip()
        if _pub_date_str:
            try:
                pub_date = datetime.date.fromisoformat(_pub_date_str[:10])
            except ValueError:
                pass

        # DOI / URL
        doi_raw: Optional[str] = (work.get("doi") or "").strip() or None
        doi: Optional[str] = None
        if doi_raw:
            # OpenAlex returns full DOI URL: https://doi.org/10.xxx/yyy
            doi = doi_raw.replace("https://doi.org/", "").replace("http://doi.org/", "")

        url: Optional[str] = None
        open_access = work.get("open_access") or {}
        url = (open_access.get("oa_url") or "").strip() or None
        if not url:
            primary = work.get("primary_location") or {}
            url = (primary.get("landing_page_url") or "").strip() or None

        pdf_url: Optional[str] = None
        for loc in work.get("locations", []):
            if isinstance(loc, dict) and loc.get("pdf_url"):
                pdf_url = loc["pdf_url"]
                break

        # Citations
        citations: Optional[int] = work.get("cited_by_count")

        # Keywords / concepts
        keywords: set[str] = set()
        for concept in work.get("concepts", []):
            kw = (concept.get("display_name") or "").strip()
            if kw:
                keywords.add(kw)
        for kw_entry in work.get("keywords", []):
            if isinstance(kw_entry, str):
                kw = kw_entry.strip()
            elif isinstance(kw_entry, dict):
                kw = (kw_entry.get("display_name") or "").strip()
            else:
                kw = ""
            if kw:
                keywords.add(kw)

        # Publication
        publication: Optional[Publication] = None
        primary_loc = work.get("primary_location") or {}
        source = primary_loc.get("source") or {}
        pub_title = (source.get("display_name") or "").strip()
        if pub_title:
            issn_list = source.get("issn_l") or source.get("issn") or []
            issn = (
                issn_list[0]
                if isinstance(issn_list, list) and issn_list
                else str(issn_list) if issn_list else None
            )
            publication = Publication(title=pub_title, issn=issn)

        # Paper type derived from the work-level "type" field
        paper_type = _openalex_work_type_to_paper_type(work.get("type"))

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
                databases={"OpenAlex"},
                paper_type=paper_type,
            )
        except ValueError:
            return None

        return paper

    def _fetch_single_query(
        self,
        query_params: Dict[str, Any],
        max_papers: Optional[int],
        papers: List[Paper],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> None:
        """Fetch papers for one converted query variant using cursor-based pagination.

        Parameters
        ----------
        query_params : dict
            Query parameters from the builder.
        max_papers : int | None
            Overall cap (shared with caller list).
        papers : list[Paper]
            Accumulator — papers appended in-place.
        progress_callback : Callable | None
            Progress callback.
        """
        cursor = "*"
        total: Optional[int] = None

        while True:
            if max_papers is not None and len(papers) >= max_papers:
                break

            remaining = (max_papers - len(papers)) if max_papers is not None else _PAGE_SIZE
            page_size = min(_PAGE_SIZE, remaining)

            params: dict = {
                **query_params,
                "per-page": page_size,
                "cursor": cursor,
                "sort": "publication_date:desc",
                "select": (
                    "id,doi,title,display_name,publication_date,authorships,"
                    "abstract_inverted_index,cited_by_count,open_access,locations,"
                    "primary_location,concepts,keywords,type"
                ),
            }

            try:
                response = self._get(params)
            except Exception:
                logger.exception("OpenAlex request failed (cursor=%s).", cursor)
                break

            data = response.json()
            meta = data.get("meta") or {}
            if total is None:
                total = meta.get("count")

            results = data.get("results") or []
            if not results:
                break

            for work in results:
                paper = self._parse_paper(work)
                if paper is not None:
                    papers.append(paper)

            if progress_callback is not None:
                progress_callback(len(papers), total)

            if max_papers is not None and len(papers) >= max_papers:
                break

            next_cursor = meta.get("next_cursor")
            if not next_cursor or len(results) < page_size:
                break

            cursor = next_cursor

    def _fetch_papers(
        self,
        query: Query,
        max_papers: Optional[int],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> List[Paper]:
        """Fetch papers from OpenAlex handling query expansion.

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
            Retrieved papers, deduplicated by DOI.
        """
        expanded = self._query_builder.expand_query(query)
        papers: List[Paper] = []
        seen_keys: set[str] = set()

        for sub_query in expanded:
            if max_papers is not None and len(papers) >= max_papers:
                break

            sub_params = self._query_builder.convert_query(sub_query)
            before = len(papers)
            self._fetch_single_query(sub_params, max_papers, papers, progress_callback)

            # Deduplicate newly appended papers by DOI or title
            deduped: List[Paper] = []
            for paper in papers[before:]:
                key = paper.doi or paper.url or paper.title
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(paper)
            papers[before:] = deduped

        return papers[:max_papers] if max_papers is not None else papers


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct plain text abstract from OpenAlex inverted index.

    Parameters
    ----------
    inverted_index : dict
        Mapping of word → list of positions.

    Returns
    -------
    str
        Reconstructed abstract string.
    """
    word_positions: list[tuple[int, str]] = []
    if not inverted_index:
        return ""
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in word_positions)
