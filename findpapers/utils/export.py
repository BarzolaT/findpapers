from __future__ import annotations

import contextlib
import datetime
import json
import re
from pathlib import Path
from typing import TypeAlias

from findpapers.core.author import Author
from findpapers.core.citation_graph import CitationGraph
from findpapers.core.paper import Paper, PaperType
from findpapers.core.search_result import SearchResult
from findpapers.core.source import Source
from findpapers.exceptions import ExportError
from findpapers.utils.version import package_version

#: Union of all exportable types.
Exportable: TypeAlias = "SearchResult | CitationGraph | list[Paper]"


def _extract_papers(data: Exportable) -> list[Paper]:
    """Extract a flat list of papers from any exportable input.

    Parameters
    ----------
    data : SearchResult | CitationGraph | list[Paper]
        Source of papers.

    Returns
    -------
    list[Paper]
        Papers extracted from *data*.

    Raises
    ------
    ExportError
        If *data* is not a supported type.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, SearchResult):
        return data.papers
    if isinstance(data, CitationGraph):
        return data.papers
    raise ExportError(
        f"Expected SearchResult, CitationGraph, or list[Paper], got {type(data).__name__}"
    )


def _serialize_to_dict(data: Exportable) -> dict:
    """Serialize any exportable input to a dictionary.

    The output always contains a top-level ``"type"`` key so that
    :func:`load_from_json` can reconstruct the original object.

    Parameters
    ----------
    data : SearchResult | CitationGraph | list[Paper]
        Data to serialize.

    Returns
    -------
    dict
        JSON-ready dictionary.

    Raises
    ------
    ExportError
        If *data* is not a supported type.
    """
    if isinstance(data, SearchResult):
        payload = data.to_dict()
        payload["type"] = "search_result"
        return payload
    if isinstance(data, CitationGraph):
        payload = data.to_dict()
        payload["type"] = "citation_graph"
        return payload
    if isinstance(data, list):
        return {
            "type": "paper_list",
            "metadata": {
                "version": package_version(),
                "total_papers": len(data),
            },
            "papers": [p.to_dict() for p in data],
        }
    raise ExportError(
        f"Expected SearchResult, CitationGraph, or list[Paper], got {type(data).__name__}"
    )


def export_to_json(data: Exportable, path: str) -> None:
    """Write data to a JSON file.

    Accepts a :class:`~findpapers.core.search_result.SearchResult`,
    a :class:`~findpapers.core.citation_graph.CitationGraph`, or a
    plain ``list[Paper]``.

    Parameters
    ----------
    data : SearchResult | CitationGraph | list[Paper]
        Data to export.
    path : str
        Output file path.

    Returns
    -------
    None
    """
    payload = _serialize_to_dict(data)
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def export_papers_to_bibtex(papers: list[Paper], path: str) -> None:
    """Write a list of papers to a BibTeX file.

    Parameters
    ----------
    papers : list[Paper]
        Papers to export.
    path : str
        Output file path.

    Returns
    -------
    None
    """
    bibtex_output = "".join(paper_to_bibtex(paper) for paper in papers)
    with Path(path).open("w", encoding="utf-8") as handle:
        handle.write(bibtex_output)


def load_from_json(
    path: str,
) -> SearchResult | CitationGraph | list[Paper]:
    """Load data previously exported with :func:`export_to_json`.

    The ``"type"`` key in the JSON payload is used to reconstruct the
    correct Python object:

    * ``"search_result"`` → :class:`~findpapers.core.search_result.SearchResult`
    * ``"citation_graph"`` → :class:`~findpapers.core.citation_graph.CitationGraph`
    * ``"paper_list"`` → ``list[Paper]``

    Files exported **before** the ``"type"`` key was introduced are
    auto-detected as either a ``SearchResult`` (when the payload
    contains a ``"papers"`` key) or a ``CitationGraph`` (when it
    contains ``"nodes"`` and ``"edges"`` keys).

    Parameters
    ----------
    path : str
        Path to a JSON file created by :func:`export_to_json`.

    Returns
    -------
    SearchResult | CitationGraph | list[Paper]
        The reconstructed object.

    Raises
    ------
    ExportError
        If the file format cannot be identified.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    kind = payload.get("type")

    # Explicit type discriminator.
    if kind == "search_result":
        return SearchResult.from_dict(payload)
    if kind == "citation_graph":
        return CitationGraph.from_dict(payload)
    if kind == "paper_list":
        return [Paper.from_dict(p) for p in payload.get("papers", [])]

    # Legacy auto-detection (files saved before "type" was added).
    if "nodes" in payload and "edges" in payload:
        return CitationGraph.from_dict(payload)
    if "papers" in payload:
        return SearchResult.from_dict(payload)

    raise ExportError(
        "Unrecognised JSON format: expected a 'type' key or a recognisable "
        "SearchResult / CitationGraph structure."
    )


# Characters that must be escaped inside BibTeX field values.
# Order matters: backslash must be escaped first to avoid double-escaping.
_BIBTEX_ESCAPE_MAP: list[tuple[str, str]] = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]


def _escape_bibtex(text: str) -> str:
    r"""Escape LaTeX special characters in a BibTeX field value.

    Replaces characters that would otherwise break BibTeX/LaTeX parsing
    with their LaTeX-safe equivalents.

    Parameters
    ----------
    text : str
        Raw text to escape.

    Returns
    -------
    str
        LaTeX-safe text suitable for inclusion in a BibTeX field.
    """
    for char, replacement in _BIBTEX_ESCAPE_MAP:
        text = text.replace(char, replacement)
    return text


def paper_to_bibtex(paper: Paper) -> str:
    """Convert a paper into a BibTeX entry.

    The BibTeX entry type is taken directly from ``paper.paper_type``
    (whose values are already BibTeX-aligned).  When ``paper_type`` is
    ``None``, the entry falls back to ``@misc``.

    Parameters
    ----------
    paper : Paper
        Paper instance.

    Returns
    -------
    str
        BibTeX entry.
    """
    default_tab = " " * 4
    source = paper.source
    # paper_type values are already BibTeX entry types; fall back to @misc.
    citation_type = f"@{paper.paper_type.value}" if paper.paper_type is not None else "@misc"
    citation_key = citation_key_for(paper)
    lines = [f"{citation_type}{{{citation_key},"]
    lines.append(f"{default_tab}title = {{{_escape_bibtex(paper.title)}}},")

    if paper.authors:
        authors = " and ".join(author.name for author in paper.authors)
        lines.append(f"{default_tab}author = {{{_escape_bibtex(authors)}}},")

    how_published = bibtex_how_published(paper)
    if how_published:
        lines.append(f"{default_tab}howpublished = {{{how_published}}},")

    # journal field for @article entries
    if paper.paper_type == PaperType.ARTICLE and source is not None:
        lines.append(f"{default_tab}journal = {{{_escape_bibtex(source.title)}}},")

    # booktitle field for @inproceedings / @incollection entries
    if paper.paper_type in {PaperType.INPROCEEDINGS, PaperType.INCOLLECTION} and source is not None:
        lines.append(f"{default_tab}booktitle = {{{_escape_bibtex(source.title)}}},")

    # institution field for @techreport / @phdthesis / @mastersthesis entries
    if (
        paper.paper_type in {PaperType.TECHREPORT, PaperType.PHDTHESIS, PaperType.MASTERSTHESIS}
        and source is not None
        and source.publisher is not None
    ):
        lines.append(f"{default_tab}institution = {{{_escape_bibtex(source.publisher)}}},")

    if paper.doi is not None:
        lines.append(f"{default_tab}doi = {{{paper.doi}}},")

    if source is not None and source.publisher is not None:
        lines.append(f"{default_tab}publisher = {{{_escape_bibtex(source.publisher)}}},")

    if paper.publication_date is not None:
        lines.append(f"{default_tab}year = {{{paper.publication_date.year}}},")

    if paper.page_range is not None:
        lines.append(f"{default_tab}pages = {{{paper.page_range}}},")

    if paper.abstract:
        lines.append(f"{default_tab}abstract = {{{_escape_bibtex(paper.abstract)}}},")

    if paper.keywords:
        kw_str = ", ".join(sorted(paper.keywords))
        lines.append(f"{default_tab}keywords = {{{_escape_bibtex(kw_str)}}},")

    if paper.url is not None:
        lines.append(f"{default_tab}url = {{{paper.url}}},")

    entry = "\n".join(lines)
    entry = entry.rstrip(",") + "\n" if entry.endswith(",") else entry
    return f"{entry}\n}}\n\n"


def citation_key_for(paper: Paper) -> str:
    """Generate a BibTeX citation key for a paper.

    Parameters
    ----------
    paper : Paper
        Paper instance.

    Returns
    -------
    str
        Citation key string.
    """
    author_key = "unknown"
    if paper.authors:
        author_key = paper.authors[0].name.lower().replace(" ", "").replace(",", "")
    year_key = "XXXX"
    if paper.publication_date is not None:
        year_key = str(paper.publication_date.year)
    title_key = paper.title.split(" ")[0].lower() if paper.title else "paper"
    return re.sub(r"[^\w\d]", "", f"{author_key}{year_key}{title_key}")


def bibtex_note(paper: Paper) -> str:
    """Build a BibTeX note field for unpublished entries.

    Parameters
    ----------
    paper : Paper
        Paper instance.

    Returns
    -------
    str
        Note field content.
    """
    parts: list[str] = []
    if paper.url:
        parts.append(f"Available at {paper.url}")
    if paper.publication_date is not None:
        parts.append(f"({paper.publication_date.strftime('%Y/%m/%d')})")
    if paper.comments:
        parts.append(paper.comments)
    return " ".join(parts).strip()


def bibtex_how_published(paper: Paper) -> str:
    """Build a BibTeX howpublished field for misc entries.

    Parameters
    ----------
    paper : Paper
        Paper instance.

    Returns
    -------
    str
        howpublished content.
    """
    if not paper.url or paper.publication_date is None:
        return ""
    date = paper.publication_date.strftime("%Y/%m/%d")
    return f"Available at {paper.url} ({date})"


# ---------------------------------------------------------------------------
# BibTeX import
# ---------------------------------------------------------------------------

# Reverse of _BIBTEX_ESCAPE_MAP for unescaping BibTeX field values.
# Order matters: LaTeX commands must be replaced before the backslash char
# so that intermediate results are not mangled.
_BIBTEX_UNESCAPE_MAP: list[tuple[str, str]] = [
    (r"\textasciicircum{}", "^"),
    (r"\textasciitilde{}", "~"),
    (r"\textbackslash{}", "\\"),
    (r"\&", "&"),
    (r"\%", "%"),
    (r"\$", "$"),
    (r"\#", "#"),
    (r"\_", "_"),
]


def _unescape_bibtex(text: str) -> str:
    r"""Reverse LaTeX escapes produced by :func:`_escape_bibtex`.

    Parameters
    ----------
    text : str
        Escaped BibTeX field value.

    Returns
    -------
    str
        Plain-text value.
    """
    for escaped, raw in _BIBTEX_UNESCAPE_MAP:
        text = text.replace(escaped, raw)
    return text


def _parse_bibtex_entries(raw: str) -> list[dict[str, str]]:
    """Parse raw BibTeX text into a list of field dictionaries.

    Each returned dictionary contains the lowercased field names as keys
    and the brace-delimited values (with outer braces stripped). A special
    ``"_entry_type"`` key holds the entry type (e.g. ``"article"``).

    Parameters
    ----------
    raw : str
        Full contents of a BibTeX file.

    Returns
    -------
    list[dict[str, str]]
        One dict per entry found.
    """
    entries: list[dict[str, str]] = []
    # Match entries like @article{key, ... }
    entry_pattern = re.compile(r"@(\w+)\s*\{([^,]*),", re.IGNORECASE)

    pos = 0
    while pos < len(raw):
        match = entry_pattern.search(raw, pos)
        if match is None:
            break

        entry_type = match.group(1).lower()
        # Find the balanced closing brace for this entry
        body_start = match.end()
        depth = 1
        i = body_start
        while i < len(raw) and depth > 0:
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
            i += 1
        body = raw[body_start : i - 1] if depth == 0 else raw[body_start:]

        fields: dict[str, str] = {"_entry_type": entry_type}
        # Parse individual fields: name = {value} or name = "value"
        field_pattern = re.compile(
            r"(\w+)\s*=\s*(?:\{([^}]*(?:\{[^}]*\}[^}]*)*)\}|\"([^\"]*)\")",
            re.DOTALL,
        )
        for field_match in field_pattern.finditer(body):
            name = field_match.group(1).lower()
            value = (
                field_match.group(2) if field_match.group(2) is not None else field_match.group(3)
            )
            fields[name] = value.strip()
        entries.append(fields)
        pos = i

    return entries


def load_papers_from_bibtex(path: str) -> list[Paper]:
    """Load papers from a BibTeX file.

    Parses the BibTeX entries and reconstructs
    :class:`~findpapers.core.paper.Paper` instances.  Fields that cannot
    be represented (e.g. custom BibTeX fields) are silently ignored.

    Parameters
    ----------
    path : str
        Path to a ``.bib`` file.

    Returns
    -------
    list[Paper]
        Papers reconstructed from BibTeX entries.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    content = Path(path).read_text(encoding="utf-8")
    entries = _parse_bibtex_entries(content)

    papers: list[Paper] = []
    for fields in entries:
        title = _unescape_bibtex(fields.get("title", "")).strip()
        if not title:
            continue

        # Authors: BibTeX uses " and " as separator
        raw_authors = fields.get("author", "")
        authors = [
            Author(name=_unescape_bibtex(a.strip()))
            for a in raw_authors.split(" and ")
            if a.strip()
        ]

        abstract = _unescape_bibtex(fields.get("abstract", ""))

        # Publication date from year field
        publication_date: datetime.date | None = None
        year_str = fields.get("year", "").strip()
        if year_str.isdigit():
            publication_date = datetime.date(int(year_str), 1, 1)

        doi = fields.get("doi")
        url = fields.get("url")
        page_range = fields.get("pages")
        keywords_raw = fields.get("keywords", "")
        keywords = {
            _unescape_bibtex(k.strip()) for k in keywords_raw.split(",") if k.strip()
        } or None

        # Source from journal, booktitle, or institution
        source_title = fields.get("journal") or fields.get("booktitle") or fields.get("institution")
        publisher = fields.get("publisher")
        source: Source | None = None
        if source_title:
            source = Source(
                title=_unescape_bibtex(source_title),
                publisher=_unescape_bibtex(publisher) if publisher else None,
            )

        # PaperType from entry type
        entry_type = fields.get("_entry_type", "misc")
        paper_type: PaperType | None = None
        with contextlib.suppress(ValueError):
            paper_type = PaperType(entry_type)

        papers.append(
            Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                source=source,
                publication_date=publication_date,
                url=url,
                doi=doi,
                page_range=page_range,
                keywords=keywords,
                paper_type=paper_type,
            )
        )

    return papers
