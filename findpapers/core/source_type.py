"""Enum for academic source types."""

from __future__ import annotations

from enum import Enum


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
