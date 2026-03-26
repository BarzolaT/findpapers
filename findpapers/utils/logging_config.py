"""Shared logging configuration utilities for runners."""

from __future__ import annotations

import logging

# Third-party loggers that produce excessive output at DEBUG level.
_NOISY_LOGGERS = ("urllib3", "requests", "curl_cffi", "charset_normalizer")


def configure_verbose_logging() -> None:
    """Enable DEBUG-level logging while suppressing noisy third-party loggers.

    Sets the root logger to DEBUG and restricts known noisy HTTP-related
    loggers to WARNING so that only findpapers' own debug messages appear.
    """
    logging.getLogger().setLevel(logging.DEBUG)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
