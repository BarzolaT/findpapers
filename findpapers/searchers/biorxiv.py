"""bioRxiv searcher implementation."""

from __future__ import annotations

from typing import Optional

from findpapers.query.builders.biorxiv import BiorxivQueryBuilder
from findpapers.query.builders.rxiv import RxivQueryBuilder
from findpapers.searchers.rxiv import RxivSearcher


class BiorxivSearcher(RxivSearcher):
    """Searcher for the bioRxiv preprint database.

    Inherits web-scraping and metadata-fetching logic from :class:`RxivSearcher`.

    API documentation:
    - https://api.biorxiv.org
    - https://www.biorxiv.org/content/search-tips
    """

    def __init__(self, query_builder: Optional[BiorxivQueryBuilder] = None) -> None:
        """Create a bioRxiv searcher.

        Parameters
        ----------
        query_builder : BiorxivQueryBuilder | None
            Builder used to validate and convert queries.  When ``None`` a
            default :class:`BiorxivQueryBuilder` is created automatically.
        """
        super().__init__(
            rxiv_server="biorxiv",
            jcode="biorxiv",
            query_builder=query_builder or BiorxivQueryBuilder(),
        )

    @property
    def name(self) -> str:
        """Return the database identifier.

        Returns
        -------
        str
            Database name.
        """
        return "bioRxiv"

    @property
    def query_builder(self) -> RxivQueryBuilder:
        """Return the bioRxiv query builder.

        Returns
        -------
        QueryBuilder
            The underlying builder instance.
        """
        return self._query_builder
