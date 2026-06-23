"""Service-layer compatibility exports."""
from modules.db_unit_of_work import BaseService, get_db_path, set_test_db_path

__all__ = ["BaseService", "get_db_path", "set_test_db_path"]
