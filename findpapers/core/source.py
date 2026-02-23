from __future__ import annotations

from enum import Enum
from typing import Optional

from ..utils.merge import merge_value


class SourceType(str, Enum):
    """Classification of academic publication sources.

    Each value represents a broad category of venue or platform
    where scholarly work is published or deposited.

    Attributes
    ----------
    JOURNAL : str
        Peer-reviewed periodicals with regular publication schedules
        (e.g. Nature, IEEE Transactions, PLOS ONE).
    CONFERENCE : str
        Conferences, symposia, and workshops that publish proceedings
        (e.g. NeurIPS, ACL, ICML, CVPR).
    BOOK : str
        Books, book series, edited volumes, and monographs
        (e.g. Lecture Notes in Computer Science, Springer Tracts).
    REPOSITORY : str
        Preprint servers and deposit platforms
        (e.g. arXiv, bioRxiv, SSRN, Zenodo).
    OTHER : str
        Sources that do not fit any of the above categories
        (e.g. technical reports, newsletters, institutional publications).
    """

    JOURNAL = "journal"
    CONFERENCE = "conference"
    BOOK = "book"
    REPOSITORY = "repository"
    OTHER = "other"


class Source:
    """Represents a source (journal, conference proceedings, or book)."""

    def __init__(
        self,
        title: str,
        isbn: Optional[str] = None,
        issn: Optional[str] = None,
        publisher: Optional[str] = None,
        source_type: Optional[SourceType] = None,
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
            Source publisher name.
        source_type : SourceType | None
            Type of the source (journal, conference, book, repository, other).

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
        self.source_type = source_type

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
        if self.source_type is None:
            self.source_type = source.source_type

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
        raw_source_type = source_dict.get("source_type")
        source_type: SourceType | None = None
        if raw_source_type is not None:
            try:
                source_type = SourceType(raw_source_type)
            except ValueError:
                pass

        return cls(
            title=title,
            isbn=source_dict.get("isbn"),
            issn=source_dict.get("issn"),
            publisher=source_dict.get("publisher"),
            source_type=source_type,
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
            "source_type": source.source_type.value if source.source_type else None,
        }
