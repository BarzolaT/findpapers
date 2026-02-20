"""Shared merge helpers for model enrichment."""

from __future__ import annotations

import re
from typing import Any


def _author_tokens(name: str) -> frozenset[str]:
    """Return the normalised word-token set of an author name.

    Splits on whitespace, commas, and trailing dots so that
    ``"Chowdhury, Asif Hasan"`` and ``"Asif Hasan Chowdhury"`` produce the
    same token set and are recognised as the same person.

    Parameters
    ----------
    name : str
        Raw author name string.

    Returns
    -------
    frozenset[str]
        Lower-cased tokens with trailing periods stripped.
    """
    return frozenset(
        token.rstrip(".").lower() for token in re.split(r"[\s,]+", name) if token.rstrip(".")
    )


def merge_authors(base: list[str], incoming: list[str]) -> list[str]:
    """Merge two author lists, deduplicating by name-token set equality.

    Names formatted as ``"First Last"`` and ``"Last, First"`` are treated as
    the same author.  When a duplicate is detected the existing (base) form
    is kept, so the canonical representation is determined by whichever
    source was encountered first.

    Parameters
    ----------
    base : list[str]
        Existing author list.
    incoming : list[str]
        New authors to merge in.

    Returns
    -------
    list[str]
        Deduplicated list preserving the original order of *base* and
        appending only genuinely new authors from *incoming*.
    """
    if not base:
        return list(incoming)
    if not incoming:
        return list(base)

    existing_tokens: list[frozenset[str]] = [_author_tokens(a) for a in base]
    result: list[str] = list(base)
    for author in incoming:
        tokens = _author_tokens(author)
        if tokens not in existing_tokens:
            result.append(author)
            existing_tokens.append(tokens)
    return result


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
