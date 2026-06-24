"""Schema definitions."""

from modules.schemas.approvals import approvals_schemas
from modules.schemas.auth import auth_schemas
from modules.schemas.customers import customers_schemas
from modules.schemas.inventory import inventory_schemas
from modules.schemas.materials import materials_schemas
from modules.schemas.orders import orders_schemas
from modules.schemas.positions import positions_schemas
from modules.schemas.processes import processes_schemas
from modules.schemas.products import products_schemas
from modules.schemas.quality import quality_schemas
from modules.schemas.scan import scan_schemas
from modules.schemas.suppliers import suppliers_schemas
from modules.schemas.users import users_schemas


SCHEMAS = {}
SCHEMAS.update(approvals_schemas)
SCHEMAS.update(auth_schemas)
SCHEMAS.update(customers_schemas)
SCHEMAS.update(inventory_schemas)
SCHEMAS.update(materials_schemas)
SCHEMAS.update(orders_schemas)
SCHEMAS.update(positions_schemas)
SCHEMAS.update(processes_schemas)
SCHEMAS.update(products_schemas)
SCHEMAS.update(quality_schemas)
SCHEMAS.update(scan_schemas)
SCHEMAS.update(suppliers_schemas)
SCHEMAS.update(users_schemas)
