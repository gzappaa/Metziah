# logging_config.py
"""
Central logging setup for Metziah.

Three ways to get a logger here:

1. setup_logging(name) -- for daily pipeline entry points: scheduler.py,
   prices.py, pricesfull.py, promosfull.py. Configures the ROOT logger
   for that process, writing to logs/<name>.log. Because it's root,
   everything that runs during that process -- including modules that
   just do logging.getLogger(__name__), like laibcatalog.py -- gets
   captured too, labeled with its own logger name.

2. setup_general_logging() -- for ad-hoc/manual scripts that aren't part
   of the daily pipeline (e.g. get_stores.py). Same mechanism as
   setup_logging, always writes to logs/general.log.

3. setup_isolated_logging(name) -- for logs that must be consumed
   independently and never mixed with anything else in the same
   process, regardless of what setup_logging/setup_general_logging did.
   Builds a NAMED logger with propagate=False, writing only to
   logs/<name>.log. Used by update_prices.py (price_changes.log) and
   get_stores.py's store-diff log (store_changes.log).

Modules that don't call any of these -- laibcatalog.py, parsers/xml.py,
geocode_google.py, etc. -- should just do
`logger = logging.getLogger(__name__)` and rely on whichever entry
point already configured root.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

ENV = os.environ.get("METZIA_ENV", "dev")  # dev | test | prod

_ENV_LEVELS = {
    "dev": logging.INFO,    ## CHANGE IT LATER
    "test": logging.WARNING,
    "prod": logging.INFO,
}


def _make_formatter():
    return logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _make_file_handler(filename: str) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        LOG_DIR / filename,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(_make_formatter())
    return handler


def setup_logging(name: str, log_to_console: bool | None = None) -> logging.Logger:
    """
    For pipeline entry points: scheduler.py, prices.py, pricesfull.py,
    promosfull.py. Configures the ROOT logger for this process, writing
    to logs/<name>.log. Because it's root, everything that runs in this
    process -- including modules that just do
    logging.getLogger(__name__), like laibcatalog.py -- propagates in
    too, labeled with its own logger name.
    """
    if log_to_console is None:
        log_to_console = ENV == "dev"

    root_logger = logging.getLogger()

    if root_logger.handlers:
        return root_logger

    root_logger.setLevel(_ENV_LEVELS.get(ENV, logging.INFO))
    root_logger.addHandler(_make_file_handler(f"{name}.log"))

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(_make_formatter())
        root_logger.addHandler(console_handler)

    return root_logger


def setup_general_logging(log_to_console: bool | None = None) -> None:
    """
    For ad-hoc scripts (get_stores.py, etc.) that aren't part of the
    daily pipeline. Same mechanism as setup_logging, always writes to
    logs/general.log.
    """
    setup_logging("general", log_to_console=log_to_console)


def setup_isolated_logging(
    name: str,
    log_to_console: bool = False,
) -> logging.Logger:
    """
    Create a logger with its own dedicated file.
    Does not propagate to root.

    Used for logs that are consumed independently,
    such as price_changes.log and store_changes.log.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(_ENV_LEVELS.get(ENV, logging.INFO))
    logger.propagate = False

    logger.addHandler(_make_file_handler(f"{name}.log"))

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(_make_formatter())
        logger.addHandler(console_handler)

    return logger