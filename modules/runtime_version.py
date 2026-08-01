"""Runtime deployment version exposed by health endpoints."""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_MANIFEST_FILE = PROJECT_ROOT / "package.json"
DEPLOYED_COMMIT_FILE = PROJECT_ROOT / ".deployed_commit"


def get_application_version():
    """Return the application version from the authoritative package manifest."""
    try:
        manifest = json.loads(PACKAGE_MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    version = str(manifest.get("version") or "").strip()
    return version or "unknown"


def get_deployed_commit():
    try:
        commit = DEPLOYED_COMMIT_FILE.read_text(encoding="ascii").strip().lower()
    except OSError:
        return "unknown"
    if 7 <= len(commit) <= 40 and all(character in "0123456789abcdef" for character in commit):
        return commit
    return "unknown"
