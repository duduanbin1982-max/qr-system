"""Compatibility exports for the centralized master-data reference catalog."""

from modules.master_data_references import (
    PROCESS_REFERENCES,
    PROCESS_REFERENCE_TABLES,
    ReferenceSpec,
)


ProcessReference = ReferenceSpec

__all__ = ["PROCESS_REFERENCES", "PROCESS_REFERENCE_TABLES", "ProcessReference"]
