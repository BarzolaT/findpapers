from __future__ import annotations

import datetime
import logging
from enum import Enum
from typing import Optional, Set, Union

from ..utils.merge import merge_authors, merge_value
from .author import Author
from .source import Source

logger = logging.getLogger(__name__)

# Maximum number of days into the future that a publication date is considered
# plausible.  Dates beyond this threshold are treated as data-quality errors
# from upstream APIs and silently replaced with ``None``.
_MAX_FUTURE_DAYS: int = 365

# DOI prefixes that belong to preprint servers and should be deprioritised
# in favour of a publisher-assigned DOI when merging two copies of the same work.
_PREPRINT_DOI_PREFIXES: frozenset[str] = frozenset(
    {
        "10.48550/arxiv.",  # arXiv
        "10.1101/",  # bioRxiv / medRxiv
        "10.2139/ssrn.",  # SSRN
        "10.5281/zenodo.",  # Zenodo
        "10.20944/preprints",  # Preprints.org
    }
)


def _is_preprint_doi(doi: str) -> bool:
    """Return ``True`` when *doi* belongs to a preprint server.

    Parameters
    ----------
    doi : str
        DOI string (without ``https://doi.org/`` prefix).

    Returns
    -------
    bool
        ``True`` for known preprint-server DOI prefixes.
    """
    lowered = doi.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _PREPRINT_DOI_PREFIXES)


def _merge_doi(base: str | None, incoming: str | None) -> str | None:
    """Merge two DOI values, preferring the non-preprint one.

    When both DOIs are present and exactly one of them belongs to a known
    preprint server, the publisher DOI is kept.  In all other cases the
    :func:`~findpapers.utils.merge.merge_value` default is used.

    Parameters
    ----------
    base : str | None
        The DOI already stored on the paper.
    incoming : str | None
        The DOI coming from the paper being merged in.

    Returns
    -------
    str | None
        The winning DOI.
    """
    if base is None:
        return incoming
    if incoming is None:
        return base

    base_is_preprint = _is_preprint_doi(base)
    incoming_is_preprint = _is_preprint_doi(incoming)

    if base_is_preprint and not incoming_is_preprint:
        return incoming
    if incoming_is_preprint and not base_is_preprint:
        return base

    # Both preprint, both publisher, or indistinguishable: fall back to default.
    return merge_value(base, incoming)


class PaperType(str, Enum):
    """Recognized paper types aligned with BibTeX entry types.

    Inheriting from :class:`str` makes each member compare equal to its string
    value, so code such as ``paper_type == "article"`` continues to work
    without modification.

    Each value matches the corresponding BibTeX entry type (lower-case).
    """

    ARTICLE = "article"
    """An article from a journal or magazine."""

    INBOOK = "inbook"
    """A chapter or section from a book."""

    INCOLLECTION = "incollection"
    """An article in a collection (e.g., book chapter with its own title)."""

    INPROCEEDINGS = "inproceedings"
    """A paper published in conference proceedings."""

    MANUAL = "manual"
    """Technical documentation or a manual."""

    MASTERSTHESIS = "mastersthesis"
    """A Masters thesis."""

    PHDTHESIS = "phdthesis"
    """A PhD thesis."""

    TECHREPORT = "techreport"
    """A technical report."""

    UNPUBLISHED = "unpublished"
    """A document that has not yet been formally published (e.g., preprint)."""


class Paper:
    """Represents a paper instance."""

    def __init__(
        self,
        title: str,
        abstract: str,
        authors: list[Author],
        source: Source | None,
        publication_date: datetime.date | None,
        url: Optional[str] = None,
        pdf_url: Optional[str] = None,
        doi: Optional[str] = None,
        citations: Optional[int] = None,
        keywords: Optional[Set[str]] = None,
        comments: Optional[str] = None,
        number_of_pages: Optional[int] = None,
        pages: Optional[str] = None,
        databases: Optional[Set[str]] = None,
        paper_type: Optional[Union[str, "PaperType"]] = None,
    ) -> None:
        """Create a Paper instance.

        Parameters
        ----------
        title : str
            Paper title.
        abstract : str
            Paper abstract.
        authors : list[Author]
            List of authors.
        source : Source | None
            Source where it was published.
        publication_date : datetime.date | None
            Publication date.
        url : str | None
            URL that references the paper.
        pdf_url : str | None
            Direct URL to PDF file.
        doi : str | None
            Paper DOI.
        citations : int | None
            Citations count.
        keywords : set[str] | None
            Keywords.
        comments : str | None
            Comments.
        number_of_pages : int | None
            Page count.
        pages : str | None
            Page range.
        databases : set[str] | None
            Databases where found.
        paper_type : str | PaperType | None
            BibTeX-aligned paper type (e.g. ``"article"``, ``"inproceedings"``).
            When a string is provided it is normalized to the matching
            :class:`PaperType` member; ``None`` means the type is unknown.

        Raises
        ------
        ValueError
            If title is missing.
        """
        if title is None or len(title) == 0:
            raise ValueError("Paper's title cannot be null")

        self.title = title
        self.abstract = abstract
        self.authors: list[Author] = list(authors or [])
        self.source = source
        self.publication_date = self._sanitize_date(publication_date)
        self.url = url
        self.pdf_url = pdf_url
        self.doi = doi
        self.citations = citations
        self.keywords = keywords if keywords is not None else set()
        self.comments = comments
        self.number_of_pages = number_of_pages
        self.pages = pages
        self.databases = databases if databases is not None else set()
        self.paper_type = paper_type  # type: ignore[assignment]

    @staticmethod
    def _sanitize_date(
        value: datetime.date | None,
    ) -> datetime.date | None:
        """Return *value* unchanged when plausible, otherwise ``None``.

        Dates more than :data:`_MAX_FUTURE_DAYS` in the future are considered
        data-quality errors from upstream APIs (e.g. OpenAlex placeholder
        dates like 2050-01-01) and are replaced with ``None``.

        Parameters
        ----------
        value : datetime.date | None
            The publication date to validate.

        Returns
        -------
        datetime.date | None
            The original date if plausible, otherwise ``None``.
        """
        if value is None:
            return None
        max_allowed = datetime.date.today() + datetime.timedelta(days=_MAX_FUTURE_DAYS)
        if value > max_allowed:
            logger.debug(
                "Discarding implausible future publication date %s "
                "(more than %d days from today).",
                value.isoformat(),
                _MAX_FUTURE_DAYS,
            )
            return None
        return value

    @property
    def paper_type(self) -> Optional[PaperType]:
        """Return the paper BibTeX type.

        Returns
        -------
        PaperType | None
            Normalized :class:`PaperType` member or ``None`` when unknown.
        """
        return self._paper_type

    @paper_type.setter
    def paper_type(self, value: Optional[Union[str, PaperType]]) -> None:
        """Normalize and set the paper type.

        Parameters
        ----------
        value : str | PaperType | None
            Raw type string or enum member to normalize.
        """
        if isinstance(value, PaperType):
            self._paper_type: Optional[PaperType] = value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            try:
                self._paper_type = PaperType(lowered)
            except ValueError:
                self._paper_type = None
        else:
            self._paper_type = None

    def add_database(self, database_name: str) -> None:
        """Add a database name where the paper was found.

        Parameters
        ----------
        database_name : str
            Database name.

        Returns
        -------
        None
        """
        if database_name:
            self.databases.add(database_name)

    def merge(self, paper: Paper) -> None:
        """Merge another paper into this one.

        Parameters
        ----------
        paper : Paper
            Another instance of the same paper.

        Returns
        -------
        None
        """
        # Prefer existing dates; if missing, use the incoming one.
        if self.publication_date is None:
            self.publication_date = paper.publication_date

        # Merge scalar fields using shared rules.
        self.title = merge_value(self.title, paper.title)
        self.doi = _merge_doi(self.doi, paper.doi)
        self.abstract = merge_value(self.abstract, paper.abstract)
        self.citations = merge_value(self.citations, paper.citations)
        self.comments = merge_value(self.comments, paper.comments)
        self.number_of_pages = merge_value(self.number_of_pages, paper.number_of_pages)
        self.pages = merge_value(self.pages, paper.pages)
        self.url = merge_value(self.url, paper.url)
        self.pdf_url = merge_value(self.pdf_url, paper.pdf_url)

        # Merge authors/keywords as collections while keeping uniqueness.
        # Authors use a token-aware merge to avoid duplicating the same person
        # when different sources represent the name as "First Last" vs "Last, First".
        self.authors = merge_authors(self.authors or [], paper.authors or [])
        self.keywords = merge_value(self.keywords, paper.keywords)

        # Always accumulate databases for traceability.
        self.databases |= paper.databases
        # Prefer the existing type; fall back to the incoming one when absent.
        if self.paper_type is None:
            self.paper_type = paper.paper_type
        if self.source is None:
            self.source = paper.source
        elif paper.source is not None:
            self.source.merge(paper.source)

    @classmethod
    def from_dict(cls, paper_dict: dict) -> "Paper":
        """Create a paper from a dict.

        Parameters
        ----------
        paper_dict : dict
            Paper dictionary.

        Returns
        -------
        Paper
            Paper instance.

        Raises
        ------
        ValueError
            If the title is missing.
        """
        title = paper_dict.get("title")
        if not isinstance(title, str) or not title:
            raise ValueError("Paper's title cannot be null")

        abstract = paper_dict.get("abstract") or ""
        if not isinstance(abstract, str):
            abstract = str(abstract)

        raw_authors = paper_dict.get("authors") or []
        if isinstance(raw_authors, (list, set, tuple)):
            authors = [Author.from_dict(author) for author in raw_authors]
        else:
            authors = [Author.from_dict(raw_authors)]

        source_data = paper_dict.get("source")
        source = Source.from_dict(source_data) if isinstance(source_data, dict) else None
        publication_date = paper_dict.get("publication_date")
        if isinstance(publication_date, str):
            try:
                publication_date = datetime.datetime.strptime(publication_date, "%Y-%m-%d").date()
            except ValueError:
                publication_date = None

        url = paper_dict.get("url")
        if url is not None and not isinstance(url, str):
            url = str(url)

        pdf_url = paper_dict.get("pdf_url")
        if pdf_url is not None and not isinstance(pdf_url, str):
            pdf_url = str(pdf_url)

        doi = paper_dict.get("doi")
        if doi is not None and not isinstance(doi, str):
            doi = str(doi)
        citations = paper_dict.get("citations")
        raw_keywords = paper_dict.get("keywords") or []
        if isinstance(raw_keywords, (list, set, tuple)):
            keywords = {str(keyword) for keyword in raw_keywords}
        else:
            keywords = {str(raw_keywords)} if raw_keywords else set()
        comments = paper_dict.get("comments")
        number_of_pages = paper_dict.get("number_of_pages")
        pages = paper_dict.get("pages")
        raw_databases = paper_dict.get("databases") or []
        if isinstance(raw_databases, (list, set, tuple)):
            databases = {str(database) for database in raw_databases}
        else:
            databases = {str(raw_databases)} if raw_databases else set()

        raw_paper_type = paper_dict.get("paper_type")
        paper_type = raw_paper_type if isinstance(raw_paper_type, str) else None

        return cls(
            title=title,
            abstract=abstract,
            authors=authors,
            source=source,
            publication_date=publication_date,
            url=url,
            pdf_url=pdf_url,
            doi=doi,
            citations=citations,
            keywords=keywords,
            comments=comments,
            number_of_pages=number_of_pages,
            pages=pages,
            databases=databases,
            paper_type=paper_type,
        )

    @staticmethod
    def to_dict(paper: "Paper") -> dict:
        """Convert a Paper to dict.

        Parameters
        ----------
        paper : Paper
            Paper instance.

        Returns
        -------
        dict
            Paper dictionary.
        """
        return {
            "title": paper.title,
            "abstract": paper.abstract,
            "authors": [author.to_dict() for author in paper.authors],
            "source": (Source.to_dict(paper.source) if paper.source is not None else None),
            "publication_date": (
                paper.publication_date.isoformat() if paper.publication_date is not None else None
            ),
            "url": paper.url,
            "pdf_url": paper.pdf_url,
            "doi": paper.doi,
            "citations": paper.citations,
            "keywords": sorted(paper.keywords),
            "comments": paper.comments,
            "number_of_pages": paper.number_of_pages,
            "pages": paper.pages,
            "databases": sorted(paper.databases),
            "paper_type": paper.paper_type.value if paper.paper_type is not None else None,
        }
