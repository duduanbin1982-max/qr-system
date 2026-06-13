"""qr-system — 质量检验 Service 层"""
from datetime import datetime
from modules.services import BaseService


INSPECTION_TYPES = {'first_article': '首件检验', 'in_process': '过程检验', 'final': '终检'}
DEFECT_CATEGORIES = ['尺寸超差', '外观缺陷', '材质问题', '焊接缺陷', '装配不良', '其他']  # 注：前端 InspectionList.js 中重复定义，修改需同步


class QualityService:

    @staticmethod
    def list_inspections(order_id=None, process_id=None, inspection_type='',
                         result='', search='', date_from='', date_to='',
                         page=1, per_page=20):
        db = BaseService.db()
        where = ['1=1']
        params = []
        if order_id:
            where.append('qi.order_id = ?'); params.append(order_id)
        if process_id:
            where.append('qi.process_id = ?'); params.append(process_id)
        if inspection_type:
            where.append('qi.inspection_type = ?'); params.append(inspection_type)
        if result:
            where.append('qi.result = ?'); params.append(result)
        if search:
            where.append('(o.order_no LIKE ? OR p.name LIKE ?)')
            params.extend([f'%{search}%'] * 2)
        if date_from:
            where.append('qi.inspected_at >= ?'); params.append(date_from)
        if date_to:
            where.append('qi.inspected_at <= ?'); params.append(date_to + ' 23:59:59')

        where_clause = ' AND '.join(where)
        total = db.execute(f'''SELECT COUNT(*) FROM quality_inspections qi
            JOIN orders o ON qi.order_id=o.id
            JOIN processes p ON qi.process_id=p.id
            WHERE {where_clause}''', params).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(f'''
            SELECT qi.*, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer_name,
                   p.name as process_name, u.name as inspector_name
            FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id
            LEFT JOIN customers c ON o.customer_id = c.id
            JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            WHERE {where_clause}
            ORDER BY qi.inspected_at DESC LIMIT ? OFFSET ?
        ''', params + [per_page, offset]).fetchall()
        return {'ok': True, 'items': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': per_page}

    @staticmethod
    def check_order_exists(order_id):
        """校验订单存在且未被软删除。Raises ValueError on failure."""
        db = BaseService.db()
        order = db.execute(
            'SELECT id, deleted_at FROM orders WHERE id = ?', (order_id,)
        ).fetchone()
        if not order:
            raise ValueError('订单不存在')
        if order['deleted_at'] is not None:
            raise ValueError('订单已删除，无法添加检验记录')
        return order

    @staticmethod
    def create_inspection(data, user_id):
        order_id = data.get('order_id')
        process_id = data.get('process_id')
        inspection_type = data.get('inspection_type', 'first_article')
        quantity_checked = data.get('quantity_checked', 0)
        quantity_passed = data.get('quantity_passed', 0)
        quantity_failed = data.get('quantity_failed', 0)
        defect_category = data.get('defect_category', '').strip()
        defect_quantity = data.get('defect_quantity', 0)
        notes = data.get('notes', '')
        inspected_at = data.get('inspected_at', '')

        if not order_id or not process_id:
            raise ValueError('订单和工序必填')
        if inspection_type not in INSPECTION_TYPES:
            raise ValueError('无效的检验类型')
        if defect_category and defect_category not in DEFECT_CATEGORIES:
            raise ValueError(f'无效的缺陷类别: {defect_category}')

        result = 'pass' if quantity_failed == 0 else ('fail' if quantity_passed == 0 else 'partial')

        with BaseService.transaction() as txn:
            cur = txn.execute('''
                INSERT INTO quality_inspections
                (order_id, process_id, inspection_type, inspector_id, quantity_checked,
                 quantity_passed, quantity_failed, result, defect_category, defect_quantity,
                 notes, inspected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (order_id, process_id, inspection_type, user_id, quantity_checked,
                  quantity_passed, quantity_failed, result, defect_category,
                  defect_quantity, notes, inspected_at or None))
            return cur.lastrowid


    @staticmethod
    def get_inspection(inspection_id):
        db = BaseService.db()
        qi = db.execute('SELECT * FROM quality_inspections WHERE id=?', (inspection_id,)).fetchone()
        if not qi:
            raise ValueError('记录不存在')
        return dict(qi)

    @staticmethod
    def update_inspection(inspection_id, data):
        db = BaseService.db()
        qi = db.execute('SELECT * FROM quality_inspections WHERE id=?', (inspection_id,)).fetchone()
        if not qi:
            raise ValueError('记录不存在')

        inspection_type = data.get('inspection_type', qi['inspection_type'])
        if inspection_type not in INSPECTION_TYPES:
            raise ValueError('无效的检验类型')
        defect_cat = data.get('defect_category', qi.get('defect_category', ''))
        if defect_cat and defect_cat not in DEFECT_CATEGORIES:
            raise ValueError(f'无效的缺陷类别: {defect_cat}')

        qc = data.get('quantity_checked', qi['quantity_checked'])
        qp = data.get('quantity_passed', qi['quantity_passed'])
        qf = data.get('quantity_failed', qi['quantity_failed'])
        result = 'pass' if qf == 0 else ('fail' if qp == 0 else 'partial')

        with BaseService.transaction() as txn:
            txn.execute('''UPDATE quality_inspections
                SET inspection_type=?, quantity_checked=?, quantity_passed=?,
                    quantity_failed=?, result=?, defect_category=?, defect_quantity=?,
                    notes=?, inspected_at=?
                WHERE id=?''',
                (inspection_type, qc, qp, qf, result,
                 data.get('defect_category', qi.get('defect_category', '')),
                 data.get('defect_quantity', qi.get('defect_quantity', 0)),
                 data.get('notes', qi['notes']),
                 data.get('inspected_at', qi['inspected_at']),
                 inspection_id))
        return result

    @staticmethod
    def delete_inspection(inspection_id):
        db = BaseService.db()
        qi = db.execute('SELECT * FROM quality_inspections WHERE id=?', (inspection_id,)).fetchone()
        if not qi:
            raise ValueError('记录不存在')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM quality_inspections WHERE id=?', (inspection_id,))

    @staticmethod
    def get_stats():
        """统计（2次查询替代4次）。"""
        db = BaseService.db()
        today = datetime.now().strftime('%Y-%m-%d')
        # 合并总计+通过+失败为1次查询
        agg = db.execute(
            "SELECT COUNT(*) as total, "
            "COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) as pass_count, "
            "COALESCE(SUM(CASE WHEN result IN ('fail','partial') THEN 1 ELSE 0 END),0) as fail_count "
            "FROM quality_inspections"
        ).fetchone()
        today_count = db.execute(
            "SELECT COUNT(*) FROM quality_inspections WHERE DATE(inspected_at)=?", (today,)
        ).fetchone()[0]
        return {'ok': True, 'total': agg['total'], 'today_count': today_count,
                'pass_count': agg['pass_count'], 'fail_count': agg['fail_count']}

    @staticmethod
    def defect_pareto(date_from='', date_to=''):
        db = BaseService.db()
        where = ["defect_category != ''"]
        params = []
        if date_from:
            where.append('inspected_at >= ?'); params.append(date_from)
        if date_to:
            where.append('inspected_at <= ?'); params.append(date_to + ' 23:59:59')
        where_clause = ' AND '.join(where)
        rows = db.execute(f'''
            SELECT defect_category, SUM(defect_quantity) as total_qty, COUNT(*) as count
            FROM quality_inspections WHERE {where_clause}
            GROUP BY defect_category ORDER BY total_qty DESC
        ''', params).fetchall()
        items = [{'category': r['defect_category'], 'quantity': r['total_qty'] or 0,
                  'count': r['count']} for r in rows]
        grand_total = sum(i['quantity'] for i in items)
        cumulative = 0
        for i in items:
            cumulative += i['quantity']
            i['pct'] = round(i['quantity'] / grand_total * 100, 1) if grand_total else 0
            i['cum_pct'] = round(cumulative / grand_total * 100, 1) if grand_total else 0
        return {'ok': True, 'items': items, 'grand_total': grand_total, 'categories': DEFECT_CATEGORIES}
