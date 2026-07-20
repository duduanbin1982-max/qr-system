"""Runtime deployment version exposed by health endpoints."""

from pathlib import Path


DEPLOYED_COMMIT_FILE = Path(__file__).resolve().parents[1] / ".deployed_commit"


def get_deployed_commit():
    try:
        commit = DEPLOYED_COMMIT_FILE.read_text(encoding="ascii").strip().lower()
    except OSError:
        return "unknown"
    if 7 <= len(commit) <= 40 and all(character in "0123456789abcdef" for character in commit):
        return commit
    return "unknown"
