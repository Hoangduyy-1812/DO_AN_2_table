"""LD2450 report decoding and strict validation of the logger's NDJSON protocol."""
from __future__ import annotations

import re

MAX_LINE_BYTES = 4096
COUNTERS = (
    "uart_bytes", "frames_seen", "queue_drops", "bad_tails", "discarded_bytes",
    "uart_overflows", "uart_line_errors", "queue_depth", "free_heap",
)


def signed_magnitude(low: int, high: int) -> int:
    raw = low | high << 8
    magnitude = raw & 0x7FFF
    return magnitude if raw & 0x8000 else -magnitude


def decode_frame(raw_hex: str) -> list[dict]:
    if not isinstance(raw_hex, str) or not re.fullmatch(r"[0-9a-fA-F]{60}", raw_hex):
        raise ValueError("raw_hex must contain exactly 30 bytes / 60 hex characters")
    raw = bytes.fromhex(raw_hex)
    if raw[:4] != b"\xaa\xff\x03\x00" or raw[-2:] != b"\x55\xcc":
        raise ValueError("invalid LD2450 report header/tail")
    targets = []
    for slot in range(3):
        p = raw[4 + slot * 8:12 + slot * 8]
        targets.append({
            "active": int(any(p)),
            "x_mm": signed_magnitude(p[0], p[1]),
            "y_mm": signed_magnitude(p[2], p[3]),
            "speed_cms": signed_magnitude(p[4], p[5]),
            "resolution_mm": int.from_bytes(p[6:8], "little"),
        })
    return targets


def validate_record(record: object) -> dict:
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    if type(record.get("schema")) is not int or record["schema"] != 1:
        raise ValueError("unsupported schema")
    if record.get("type") not in ("frame", "status"):
        raise ValueError("unknown record type")
    for key, pattern in (("device_id", r"[0-9a-fA-F]{12,16}"), ("boot_id", r"[0-9a-fA-F]{8}")):
        if not isinstance(record.get(key), str) or not re.fullmatch(pattern, record[key]):
            raise ValueError(f"invalid {key}")
    for key in ("seq", "t_us", "sent_us", *COUNTERS):
        if type(record.get(key)) is not int or record[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if record["seq"] > 0xFFFFFFFF:
        raise ValueError("seq out of uint32 range")
    for key in ("last_frame_age_ms", "rssi_dbm"):
        if type(record.get(key)) is not int:
            raise ValueError(f"invalid {key}")
    if record["last_frame_age_ms"] < -1:
        raise ValueError("invalid last_frame_age_ms")
    if record["type"] == "frame":
        if record["seq"] < 1 or record["sent_us"] < record["t_us"]:
            raise ValueError("invalid frame sequence/time")
        decode_frame(record.get("raw_hex"))
    elif record["seq"] != 0:
        raise ValueError("status must use seq=0")
    return record

