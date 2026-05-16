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
    "ja": "UTC+9",
    "ko": "UTC+9",
    "zh-CN": "UTC+8",
    "zh-TW": "UTC+8",
    "de": "UTC+1",
    "fr": "UTC+1",
    "es-ES": "UTC+1",
    "it": "UTC+1",
    "pt-BR": "UTC-3",
    "ru": "UTC+3",
    "nl": "UTC+1",
    "pl": "UTC+1",
    "tr": "UTC+3",
    "da": "UTC+1",
    "fi": "UTC+2",
    "nb-NO": "UTC+1",
    "sv-SE": "UTC+1",
    "cs": "UTC+1",
    "hu": "UTC+1",
    "ro": "UTC+2",
    "uk": "UTC+2",
    "bg": "UTC+2",
    "el": "UTC+2",
    "th": "UTC+7",
    "vi": "UTC+7",
    "id": "UTC+7",
    "ms": "UTC+8",
    "hi": "UTC+5:30",
    "en-GB": "UTC+0",
    "pt-PT": "UTC+0",
    "en-AU": "UTC+10",
    "en-CA": "UTC-5",
    "es-MX": "UTC-6",
    "fr-CA": "UTC-5",
    "es-AR": "UTC-3",
    "es-CL": "UTC-3",
    "es-CO": "UTC-5",
    "en-US": "UTC-5",
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
    """Format timedelta → ``'UTC+5'`` or ``'UTC+5:30'``."""
    total_minutes = int(offset.total_seconds() / 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours = abs(total_minutes) // 60
    minutes = abs(total_minutes) % 60
    if minutes == 0:
        return f"UTC{sign}{hours}"
    return f"UTC{sign}{hours}:{minutes:02d}"


def locale_to_offset_str(locale_value: str) -> str | None:
    """Guess UTC offset string from a Discord locale value (e.g. ``'en-US'``)."""  # noqa: E501
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
