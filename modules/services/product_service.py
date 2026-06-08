"""
qr-system — 产品管理 Service 层

从 routes/products.py 提取全部业务逻辑。
路由层只负责 HTTP 解析和响应，业务逻辑集中在此。
"""
from datetime import datetime
from modules.services import BaseService
from modules.config import generate_product_code


# ============================================================
# XLSX 解析工具（模块级，零依赖 zipfile + xml）
# ============================================================
import zipfile
import xml.etree.ElementTree as ET


MAX_IMPORT_ROWS = 5000

def parse_xlsx(filepath):
    """Parse .xlsx file, return [{col_letter: cell_value}, ...]. Max {MAX_IMPORT_ROWS} rows."""
    rows = []
    with zipfile.ZipFile(filepath, 'r') as z:
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            ss_tree = ET.parse(z.open('xl/sharedStrings.xml'))
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in ss_tree.findall('.//s:si', ns):
                text = ''.join(t.text or '' for t in si.findall('.//s:t', ns))
                shared_strings.append(text)

        sheet = ET.parse(z.open('xl/worksheets/sheet1.xml'))
        for row_el in sheet.findall('.//s:row', ns):
            row_data = {}
            for cell in row_el.findall('s:c', ns):
                ref = cell.get('r')
                col_letter = ''.join(c for c in ref if c.isalpha())
                cell_type = cell.get('t')
                value_el = cell.find('s:v', ns)
                if value_el is None or value_el.text is None:
                    row_data[col_letter] = ''
                elif cell_type == 's':
                    idx = int(value_el.text)
                    row_data[col_letter] = shared_strings[idx] if idx < len(shared_strings) else ''
                else:
                    row_data[col_letter] = value_el.text
            if row_data:
                rows.append(row_data)
                if len(rows) >= MAX_IMPORT_ROWS:
                    break
    return rows


class ProductService:
    """产品管理业务逻辑。所有方法为静态方法，接受纯数据参数。"""

    # ============================================================
    # 查询 — 列表
    # ============================================================

    @staticmethod
    def list_products(keyword='', category='', page=1, limit=100):
        """
        产品列表（支持搜索、分类筛选、分页）。

        Returns:
            dict: {products: [...], total, page, limit}
        """
        db = BaseService.db()
        where = '1=1'
        params = []
        if keyword:
            where += ' AND (product_name LIKE ? OR model LIKE ? OR spec LIKE ?)'
            params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
        if category and category in ('结构件', '机加工'):
            where += ' AND category = ?'
            params.append(category)
        total = db.execute(
            f'SELECT COUNT(*) FROM products WHERE {where}', params
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(
            f'SELECT p.*,'
            f' COALESCE(pa.attachment_count, 0) as attachment_count,'
            f' pa_img.id as thumbnail_id'
            f' FROM products p'
            f' LEFT JOIN ('
            f'  SELECT product_id, COUNT(*) as attachment_count'
            f'  FROM product_attachments GROUP BY product_id'
            f' ) pa ON pa.product_id = p.id'
            f' LEFT JOIN ('
            f'  SELECT product_id, MIN(id) as id'
            f'  FROM product_attachments WHERE file_type LIKE "%image%"'
            f'  GROUP BY product_id'
            f' ) pa_img ON pa_img.product_id = p.id'
            f' WHERE {where} ORDER BY p.id DESC LIMIT ? OFFSET ?',
            params + [limit, offset]
        ).fetchall()
        return {'products': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit}

    # ============================================================
    # 查询 — 快速搜索（combobox 用）
    # ============================================================

    @staticmethod
    def search_products(q='', limit=20):
        """快速搜索产品，返回 id/product_name/product_code/category。"""
        db = BaseService.db()
        if q:
            rows = db.execute(
                "SELECT id, product_name, product_code, category FROM products "
                "WHERE product_name LIKE ? OR product_code LIKE ? "
                "ORDER BY product_code LIMIT ?",
                (f'%{q}%', f'%{q}%', limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, product_name, product_code, category FROM products "
                "ORDER BY product_code LIMIT ?",
                (limit,)
            ).fetchall()
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

        model = data.get('model', '').strip()
        spec = data.get('spec', '')
        upper = data.get('upper_opening', '')
        thickness = data.get('plate_thickness', '')
        style = data.get('style', '')
        product_code = generate_product_code(name, model, spec, upper, thickness, style)

        with BaseService.transaction() as db:
            existing = db.execute(
                'SELECT id FROM products WHERE product_code = ?', (product_code,)
            ).fetchone()
            if existing:
                raise ValueError(f'产品编码重复：{product_code}，已有产品 ID={existing["id"]}')

            cur = db.execute('''
                INSERT INTO products (product_name, model, product_code, spec, style,
                    upper_opening, plate_thickness, category, weight, price,
                    description, route_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                name,
                model,
                product_code,
                data.get('spec', ''),
                style,
                data.get('upper_opening', ''),
                data.get('plate_thickness', ''),
                data.get('category', '结构件').strip() or '结构件',
                float(data.get('weight') or 0),
                float(data.get('price') or 0),
                data.get('description', ''),
                data.get('route_id') or None
            ))
            return cur.lastrowid, product_code

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
        db = BaseService.db()
        prod = db.execute('SELECT id, product_name, IFNULL(model,"") as model, '
                          'IFNULL(spec,"") as spec, IFNULL(style,"") as style, '
                          'IFNULL(upper_opening,"") as upper_opening, '
                          'IFNULL(plate_thickness,"") as plate_thickness '
                          'FROM products WHERE id = ?', (pid,)).fetchone()
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
            new_code = generate_product_code(nm, md, sp, up, th, st)

        with BaseService.transaction() as txn:
            # 在事务内检查唯一性，消除 TOCTOU 竞态
            if new_code:
                dup = txn.execute(
                    'SELECT id FROM products WHERE product_code = ? AND id != ?',
                    (new_code, pid)
                ).fetchone()
                if dup:
                    raise ValueError(f'产品编码 {new_code} 已被其他产品使用，修改后会导致重复')

            txn.execute(
                f'UPDATE products SET {", ".join(sets)} WHERE id = ?',
                params + [pid]
            )

            # 如果关键字段变了，重新生成编码
            if new_code:
                txn.execute(
                    'UPDATE products SET product_code = ? WHERE id = ?',
                    (new_code, pid)
                )

        pc_row = db.execute(
            'SELECT product_code FROM products WHERE id = ?', (pid,)
        ).fetchone()
        return pc_row['product_code'] if pc_row else ''

    # ============================================================
    # 删除
    # ============================================================

    @staticmethod
    def delete_product(pid):
        """
        删除产品（检查订单引用，级联清理关联数据）。

        Raises:
            ValueError: 产品不存在或被订单使用
        """
        db = BaseService.db()
        prod = db.execute(
            'SELECT id, product_code FROM products WHERE id = ?', (pid,)
        ).fetchone()
        if not prod:
            raise ValueError('产品不存在')

        used = db.execute(
            'SELECT COUNT(*) FROM orders WHERE product_code = ?',
            (prod['product_code'],)
        ).fetchone()[0]
        if used > 0:
            raise ValueError(f'该产品已被 {used} 个订单使用，无法删除')

        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM product_attachments WHERE product_id = ?', (pid,))
            txn.execute('DELETE FROM process_prices WHERE product_id = ?', (pid,))
            txn.execute('DELETE FROM products WHERE id = ?', (pid,))

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
            rows = parse_xlsx(filepath)
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

        db = BaseService.db()
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

                model = product_data.get('model', '')
                spec = product_data.get('spec', '')
                upper = product_data.get('upper_opening', '')
                thickness = product_data.get('plate_thickness', '')
                style = product_data.get('style', '')
                product_code = generate_product_code(name, model, spec, upper, thickness, style)

                existing = txn.execute(
                    'SELECT id FROM products WHERE product_code = ?', (product_code,)
                ).fetchone()
                if existing:
                    skipped += 1
                    errors.append(f'第{i}行：{product_code}({name})已存在，跳过')
                    continue

                try:
                    txn.execute(
                        "INSERT INTO products (product_name, model, product_code, spec, style, "
                        "upper_opening, plate_thickness, category, weight, price, description) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (name, model, product_code, spec, style, upper, thickness,
                         product_data.get('category', '结构件') or '结构件',
                         float(product_data.get('weight') or 0),
                         float(product_data.get('price') or 0),
                         product_data.get('description', ''))
                    )
                    success += 1
                except Exception as e:
                    skipped += 1
                    errors.append(f'第{i}行：入库失败 - {e}')

        return {
            'success': success,
            'skipped': skipped,
            'errors': errors[:20],
            'message': f'导入完成：成功{success}条，跳过{skipped}条'
        }

    # ============================================================
    # 附件 — 列表
    # ============================================================

    @staticmethod
    def list_attachments(product_id):
        """获取产品附件列表（含上传者姓名）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT a.id, a.product_id, a.file_name, a.file_type, a.file_size,
                   a.created_at, u.name as uploaded_by_name
            FROM product_attachments a
            LEFT JOIN users u ON a.uploaded_by = u.id
            WHERE a.product_id = ?
            ORDER BY a.created_at DESC
        ''', (product_id,)).fetchall()
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
            db.execute('''
                INSERT INTO product_attachments
                    (product_id, file_name, file_type, file_size, file_data, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (product_id, file_name, file_type, len(file_data), file_data, uploaded_by))

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
        db = BaseService.db()
        return db.execute(
            'SELECT * FROM product_attachments WHERE id = ?', (attachment_id,)
        ).fetchone()

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
        db = BaseService.db()
        row = db.execute(
            'SELECT * FROM product_attachments WHERE id = ?', (attachment_id,)
        ).fetchone()
        if not row:
            raise ValueError('附件不存在')
        with BaseService.transaction() as txn:
            txn.execute(
                'DELETE FROM product_attachments WHERE id = ?', (attachment_id,)
            )
        return row
