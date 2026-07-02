"""Repository database access seam.

Repository methods accept an explicit db for transactions and tests. When callers
do not pass one, repositories resolve the current request connection here instead
of depending on service-layer helpers.
"""

from modules.db import get_db


def resolve_db(db=None):
    """Return the supplied connection or the current request database connection."""
    return db if db is not None else get_db()
