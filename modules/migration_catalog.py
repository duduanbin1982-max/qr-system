"""Authoritative migration catalog and explicit linear dependency contract."""

from modules.migration_approval_policy import MIGRATIONS as APPROVAL_POLICY_MIGRATIONS
from modules.migration_approval_workflow import MIGRATIONS as APPROVAL_WORKFLOW_MIGRATIONS
from modules.migration_audit import MIGRATIONS as AUDIT_MIGRATIONS
from modules.migration_auth import MIGRATIONS as AUTH_MIGRATIONS
from modules.migration_baseline import MIGRATIONS as BASELINE_MIGRATIONS
from modules.migration_company_profile import MIGRATIONS as COMPANY_PROFILE_MIGRATIONS
from modules.migration_core import MIGRATIONS as CORE_MIGRATIONS
from modules.migration_inventory_ledger import MIGRATIONS as INVENTORY_LEDGER_MIGRATIONS
from modules.migration_materials import MIGRATIONS as MATERIAL_MIGRATIONS
from modules.migration_order_completion import MIGRATIONS as ORDER_COMPLETION_MIGRATIONS
from modules.migration_order_qr_print import MIGRATIONS as ORDER_QR_PRINT_MIGRATIONS
from modules.migration_payroll_ledger import MIGRATIONS as PAYROLL_LEDGER_MIGRATIONS
from modules.migration_pending_route_price_v074 import (
    PENDING_ROUTE_PRICE_MIGRATIONS,
)
from modules.migration_performance import MIGRATIONS as PERFORMANCE_MIGRATIONS
from modules.migration_performance_department import MIGRATIONS as PERFORMANCE_DEPARTMENT_MIGRATIONS
from modules.migration_position_versioning import MIGRATIONS as POSITION_VERSIONING_MIGRATIONS
from modules.migration_process_config import MIGRATIONS as PROCESS_CONFIG_MIGRATIONS
from modules.migration_process_management import MIGRATIONS as PROCESS_MANAGEMENT_MIGRATIONS
from modules.migration_process_quality import MIGRATIONS as PROCESS_QUALITY_MIGRATIONS
from modules.migration_process_versioning import MIGRATIONS as PROCESS_VERSIONING_MIGRATIONS
from modules.migration_process_content_digest_v075 import (
    MIGRATIONS as PROCESS_CONTENT_DIGEST_MIGRATIONS,
)
from modules.migration_product_identity import MIGRATIONS as PRODUCT_IDENTITY_MIGRATIONS
from modules.migration_product_integrity import MIGRATIONS as PRODUCT_INTEGRITY_MIGRATIONS
from modules.migration_quality_management import MIGRATIONS as QUALITY_MANAGEMENT_MIGRATIONS
from modules.migration_reporting import MIGRATIONS as REPORTING_MIGRATIONS
from modules.migration_role_group_permissions import MIGRATIONS as ROLE_GROUP_PERMISSION_MIGRATIONS
from modules.migration_role_management import MIGRATIONS as ROLE_MANAGEMENT_MIGRATIONS
from modules.migration_schedule_capacity import MIGRATIONS as SCHEDULE_CAPACITY_MIGRATIONS
from modules.migration_serial_backfill import MIGRATIONS as SERIAL_BACKFILL_MIGRATIONS
from modules.migration_shipment_lifecycle import MIGRATIONS as SHIPMENT_LIFECYCLE_MIGRATIONS
from modules.migration_user_management import MIGRATIONS as USER_MANAGEMENT_MIGRATIONS
from modules.migration_work_time import MIGRATIONS as WORK_TIME_MIGRATIONS


MIGRATIONS = sorted(
    [
        *BASELINE_MIGRATIONS, *CORE_MIGRATIONS, *PERFORMANCE_MIGRATIONS,
        *WORK_TIME_MIGRATIONS, *AUTH_MIGRATIONS, *ORDER_COMPLETION_MIGRATIONS,
        *PROCESS_QUALITY_MIGRATIONS, *QUALITY_MANAGEMENT_MIGRATIONS,
        *MATERIAL_MIGRATIONS, *APPROVAL_WORKFLOW_MIGRATIONS,
        *ORDER_QR_PRINT_MIGRATIONS, *SERIAL_BACKFILL_MIGRATIONS,
        *PROCESS_MANAGEMENT_MIGRATIONS, *PRODUCT_IDENTITY_MIGRATIONS,
        *INVENTORY_LEDGER_MIGRATIONS, *SHIPMENT_LIFECYCLE_MIGRATIONS,
        *REPORTING_MIGRATIONS, *PAYROLL_LEDGER_MIGRATIONS,
        *PERFORMANCE_DEPARTMENT_MIGRATIONS, *USER_MANAGEMENT_MIGRATIONS,
        *PROCESS_VERSIONING_MIGRATIONS, *PRODUCT_INTEGRITY_MIGRATIONS,
        *COMPANY_PROFILE_MIGRATIONS, *AUDIT_MIGRATIONS,
        *PROCESS_CONFIG_MIGRATIONS, *ROLE_GROUP_PERMISSION_MIGRATIONS,
        *ROLE_MANAGEMENT_MIGRATIONS, *POSITION_VERSIONING_MIGRATIONS,
        *APPROVAL_POLICY_MIGRATIONS,
        *PENDING_ROUTE_PRICE_MIGRATIONS,
        *PROCESS_CONTENT_DIGEST_MIGRATIONS,
        *SCHEDULE_CAPACITY_MIGRATIONS,
    ],
    key=lambda migration: migration[0],
)

# SQLite user_version represents one linear schema state. Keeping the chain separate
# from function registration makes missing versions and accidental reordering explicit.
MIGRATION_VERSION_CHAIN = (1, *range(13, 83))
MIGRATION_DEPENDENCIES = {
    version: (() if index == 0 else (MIGRATION_VERSION_CHAIN[index - 1],))
    for index, version in enumerate(MIGRATION_VERSION_CHAIN)
}
