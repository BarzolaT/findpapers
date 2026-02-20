"""Utilities for enriching papers by scraping metadata from web pages."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Iterable

import requests
from lxml import html
from lxml.html import HtmlElement

from findpapers.core.paper import Paper, PaperType
from findpapers.core.source import Source
from findpapers.utils.http_headers import get_browser_headers

logger = logging.getLogger(__name__)

# Metadata keys searched in priority order for each field.
TITLE_META_KEYS = [
    "citation_title",
    "dc.title",
    "dc.title.alternative",
    "og:title",
    "twitter:title",
    "title",
]
ABSTRACT_META_KEYS = [
    "citation_abstract",
    "dc.description",
    "dc.description.abstract",
    "description",
    "og:description",
    "twitter:description",
]
AUTHOR_META_KEYS = [
    "citation_author",
    "citation_authors",  # PubMed uses the plural form (semicolon-separated)
    "dc.creator",
    "dc.creator.personalname",  # OpenAlex, Scopus, SemanticScholar
    "dc.contributor",
    "author",
]
DOI_META_KEYS = [
    "citation_doi",
    "dc.identifier",
    "dc.identifier.doi",  # OpenAlex, Scopus
    "doi",
    "prism.doi",
]
KEYWORDS_META_KEYS = [
    "citation_keywords",
    "citation_keyword",  # SemanticScholar uses the singular form
    "dc.subject",  # OpenAlex, SemanticScholar
    "book:tag",  # Scopus book chapters
    "keywords",
    "article:tag",
]
DATE_META_KEYS = [
    "citation_publication_date",
    "citation_date",
    "dc.date",
    "dc.date.issued",  # OpenAlex, Scopus, SemanticScholar
    "article:published_time",
    "prism.publicationdate",
    "citation_online_date",  # arXiv and others; used as last-resort fallback
]
PUBLICATION_TITLE_KEYS = [
    "citation_journal_title",
    "citation_conference_title",
    "citation_book_title",
    "citation_inbook_title",  # Scopus book chapters
]
PUBLICATION_PUBLISHER_KEYS = [
    "citation_publisher",
    "dc.publisher",
]
PUBLICATION_ISSN_KEYS = [
    "citation_issn",
    "prism.issn",
]
PUBLICATION_ISBN_KEYS = [
    "citation_isbn",
    "prism.isbn",
]
PDF_URL_KEYS = [
    "citation_pdf_url",
]

# Keys used to build the page-range and page-count fields on Paper.
_FIRSTPAGE_KEY = "citation_firstpage"
_LASTPAGE_KEY = "citation_lastpage"
_NUM_PAGES_KEY = "citation_num_pages"

# Preprint server names to avoid treating them as formal publications.
_PREPRINT_SERVERS = {"biorxiv", "medrxiv", "arxiv"}

# doi.org URL prefixes that some databases add before the bare DOI.
_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)

# Regex to locate the IEEE Xplore JS-embedded metadata blob.
_IEEE_META_RE = re.compile(
    r"xplGlobal\.document\.metadata\s*=\s*(\{.*?\});",
    re.DOTALL,
)


def fetch_metadata(url: str, timeout: float | None = None) -> dict[str, Any] | None:
    """Fetch HTML metadata from a URL.

    Parameters
    ----------
    url : str
        URL to fetch.
    timeout : float | None
        Request timeout in seconds.

    Returns
    -------
    dict[str, Any] | None
        Parsed metadata dict, or ``None`` when the response is not HTML.

    Raises
    ------
    requests.RequestException
        If the HTTP request fails.
    """
    logger.debug("GET %s", url)
    response = requests.get(
        url, headers=get_browser_headers(), timeout=timeout, allow_redirects=True
    )
    content_type = response.headers.get("content-type", "")
    logger.debug(
        "<- %s %s | content-type: %s | %d bytes",
        response.status_code,
        response.reason,
        content_type.split(";")[0].strip() or "unknown",
        len(response.content),
    )
    response.raise_for_status()
    if "text/html" not in content_type.lower():
        return None
    return extract_metadata_from_html(response.text)


def extract_metadata_from_html(content: str) -> dict[str, Any]:
    """Extract ``<meta>`` tag data and supplementary JS-embedded data from raw HTML.

    In addition to standard ``<meta>`` tags the function also attempts to
    extract metadata from IEEE Xplore's JS-embedded ``xplGlobal.document.metadata``
    JSON blob (IEEE does not use ``<meta>`` tags for most fields).  ``<meta>``
    tag values always take precedence over JS-derived values.

    Key normalisation applied:

    * All keys are lower-cased.
    * Dublin Core colon-form prefixes are mapped to dot-form
      (``dc:creator`` → ``dc.creator``) so they match the
      standard key lists used throughout the pipeline.

    Parameters
    ----------
    content : str
        Raw HTML content.

    Returns
    -------
    dict[str, Any]
        Mapping of normalised metadata key to value (or list of values when
        the same key appears multiple times).
    """
    if not content or not content.strip():
        return {}
    doc = html.fromstring(content)
    metadata: dict[str, Any] = {}
    elements = doc.xpath("//meta[@name or @property or @itemprop]")
    if not isinstance(elements, list):
        return metadata
    for element in elements:
        if not isinstance(element, HtmlElement):
            continue
        raw_key = (
            (element.get("name") or element.get("property") or element.get("itemprop") or "")
            .strip()
            .lower()
        )
        # Normalise Dublin Core colon-form (dc:creator → dc.creator) while
        # preserving other colon-prefixed namespaces such as og:title.
        if raw_key.startswith("dc:"):
            raw_key = "dc." + raw_key[3:]
        value = (element.get("content") or "").strip()
        if not raw_key or not value:
            continue
        # Preserve multiple values for the same key as a list.
        if raw_key in metadata:
            if not isinstance(metadata[raw_key], list):
                metadata[raw_key] = [metadata[raw_key]]
            metadata[raw_key].append(value)
        else:
            metadata[raw_key] = value
    # Supplement with IEEE-specific JS-embedded metadata.  Meta tag values
    # already in the dict take priority over JS-derived values.
    _merge_ieee_metadata(content, metadata)
    return metadata


def _merge_ieee_metadata(content: str, metadata: dict[str, Any]) -> None:
    """Extract IEEE Xplore JS-blob metadata and merge into *metadata* in-place.

    IEEE Xplore pages embed all structured data inside a
    ``xplGlobal.document.metadata`` JavaScript object rather than in
    ``<meta>`` tags.  This helper finds and parses that blob, then maps
    fields onto the standard ``citation_*`` key names used throughout the
    enrichment pipeline.

    Only keys not already present in *metadata* are written, so that real
    ``<meta>`` tag values always take precedence.

    Parameters
    ----------
    content : str
        Raw HTML page content.
    metadata : dict[str, Any]
        Metadata dict to update in-place.

    Returns
    -------
    None
    """
    match = _IEEE_META_RE.search(content)
    if not match:
        return
    try:
        data: dict = json.loads(match.group(1))
    except Exception:  # noqa: BLE001
        return

    def _set_if_absent(key: str, value: Any) -> None:
        """Write *key*/*value* only when key is absent and value is truthy."""
        if key not in metadata and value:
            metadata[key] = value

    # Authors — stored as a list so _parse_authors handles it correctly.
    authors = [a.get("name", "").strip() for a in data.get("authors", []) if a.get("name")]
    if authors:
        _set_if_absent("citation_author", authors if len(authors) > 1 else authors[0])

    _set_if_absent("citation_doi", data.get("doi"))
    _set_if_absent("citation_title", data.get("title") or data.get("displayDocTitle"))
    _set_if_absent("citation_abstract", data.get("abstract"))

    # Keywords — flatten all keyword groups from the nested structure.
    kw_list: list[str] = []
    for kw_group in data.get("keywords", []):
        kw_list.extend(kw_group.get("kwd", []))
    if kw_list:
        _set_if_absent("citation_keywords", ", ".join(kw_list))

    # Publication title — choose the right citation key based on content type.
    pub_title = data.get("displayPublicationTitle") or data.get("publicationTitle")
    if pub_title:
        if data.get("isJournal") or data.get("contentType", "").lower() == "periodicals":
            _set_if_absent("citation_journal_title", pub_title)
        elif data.get("isConference"):
            _set_if_absent("citation_conference_title", pub_title)
        elif data.get("isBook") or data.get("isBookWithoutChapters"):
            _set_if_absent("citation_book_title", pub_title)
        else:
            _set_if_absent("citation_journal_title", pub_title)

    _set_if_absent("citation_volume", data.get("volume"))
    _set_if_absent("citation_firstpage", data.get("startPage"))
    _set_if_absent("citation_lastpage", data.get("endPage"))
    _set_if_absent("citation_publication_date", data.get("publicationDate"))

    # PDF URL — prepend domain for relative paths.
    pdf_path = data.get("pdfPath") or data.get("pdfUrl")
    if pdf_path and str(pdf_path).startswith("/"):
        _set_if_absent("citation_pdf_url", f"https://ieeexplore.ieee.org{pdf_path}")

    # ISSN — pick the first available value.
    for issn_entry in data.get("issn", []):
        val = issn_entry.get("value")
        if val:
            _set_if_absent("citation_issn", val)
            break

    _set_if_absent("citation_publisher", data.get("publisher"))


def _pick_metadata_value(metadata: dict[str, Any], keys: Iterable[str]) -> str | None:
    """Return the first non-empty value for any of the candidate keys.

    Parameters
    ----------
    metadata : dict[str, Any]
        Metadata mapping.
    keys : Iterable[str]
        Candidate keys in priority order.

    Returns
    -------
    str | None
        First matched value, or ``None``.
    """
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            values = [str(item).strip() for item in value if item]
            selected = max(values, key=len, default=None)
        else:
            selected = str(value).strip() if value is not None else None
        if selected:
            return selected
    return None


def _parse_date(value: str | None) -> date | None:
    """Parse a date string into a :class:`datetime.date`.

    Tries several common metadata date formats in order.

    Parameters
    ----------
    value : str | None
        Date string.

    Returns
    -------
    date | None
        Parsed date, or ``None`` when parsing fails.
    """
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _normalize_doi(raw: str) -> str | None:
    """Strip doi.org URL prefixes and return a bare DOI, or ``None`` if invalid.

    Parameters
    ----------
    raw : str
        Raw DOI string (may include a ``https://doi.org/`` prefix).

    Returns
    -------
    str | None
        Bare DOI starting with ``10.``, or ``None`` when the value is not a
        recognisable DOI.
    """
    value = raw.strip()
    for prefix in _DOI_URL_PREFIXES:
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    return value if value.startswith("10.") else None


def _parse_keywords(value: str | list | None) -> set[str]:
    """Parse keyword metadata into a set of strings.

    Handles three forms:

    * ``list``: already split (e.g. from multiple ``dc.subject`` meta tags);
      each item may itself be a comma- or semicolon-delimited string.
    * ``str`` with commas or semicolons: a delimited keyword string.
    * plain ``str``: a single keyword.

    Parameters
    ----------
    value : str | list | None
        Raw keyword data.

    Returns
    -------
    set[str]
        Parsed, stripped keyword set.
    """
    if not value:
        return set()
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result |= _parse_keywords(item)
        return result
    if "," in value:
        parts = value.split(",")
    elif ";" in value:
        parts = value.split(";")
    else:
        parts = [value]
    return {part.strip() for part in parts if part.strip()}


def _parse_authors(value: Any) -> list[str]:
    """Normalise author metadata into a flat list of strings.

    Handles three forms:

    * ``list``: already split, e.g. from multiple ``citation_author`` meta
      tags.  Each list item may itself be semicolon-separated.
    * ``str`` with semicolons: PubMed-style ``"Wang Y;Tian J;..."``.
    * plain ``str``: a single author name.

    Parameters
    ----------
    value : Any
        Raw author data (str, list, or ``None``).

    Returns
    -------
    list[str]
        Stripped, deduplicated author names in original order.
    """
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            # Each list item may itself be semicolon-separated.
            for part in str(item).split(";"):
                name = part.strip()
                if name and name not in seen:
                    result.append(name)
                    seen.add(name)
        return result
    # Single string — split on semicolons.
    return [part.strip() for part in str(value).split(";") if part.strip()]


def build_paper_from_metadata(metadata: dict[str, Any], page_url: str) -> Paper | None:
    """Build a :class:`~findpapers.core.paper.Paper` from extracted metadata.

    Parameters
    ----------
    metadata : dict[str, Any]
        Metadata extracted from the page.
    page_url : str
        Final landing-page URL (used as a source URL and fallback).

    Returns
    -------
    Paper | None
        Populated paper instance, or ``None`` when required fields are absent.
    """
    title = _pick_metadata_value(metadata, TITLE_META_KEYS)
    if not title:
        return None

    abstract = _pick_metadata_value(metadata, ABSTRACT_META_KEYS)

    # DOI — try each candidate key in priority order; normalise URL prefixes.
    doi: str | None = None
    for doi_key in DOI_META_KEYS:
        raw = metadata.get(doi_key)
        if isinstance(raw, list):
            raw = max((str(v).strip() for v in raw if v), key=len, default=None)
        if raw:
            doi = _normalize_doi(str(raw))
            if doi:
                break

    # Authors — iterate key priority order and stop at the first non-empty hit.
    authors: list[str] = []
    for author_key in AUTHOR_META_KEYS:
        val = metadata.get(author_key)
        if val:
            authors = _parse_authors(val)
            if authors:
                break

    # Keywords — accumulate from all matching keys.
    keywords: set[str] = set()
    for kw_key in KEYWORDS_META_KEYS:
        val = metadata.get(kw_key)
        if val:
            keywords |= _parse_keywords(val)

    publication_date = _parse_date(_pick_metadata_value(metadata, DATE_META_KEYS))

    # Page range — combine first/last page into a single string when available.
    first_page = (str(metadata.get(_FIRSTPAGE_KEY) or "")).strip()
    last_page = (str(metadata.get(_LASTPAGE_KEY) or "")).strip()
    if first_page and last_page:
        pages: str | None = f"{first_page}\u2013{last_page}"  # en-dash
    elif first_page:
        pages = first_page
    else:
        pages = None

    # Number of pages — parse as int when the key is present.
    number_of_pages: int | None = None
    num_pages_raw = metadata.get(_NUM_PAGES_KEY)
    if num_pages_raw:
        try:
            number_of_pages = int(str(num_pages_raw).strip())
        except ValueError:
            pass

    source_title = _pick_metadata_value(metadata, PUBLICATION_TITLE_KEYS)
    source = None
    paper_type: PaperType | None = None
    if source_title and source_title.lower() not in _PREPRINT_SERVERS:
        if "citation_journal_title" in metadata:
            paper_type = PaperType.ARTICLE
        elif "citation_conference_title" in metadata:
            paper_type = PaperType.INPROCEEDINGS
        elif "citation_inbook_title" in metadata:
            paper_type = PaperType.INBOOK
        elif "citation_book_title" in metadata:
            paper_type = PaperType.INCOLLECTION
        source = Source(
            title=source_title,
            issn=_pick_metadata_value(metadata, PUBLICATION_ISSN_KEYS),
            isbn=_pick_metadata_value(metadata, PUBLICATION_ISBN_KEYS),
            publisher=_pick_metadata_value(metadata, PUBLICATION_PUBLISHER_KEYS),
        )

    pdf_url_val = _pick_metadata_value(metadata, PDF_URL_KEYS)

    return Paper(
        title=title,
        abstract=abstract or "",
        authors=authors,
        source=source,
        publication_date=publication_date,
        url=page_url,
        pdf_url=pdf_url_val,
        doi=doi,
        keywords=keywords or None,
        pages=pages,
        number_of_pages=number_of_pages,
        paper_type=paper_type,
    )


def enrich_from_sources(urls: Iterable[str], timeout: float | None) -> Paper | None:
    """Try each URL until metadata can be successfully fetched and parsed.

    PDF URLs are skipped because they rarely contain useful ``<meta>`` tags.

    Parameters
    ----------
    urls : Iterable[str]
        Candidate landing-page or PDF URLs.
    timeout : float | None
        HTTP request timeout in seconds.

    Returns
    -------
    Paper | None
        Enriched :class:`~findpapers.core.paper.Paper`, or ``None`` when all
        URLs fail or return no useful metadata.
    """
    for url in dict.fromkeys(urls):  # deduplicate while preserving insertion order
        if "pdf" in url.lower():
            continue
        try:
            metadata = fetch_metadata(url, timeout=timeout)
        except Exception:  # noqa: BLE001
            continue
        if not metadata:
            continue
        paper = build_paper_from_metadata(metadata, url)
        if paper is not None:
            return paper
    return None
