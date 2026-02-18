"""Utilities for creating consistently styled tqdm progress bars."""

from __future__ import annotations

from tqdm import tqdm


def make_progress_bar(
    desc: str | None = None,
    total: int | None = None,
    unit: str = "item",
) -> tqdm:
    """Create a tqdm progress bar with the project's standard style.

    Centralises all tqdm configuration so every runner produces visually
    uniform progress bars.  The shared defaults are:

    * ``leave=True`` — the completed bar remains visible after finishing.
    * ``dynamic_ncols=True`` — the bar adapts to the current terminal width.

    Parameters
    ----------
    desc : str | None
        Short label displayed before the bar (e.g. ``"Downloading"`` or a
        database name like ``"arxiv"``).  ``None`` omits the label.
    total : int | None
        Expected total number of units.  ``None`` leaves the bar in
        indeterminate mode.
    unit : str
        Singular label for one unit of work (e.g. ``"paper"``).

    Returns
    -------
    tqdm
        Configured, ready-to-use tqdm instance.  Callers are responsible
        for closing it (e.g. via a context manager or ``.close()``).

    Examples
    --------
    >>> pbar = make_progress_bar(desc="Downloading", total=100, unit="paper")
    >>> pbar.update(1)
    >>> pbar.close()
    """
    return tqdm(
        desc=desc,
        total=total,
        unit=unit,
        leave=True,
        dynamic_ncols=True,
    )
