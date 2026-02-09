from __future__ import annotations

import datetime
from typing import List, Optional, Set

from ..utils.merge import merge_value
from .publication import Publication


class Paper:
    """Represents a paper instance."""

    def __init__(
        self,
        title: str,
        abstract: str,
        authors: List[str],
        publication: Publication | None,
        publication_date: datetime.date | None,
        url: Optional[str] = None,
        pdf_url: Optional[str] = None,
        doi: Optional[str] = None,
        citations: Optional[int] = None,
        keywords: Optional[Set[str]] = None,
        comments: Optional[str] = None,
        number_of_pages: Optional[int] = None,
        pages: Optional[str] = None,
        databases: Optional[Set[str]] = None,
    ) -> None:
        """Create a Paper instance.

        Parameters
        ----------
        title : str
            Paper title.
        abstract : str
            Paper abstract.
        authors : list[str]
            List of authors.
        publication : Publication | None
            Publication where it was published.
        publication_date : datetime.date | None
            Publication date.
        url : str | None
            URL that references the paper.
        pdf_url : str | None
            Direct URL to PDF file.
        doi : str | None
            Paper DOI.
        citations : int | None
            Citations count.
        keywords : set[str] | None
            Keywords.
        comments : str | None
            Comments.
        number_of_pages : int | None
            Page count.
        pages : str | None
            Page range.
        databases : set[str] | None
            Databases where found.

        Raises
        ------
        ValueError
            If title is missing.
        """
        if title is None or len(title) == 0:
            raise ValueError("Paper's title cannot be null")

        self.title = title
        self.abstract = abstract
        self.authors = authors
        self.publication = publication
        self.publication_date = publication_date
        self.url = url
        self.pdf_url = pdf_url
        self.doi = doi
        self.citations = citations
        self.keywords = keywords if keywords is not None else set()
        self.comments = comments
        self.number_of_pages = number_of_pages
        self.pages = pages
        self.databases = databases if databases is not None else set()

    def add_database(self, database_name: str) -> None:
        """Add a database name where the paper was found.

        Parameters
        ----------
        database_name : str
            Database name.

        Returns
        -------
        None
        """
        if database_name:
            self.databases.add(database_name)

    def merge(self, paper: Paper) -> None:
        """Merge another paper into this one.

        Parameters
        ----------
        paper : Paper
            Another instance of the same paper.

        Returns
        -------
        None
        """
        # Prefer existing dates; if missing, use the incoming one.
        if self.publication_date is None:
            self.publication_date = paper.publication_date

        # Merge scalar fields using shared rules.
        self.title = merge_value(self.title, paper.title)
        self.doi = merge_value(self.doi, paper.doi)
        self.abstract = merge_value(self.abstract, paper.abstract)
        self.citations = merge_value(self.citations, paper.citations)
        self.comments = merge_value(self.comments, paper.comments)
        self.number_of_pages = merge_value(self.number_of_pages, paper.number_of_pages)
        self.pages = merge_value(self.pages, paper.pages)
        self.url = merge_value(self.url, paper.url)
        self.pdf_url = merge_value(self.pdf_url, paper.pdf_url)

        # Merge authors/keywords as collections while keeping uniqueness.
        self.authors = merge_value(self.authors, paper.authors)
        self.keywords = merge_value(self.keywords, paper.keywords)

        # Always accumulate databases for traceability.
        self.databases |= paper.databases
        if self.publication is None:
            self.publication = paper.publication
        elif paper.publication is not None:
            self.publication.merge(paper.publication)

    @classmethod
    def from_dict(cls, paper_dict: dict) -> "Paper":
        """Create a paper from a dict.

        Parameters
        ----------
        paper_dict : dict
            Paper dictionary.

        Returns
        -------
        Paper
            Paper instance.

        Raises
        ------
        ValueError
            If the title is missing.
        """
        title = paper_dict.get("title")
        if not isinstance(title, str) or not title:
            raise ValueError("Paper's title cannot be null")

        abstract = paper_dict.get("abstract") or ""
        if not isinstance(abstract, str):
            abstract = str(abstract)

        raw_authors = paper_dict.get("authors") or []
        if isinstance(raw_authors, (list, set, tuple)):
            authors = [str(author) for author in raw_authors]
        else:
            authors = [str(raw_authors)]

        publication_data = paper_dict.get("publication")
        publication = (
            Publication.from_dict(publication_data) if isinstance(publication_data, dict) else None
        )
        publication_date = paper_dict.get("publication_date")
        if isinstance(publication_date, str):
            try:
                publication_date = datetime.datetime.strptime(publication_date, "%Y-%m-%d").date()
            except ValueError:
                publication_date = None

        url = paper_dict.get("url")
        if url is not None and not isinstance(url, str):
            url = str(url)

        pdf_url = paper_dict.get("pdf_url")
        if pdf_url is not None and not isinstance(pdf_url, str):
            pdf_url = str(pdf_url)

        doi = paper_dict.get("doi")
        if doi is not None and not isinstance(doi, str):
            doi = str(doi)
        citations = paper_dict.get("citations")
        raw_keywords = paper_dict.get("keywords") or []
        if isinstance(raw_keywords, (list, set, tuple)):
            keywords = {str(keyword) for keyword in raw_keywords}
        else:
            keywords = {str(raw_keywords)} if raw_keywords else set()
        comments = paper_dict.get("comments")
        number_of_pages = paper_dict.get("number_of_pages")
        pages = paper_dict.get("pages")
        raw_databases = paper_dict.get("databases") or []
        if isinstance(raw_databases, (list, set, tuple)):
            databases = {str(database) for database in raw_databases}
        else:
            databases = {str(raw_databases)} if raw_databases else set()

        return cls(
            title=title,
            abstract=abstract,
            authors=authors,
            publication=publication,
            publication_date=publication_date,
            url=url,
            pdf_url=pdf_url,
            doi=doi,
            citations=citations,
            keywords=keywords,
            comments=comments,
            number_of_pages=number_of_pages,
            pages=pages,
            databases=databases,
        )

    @staticmethod
    def to_dict(paper: "Paper") -> dict:
        """Convert a Paper to dict.

        Parameters
        ----------
        paper : Paper
            Paper instance.

        Returns
        -------
        dict
            Paper dictionary.
        """
        return {
            "title": paper.title,
            "abstract": paper.abstract,
            "authors": list(paper.authors),
            "publication": (
                Publication.to_dict(paper.publication) if paper.publication is not None else None
            ),
            "publication_date": (
                paper.publication_date.isoformat() if paper.publication_date is not None else None
            ),
            "url": paper.url,
            "pdf_url": paper.pdf_url,
            "doi": paper.doi,
            "citations": paper.citations,
            "keywords": sorted(paper.keywords),
            "comments": paper.comments,
            "number_of_pages": paper.number_of_pages,
            "pages": paper.pages,
            "databases": sorted(paper.databases),
        }
