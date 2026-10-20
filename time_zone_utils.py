"""Convert archived UTC message timestamps to a selected IANA time zone."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


DEFAULT_TIME_ZONE = 'America/New_York'


def available_time_zones():
    zones = {
        zone
        for zone in available_timezones()
        if '/' in zone and not zone.startswith(('Etc/', 'SystemV/'))
    }
    zones.add('UTC')
    return tuple(sorted(zones))


def get_time_zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as error:
        raise ValueError(f'Unknown IANA time zone: {name}') from error


def localize_message_datetime(value, time_zone=DEFAULT_TIME_ZONE):
    text = str(value or '')
    if not text or text == 'Unknown':
        return text or 'Unknown'

    try:
        message_datetime = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return text

    if message_datetime.tzinfo is None:
        message_datetime = message_datetime.replace(tzinfo=timezone.utc)
    return message_datetime.astimezone(get_time_zone(time_zone)).strftime('%Y-%m-%d %H:%M:%S')
