"""arXiv searcher implementation."""

from __future__ import annotations

import datetime
import logging
import re
from collections.abc import Callable
from xml.etree import ElementTree as ET

from findpapers.connectors.search_base import SearchConnectorBase
from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import Query
from findpapers.core.search_result import Database
from findpapers.core.source import Source, SourceType
from findpapers.query.builder import QueryBuilder
from findpapers.query.builders.arxiv import ArxivQueryBuilder

logger = logging.getLogger(__name__)

_BASE_URL = "http://export.arxiv.org/api/query"
_PAGE_SIZE = 100
# arXiv recommends at least 3 seconds between requests
_MIN_REQUEST_INTERVAL = 3.0
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# Regex to extract the arXiv paper ID from the Atom <id> element.
# Example: http://arxiv.org/abs/1706.03762v5 → 1706.03762
_ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/([\d.]+)", re.IGNORECASE)

# Mapping from SourceType to PaperType for arXiv entries.
_ARXIV_PAPER_TYPE_MAP: dict[SourceType, PaperType] = {
    SourceType.JOURNAL: PaperType.ARTICLE,
    SourceType.CONFERENCE: PaperType.INPROCEEDINGS,
    SourceType.BOOK: PaperType.INBOOK,
    SourceType.REPOSITORY: PaperType.UNPUBLISHED,
}


class ArxivConnector(SearchConnectorBase):
    """Connector for the arXiv preprint database.

    Uses the arXiv Atom Feed API:
    https://info.arxiv.org/help/api/user-manual.html

    Rate limit: 3 seconds between requests (as recommended by arXiv).
    """

    def __init__(self, query_builder: ArxivQueryBuilder | None = None) -> None:
        """Create an arXiv searcher.

        Parameters
        ----------
        query_builder : ArxivQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`ArxivQueryBuilder` is created automatically.
        """
        super().__init__()
        self._query_builder: ArxivQueryBuilder = query_builder or ArxivQueryBuilder()

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return Database.ARXIV.value

    @property
    def query_builder(self) -> QueryBuilder:
        """Return the arXiv query builder.

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

    @staticmethod
    def _parse_date(date_str: str | None) -> str | None:
        """Parse ISO-8601 date string to ``YYYY-MM-DD``.

        Parameters
        ----------
        date_str : str | None
            Raw date string from API.

        Returns
        -------
        str | None
            Formatted date or ``None`` when input is empty.
        """
        if not date_str:
            return None
        return date_str[:10]

    def _parse_paper(self, entry: ET.Element) -> Paper | None:
        """Parse a single Atom entry element into a :class:`Paper`.

        Parameters
        ----------
        entry : ET.Element
            Atom entry XML element.

        Returns
        -------
        Paper | None
            Parsed paper or ``None`` when required fields are missing.
        """
        title_el = entry.find("atom:title", _NS)
        abstract_el = entry.find("atom:summary", _NS)
        if title_el is None or not (title_el.text or "").strip():
            return None

        title = (title_el.text or "").strip().replace("\n", " ")
        abstract = (
            (abstract_el.text or "").strip().replace("\n", " ") if abstract_el is not None else ""
        )

        # Authors
        authors: list[Author] = []
        for author_el in entry.findall("atom:author", _NS):
            name_el = author_el.find("atom:name", _NS)
            if name_el is None or not (name_el.text or "").strip():
                continue
            name = (name_el.text or "").strip()
            affiliation_parts = [
                (aff_el.text or "").strip()
                for aff_el in author_el.findall("arxiv:affiliation", _NS)
                if aff_el is not None and (aff_el.text or "").strip()
            ]
            affiliation = "; ".join(affiliation_parts) if affiliation_parts else None
            authors.append(Author(name=name, affiliation=affiliation))

        # Published date
        published_el = entry.find("atom:published", _NS)
        pub_date_str = _parse_date_from_str(
            (published_el.text or "").strip() if published_el is not None else None
        )

        # DOI — prefer the explicit <arxiv:doi> element (publisher DOI).
        # When absent, derive the canonical arXiv DOI from the entry ID.
        doi: str | None = None
        doi_el = entry.find("arxiv:doi", _NS)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()

        # URL - prefer HTML link
        url: str | None = None
        for link_el in entry.findall("atom:link", _NS):
            rel = link_el.get("rel", "")
            href = link_el.get("href", "")
            if rel == "alternate" and href:
                url = href
                break
        if url is None:
            id_el = entry.find("atom:id", _NS)
            if id_el is not None and id_el.text:
                url = id_el.text.strip()

        # Derive arXiv DOI when none was provided by the API.
        # The canonical DOI format is 10.48550/arXiv.<id>, e.g.
        # http://arxiv.org/abs/1706.03762v5 → 10.48550/arXiv.1706.03762
        if doi is None and url:
            m = _ARXIV_ID_RE.search(url)
            if m:
                doi = f"10.48550/arXiv.{m.group(1)}"

        # PDF URL
        pdf_url: str | None = None
        for link_el in entry.findall("atom:link", _NS):
            title_attr = link_el.get("title", "")
            href = link_el.get("href", "")
            if title_attr == "pdf" and href:
                pdf_url = href
                break

        # Journal ref → source.
        # Papers with a journal reference were formally published in a journal.
        journal_ref_el = entry.find("arxiv:journal_ref", _NS)
        source: Source | None = None
        has_journal_ref = (
            journal_ref_el is not None and journal_ref_el.text and journal_ref_el.text.strip()
        )
        if has_journal_ref:
            ref_text = journal_ref_el.text.strip()  # type: ignore[union-attr]
            source = Source(
                title=ref_text,
                source_type=_infer_source_type_from_journal_ref(ref_text),
            )
        else:
            # Paper is an arXiv preprint without a formal publication venue.
            source = Source(title="arXiv", source_type=SourceType.REPOSITORY)

        # Comments — optional free-text note (e.g. "39 pages, 14 figures")
        comment: str | None = None
        comment_el = entry.find("arxiv:comment", _NS)
        if comment_el is not None and comment_el.text and comment_el.text.strip():
            comment = comment_el.text.strip()

        # Infer paper_type from source_type.
        paper_type: PaperType | None = None
        if source is not None and source.source_type is not None:
            paper_type = _ARXIV_PAPER_TYPE_MAP.get(source.source_type)

        try:
            paper = Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                source=source,
                publication_date=pub_date_str,
                url=url,
                pdf_url=pdf_url,
                doi=doi,
                comments=comment,
                databases={self.name},
                paper_type=paper_type,
            )
        except ValueError:
            return None

        return paper

    def _fetch_papers(
        self,
        query: Query,
        max_papers: int | None,
        progress_callback: Callable[[int, int | None], None] | None,
        since: datetime.date | None = None,
        until: datetime.date | None = None,
    ) -> list[Paper]:
        """Fetch papers from arXiv with pagination and rate limiting.

        Parameters
        ----------
        query : Query
            Validated query object.
        max_papers : int | None
            Maximum papers to retrieve.
        progress_callback : Callable[[int, int | None], None] | None
            Progress callback.
        since : datetime.date | None
            Only return papers submitted on or after this date.
        until : datetime.date | None
            Only return papers submitted on or before this date.

        Returns
        -------
        list[Paper]
            Retrieved papers.
        """
        arxiv_query = self._query_builder.convert_query(query)

        # Append arXiv submittedDate range filter when date bounds are given.
        if since or until:
            from_date = since.strftime("%Y%m%d") + "0000" if since else "000001010000"
            to_date = until.strftime("%Y%m%d") + "2359" if until else "999912312359"
            date_filter = f"submittedDate:[{from_date}+TO+{to_date}]"
            if arxiv_query:
                arxiv_query = f"{arxiv_query}+AND+{date_filter}"
            else:
                arxiv_query = date_filter
        papers: list[Paper] = []
        processed = 0
        offset = 0

        while True:
            remaining = (max_papers - len(papers)) if max_papers is not None else _PAGE_SIZE
            page_size = min(_PAGE_SIZE, remaining)

            params = {
                "search_query": arxiv_query,
                "start": offset,
                "max_results": page_size,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            try:
                response = self._get(_BASE_URL, params)
            except Exception:
                logger.exception("arXiv request failed (offset=%d).", offset)
                break

            tree = ET.fromstring(response.text)

            total_results_el = tree.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
            total: int | None = None
            if total_results_el is not None and total_results_el.text:
                try:
                    total = int(total_results_el.text.strip())
                except ValueError:
                    pass

            entries = tree.findall("atom:entry", _NS)
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


# ---------------------------------------------------------------------------
# Heuristic patterns to infer source type from arXiv journal_ref text
# ---------------------------------------------------------------------------

_CONFERENCE_RE = re.compile(
    r"\b(?:proceedings?|conference|workshop|symposium)\b" r"|\b(?:proc|conf|symp)\.",
    re.IGNORECASE,
)

_BOOK_RE = re.compile(
    r"\b(?:lecture\s+notes|book|chapter)\b",
    re.IGNORECASE,
)

_JOURNAL_RE = re.compile(
    r"\b(?:"
    r"journal|review[s]?|letters?|transactions?|annals?|bulletin"
    r"|magazine"
    r")\b"
    r"|\bj\."
    r"|\brev\."
    r"|\blett\."
    r"|\btrans\."
    r"|\bann\."
    r"|\bbull\."
    r"|\bmag\.",
    re.IGNORECASE,
)


def _infer_source_type_from_journal_ref(text: str) -> SourceType | None:
    """Infer a :class:`SourceType` from a free-text ``journal_ref`` string.

    The function applies keyword heuristics in priority order:

    1. **CONFERENCE** – contains words like *proceedings*, *conference*,
       *workshop*, or *symposium*.
    2. **BOOK** – contains *lecture notes*, *book*, or *chapter*.
    3. **JOURNAL** – contains common journal indicators such as *journal*,
       *review*, *letters*, *transactions*, abbreviated forms like
       *J.*, *Rev.*, *Lett.*, etc.

    If no pattern matches the text is left unclassified (``None``).

    Parameters
    ----------
    text : str
        The ``journal_ref`` value from an arXiv entry.

    Returns
    -------
    SourceType | None
        Inferred source type or ``None`` when no rule matches.
    """
    if _CONFERENCE_RE.search(text):
        return SourceType.CONFERENCE
    if _BOOK_RE.search(text):
        return SourceType.BOOK
    if _JOURNAL_RE.search(text):
        return SourceType.JOURNAL
    return None


def _parse_date_from_str(date_str: str | None) -> datetime.date | None:
    """Parse a date string into a :class:`datetime.date`.

    Parameters
    ----------
    date_str : str | None
        Raw date string (ISO-8601 or ``YYYY-MM-DD`` prefix).

    Returns
    -------
    datetime.date | None
        Parsed date or ``None`` when input is empty / unparseable.
    """
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str[:10])
    except ValueError:
        return None
