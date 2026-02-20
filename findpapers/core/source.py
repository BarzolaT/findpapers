from __future__ import annotations

from typing import Optional

from ..utils.merge import merge_value


class Source:
    """Represents a source (journal, conference proceedings, or book)."""

    def __init__(
        self,
        title: str,
        isbn: Optional[str] = None,
        issn: Optional[str] = None,
        publisher: Optional[str] = None,
        is_potentially_predatory: Optional[bool] = False,
    ) -> None:
        """Create a Source instance.

        Parameters
        ----------
        title : str
            Source title.
        isbn : str | None
            Source ISBN.
        issn : str | None
            Source ISSN.
        publisher : str | None
            Publication publisher name.
        is_potentially_predatory : bool | None
            Predatory flag.

        Raises
        ------
        ValueError
            If title is empty.
        """
        if title is None or len(title) == 0:
            raise ValueError("Source's title cannot be null")

        self.title = title
        self.isbn = isbn
        self.issn = issn
        self.publisher = publisher
        self.is_potentially_predatory = is_potentially_predatory

    def merge(self, source: Source) -> None:
        """Merge another source into this one.

        Parameters
        ----------
        source : Source
            Source to merge into this one.

        Returns
        -------
        None
        """
        # Merge scalar and collection fields using shared rules.
        self.title = merge_value(self.title, source.title)
        self.isbn = merge_value(self.isbn, source.isbn)
        self.issn = merge_value(self.issn, source.issn)
        self.publisher = merge_value(self.publisher, source.publisher)
        self.is_potentially_predatory = bool(
            self.is_potentially_predatory or source.is_potentially_predatory
        )

    @classmethod
    def from_dict(cls, source_dict: dict) -> Source:
        """Create a Source from a dict.

        Parameters
        ----------
        source_dict : dict
            Source dictionary.

        Returns
        -------
        Source
            Source instance.

        Raises
        ------
        ValueError
            If the title is missing.
        """
        title = source_dict.get("title")
        if not isinstance(title, str) or not title:
            raise ValueError("Source's title cannot be null")
        return cls(
            title=title,
            isbn=source_dict.get("isbn"),
            issn=source_dict.get("issn"),
            publisher=source_dict.get("publisher"),
            is_potentially_predatory=source_dict.get("is_potentially_predatory"),
        )

    @staticmethod
    def to_dict(source: Source) -> dict:
        """Convert a Source to dict.

        Parameters
        ----------
        source : Source
            Source instance.

        Returns
        -------
        dict
            Source dictionary.
        """
        return {
            "title": source.title,
            "isbn": source.isbn,
            "issn": source.issn,
            "publisher": source.publisher,
            "is_potentially_predatory": source.is_potentially_predatory,
        }
