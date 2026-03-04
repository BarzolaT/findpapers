"""Connector registry for academic database integrations.

Provides two central registries that map database identifiers to their
connector classes, so that runners can discover connectors without importing
each one individually.

To register a **new search connector**:
    1. Create the connector class inheriting from
       :class:`~findpapers.connectors.search_base.SearchConnectorBase`.
    2. Add a corresponding member to
       :class:`~findpapers.core.search_result.Database`.
    3. Add an entry to :data:`SEARCH_REGISTRY` below.

To register a **new citation connector**:
    1. Create the connector class inheriting from
       :class:`~findpapers.connectors.citation_base.CitationConnectorBase`.
    2. Add an entry to :data:`CITATION_REGISTRY` below.
"""

from __future__ import annotations

from findpapers.connectors.arxiv import ArxivConnector
from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.connectors.crossref import CrossRefConnector
from findpapers.connectors.ieee import IEEEConnector
from findpapers.connectors.openalex import OpenAlexConnector
from findpapers.connectors.pubmed import PubmedConnector
from findpapers.connectors.scopus import ScopusConnector
from findpapers.connectors.search_base import SearchConnectorBase
from findpapers.connectors.semantic_scholar import SemanticScholarConnector
from findpapers.core.search_result import Database

# Central mapping of Database identifiers to their search connector classes.
SEARCH_REGISTRY: dict[Database, type[SearchConnectorBase]] = {
    Database.ARXIV: ArxivConnector,
    Database.IEEE: IEEEConnector,
    Database.OPENALEX: OpenAlexConnector,
    Database.PUBMED: PubmedConnector,
    Database.SCOPUS: ScopusConnector,
    Database.SEMANTIC_SCHOLAR: SemanticScholarConnector,
}

# Central mapping of connector names to their citation connector classes.
CITATION_REGISTRY: dict[str, type[CitationConnectorBase]] = {
    "openalex": OpenAlexConnector,
    "semantic_scholar": SemanticScholarConnector,
    "crossref": CrossRefConnector,
}
