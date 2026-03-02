from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Union

from findpapers.core.paper import Paper
from findpapers.utils.version import package_version

if TYPE_CHECKING:
    from findpapers.core.citation_graph import CitationGraph
    from findpapers.core.search_result import SearchResult

#: Union of all exportable types.
Exportable = Union["SearchResult", "CitationGraph", list[Paper]]


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
    TypeError
        If *data* is not a supported type.
    """
    from findpapers.core.citation_graph import CitationGraph
    from findpapers.core.search_result import SearchResult

    if isinstance(data, list):
        return data
    if isinstance(data, SearchResult):
        return data.papers
    if isinstance(data, CitationGraph):
        return data.papers
    raise TypeError(
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
    TypeError
        If *data* is not a supported type.
    """
    from findpapers.core.citation_graph import CitationGraph
    from findpapers.core.search_result import SearchResult

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
            "papers": [Paper.to_dict(p) for p in data],
        }
    raise TypeError(
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


def export_to_bibtex(data: Exportable, path: str) -> None:
    """Write data to a BibTeX file.

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
    papers = _extract_papers(data)
    bibtex_output = "".join(paper_to_bibtex(paper) for paper in papers)
    with Path(path).open("w", encoding="utf-8") as handle:
        handle.write(bibtex_output)


def load_from_json(
    path: str,
) -> "SearchResult | CitationGraph | list[Paper]":
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
    ValueError
        If the file format cannot be identified.
    """
    from findpapers.core.citation_graph import CitationGraph
    from findpapers.core.search_result import SearchResult

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

    raise ValueError(
        "Unrecognised JSON format: expected a 'type' key or a recognisable "
        "SearchResult / CitationGraph structure."
    )


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
    lines.append(f"{default_tab}title = {{{paper.title}}},")

    if paper.authors:
        authors = " and ".join(author.name for author in paper.authors)
        lines.append(f"{default_tab}author = {{{authors}}},")

    how_published = bibtex_how_published(paper)
    if how_published:
        lines.append(f"{default_tab}howpublished = {{{how_published}}},")

    if source is not None and source.publisher is not None:
        lines.append(f"{default_tab}publisher = {{{source.publisher}}},")

    if paper.publication_date is not None:
        lines.append(f"{default_tab}year = {{{paper.publication_date.year}}},")

    if paper.page_range is not None:
        lines.append(f"{default_tab}pages = {{{paper.page_range}}},")

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
