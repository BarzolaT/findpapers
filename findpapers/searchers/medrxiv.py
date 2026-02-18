"""medRxiv searcher implementation."""

from __future__ import annotations

from typing import Optional

from findpapers.query.builders.medrxiv import MedrxivQueryBuilder
from findpapers.query.builders.rxiv import RxivQueryBuilder
from findpapers.searchers.rxiv import RxivSearcher


class MedrxivSearcher(RxivSearcher):
    """Searcher for the medRxiv preprint database.

    Inherits web-scraping and metadata-fetching logic from :class:`RxivSearcher`.

    API documentation:
    - https://api.biorxiv.org (used for metadata, server=medrxiv)
    - https://www.medrxiv.org/content/search-tips
    """

    def __init__(self, query_builder: Optional[MedrxivQueryBuilder] = None) -> None:
        """Create a medRxiv searcher.

        Parameters
        ----------
        query_builder : MedrxivQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`MedrxivQueryBuilder` is created automatically.
        """
        super().__init__(
            rxiv_server="medrxiv",
            jcode="medrxiv",
            query_builder=query_builder or MedrxivQueryBuilder(),
        )

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return "medRxiv"

    @property
    def query_builder(self) -> RxivQueryBuilder:
        """Return the medRxiv query builder.

        Returns
        -------
        QueryBuilder
            The underlying builder instance.
        """
        return self._query_builder
