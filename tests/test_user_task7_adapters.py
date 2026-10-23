import io
import os

import pytest
from werkzeug.datastructures import FileStorage

from modules.domain.errors import ValidationError
from modules.services.employee_document_storage import EmployeeDocumentStorage
from modules.services.user_import_adapter import UserImportWorkbookAdapter


def test_user_import_adapter_preserves_header_mapping_and_row_error_location():
    column_map = UserImportWorkbookAdapter.map_columns(
        ["username", "name", "unsupported_field"]
    )

    assert column_map == {0: "username", 1: "name"}
    assert UserImportWorkbookAdapter.row_data(
        (" worker ", "员工", "ignored"), column_map
    ) == {"username": "worker", "name": "员工"}
    assert UserImportWorkbookAdapter.normalize_identity(7, {}) == (
        None,
        None,
        "Row 7: empty username and name",
    )


def test_employee_document_storage_rejects_mismatched_content_before_install(tmp_path):
    upload_dir = tmp_path / "documents"

    with pytest.raises(ValidationError, match="内容与扩展名不一致"):
        EmployeeDocumentStorage.prepare_upload(
            17,
            FileStorage(stream=io.BytesIO(b"not a pdf"), filename="identity.pdf"),
            str(upload_dir),
            {".pdf"},
            1024,
        )

    assert not list(upload_dir.glob(".employee-upload-*"))


def test_employee_document_storage_stages_and_cleans_valid_content(tmp_path):
    upload_dir = tmp_path / "documents"
    prepared = EmployeeDocumentStorage.prepare_upload(
        17,
        FileStorage(
            stream=io.BytesIO(b"%PDF-1.7\ncertificate"),
            filename="identity.pdf",
        ),
        str(upload_dir),
        {".pdf"},
        1024,
    )

    assert prepared.original_name == "identity.pdf"
    assert prepared.file_size == len(b"%PDF-1.7\ncertificate")
    assert os.path.exists(prepared.temp_path)
    assert not os.path.exists(prepared.filepath)

    EmployeeDocumentStorage.install(prepared)
    assert os.path.exists(prepared.filepath)
    EmployeeDocumentStorage.remove_installed(prepared)
    EmployeeDocumentStorage.cleanup(prepared)
    assert not os.path.exists(prepared.filepath)
    assert not os.path.exists(prepared.temp_path)


def test_employee_document_storage_cleans_installed_file_when_permissions_fail(
    tmp_path, monkeypatch
):
    upload_dir = tmp_path / "documents"
    prepared = EmployeeDocumentStorage.prepare_upload(
        17,
        FileStorage(
            stream=io.BytesIO(b"%PDF-1.7\ncertificate"),
            filename="identity.pdf",
        ),
        str(upload_dir),
        {".pdf"},
        1024,
    )

    def fail_chmod(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(os, "chmod", fail_chmod)
    with pytest.raises(OSError, match="permission denied"):
        EmployeeDocumentStorage.install(prepared)

    EmployeeDocumentStorage.cleanup(prepared)
    assert not os.path.exists(prepared.filepath)
    assert not os.path.exists(prepared.temp_path)
