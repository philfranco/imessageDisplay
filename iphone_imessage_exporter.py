"""iPhone iMessage-style conversation exporter.

Reads Apple SMS database(s) and attachment database(s), groups messages by conversation,
and writes HTML files that look like iMessage chat transcripts.

Usage:
    python iphone_imessage_exporter.py --sms-db path/to/sms.db --attachment-db path/to/attachment.db --output-dir output_html

If attachment database is omitted, the script will attempt to read attachments from the same SMS database.
"""

import argparse
import hashlib
import html
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import datetime
import pickle
from collections import defaultdict
from pathlib import Path

def sanitize_filename(name):
    if not name:
        return 'conversation'
    name = re.sub(r'[<>:"/\\|?*]', '_', str(name))
    name = re.sub(r'\s+', '_', name.strip())
    return name[:120] or 'conversation'


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
        name_expr = f'TRIM({" || \' \' || ".join(name_parts)})' if name_parts else "''"

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
            sql += f" FROM {join_table} j JOIN {attachment_table} a ON j.{attach_id_col} = a.{attach_pk}"
            for row in conn.execute(sql):
                attachments[row['msg_id']].append({
                    'id': row['attach_id'],
                    'filename': row_value(row, 'filename') or f'attachment_{row["attach_id"]}',
                    'mime_type': row_value(row, 'mime_type'),
                    'file_path': row_value(row, 'file_path'),
                    'file_size': row_value(row, 'file_size')
                })
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
            sql += f" FROM {attachment_table}"
            for row in conn.execute(sql):
                attachments[row['msg_id']].append({
                    'id': row['attach_id'],
                    'filename': row_value(row, 'filename') or f'attachment_{row["attach_id"]}',
                    'mime_type': row_value(row, 'mime_type'),
                    'file_path': row_value(row, 'file_path'),
                    'file_size': row_value(row, 'file_size')
                })

    conn.close()
    return attachments


def normalize_attachment_paths(attachments, attachment_folder):
    if not attachment_folder:
        return attachments

    normalized = {}
    for msg_id, attach_list in attachments.items():
        normalized[msg_id] = []
        for attachment in attach_list:
            file_path = attachment.get('file_path')
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


def is_image_type(mime_type, filename):
    if mime_type and mime_type.startswith('image'):
        return True
    lower_name = filename.lower()
    return any(lower_name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.heif', '.heics'))


def is_video_type(mime_type, filename):
    if mime_type and mime_type.lower().startswith('video/'):
        return True
    return str(filename or '').lower().endswith(('.mov', '.mp4', '.m4v', '.3gp'))


def is_heic_type(mime_type, filename):
    lower_mime = str(mime_type or '').lower()
    lower_name = str(filename or '').lower()
    return (
        lower_mime in ('image/heic', 'image/heif', 'image/heic-sequence', 'image/heif-sequence', 'public.heic', 'public.heif')
        or lower_name.endswith(('.heic', '.heif', '.heics'))
    )


def convert_heic_to_jpeg(source_path, output_dir):
    source_stat = os.stat(source_path)
    source_key = (
        f'{os.path.normcase(os.path.abspath(source_path))}:'
        f'{source_stat.st_mtime_ns}:{source_stat.st_size}'
    )
    preview_name = f'{hashlib.sha256(source_key.encode("utf-8")).hexdigest()}.jpg'
    preview_dir = os.path.join(output_dir, 'converted_heic')
    preview_path = os.path.join(preview_dir, preview_name)

    if os.path.exists(preview_path):
        return preview_path

    try:
        import pillow_heif
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError(
            'HEIC/HEIF attachments require Pillow and pillow-heif. '
            'Install them with: python -m pip install Pillow pillow-heif'
        ) from exc

    os.makedirs(preview_dir, exist_ok=True)
    pillow_heif.register_heif_opener()
    with Image.open(source_path) as image:
        ImageOps.exif_transpose(image).convert('RGB').save(preview_path, format='JPEG', quality=90)

    return preview_path


def convert_mov_to_mp4(source_path, output_dir):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError(
            'MOV conversion requires FFmpeg. Install it in your Conda environment with: '
            'conda install -c conda-forge ffmpeg'
        )

    source_stat = os.stat(source_path)
    source_key = (
        f'{os.path.normcase(os.path.abspath(source_path))}:'
        f'{source_stat.st_mtime_ns}:{source_stat.st_size}'
    )
    video_name = f'{hashlib.sha256(source_key.encode("utf-8")).hexdigest()}.mp4'
    video_dir = os.path.join(output_dir, 'converted_video')
    video_path = os.path.join(video_dir, video_name)

    if os.path.exists(video_path):
        return video_path

    os.makedirs(video_dir, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4', dir=video_dir)
    os.close(temp_fd)
    try:
        result = subprocess.run(
            [
                ffmpeg,
                '-y',
                '-analyzeduration', '100M',
                '-probesize', '100M',
                '-i', source_path,
                '-map', '0:v:0',
                '-map', '0:a?',
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-movflags', '+faststart',
                temp_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or 'FFmpeg returned an error without details.'
            raise RuntimeError(detail)
        os.replace(temp_path, video_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return video_path


def format_attachment_html(attachment, base_dir, attachment_folder=None, conversion_failures=None):
    if conversion_failures is None:
        conversion_failures = {}

    filename = html.escape(str(attachment.get('filename') or 'attachment'))
    mime_type = attachment.get('mime_type') or ''
    file_path = attachment.get('file_path')
    size = attachment.get('file_size')

    info = []
    if mime_type:
        info.append(html.escape(mime_type))
    if size is not None:
        info.append(f"{size} bytes")
    info_text = ' | '.join(info)

    def normalize_path_text(raw_path):
        path = str(raw_path)
        if path.startswith('file://'):
            path = path[7:]
        return path.replace('\\', '/')

    if file_path:
        path_text = normalize_path_text(file_path)
        full_path = None

        if attachment_folder:
            # Try mapping iOS-style attachment paths to the configured attachment folder.
            relative_path = path_text.lstrip('/\\')
            candidate = os.path.normpath(os.path.join(attachment_folder, relative_path))
            if os.path.exists(candidate):
                full_path = candidate

            if not full_path and path_text.startswith('~/'):
                candidate = os.path.normpath(os.path.join(attachment_folder, path_text[2:]))
                if os.path.exists(candidate):
                    full_path = candidate

            if not full_path and 'Library/SMS/Attachments' in path_text:
                suffix = path_text.split('Library/SMS/Attachments', 1)[1].lstrip('/\\')
                candidate = os.path.normpath(os.path.join(attachment_folder, suffix))
                if os.path.exists(candidate):
                    full_path = candidate

            if not full_path and os.path.isabs(path_text):
                normalized = os.path.normpath(path_text)
                if os.path.exists(normalized):
                    full_path = normalized
                else:
                    just_filename = os.path.basename(path_text)
                    candidate = os.path.normpath(os.path.join(attachment_folder, just_filename))
                    if os.path.exists(candidate):
                        full_path = candidate

            if not full_path:
                just_filename = os.path.basename(path_text)
                candidate = os.path.normpath(os.path.join(attachment_folder, just_filename))
                if os.path.exists(candidate):
                    full_path = candidate

        if not full_path and os.path.exists(path_text):
            full_path = os.path.normpath(path_text)
        elif not full_path:
            expanded = os.path.expanduser(path_text)
            if expanded != path_text and os.path.exists(expanded):
                full_path = os.path.normpath(expanded)

        if full_path:
            if is_heic_type(mime_type, filename):
                failure_key = os.path.normcase(os.path.abspath(full_path))
                if failure_key not in conversion_failures:
                    try:
                        preview_path = convert_heic_to_jpeg(full_path, base_dir)
                    except (OSError, SyntaxError, ValueError) as exc:
                        conversion_failures[failure_key] = str(exc)
                        print(f'Warning: Could not convert HEIC/HEIF attachment "{full_path}": {exc}')
                    else:
                        src = os.path.relpath(preview_path, base_dir).replace('\\', '/')
                        return f'<div class="attachment"><img src="{html.escape(src)}" alt="{filename}" /></div>'

                return (
                    f'<div class="attachment"><span>{filename}</span>'
                    '<div class="attachment-meta">Preview unavailable (conversion failed).</div></div>'
                )

            if os.path.isabs(full_path):
                src = full_path
            else:
                src = os.path.relpath(full_path, base_dir).replace('\\', '/')
            if is_image_type(mime_type, filename):
                return f'<div class="attachment"><img src="{html.escape(src)}" alt="{filename}" /></div>'
            if is_video_type(mime_type, filename):
                video_path = full_path
                video_mime_type = mime_type
                if filename.lower().endswith('.mov'):
                    failure_key = f'mov:{os.path.normcase(os.path.abspath(full_path))}'
                    if failure_key not in conversion_failures:
                        try:
                            video_path = convert_mov_to_mp4(full_path, base_dir)
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            conversion_failures[failure_key] = str(exc)
                            print(f'Warning: Could not convert MOV attachment "{full_path}": {exc}')
                        else:
                            video_mime_type = 'video/mp4'
                    if failure_key in conversion_failures:
                        return (
                            f'<div class="attachment"><video controls preload="metadata">'
                            f'<source src="{html.escape(src)}" type="video/quicktime">'
                            'Your browser cannot play this video. '
                            f'<a href="{html.escape(src)}" target="_blank">{filename}</a>'
                            '</video><div class="attachment-meta">'
                            'MP4 conversion unavailable; try opening the original MOV.</div></div>'
                        )

                try:
                    video_src = os.path.relpath(video_path, base_dir).replace('\\', '/')
                except ValueError:
                    video_src = Path(video_path).as_uri()
                source_mime_type = (
                    video_mime_type
                    if video_mime_type.lower().startswith('video/')
                    else 'video/quicktime' if filename.lower().endswith('.mov') else 'video/mp4'
                )
                return (
                    f'<div class="attachment"><video controls preload="metadata">'
                    f'<source src="{html.escape(video_src)}" type="{html.escape(source_mime_type)}">'
                    'Your browser cannot play this video. '
                    f'<a href="{html.escape(video_src)}" target="_blank">{filename}</a>'
                    '</video></div>'
                )
            return f'<div class="attachment"><a href="{html.escape(src)}" target="_blank">{filename}</a><div class="attachment-meta">{info_text}</div></div>'

    return f'<div class="attachment"><span>{filename}</span><div class="attachment-meta">{info_text or "Attachment"}</div></div>'


def build_html(
    conversation_name,
    messages,
    output_dir,
    attachment_folder=None,
    conversion_failures=None,
    output_filename=None,
):
    if conversion_failures is None:
        conversion_failures = {}

    safe_name = output_filename or sanitize_filename(conversation_name)
    filename = os.path.join(output_dir, f'{safe_name}.html')
    stats = summarize_messages(messages)

    html_content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        f'  <title>{html.escape(conversation_name)}</title>',
        '  <style>',
        '    body { min-height: 100vh; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; background: #f2f2f7; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1100px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #ffffff; transition: background .15s, color .15s, border-color .15s; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 42px); margin-bottom: 26px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .eyebrow { margin: 0 0 10px; color: #bfdbfe; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }',
        '    h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); letter-spacing: -.03em; overflow-wrap: anywhere; }',
        '    .conversation-summary { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }',
        '    .conversation-summary span { padding: 7px 11px; border: 1px solid #ffffff4d; border-radius: 999px; background: #ffffff1c; color: #eff6ff; font-size: 13px; }',
        '    .message-list { padding: 20px; border: 1px solid #e2e8f0; border-radius: 18px; background: #ffffffb8; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .message { display: flex; margin-bottom: 14px; }',
        '    .message.me { justify-content: flex-end; }',
        '    .bubble { max-width: min(78%, 760px); padding: 12px 15px; border-radius: 20px; line-height: 1.5; position: relative; overflow-wrap: anywhere; box-shadow: 0 1px 3px #0f172a12; }',
        '    .bubble.me { background: #2563eb; color: white; border-bottom-right-radius: 6px; border-bottom-left-radius: 20px; }',
        '    .bubble.other { background: #e2e8f0; color: #172033; border-bottom-left-radius: 6px; border-bottom-right-radius: 20px; }',
        '    .meta { font-size: 12px; color: #64748b; margin-top: 6px; }',
        '    .bubble.me .meta { color: #dbeafe; }',
        '    .attachment { margin-top: 8px; font-size: 13px; color: #334155; }',
        '    .attachment img { max-width: 100%; border-radius: 12px; margin-top: 4px; }',
        '    .attachment video { max-width: 100%; max-height: 480px; border-radius: 12px; margin-top: 4px; }',
        '    .attachment-meta { font-size: 11px; color: #666; margin-top: 4px; }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } .message-list { padding: 12px 8px; border-radius: 14px; } .bubble { max-width: 88%; padding: 10px 12px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="search.html">← Back to search</a><a href="index.html">Index</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage conversation</p>',
        f'      <h1>{html.escape(conversation_name)}</h1>',
        '      <div class="conversation-summary">',
        f'        <span>{stats["messages"]:,} messages</span>',
        f'        <span>{stats["attachments"]:,} attachments</span>',
        f'        <span>{html.escape(stats["first_date"])} – {html.escape(stats["last_date"])}</span>',
        '      </div>',
        '    </header>',
        '    <main class="message-list">',
    ]

    for msg in messages:
        bubble_class = 'me' if msg['is_from_me'] else 'other'
        text = html.escape(msg['text'] or '')
        if not text and not msg['attachments']:
            text = '[No text]'
        attachments_html = ''.join(
            format_attachment_html(att, output_dir, attachment_folder, conversion_failures)
            for att in msg['attachments']
        )
        sender = 'Me' if msg['is_from_me'] else html.escape(str(msg['sender']))

        html_content.append(f'    <div class="message {bubble_class}">')
        html_content.append(f'      <div class="bubble {bubble_class}">')
        html_content.append(f'        <div>{text}</div>')
        if attachments_html:
            html_content.append(f'        {attachments_html}')
        html_content.append(f'        <div class="meta">{sender} • {html.escape(msg["date"])}</div>')
        html_content.append('      </div>')
        html_content.append('    </div>')

    html_content.extend([
        '    </main>',
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_content))

    return filename


def build_conversation_entries(conversations):
    titles = {
        key: conv_data['name'] or str(key)
        for key, conv_data in conversations.items()
    }
    base_names = {key: sanitize_filename(title) for key, title in titles.items()}
    base_name_counts = defaultdict(int)
    for base_name in base_names.values():
        base_name_counts[base_name.casefold()] += 1

    entries = []
    used_filenames = set()
    for key, title in titles.items():
        filename = base_names[key]
        display_name = title
        if base_name_counts[filename.casefold()] > 1:
            key_type, key_value = key
            if key_type == 'phone' and len(str(key_value)) == 10:
                phone = str(key_value)
                display_name = f'{title} (+1 ({phone[:3]}) {phone[3:6]}-{phone[6:]})'
            else:
                display_name = f'{title} ({key_type})'
            suffix = hashlib.sha256(repr(key).encode('utf-8')).hexdigest()[:8]
            filename = f'{filename[:100]}_{suffix}'

        if filename.casefold() in used_filenames:
            suffix = hashlib.sha256(repr(key).encode('utf-8')).hexdigest()[:12]
            filename = f'{filename[:95]}_{suffix}'
        used_filenames.add(filename.casefold())
        entries.append((key, display_name, filename))

    return entries


def summarize_messages(messages):
    dates = [
        str(message.get('date'))
        for message in messages
        if message.get('date') and message.get('date') != 'Unknown'
    ]
    return {
        'messages': len(messages),
        'attachments': sum(len(message.get('attachments', [])) for message in messages),
        'first_date': min(dates) if dates else '—',
        'last_date': max(dates) if dates else '—',
    }


def build_index(conversations, output_dir, overall_stats):
    index_path = os.path.join(output_dir, 'index.html')
    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <title>iMessage Conversations</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; padding: 0; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1400px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #ffffff; transition: background .15s, color .15s, border-color .15s; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 48px); margin-bottom: 26px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .eyebrow { margin: 0 0 10px; color: #bfdbfe; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }',
        '    h1 { margin: 0; font-size: clamp(30px, 4vw, 42px); letter-spacing: -.03em; }',
        '    .page-header p:last-child { max-width: 680px; margin: 10px 0 0; color: #e0f2fe; font-size: 16px; line-height: 1.55; }',
        '    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }',
        '    .stat { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px #0001; }',
        '    .stat strong { display: block; font-size: 22px; color: #111; }',
        '    .stat span { color: #666; font-size: 13px; }',
        '    .search-link { display: inline-flex; align-items: center; gap: 8px; margin-top: 8px; padding: 12px 18px; border-radius: 12px; color: #fff; background: #2563eb; text-decoration: none; font-size: 15px; font-weight: 600; box-shadow: 0 5px 14px #2563eb33; transition: background .15s, transform .15s; }',
        '    .search-link:hover { background: #1d4ed8; transform: translateY(-1px); }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage archive</p>',
        '      <h1>Your conversations</h1>',
        '      <p>A snapshot of your message history. Search the archive to find a specific conversation.</p>',
        '    </header>',
        '    <main>',
        '    <section class="stats" aria-label="Database statistics">',
        f'      <div class="stat"><strong>{overall_stats["conversations"]:,}</strong><span>Conversations</span></div>',
        f'      <div class="stat"><strong>{overall_stats["messages"]:,}</strong><span>Messages</span></div>',
        f'      <div class="stat"><strong>{overall_stats["attachments"]:,}</strong><span>Attachments</span></div>',
        f'      <div class="stat"><strong>{html.escape(overall_stats["first_date"])}</strong><span>First message</span></div>',
        f'      <div class="stat"><strong>{html.escape(overall_stats["last_date"])}</strong><span>Last message</span></div>',
        '    </section>',
        '    <a class="search-link" href="search.html">Search conversations <span aria-hidden="true">→</span></a>',
        '    </main>',
        '  </div>',
        '</body>',
        '</html>'
    ]

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return index_path


def build_search_index(conversations, output_dir):
    search_path = os.path.join(output_dir, 'search.html')
    conv_list = sorted(conversations, key=lambda entry: entry[0].lower())

    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <title>Search iMessage Conversations</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; padding: 0; }',
        '    body { min-height: 100vh; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1800px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #ffffff; transition: background .15s, color .15s, border-color .15s; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 48px); margin-bottom: 26px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .eyebrow { margin: 0 0 10px; color: #bfdbfe; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }',
        '    h1 { margin: 0; font-size: clamp(30px, 4vw, 42px); letter-spacing: -.03em; }',
        '    .page-header p:last-child { max-width: 680px; margin: 10px 0 0; color: #e0f2fe; font-size: 16px; line-height: 1.55; }',
        '    .search-box { margin-bottom: 18px; }',
        '    input { width: 100%; padding: 14px 16px; font-size: 16px; border: 1px solid #cbd5e1; border-radius: 12px; box-sizing: border-box; box-shadow: 0 2px 8px #0f172a0a; }',
        '    input:focus { outline: 3px solid #93c5fd; border-color: #2563eb; }',
        '    .results-count { font-size: 14px; color: #64748b; margin-bottom: 12px; }',
        '    .table-wrap { overflow-x: auto; border-radius: 14px; box-shadow: 0 4px 18px #0f172a0d; }',
        '    table { width: 100%; border-collapse: collapse; background: white; }',
        '    th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e5ea; }',
        '    th { background: #f1f5f9; color: #475569; font-size: 13px; white-space: nowrap; }',
        '    th button { border: 0; padding: 0; background: none; color: inherit; font: inherit; font-weight: 600; cursor: pointer; }',
        '    th button:hover { color: #2563eb; }',
        '    .sort-indicator { margin-left: 4px; }',
        '    td { font-size: 14px; color: #334155; vertical-align: top; }',
        '    td a { color: #2563eb; text-decoration: none; font-size: 16px; font-weight: 600; }',
        '    td a:hover { text-decoration: underline; }',
        '    td.participants { min-width: 220px; color: #64748b; line-height: 1.5; }',
        '    tbody tr:hover { background: #f8fafc; }',
        '    tr:last-child td { border-bottom: 0; }',
        '    .hidden { display: none; }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } th, td { padding: 9px 7px; font-size: 12px; } td a { font-size: 13px; } td.participants { min-width: 160px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage archive</p>',
        '      <h1>Find a conversation</h1>',
        '      <p>Search, sort, and explore your conversations and message history.</p>',
        '    </header>',
        '    <div class="search-box">',
        '      <input type="text" id="searchInput" placeholder="Search for a person or name...">',
        '    </div>',
        '    <div class="results-count"><span id="resultCount">Showing all</span> conversations</div>',
        '    <div class="table-wrap"><table><thead><tr>',
        '      <th scope="col"><button type="button" data-sort-key="name" aria-sort="none">Conversation <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="participants" aria-sort="none">People in group <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="messages" aria-sort="none">Messages <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="attachments" aria-sort="none">Attachments <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="first-date" aria-sort="none">First message <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="last-date" aria-sort="none">Last message <span class="sort-indicator"></span></button></th>',
        '    </tr></thead>',
        '    <tbody id="conversationList">',
    ]

    for display_name, filename, messages in conv_list:
        stats = summarize_messages(messages)
        is_group = any(
            isinstance(message.get('chat_id'), tuple) and message['chat_id'][0] == 'group'
            for message in messages
        )
        participant_names = sorted({
            name
            for message in messages
            for name in message.get('group_participants', [])
        }, key=str.casefold) if is_group else []
        participants_text = ', '.join(participant_names)
        searchable_name = f'{display_name} {participants_text}'.lower()
        content.append(
            f'      <tr class="conv-item" data-name="{html.escape(searchable_name, quote=True)}" '
            f'data-sort-name="{html.escape(display_name.lower())}" '
            f'data-sort-participants="{html.escape(participants_text.lower(), quote=True)}" '
            f'data-sort-messages="{stats["messages"]}" data-sort-attachments="{stats["attachments"]}" '
            f'data-sort-first-date="{html.escape(stats["first_date"])}" '
            f'data-sort-last-date="{html.escape(stats["last_date"])}">'
            f'<td><a href="{filename}.html">{html.escape(display_name)}</a></td>'
            f'<td class="participants">{html.escape(participants_text) if participants_text else "—"}</td>'
            f'<td>{stats["messages"]:,}</td><td>{stats["attachments"]:,}</td>'
            f'<td>{html.escape(stats["first_date"])}</td><td>{html.escape(stats["last_date"])}</td></tr>'
        )

    content.extend([
        '    </tbody></table></div>',
        '    <script>',
        '      const searchInput = document.getElementById("searchInput");',
        '      const conversationList = document.getElementById("conversationList");',
        '      const conversationItems = conversationList.querySelectorAll(".conv-item");',
        '      const resultCount = document.getElementById("resultCount");',
        '      const totalConversations = conversationItems.length;',
        '      const sortButtons = document.querySelectorAll("th button[data-sort-key]");',
        '      let activeSortKey = "";',
        '      let sortAscending = true;',
        '      ',
        '      sortButtons.forEach(function(button) {',
        '        button.addEventListener("click", function() {',
        '          const sortKey = this.getAttribute("data-sort-key");',
        '          if (activeSortKey === sortKey) {',
        '            sortAscending = !sortAscending;',
        '          } else {',
        '            activeSortKey = sortKey;',
        '            sortAscending = true;',
        '          }',
        '          sortButtons.forEach(function(sortButton) {',
        '            const isActive = sortButton === button;',
        '            sortButton.setAttribute("aria-sort", isActive ? (sortAscending ? "ascending" : "descending") : "none");',
        '            sortButton.querySelector(".sort-indicator").textContent = isActive ? (sortAscending ? "▲" : "▼") : "";',
        '          });',
        '          const sortAttribute = "data-sort-" + sortKey;',
        '          const sortedItems = Array.from(conversationItems).sort(function(left, right) {',
        '            const leftValue = left.getAttribute(sortAttribute) || "";',
        '            const rightValue = right.getAttribute(sortAttribute) || "";',
        '            let comparison;',
        '            if (sortKey === "messages" || sortKey === "attachments") {',
        '              comparison = Number(leftValue) - Number(rightValue);',
        '            } else {',
        '              comparison = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });',
        '            }',
        '            return (sortAscending ? comparison : -comparison) ||',
        '              left.getAttribute("data-sort-name").localeCompare(right.getAttribute("data-sort-name"));',
        '          });',
        '          sortedItems.forEach(function(item) { conversationList.appendChild(item); });',
        '        });',
        '      });',
        '      ',
        '      searchInput.addEventListener("input", function() {',
        '        const searchTerm = this.value.toLowerCase().trim();',
        '        let visibleCount = 0;',
        '        ',
        '        conversationItems.forEach(function(item) {',
        '          const name = item.getAttribute("data-name");',
        '          if (searchTerm === "" || name.includes(searchTerm)) {',
        '            item.classList.remove("hidden");',
        '            visibleCount++;',
        '          } else {',
        '            item.classList.add("hidden");',
        '          }',
        '        });',
        '        ',
        '        if (searchTerm === "") {',
        '          resultCount.textContent = "Showing all";',
        '        } else {',
        '          resultCount.textContent = "Showing " + visibleCount + " of " + totalConversations;',
        '        }',
        '      });',
        '    </script>',
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(search_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return search_path


def main():
    parser = argparse.ArgumentParser(description='Export iPhone SMS/Attachment databases as styled iMessage HTML conversations.')
    parser.add_argument('--sms-db', required=False, help='Path to the SMS SQLite database (sms.db)')
    parser.add_argument('--attachment-db', help='Path to the attachment SQLite database (if separate)')
    parser.add_argument('--attachment-folder', help='Base folder path where attachment files are located')
    parser.add_argument(
        '--address-book-db',
        default=r'C:\Users\PC\Files\___Phil_iphone_convo\testinggg\HomeDomain\Library\AddressBook\AddressBook.sqlitedb',
        help='Path to the Address Book SQLite database',
    )
    parser.add_argument('--output-dir', default='imessage_html', help='Directory where HTML output will be written')
    args = parser.parse_args()

    # Hardcoded paths
    args.sms_db = "C:\\Users\\PC\\Files\\___Phil_iphone_convo\\test2026\\HomeDomain\\Library\\SMS\\sms.db"
    args.attachment_folder = "C:\\Users\\PC\\Files\\___Phil_iphone_convo\\test2026\\MediaDomain\\"

    contacts = fetch_contacts(args.address_book_db)

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Use a new cache version because message text now falls back to attributedBody.
    cache_path = os.path.join(output_dir, 'sms_messages_v3.pkl')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as f:
                messages, chat_names = pickle.load(f)
            print(f'Loaded cached messages from: {cache_path}')
        except Exception as e:
            print(f'Failed to load cache ({cache_path}), refetching: {e}')
            messages, chat_names = fetch_sms_messages(args.sms_db)
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump((messages, chat_names), f)
            except Exception:
                pass
    else:
        messages, chat_names = fetch_sms_messages(args.sms_db)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump((messages, chat_names), f)
        except Exception:
            pass
    attachments = {}
    if args.attachment_db:
        attachments = fetch_attachments(args.attachment_db)
    else:
        attachments = fetch_attachments(args.sms_db)

    attachments = normalize_attachment_paths(attachments, args.attachment_folder)
    messages = attach_to_messages(messages, attachments)
    apply_contact_names(messages, contacts)
    group_participants = fetch_group_participants(args.sms_db, contacts)
    for message in messages:
        message['group_participants'] = group_participants.get(message['chat_id'], [])
    for phone_number, contact_name in contacts.items():
        chat_names.setdefault(('phone', phone_number), contact_name)
    conversations, id_to_sender = group_messages_by_conversation(messages, chat_names)

    if not conversations:
        raise ValueError('No conversations were found in the provided database files.')

    total_convs = len(conversations)
    print(f'\nExporting {total_convs} conversations...\n')
    print(f'Conversation ID to Sender Mapping:\n{id_to_sender}\n')

    conversion_failures = {}
    conversation_entries = build_conversation_entries(conversations)
    index_entries = []
    for idx, (conv_key, conv_name, output_filename) in enumerate(conversation_entries, 1):
        conv_data = conversations[conv_key]
        num_msgs = len(conv_data['messages'])
        sender_phone = id_to_sender.get(conv_key, 'Unknown')
        build_html(
            conv_name,
            conv_data['messages'],
            output_dir,
            args.attachment_folder,
            conversion_failures,
            output_filename,
        )
        index_entries.append((conv_name, output_filename, conv_data['messages']))
        print(f'[{idx}/{total_convs}] Created: {conv_name} ({num_msgs} messages) - Sender: {sender_phone}')

    overall_stats = summarize_messages(messages)
    overall_stats['conversations'] = total_convs
    build_index(index_entries, output_dir, overall_stats)
    build_search_index(index_entries, output_dir)

    if conversion_failures:
        print(f'\nAttachment conversion failures: {len(conversion_failures)}')

    print(f'\nExport complete: {output_dir}')


if __name__ == '__main__':
    main()
