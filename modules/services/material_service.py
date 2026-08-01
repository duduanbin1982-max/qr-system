"""Material and supplier application services."""
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.material_requirements import MaterialRequirementPolicy
from modules.repositories.material_repository import MaterialRepository, SupplierRepository
from modules.repositories.material_consumption_repository import MaterialConsumptionRepository


class MaterialNotFoundError(NotFoundError):
    """Raised when a material is not found."""
    pass


class MaterialService:
    """Material management business operations."""

    repository = None
    consumption_repository = None
    unit_of_work = None

    @classmethod
    def _repository(cls):
        return cls.repository or MaterialRepository

    @classmethod
    def _consumption_repository(cls):
        return cls.consumption_repository or MaterialConsumptionRepository

    @classmethod
    def _unit_of_work(cls):
        return cls.unit_of_work or BaseService

    @staticmethod
    def _actor(user):
        user = user or {}
        return (
            user.get('id'),
            user.get('name') or user.get('username') or '系统',
        )

    @staticmethod
    def list_materials(page=1, limit=100, keyword='', material_type=''):
        """Return a filtered material page with global inventory metrics."""
        repository = MaterialService._repository()
        total = repository.count_filtered(keyword, material_type)
        offset = (page - 1) * limit
        rows = repository.find_all_with_supplier_paginated(
            limit,
            offset,
            keyword=keyword,
            material_type=material_type,
        )
        value_rows = repository.find_inventory_values()
        total_value = sum(float(row['inventory_value'] or 0) for row in value_rows)
        cumulative = 0
        abc_ranks = {}
        for row in value_rows:
            cumulative += float(row['inventory_value'] or 0)
            ratio = cumulative / total_value if total_value > 0 else 1
            abc_ranks[row['id']] = 'A' if ratio <= 0.70 else 'B' if ratio <= 0.90 else 'C'

        materials = []
        for row in rows:
            item = dict(row)
            item['abc_class'] = abc_ranks.get(item['id'], 'C')
            materials.append(item)
        return {
            'materials': materials,
            'total': total,
            'page': page,
            'limit': limit,
            'summary': repository.inventory_summary(),
            'material_types': repository.list_material_types(),
        }

    @staticmethod
    def create_material(data, user=None):
        """Create material. Raises ValueError on empty name or duplicate name+spec+material_type."""
        name = data.get('name', '').strip()
        if not name:
            raise ValidationError('物料名称不能为空')
        spec = (data.get('spec') or '').strip()
        mt = (data.get('material_type') or '').strip()
        repository = MaterialService._repository()
        existing = repository.check_duplicate(name, spec, mt)
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
        with MaterialService._unit_of_work().transaction() as txn:
            material_id = repository.insert(data_tuple, db=txn)
            if opening_quantity > 0:
                operator_id, operator_name = MaterialService._actor(user)
                repository.insert_log(
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
        repository = MaterialService._repository()
        row = repository.find_by_id(mid)
        if not row:
            raise MaterialNotFoundError('物料不存在')
        if 'quantity' in data:
            raise ValidationError('库存数量请通过出入库功能调整')

        # Validate the effective unique material identity before updating.
        if 'name' in data:
            name = str(data['name']).strip()
            spec = str(data.get('spec', '')).strip()
            mt = str(data.get('material_type', '')).strip()
            dup = repository.check_duplicate(name, spec, mt, exclude_id=mid)
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
        with MaterialService._unit_of_work().transaction() as txn:
            repository.update(mid, set_clauses, params, db=txn)

    @staticmethod
    def check_impact(mid):
        repository = MaterialService._repository()
        mat = repository.find_by_id(mid)
        if not mat:
            raise MaterialNotFoundError('物料不存在')
        references = repository.reference_counts(mid)
        return {
            "material_id": mid,
            "name": mat["name"],
            "refs": sum(references.values()),
            "references": references,
        }

    @staticmethod
    def delete_material(mid):
        """Delete a material only when no business records reference it."""
        repository = MaterialService._repository()
        with MaterialService._unit_of_work().transaction() as txn:
            mat = repository.find_by_id(mid, db=txn)
            if not mat:
                raise MaterialNotFoundError('物料不存在')
            references = repository.reference_counts(mid, db=txn)
            refs = sum(references.values())
            if refs > 0:
                raise ConflictError(
                    f'物料「{mat["name"]}」已有 {refs} 条关联记录，无法删除',
                    details={'references': references},
                )
            repository.delete_logs_by_material(mid, db=txn)
            repository.delete(mid, db=txn)

    @staticmethod
    def get_logs(mid, page=1, limit=100):
        """Return paginated material inventory movements."""
        repository = MaterialService._repository()
        total = repository.count_logs_by_material(mid)
        offset = (page - 1) * limit
        rows = repository.find_logs_by_material_paginated(mid, limit, offset)
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

        repository = MaterialService._repository()
        with MaterialService._unit_of_work().transaction() as txn:
            delta = quantity if change_type == 'in' else -quantity
            transition = repository.apply_quantity_delta(mid, delta, db=txn)
            if transition is None:
                raise MaterialNotFoundError('物料不存在')
            if transition['insufficient']:
                raise ConflictError(f'库存不足，当前库存为 {transition["balance_before"]}')
            repository.insert_log(
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
        repository = MaterialService._repository()
        total = repository.count_consumptions_by_material(mid)
        offset = (page - 1) * limit
        rows = repository.find_consumptions_by_material_paginated(mid, limit, offset)
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

        repository = MaterialService._repository()
        with MaterialService._unit_of_work().transaction() as txn:
            transition = repository.apply_quantity_delta(mid, -quantity, db=txn)
            if transition is None:
                raise MaterialNotFoundError('物料不存在')
            if transition['insufficient']:
                raise ConflictError(f'库存不足，当前库存为 {transition["balance_before"]}')
            consumption_id = repository.insert_consumption(
                mid, order_id, process_id, quantity,
                user_id, operator_name, notes, db=txn
            )
            repository.insert_log(
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
        repository = MaterialService._repository()
        with MaterialService._unit_of_work().transaction() as txn:
            mc = repository.find_consumption_by_id(cid, db=txn)
            if not mc:
                raise NotFoundError('物料消耗记录不存在')
            if (mc['status'] or 'active') != 'active':
                raise ConflictError('该消耗记录已经撤销')
            transition = repository.apply_quantity_delta(
                mc['material_id'], mc['quantity'], db=txn
            )
            original_log = repository.find_log_for_source(
                'consumption', cid, db=txn
            )
            reversal_log_id = repository.insert_log(
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
            if not repository.mark_consumption_reversed(
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
    def _assert_consumption_not_recorded(material_rows, work_record_id, db):
        if not material_rows or work_record_id is None:
            return
        existing = MaterialService._repository().find_consumptions_by_work_record(
            work_record_id, db=db
        )
        if existing:
            raise ConflictError(
                '该报工记录的物料已经扣减，请勿重复处理',
                details={
                    'work_record_id': work_record_id,
                    'consumption_ids': [row['id'] for row in existing],
                },
            )

    @staticmethod
    def _apply_process_requirement(
        requirement,
        order_id,
        process_id,
        user_id,
        user_name,
        work_record_id,
        db,
    ):
        repository = MaterialService._repository()
        transition = repository.apply_quantity_delta(
            requirement['material_id'],
            -requirement['required_quantity'],
            db=db,
        )
        if transition is None:
            raise MaterialNotFoundError('物料不存在')
        if transition['insufficient']:
            raise ConflictError(
                f"物料「{requirement['material_name']}」库存已发生变化，请重新提交"
            )
        consumption_id = repository.insert_consumption(
            requirement['material_id'],
            order_id,
            process_id,
            requirement['required_quantity'],
            user_id,
            user_name,
            'auto-deduct from order BOM',
            source_work_record_id=work_record_id,
            db=db,
        )
        repository.insert_log(
            requirement['material_id'],
            'out',
            requirement['required_quantity'],
            'auto-deduct',
            user_name,
            operator_id=user_id,
            balance_before=transition['balance_before'],
            balance_after=transition['balance_after'],
            source_type='auto_consumption',
            source_id=consumption_id,
            db=db,
        )

    @staticmethod
    def deduct_for_process(
        order_id,
        process_id,
        quantity,
        user_id,
        user_name,
        db,
        work_record_id=None,
    ):
        """Apply approved-report material deductions through the stock ledger."""
        material_rows = MaterialService._consumption_repository().deduction_candidates(
            order_id, process_id, db=db
        )
        MaterialService._assert_consumption_not_recorded(
            material_rows, work_record_id, db
        )
        requirements, shortages = MaterialRequirementPolicy.calculate(
            material_rows, quantity
        )
        MaterialRequirementPolicy.assert_sufficient(shortages)

        for requirement in requirements:
            MaterialService._apply_process_requirement(
                requirement,
                order_id,
                process_id,
                user_id,
                user_name,
                work_record_id,
                db,
            )
        return []


class SupplierService:
    """Supplier management business operations."""

    @staticmethod
    def list_suppliers(page=1, limit=100, keyword=''):
        """Return a filtered, paginated supplier list."""
        total = SupplierRepository.count_filtered(keyword)
        offset = (page - 1) * limit
        rows = SupplierRepository.find_all_paginated(limit, offset, keyword=keyword)
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
        with BaseService.transaction() as txn:
            sup = SupplierRepository.find_by_id(sid, db=txn)
            if not sup:
                raise NotFoundError('供应商不存在')
            references = SupplierRepository.reference_counts(sid, db=txn)
            refs = sum(references.values())
            if refs > 0:
                raise ConflictError(
                    f'供应商「{sup["name"]}」已有 {refs} 条关联记录，无法删除',
                    details={'references': references},
                )
            SupplierRepository.delete(sid, db=txn)
