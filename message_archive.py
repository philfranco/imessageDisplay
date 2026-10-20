"""Persistent, append-only storage for messages imported from multiple backups."""

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from itertools import chain


ARCHIVE_FILENAME = 'messages_archive.sqlite3'


def _stable_value(value):
    if isinstance(value, tuple):
        return [_stable_value(item) for item in value]
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stable_value(item) for key, item in value.items()}
    return value


def _fallback_message_key(message, occurrence):
    fallback = {
        'chat_id': _stable_value(message.get('chat_id')),
        'date': message.get('date'),
        'is_from_me': bool(message.get('is_from_me')),
        'handle_address': message.get('handle_address'),
        'text': message.get('text'),
    }
    serialized = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f'fallback:{digest}:{occurrence}'


def _message_key(message, occurrence):
    guid = str(message.get('guid') or '').strip()
    if guid:
        return f'guid:{guid.casefold()}'
    return _fallback_message_key(message, occurrence)


def _encode_chat_key(key):
    return json.dumps(_stable_value(key), ensure_ascii=False, separators=(',', ':'))


def _decode_chat_key(value):
    decoded = json.loads(value)
    return tuple(decoded) if isinstance(decoded, list) else decoded


def archive_is_empty(output_dir):
    archive_path = os.path.join(output_dir, ARCHIVE_FILENAME)
    if not os.path.isfile(archive_path):
        return True
    conn = sqlite3.connect(archive_path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'messages'"
        ).fetchone()
        if not table:
            return True
        return conn.execute('SELECT 1 FROM messages LIMIT 1').fetchone() is None
    finally:
        conn.close()


def merge_messages(output_dir, messages, chat_names, legacy_message_batches=()):
    """Upsert this import into the archive without removing older messages."""
    archive_path = os.path.join(output_dir, ARCHIVE_FILENAME)
    conn = sqlite3.connect(archive_path)
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS messages ('
            'message_key TEXT PRIMARY KEY, guid TEXT, payload TEXT NOT NULL, '
            'first_imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, '
            'last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'
        )
        conn.execute(
            'CREATE TABLE IF NOT EXISTS conversation_names ('
            'conversation_key TEXT PRIMARY KEY, name TEXT NOT NULL)'
        )

        for batch in chain(legacy_message_batches, (messages,)):
            occurrences = defaultdict(int)
            for message in batch:
                guid = str(message.get('guid') or '').strip() or None
                signature = (
                    _stable_value(message.get('chat_id')),
                    message.get('date'),
                    bool(message.get('is_from_me')),
                    message.get('handle_address'),
                    message.get('text'),
                )
                signature_json = json.dumps(
                    signature, ensure_ascii=False, sort_keys=True, separators=(',', ':')
                )
                occurrence = occurrences[signature_json]
                occurrences[signature_json] += 1

                message_key = _message_key(message, occurrence)
                fallback_key = _fallback_message_key(message, occurrence)
                existing = conn.execute(
                    'SELECT payload FROM messages WHERE message_key = ?', (message_key,)
                ).fetchone()
                fallback_existing = None
                if guid and fallback_key != message_key:
                    fallback_existing = conn.execute(
                        'SELECT payload FROM messages WHERE message_key = ?', (fallback_key,)
                    ).fetchone()

                payload_message = dict(message)
                previous_payloads = [
                    json.loads(row[0])
                    for row in (existing, fallback_existing)
                    if row is not None
                ]
                if previous_payloads:
                    if not payload_message.get('attachments'):
                        payload_message['attachments'] = next(
                            (item.get('attachments') for item in previous_payloads if item.get('attachments')),
                            [],
                        )
                    if not payload_message.get('group_participants'):
                        payload_message['group_participants'] = next(
                            (item.get('group_participants') for item in previous_payloads
                             if item.get('group_participants')),
                            [],
                        )

                payload = json.dumps(payload_message, ensure_ascii=False, separators=(',', ':'))
                conn.execute(
                    'INSERT INTO messages (message_key, guid, payload) VALUES (?, ?, ?) '
                    'ON CONFLICT(message_key) DO UPDATE SET '
                    'guid = excluded.guid, payload = excluded.payload, last_seen_at = CURRENT_TIMESTAMP',
                    (message_key, guid, payload),
                )
                if fallback_existing and fallback_key != message_key:
                    conn.execute('DELETE FROM messages WHERE message_key = ?', (fallback_key,))

        for key, name in chat_names.items():
            if name:
                conn.execute(
                    'INSERT INTO conversation_names (conversation_key, name) VALUES (?, ?) '
                    'ON CONFLICT(conversation_key) DO UPDATE SET name = excluded.name',
                    (_encode_chat_key(key), str(name)),
                )

        conn.commit()
        archived_messages = [
            json.loads(row[0])
            for row in conn.execute('SELECT payload FROM messages')
        ]
        for message in archived_messages:
            if isinstance(message.get('chat_id'), list):
                message['chat_id'] = tuple(message['chat_id'])
        archived_messages.sort(
            key=lambda message: (str(message.get('date') or 'Unknown'), str(message.get('id') or ''))
        )

        archived_chat_names = {
            _decode_chat_key(key): name
            for key, name in conn.execute('SELECT conversation_key, name FROM conversation_names')
        }
        imported_count = len(messages)
        archived_count = len(archived_messages)
        return archived_messages, archived_chat_names, imported_count, archived_count
    finally:
        conn.close()
