"""Shared logging setup for PawPal+.

Both entry points (app.py, main.py) call configure_logging() once at import time. It writes
to the console and to a local pawpal.log file, and is idempotent -- safe to call on every
Streamlit rerun without piling up duplicate handlers on the root logger.
"""

import logging
import os

LOG_FILE = "pawpal.log"


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # already configured by an earlier call (e.g. an earlier Streamlit rerun)

    root.setLevel(os.environ.get("PAWPAL_LOG_LEVEL", "INFO").upper())
    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
