"""qr-system — 返工管理 Service 层"""
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.services.quality_service import QualityService


class ReworkService:

    @staticmethod
    def list_rework(status='', search='', date_from='', date_to='', page=1, per_page=50,
                    worker_id=None, process_id=None):
        db = BaseService.db()
        where = ['1=1']
        params = []
        if status:
            where.append('rw.status = ?'); params.append(status)
        if search:
            where.append('(o.order_no LIKE ? OR p.name LIKE ? OR u.name LIKE ?)')
            params.extend([f'%{search}%'] * 3)
        if date_from:
            where.append('rw.created_at >= ?'); params.append(date_from)
        if date_to:
            where.append('rw.created_at <= ?'); params.append(date_to + ' 23:59:59')
        if worker_id:
            where.append('rw.user_id = ?'); params.append(worker_id)
        if process_id:
            where.append('rw.process_id = ?'); params.append(process_id)

        where_clause = ' AND '.join(where)
        total = db.execute(f'''SELECT COUNT(*) FROM rework_records rw
            JOIN orders o ON rw.order_id=o.id
            JOIN processes p ON rw.process_id=p.id
            LEFT JOIN users u ON rw.user_id=u.id
            WHERE {where_clause}''', params).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(f'''
            SELECT rw.*, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer_name,
                   p.name as process_name, u.name as worker_name,
                   cu.name as completed_by_name
            FROM rework_records rw
            JOIN orders o ON rw.order_id = o.id
            LEFT JOIN customers c ON o.customer_id = c.id
            JOIN processes p ON rw.process_id = p.id
            LEFT JOIN users u ON rw.user_id = u.id
            LEFT JOIN users cu ON rw.completed_by = cu.id
            WHERE {where_clause}
            ORDER BY rw.created_at DESC LIMIT ? OFFSET ?
        ''', params + [per_page, offset]).fetchall()
        return {'ok': True, 'items': [dict(r) for r in rows],
                'total': total, 'page': page, 'per_page': per_page}

    @staticmethod
    @staticmethod
    def create_rework(order_id, process_id, user_id, quantity, reason=''):
        db = BaseService.db()
        # Verify order and process exist
        order = db.execute('SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)).fetchone()
        if not order:
            raise ValueError('订单不存在或已删除')
        proc = db.execute('SELECT id, name FROM processes WHERE id = ?', (process_id,)).fetchone()
        if not proc:
            raise ValueError('工序不存在')

        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)',
                (order_id, process_id, user_id, quantity, reason)
            )
            rework_id = cur.lastrowid
            # Update order_processes rework counter
            txn.execute(
                'UPDATE order_processes SET rework = COALESCE(rework,0) + ? WHERE order_id = ? AND process_id = ?',
                (quantity, order_id, process_id)
            )
            # Sync orders.rework
            txn.execute(
                'UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?), updated_at = datetime("now","localtime") WHERE id = ?',
                (order_id, order_id)
            )
        return rework_id


    @staticmethod
    def get_stats():
        db = BaseService.db()
        today = datetime.now().strftime('%Y-%m-%d')
        # Week range (Mon-Sun)
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
        month_start = now.strftime('%Y-%m-01')

        row = db.execute('''
            SELECT
                COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) as pending_count,
                COALESCE(SUM(CASE WHEN status='pending' THEN quantity ELSE 0 END),0) as pending_qty,
                COALESCE(SUM(CASE WHEN DATE(created_at)=? THEN 1 ELSE 0 END),0) as today_count,
                COALESCE(SUM(CASE WHEN DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_qty,
                COALESCE(SUM(CASE WHEN DATE(completed_at)=? THEN 1 ELSE 0 END),0) as today_done,
                COALESCE(SUM(CASE WHEN DATE(completed_at)=? THEN quantity ELSE 0 END),0) as today_done_qty,
                COALESCE(SUM(CASE WHEN DATE(created_at)>=? THEN quantity ELSE 0 END),0) as week_rework_qty,
                COALESCE(SUM(CASE WHEN DATE(created_at)>=? THEN quantity ELSE 0 END),0) as month_rework_qty
            FROM rework_records
        ''', (today, today, today, today, week_start, month_start)).fetchone()

        # Week work records total
        week_work = db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE DATE(created_at)>=? AND type!='scrap'",
            (week_start,)
        ).fetchone()[0]
        month_work = db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE DATE(created_at)>=? AND type!='scrap'",
            (month_start,)
        ).fetchone()[0]

        week_rate = round(row['week_rework_qty'] / week_work * 100, 1) if week_work > 0 else 0
        month_rate = round(row['month_rework_qty'] / month_work * 100, 1) if month_work > 0 else 0

        return {'ok': True,
                'pending_count': row['pending_count'], 'pending_qty': row['pending_qty'],
                'today_count': row['today_count'], 'today_qty': row['today_qty'],
                'today_done': row['today_done'], 'today_done_qty': row['today_done_qty'],
                'week_rework_qty': row['week_rework_qty'], 'week_rate': week_rate,
                'month_rework_qty': row['month_rework_qty'], 'month_rate': month_rate}

    def update_rework(rework_id, reason):
        db = BaseService.db()
        rw = db.execute('SELECT * FROM rework_records WHERE id = ?', (rework_id,)).fetchone()
        if not rw:
            raise ValueError('记录不存在')
        with BaseService.transaction() as txn:
            txn.execute('UPDATE rework_records SET reason = ? WHERE id = ?', (reason, rework_id))

    @staticmethod
    def export_rework(status='', search='', date_from='', date_to='',
                      worker_id=None, process_id=None):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from io import BytesIO

        # Get all matching records (no pagination)
        result = ReworkService.list_rework(
            status=status, search=search, date_from=date_from, date_to=date_to,
            page=1, per_page=99999, worker_id=worker_id, process_id=process_id
        )
        items = result.get('items', [])

        wb = Workbook()
        ws = wb.active
        ws.title = '返工记录'

        headers = ['订单号', '产品', '客户', '工序', '工人', '数量', '原因', '状态', '结果', '创建时间', '完成时间', '耗时(h)']
        style_header(ws, headers)

        status_map = {'pending': '待处理', 'completed': '已完成'}
        result_map = {'ok': '合格', 'scrap': '报废', 'rework_again': '需再次返工'}

        for row_idx, item in enumerate(items, 2):
            vals = [
                item.get('order_no', ''),
                item.get('product_name', ''),
                item.get('customer_name', ''),
                item.get('process_name', ''),
                item.get('worker_name', ''),
                item.get('quantity', 0),
                item.get('reason', ''),
                status_map.get(item.get('status', ''), item.get('status', '')),
                result_map.get(item.get('result', ''), item.get('result', '')),
                item.get('created_at', '')[:19] if item.get('created_at') else '',
                item.get('completed_at', '')[:19] if item.get('completed_at') else '',
                item.get('duration_hours', 0),
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

    @staticmethod
    def complete_rework(rework_id, reason, user_id, result='', result_remark=''):
        db = BaseService.db()
        rw = db.execute('SELECT * FROM rework_records WHERE id = ?', (rework_id,)).fetchone()
        if not rw:
            raise ValueError('返工记录不存在')
        if rw['status'] == 'completed':
            raise ValueError('该记录已完成')

        with BaseService.transaction() as txn:
            reason_final = reason or rw['reason']
            # Calculate duration hours
            created = rw['created_at'] or ''
            duration = 0
            if created:
                try:
                    from datetime import datetime, timedelta as dt
                    created_dt = dt.strptime(created[:19], '%Y-%m-%d %H:%M:%S')
                    duration = round((dt.now() - created_dt).total_seconds() / 3600, 1)
                except:
                    pass
            txn.execute('''UPDATE rework_records SET status = 'completed', reason = ?,
                          completed_at = datetime("now","localtime"),
                          completed_by = ?, result = ?, result_remark = ?, duration_hours = ?
                          WHERE id = ?''', (reason_final, user_id, result, result_remark, duration, rework_id))
            txn.execute(
                'UPDATE order_processes SET rework = MAX(rework - ?, 0) '
                'WHERE order_id = ? AND process_id = ?',
                (rw['quantity'], rw['order_id'], rw['process_id']))
            txn.execute(
                'UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) '
                'FROM order_processes WHERE order_id = ?), '
                'updated_at = datetime("now","localtime") WHERE id = ?',
                (rw['order_id'], rw['order_id']))

        # P1: Auto-create quality re-check after rework complete
        try:
            QualityService.create_inspection({
                'order_id': rw['order_id'],
                'process_id': rw['process_id'],
                'inspection_type': 'rework_check',
                'quantity_checked': rw['quantity'],
                'quantity_passed': rw['quantity'] if result == 'ok' else 0,
                'quantity_failed': rw['quantity'] if result == 'scrap' else 0,
                'defect_category': '',
                'defect_quantity': 0,
                'notes': f'返工复检(返工ID:{rework_id}) - 结果:{result} {result_remark}'.strip(),
                'inspected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }, user_id)
        except Exception:
            pass  # Non-critical, don't block rework completion

    # ============ P3: Analytics ============

    @staticmethod
    def rework_trend(period='week', months=3):
        db = BaseService.db()
        if period == 'week':
            # Weekly trend: last N weeks
            rows = db.execute('''
                SELECT strftime('%Y-W%W', created_at) as week_label,
                       COUNT(*) as cnt, COALESCE(SUM(quantity),0) as qty
                FROM rework_records
                WHERE created_at >= date('now',?||' months')
                GROUP BY week_label ORDER BY week_label
            ''', (f'-{months}',)).fetchall()
            return [{'label': r['week_label'], 'count': r['cnt'], 'quantity': r['qty']} for r in rows]
        else:
            # Monthly trend
            rows = db.execute('''
                SELECT strftime('%Y-%m', created_at) as month_label,
                       COUNT(*) as cnt, COALESCE(SUM(quantity),0) as qty
                FROM rework_records
                WHERE created_at >= date('now',?||' months')
                GROUP BY month_label ORDER BY month_label
            ''', (f'-{months}',)).fetchall()
            return [{'label': r['month_label'], 'count': r['cnt'], 'quantity': r['qty']} for r in rows]

    @staticmethod
    def top_rework_processes(top_n=5):
        db = BaseService.db()
        rows = db.execute('''
            SELECT p.name as process_name, COUNT(*) as rework_count,
                   COALESCE(SUM(rw.quantity),0) as rework_qty
            FROM rework_records rw
            JOIN processes p ON rw.process_id = p.id
            GROUP BY rw.process_id
            ORDER BY rework_count DESC LIMIT ?
        ''', (top_n,)).fetchall()
        # Also get total work per process for rate
        total_work = db.execute('''
            SELECT p.name, COALESCE(SUM(wr.quantity),0) as total_qty
            FROM work_records wr
            JOIN processes p ON wr.process_id = p.id
            WHERE wr.type != 'scrap'
            GROUP BY wr.process_id
        ''').fetchall()
        work_map = {r['name']: r['total_qty'] for r in total_work}
        result = []
        for r in rows:
            total = work_map.get(r['process_name'], 0)
            rate = round(r['rework_qty'] / total * 100, 1) if total > 0 else 0
            result.append({
                'process_name': r['process_name'],
                'rework_count': r['rework_count'],
                'rework_qty': r['rework_qty'],
                'total_qty': total,
                'rate': rate
            })
        return result

    @staticmethod
    def worker_rework_stats():
        db = BaseService.db()
        rows = db.execute('''
            SELECT u.name as worker_name, u.id as worker_id,
                   COUNT(*) as rework_count,
                   COALESCE(SUM(rw.quantity),0) as rework_qty,
                   COUNT(DISTINCT rw.order_id) as affected_orders,
                   COALESCE(SUM(CASE WHEN rw.result='scrap' THEN rw.quantity ELSE 0 END),0) as scrap_qty,
                   ROUND(AVG(rw.duration_hours),1) as avg_duration
            FROM rework_records rw
            JOIN users u ON rw.user_id = u.id
            GROUP BY rw.user_id
            ORDER BY rework_count DESC
        ''').fetchall()
        # Get each worker's total work for rate
        total_work = db.execute('''
            SELECT u.name, COALESCE(SUM(wr.quantity),0) as total_qty
            FROM work_records wr
            JOIN users u ON wr.user_id = u.id
            WHERE wr.type != 'scrap'
            GROUP BY wr.user_id
        ''').fetchall()
        work_map = {r['name']: r['total_qty'] for r in total_work}
        result = []
        for r in rows:
            total = work_map.get(r['worker_name'], 0)
            rate = round(r['rework_qty'] / total * 100, 1) if total > 0 else 0
            result.append({
                'worker_name': r['worker_name'],
                'worker_id': r['worker_id'],
                'rework_count': r['rework_count'],
                'rework_qty': r['rework_qty'],
                'affected_orders': r['affected_orders'],
                'scrap_qty': r['scrap_qty'],
                'avg_duration': r['avg_duration'],
                'total_qty': total,
                'rate': rate,
            })
        return result

    @staticmethod
    def batch_complete(rework_ids, reason, user_id, result='ok', result_remark=''):
        db = BaseService.db()
        completed = []
        errors = []
        for rid in rework_ids:
            try:
                ReworkService.complete_rework(rid, reason, user_id, result, result_remark)
                completed.append(rid)
            except ValueError as e:
                errors.append({'id': rid, 'error': str(e)})
        return {'completed': len(completed), 'errors': errors}
