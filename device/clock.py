# Real-world time for the clip, learned from the "Date" header of the API's HTTPS replies
# (cloud_sync.py calls set_from_http_date on every check-in). No NTP library needed.
#
# The clip has no battery-backed clock, so after a restart the time is unknown until the first
# successful check-in. now() returns None until then. Times are whole Unix seconds (ints):
# CircuitPython floats are too coarse to hold today's Unix time precisely.
import time

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_offset = None  # Unix seconds minus monotonic seconds


def _monotonic_seconds():
    return time.monotonic_ns() // 1_000_000_000


def set_from_http_date(value):
    """Set the clock from an HTTP date like 'Sun, 22 Nov 2026 23:54:51 GMT'.

    Returns True the first time the clock becomes known. Bad values are ignored.
    """
    global _offset
    try:
        _, day, month, year, hms = value.split()[:5]
        hour, minute, second = (int(part) for part in hms.split(":"))
        unix = time.mktime((int(year), _MONTHS.index(month) + 1, int(day), hour, minute, second, 0, -1, -1))
    except (AttributeError, ValueError, OverflowError):
        return False
    first = _offset is None
    _offset = unix - _monotonic_seconds()
    if first:
        print("Clock: set from server, Unix time", unix)
    return first


def now():
    """Current Unix time in whole seconds, or None if not known yet."""
    return None if _offset is None else _offset + _monotonic_seconds()
