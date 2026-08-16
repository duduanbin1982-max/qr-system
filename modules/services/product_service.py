"""
qr-system — 产品管理 Service 层

从 routes/products.py 提取全部业务逻辑。
路由层只负责 HTTP 解析和响应，业务逻辑集中在此。
"""
from datetime import datetime
import math
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.config import generate_product_code
from modules.repositories.product_repository import ProductRepository
from modules.repositories.product_bom_repository import ProductBomRepository


# ============================================================
# XLSX 解析  openpyxl
import openpyxl

MAX_IMPORT_ROWS = 5000
PRODUCT_CATEGORIES = ("结构件", "机加工")
PRODUCT_STRING_FIELDS = (
    "product_name",
    "model",
    "spec",
    "style",
    "upper_opening",
    "lower_opening",
    "plate_thickness",
    "category",
    "description",
)
PRODUCT_IMPORT_FIELD_ALIASES = {
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

class ProductService:
    """产品管理业务逻辑。所有方法为静态方法，接受纯数据参数。"""

    @staticmethod
    def _optional_number(value, label):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label}必须是有效数字") from exc
        if not math.isfinite(number) or number < 0:
            raise ValidationError(f"{label}必须是大于或等于0的有限数字")
        return number

    @staticmethod
    def _optional_positive_id(value, label):
        if value in (None, ""):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label}无效") from exc
        if normalized <= 0:
            raise ValidationError(f"{label}无效")
        return normalized

    @staticmethod
    def normalize_product_payload(data, *, partial=False):
        if not isinstance(data, dict):
            raise ValidationError("产品参数必须是对象")
        normalized = {}
        for field in PRODUCT_STRING_FIELDS:
            if field in data:
                value = data.get(field)
                normalized[field] = str(value or "").strip()

        if not partial or "product_name" in normalized:
            name = normalized.get("product_name", "")
            if not name:
                raise ValidationError("产品名称不能为空")

        if not partial and "category" not in normalized:
            normalized["category"] = "结构件"
        if not partial and normalized.get("category") == "":
            normalized["category"] = "结构件"
        if "category" in normalized and normalized["category"] not in PRODUCT_CATEGORIES:
            raise ValidationError("产品分类仅支持结构件或机加工")

        for field, label in (("weight", "重量"), ("price", "价格")):
            if field in data:
                normalized[field] = ProductService._optional_number(data.get(field), label)
            elif not partial:
                normalized[field] = None

        legacy_route = data.get("route_id") if "route_id" in data else None
        route_root = data.get("process_route_id") if "process_route_id" in data else legacy_route
        if "route_id" in data and "process_route_id" in data:
            left = ProductService._optional_positive_id(legacy_route, "默认路线")
            right = ProductService._optional_positive_id(route_root, "默认路线")
            if left != right:
                raise ValidationError("route_id 与 process_route_id 不一致")
        if "route_id" in data or "process_route_id" in data or not partial:
            normalized["process_route_id"] = ProductService._optional_positive_id(
                route_root, "默认路线"
            )
        return normalized

    @staticmethod
    def _generated_code(data):
        return generate_product_code(
            data.get("product_name", ""),
            data.get("model", ""),
            data.get("spec", ""),
            data.get("upper_opening", ""),
            data.get("plate_thickness", ""),
            data.get("style", ""),
            lower_opening=data.get("lower_opening", ""),
            category=data.get("category", "结构件"),
        )

    @staticmethod
    def preview_product_code(data):
        normalized = ProductService.normalize_product_payload(data, partial=False)
        return ProductService._generated_code(normalized)

    @staticmethod
    def _ensure_code_alias(product_id, product_code, source, db):
        product_code = (product_code or '').strip()
        if not product_code:
            return
        existing = ProductRepository.find_code_alias(product_code, db=db)
        if existing:
            if existing['product_id'] != product_id:
                raise ConflictError(
                    f'产品编码 {product_code} 已是产品 {existing["product_id"]} 的历史编码'
                )
            return
        ProductRepository.insert_code_alias(
            product_id,
            product_code,
            source,
            db=db,
        )

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
        return {
            'products': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'limit': limit,
            'summary': ProductRepository.summary(deleted=deleted),
        }

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
        normalized = ProductService.normalize_product_payload(data, partial=False)
        name = normalized['product_name']
        model = normalized.get('model', '')
        product_code = ProductService._generated_code(normalized)
        # Auto-generate model from product_code when not provided
        if not model:
            model = product_code

        with BaseService.transaction() as db:
            if ProductRepository.find_by_code(product_code, db=db):
                raise ConflictError(f'产品编码 {product_code} 已存在')
            alias = ProductRepository.find_code_alias(product_code, db=db)
            if alias:
                raise ConflictError(
                    f'产品编码 {product_code} 已是产品 {alias["product_id"]} 的历史编码'
                )

            route_id = normalized.get('process_route_id')
            if route_id is not None and not ProductRepository.route_exists(route_id, db=db):
                raise NotFoundError('默认工艺路线不存在')
            insert_data = dict(normalized)
            insert_data.update({'model': model, 'product_code': product_code})
            pid = ProductRepository.insert(insert_data, db=db)
            ProductService._ensure_code_alias(pid, product_code, 'current', db)
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
        normalized = ProductService.normalize_product_payload(data, partial=True)
        allowed = ['product_name', 'model', 'spec', 'style', 'upper_opening',
                   'lower_opening', 'plate_thickness', 'category', 'price', 'weight',
                   'description']
        sets = []
        params = []
        for field in allowed:
            if field in normalized:
                sets.append(f'{field} = ?')
                params.append(normalized[field])

        if 'process_route_id' in normalized:
            sets.extend(['process_route_id = ?', 'route_id = ?'])
            params.extend([normalized['process_route_id'], normalized['process_route_id']])

        if not sets:
            raise ValueError('无更新内容')

        sets.append('updated_at = datetime("now","localtime")')

        with BaseService.transaction() as txn:
            prod = ProductRepository.find_with_fields(pid, db=txn)
            if not prod:
                raise NotFoundError('产品不存在')

            route_id = normalized.get('process_route_id')
            if route_id is not None and not ProductRepository.route_exists(route_id, db=txn):
                raise NotFoundError('默认工艺路线不存在')

            key_fields = {'product_name', 'model', 'spec', 'upper_opening',
                          'lower_opening', 'plate_thickness', 'style', 'category'}
            new_code = None
            if key_fields & set(normalized.keys()):
                merged = dict(prod)
                merged.update(normalized)
                new_code = ProductService._generated_code(merged)

            # 在事务内检查唯一性，消除 TOCTOU 竞态
            if new_code:
                dup = ProductRepository.find_by_code_exclude(new_code, pid, db=txn)
                if dup:
                    raise ConflictError(f'产品编码 {new_code} 已被其他产品使用，修改后会导致重复')
                alias = ProductRepository.find_code_alias(new_code, db=txn)
                if alias and alias['product_id'] != pid:
                    raise ConflictError(
                        f'产品编码 {new_code} 已是产品 {alias["product_id"]} 的历史编码'
                    )

            old_code = prod['product_code'] or ''
            ProductService._ensure_code_alias(pid, old_code, 'product_update', txn)

            ProductRepository.update(pid, sets, params, db=txn)

            # 如果关键字段变了，重新生成编码
            if new_code and new_code != old_code:
                ProductRepository.update_product_code(pid, new_code, db=txn)
            current_code = new_code or old_code
            ProductService._ensure_code_alias(pid, current_code, 'current', txn)
            ProductRepository.link_unresolved_orders(pid, db=txn)

        return current_code

    # ============================================================
    # 删除
    @staticmethod
    def check_product_impact(pid):
        prod = ProductRepository.find_active_identity(pid)
        if not prod:
            raise NotFoundError("Product not found")
        references = ProductRepository.reference_counts(pid)
        return {
            "product": dict(prod),
            "used_in_orders": references["orders"],
            "references": references,
            "can_purge": not any(references.values()),
        }

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
            raise NotFoundError('产品不存在')

        with BaseService.transaction() as txn:
            ProductRepository.soft_delete(pid, db=txn)

    @staticmethod
    def restore_product(pid):
        row = ProductRepository.find_by_id(pid)
        if not row:
            raise NotFoundError('产品不存在')
        prod = dict(row)
        if not prod.get('deleted_at'):
            raise ConflictError('该产品未被删除，无需恢复')
        with BaseService.transaction() as txn:
            ProductRepository.restore(pid, db=txn)
        return prod['product_name']

    @staticmethod
    def purge_product(pid):
        row = ProductRepository.find_by_id(pid)
        if not row:
            raise NotFoundError("product not found")
        prod = dict(row)
        if not prod.get("deleted_at"):
            raise ConflictError("only soft-deleted products can be purged")
        references = ProductRepository.reference_counts(pid)
        if any(references.values()):
            raise ConflictError("产品存在历史业务引用，只能保留软删除状态")
        with BaseService.transaction() as txn:
            ProductRepository.hard_delete(pid, db=txn)
        return prod["product_name"]

    # ============================================================
    # Excel 批量导入
    # ============================================================

    @staticmethod
    def _read_product_import_rows(filepath):
        try:
            wb = openpyxl.load_workbook(filepath, read_only=True)
            try:
                rows = []
                for row in wb.active.iter_rows(min_row=1, values_only=False):
                    row_data = {}
                    for cell in row:
                        if cell.value is not None:
                            row_data[cell.column_letter] = str(cell.value).strip() if cell.value else ''
                    if row_data:
                        rows.append(row_data)
                        if len(rows) > MAX_IMPORT_ROWS:
                            break
                return rows
            finally:
                wb.close()
        except Exception as e:
            raise ValueError(f'文件解析失败: {e}')

    @staticmethod
    def _map_product_import_columns(header):
        col_map = {}
        for col_letter, cell_val in header.items():
            hdr = str(cell_val).strip()
            if hdr in PRODUCT_IMPORT_FIELD_ALIASES:
                col_map[col_letter] = PRODUCT_IMPORT_FIELD_ALIASES[hdr]
        if 'product_name' not in col_map.values():
            raise ValueError('表头需包含「产品名称」列')
        return col_map

    @staticmethod
    def _product_import_row_data(row, col_map):
        product_data = {}
        for col_letter, field in col_map.items():
            val = row.get(col_letter, '')
            product_data[field] = str(val).strip() if val else ''
        return product_data

    @staticmethod
    def _product_import_payload(product_data):
        normalized = ProductService.normalize_product_payload(product_data, partial=False)
        product_code = ProductService._generated_code(normalized)
        normalized.update({
            'model': normalized.get('model') or product_code,
            'product_code': product_code,
        })
        return normalized

    @staticmethod
    def _import_product_row(row_index, row, col_map, txn):
        product_data = ProductService._product_import_row_data(row, col_map)
        return ProductService._import_product_data(row_index, product_data, txn)

    @staticmethod
    def _import_product_data(row_index, product_data, txn):
        name = product_data.get('product_name', '')
        if not name:
            return False, f'第{row_index}行：产品名称为空，跳过'

        try:
            payload = ProductService._product_import_payload(product_data)
        except ValueError as exc:
            return False, f'第{row_index}行：参数无效 - {exc}'
        product_code = payload['product_code']
        existing = ProductRepository.find_by_code(product_code, db=txn)
        if existing:
            if existing.get("deleted_at"):
                return False, f'第{row_index}行：{product_code}({name})的编码与已删除产品重复，请先联系管理员恢复'
            return False, f'第{row_index}行：{product_code}({name})已存在，跳过'
        alias = ProductRepository.find_code_alias(product_code, db=txn)
        if alias:
            return False, (
                f'第{row_index}行：{product_code}({name})是产品'
                f'{alias["product_id"]}的历史编码，跳过'
            )

        try:
            product_id = ProductRepository.insert(payload, db=txn)
            ProductService._ensure_code_alias(
                product_id,
                product_code,
                'current',
                txn,
            )
            return True, None
        except Exception as e:
            return False, f'第{row_index}行：入库失败 - {e}'

    @staticmethod
    def _product_import_result(success, skipped, errors, col_map):
        empty_name = sum(1 for e in errors if '产品名称为空' in e)
        duplicate = sum(1 for e in errors if '已存在' in e)
        db_error = len(errors) - empty_name - duplicate
        summary = f'空名称:{empty_name} 重复:{duplicate} 其他:{db_error}'
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

    @staticmethod
    def import_products(filepath):
        """Import products from an .xlsx file."""
        rows = ProductService._read_product_import_rows(filepath)
        if not rows:
            raise ValueError('文件中没有数据')

        col_map = ProductService._map_product_import_columns(rows[0])
        success = 0
        skipped = 0
        errors = []

        with BaseService.transaction() as txn:
            for row_index, row in enumerate(rows[1:], start=2):
                created, error = ProductService._import_product_row(row_index, row, col_map, txn)
                if created:
                    success += 1
                else:
                    skipped += 1
                    errors.append(error)

        return ProductService._product_import_result(success, skipped, errors, col_map)

    @staticmethod
    def import_product_rows(rows):
        """Compatibility importer using the same product policy as XLSX imports."""
        if not isinstance(rows, list) or not rows:
            raise ValidationError('没有可导入的产品数据')
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValidationError(f'单次最多导入{MAX_IMPORT_ROWS}条产品')

        success = 0
        skipped = 0
        errors = []
        columns = set()
        with BaseService.transaction() as txn:
            for row_index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    created, error = False, f'第{row_index}行：数据必须是对象'
                else:
                    columns.update(row.keys())
                    created, error = ProductService._import_product_data(
                        row_index, row, txn
                    )
                if created:
                    success += 1
                else:
                    skipped += 1
                    errors.append(error)
        result = ProductService._product_import_result(
            success,
            skipped,
            errors,
            {str(index): column for index, column in enumerate(sorted(columns))},
        )
        result['imported'] = result['success']
        return result

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
            if not ProductRepository.find_active_identity(product_id, db=db):
                raise NotFoundError('产品不存在或已停用')
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
            raise NotFoundError('附件不存在')
        with BaseService.transaction() as txn:
            ProductRepository.delete_attachment(attachment_id, db=txn)
        return row

    # ============================================================
    # Product BOM
    # ============================================================
    @staticmethod
    def list_product_bom(product_id):
        return [dict(row) for row in ProductBomRepository.list_by_product(product_id)]

    @staticmethod
    def add_product_bom(product_id, data):
        material_id = ProductService._optional_positive_id(data.get('material_id'), '物料 ID')
        quantity = data.get('quantity_per_unit', data.get('quantity', 1))
        process_id = ProductService._optional_positive_id(data.get('process_id'), '工序 ID')
        if not material_id:
            raise ValidationError('物料 ID 不能为空')
        try:
            quantity = float(quantity)
        except (TypeError, ValueError) as exc:
            raise ValidationError('单位用量必须是有效数字') from exc
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValidationError('单位用量必须是大于0的有限数字')
        with BaseService.transaction() as txn:
            if not ProductBomRepository.product_exists(product_id, db=txn):
                raise NotFoundError('产品不存在')
            if not ProductBomRepository.material_exists(material_id, db=txn):
                raise NotFoundError('物料不存在')
            if process_id is not None and not ProductBomRepository.process_exists(process_id, db=txn):
                raise NotFoundError('工序不存在或已停用')
            new_id = ProductBomRepository.insert_unique(
                product_id, material_id, quantity, process_id, db=txn
            )
            if new_id is None:
                raise ConflictError('该物料已存在于产品配方中')
            row = ProductBomRepository.find_by_id(new_id, db=txn)
            return dict(row)

    @staticmethod
    def delete_product_bom(product_id, bom_id):
        with BaseService.transaction() as txn:
            if not ProductBomRepository.find_by_id_and_product(bom_id, product_id, db=txn):
                raise NotFoundError('产品物料配方记录不存在')
            ProductBomRepository.delete(bom_id, db=txn)
