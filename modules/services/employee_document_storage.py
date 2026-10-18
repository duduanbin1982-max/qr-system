"""Filesystem adapter for employee document validation and staging.

The adapter owns filename/content checks and filesystem compensation primitives.
Database writes, audit writes, and transaction boundaries remain in
``UserService`` so existing atomicity and audit behavior stay unchanged.
"""

from dataclasses import dataclass
import os
import tempfile
import uuid
import zipfile

from modules.domain.errors import ConflictError, ValidationError


@dataclass(frozen=True)
class PreparedEmployeeDocument:
    original_name: str
    extension: str
    stored_name: str
    filepath: str
    temp_path: str
    file_size: int


class EmployeeDocumentStorage:
    """Pure filesystem boundary used by the user service facade."""

    @staticmethod
    def validate_name(filename, allowed_extensions):
        normalized = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not normalized or len(normalized) > 255 or "\x00" in normalized:
            raise ValidationError("附件文件名无效")
        extension = os.path.splitext(normalized)[1].lower()
        if extension not in allowed_extensions:
            raise ValidationError("附件类型不支持")
        return normalized, extension

    @staticmethod
    def validate_content(filepath, extension, header):
        if extension == ".pdf" and not header.startswith(b"%PDF-"):
            raise ValidationError("PDF 文件内容与扩展名不一致")
        if extension in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
            raise ValidationError("JPEG 文件内容与扩展名不一致")
        if extension == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError("PNG 文件内容与扩展名不一致")
        if extension in {".doc", ".xls"} and not header.startswith(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        ):
            raise ValidationError("Office 文件内容与扩展名不一致")
        if extension in {".docx", ".xlsx"}:
            try:
                with zipfile.ZipFile(filepath) as archive:
                    names = archive.namelist()
            except (OSError, zipfile.BadZipFile) as exc:
                raise ValidationError("Office 文件内容与扩展名不一致") from exc
            required_prefix = "word/" if extension == ".docx" else "xl/"
            if not any(name.startswith(required_prefix) for name in names):
                raise ValidationError("Office 文件内容与扩展名不一致")

    @staticmethod
    def path(upload_dir, stored_name):
        base = os.path.realpath(upload_dir)
        filepath = os.path.realpath(os.path.join(base, stored_name))
        if os.path.commonpath([base, filepath]) != base:
            raise ConflictError("附件存储路径无效")
        return filepath

    @classmethod
    def existing_path(cls, upload_dir, stored_name, legacy_upload_dir=None):
        filepath = cls.path(upload_dir, stored_name)
        if os.path.exists(filepath) or not legacy_upload_dir:
            return filepath
        legacy_path = cls.path(legacy_upload_dir, stored_name)
        return legacy_path if os.path.exists(legacy_path) else filepath

    @classmethod
    def prepare_upload(
        cls,
        uid,
        file_storage,
        upload_dir,
        allowed_extensions,
        max_bytes,
    ):
        original_name, extension = cls.validate_name(
            file_storage.filename, allowed_extensions
        )
        os.makedirs(upload_dir, mode=0o700, exist_ok=True)
        stored_name = str(uid) + "_" + uuid.uuid4().hex + extension
        filepath = cls.path(upload_dir, stored_name)
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".employee-upload-", dir=upload_dir
        )
        file_size = 0
        header = b""
        try:
            with os.fdopen(descriptor, "wb") as target:
                descriptor = None
                while True:
                    chunk = file_storage.stream.read(64 * 1024)
                    if not chunk:
                        break
                    if not header:
                        header = chunk[:16]
                    file_size += len(chunk)
                    if file_size > max_bytes:
                        raise ValidationError("员工附件最大允许 20MB")
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if file_size == 0:
                raise ValidationError("附件内容不能为空")
            cls.validate_content(temp_path, extension, header)
            return PreparedEmployeeDocument(
                original_name=original_name,
                extension=extension,
                stored_name=stored_name,
                filepath=filepath,
                temp_path=temp_path,
                file_size=file_size,
            )
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    @staticmethod
    def install(prepared):
        os.replace(prepared.temp_path, prepared.filepath)
        try:
            os.chmod(prepared.filepath, 0o600)
        except Exception:
            if os.path.exists(prepared.filepath):
                os.remove(prepared.filepath)
            raise

    @staticmethod
    def cleanup(prepared):
        if prepared and os.path.exists(prepared.temp_path):
            os.remove(prepared.temp_path)

    @staticmethod
    def remove_installed(prepared):
        if prepared and os.path.exists(prepared.filepath):
            os.remove(prepared.filepath)

    @staticmethod
    def ensure_quarantine_dir(upload_dir):
        os.makedirs(upload_dir, mode=0o700, exist_ok=True)
        quarantine_dir = os.path.join(upload_dir, ".quarantine")
        os.makedirs(quarantine_dir, mode=0o700, exist_ok=True)
        return quarantine_dir

    @staticmethod
    def quarantine(filepath, quarantine_dir):
        if not os.path.exists(filepath):
            return None
        quarantine_path = os.path.join(quarantine_dir, uuid.uuid4().hex + ".deleted")
        os.replace(filepath, quarantine_path)
        return quarantine_path

    @staticmethod
    def restore_quarantine(quarantine_path, filepath):
        if quarantine_path and os.path.exists(quarantine_path) and filepath:
            os.replace(quarantine_path, filepath)

    @staticmethod
    def discard_quarantine(quarantine_path):
        if quarantine_path and os.path.exists(quarantine_path):
            os.remove(quarantine_path)
