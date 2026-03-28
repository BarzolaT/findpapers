"""BaseRunner: shared filter state and helpers for all runner classes."""

from __future__ import annotations

import datetime as dt

from findpapers.core.paper import Paper


class BaseRunner:
    """Shared filter state and helpers for :class:`SearchRunner` and :class:`SnowballRunner`.

    Subclasses that accept ``since`` and ``until`` parameters should call
    ``super().__init__`` with those values to populate the shared filter
    attributes and gain access to :meth:`_matches_filters`.

    Parameters
    ----------
    since : dt.date | None
        Lower-bound publication date filter (inclusive).  ``None`` disables it.
    until : dt.date | None
        Upper-bound publication date filter (inclusive).  ``None`` disables it.
    """

    def __init__(
        self,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
    ) -> None:
        """Initialise shared filter state."""
        self._since = since
        self._until = until

    def _matches_filters(self, paper: Paper) -> bool:
        """Return ``True`` when *paper* passes all configured date filters.

        Checks the ``since``/``until`` date range.  Any filter that is
        ``None`` (not configured) is treated as a pass-through.  Papers with
        no ``publication_date`` are excluded when any date filter is active.

        Parameters
        ----------
        paper : Paper
            Candidate paper to evaluate.

        Returns
        -------
        bool
            ``True`` if the paper satisfies all active filters.
        """
        if self._since is not None and (
            paper.publication_date is None or paper.publication_date < self._since
        ):
            return False
        return not (
            self._until is not None
            and (paper.publication_date is None or paper.publication_date > self._until)
        )
