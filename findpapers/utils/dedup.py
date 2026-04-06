_PREPRINT_DOI_PREFIXES: frozenset[str] = frozenset(
    {
        "10.48550/arxiv.",  # arXiv
        "10.1101/",  # bioRxiv / medRxiv
        "10.2139/ssrn.",  # SSRN
        "10.5281/zenodo.",  # Zenodo
        "10.20944/preprints",  # Preprints.org
    }
)


def _is_preprint_doi(doi: str) -> bool:
    """Return ``True`` when *doi* belongs to a preprint server.

    Parameters
    ----------
    doi : str
        DOI string (without ``https://doi.org/`` prefix).

    Returns
    -------
    bool
        ``True`` for known preprint-server DOI prefixes.
    """
    lowered = doi.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _PREPRINT_DOI_PREFIXES)


def _are_years_compatible(
    year_a: int | None,
    year_b: int | None,
    doi_a: str | None,
    doi_b: str | None,
) -> bool:
    """Return whether two publication years are compatible for merging.

    Two papers are considered year-compatible when:

    * Either year is unknown (``None``), or
    * Both years are identical, or
    * Their years differ by exactly 1 **and** at least one DOI belongs to a
      preprint server (covers preprint-to-published transitions across the
      Dec/Jan boundary).

    Parameters
    ----------
    year_a : int | None
        Publication year of the first paper.
    year_b : int | None
        Publication year of the second paper.
    doi_a : str | None
        DOI of the first paper.
    doi_b : str | None
        DOI of the second paper.

    Returns
    -------
    bool
        ``True`` when the years are compatible for merging.
    """
    if year_a is None or year_b is None or year_a == year_b:
        return True

    # Adjacent-year preprint check.
    raw_doi_a = doi_a or ""
    raw_doi_b = doi_b or ""
    return (
        abs(year_a - year_b) == 1
        and bool(raw_doi_a)
        and bool(raw_doi_b)
        and (_is_preprint_doi(raw_doi_a) or _is_preprint_doi(raw_doi_b))
    )
