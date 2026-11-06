"""Prevent the standard server access logger from recording OAuth query strings."""

import logging


class OAuthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def install_access_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, OAuthAccessFilter) for f in logger.filters):
        logger.addFilter(OAuthAccessFilter())
