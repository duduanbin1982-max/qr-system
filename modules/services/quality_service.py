"""qr-system — 质量检验 Service 层"""
from datetime import datetime
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause


INSPECTION_TYPES = {'first_article': '首件检验', 'in_process': '过程检验', 'final': '终检', 'rework_check': '返工复检'}
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

        base_sql = f'''
            SELECT qi.*, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer_name,
                   p.name as process_name, u.name as inspector_name
            FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id
            LEFT JOIN customers c ON o.customer_id = c.id
            JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            WHERE {where_clause}
            {build_sort_clause("qi.inspected_at", {"qi.inspected_at": "qi.inspected_at"}, default="qi.inspected_at")}
        '''
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=per_page)
        rows = db.execute(paginated_sql, all_params).fetchall()
        return {'ok': True, 'items': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': size}

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

    # Predefined inspection templates
    INSPECTION_TEMPLATES = {
        'standard_first': {
            'name': '标准首件检验',
            'inspection_type': 'first_article',
            'check_items': ['尺寸检查', '外观检查', '材质确认'],
            'defect_categories': ['尺寸超差', '外观缺陷', '材质问题'],
        },
        'welding': {
            'name': '焊接专项检验',
            'inspection_type': 'in_process',
            'check_items': ['焊缝外观', '焊缝尺寸', '渗透检测'],
            'defect_categories': ['焊接缺陷', '外观缺陷', '尺寸超差'],
        },
        'final_check': {
            'name': '成品终检',
            'inspection_type': 'final',
            'check_items': ['外观总检', '尺寸复核', '包装检查'],
            'defect_categories': ['外观缺陷', '尺寸超差', '装配不良', '其他'],
        },
        'rework_recheck': {
            'name': '返工后复检',
            'inspection_type': 'rework_check',
            'check_items': ['返工部位检查', '关联尺寸复核'],
            'defect_categories': ['焊接缺陷', '尺寸超差', '外观缺陷'],
        },
    }

    @staticmethod
    def get_templates():
        return [{'code': k, 'name': v['name'], 'inspection_type': v['inspection_type'],
                 'check_items': v['check_items'], 'defect_categories': v['defect_categories']}
                for k, v in QualityService.INSPECTION_TEMPLATES.items()]

    @staticmethod
    def batch_create_inspections(items, user_id):
        db = BaseService.db()
        created = []
        errors = []
        for idx, item in enumerate(items):
            try:
                # Validate
                if not item.get('order_id') or not item.get('process_id'):
                    errors.append({'index': idx, 'error': '订单和工序必填'})
                    continue
                QualityService.check_order_exists(item['order_id'])
                iid = QualityService.create_inspection(item, user_id)
                created.append(iid)
            except ValueError as e:
                errors.append({'index': idx, 'error': str(e)})
        return {'created': len(created), 'ids': created, 'errors': errors}

    @staticmethod
    def spc_p_chart(order_id=None, process_id=None, limit=20):
        db = BaseService.db()
        where = ['1=1']
        params = []
        if order_id:
            where.append('qi.order_id = ?'); params.append(order_id)
        if process_id:
            where.append('qi.process_id = ?'); params.append(process_id)
        rows = db.execute(f'''
            SELECT qi.id, qi.order_id, qi.process_id, qi.quantity_checked,
                   qi.quantity_failed, qi.inspected_at, o.order_no
            FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id
            WHERE {" AND ".join(where)}
            ORDER BY qi.inspected_at DESC LIMIT ?
        ''', params + [limit]).fetchall()

        samples = []
        for r in reversed(rows):
            qc = r['quantity_checked'] or 0
            qf = r['quantity_failed'] or 0
            rate = round(qf / qc * 100, 1) if qc > 0 else 0
            samples.append({
                'label': (r['inspected_at'] or '')[:10],
                'order_no': r['order_no'],
                'checked': qc, 'failed': qf, 'rate': rate,
            })

        if samples:
            total_checked = sum(s['checked'] for s in samples)
            total_failed = sum(s['failed'] for s in samples)
            p_bar = total_failed / total_checked if total_checked > 0 else 0
            n_bar = total_checked / len(samples) if samples else 1
            import math
            sigma = math.sqrt(p_bar * (1 - p_bar) / n_bar) if n_bar > 0 else 0
            ucl = round(min(p_bar + 3 * sigma, 1) * 100, 1)
            cl = round(p_bar * 100, 1)
            lcl = round(max(p_bar - 3 * sigma, 0) * 100, 1)
        else:
            ucl, cl, lcl = 0, 0, 0

        return {'ok': True, 'samples': samples, 'ucl': ucl, 'cl': cl, 'lcl': lcl,
                'total_checked': total_checked if samples else 0,
                'total_failed': total_failed if samples else 0}

    @staticmethod
    def inspector_performance():
        db = BaseService.db()
        rows = db.execute('''
            SELECT u.id, u.name,
                   COUNT(*) as inspection_count,
                   COALESCE(SUM(qi.quantity_checked),0) as total_checked,
                   COALESCE(SUM(qi.quantity_failed),0) as total_failed,
                   COUNT(DISTINCT qi.order_id) as orders_covered,
                   ROUND(AVG(CASE WHEN qi.quantity_checked>0 THEN qi.quantity_failed*100.0/qi.quantity_checked ELSE 0 END),1) as avg_defect_rate
            FROM quality_inspections qi
            JOIN users u ON qi.inspector_id = u.id
            GROUP BY qi.inspector_id
            ORDER BY inspection_count DESC
        ''').fetchall()
        result = []
        for r in rows:
            total = r['total_checked'] or 0
            failed = r['total_failed'] or 0
            rate = round(failed / total * 100, 1) if total > 0 else 0
            result.append({
                'inspector_id': r['id'], 'inspector_name': r['name'],
                'inspection_count': r['inspection_count'],
                'total_checked': total, 'total_failed': failed,
                'overall_defect_rate': rate,
                'avg_defect_rate': r['avg_defect_rate'] or 0,
                'orders_covered': r['orders_covered'],
            })
        return {'ok': True, 'data': result}

    @staticmethod
    def supplier_quality():
        db = BaseService.db()
        rows = db.execute('''
            SELECT c.id as customer_id, c.name as customer_name,
                   COUNT(*) as inspection_count,
                   COALESCE(SUM(qi.quantity_checked),0) as total_checked,
                   COALESCE(SUM(qi.quantity_failed),0) as total_failed,
                   COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count,
                   COALESCE(SUM(CASE WHEN qi.result IN ('fail','partial') THEN 1 ELSE 0 END),0) as fail_count
            FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id
            JOIN customers c ON o.customer_id = c.id
            WHERE c.id IS NOT NULL
            GROUP BY c.id
            ORDER BY inspection_count DESC
        ''').fetchall()
        result = []
        for r in rows:
            total = r['total_checked'] or 0
            failed = r['total_failed'] or 0
            rate = round(failed / total * 100, 1) if total > 0 else 0
            pass_rate = round(r['pass_count'] / r['inspection_count'] * 100, 1) if r['inspection_count'] > 0 else 0
            result.append({
                'customer_id': r['customer_id'],
                'customer_name': r['customer_name'],
                'inspection_count': r['inspection_count'],
                'total_checked': total, 'total_failed': failed,
                'defect_rate': rate, 'pass_rate': pass_rate,
                'pass_count': r['pass_count'], 'fail_count': r['fail_count'],
            })
        return {'ok': True, 'data': result}

    @staticmethod
    def pass_rate_trend(weeks=6):
        db = BaseService.db()
        rows = db.execute('''
            SELECT strftime('%Y-W%W', inspected_at) as week,
                   COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) as pass_count
            FROM quality_inspections
            WHERE inspected_at >= date('now', ?||' days')
            GROUP BY week ORDER BY week
        ''', (f'-{weeks*7}',)).fetchall()
        result = []
        for r in rows:
            rate = round(r['pass_count'] / r['total'] * 100, 1) if r['total'] > 0 else 0
            result.append({'label': r['week'], 'total': r['total'], 'pass': r['pass_count'], 'rate': rate})
        return result

    @staticmethod
    def export_inspections(order_id=None, process_id=None, inspection_type='',
                           result='', search='', date_from='', date_to=''):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from io import BytesIO

        result_data = QualityService.list_inspections(
            order_id=order_id, process_id=process_id,
            inspection_type=inspection_type, result=result, search=search,
            date_from=date_from, date_to=date_to, page=1, per_page=99999
        )
        items = result_data.get('items', [])

        wb = Workbook()
        ws = wb.active
        ws.title = '质检记录'

        headers = ['订单号', '产品', '客户', '工序', '检验类型', '检验员',
                   '检验数', '合格数', '不合格数', '结果', '缺陷类别', '缺陷数', '备注', '检验时间']
        style_header(ws, headers)

        type_map = {'first_article': '首件检验', 'in_process': '过程检验', 'final': '终检', 'rework_check': '返工复检'}
        result_map = {'pass': '合格', 'fail': '不合格', 'partial': '部分合格'}

        for row_idx, item in enumerate(items, 2):
            vals = [
                item.get('order_no', ''),
                item.get('product_name', ''),
                item.get('customer_name', ''),
                item.get('process_name', ''),
                type_map.get(item.get('inspection_type', ''), item.get('inspection_type', '')),
                item.get('inspector_name', ''),
                item.get('quantity_checked', 0),
                item.get('quantity_passed', 0),
                item.get('quantity_failed', 0),
                result_map.get(item.get('result', ''), item.get('result', '')),
                item.get('defect_category', ''),
                item.get('defect_quantity', 0),
                item.get('notes', ''),
                item.get('inspected_at', '')[:19] if item.get('inspected_at') else '',
            ]
            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN

        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output
