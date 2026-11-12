"""Small CSV safety helpers shared by HTTP and service exports."""

import re


_SPREADSHEET_FORMULA_PREFIX = re.compile(r"^[\t\r]|^[\t\r\n ]*[=+\-@]")


def safe_csv_cell(value):
    """Neutralize spreadsheet formulas while preserving real numeric values."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    if _SPREADSHEET_FORMULA_PREFIX.match(text):
        return "'" + text
    return text
