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
    FindpapersError,
    InvalidParameterError,
    ModelValidationError,
    PersistenceError,
    QueryValidationError,
    UnsupportedQueryError,
)
from findpapers.runners.doi_lookup_runner import DOILookupRunner
from findpapers.runners.download_runner import DownloadRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.search_runner import SearchRunner
from findpapers.runners.snowball_runner import SnowballRunner
from findpapers.utils.persistence import (
    load_from_bibtex,
    load_from_csv,
    load_from_json,
    save_to_bibtex,
    save_to_csv,
    save_to_json,
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
    "FilterCode",
    "FindpapersError",
    "InvalidParameterError",
    "ModelValidationError",
    "Paper",
    "PaperType",
    "PersistenceError",
    "QueryValidationError",
    "SearchResult",
    "SearchRunner",
    "SnowballRunner",
    "Source",
    "SourceType",
    "UnsupportedQueryError",
    "load_from_bibtex",
    "load_from_csv",
    "load_from_json",
    "save_to_bibtex",
    "save_to_csv",
    "save_to_json",
]
