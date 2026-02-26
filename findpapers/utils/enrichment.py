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

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.source import Source, SourceType
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
AUTHOR_AFFILIATION_META_KEYS = [
    "citation_author_institution",
    "citation_author_affiliation",
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
SOURCE_TITLE_KEYS = [
    "citation_journal_title",
    "citation_conference_title",
    "citation_book_title",
    "citation_inbook_title",  # Scopus book chapters
]
SOURCE_PUBLISHER_KEYS = [
    "citation_publisher",
    "dc.publisher",
]
SOURCE_ISSN_KEYS = [
    "citation_issn",
    "prism.issn",
]
SOURCE_ISBN_KEYS = [
    "citation_isbn",
    "prism.isbn",
]

# Mapping from meta key names to SourceType for source classification.
_SOURCE_KEY_TYPE_MAP: dict[str, SourceType] = {
    "citation_journal_title": SourceType.JOURNAL,
    "citation_conference_title": SourceType.CONFERENCE,
    "citation_book_title": SourceType.BOOK,
    "citation_inbook_title": SourceType.BOOK,
}
PDF_URL_KEYS = [
    "citation_pdf_url",
]

# Keys used to build the page-range and page-count fields on Paper.
_FIRSTPAGE_KEY = "citation_firstpage"
_LASTPAGE_KEY = "citation_lastpage"
_NUM_PAGES_KEY = "citation_num_pages"

# Preprint server names to avoid treating them as formal sources.
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

    # Affiliations — IEEE embeds per-author affiliation in the authors list.
    # The affiliation field may be a string or a list of strings.
    affiliations: list[str] = []
    for a in data.get("authors", []):
        if not a.get("name"):
            continue
        raw_aff = a.get("affiliation") or ""
        if isinstance(raw_aff, list):
            aff_str = "; ".join(s.strip() for s in raw_aff if isinstance(s, str) and s.strip())
        else:
            aff_str = str(raw_aff).strip()
        affiliations.append(aff_str)
    if affiliations and any(affiliations):
        _set_if_absent(
            "citation_author_institution",
            affiliations if len(affiliations) > 1 else affiliations[0],
        )

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


def _parse_affiliations(value: Any) -> list[str]:
    """Normalise affiliation metadata into a flat list of strings.

    Works similarly to :func:`_parse_authors`: handles ``list``, semicolon-
    separated ``str``, and single-string forms.

    Parameters
    ----------
    value : Any
        Raw affiliation data (str, list, or ``None``).

    Returns
    -------
    list[str]
        Stripped affiliation strings in original order.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _build_authors_from_metadata(metadata: dict[str, Any]) -> list[Author]:
    """Build :class:`Author` objects pairing names with affiliations.

    Author names are resolved from :data:`AUTHOR_META_KEYS`, and affiliations
    from :data:`AUTHOR_AFFILIATION_META_KEYS`.  When both lists are present
    they are paired positionally (one affiliation per author); surplus names
    receive no affiliation.

    Parameters
    ----------
    metadata : dict[str, Any]
        Extracted HTML metadata.

    Returns
    -------
    list[Author]
        Author objects with affiliations where available.
    """
    names: list[str] = []
    for key in AUTHOR_META_KEYS:
        raw = metadata.get(key)
        if raw:
            names = _parse_authors(raw)
            if names:
                break

    affiliations: list[str] = []
    for key in AUTHOR_AFFILIATION_META_KEYS:
        raw = metadata.get(key)
        if raw:
            affiliations = _parse_affiliations(raw)
            if affiliations:
                break

    authors: list[Author] = []
    for idx, name in enumerate(names):
        affiliation = affiliations[idx] if idx < len(affiliations) else None
        authors.append(Author(name=name, affiliation=affiliation))
    return authors


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

    # Authors — build Author objects with affiliations when available.
    authors: list[Author] = _build_authors_from_metadata(metadata)

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
    page_count: int | None = None
    num_pages_raw = metadata.get(_NUM_PAGES_KEY)
    if num_pages_raw:
        try:
            page_count = int(str(num_pages_raw).strip())
        except ValueError:
            pass

    source_title = _pick_metadata_value(metadata, SOURCE_TITLE_KEYS)
    source = None
    source_type: SourceType | None = None
    if source_title and source_title.lower() not in _PREPRINT_SERVERS:
        # Determine source_type based on which meta key matched.
        for key in SOURCE_TITLE_KEYS:
            raw = metadata.get(key)
            if raw:
                val = raw[0].strip() if isinstance(raw, list) else str(raw).strip()
                if val:
                    source_type = _SOURCE_KEY_TYPE_MAP.get(key)
                    break
        source = Source(
            title=source_title,
            issn=_pick_metadata_value(metadata, SOURCE_ISSN_KEYS),
            isbn=_pick_metadata_value(metadata, SOURCE_ISBN_KEYS),
            publisher=_pick_metadata_value(metadata, SOURCE_PUBLISHER_KEYS),
            source_type=source_type,
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
        page_range=pages,
        page_count=page_count,
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
