"""Compatibility facade for the V060-V063 process-version migrations."""

from modules.migration_process_versioning_common import (
    PROCESS_FACT_BINDINGS,
    PROCESS_FACT_MIGRATION_KEY,
)
from modules.migration_process_versioning_v060 import m060_process_master_versioning
from modules.migration_process_versioning_v061 import m061_bind_order_versions
from modules.migration_process_versioning_v062 import m062_bind_price_versions
from modules.migration_process_versioning_v063 import m063_version_process_facts


MIGRATIONS = [
    (60, "Add versioned process and route master-data baseline", m060_process_master_versioning),
    (61, "Bind orders to process and route versions", m061_bind_order_versions),
    (62, "Bind payroll prices to route and process versions", m062_bind_price_versions),
    (63, "Version process and route references across business facts", m063_version_process_facts),
]

__all__ = [
    "MIGRATIONS",
    "PROCESS_FACT_BINDINGS",
    "PROCESS_FACT_MIGRATION_KEY",
    "m060_process_master_versioning",
    "m061_bind_order_versions",
    "m062_bind_price_versions",
    "m063_version_process_facts",
]
