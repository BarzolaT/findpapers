"""Shared searcher base for bioRxiv and medRxiv (rxiv family)."""

from __future__ import annotations

import datetime
import logging
import time
import urllib.parse
from collections.abc import Callable
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from findpapers.core.paper import Paper, PaperType
from findpapers.core.publication import Publication
from findpapers.core.query import Query
from findpapers.query.builders.rxiv import RxivQueryBuilder
from findpapers.searchers.base import QUERY_COMBINATIONS_WARNING_THRESHOLD, SearcherBase

logger = logging.getLogger(__name__)

_SEARCH_BASE_URL = "https://www.medrxiv.org/search/"
_API_BASE_URL = "https://api.biorxiv.org/details/{server}/{doi}"
# Conservative rate limit (~1 req/s)
_MIN_REQUEST_INTERVAL = 1.0


class RxivSearcher(SearcherBase):
    """Base searcher shared by bioRxiv and medRxiv.

    Uses:
    - Web-scraping for search (extract DOIs from search results pages).
    - biorxiv.org API for fetching metadata by DOI.

    Rate limit: ~1 req/s (not specified officially).
    """

    def __init__(
        self,
        rxiv_server: str,
        jcode: str,
        query_builder: Optional[RxivQueryBuilder] = None,
    ) -> None:
        """Create an rxiv-family searcher.

        Parameters
        ----------
        rxiv_server : str
            Server identifier used in the metadata API (``biorxiv`` or ``medrxiv``).
        jcode : str
            Journal code used in the search URL (``biorxiv`` or ``medrxiv``).
        query_builder : RxivQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`RxivQueryBuilder` is created automatically.
        """
        self._rxiv_server = rxiv_server
        self._jcode = jcode
        self._query_builder: RxivQueryBuilder = query_builder or RxivQueryBuilder()
        self._last_request_time: float = 0.0

    @property
    def query_builder(self) -> RxivQueryBuilder:
        """Return the rxiv query builder.

        Returns
        -------
        RxivQueryBuilder
            The underlying builder instance.
        """
        return self._query_builder

    def _rate_limit(self) -> None:
        """Enforce minimum interval between HTTP requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    def _get(self, url: str, params: Optional[dict] = None) -> requests.Response:
        """Perform a rate-limited GET request.

        Parameters
        ----------
        url : str
            Target URL.
        params : dict | None
            Optional query parameters.

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
        response = requests.get(url, params=params, timeout=30)
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return response

    def _build_search_url(self, params: Dict[str, Any], page: int = 0) -> str:
        """Build query URL for the rxiv search endpoint.

        Parameters
        ----------
        params : dict
            Parsed query params from builder (``field``, ``match``, ``terms``).
        page : int
            0-based page index (each page has 10 results).

        Returns
        -------
        str
            Fully-formed search URL.
        """
        terms = params.get("terms", [])
        match_flag = params.get("match", "match-all")

        encoded_terms = "+".join(urllib.parse.quote(t, safe="") for t in terms)
        path = (
            f"abstract_title%3A{encoded_terms}"
            f"%20abstract_title_flags%3A{match_flag}"
            f"%20jcode%3A{self._jcode}"
            f"%20numresults%3A10"
            f"%20sort%3Apublication-date"
            f"%20direction%3Adescending"
            f"%20format_result%3Astandard"
            f"%20cursor%3A{page * 10}"
        )
        return _SEARCH_BASE_URL + path

    def _scrape_dois(self, url: str) -> list[str]:
        """Scrape paper DOIs from a search results page.

        Parameters
        ----------
        url : str
            Search results page URL.

        Returns
        -------
        list[str]
            DOI strings found on the page.
        """
        try:
            response = self._get(url)
        except Exception:
            logger.exception("Failed to scrape rxiv search page: %s", url)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        dois: list[str] = []
        for link in soup.select("a.highwire-cite-linked-title"):
            href = link.get("href", "")
            href_str = href if isinstance(href, str) else (href[0] if href else "")
            if href_str:
                # href has form /content/10.1101/2020.01.01.123456v1
                parts = href_str.strip("/").split("/", maxsplit=1)
                if len(parts) == 2:
                    dois.append(parts[1])
        return dois

    def _fetch_metadata(self, doi: str) -> Optional[Dict[str, Any]]:
        """Fetch paper metadata from the biorxiv.org API.

        Parameters
        ----------
        doi : str
            DOI string.

        Returns
        -------
        dict | None
            Metadata dict or ``None`` on failure.
        """
        url = _API_BASE_URL.format(server=self._rxiv_server, doi=doi)
        try:
            response = self._get(url)
        except Exception:
            logger.exception("Failed to fetch metadata for DOI %s.", doi)
            return None

        data = response.json()
        collection = data.get("collection") or []
        return collection[0] if collection else None

    @staticmethod
    def _parse_paper(meta: Dict[str, Any], database: str) -> Optional[Paper]:
        """Parse rxiv metadata dict into a :class:`Paper`.

        Parameters
        ----------
        meta : dict
            Metadata dictionary from the biorxiv API.
        database : str
            Database label to attach to the paper.

        Returns
        -------
        Paper | None
            Parsed paper or ``None`` when required fields are missing.
        """
        title = (meta.get("title") or "").strip()
        if not title:
            return None

        abstract = (meta.get("abstract") or "").strip()
        doi = (meta.get("doi") or "").strip() or None
        url = f"https://www.{database}.org/content/{doi}" if doi else None
        pdf_url = f"https://www.{database}.org/content/{doi}.full.pdf" if doi else None

        # Authors — comma-separated string
        authors_str = (meta.get("authors") or "").strip()
        authors = [a.strip() for a in authors_str.split(";") if a.strip()] if authors_str else []

        # Date
        pub_date: Optional[datetime.date] = None
        _pub_date_str = (meta.get("date") or "").strip()
        if _pub_date_str:
            try:
                pub_date = datetime.date.fromisoformat(_pub_date_str[:10])
            except ValueError:
                pass

        # Category/publication — the API "category" is a subject area (e.g.
        # "Neuroscience"), not a publication type.  We still use it as the
        # publication title so the source is identifiable.
        category = (meta.get("category") or "").strip()
        publication: Optional[Publication] = None
        if category:
            publication = Publication(title=category)

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
                databases={database},
                # bioRxiv / medRxiv are preprint servers — all output is unpublished.
                paper_type=PaperType.UNPUBLISHED,
            )
        except ValueError:
            return None

        return paper

    def _search_single(
        self,
        params: Dict[str, Any],
        max_papers: Optional[int],
        papers: List[Paper],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> None:
        """Fetch papers for a single expanded query variant.

        Parameters
        ----------
        params : dict
            Query parameters from the builder.
        max_papers : int | None
            Overall cap (shared across all expanded queries).
        papers : list[Paper]
            Accumulator list; papers are appended in place.
        progress_callback : Callable | None
            Progress callback.
        """
        page = 0

        while True:
            if max_papers is not None and len(papers) >= max_papers:
                break

            url = self._build_search_url(params, page)
            dois = self._scrape_dois(url)
            if not dois:
                break

            for doi in dois:
                if max_papers is not None and len(papers) >= max_papers:
                    break
                meta = self._fetch_metadata(doi)
                if meta is not None:
                    paper = self._parse_paper(meta, self._rxiv_server)
                    if paper is not None:
                        papers.append(paper)

                if progress_callback is not None:
                    progress_callback(len(papers), None)

            if len(dois) < 10:
                break

            page += 1

    def _fetch_papers(
        self,
        query: Query,
        max_papers: Optional[int],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> List[Paper]:
        """Fetch papers from the rxiv family with query expansion.

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
            Retrieved papers (deduplicated by DOI).
        """
        expanded = self._query_builder.expand_query(query)
        if len(expanded) > QUERY_COMBINATIONS_WARNING_THRESHOLD:
            logger.warning(
                "%s: query expanded to %d combinations; search may be slow.",
                self.name,
                len(expanded),
            )

        papers: List[Paper] = []
        seen_dois: set[str] = set()

        for sub_query in expanded:
            if max_papers is not None and len(papers) >= max_papers:
                break

            sub_params = self._query_builder.convert_query(sub_query)
            before = len(papers)
            self._search_single(sub_params, max_papers, papers, progress_callback)

            # Deduplicate by DOI in place
            deduped: List[Paper] = []
            for paper in papers[before:]:
                key = paper.doi or paper.url or paper.title
                if key and key not in seen_dois:
                    seen_dois.add(key)
                    deduped.append(paper)
            papers[before:] = deduped

        return papers[:max_papers] if max_papers is not None else papers
