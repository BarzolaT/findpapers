"""OpenAlex searcher implementation."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.connectors.search_base import SearchConnectorBase
from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import Query
from findpapers.core.search_result import Database
from findpapers.core.source import Source, SourceType
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.openalex import OpenAlexQueryBuilder

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openalex.org/works"
_PAGE_SIZE = 200  # OpenAlex max per_page
# Polite pool: ~10 req/s with email in User-Agent → use 0.1s interval
_MIN_REQUEST_INTERVAL = 0.15
# Default User-Agent used when no contact email has been provided.
_USER_AGENT_DEFAULT = "findpapers/1.0 (https://github.com/jonatasgrosman/findpapers)"

# Mapping from OpenAlex source.type values to SourceType.
_OPENALEX_SOURCE_TYPE_MAP: dict[str, SourceType] = {
    "journal": SourceType.JOURNAL,
    "conference": SourceType.CONFERENCE,
    "repository": SourceType.REPOSITORY,
    "book series": SourceType.BOOK,
    "ebook platform": SourceType.BOOK,
    "metadata": SourceType.OTHER,
    "other": SourceType.OTHER,
}


# Maximum number of OpenAlex IDs to fetch in a single filter request
# (the API supports pipe-separated ID filters).
_REFERENCES_BATCH_SIZE = 50

# Mapping from OpenAlex work.type (lowered) to PaperType.
_OPENALEX_PAPER_TYPE_MAP: dict[str, PaperType] = {
    "article": PaperType.ARTICLE,
    "review": PaperType.ARTICLE,
    "letter": PaperType.ARTICLE,
    "editorial": PaperType.ARTICLE,
    "erratum": PaperType.ARTICLE,
    "book-chapter": PaperType.INBOOK,
    "book": PaperType.BOOK,
    "dissertation": PaperType.PHDTHESIS,
    "preprint": PaperType.UNPUBLISHED,
    "report": PaperType.TECHREPORT,
    "standard": PaperType.TECHREPORT,
    "peer-review": PaperType.MISC,
    "other": PaperType.MISC,
    "paratext": PaperType.MISC,
    "reference-entry": PaperType.INCOLLECTION,
    "dataset": PaperType.MISC,
    "component": PaperType.MISC,
    "grant": PaperType.MISC,
    "supplementary-materials": PaperType.MISC,
    "libguides": PaperType.MISC,
}


class OpenAlexConnector(SearchConnectorBase, CitationConnectorBase):
    """Connector for the OpenAlex open catalog of academic works.

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

        if not api_key:
            logger.warning(
                "No API key provided for OpenAlex. "
                "The daily budget without a key is $0.01/day (~10 requests), "
                "suitable for testing only. Get a free key at "
                "https://openalex.org/settings/api to increase your quota."
            )

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return Database.OPENALEX.value

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the OpenAlex query builder.

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
        """Inject the OpenAlex API key into query parameters when configured.

        Parameters
        ----------
        params : dict
            Raw query parameters.

        Returns
        -------
        dict
            Parameters with ``api_key`` added when a key is set.
        """
        if self._api_key:
            return {**params, "api_key": self._api_key}
        return params

    def _prepare_headers(self, headers: dict) -> dict:
        """Set the User-Agent header for OpenAlex polite pool access.

        Parameters
        ----------
        headers : dict
            Raw HTTP headers.

        Returns
        -------
        dict
            Headers with ``User-Agent`` set.
        """
        user_agent = _USER_AGENT_DEFAULT
        if self._email:
            user_agent = f"findpapers/1.0 (mailto:{self._email})"
        return {**headers, "User-Agent": user_agent}

    # ------------------------------------------------------------------
    # Citation methods (CitationConnectorBase)
    # ------------------------------------------------------------------

    def _resolve_openalex_id(self, paper: Paper) -> str | None:
        """Resolve a paper's OpenAlex ID via the DOI.

        Queries ``GET /works/doi:{doi}`` which returns the full work record
        whose ``id`` field is the canonical OpenAlex ID.

        Parameters
        ----------
        paper : Paper
            Paper with a DOI.

        Returns
        -------
        str | None
            The OpenAlex ID (e.g. ``"https://openalex.org/W123456"``), or
            ``None`` when the DOI cannot be resolved.
        """
        if not paper.doi:
            return None

        url = f"{_BASE_URL}/doi:{paper.doi}"
        try:
            response = self._get(url, params={"select": "id"})
            data = response.json()
            return (data.get("id") or "").strip() or None
        except Exception:
            logger.debug("Failed to resolve OpenAlex ID for DOI %s.", paper.doi)
            return None

    def _fetch_works_by_ids(self, openalex_ids: list[str]) -> list[Paper]:
        """Fetch full work records for a list of OpenAlex IDs.

        Uses the pipe-separated ID filter (``openalex:{id1}|{id2}|...``) to
        batch-fetch works in chunks of :data:`_REFERENCES_BATCH_SIZE`.

        Parameters
        ----------
        openalex_ids : list[str]
            OpenAlex work IDs (full URLs like
            ``https://openalex.org/W123``).

        Returns
        -------
        list[Paper]
            Parsed papers.
        """
        papers: list[Paper] = []
        if not openalex_ids:
            return papers

        for start in range(0, len(openalex_ids), _REFERENCES_BATCH_SIZE):
            batch = openalex_ids[start : start + _REFERENCES_BATCH_SIZE]
            id_filter = "|".join(batch)
            params: dict[str, Any] = {
                "filter": f"openalex:{id_filter}",
                "per-page": _PAGE_SIZE,
                "select": (
                    "id,doi,title,display_name,publication_date,authorships,"
                    "abstract_inverted_index,cited_by_count,open_access,locations,"
                    "primary_location,concepts,keywords,type,biblio"
                ),
            }
            try:
                response = self._get(_BASE_URL, params)
                data = response.json()
                for work in data.get("results") or []:
                    paper = self._parse_paper(work)
                    if paper is not None:
                        papers.append(paper)
            except Exception:
                logger.warning(
                    "Failed to fetch OpenAlex works batch (offset=%d, count=%d).",
                    start,
                    len(batch),
                )
        return papers

    def _fetch_cited_by_page(
        self,
        openalex_id: str,
        cursor: str,
    ) -> tuple[list[Paper], str | None]:
        """Fetch one page of papers that cite the given work.

        Parameters
        ----------
        openalex_id : str
            OpenAlex ID of the cited work.
        cursor : str
            Pagination cursor (``"*"`` for the first page).

        Returns
        -------
        tuple[list[Paper], str | None]
            Papers from this page and the next cursor (``None`` when done).
        """
        params: dict[str, Any] = {
            "filter": f"cites:{openalex_id}",
            "per-page": _PAGE_SIZE,
            "cursor": cursor,
            "select": (
                "id,doi,title,display_name,publication_date,authorships,"
                "abstract_inverted_index,cited_by_count,open_access,locations,"
                "primary_location,concepts,keywords,type,biblio"
            ),
        }
        try:
            response = self._get(_BASE_URL, params)
        except Exception:
            logger.warning(
                "Failed to fetch cited-by page for %s (cursor=%s).",
                openalex_id,
                cursor,
            )
            return [], None

        data = response.json()
        papers: list[Paper] = []
        for work in data.get("results") or []:
            paper = self._parse_paper(work)
            if paper is not None:
                papers.append(paper)

        meta = data.get("meta") or {}
        next_cursor = meta.get("next_cursor")
        results = data.get("results") or []
        if not next_cursor or len(results) < _PAGE_SIZE:
            next_cursor = None

        return papers, next_cursor

    def fetch_references(self, paper: Paper) -> list[Paper]:
        """Return papers cited *by* the given paper (backward snowballing).

        Queries OpenAlex for the full work record (which includes the
        ``referenced_works`` field) and then batch-fetches the referenced
        works to build full :class:`Paper` objects.

        Parameters
        ----------
        paper : Paper
            The paper whose references should be fetched.  Must have a DOI.

        Returns
        -------
        list[Paper]
            Papers referenced by *paper*, or an empty list on failure.
        """
        if not paper.doi:
            return []

        # Fetch the full work record to get referenced_works.
        url = f"{_BASE_URL}/doi:{paper.doi}"
        try:
            response = self._get(url, params={"select": "id,referenced_works"})
            data = response.json()
        except Exception:
            logger.warning("Failed to fetch OpenAlex work for DOI %s.", paper.doi)
            return []

        referenced_ids = data.get("referenced_works") or []
        if not referenced_ids:
            return []

        logger.debug(
            "OpenAlex: fetching %d references for DOI %s.",
            len(referenced_ids),
            paper.doi,
        )
        return self._fetch_works_by_ids(referenced_ids)

    def fetch_cited_by(self, paper: Paper) -> list[Paper]:
        """Return papers that cite the given paper (forward snowballing).

        Uses the OpenAlex ``cites`` filter to paginate through all papers
        that cite the given work.

        Parameters
        ----------
        paper : Paper
            The paper whose citing papers should be fetched.  Must have a DOI.

        Returns
        -------
        list[Paper]
            Papers that cite *paper*, or an empty list on failure.
        """
        if not paper.doi:
            return []

        openalex_id = self._resolve_openalex_id(paper)
        if not openalex_id:
            return []

        logger.debug("OpenAlex: fetching cited-by for %s.", openalex_id)

        all_papers: list[Paper] = []
        cursor: str | None = "*"

        while cursor is not None:
            page_papers, cursor = self._fetch_cited_by_page(openalex_id, cursor)
            all_papers.extend(page_papers)

        return all_papers

    def _parse_paper(self, work: Dict[str, Any]) -> Optional[Paper]:
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
        authors: list[Author] = []
        for authorship in work.get("authorships", []):
            author_info = authorship.get("author") or {}
            name = (author_info.get("display_name") or "").strip()
            if name:
                # OpenAlex provides institutions per authorship entry.
                institutions = authorship.get("institutions") or []
                affiliation_parts = [
                    (inst.get("display_name") or "").strip()
                    for inst in institutions
                    if isinstance(inst, dict) and (inst.get("display_name") or "").strip()
                ]
                affiliation = "; ".join(affiliation_parts) if affiliation_parts else None
                authors.append(Author(name=name, affiliation=affiliation))

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

        # Source – prefer a journal or conference venue over a repository.
        # OpenAlex ``source.type`` may be "journal", "conference", "repository",
        # "ebook platform", or "book series".  Repository sources (e.g.
        # institutional repos, Zenodo) should not be used as the paper's
        # publication source since they represent the *hosting location*, not
        # the actual venue.
        source: Optional[Source] = None
        source_data = _find_best_source(work)
        if source_data:
            pub_title = (source_data.get("display_name") or "").strip()
            if pub_title:
                issn_list = source_data.get("issn_l") or source_data.get("issn") or []
                issn = (
                    issn_list[0]
                    if isinstance(issn_list, list) and issn_list
                    else str(issn_list) if issn_list else None
                )
                raw_src_type = (source_data.get("type") or "").strip().lower()
                source_type = _OPENALEX_SOURCE_TYPE_MAP.get(raw_src_type)
                source = Source(title=pub_title, issn=issn, source_type=source_type)

        # When no formal source was found and the work is a preprint,
        # create a repository-type source from the repository location.
        if source is None:
            repo_source = _find_repository_source(work)
            if repo_source:
                repo_name = (repo_source.get("display_name") or "").strip()
                if repo_name:
                    source = Source(title=repo_name, source_type=SourceType.REPOSITORY)

        # Pages from biblio
        pages: Optional[str] = None
        biblio = work.get("biblio") or {}
        first_page = (biblio.get("first_page") or "").strip()
        last_page = (biblio.get("last_page") or "").strip()
        if first_page and last_page:
            pages = f"{first_page}\u2013{last_page}"
        elif first_page:
            pages = first_page

        # Infer paper_type from the work-level "type" field.
        raw_work_type = (work.get("type") or "").strip().lower()
        paper_type = _OPENALEX_PAPER_TYPE_MAP.get(raw_work_type)

        # OpenAlex classifies conference papers as work.type "article".
        # When the source is a conference venue, promote to INPROCEEDINGS.
        if (
            paper_type is PaperType.ARTICLE
            and source is not None
            and source.source_type is SourceType.CONFERENCE
        ):
            paper_type = PaperType.INPROCEEDINGS

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
        processed = 0

        # Cap results to at most 1 year in the future to avoid placeholder
        # dates (e.g. 2050-01-01) that some upstream metadata sources produce.
        _max_pub_date = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()

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
                    "primary_location,concepts,keywords,type,biblio"
                ),
            }

            # Inject the date cap into the existing filter string.
            existing_filter = params.get("filter", "")
            date_cap = f"to_publication_date:{_max_pub_date}"
            if existing_filter:
                params["filter"] = f"{existing_filter},{date_cap}"
            else:
                params["filter"] = date_cap

            try:
                response = self._get(_BASE_URL, params)
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

            processed += len(results)
            if progress_callback is not None:
                progress_callback(processed, total)

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
        all_papers: List[Paper] = []
        seen_keys: set[str] = set()

        for sub_query in expanded:
            # Use a fresh accumulator per sub-query so that any preceding
            # branch does not exhaust the budget and prevent later branches
            # from being fetched.  Each branch is allowed to return up to
            # max_papers results independently; the combined list is
            # deduplicated and truncated to max_papers at the very end.
            sub_papers: List[Paper] = []
            sub_params = self._query_builder.convert_query(sub_query)
            self._fetch_single_query(sub_params, max_papers, sub_papers, progress_callback)

            # Merge into the global accumulator, deduplicating across branches.
            for paper in sub_papers:
                key = paper.doi or paper.url or paper.title
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    all_papers.append(paper)

        return all_papers[:max_papers] if max_papers is not None else all_papers


def _find_best_source(work: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Select the best publication source from an OpenAlex work.

    OpenAlex distinguishes several source types (``journal``, ``conference``,
    ``repository``, ``ebook platform``, ``book series``).  Repository sources
    represent hosting locations (institutional repos, Zenodo, etc.) rather than
    the actual publication venue and should be avoided when a proper venue is
    available.

    The function scans all locations — starting with the primary one — and
    returns the first source whose type is **not** ``repository``.  If every
    source is a repository (or no source is present at all) it returns
    ``None``.

    Parameters
    ----------
    work : dict
        OpenAlex work metadata dictionary.

    Returns
    -------
    dict | None
        The chosen source dict, or ``None`` when no suitable source exists.
    """
    _EXCLUDED_SOURCE_TYPES = {"repository"}

    # Collect all candidate locations, primary first.
    locations: list[dict] = []
    primary = work.get("primary_location")
    if isinstance(primary, dict):
        locations.append(primary)

    for loc in work.get("locations") or []:
        if isinstance(loc, dict) and loc is not primary:
            locations.append(loc)

    for loc in locations:
        src = loc.get("source")
        if not isinstance(src, dict):
            continue
        src_type = (src.get("type") or "").strip().lower()
        if src_type and src_type in _EXCLUDED_SOURCE_TYPES:
            continue
        # Accept sources with a known non-repository type or no type at all
        # (missing type still beats a confirmed repository).
        if (src.get("display_name") or "").strip():
            return src

    return None


def _find_repository_source(work: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find a repository-type source when no formal venue is available.

    When ``_find_best_source`` yields ``None`` (i.e. the work is only hosted
    on repository platforms), this helper returns the first repository source
    so the caller can create a ``Source`` with ``source_type=REPOSITORY``.

    Parameters
    ----------
    work : dict
        OpenAlex work metadata dictionary.

    Returns
    -------
    dict | None
        A repository source dict, or ``None`` when none exists.
    """
    locations: list[dict] = []
    primary = work.get("primary_location")
    if isinstance(primary, dict):
        locations.append(primary)

    for loc in work.get("locations") or []:
        if isinstance(loc, dict) and loc is not primary:
            locations.append(loc)

    for loc in locations:
        src = loc.get("source")
        if not isinstance(src, dict):
            continue
        src_type = (src.get("type") or "").strip().lower()
        if src_type == "repository" and (src.get("display_name") or "").strip():
            return src

    return None


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
