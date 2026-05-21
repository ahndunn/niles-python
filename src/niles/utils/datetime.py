"""Date/time utilities with UTC offset support."""

import re
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone

_OFFSET_RE = re.compile(r"^UTC([+-])(\d{1,2})(?::(\d{2}))?$", re.IGNORECASE)

_MAX_OFFSET_HOURS = 14
_MAX_OFFSET_MINUTES = 59

_LOCALE_TO_OFFSET: dict[str, str] = {
    "ja": "UTC+09",
    "ko": "UTC+09",
    "zh-CN": "UTC+08",
    "zh-TW": "UTC+08",
    "de": "UTC+01",
    "fr": "UTC+01",
    "es-ES": "UTC+01",
    "it": "UTC+01",
    "pt-BR": "UTC-03",
    "ru": "UTC+03",
    "nl": "UTC+01",
    "pl": "UTC+01",
    "tr": "UTC+03",
    "da": "UTC+01",
    "fi": "UTC+02",
    "nb-NO": "UTC+01",
    "sv-SE": "UTC+01",
    "cs": "UTC+01",
    "hu": "UTC+01",
    "ro": "UTC+02",
    "uk": "UTC+02",
    "bg": "UTC+02",
    "el": "UTC+02",
    "th": "UTC+07",
    "vi": "UTC+07",
    "id": "UTC+07",
    "ms": "UTC+08",
    "hi": "UTC+05:30",
    "en-GB": "UTC+00",
    "pt-PT": "UTC+00",
    "en-AU": "UTC+10",
    "en-CA": "UTC-05",
    "es-MX": "UTC-06",
    "fr-CA": "UTC-05",
    "es-AR": "UTC-03",
    "es-CL": "UTC-03",
    "es-CO": "UTC-05",
    "en-US": "UTC-05",
}


def parse_offset(offset_str: str) -> timedelta | None:
    """Parse ``'UTC+5'``, ``'UTC-3'``, ``'UTC+5:30'`` → timedelta."""
    m = _OFFSET_RE.match(offset_str.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3)) if m.group(3) else 0
    if not (
        0 <= hours <= _MAX_OFFSET_HOURS and 0 <= minutes <= _MAX_OFFSET_MINUTES
    ):
        return None
    return sign * timedelta(hours=hours, minutes=minutes)


def format_offset(offset: timedelta) -> str:
    """Format timedelta → ``'UTC+05'`` or ``'UTC+05:30'``."""
    total_minutes = int(offset.total_seconds() / 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours = abs(total_minutes) // 60
    minutes = abs(total_minutes) % 60
    if minutes == 0:
        return f"UTC{sign}{hours:02d}"
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def locale_to_offset_str(locale_value: str) -> str | None:
    """Guess UTC offset from a Discord locale value (e.g. ``'en-US'``)."""
    return _LOCALE_TO_OFFSET.get(locale_value)


def user_datetime_to_utc(
    date_str: str, time_str: str, offset: timedelta
) -> datetime:
    """Parse date/time strings the user typed in their offset → UTC datetime."""
    y_str, m_str, d_str = date_str.split("-")
    h_str, mi_str = time_str.split(":")
    user_tz = timezone(offset)
    return datetime(
        int(y_str),
        int(m_str),
        int(d_str),
        int(h_str),
        int(mi_str),
        tzinfo=user_tz,
    ).astimezone(UTC)
