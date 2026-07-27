"""qr-system - OrderAttachmentsService"""
import os
import tempfile
import uuid

from werkzeug.utils import secure_filename

from modules.config import ALLOWED_UPLOAD_EXTENSIONS
from modules.constants import MAX_ATTACHMENT_SIZE_KB
from modules.services import BaseService
from modules.repositories.order_attachments_repository import OrderAttachmentsRepository


class OrderAttachmentsService:
    @staticmethod
    def _normalize_file_name(file_name):
        display_name = str(file_name or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
        if not display_name:
            raise ValueError('请选择文件')

        extension = os.path.splitext(display_name)[1].lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f'不支持的附件类型：{extension or "无扩展名"}')

        safe_stem = secure_filename(os.path.splitext(display_name)[0]) or 'attachment'
        return display_name, f'{safe_stem}{extension}'

    @staticmethod
    def _write_temp_file(file_storage, upload_dir):
        os.makedirs(upload_dir, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(prefix='.upload-', suffix='.tmp', dir=upload_dir)
        file_size = 0
        max_size = MAX_ATTACHMENT_SIZE_KB * 1024
        try:
            with os.fdopen(descriptor, 'wb') as temp_file:
                while chunk := file_storage.stream.read(64 * 1024):
                    file_size += len(chunk)
                    if file_size > max_size:
                        raise ValueError(f'附件大小不能超过 {MAX_ATTACHMENT_SIZE_KB} KB')
                    temp_file.write(chunk)
                temp_file.flush()
                os.fsync(temp_file.fileno())
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
        return temp_path, file_size

    @staticmethod
    def list_attachments(order_id):
        rows = OrderAttachmentsRepository.list_by_order(order_id)
        return [dict(r) for r in rows]

    @staticmethod
    def upload_attachment(order_id, file_storage, uploaded_by, upload_dir):
        file_name, storage_name = OrderAttachmentsService._normalize_file_name(file_storage.filename)
        temp_path, file_size = OrderAttachmentsService._write_temp_file(file_storage, upload_dir)
        final_path = None
        try:
            with BaseService.transaction() as txn:
                aid = OrderAttachmentsRepository.insert_txn(
                    order_id,
                    file_name,
                    file_storage.content_type or 'application/octet-stream',
                    file_size,
                    uploaded_by,
                    db=txn,
                )
                final_path = os.path.join(upload_dir, f'{aid}_{storage_name}')
                os.replace(temp_path, final_path)
                OrderAttachmentsRepository.update_file_path_txn(aid, final_path, db=txn)
            return aid, file_size
        except Exception:
            for candidate in (temp_path, final_path):
                if candidate and os.path.exists(candidate):
                    os.remove(candidate)
            raise

    @staticmethod
    def get_attachment_meta(attachment_id):
        return OrderAttachmentsRepository.find_by_id(attachment_id)

    @staticmethod
    def get_attachment_file(attachment_id):
        row = OrderAttachmentsRepository.find_with_meta(attachment_id)
        if not row:
            raise ValueError("Attachment not found")
        return row

    @staticmethod
    def delete_attachment(attachment_id, upload_dir):
        row = OrderAttachmentsRepository.find_with_meta(attachment_id)
        if not row:
            raise ValueError('附件不存在')

        file_path = row['file_path'] or ''
        staged_path = None
        if file_path and os.path.exists(file_path):
            staged_path = os.path.join(upload_dir, f'.delete-{attachment_id}-{uuid.uuid4().hex}.tmp')
            try:
                os.replace(file_path, staged_path)
            except OSError as exc:
                raise OSError('附件文件暂时无法删除') from exc

        try:
            with BaseService.transaction() as txn:
                OrderAttachmentsRepository.delete_txn(attachment_id, db=txn)
        except Exception:
            if staged_path and os.path.exists(staged_path):
                os.replace(staged_path, file_path)
            raise

        if staged_path:
            try:
                os.remove(staged_path)
            except OSError as cleanup_error:
                try:
                    os.replace(staged_path, file_path)
                    with BaseService.transaction() as txn:
                        OrderAttachmentsRepository.restore_txn(row, db=txn)
                except Exception as restore_error:
                    raise OSError('附件删除后的存储补偿失败') from restore_error
                raise OSError('附件删除失败，已恢复原文件') from cleanup_error
        return row
