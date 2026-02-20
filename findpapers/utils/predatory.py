"""Utilities for detecting potentially predatory publications."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse

from .predatory_data import POTENTIAL_PREDATORY_JOURNALS, POTENTIAL_PREDATORY_PUBLISHERS


def _normalize(value: str | None) -> str | None:
    """Normalize a string for matching.

    Parameters
    ----------
    value : str | None
        Raw string value.

    Returns
    -------
    str | None
        Lowercase-stripped string, or ``None`` when empty.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalized_names(entries: Iterable[dict]) -> set[str]:
    """Return a set of normalized names extracted from a list of entry dicts.

    Parameters
    ----------
    entries : Iterable[dict]
        Iterable of dicts, each expected to contain a ``"name"`` key.

    Returns
    -------
    set[str]
        Normalized name strings.
    """
    names: set[str] = set()
    for entry in entries:
        normalized = _normalize(entry.get("name"))
        if normalized:
            names.add(normalized)
    return names


# Pre-computed sets for O(1) look-ups at runtime.
PREDATORY_PUBLISHER_HOSTS: set[str] = {
    urlparse(entry.get("url", "")).netloc.replace("www.", "")
    for entry in POTENTIAL_PREDATORY_PUBLISHERS
    if entry.get("url")
}
PREDATORY_PUBLISHER_NAMES: set[str] = _normalized_names(POTENTIAL_PREDATORY_PUBLISHERS)
PREDATORY_JOURNAL_NAMES: set[str] = _normalized_names(POTENTIAL_PREDATORY_JOURNALS)


def _get_source_fields(source: object) -> tuple[str | None, str | None, str | None]:
    """Extract source name, publisher name and publisher host.

    Supports both dict-like and attribute-based source objects.

    Parameters
    ----------
    source : object
        Source object or dict.

    Returns
    -------
    tuple[str | None, str | None, str | None]
        ``(source_name, publisher_name, publisher_host)`` normalized.
    """
    if isinstance(source, dict):
        source_name = _normalize(source.get("title"))
        publisher_name = _normalize(source.get("publisher"))
        publisher_host = _normalize(source.get("publisher_host"))
    else:
        source_name = _normalize(getattr(source, "title", None))
        publisher_name = _normalize(getattr(source, "publisher", None))
        publisher_host = _normalize(getattr(source, "publisher_host", None))

    return source_name, publisher_name, publisher_host


def is_predatory_source(source: object | None) -> bool:
    """Determine whether a source is potentially predatory.

    Checks the source name against the predatory journals list and the
    publisher name / host against the predatory publishers list.

    Parameters
    ----------
    source : object | None
        Source object (with ``.title``, ``.publisher``, ``.publisher_host``
        attributes) or dict, or ``None``.

    Returns
    -------
    bool
        ``True`` if the source matches any predatory list entry.

    Examples
    --------
    >>> is_predatory_source(None)
    False
    """
    if source is None:
        return False

    source_name, publisher_name, publisher_host = _get_source_fields(source)

    if source_name and source_name in PREDATORY_JOURNAL_NAMES:
        return True
    if publisher_name and publisher_name in PREDATORY_PUBLISHER_NAMES:
        return True
    if publisher_host and publisher_host in PREDATORY_PUBLISHER_HOSTS:
        return True

    return False
