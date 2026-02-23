"""Utilities for fetching paper metadata from the CrossRef API.

CrossRef is the authoritative DOI registration agency and provides a free,
key-less REST API that returns rich structured metadata for most academic
DOIs.  This module wraps the ``/works/{doi}`` endpoint and converts the
response into a :class:`~findpapers.core.paper.Paper` instance ready for
merging.

API documentation: https://api.crossref.org/swagger-ui/index.html
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Optional
from urllib.parse import quote as _url_quote

import requests

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.source import Source, SourceType

logger = logging.getLogger(__name__)

_CROSSREF_API_URL = "https://api.crossref.org/works"

# Polite-pool header — CrossRef grants higher rate-limits when a contact
# e-mail is provided via the ``mailto`` query parameter or ``User-Agent``.
_CROSSREF_USER_AGENT = (
    "findpapers/1.0 (https://github.com/jonatasgrosman/findpapers; "
    "mailto:findpapers@users.noreply.github.com)"
)

# Mapping from CrossRef ``type`` values to :class:`SourceType`.
_CROSSREF_TYPE_MAP: dict[str, SourceType] = {
    "journal-article": SourceType.JOURNAL,
    "proceedings-article": SourceType.CONFERENCE,
    "book": SourceType.BOOK,
    "book-chapter": SourceType.BOOK,
    "monograph": SourceType.BOOK,
    "edited-book": SourceType.BOOK,
    "book-section": SourceType.BOOK,
    "book-part": SourceType.BOOK,
    "reference-book": SourceType.BOOK,
    "posted-content": SourceType.REPOSITORY,
    "dissertation": SourceType.OTHER,
    "report": SourceType.OTHER,
    "dataset": SourceType.OTHER,
    "peer-review": SourceType.OTHER,
    "standard": SourceType.OTHER,
    "component": SourceType.OTHER,
}

# Simple regex to strip JATS/HTML tags from CrossRef abstract text.
_TAG_RE = re.compile(r"<[^>]+>")


def fetch_crossref_work(doi: str, timeout: float | None = None) -> dict[str, Any] | None:
    """Fetch the CrossRef ``/works/{doi}`` record.

    Parameters
    ----------
    doi : str
        Bare DOI (without ``https://doi.org/`` prefix), e.g. ``10.1038/nature12373``.
    timeout : float | None
        HTTP request timeout in seconds.  ``None`` uses the ``requests`` default.

    Returns
    -------
    dict[str, Any] | None
        The ``message`` portion of the CrossRef response, or ``None`` when the
        DOI is not found or the request fails.

    Raises
    ------
    requests.RequestException
        On non-404 HTTP errors (propagated so the caller can decide on retries).
    """
    url = f"{_CROSSREF_API_URL}/{_url_quote(doi, safe='')}"
    logger.debug("CrossRef GET %s", url)
    response = requests.get(
        url,
        headers={"User-Agent": _CROSSREF_USER_AGENT},
        timeout=timeout,
    )
    if response.status_code == 404:
        logger.debug("CrossRef: DOI %s not found (404)", doi)
        return None
    response.raise_for_status()
    data = response.json()
    return data.get("message")


def _parse_crossref_date(work: dict[str, Any]) -> datetime.date | None:
    """Extract the best publication date from a CrossRef work record.

    CrossRef stores dates in several fields, each as
    ``{"date-parts": [[year, month, day]]}``.  Not all parts are always
    present, so missing month/day default to 1.

    Priority order: ``published-print`` → ``published-online`` →
    ``published`` → ``issued`` → ``created``.

    Parameters
    ----------
    work : dict[str, Any]
        CrossRef work JSON (the ``message`` dict).

    Returns
    -------
    datetime.date | None
        Parsed date, or ``None`` when no usable date field is available.
    """
    for field in (
        "published-print",
        "published-online",
        "published",
        "issued",
        "created",
    ):
        date_obj = work.get(field)
        if not date_obj or not isinstance(date_obj, dict):
            continue
        parts = date_obj.get("date-parts")
        if not parts or not isinstance(parts, list) or not parts[0]:
            continue
        nums = parts[0]
        if not isinstance(nums, list) or not nums:
            continue
        try:
            year = int(nums[0])
            month = int(nums[1]) if len(nums) > 1 else 1
            day = int(nums[2]) if len(nums) > 2 else 1
            return datetime.date(year, month, day)
        except (ValueError, TypeError):
            continue
    return None


def _parse_crossref_authors(work: dict[str, Any]) -> list[Author]:
    """Parse authors from a CrossRef work record.

    Each author entry contains ``given`` and ``family`` name fields, and
    optionally an ``affiliation`` list.

    Parameters
    ----------
    work : dict[str, Any]
        CrossRef work JSON.

    Returns
    -------
    list[Author]
        Author objects with affiliations when available.
    """
    authors: list[Author] = []
    for entry in work.get("author", []):
        if not isinstance(entry, dict):
            continue
        given = (entry.get("given") or "").strip()
        family = (entry.get("family") or "").strip()
        if not family:
            # Some records have only ``name`` (e.g. organisational authors).
            name = (entry.get("name") or "").strip()
        else:
            name = f"{given} {family}".strip() if given else family

        if not name:
            continue

        # Affiliations — CrossRef stores them as [{"name": "..."}].
        aff_parts: list[str] = []
        for aff in entry.get("affiliation", []):
            if isinstance(aff, dict):
                aff_name = (aff.get("name") or "").strip()
                if aff_name:
                    aff_parts.append(aff_name)
        affiliation = "; ".join(aff_parts) if aff_parts else None
        authors.append(Author(name=name, affiliation=affiliation))
    return authors


def _strip_jats_tags(text: str) -> str:
    """Remove JATS/HTML markup from CrossRef abstract text.

    CrossRef often returns abstracts wrapped in JATS XML tags such as
    ``<jats:p>`` or ``<jats:title>``.

    Parameters
    ----------
    text : str
        Raw abstract text potentially containing XML tags.

    Returns
    -------
    str
        Plain text with tags removed.
    """
    return _TAG_RE.sub("", text).strip()


def _parse_crossref_keywords(work: dict[str, Any]) -> set[str]:
    """Extract keywords/subjects from a CrossRef work record.

    CrossRef stores keywords in the ``subject`` field (list of strings).

    Parameters
    ----------
    work : dict[str, Any]
        CrossRef work JSON.

    Returns
    -------
    set[str]
        Keyword set, possibly empty.
    """
    keywords: set[str] = set()
    for subj in work.get("subject", []):
        if isinstance(subj, str) and subj.strip():
            keywords.add(subj.strip())
    return keywords


def _parse_crossref_pdf_url(work: dict[str, Any]) -> str | None:
    """Extract a direct PDF link from CrossRef ``link`` entries.

    Parameters
    ----------
    work : dict[str, Any]
        CrossRef work JSON.

    Returns
    -------
    str | None
        PDF URL, or ``None`` when no PDF link is available.
    """
    for link in work.get("link", []):
        if not isinstance(link, dict):
            continue
        content_type = (link.get("content-type") or "").lower()
        url = (link.get("URL") or "").strip()
        if "pdf" in content_type and url:
            return url
    return None


def build_paper_from_crossref(work: dict[str, Any]) -> Paper | None:
    """Build a :class:`~findpapers.core.paper.Paper` from a CrossRef work record.

    Parameters
    ----------
    work : dict[str, Any]
        The ``message`` dict returned by :func:`fetch_crossref_work`.

    Returns
    -------
    Paper | None
        Populated paper, or ``None`` when required fields (title) are missing.
    """
    if not work:
        return None

    # Title — CrossRef returns it as a list of strings.
    titles = work.get("title") or []
    title = titles[0].strip() if isinstance(titles, list) and titles else ""
    if not title:
        return None

    # Abstract
    raw_abstract = (work.get("abstract") or "").strip()
    abstract = _strip_jats_tags(raw_abstract) if raw_abstract else ""

    # DOI
    doi: Optional[str] = (work.get("DOI") or "").strip() or None

    # Authors
    authors = _parse_crossref_authors(work)

    # Publication date
    publication_date = _parse_crossref_date(work)

    # Keywords / subjects
    keywords = _parse_crossref_keywords(work)

    # Citations count
    citations: Optional[int] = work.get("is-referenced-by-count")

    # Page range
    pages: Optional[str] = (work.get("page") or "").strip() or None

    # Number of pages — not directly available, but can be inferred from
    # page range when it's in "first-last" format.
    number_of_pages: Optional[int] = None

    # PDF URL
    pdf_url = _parse_crossref_pdf_url(work)

    # URL — use the DOI URL as landing page.
    url: Optional[str] = (work.get("URL") or "").strip() or None

    # Source (journal, conference, book, etc.)
    source: Optional[Source] = None
    container_titles = work.get("container-title") or []
    source_title = (
        container_titles[0].strip()
        if isinstance(container_titles, list) and container_titles
        else ""
    )
    if source_title:
        # ISSN — CrossRef returns a list of ISSNs.
        issn_list = work.get("ISSN") or []
        issn = issn_list[0] if isinstance(issn_list, list) and issn_list else None

        # ISBN
        isbn_list = work.get("ISBN") or []
        isbn = isbn_list[0] if isinstance(isbn_list, list) and isbn_list else None

        # Publisher
        publisher = (work.get("publisher") or "").strip() or None

        # Source type
        crossref_type = (work.get("type") or "").strip().lower()
        source_type = _CROSSREF_TYPE_MAP.get(crossref_type)

        source = Source(
            title=source_title,
            issn=issn,
            isbn=isbn,
            publisher=publisher,
            source_type=source_type,
        )

    return Paper(
        title=title,
        abstract=abstract,
        authors=authors,
        source=source,
        publication_date=publication_date,
        url=url,
        pdf_url=pdf_url,
        doi=doi,
        citations=citations,
        keywords=keywords or None,
        pages=pages,
        number_of_pages=number_of_pages,
    )
