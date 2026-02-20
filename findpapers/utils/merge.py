"""Shared merge helpers for model enrichment."""

from __future__ import annotations

from typing import Any


def merge_authors(base: list[str], incoming: list[str]) -> list[str]:
    """Merge two author lists by keeping whichever list is larger.

    This conservative strategy avoids the risk of combining lists that
    represent the same authors in different string formats (e.g.
    ``"First Last"`` vs ``"Last, First"``).  The list with more entries is
    returned as-is; when both have the same length the *base* list is kept.

    Parameters
    ----------
    base : list[str]
        Existing author list.
    incoming : list[str]
        New authors to merge in.

    Returns
    -------
    list[str]
        The larger of the two lists (base wins on a tie).
    """
    return list(incoming) if len(incoming) > len(base) else list(base)


def merge_value(base: Any, incoming: Any) -> Any:
    """Merge two values, keeping the most complete result.

    Parameters
    ----------
    base : Any
        Base value.
    incoming : Any
        Incoming value.

    Returns
    -------
    Any
        Selected merged value.
    """
    # Prefer non-null values.
    if base is None:
        return incoming
    if incoming is None:
        return base

    # Prefer longer text and larger numeric values.
    if isinstance(base, str) and isinstance(incoming, str):
        return base if len(base) >= len(incoming) else incoming
    if isinstance(base, (int, float)) and isinstance(incoming, (int, float)):
        return base if base >= incoming else incoming

    # Prefer merged collections when possible.
    if isinstance(base, set) and isinstance(incoming, set):
        return base | incoming
    if isinstance(base, list) and isinstance(incoming, list):
        return list({*base, *incoming})
    if isinstance(base, tuple) and isinstance(incoming, tuple):
        return tuple({*base, *incoming})
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = dict(base)
        for key in set(base.keys()) | set(incoming.keys()):
            merged[key] = merge_value(base.get(key), incoming.get(key))
        return merged

    # Fall back to the base value for unsupported types.
    return base
