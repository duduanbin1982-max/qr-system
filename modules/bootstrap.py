"""Application bootstrap helpers shared by every executable entry point.

Environment loading must happen before importing ``modules.config`` because the
configuration module intentionally fails closed when ``SECRET_KEY`` is absent.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_environment(project_root=None):
    """Load the project ``.env`` without overwriting explicit environment values."""
    root = Path(project_root or PROJECT_ROOT).resolve()
    env_file = root / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    return os.environ
