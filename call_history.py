"""Read call records from extracted Apple CallHistory databases."""

import datetime
import os
import sqlite3

from sms_database import choose_column, normalize_phone_number
from time_zone_utils import DEFAULT_TIME_ZONE, localize_message_datetime


APPLE_EPOCH_OFFSET = 978307200


def _quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _call_date(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            value = datetime.datetime.fromtimestamp(
                float(value) + APPLE_EPOCH_OFFSET,
                datetime.timezone.utc,
            )
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
    else:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _direction(originated, answered):
    if originated:
        return 'Outgoing'
    if answered is not None and not answered:
        return 'Missed'
    return 'Incoming'


def _read_database(database_path, contacts):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            name.casefold(): name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        table = tables.get('zcallrecord')
        if not table:
            raise ValueError(
                f'Call history database has no ZCALLRECORD table: {database_path}'
            )

        columns = [
            row['name']
            for row in connection.execute(
                f'PRAGMA table_info({_quote_identifier(table)})'
            )
        ]
        date_column = choose_column(['ZDATE', 'date'], columns)
        address_column = choose_column(['ZADDRESS', 'address'], columns)
        duration_column = choose_column(['ZDURATION', 'duration'], columns)
        originated_column = choose_column(['ZORIGINATED', 'originated'], columns)
        answered_column = choose_column(['ZANSWERED', 'answered'], columns)
        name_column = choose_column(['ZNAME', 'name'], columns)
        if not date_column or not address_column:
            raise ValueError(
                f'Call history table is missing date or address columns: {database_path}'
            )

        selected = [date_column, address_column]
        selected.extend(
            column for column in (
                duration_column,
                originated_column,
                answered_column,
                name_column,
            )
            if column and column not in selected
        )
        query = (
            'SELECT ' + ', '.join(_quote_identifier(column) for column in selected)
            + f' FROM {_quote_identifier(table)}'
        )
        records = []
        for row in connection.execute(query):
            call_date = _call_date(row[date_column])
            address = str(row[address_column] or '').strip()
            if not call_date or not address:
                continue
            phone_number = normalize_phone_number(address)
            stored_name = str(row[name_column] or '').strip() if name_column else ''
            records.append({
                'date': call_date,
                'address': address,
                'phone_number': phone_number,
                'contact': stored_name or contacts.get(phone_number) or address,
                'duration': row[duration_column] if duration_column else 0,
                'direction': _direction(
                    row[originated_column] if originated_column else False,
                    row[answered_column] if answered_column else None,
                ),
            })
        return records
    finally:
        connection.close()


def fetch_call_history(database_contacts, time_zone=DEFAULT_TIME_ZONE):
    """Read, resolve, deduplicate, and chronologically sort call records."""
    records_by_key = {}
    for database_path, contacts in database_contacts:
        if not database_path or not os.path.isfile(database_path):
            continue
        for record in _read_database(database_path, contacts):
            key = (
                record['date'],
                record['phone_number'] or record['address'].casefold(),
                record['duration'],
                record['direction'],
            )
            previous = records_by_key.get(key)
            if previous is None or previous['contact'] == previous['address']:
                records_by_key[key] = record

    records = list(records_by_key.values())
    records.sort(key=lambda record: localize_message_datetime(record['date'], time_zone), reverse=True)
    return records
