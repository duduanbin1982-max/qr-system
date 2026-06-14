"""
qr-system — 产品管理 Service 层

从 routes/products.py 提取全部业务逻辑。
路由层只负责 HTTP 解析和响应，业务逻辑集中在此。
"""
from datetime import datetime
from modules.services import BaseService
from modules.config import generate_product_code
from modules.repositories.product_repository import ProductRepository


# ============================================================
# XLSX 解析  openpyxl
import openpyxl

MAX_IMPORT_ROWS = 5000

class ProductService:
    """产品管理业务逻辑。所有方法为静态方法，接受纯数据参数。"""

    # ============================================================
    # 查询 — 列表
    # ============================================================

    @staticmethod
    def list_products(keyword='', category='', page=1, limit=100, deleted=False):
        """
        产品列表（支持搜索、分类筛选、分页）。

        Returns:
            dict: {products: [...], total, page, limit}
        """
        where = 'deleted_at IS NOT NULL' if deleted else 'deleted_at IS NULL'
        params = []
        if keyword:
            where += ' AND (product_name LIKE ? OR model LIKE ? OR spec LIKE ?)'
            params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
        if category and category in ('结构件', '机加工'):
            where += ' AND category = ?'
            params.append(category)
        rows, total = ProductRepository.list_with_attachments(where, params, page, limit)
        return {'products': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit}

    # ============================================================
    # 查询 — 快速搜索（combobox 用）
    # ============================================================

    @staticmethod
    def search_products(q='', limit=20):
        """快速搜索产品，返回 id/product_name/product_code/category。"""
        rows = ProductRepository.list_search(q, limit)
        return {'products': [dict(r) for r in rows]}

    # ============================================================
    # 创建
    # ============================================================

    @staticmethod
    def create_product(data):
        """
        创建产品。

        Args:
            data: dict with product_name, model, spec, style, upper_opening,
                  plate_thickness, category, weight, price, description, route_id

        Returns:
            tuple: (product_id, product_code)

        Raises:
            ValueError: 名称空或编码重复
        """
        name = data.get('product_name', '').strip()
        if not name:
            raise ValueError('产品名称不能为空')
        category = (data.get('category', '') or '').strip()
        if category and category not in ('结构件', '机加工'):
            raise ValueError(f'无效的产品分类: {category}，仅支持 结构件/机加工')

        model = data.get('model', '').strip()
        spec = data.get('spec', '')
        upper = data.get('upper_opening', '')
        thickness = data.get('plate_thickness', '')
        style = data.get('style', '')
        product_code = generate_product_code(name, model, spec, upper, thickness, style, lower_opening=data.get('lower_opening', ''), category=category)
        # Auto-generate model from product_code when not provided
        if not model:
            model = product_code

        with BaseService.transaction() as db:
            existing = ProductRepository.find_by_code(product_code, db=db)
            if existing:
                if existing['deleted_at']:
                    raise ValueError(f'产品编码重复：{product_code}，该产品已被删除，请先联系管理员恢复')
                raise ValueError(f'产品编码 {product_code} 已存在')

            insert_data = {
                'product_name': name,
                'model': model,
                'product_code': product_code,
                'spec': data.get('spec', ''),
                'style': style,
                'upper_opening': data.get('upper_opening', ''),
                'plate_thickness': data.get('plate_thickness', ''),
                'category': data.get('category', '结构件').strip() or '结构件',
                'weight': float(data.get('weight') or 0),
                'price': float(data.get('price') or 0),
                'description': data.get('description', ''),
                'route_id': data.get('route_id') or None
            }
            pid = ProductRepository.insert(insert_data, db=db)
            return pid, product_code

    # ============================================================
    # 更新
    # ============================================================

    @staticmethod
    def update_product(pid, data):
        """
        更新产品。

        Args:
            pid: 产品ID
            data: 要更新的字段 dict

        Returns:
            str: 更新后的 product_code

        Raises:
            ValueError: 产品不存在、无更新内容、编码重复
        """
        prod = ProductRepository.find_with_fields(pid)
        if not prod:
            raise ValueError('产品不存在')

        allowed = ['product_name', 'model', 'spec', 'style', 'upper_opening',
                   'plate_thickness', 'category', 'price', 'weight',
                   'description', 'route_id']
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])

        if not sets:
            raise ValueError('无更新内容')

        sets.append('updated_at = datetime("now","localtime")')

        # 检查编码是否会重复
        key_fields = {'product_name', 'model', 'spec', 'upper_opening',
                      'plate_thickness', 'style'}
        new_code = None
        if key_fields & set(data.keys()):
            nm = data.get('product_name', prod['product_name'])
            md = data.get('model', prod['model'])
            sp = data.get('spec', prod['spec'])
            up = data.get('upper_opening', prod['upper_opening'])
            th = data.get('plate_thickness', prod['plate_thickness'])
            st = data.get('style', prod['style'] or '')
            lo = data.get('lower_opening', prod.get('lower_opening', ''))
            cat = data.get('category', prod.get('category', '结构件'))
            new_code = generate_product_code(nm, md, sp, up, th, st, lower_opening=lo, category=cat)

        with BaseService.transaction() as txn:
            # 在事务内检查唯一性，消除 TOCTOU 竞态
            if new_code:
                dup = ProductRepository.find_by_code_exclude(new_code, pid, db=txn)
                if dup:
                    raise ValueError(f'产品编码 {new_code} 已被其他产品使用，修改后会导致重复')

            ProductRepository.update(pid, sets, params, db=txn)

            # 如果关键字段变了，重新生成编码
            if new_code:
                ProductRepository.update_product_code(pid, new_code, db=txn)

        return ProductRepository.get_product_code(pid)

    # ============================================================
    # 删除
    @staticmethod
    def check_product_impact(pid):
        db = BaseService.db()
        prod = db.execute(
            "SELECT id, product_name, product_code FROM products WHERE id = ? AND deleted_at IS NULL",
            (pid,)
        ).fetchone()
        if not prod:
            raise ValueError("Product not found")
        used = ProductRepository.count_by_product_code_in_orders(prod["product_code"])
        return {"product": dict(prod), "used_in_orders": used}

    # ============================================================    # ============================================================

    @staticmethod
    def delete_product(pid):
        """
        删除产品（检查订单引用，级联清理关联数据）。

        Raises:
            ValueError: 产品不存在或被订单使用
        """
        prod = ProductRepository.find_by_id(pid)
        if not prod:
            raise ValueError('产品不存在')

        used = ProductRepository.count_by_product_code_in_orders(prod['product_code'])
        if used > 0:
            raise ValueError(f'该产品已被 {used} 个订单使用，无法删除')

        with BaseService.transaction() as txn:
            ProductRepository.soft_delete(pid, db=txn)

    @staticmethod
    def restore_product(pid):
        prod = dict(ProductRepository.find_by_id(pid))
        if not prod:
            raise ValueError('产品不存在')
        if not prod.get('deleted_at'):
            raise ValueError('该产品未被删除，无需恢复')
        with BaseService.transaction() as txn:
            ProductRepository.restore(pid, db=txn)
        return prod['product_name']

    @staticmethod
    def purge_product(pid):
        prod = dict(ProductRepository.find_by_id(pid))
        if not prod:
            raise ValueError("product not found")
        if not prod.get("deleted_at"):
            raise ValueError("only soft-deleted products can be purged")
        used = ProductRepository.count_by_product_code_in_orders(prod["product_code"])
        if used > 0:
            raise ValueError("product referenced by " + str(used) + " orders, cannot purge")
        with BaseService.transaction() as txn:
            ProductRepository.hard_delete(pid, db=txn)
        return prod["product_name"]

    # ============================================================
    # Excel 批量导入
    # ============================================================

    @staticmethod
    def import_products(filepath):
        """
        从 .xlsx 文件批量导入产品。

        Args:
            filepath: 临时 xlsx 文件路径

        Returns:
            dict: {success, skipped, errors}

        Raises:
            ValueError: 文件解析失败或无数据
        """
        try:
            wb = openpyxl.load_workbook(filepath, read_only=True)
            ws = wb.active
            rows = []
            for row in ws.iter_rows(min_row=1, values_only=False):
                row_data = {}
                for cell in row:
                    if cell.value is not None:
                        col_letter = cell.column_letter
                        row_data[col_letter] = str(cell.value).strip() if cell.value else ''
                if row_data:
                    rows.append(row_data)
                    if len(rows) > MAX_IMPORT_ROWS:
                        break
            wb.close()
        except Exception as e:
            raise ValueError(f'文件解析失败: {e}')

        if not rows:
            raise ValueError('文件中没有数据')

        header = rows[0]
        field_aliases = {
            '产品名称': 'product_name', '名称': 'product_name',
            '型号': 'model',
            '规格': 'spec',
            '款式': 'style', '样式': 'style',
            '上开档': 'upper_opening', '上开档尺寸': 'upper_opening',
            '板厚': 'plate_thickness', '厚度': 'plate_thickness',
            '分类': 'category', '类别': 'category',
            '重量': 'weight', '重量(kg)': 'weight',
            '单价': 'price', '单价(元)': 'price',
            '描述': 'description', '备注': 'description', '说明': 'description',
        }

        col_map = {}
        for col_letter, cell_val in header.items():
            hdr = str(cell_val).strip()
            if hdr in field_aliases:
                col_map[col_letter] = field_aliases[hdr]

        if 'product_name' not in col_map.values():
            raise ValueError('表头需包含「产品名称」列')

        success = 0
        skipped = 0
        errors = []

        with BaseService.transaction() as txn:
            for i, row in enumerate(rows[1:], start=2):
                product_data = {}
                for col_letter, field in col_map.items():
                    val = row.get(col_letter, '')
                    product_data[field] = str(val).strip() if val else ''

                name = product_data.get('product_name', '')
                if not name:
                    skipped += 1
                    errors.append(f'第{i}行：产品名称为空，跳过')
                    continue

                model = product_data.get('model', '').strip()
                spec = product_data.get('spec', '')
                upper = product_data.get('upper_opening', '')
                thickness = product_data.get('plate_thickness', '')
                style = product_data.get('style', '')
                product_code = generate_product_code(name, model, spec, upper, thickness, style, lower_opening=product_data.get('lower_opening', ''), category=product_data.get('category', '结构件'))
                # Auto-generate model from product_code when not provided
                if not model:
                    model = product_code

                existing = ProductRepository.find_by_code(product_code, db=txn)
                if existing:
                    skipped += 1
                    if existing.get("deleted_at"):
                        errors.append(f'第{i}行：{product_code}({name})的编码与已删除产品重复，请先联系管理员恢复')
                    else:
                        errors.append(f'第{i}行：{product_code}({name})已存在，跳过')
                    continue

                try:
                    ProductRepository.insert({
                        'product_name': name,
                        'model': model,
                        'product_code': product_code,
                        'spec': spec,
                        'style': style,
                        'upper_opening': upper,
                        'lower_opening': product_data.get('lower_opening', ''),
                        'plate_thickness': thickness,
                        'category': product_data.get('category', '结构件') or '结构件',
                        'weight': float(product_data.get('weight') or 0),
                        'price': float(product_data.get('price') or 0),
                        'description': product_data.get('description', ''),
                    }, db=txn)
                    success += 1
                except Exception as e:
                    skipped += 1
                    errors.append(f'第{i}行：入库失败 - {e}')

        # Categorize errors for better diagnostics
        empty_name = sum(1 for e in errors if '产品名称为空' in e)
        duplicate = sum(1 for e in errors if '已存在' in e)
        db_error = len(errors) - empty_name - duplicate
        
        summary = f'空名称:{empty_name} 重复:{duplicate} 其他:{db_error}'
        # Include first 3 actual error details
        sample_errors = [e for e in errors if '入库失败' in e][:3]
        error_detail = ' | '.join(sample_errors) if sample_errors else ''
        return {
            'success': success,
            'skipped': skipped,
            'errors': errors,
            'error_summary': summary,
            'columns_found': list(col_map.values()),
            'message': f'导入完成：成功{success}条，跳过{skipped}条 | {summary}'
            + (f' | 详情: {error_detail}' if error_detail else '')
        }

    # ============================================================
    # 附件 — 列表
    # ============================================================

    @staticmethod
    def list_attachments(product_id):
        """获取产品附件列表（含上传者姓名）。"""
        rows = ProductRepository.list_attachments(product_id)
        return {'attachments': [dict(r) for r in rows]}

    # ============================================================
    # 附件 — 上传
    # ============================================================

    @staticmethod
    def upload_attachment(product_id, file_name, file_type, file_data, uploaded_by):
        """
        上传产品附件。

        Raises:
            ValueError: 文件大小超限
        """
        if len(file_data) > 10 * 1024 * 1024:
            raise ValueError('文件大小超过10MB限制')
        with BaseService.transaction() as db:
            ProductRepository.insert_attachment(
                product_id, file_name, file_type, len(file_data), file_data, uploaded_by,
                db=db
            )

    # ============================================================
    # 附件 — 获取文件数据
    # ============================================================

    @staticmethod
    def get_attachment(attachment_id):
        """
        获取附件记录。

        Returns:
            sqlite3.Row or None
        """
        return ProductRepository.find_attachment(attachment_id)

    # ============================================================
    # 附件 — 删除
    # ============================================================

    @staticmethod
    def delete_attachment(attachment_id):
        """
        删除附件。

        Returns:
            sqlite3.Row: 被删除的附件记录（用于审计）

        Raises:
            ValueError: 附件不存在
        """
        row = ProductRepository.find_attachment(attachment_id)
        if not row:
            raise ValueError('附件不存在')
        with BaseService.transaction() as txn:
            ProductRepository.delete_attachment(attachment_id, db=txn)
        return row
