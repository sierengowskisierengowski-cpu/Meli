"""Structured logging setup for Meli."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
import structlog


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_file_handler(log_path: Path, level: int = logging.INFO) -> logging.FileHandler:
    log_path.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path / "meli.log")
    handler.setLevel(level)
    return handler
