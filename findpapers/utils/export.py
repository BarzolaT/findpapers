from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from findpapers.core.paper import Paper
from findpapers.core.source_type import SourceType

if TYPE_CHECKING:
    from findpapers.core.search import Search


def export_to_json(search: Search, path: str) -> None:
    """Write search results to a JSON file.

    Parameters
    ----------
    search : Search
        Search instance with results and metadata.
    path : str
        Output file path.

    Returns
    -------
    None
    """
    payload = search.to_dict()
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def export_to_csv(search: Search, path: str) -> None:
    """Write search results to a CSV file using the standard column order.

    Parameters
    ----------
    search : Search
        Search instance with papers to export.
    path : str
        Output file path.

    Returns
    -------
    None
    """
    columns = csv_columns()
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for paper in search.papers:
            writer.writerow(paper_to_csv_row(paper))


def export_to_bibtex(search: Search, path: str) -> None:
    """Write search results to a BibTeX file.

    Parameters
    ----------
    search : Search
        Search instance with papers to export.
    path : str
        Output file path.

    Returns
    -------
    None
    """
    bibtex_output = "".join(paper_to_bibtex(paper) for paper in search.papers)
    with Path(path).open("w", encoding="utf-8") as handle:
        handle.write(bibtex_output)


def csv_columns() -> list[str]:
    """Return the CSV column order.

    Returns
    -------
    list[str]
        Column names ordered by priority.
    """
    paper_fields = [
        "title",
        "abstract",
        "authors",
        "author_affiliations",
        "publication_date",
        "url",
        "pdf_url",
        "doi",
        "citations",
        "keywords",
        "comments",
        "number_of_pages",
        "pages",
        "databases",
    ]
    source_fields = [
        "source_title",
        "source_type",
        "source_isbn",
        "source_issn",
        "source_publisher",
        "source_is_potentially_predatory",
    ]
    return paper_fields + source_fields


def paper_to_csv_row(paper: Paper) -> dict[str, object]:
    """Convert a paper into a CSV row mapping.

    Parameters
    ----------
    paper : Paper
        Paper instance.

    Returns
    -------
    dict[str, object]
        CSV row mapping.
    """
    source = paper.source
    row: dict[str, object] = {
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": "; ".join(author.name for author in paper.authors),
        "author_affiliations": "; ".join(
            author.affiliation for author in paper.authors if author.affiliation
        ),
        "publication_date": paper.publication_date.isoformat() if paper.publication_date else None,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "doi": paper.doi,
        "citations": paper.citations,
        "keywords": "; ".join(sorted(paper.keywords)),
        "comments": paper.comments,
        "number_of_pages": paper.number_of_pages,
        "pages": paper.pages,
        "databases": "; ".join(sorted(paper.databases)),
        "source_title": source.title if source else None,
        "source_type": source.source_type.value if source and source.source_type else None,
        "source_isbn": source.isbn if source else None,
        "source_issn": source.issn if source else None,
        "source_publisher": source.publisher if source else None,
        "source_is_potentially_predatory": (source.is_potentially_predatory if source else None),
    }
    return row


def paper_to_bibtex(paper: Paper) -> str:
    """Convert a paper into a BibTeX entry.

    The BibTeX entry type is determined from the source type when available:
    ``@article`` for journals, ``@inproceedings`` for conferences,
    ``@inbook`` for books, and ``@misc`` as the fallback.

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
    # Map source_type to BibTeX entry type.
    _BIBTEX_TYPE_MAP: dict[SourceType, str] = {
        SourceType.JOURNAL: "@article",
        SourceType.CONFERENCE: "@inproceedings",
        SourceType.BOOK: "@inbook",
    }
    source = paper.source
    citation_type = "@misc"
    if source and source.source_type:
        citation_type = _BIBTEX_TYPE_MAP.get(source.source_type, "@misc")
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

    if paper.pages is not None:
        lines.append(f"{default_tab}pages = {{{paper.pages}}},")

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
