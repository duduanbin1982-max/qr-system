"""
qr-system ? ???? Service ?

Brooks R6 fix: ?? SQL ???? MaterialRepository / SupplierRepository?
Service ???????????????????
"""
from modules.services import BaseService
from modules.repositories.material_repository import MaterialRepository, SupplierRepository


class MaterialService:
    """?????????"""

    @staticmethod
    def list_materials(page=1, limit=100):
        """????????????????"""
        total = MaterialRepository.count_all()
        offset = (page - 1) * limit
        rows = MaterialRepository.find_all_with_supplier_paginated(limit, offset)
        return {
            'materials': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def create_material(data):
        """Create material. Raises ValueError on empty name or duplicate name+spec+material_type."""
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('物料名称不能为空')
        spec = (data.get('spec') or '').strip()
        mt = (data.get('material_type') or '').strip()
        existing = MaterialRepository.check_duplicate(name, spec, mt)
        if existing:
            info = name
            if spec:
                info += '(' + chr(35268) + chr(26684) + ':' + spec
                if mt:
                    info += ', ' + chr(26448) + chr(36136) + ':' + mt
                info += ')'
            raise ValueError('物料' + info + '已存在')
        data_tuple = (
            name,
            spec,
            data.get('unit', '件').strip(),
            float(data.get('quantity', 0)),
            float(data.get('unit_price', 0)),
            float(data.get('safe_stock', 0)),
            data.get('location', '').strip(),
            data.get('supplier_id') or None,
            data.get('remark', '').strip(),
            mt
        )
        with BaseService.transaction() as txn:
            return MaterialRepository.insert(data_tuple, db=txn)

    @staticmethod
    def update_material(mid, data):
        """?????Raises ValueError on not found or no fields."""
        row = MaterialRepository.find_by_id(mid)
        if not row:
            raise ValueError('?????')

        # ????????????
        if 'name' in data:
            name = str(data['name']).strip()
            spec = str(data.get('spec', '')).strip()
            mt = str(data.get('material_type', '')).strip()
            dup = MaterialRepository.check_duplicate(name, spec, mt, exclude_id=mid)
            if dup:
                info = name
                if spec:
                    info += '(' + chr(35268) + chr(26684) + ':' + spec
                    if mt:
                        info += ', ' + chr(26448) + chr(36136) + ':' + mt
                    info += ')'
                raise ValueError(chr(29289) + chr(26009) + info + chr(24050) + chr(23384) + chr(22312))

        set_clauses = []
        params = []
        for k in ['name', 'spec', 'unit', 'location', 'remark', 'material_type']:
            if k in data:
                set_clauses.append(f'{k} = ?')
                params.append(str(data[k]).strip())
        for k in ['quantity', 'unit_price', 'safe_stock', 'supplier_id']:
            if k in data:
                if data[k] is None and k == 'supplier_id':
                    set_clauses.append(f'{k} = NULL')
                else:
                    set_clauses.append(f'{k} = ?')
                    params.append(float(data[k] or 0))
        if not set_clauses:
            raise ValueError('no fields to update')

        set_clauses.append("updated_at = datetime('now','localtime')")
        with BaseService.transaction() as txn:
            MaterialRepository.update(mid, set_clauses, params, db=txn)

    @staticmethod
    def delete_material(mid):
        """?????????????Raises ValueError on not found or has refs."""
        mat = MaterialRepository.find_by_id(mid)
        if not mat:
            raise ValueError('?????')
        refs = MaterialRepository.count_refs(mid)
        if refs > 0:
            raise ValueError(f'???{mat["name"]}??? {refs} ????????????')
        with BaseService.transaction() as txn:
            MaterialRepository.delete_logs_by_material(mid, db=txn)
            MaterialRepository.delete(mid, db=txn)

    @staticmethod
    def get_logs(mid, page=1, limit=100):
        """???????????"""
        total = MaterialRepository.count_logs_by_material(mid)
        offset = (page - 1) * limit
        rows = MaterialRepository.find_logs_by_material_paginated(mid, limit, offset)
        return {
            'logs': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def stock_change(mid, change_type, quantity, remark='', operator_name=''):
        """????/???Raises ValueError on validation failure."""
        if change_type not in ('in', 'out'):
            raise ValueError('????? in ? out')
        if quantity <= 0:
            raise ValueError('??????0')

        row = MaterialRepository.find_quantity_by_id(mid)
        if not row:
            raise ValueError('?????')

        new_qty = (row['quantity'] + quantity if change_type == 'in'
                   else row['quantity'] - quantity)
        if new_qty < 0 and change_type == 'out':
            raise ValueError(f'????????? {row["quantity"]}')

        with BaseService.transaction() as txn:
            MaterialRepository.update_quantity(mid, new_qty, db=txn)
            MaterialRepository.insert_log(
                mid, change_type, quantity, remark, operator_name, db=txn
            )
        return new_qty

    @staticmethod
    def list_consumptions(mid, page=1, limit=100):
        """??????????/?????????"""
        total = MaterialRepository.count_consumptions_by_material(mid)
        offset = (page - 1) * limit
        rows = MaterialRepository.find_consumptions_by_material_paginated(mid, limit, offset)
        return {
            'consumptions': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def create_consumption(mid, order_id, process_id, quantity, notes='',
                           operator_name='', user_id=None):
        """?????????????Raises ValueError on validation failure."""
        if quantity <= 0:
            raise ValueError('??????0')

        mat = MaterialRepository.find_quantity_by_id(mid)
        if not mat:
            raise ValueError('?????')
        if mat['quantity'] < quantity:
            raise ValueError(f'????????? {mat["quantity"]}')

        with BaseService.transaction() as txn:
            MaterialRepository.insert_consumption(
                mid, order_id, process_id, quantity,
                user_id, operator_name, notes, db=txn
            )
            new_qty = mat['quantity'] - quantity
            MaterialRepository.update_quantity(mid, new_qty, db=txn)
            MaterialRepository.insert_log(
                mid, 'out', quantity,
                f'??: {notes}' if notes else '??',
                operator_name, db=txn
            )
        return new_qty

    @staticmethod
    def delete_consumption(cid):
        """?????????????Raises ValueError if not found."""
        mc = MaterialRepository.find_consumption_by_id(cid)
        if not mc:
            raise ValueError('?????')

        with BaseService.transaction() as txn:
            MaterialRepository.increment_quantity(
                mc['material_id'], mc['quantity'], db=txn
            )
            MaterialRepository.delete_consumption_by_id(cid, db=txn)


class SupplierService:
    """??????????"""

    @staticmethod
    def list_suppliers(page=1, limit=100):
        """??????????"""
        total = SupplierRepository.count_all()
        offset = (page - 1) * limit
        rows = SupplierRepository.find_all_paginated(limit, offset)
        return {
            'suppliers': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def create_supplier(data):
        """??????Raises ValueError on empty name."""
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('?????????')
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
        """??????Raises ValueError if not found."""
        row = SupplierRepository.find_by_id(sid)
        if not row:
            raise ValueError('??????')
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
        """??????Raises ValueError if not found or has refs."""
        sup = SupplierRepository.find_by_id(sid)
        if not sup:
            raise ValueError('??????')
        refs = SupplierRepository.count_refs(sid)
        if refs > 0:
            raise ValueError(f'????{sup["name"]}?? {refs} ??????????')
        with BaseService.transaction() as txn:
            SupplierRepository.delete(sid, db=txn)
