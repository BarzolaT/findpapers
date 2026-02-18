from __future__ import annotations

from enum import Enum
from typing import Optional, Union

from ..utils.merge import merge_value


class PublicationCategory(str, Enum):
    """Recognized publication categories.

    Inheriting from :class:`str` makes each member compare equal to its string
    value, so existing code such as ``category == "Journal"`` or
    ``str(category)`` continues to work without modification.
    """

    JOURNAL = "Journal"
    CONFERENCE_PROCEEDINGS = "Conference Proceedings"
    BOOK = "Book"


class Publication:
    """Represents a publication (journal, conference proceedings, or book)."""

    def __init__(
        self,
        title: str,
        isbn: Optional[str] = None,
        issn: Optional[str] = None,
        publisher: Optional[str] = None,
        category: Optional[Union[str, PublicationCategory]] = None,
        is_potentially_predatory: Optional[bool] = False,
    ) -> None:
        """Create a Publication instance.

        Parameters
        ----------
        title : str
            Publication title.
        isbn : str | None
            Publication ISBN.
        issn : str | None
            Publication ISSN.
        publisher : str | None
            Publication publisher name.
        category : str | PublicationCategory | None
            Publication category (Journal, Conference Proceedings, Book).
        is_potentially_predatory : bool | None
            Predatory flag.

        Raises
        ------
        ValueError
            If title is empty.
        """
        if title is None or len(title) == 0:
            raise ValueError("Publication's title cannot be null")

        self.title = title
        self.isbn = isbn
        self.issn = issn
        self.publisher = publisher
        self.category = category if category is not None else title
        self.is_potentially_predatory = is_potentially_predatory

    @property
    def category(self) -> Optional[PublicationCategory]:
        """Return the publication category.

        Returns
        -------
        PublicationCategory | None
            Normalized category enum member or None.
        """
        return self._category

    @category.setter
    def category(self, value: Optional[Union[str, PublicationCategory]]) -> None:
        """Normalize and set the publication category.

        Parameters
        ----------
        value : str | PublicationCategory | None
            Raw category string or enum member to normalize.
        """
        normalized: Optional[PublicationCategory] = None
        if isinstance(value, PublicationCategory):
            normalized = value
        elif isinstance(value, str):
            lowered = value.lower()
            if "journal" in lowered:
                normalized = PublicationCategory.JOURNAL
            elif "conference" in lowered or "proceeding" in lowered:
                normalized = PublicationCategory.CONFERENCE_PROCEEDINGS
            elif "book" in lowered:
                normalized = PublicationCategory.BOOK

        self._category = normalized

    def merge(self, publication: Publication) -> None:
        """Merge another publication into this one.

        Parameters
        ----------
        publication : Publication
            Publication to merge into this one.

        Returns
        -------
        None
        """
        # Merge scalar and collection fields using shared rules.
        self.title = merge_value(self.title, publication.title)
        self.isbn = merge_value(self.isbn, publication.isbn)
        self.issn = merge_value(self.issn, publication.issn)
        self.publisher = merge_value(self.publisher, publication.publisher)
        self.category = merge_value(self.category, publication.category)
        self.is_potentially_predatory = bool(
            self.is_potentially_predatory or publication.is_potentially_predatory
        )

    @classmethod
    def from_dict(cls, publication_dict: dict) -> Publication:
        """Create a Publication from a dict.

        Parameters
        ----------
        publication_dict : dict
            Publication dictionary.

        Returns
        -------
        Publication
            Publication instance.

        Raises
        ------
        ValueError
            If the title is missing.
        """
        title = publication_dict.get("title")
        if not isinstance(title, str) or not title:
            raise ValueError("Publication's title cannot be null")
        return cls(
            title=title,
            isbn=publication_dict.get("isbn"),
            issn=publication_dict.get("issn"),
            publisher=publication_dict.get("publisher"),
            category=publication_dict.get("category"),
            is_potentially_predatory=publication_dict.get("is_potentially_predatory"),
        )

    @staticmethod
    def to_dict(publication: Publication) -> dict:
        """Convert a Publication to dict.

        Parameters
        ----------
        publication : Publication
            Publication instance.

        Returns
        -------
        dict
            Publication dictionary.
        """
        return {
            "title": publication.title,
            "isbn": publication.isbn,
            "issn": publication.issn,
            "publisher": publication.publisher,
            # Serialise enum as its plain string value so JSON round-trips cleanly.
            "category": publication.category.value if publication.category is not None else None,
            "is_potentially_predatory": publication.is_potentially_predatory,
        }
