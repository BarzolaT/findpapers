from __future__ import annotations

from typing import Optional

from ..utils.merge import merge_value


class Publication:
    """Represents a publication (journal, conference proceedings, or book)."""

    def __init__(
        self,
        title: str,
        isbn: Optional[str] = None,
        issn: Optional[str] = None,
        publisher: Optional[str] = None,
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
        self.is_potentially_predatory = is_potentially_predatory

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
            "is_potentially_predatory": publication.is_potentially_predatory,
        }
