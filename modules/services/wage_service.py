"""qr-system — 工资计算 + 日报 + 生产进度 Service 层"""
import json
from modules.services import BaseService
from modules.repositories.wage_repository import WageRepository


class WageService:
    """计件工资 + 日报 + 生产进度。"""

    @staticmethod
    def calculate_wages(employee_id='', date_from='', date_to='', page=1, limit=200, include_pending=False, include_rework=False, hide_zero=False):
        status_filter = "wr.status = 'approved'" if not include_pending else "wr.status IN ('approved','pending')"
        type_filter = "wr.type IN ('normal','rework')" if include_rework else "wr.type = 'normal'"
        wr_where_parts = [status_filter, type_filter]
        wr_params = []
        if employee_id:
            wr_where_parts.append('wr.user_id = ?'); wr_params.append(employee_id)
        if date_from:
            wr_where_parts.append('wr.created_at >= ?'); wr_params.append(date_from)
        if date_to:
            wr_where_parts.append('wr.created_at <= ?'); wr_params.append(date_to + ' 23:59:59')
        wr_where = ' AND '.join(wr_where_parts)

        user_rows, total = WageRepository.get_worker_paged_by_role(employee_id, page=page, limit=limit)
        user_map = {row['id']: {'employee_name': row['name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'position_name': row['position_name'] or ''} for row in user_rows}
        user_ids = list(user_map.keys())
        if not user_ids:
            return {'wages': [], 'total': total, 'page': page, 'limit': limit}

        rows = WageRepository.get_wage_rows_for_workers(wr_where, wr_params, user_ids)
        wages = {}
        for uid, info in user_map.items():
            wages[uid] = {'employee_id': uid, 'employee_name': info['employee_name'], 'employee_no': info['employee_no'], 'position_name': info['position_name'], 'total_quantity': 0, 'total_wage': 0, 'details': []}
        for row in rows:
            emp_id = row['user_id']
            if row['wr_id'] is not None:
                qty = row['quantity'] or 0
                up = row['unit_price'] or 0
                wage = qty * up
                if emp_id not in wages:
                    wages[emp_id] = {'employee_id': emp_id, 'employee_name': row['employee_name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'position_name': '', 'total_quantity': 0, 'total_wage': 0, 'details': []}
                wages[emp_id]['total_quantity'] += qty
                wages[emp_id]['total_wage'] += wage
                wages[emp_id]['details'].append({'date': row['created_at'], 'order_no': row['order_no'] or '', 'product_name': row['product_name'] or '', 'product_code': row['order_product_code'] or '', 'process_name': row['process_name'], 'quantity': qty, 'unit_price': up, 'wage': wage})
        if hide_zero:
            wages = {uid: w for uid, w in wages.items() if w['total_quantity'] > 0}
            total = len(wages)
        return {'wages': list(wages.values()), 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def daily_report(date):
        """员工生产日报表（含工序工价和工资，仅统计已审批通过的正常报工）。"""
        rows = WageRepository.get_daily_report_rows(date)
        report = {}
        for row in rows:
            emp_id = row['user_id']
            if emp_id not in report:
                report[emp_id] = {'employee_name': row['employee_name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'processes': {}}
            pid = row['process_id']
            if pid not in report[emp_id]['processes']:
                report[emp_id]['processes'][pid] = {'process_name': row['process_name'], 'quantity': 0, 'unit_price': row['unit_price'] or 0}
            report[emp_id]['processes'][pid]['quantity'] += row['quantity'] or 0
        return {'date': date, 'report': list(report.values())}

    @staticmethod
    def production_progress(page=1, limit=50):
        total = WageRepository.count_active_orders()
        rows = WageRepository.get_production_orders(page, limit)
        result = []
        for o in rows:
            o = dict(o)
            processes = WageRepository.get_production_processes(o['id'])
            processes_list = []
            for pr in processes:
                total = pr['total_items'] or o['quantity'] or 1
                pd = pr['completed'] or 0
                ps = pr['scrapped'] or 0
                pp = min(100, int((pd + ps) / total * 100))
                processes_list.append({
                    'process_id': pr['process_id'], 'process_name': pr['process_name'],
                    'completed': pd, 'scrapped': ps, 'progress': pp,
                    'required_audit': pr['required_audit']
                })
            o['processes'] = processes_list
            result.append(o)
        return {'orders': result, 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def monthly_summary(year_month, page=1, limit=100):
        """月度工资汇总（按员工聚合）。"""
        rows, total_count, grand_total = WageRepository.get_monthly_summary(year_month, page, limit)
        return {
            'year_month': year_month,
            'summary': [dict(r) for r in rows],
            'grand_total_wage': round(grand_total['total_wage'] or 0, 2),
            'grand_total_quantity': grand_total['total_qty'] or 0,
            'total': total_count, 'page': page, 'limit': limit,
        }

    @staticmethod
    def process_wage_summary(year_month):
        """按工序维度的工资汇总（用于分析各工序工资支出）。"""
        rows = WageRepository.get_process_wage_summary(year_month)
        grand_total = sum(r['total_wage'] or 0 for r in rows)
        return {
            'year_month': year_month,
            'summary': [dict(r) for r in rows],
            'grand_total_wage': grand_total,
        }

    # -- P0: snapshots --
    @staticmethod
    def save_snapshot(year_month, employee_id=None):
        db = BaseService.db()
        result = WageService.calculate_wages(
            employee_id=str(employee_id) if employee_id else "",
            date_from=year_month + "-01", date_to="", page=1, limit=99999
        )
        saved = 0
        with BaseService.transaction() as txn:
            for emp in result.get("wages", []):
                WageRepository.upsert_snapshot(
                    emp, year_month, json.dumps(emp.get("details", []), ensure_ascii=False), txn
                )
                saved += 1
        return {"saved": saved, "year_month": year_month}

    @staticmethod
    def lock_snapshot(year_month, locked_by="system", notes=""):
        with BaseService.transaction() as txn:
            count = WageRepository.lock_snapshots(year_month, locked_by, notes, txn)
        return {"locked": count, "year_month": year_month, "notes": notes}

    @staticmethod
    def list_snapshots(year_month):
        rows = WageRepository.list_snapshots(year_month)
        return [dict(r) for r in rows]

    @staticmethod
    def confirm_snapshot(year_month, confirmed_by="system"):
        with BaseService.transaction() as txn:
            count = WageRepository.confirm_snapshots(year_month, confirmed_by, txn)
        return {"confirmed": count, "year_month": year_month, "confirmed_by": confirmed_by}

    @staticmethod
    def get_snapshot_status(year_month):
        rows = WageRepository.get_snapshot_status_rows(year_month)
        result = {"draft": 0, "locked": 0, "confirmed": 0, "total_wage": 0}
        for r in rows:
            result[r["status"]] = r["cnt"]
            result["total_wage"] += r["total_wage"] or 0
        result["total_employees"] = sum(v for k,v in result.items() if k != "total_wage")
        return result

    # -- P2-P3: adjustments, trends, positions, prediction --
    @staticmethod
    def list_adjustments(user_id=None, year_month=None):
        rows = WageRepository.list_adjustments(user_id, year_month)
        return [dict(r) for r in rows]

    @staticmethod
    def save_adjustment(user_id, year_month, adj_type, amount, reason, created_by):
        db = BaseService.db()
        existing = WageRepository.find_adjustment_id(user_id, year_month, adj_type, db)
        if existing:
            WageRepository.update_adjustment(existing["id"], amount, reason, created_by, db)
            adj_id = existing["id"]
        else:
            adj_id = WageRepository.insert_adjustment(
                user_id, year_month, adj_type, amount, reason, created_by, db
            )
        db.commit()
        return {"success": True, "id": adj_id}

    @staticmethod
    def delete_adjustment(adj_id):
        db = BaseService.db()
        deleted = WageRepository.delete_adjustment(adj_id, db)
        db.commit()
        return {"deleted": deleted}

    @staticmethod
    def get_adjustments_total(user_id, year_month):
        rows = WageRepository.get_adjustments_total_rows(user_id, year_month)
        result = {"bonus": 0, "deduction": 0, "allowance": 0, "net": 0}
        for r in rows:
            result[r["type"]] = r["total"] or 0
        result["net"] = result["bonus"] + result["allowance"] - result["deduction"]
        return result

    @staticmethod
    def wage_trends(months=12):
        rows = WageRepository.get_wage_trend_snapshots(months)
        if rows:
            result = []
            for r in reversed(rows):
                result.append({
                    "year_month": r["year_month"],
                    "total_wage": round(r["total_wage"] or 0, 2),
                    "total_quantity": r["total_quantity"] or 0,
                    "employee_count": r["employee_count"] or 0,
                })
            return result
        # Fallback: live data from work_records when no snapshots saved
        rows2 = WageRepository.get_live_wage_trends(months)
        result = []
        for r in rows2:
            result.append({
                "year_month": r["year_month"],
                "total_wage": round(r["total_wage"] or 0, 2),
                "total_quantity": r["total_quantity"] or 0,
                "employee_count": r["employee_count"] or 0,
            })
        return result

    @staticmethod
    def position_summary(year_month):
        rows = WageRepository.get_position_summary(year_month)
        grand_total = sum(r["total_wage"] or 0 for r in rows)
        return {"year_month": year_month, "summary": [dict(r) for r in rows], "grand_total_wage": grand_total}

    @staticmethod
    def wage_prediction(months=6):
        rows = WageRepository.get_wage_trend_snapshots(months)
        if len(rows) < 2:
            return {"predicted_wage": 0, "predicted_quantity": 0, "confidence": 0, "months_data": len(rows)}
        wages = [r["total_wage"] or 0 for r in reversed(rows)]
        n = len(wages)
        x_mean = (n - 1) / 2
        y_mean = sum(wages) / n
        denom = max(sum((i - x_mean)**2 for i in range(n)), 1)
        slope = sum((i - x_mean) * (wages[i] - y_mean) for i in range(n)) / denom
        predicted_wage = y_mean + slope * n
        ss_res = sum((wages[i] - (y_mean + slope * (i - x_mean)))**2 for i in range(n))
        ss_tot = sum((w - y_mean)**2 for w in wages)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        quantities = [r["total_quantity"] or 0 for r in reversed(rows)]
        predicted_quantity = round(sum(quantities) / n)
        return {
            "predicted_wage": round(max(0, predicted_wage), 2),
            "predicted_quantity": predicted_quantity,
            "confidence": round(min(100, max(0, r2 * 100))),
            "months_data": n, "trend": "up" if slope > 0 else "down" if slope < 0 else "stable",
            "avg_wage": round(y_mean, 2),
        }
