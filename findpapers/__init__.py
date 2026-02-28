"""Findpapers - Academic paper search and management tool."""

from findpapers.api import download, enrich, search
from findpapers.core.author import Author
from findpapers.core.paper import PaperType
from findpapers.core.query import ConnectorType, FilterCode
from findpapers.core.source import SourceType
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.download_runner import DownloadRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.search_runner import SearchRunner

__all__ = [
    "Author",
    "download",
    "DownloadRunner",
    "enrich",
    "EnrichmentRunner",
    "FilterCode",
    "ConnectorType",
    "PaperType",
    "search",
    "SearchRunner",
    "SearchRunnerNotExecutedError",
    "SourceType",
]
