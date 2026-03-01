"""Findpapers - Academic paper search and management tool."""

from findpapers.api import download, enrich, fetch_paper_by_doi, search
from findpapers.core.author import Author
from findpapers.core.paper import PaperType
from findpapers.core.query import ConnectorType, FilterCode
from findpapers.core.source import SourceType
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.doi_lookup_runner import DOILookupRunner
from findpapers.runners.download_runner import DownloadRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.search_runner import SearchRunner

__all__ = [
    "Author",
    "DOILookupRunner",
    "download",
    "DownloadRunner",
    "enrich",
    "EnrichmentRunner",
    "fetch_paper_by_doi",
    "FilterCode",
    "ConnectorType",
    "PaperType",
    "search",
    "SearchRunner",
    "SearchRunnerNotExecutedError",
    "SourceType",
]
