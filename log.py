"""
Pipeline logging setup.

- Forces unbuffered stdout/stderr (so prints show immediately)
- Tees all stdout to a log file in the output directory
- Provides a structured logger with timestamps for key events

Usage in main.py:
    from log import setup_logging
    logger = setup_logging(component.output_dir)
    logger.info("Pipeline started")
"""

import logging
import sys
from pathlib import Path


class TeeWriter:
    def __init__(self, *files):
        self.files = files

    def write(self, data):
        for f in self.files:
            f.write(data)

    def flush(self):
        for f in self.files:
            f.flush()


_original_stdout = sys.stdout
_original_stderr = sys.stderr


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    log_file = open(log_dir / "pipeline.log", "w", buffering=1)
    sys.stdout = TeeWriter(_original_stdout, log_file)

    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"
    )

    ch = logging.StreamHandler(_original_stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_dir / "structured.log", mode="w")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("pipeline")
