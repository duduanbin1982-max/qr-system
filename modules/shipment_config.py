"""Shipment numbering settings and validation."""


SHIPMENT_NO_PREFIX_KEY = "shipment_no_prefix"
DEFAULT_SHIPMENT_NO_PREFIX = "SH"
MAX_SHIPMENT_NO_PREFIX_LENGTH = 12


def normalize_shipment_no_prefix(value):
    prefix = str(value or "").strip().upper()
    if not prefix:
        return DEFAULT_SHIPMENT_NO_PREFIX
    if len(prefix) > MAX_SHIPMENT_NO_PREFIX_LENGTH:
        raise ValueError("出库单号前缀不能超过 12 个字符")
    if not all(character.isalnum() or character in "-_" for character in prefix):
        raise ValueError("出库单号前缀只能包含字母、数字、短横线和下划线")
    return prefix
