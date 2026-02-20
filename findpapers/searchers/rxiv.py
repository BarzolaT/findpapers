"""Shared searcher base for bioRxiv and medRxiv (rxiv family)."""

from __future__ import annotations

import datetime
import logging
import re
import urllib.parse
from collections.abc import Callable
from typing import Any, Dict, List, Optional

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

    @property
    def query_builder(self) -> RxivQueryBuilder:
        """Return the rxiv query builder.

        Returns
        -------
        RxivQueryBuilder
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

    @staticmethod
    def _parse_total_from_soup(soup: BeautifulSoup) -> Optional[int]:
        """Try to extract the total result count from a search results page.

        Attempts several CSS selectors used by the Highwire Press platform
        (medrxiv.org / biorxiv.org) and falls back to a regex on the full page
        text.  Returns ``None`` when the count cannot be determined.

        Parameters
        ----------
        soup : BeautifulSoup
            Parsed HTML of the search results page.

        Returns
        -------
        int | None
            Total result count, or ``None`` when unavailable.
        """
        # bioRxiv / medRxiv (Highwire Press): the total result count is in
        # <h1 id="page-title"> inside a .highwire-search-summary wrapper, e.g.
        #   <h1 id="page-title">26,467 Results</h1>
        el = soup.select_one(".highwire-search-summary h1#page-title")
        if el:
            text = el.get_text(separator=" ")
            m = re.search(r"([\d,]+)", text)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        return None

    def _scrape_dois(self, url: str) -> tuple[list[str], Optional[int]]:
        """Scrape paper DOIs and the total result count from a search results page.

        Parameters
        ----------
        url : str
            Search results page URL.

        Returns
        -------
        tuple[list[str], int | None]
            A 2-tuple of (doi_list, total_count).  *total_count* is ``None``
            when the page does not expose the total number of results.
        """
        try:
            response = self._get(url)
        except Exception:
            logger.exception("Failed to scrape rxiv search page: %s", url)
            return [], None

        soup = BeautifulSoup(response.text, "html.parser")
        total = self._parse_total_from_soup(soup)
        dois: list[str] = []
        for link in soup.select("a.highwire-cite-linked-title"):
            href = link.get("href", "")
            href_str = href if isinstance(href, str) else (href[0] if href else "")
            if not href_str:
                continue
            # Normalize: extract the path component so that both relative
            # (/content/...) and absolute (https://biorxiv.org/content/...)
            # hrefs are handled uniformly.
            parsed_href = urllib.parse.urlparse(href_str)
            path = parsed_href.path
            if not path:
                continue
            # Expected path formats:
            #   /content/10.1101/2020.01.01.123456v1   (old — DOI embedded)
            #   /content/early/YYYY/MM/DD/SUFFIX[vN]   (new — DOI suffix last)
            parts = path.strip("/").split("/", maxsplit=1)
            if len(parts) != 2:
                continue
            doi_path = parts[1]
            if doi_path.startswith("early/"):
                # The actual DOI suffix is the last path segment.
                suffix = doi_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
                dois.append(f"10.1101/{suffix}")
            else:
                dois.append(doi_path)
        return dois, total

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
            logger.debug("Failed to fetch metadata for DOI %s.", doi, exc_info=True)
            return None

        data = response.json()
        collection = data.get("collection") or []
        if not collection:
            messages = data.get("messages") or []
            for msg in messages:
                status = msg.get("status", "")
                if status:
                    logger.warning(
                        "biorxiv API did not return metadata for DOI %s: %s",
                        doi,
                        status,
                    )
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
        total: Optional[int] = None
        processed = 0

        while True:
            if max_papers is not None and len(papers) >= max_papers:
                break

            url = self._build_search_url(params, page)
            dois, page_total = self._scrape_dois(url)
            # Use the total from the first page that provides one.
            if total is None and page_total is not None:
                total = page_total
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

                processed += 1
                if progress_callback is not None:
                    progress_callback(processed, total)

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
