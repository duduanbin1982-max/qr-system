"""Pure workbook parsing adapter for the user import boundary.

This module deliberately knows nothing about repositories, transactions, or user
permissions.  It only turns workbook rows into normalized import fields so the
service facade can keep ownership of business decisions.
"""

import openpyxl


USER_IMPORT_FIELDS = [
    "username", "name", "employee_no", "phone", "email", "nickname",
    "position_name", "role", "password", "process_names",
]
USER_IMPORT_FIELD_MAP = {field: field for field in USER_IMPORT_FIELDS}
USER_IMPORT_EN_MAP = {field.lower(): field for field in USER_IMPORT_FIELDS}


class UserImportWorkbookAdapter:
    """Parse and normalize user-import workbook content without side effects."""

    @staticmethod
    def open_workbook(filepath):
        workbook = openpyxl.load_workbook(filepath)
        return workbook, workbook.active

    @staticmethod
    def map_columns(headers):
        column_map = {}
        for index, header in enumerate(headers):
            if header is None:
                continue
            header_text = str(header).strip()
            if header_text in USER_IMPORT_FIELD_MAP:
                column_map[index] = USER_IMPORT_FIELD_MAP[header_text]
            elif header_text.lower() in USER_IMPORT_EN_MAP:
                column_map[index] = USER_IMPORT_EN_MAP[header_text.lower()]
        if not column_map:
            raise ValueError("No valid column headers found")
        return column_map

    @staticmethod
    def row_data(row, column_map):
        row_data = {}
        for column_index, field in column_map.items():
            value = row[column_index] if column_index < len(row) else None
            row_data[field] = str(value).strip() if value is not None else ""
        return row_data

    @staticmethod
    def normalize_identity(row_index, row_data):
        username = row_data.get("username", "")
        name = row_data.get("name", "")
        if not username and not name:
            return None, None, "Row " + str(row_index) + ": empty username and name"
        return username or name, name or username, None
