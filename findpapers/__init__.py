"""Findpapers - Academic paper search and management tool."""

from findpapers.core.author import Author
from findpapers.core.citation_graph import CitationGraph
from findpapers.core.paper import Paper, PaperType
from findpapers.core.query import ConnectorType, FilterCode
from findpapers.core.search_result import SearchResult
from findpapers.core.source import Source, SourceType
from findpapers.engine import Engine
from findpapers.exceptions import (
    ConnectorError,
    ExportError,
    FindpapersError,
    QueryValidationError,
    UnsupportedQueryError,
)
from findpapers.runners.doi_lookup_runner import DOILookupRunner
from findpapers.runners.download_runner import DownloadRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.search_runner import SearchRunner
from findpapers.runners.snowball_runner import SnowballRunner
from findpapers.utils.export import (
    export_papers_to_bibtex,
    export_papers_to_csv,
    export_to_json,
    load_from_json,
    load_papers_from_bibtex,
    load_papers_from_csv,
)

__all__ = [
    "Author",
    "CitationGraph",
    "ConnectorError",
    "ConnectorType",
    "DOILookupRunner",
    "DownloadRunner",
    "Engine",
    "EnrichmentRunner",
    "ExportError",
    "FilterCode",
    "FindpapersError",
    "Paper",
    "PaperType",
    "QueryValidationError",
    "SearchResult",
    "SearchRunner",
    "SnowballRunner",
    "Source",
    "SourceType",
    "UnsupportedQueryError",
    "export_papers_to_bibtex",
    "export_papers_to_csv",
    "export_to_json",
    "load_from_json",
    "load_papers_from_bibtex",
    "load_papers_from_csv",
]
