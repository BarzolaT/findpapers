"""BaseRunner: shared filter state and helpers for all runner classes."""

from __future__ import annotations

import datetime as dt

from findpapers.core.paper import Paper, PaperType
from findpapers.exceptions import InvalidParameterError


class BaseRunner:
    """Shared filter state and helpers for :class:`SearchRunner` and :class:`SnowballRunner`.

    Subclasses that accept ``since``, ``until``, and ``paper_types``
    parameters should call ``super().__init__`` with those values to
    populate the shared filter attributes and gain access to
    :meth:`_matches_filters` and :meth:`_parse_paper_types`.

    Parameters
    ----------
    since : dt.date | None
        Lower-bound publication date filter (inclusive).  ``None`` disables it.
    until : dt.date | None
        Upper-bound publication date filter (inclusive).  ``None`` disables it.
    paper_types : list[str] | None
        Allowed paper type strings.  ``None`` disables the filter.

    Raises
    ------
    InvalidParameterError
        If any value in *paper_types* is not a recognised :class:`PaperType`.
    """

    def __init__(
        self,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
        paper_types: list[str] | None = None,
    ) -> None:
        """Initialise shared filter state."""
        self._since = since
        self._until = until
        self._paper_types = self._parse_paper_types(paper_types)

    @staticmethod
    def _parse_paper_types(paper_types: list[str] | None) -> list[PaperType] | None:
        """Convert a list of paper-type strings to :class:`PaperType` values.

        Parameters
        ----------
        paper_types : list[str] | None
            Raw string values supplied by the caller.

        Returns
        -------
        list[PaperType] | None
            Converted list, or ``None`` when the input is ``None``.

        Raises
        ------
        InvalidParameterError
            If any value is not a recognised :class:`PaperType`.
        """
        if paper_types is None:
            return None
        result: list[PaperType] = []
        for raw in paper_types:
            try:
                result.append(PaperType(raw))
            except ValueError:
                valid = ", ".join(f'"{pt.value}"' for pt in PaperType)
                raise InvalidParameterError(
                    f"Unknown paper_type '{raw}'. Accepted values: {valid}"
                ) from None
        return result

    def _matches_filters(self, paper: Paper) -> bool:
        """Return ``True`` when *paper* passes all configured filters.

        Checks the ``since``/``until`` date range and the ``paper_types``
        allow-list.  Any filter that is ``None`` (not configured) is treated
        as a pass-through.  Papers with no ``publication_date`` are excluded
        when any date filter is active.

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
        if self._until is not None and (
            paper.publication_date is None or paper.publication_date > self._until
        ):
            return False
        return self._paper_types is None or paper.paper_type in self._paper_types
