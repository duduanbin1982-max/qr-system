"""Material and supplier application services."""
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.material_repository import MaterialRepository, SupplierRepository
from modules.repositories.material_consumption_repository import MaterialConsumptionRepository


class MaterialNotFoundError(NotFoundError):
    """Raised when a material is not found."""
    pass


class MaterialService:
    """Material management business operations."""

    @staticmethod
    def _actor(user):
        user = user or {}
        return (
            user.get('id'),
            user.get('name') or user.get('username') or '系统',
        )

    @staticmethod
    def list_materials(page=1, limit=100):
        """Return a paginated material list with supplier names."""
        total = MaterialRepository.count_all()
        offset = (page - 1) * limit
        rows = MaterialRepository.find_all_with_supplier_paginated(limit, offset)
        return {
            'materials': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def create_material(data, user=None):
        """Create material. Raises ValueError on empty name or duplicate name+spec+material_type."""
        name = data.get('name', '').strip()
        if not name:
            raise ValidationError('物料名称不能为空')
        spec = (data.get('spec') or '').strip()
        mt = (data.get('material_type') or '').strip()
        existing = MaterialRepository.check_duplicate(name, spec, mt)
        if existing:
            info = name
            if spec:
                info += '(' + '规格' + ':' + spec
                if mt:
                    info += ', ' + '材质' + ':' + mt
                info += ')'
            raise ConflictError('物料' + info + '已存在')
        opening_quantity = float(data.get('quantity', 0))
        data_tuple = (
            name,
            spec,
            data.get('unit', '件').strip(),
            opening_quantity,
            float(data.get('unit_price', 0)),
            float(data.get('safe_stock', 0)),
            data.get('location', '').strip(),
            data.get('supplier_id') or None,
            data.get('remark', '').strip(),
            mt
        )
        with BaseService.transaction() as txn:
            material_id = MaterialRepository.insert(data_tuple, db=txn)
            if opening_quantity > 0:
                operator_id, operator_name = MaterialService._actor(user)
                MaterialRepository.insert_log(
                    material_id,
                    'in',
                    opening_quantity,
                    '期初库存',
                    operator_name,
                    operator_id=operator_id,
                    balance_before=0,
                    balance_after=opening_quantity,
                    source_type='opening_balance',
                    source_id=material_id,
                    db=txn,
                )
            return material_id

    @staticmethod
    def update_material(mid, data):
        """Update a material after validating identity and uniqueness."""
        row = MaterialRepository.find_by_id(mid)
        if not row:
            raise MaterialNotFoundError('物料不存在')
        if 'quantity' in data:
            raise ValidationError('库存数量请通过出入库功能调整')

        # Validate the effective unique material identity before updating.
        if 'name' in data:
            name = str(data['name']).strip()
            spec = str(data.get('spec', '')).strip()
            mt = str(data.get('material_type', '')).strip()
            dup = MaterialRepository.check_duplicate(name, spec, mt, exclude_id=mid)
            if dup:
                info = name
                if spec:
                    info += '(' + '规格' + ':' + spec
                    if mt:
                        info += ', ' + '材质' + ':' + mt
                    info += ')'
                raise ConflictError('物料' + info + '已存在')

        set_clauses = []
        params = []
        for k in ['name', 'spec', 'unit', 'location', 'remark', 'material_type']:
            if k in data:
                set_clauses.append(f'{k} = ?')
                params.append(str(data[k]).strip())
        for k in ['unit_price', 'safe_stock', 'supplier_id']:
            if k in data:
                if data[k] is None and k == 'supplier_id':
                    set_clauses.append(f'{k} = NULL')
                else:
                    set_clauses.append(f'{k} = ?')
                    params.append(float(data[k] or 0))
        if not set_clauses:
            raise ValidationError('没有可更新的字段')

        set_clauses.append("updated_at = datetime('now','localtime')")
        with BaseService.transaction() as txn:
            MaterialRepository.update(mid, set_clauses, params, db=txn)

    @staticmethod
    def check_impact(mid):
        mat = MaterialRepository.find_by_id(mid)
        if not mat:
            raise MaterialNotFoundError('物料不存在')
        refs = MaterialRepository.count_refs(mid)
        return {"material_id": mid, "name": mat["name"], "refs": refs}

    @staticmethod
    def delete_material(mid):
        """Delete a material only when no business records reference it."""
        mat = MaterialRepository.find_by_id(mid)
        if not mat:
            raise MaterialNotFoundError('物料不存在')
        refs = MaterialRepository.count_refs(mid)
        if refs > 0:
            raise ConflictError(f'物料「{mat["name"]}」已有 {refs} 条关联记录，无法删除')
        with BaseService.transaction() as txn:
            MaterialRepository.delete_logs_by_material(mid, db=txn)
            MaterialRepository.delete(mid, db=txn)

    @staticmethod
    def get_logs(mid, page=1, limit=100):
        """Return paginated material inventory movements."""
        total = MaterialRepository.count_logs_by_material(mid)
        offset = (page - 1) * limit
        rows = MaterialRepository.find_logs_by_material_paginated(mid, limit, offset)
        logs = []
        for row in rows:
            item = dict(row)
            item['operator_name'] = item.get('operator_name_from_fk') or item.get('operator_name') or ''
            logs.append(item)
        return {
            'logs': logs,
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def stock_change(
        mid,
        change_type,
        quantity,
        remark='',
        operator_name='',
        operator_id=None,
    ):
        """Apply a validated inbound or outbound stock movement."""
        if change_type not in ('in', 'out'):
            raise ValidationError('库存变动类型必须是 in 或 out')
        if quantity <= 0:
            raise ValidationError('数量必须大于 0')

        with BaseService.transaction() as txn:
            delta = quantity if change_type == 'in' else -quantity
            transition = MaterialRepository.apply_quantity_delta(mid, delta, db=txn)
            if transition is None:
                raise MaterialNotFoundError('物料不存在')
            if transition['insufficient']:
                raise ConflictError(f'库存不足，当前库存为 {transition["balance_before"]}')
            MaterialRepository.insert_log(
                mid,
                change_type,
                quantity,
                remark,
                operator_name,
                operator_id=operator_id,
                balance_before=transition['balance_before'],
                balance_after=transition['balance_after'],
                source_type='manual_stock',
                db=txn,
            )
        return transition['balance_after']

    @staticmethod
    def list_consumptions(mid, page=1, limit=100):
        """Return paginated material consumption records."""
        total = MaterialRepository.count_consumptions_by_material(mid)
        offset = (page - 1) * limit
        rows = MaterialRepository.find_consumptions_by_material_paginated(mid, limit, offset)
        consumptions = []
        for row in rows:
            item = dict(row)
            item['operator_name'] = item.get('operator_name_from_fk') or item.get('operator_name') or ''
            consumptions.append(item)
        return {
            'consumptions': consumptions,
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def create_consumption(mid, order_id, process_id, quantity, notes='',
                           operator_name='', user_id=None):
        """Record material consumption and deduct stock atomically."""
        if quantity <= 0:
            raise ValidationError('数量必须大于 0')

        with BaseService.transaction() as txn:
            transition = MaterialRepository.apply_quantity_delta(mid, -quantity, db=txn)
            if transition is None:
                raise MaterialNotFoundError('物料不存在')
            if transition['insufficient']:
                raise ConflictError(f'库存不足，当前库存为 {transition["balance_before"]}')
            consumption_id = MaterialRepository.insert_consumption(
                mid, order_id, process_id, quantity,
                user_id, operator_name, notes, db=txn
            )
            MaterialRepository.insert_log(
                mid,
                'out',
                quantity,
                f'消耗: {notes}' if notes else '消耗',
                operator_name,
                operator_id=user_id,
                balance_before=transition['balance_before'],
                balance_after=transition['balance_after'],
                source_type='consumption',
                source_id=consumption_id,
                db=txn,
            )
        return transition['balance_after']

    @staticmethod
    def delete_consumption(cid, reason, user=None):
        """Reverse a material consumption and preserve the original record."""
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError('请填写撤销原因')
        operator_id, operator_name = MaterialService._actor(user)
        with BaseService.transaction() as txn:
            mc = MaterialRepository.find_consumption_by_id(cid, db=txn)
            if not mc:
                raise NotFoundError('物料消耗记录不存在')
            if (mc['status'] or 'active') != 'active':
                raise ConflictError('该消耗记录已经撤销')
            transition = MaterialRepository.apply_quantity_delta(
                mc['material_id'], mc['quantity'], db=txn
            )
            original_log = MaterialRepository.find_log_for_source(
                'consumption', cid, db=txn
            )
            reversal_log_id = MaterialRepository.insert_log(
                mc['material_id'],
                'reversal',
                mc['quantity'],
                f'撤销消耗: {reason}',
                operator_name,
                operator_id=operator_id,
                balance_before=transition['balance_before'],
                balance_after=transition['balance_after'],
                source_type='consumption_reversal',
                source_id=cid,
                reversal_of_log_id=original_log['id'] if original_log else None,
                db=txn,
            )
            if not MaterialRepository.mark_consumption_reversed(
                cid,
                operator_id,
                reason,
                reversal_log_id,
                db=txn,
            ):
                raise ConflictError('该消耗记录已经撤销')
        return {
            'material_id': mc['material_id'],
            'new_quantity': transition['balance_after'],
            'reversal_log_id': reversal_log_id,
        }

    @staticmethod
    def deduct_for_process(order_id, process_id, quantity, user_id, user_name, db):
        """Apply approved-report material deductions through the stock ledger."""
        material_rows = MaterialConsumptionRepository.deduction_candidates(
            order_id, process_id, db=db
        )
        shortages = []
        for material in material_rows:
            deduct_quantity = quantity * material['quantity_per_unit']
            stock_quantity = material['stock_qty'] or 0
            if stock_quantity < deduct_quantity:
                shortages.append({
                    'material_id': material['material_id'],
                    'required_quantity': deduct_quantity,
                    'available_quantity': stock_quantity,
                })
                continue
            transition = MaterialRepository.apply_quantity_delta(
                material['material_id'], -deduct_quantity, db=db
            )
            consumption_id = MaterialRepository.insert_consumption(
                material['material_id'],
                order_id,
                process_id,
                deduct_quantity,
                user_id,
                user_name,
                'auto-deduct from order BOM',
                db=db,
            )
            MaterialRepository.insert_log(
                material['material_id'],
                'out',
                deduct_quantity,
                'auto-deduct',
                user_name,
                operator_id=user_id,
                balance_before=transition['balance_before'],
                balance_after=transition['balance_after'],
                source_type='auto_consumption',
                source_id=consumption_id,
                db=db,
            )
        return shortages


class SupplierService:
    """Supplier management business operations."""

    @staticmethod
    def list_suppliers(page=1, limit=100):
        """Return a paginated supplier list."""
        total = SupplierRepository.count_all()
        offset = (page - 1) * limit
        rows = SupplierRepository.find_all_paginated(limit, offset)
        return {
            'suppliers': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def create_supplier(data):
        """Create a supplier after validating its name."""
        name = data.get('name', '').strip()
        if not name:
            raise ValidationError('供应商名称不能为空')
        data_tuple = (
            name,
            data.get('contact', '').strip(),
            data.get('phone', '').strip(),
            data.get('address', '').strip(),
            data.get('remark', '').strip()
        )
        with BaseService.transaction() as txn:
            return SupplierRepository.insert(data_tuple, db=txn)

    @staticmethod
    def update_supplier(sid, data):
        """Update an existing supplier."""
        row = SupplierRepository.find_by_id(sid)
        if not row:
            raise NotFoundError('供应商不存在')
        data_tuple = (
            data.get('name', '').strip(),
            data.get('contact', '').strip(),
            data.get('phone', '').strip(),
            data.get('address', '').strip(),
            data.get('remark', '').strip()
        )
        with BaseService.transaction() as txn:
            SupplierRepository.update(sid, data_tuple, db=txn)

    @staticmethod
    def delete_supplier(sid):
        """Delete a supplier only when no materials reference it."""
        sup = SupplierRepository.find_by_id(sid)
        if not sup:
            raise NotFoundError('供应商不存在')
        refs = SupplierRepository.count_refs(sid)
        if refs > 0:
            raise ConflictError(f'供应商「{sup["name"]}」被 {refs} 条物料记录引用，无法删除')
        with BaseService.transaction() as txn:
            SupplierRepository.delete(sid, db=txn)
