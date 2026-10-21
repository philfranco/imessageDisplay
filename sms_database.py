"""Read and organize messages, contacts, and attachments from Apple databases."""

import datetime
import hashlib
import os
import plistlib
import re
import sqlite3
from collections import defaultdict



def sanitize_filename(name):
    if not name:
        return 'conversation'
    name = re.sub(r'[<>:"/\\|?*]', '_', str(name))
    name = re.sub(r'\s+', '_', name.strip())
    return name[:120] or 'conversation'


def sanitize_backup_relative_path(path, base_path=None):
    if os.path.splitdrive(path)[0]:
        return path
    parts = []
    for part in str(path).replace('\\', '/').split('/'):
        if not part:
            continue
        part = re.sub(r'[<>:"|?*]', '-', part).rstrip(' .') or '_'
        if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.IGNORECASE):
            part = '_' + part
        parts.append(part)
    if not parts:
        return ''

    original_parts = parts[:]
    relative_path = os.path.join(*parts)
    if not base_path:
        return relative_path

    maximum_path_length = 240
    base_length = len(os.path.abspath(base_path))
    while len(os.path.join(os.path.abspath(base_path), relative_path)) > maximum_path_length:
        excess = len(os.path.join(os.path.abspath(base_path), relative_path)) - maximum_path_length
        candidates = []
        for index, part in enumerate(parts):
            extension = os.path.splitext(original_parts[index])[1][:20] if index == len(parts) - 1 else ''
            minimum_length = len(extension) + 9
            if len(part) > minimum_length:
                candidates.append((len(part) - minimum_length, index))
        if not candidates:
            extension = os.path.splitext(original_parts[-1])[1][:20]
            parts = [hashlib.sha256('/'.join(original_parts).encode('utf-8')).hexdigest()[:16] + extension]
            relative_path = parts[0]
            if base_length + 1 + len(relative_path) > maximum_path_length:
                raise ValueError('The selected output folder is too long for Windows paths.')
            break

        _, index = max(candidates)
        original = original_parts[index]
        extension = os.path.splitext(original)[1][:20] if index == len(parts) - 1 else ''
        digest = hashlib.sha256(original.encode('utf-8')).hexdigest()[:8]
        minimum_length = len(extension) + 9
        target_length = max(minimum_length, len(parts[index]) - excess)
        prefix_length = max(0, target_length - len(extension) - len(digest) - 1)
        parts[index] = f'{original[:prefix_length]}~{digest}{extension}'
        relative_path = os.path.join(*parts)
    return relative_path


def get_table_names(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cursor.fetchall()]


def choose_column(candidates, available):
    lower_map = {name.lower(): name for name in available}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    for candidate in candidates:
        for available_name in available:
            if candidate.lower() in available_name.lower():
                return available_name
    return None


def row_value(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def extract_attributed_body_text(attributed_body):
    if not isinstance(attributed_body, (bytes, bytearray, memoryview)):
        return None

    data = bytes(attributed_body)
    marker = re.search(rb'[\x94\x95]\x84\x01\+', data)
    if not marker:
        return None

    offset = marker.end()
    if offset >= len(data):
        return None

    length_marker = data[offset]
    offset += 1
    if length_marker == 0x81:
        length_size = 2
    elif length_marker == 0x82:
        length_size = 4
    elif length_marker < 0x80:
        length = length_marker
        length_size = 0
    else:
        return None

    if length_size:
        length_end = offset + length_size
        if length_end > len(data):
            return None
        length = int.from_bytes(data[offset:length_end], 'little')
        offset = length_end

    text_end = offset + length
    if text_end > len(data):
        return None
    return data[offset:text_end].decode('utf-8', errors='replace')


def apple_timestamp_to_iso(value):
    if value is None:
        return 'Unknown'
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)

    if ts > 1e14:
        ts /= 1_000_000_000
    elif ts > 1e11:
        ts /= 1_000_000
    elif ts > 1e9:
        ts /= 1_000_000

    ts += 978307200
    try:
        return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    except (OSError, OverflowError, ValueError):
        return str(value)


def connect_db(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Database file not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_phone_number(number):
    digits = re.sub(r'\D', '', str(number or ''))
    if len(digits) == 11 and digits.startswith('1'):
        return digits[1:]
    return digits


def conversation_key_for_address(address):
    address = str(address or '').strip()
    phone_number = normalize_phone_number(address)
    if phone_number:
        return ('phone', phone_number)
    if address:
        return ('address', address.casefold())
    return None


def fetch_contacts(address_book_db_path):
    conn = connect_db(address_book_db_path)
    try:
        tables = get_table_names(conn)
        person_table = choose_column(['ABPerson'], tables)
        multivalue_table = choose_column(['ABMultiValue'], tables)
        if not person_table or not multivalue_table:
            raise ValueError('Address Book database must contain ABPerson and ABMultiValue tables.')

        person_cols = get_columns(conn, person_table)
        multivalue_cols = get_columns(conn, multivalue_table)
        person_id_col = choose_column(['ROWID', '_ROWID_'], person_cols)
        first_col = choose_column(['First'], person_cols)
        last_col = choose_column(['Last'], person_cols)
        display_col = choose_column(['DisplayName'], person_cols)
        organization_col = choose_column(['Organization'], person_cols)
        record_id_col = choose_column(['record_id'], multivalue_cols)
        property_col = choose_column(['property'], multivalue_cols)
        value_col = choose_column(['value'], multivalue_cols)

        required = (
            person_id_col,
            record_id_col,
            property_col,
            value_col,
        )
        if not all(required):
            raise ValueError('Address Book tables are missing required contact or phone columns.')

        name_parts = []
        if first_col:
            name_parts.append(f'COALESCE(p."{first_col}", \'\')')
        if last_col:
            name_parts.append(f'COALESCE(p."{last_col}", \'\')')
        name_expr = 'TRIM(' + " || ' ' || ".join(name_parts) + ')' if name_parts else "''"

        select_name = name_expr
        if display_col:
            select_name = f"COALESCE(NULLIF({select_name}, ''), p.\"{display_col}\")"
        if organization_col:
            select_name = f"COALESCE(NULLIF({select_name}, ''), p.\"{organization_col}\")"

        sql = (
            f'SELECT {select_name} AS contact_name, mv."{value_col}" AS phone_number '
            f'FROM "{person_table}" p '
            f'JOIN "{multivalue_table}" mv '
            f'ON p."{person_id_col}" = mv."{record_id_col}" '
            f'WHERE mv."{property_col}" = 3'
        )
        contacts = {}
        for row in conn.execute(sql):
            phone_number = normalize_phone_number(row['phone_number'])
            contact_name = str(row['contact_name'] or '').strip()
            if phone_number and contact_name:
                contacts.setdefault(phone_number, contact_name)
        return contacts
    finally:
        conn.close()


def fetch_group_participants(sms_db_path, contacts):
    conn = connect_db(sms_db_path)
    try:
        tables = get_table_names(conn)
        chat_table = choose_column(['chat', 'zchat'], tables)
        handle_table = choose_column(['handle', 'zhandle'], tables)
        chat_handle_table = choose_column(['chat_handle_join', 'zchathandlejoin'], tables)
        if not chat_table or not handle_table or not chat_handle_table:
            raise ValueError('SMS database is missing chat participant tables.')

        chat_cols = get_columns(conn, chat_table)
        chat_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK'], chat_cols)
        chat_identifier_col = choose_column(['chat_identifier'], chat_cols)
        handle_cols = get_columns(conn, handle_table)
        handle_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK'], handle_cols)
        handle_name_col = choose_column(['id', 'address', 'username', 'phone_number'], handle_cols)
        join_cols = get_columns(conn, chat_handle_table)
        join_chat_col = choose_column(['chat_id', 'chatid', 'ZCHAT'], join_cols)
        join_handle_col = choose_column(['handle_id', 'handleid', 'ZHANDLE'], join_cols)
        if not all((chat_pk, chat_identifier_col, handle_pk, handle_name_col, join_chat_col, join_handle_col)):
            raise ValueError('SMS database chat participant tables are missing required columns.')

        sql = (
            f'SELECT c."{chat_identifier_col}" AS chat_identifier, h."{handle_name_col}" AS address '
            f'FROM "{chat_handle_table}" j '
            f'JOIN "{chat_table}" c ON j."{join_chat_col}" = c."{chat_pk}" '
            f'JOIN "{handle_table}" h ON j."{join_handle_col}" = h."{handle_pk}" '
            f'WHERE c."{chat_identifier_col}" LIKE \'chat%\''
        )
        participants = defaultdict(set)
        for row in conn.execute(sql):
            identifier = str(row['chat_identifier'] or '').strip()
            address = str(row['address'] or '').strip()
            if not identifier or not address:
                continue
            contact_name = contacts.get(normalize_phone_number(address), address)
            if contact_name.casefold() != 'me':
                participants[('group', identifier.casefold())].add(contact_name)
        return {
            key: sorted(names, key=str.casefold)
            for key, names in participants.items()
        }
    finally:
        conn.close()


def apply_contact_names(messages, contacts):
    for message in messages:
        if message['sender'] in ('Me', 'Unknown'):
            continue
        phone_number = normalize_phone_number(message['sender'])
        if phone_number in contacts:
            message['sender'] = contacts[phone_number]
    return messages


def get_columns(conn, table_name):
    cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
    return [row[1] for row in cursor.fetchall()]


def fetch_sms_messages(sms_db_path):
    conn = connect_db(sms_db_path)
    tables = get_table_names(conn)

    message_table = choose_column(['message', 'zmessage'], tables)
    handle_table = choose_column(['handle', 'zhandle'], tables)
    chat_table = choose_column(['chat', 'zchat'], tables)
    join_table = choose_column(['chat_message_join', 'zchatmessagejoin', 'chat_message_join', 'zchatmessagejoin'], tables)

    if not message_table:
        raise ValueError('No message table found in SMS database')

    message_cols = get_columns(conn, message_table)
    msg_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK', 'ZMESSAGE'], message_cols) or 'ROWID'
    text_col = choose_column(['text', 'body', 'message'], message_cols)
    attributed_body_col = choose_column(['attributedBody'], message_cols)
    date_col = choose_column(['date', 'date_sent', 'timestamp'], message_cols)
    is_from_me_col = choose_column(['is_from_me', 'is_from_me', 'is_from_me', 'sender', 'is_from_me'], message_cols)
    handle_id_col = choose_column(['handle_id', 'handleid', 'ZFROMHANDLE', 'ZHANDLE'], message_cols)
    guid_col = choose_column(['guid', 'message_guid', 'ZGUID'], message_cols)

    handle_cols = get_columns(conn, handle_table) if handle_table else []
    handle_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK'], handle_cols)
    handle_name_col = choose_column(['id', 'address', 'username', 'phone_number'], handle_cols)

    query = [f'm.{msg_pk} AS msg_id']
    if text_col:
        query.append(f'm.{text_col} AS text')
    if attributed_body_col:
        query.append(f'm.{attributed_body_col} AS attributed_body')
    query.append(f'm.{date_col} AS date')
    query.append(f'm.{is_from_me_col} AS is_from_me')
    if guid_col:
        query.append(f'm."{guid_col}" AS guid')
    if handle_id_col:
        query.append(f'm.{handle_id_col} AS handle_id')
    if handle_table and handle_pk and handle_name_col and handle_id_col:
        query.append(f'h.{handle_name_col} AS handle_address')
    sql = f"SELECT {', '.join(query)} FROM {message_table} m"
    if handle_table and handle_pk and handle_name_col and handle_id_col:
        sql += f" LEFT JOIN {handle_table} h ON m.{handle_id_col} = h.{handle_pk}"
    if date_col:
        sql += f" ORDER BY m.{date_col} ASC"

    messages = []
    for row in conn.execute(sql):
        handle_address = row_value(row, 'handle_address')
        message_text = row_value(row, 'text')
        if not message_text:
            message_text = extract_attributed_body_text(row_value(row, 'attributed_body'))
        sender = 'Me' if bool(row['is_from_me']) else (handle_address or row_value(row, 'handle_id') or 'Unknown')
        messages.append({
            'id': row['msg_id'],
            'guid': row_value(row, 'guid'),
            'text': message_text,
            'date': apple_timestamp_to_iso(row['date']),
            'is_from_me': bool(row['is_from_me']),
            'sender': sender,
            'handle_address': handle_address,
            'handle_id': row_value(row, 'handle_id'),
            'chat_id': None,
            'attachments': []
        })

    chat_names = {}
    if chat_table and join_table:
        chat_cols = get_columns(conn, join_table)
        chat_msg_col = choose_column(['message_id', 'messageid', 'ZMESSAGE'], chat_cols)
        chat_id_col = choose_column(['chat_id', 'chatid', 'ZCHAT'], chat_cols)
        chat_cols = get_columns(conn, chat_table)
        chat_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK'], chat_cols)
        chat_name_col = choose_column(['display_name', 'chat_identifier', 'name'], chat_cols)
        chat_identifier_col = choose_column(['chat_identifier'], chat_cols)
        if chat_pk:
            chat_query = [f'"{chat_pk}" AS chat_id']
            if chat_name_col:
                chat_query.append(f'"{chat_name_col}" AS name')
            if chat_identifier_col:
                chat_query.append(f'"{chat_identifier_col}" AS identifier')
            chat_keys = {}
            for row in conn.execute(f'SELECT {", ".join(chat_query)} FROM "{chat_table}"'):
                identifier = row_value(row, 'identifier')
                if identifier and str(identifier).lower().startswith('chat'):
                    key = ('group', str(identifier).casefold())
                else:
                    key = conversation_key_for_address(identifier)
                    if key is None:
                        key = ('chat', row['chat_id'])
                chat_keys[row['chat_id']] = key
                name = str(row_value(row, 'name') or '').strip()
                if name:
                    chat_names.setdefault(key, name)

            if chat_msg_col and chat_id_col:
                message_by_id = {msg['id']: msg for msg in messages}
                chat_keys_by_message = defaultdict(set)
                join_sql = (
                    f'SELECT "{chat_msg_col}" AS msg_id, "{chat_id_col}" AS chat_id '
                    f'FROM "{join_table}"'
                )
                for row in conn.execute(join_sql):
                    if row['msg_id'] in message_by_id and row['chat_id'] in chat_keys:
                        chat_keys_by_message[row['msg_id']].add(chat_keys[row['chat_id']])

                for msg in messages:
                    candidate_keys = chat_keys_by_message.get(msg['id'], set())
                    group_keys = sorted(key for key in candidate_keys if key[0] == 'group')
                    if group_keys:
                        msg['chat_id'] = group_keys[0]
                    elif candidate_keys:
                        sender_key = conversation_key_for_address(msg['handle_address'])
                        if sender_key in candidate_keys:
                            msg['chat_id'] = sender_key
                        else:
                            msg['chat_id'] = sorted(candidate_keys)[0]
                    else:
                        msg['chat_id'] = conversation_key_for_address(msg['handle_address'])

    for msg in messages:
        if msg['chat_id'] is None:
            msg['chat_id'] = conversation_key_for_address(msg['handle_address'])

    conn.close()
    return messages, chat_names


def fetch_attachments(attachment_db_path):
    conn = connect_db(attachment_db_path)
    tables = get_table_names(conn)

    attachment_table = choose_column(['attachment', 'zattachment'], tables)
    join_table = choose_column(['message_attachment_join', 'zmessageattachment', 'zmessage_attachment_join', 'zmessageattachment'], tables)

    if not attachment_table:
        conn.close()
        return {}

    attach_cols = get_columns(conn, attachment_table)
    attach_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK', 'ZATTACHMENT'], attach_cols) or 'ROWID'
    filename_col = choose_column(['filename', 'transfer_name', 'name', 'file_name', 'path'], attach_cols)
    mime_col = choose_column(['mime_type', 'uti', 'uniform_type_identifier'], attach_cols)
    filepath_col = choose_column(['file_path', 'path', 'filepath', 'filename'], attach_cols)
    size_col = choose_column(['total_bytes', 'filesize', 'file_size'], attach_cols)
    sticker_col = choose_column(['is_sticker'], attach_cols)
    sticker_info_col = choose_column(['sticker_user_info'], attach_cols)

    def attachment_from_row(row):
        sticker_info = row_value(row, 'sticker_user_info')
        if isinstance(sticker_info, (bytes, bytearray, memoryview)):
            sticker_info = plistlib.loads(bytes(sticker_info))
        return {
            'id': row['attach_id'],
            'filename': row_value(row, 'filename') or f'attachment_{row["attach_id"]}',
            'mime_type': row_value(row, 'mime_type'),
            'file_path': row_value(row, 'file_path'),
            'file_size': row_value(row, 'file_size'),
            'is_sticker': bool(row_value(row, 'is_sticker')),
            'sticker_user_info': sticker_info if isinstance(sticker_info, dict) else {},
        }

    attachments = defaultdict(list)
    if join_table:
        join_cols = get_columns(conn, join_table)
        msg_id_col = choose_column(['message_id', 'messageid', 'ZMESSAGE'], join_cols)
        attach_id_col = choose_column(['attachment_id', 'attachmentid', 'ZATTACHMENT'], join_cols)
        if msg_id_col and attach_id_col:
            sql = f"SELECT j.{msg_id_col} AS msg_id, a.{attach_pk} AS attach_id"
            if filename_col:
                sql += f", a.{filename_col} AS filename"
            if mime_col:
                sql += f", a.{mime_col} AS mime_type"
            if filepath_col and filepath_col != filename_col:
                sql += f", a.{filepath_col} AS file_path"
            if size_col:
                sql += f", a.{size_col} AS file_size"
            if sticker_col:
                sql += f", a.{sticker_col} AS is_sticker"
            if sticker_info_col:
                sql += f", a.{sticker_info_col} AS sticker_user_info"
            sql += f" FROM {join_table} j JOIN {attachment_table} a ON j.{attach_id_col} = a.{attach_pk}"
            for row in conn.execute(sql):
                attachments[row['msg_id']].append(attachment_from_row(row))
    else:
        if choose_column(['message_id', 'messageid', 'ZMESSAGE'], attach_cols):
            msg_col = choose_column(['message_id', 'messageid', 'ZMESSAGE'], attach_cols)
            sql = f"SELECT {attach_pk} AS attach_id, {msg_col} AS msg_id"
            if filename_col:
                sql += f", {filename_col} AS filename"
            if mime_col:
                sql += f", {mime_col} AS mime_type"
            if filepath_col and filepath_col != filename_col:
                sql += f", {filepath_col} AS file_path"
            if size_col:
                sql += f", {size_col} AS file_size"
            if sticker_col:
                sql += f", {sticker_col} AS is_sticker"
            if sticker_info_col:
                sql += f", {sticker_info_col} AS sticker_user_info"
            sql += f" FROM {attachment_table}"
            for row in conn.execute(sql):
                attachments[row['msg_id']].append(attachment_from_row(row))

    conn.close()
    return attachments


def normalize_attachment_paths(attachments, attachment_folder, sticker_cache_folder=None):
    if not attachment_folder:
        return attachments

    normalized = {}
    for msg_id, attach_list in attachments.items():
        normalized[msg_id] = []
        for attachment in attach_list:
            file_path = attachment.get('file_path')
            path_value = file_path or attachment.get('filename')
            path_text = str(path_value or '').replace('\\', '/')
            sticker_marker = 'Library/SMS/StickerCache/'
            sticker_index = path_text.casefold().find(sticker_marker.casefold())
            if sticker_cache_folder and sticker_index >= 0:
                sticker_relative_path = path_text[sticker_index + len(sticker_marker):]
                safe_relative_path = sanitize_backup_relative_path(
                    sticker_relative_path,
                    sticker_cache_folder,
                )
                attachment['file_path'] = os.path.normpath(
                    os.path.join(sticker_cache_folder, safe_relative_path)
                )
                normalized[msg_id].append(attachment)
                continue

            if file_path:
                path_text = str(file_path)
                if path_text.startswith('file://'):
                    path_text = path_text[7:]

                # Strip any leading slashes
                path_text = path_text.lstrip('/\\')
                # Remove leading '~/'' or '~\\' if present
                if path_text.startswith('~/') or path_text.startswith('~\\'):
                    path_text = path_text[2:]
                # Remove any '/~/' or '\\~\\' segments that may appear in exported paths
                path_text = path_text.replace('/~/', '/').replace('\\~\\', '\\')
                # Also remove any remaining standalone '~' path segment at start
                if path_text.startswith('~'):
                    path_text = path_text.lstrip('~').lstrip('/\\')
                path_text = sanitize_backup_relative_path(path_text, attachment_folder)
                attachment['file_path'] = os.path.normpath(os.path.join(attachment_folder, path_text))
            elif attachment.get('filename'):
                path_text = str(attachment.get('filename'))

                if path_text.startswith('file://'):
                    path_text = path_text[7:]
                # Strip any leading slashes
                path_text = path_text.lstrip('/\\')
                # Remove leading '~/'' or '~\\' if present
                if path_text.startswith('~/') or path_text.startswith('~\\'):
                    path_text = path_text[2:]
                # Remove any '/~/' or '\\~\\' segments that may appear in exported paths
                path_text = path_text.replace('/~/', '/').replace('\\~\\', '\\')
                # Also remove any remaining standalone '~' path segment at start
                if path_text.startswith('~'):
                    path_text = path_text.lstrip('~').lstrip('/\\')
                path_text = sanitize_backup_relative_path(path_text, attachment_folder)

                attachment['file_path'] = os.path.normpath(os.path.join(attachment_folder, path_text))
            normalized[msg_id].append(attachment)
    return normalized


def attach_to_messages(messages, attachments_map):
    for msg in messages:
        if msg['id'] in attachments_map:
            msg['attachments'] = attachments_map[msg['id']]
    return messages


def group_messages_by_conversation(messages, chat_names):
    conversations = defaultdict(lambda: {'name': None, 'messages': []})
    id_to_sender = {}  # Map conversation ID to phone number/sender
    for msg in messages:
        key = msg['chat_id'] or ('message', msg['id'])
        if conversations[key]['name'] is None:
            if key[0] == 'group':
                conversations[key]['name'] = chat_names.get(key) or f'Chat_{key[1]}'
                id_to_sender[key] = str(msg['sender'])
            elif key[0] == 'phone':
                conversations[key]['name'] = chat_names.get(key) or str(msg['sender'] if msg['sender'] != 'Me' else key[1])
                id_to_sender[key] = str(msg['sender'])
            elif key[0] == 'address':
                conversations[key]['name'] = chat_names.get(key) or str(msg['sender'] if msg['sender'] != 'Me' else key[1])
                id_to_sender[key] = str(msg['sender'])
            else:
                conversations[key]['name'] = str(msg['sender'])
                id_to_sender[key] = str(msg['sender'])
        conversations[key]['messages'].append(msg)
    return conversations, id_to_sender
