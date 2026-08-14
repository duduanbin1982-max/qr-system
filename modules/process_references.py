"""Compatibility exports for the centralized master-data reference catalog."""

from modules.master_data_references import (
    MASTER_DATA_REFERENCES,
    PROCESS_REFERENCES,
    PROCESS_REFERENCE_TABLES,
    ROUTE_REFERENCES,
    ROUTE_REFERENCE_TABLES,
    ReferenceSpec,
)


ProcessReference = ReferenceSpec

__all__ = [
    "MASTER_DATA_REFERENCES",
    "PROCESS_REFERENCES",
    "PROCESS_REFERENCE_TABLES",
    "ROUTE_REFERENCES",
    "ROUTE_REFERENCE_TABLES",
    "ProcessReference",
]
