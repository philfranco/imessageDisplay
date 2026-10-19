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
    date_col = choose_column(['date', 'date_sent', 'timestamp'], message_cols)
    is_from_me_col = choose_column(['is_from_me', 'is_from_me', 'is_from_me', 'sender', 'is_from_me'], message_cols)
    handle_id_col = choose_column(['handle_id', 'handleid', 'ZFROMHANDLE', 'ZHANDLE'], message_cols)

    handle_cols = get_columns(conn, handle_table) if handle_table else []
    handle_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK'], handle_cols)
    handle_name_col = choose_column(['id', 'address', 'username', 'phone_number'], handle_cols)

    query = [f'm.{msg_pk} AS msg_id']
    if text_col:
        query.append(f'm.{text_col} AS text')
    query.append(f'm.{date_col} AS date')
    query.append(f'm.{is_from_me_col} AS is_from_me')
    if handle_id_col:
        query.append(f'm.{handle_id_col} AS handle_id')
    if handle_table and handle_pk and handle_name_col and handle_id_col:
        query.append(f'h.{handle_name_col} AS handle_name')
    sql = f"SELECT {', '.join(query)} FROM {message_table} m"
    if handle_table and handle_pk and handle_name_col and handle_id_col:
        sql += f" LEFT JOIN {handle_table} h ON m.{handle_id_col} = h.{handle_pk}"
    if date_col:
        sql += f" ORDER BY m.{date_col} ASC"

    messages = []
    for row in conn.execute(sql):
        sender = 'Me' if bool(row['is_from_me']) else (row_value(row, 'handle_name') or row_value(row, 'handle_id') or 'Unknown')
        messages.append({
            'id': row['msg_id'],
            'text': row['text'],
            'date': apple_timestamp_to_iso(row['date']),
            'is_from_me': bool(row['is_from_me']),
            'sender': sender,
            'handle_id': row_value(row, 'handle_id'),
            'chat_id': None,
            'attachments': []
        })

    chat_names = {}
    if chat_table and join_table:
        chat_cols = get_columns(conn, join_table)
        chat_msg_col = choose_column(['message_id', 'messageid', 'ZMESSAGE'], chat_cols)
        chat_id_col = choose_column(['chat_id', 'chatid', 'ZCHAT'], chat_cols)
        if chat_msg_col and chat_id_col:
            for row in conn.execute(f"SELECT {chat_msg_col} AS msg_id, {chat_id_col} AS chat_id FROM {join_table}"):
                for msg in messages:
                    if msg['id'] == row['msg_id']:
                        msg['chat_id'] = row['chat_id']
                        break

        chat_cols = get_columns(conn, chat_table)
        chat_pk = choose_column(['ROWID', '_ROWID_', 'Z_PK'], chat_cols)
        chat_name_col = choose_column(['display_name', 'chat_identifier', 'name'], chat_cols)
        if chat_pk and chat_name_col:
            for row in conn.execute(f"SELECT {chat_pk} AS chat_id, {chat_name_col} AS name FROM {chat_table}"):
                chat_names[row['chat_id']] = row['name']

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
        key = msg['chat_id'] if msg['chat_id'] is not None else msg['handle_id'] or 'Unknown'
        if key is None:
            key = 'Unknown'
        if conversations[key]['name'] is None:
            if msg['chat_id'] is not None:
                conversations[key]['name'] = chat_names.get(msg['chat_id']) or f'Chat_{msg["chat_id"]}'
                id_to_sender[key] = str(msg['sender'])
            else:
                conversations[key]['name'] = str(msg['sender'])
                # Extract phone number from sender (handle_id is typically the phone number)
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


def build_html(conversation_name, messages, output_dir, attachment_folder=None, conversion_failures=None):
    if conversion_failures is None:
        conversion_failures = {}

    safe_name = sanitize_filename(conversation_name)
    filename = os.path.join(output_dir, f'{safe_name}.html')

    html_content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        f'  <title>{html.escape(conversation_name)}</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; background: #f2f2f7; }',
        '    .wrapper { max-width: 780px; margin: 0 auto; padding: 24px; }',
        '    h1 { font-size: 24px; margin-bottom: 16px; color: #111; }',
        '    .message { display: flex; margin-bottom: 14px; }',
        '    .message.me { justify-content: flex-end; }',
        '    .bubble { max-width: 70%; padding: 12px 14px; border-radius: 20px; line-height: 1.5; position: relative; }',
        '    .bubble.me { background: #007aff; color: white; border-bottom-right-radius: 6px; border-bottom-left-radius: 20px; }',
        '    .bubble.other { background: #e5e5ea; color: black; border-bottom-left-radius: 6px; border-bottom-right-radius: 20px; }',
        '    .meta { font-size: 12px; color: #555; margin-top: 6px; }',
        '    .attachment { margin-top: 8px; font-size: 13px; color: #333; }',
        '    .attachment img { max-width: 100%; border-radius: 12px; margin-top: 4px; }',
        '    .attachment video { max-width: 100%; max-height: 480px; border-radius: 12px; margin-top: 4px; }',
        '    .attachment-meta { font-size: 11px; color: #666; margin-top: 4px; }',
        '    .index-link { display: inline-block; margin-bottom: 16px; color: #007aff; text-decoration: none; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        f'    <a class="index-link" href="index.html">← Back to all conversations</a>',
        f'    <h1>{html.escape(conversation_name)}</h1>',
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
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_content))

    return filename


def build_index(conversations, output_dir):
    index_path = os.path.join(output_dir, 'index.html')
    items = []
    for conv in sorted(conversations, key=lambda k: k.lower()):
        safe_name = sanitize_filename(conv)
        items.append(f'      <li><a href="{safe_name}.html">{html.escape(conv)}</a></li>')

    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <title>iMessage Conversations</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; padding: 0; }',
        '    .wrapper { max-width: 780px; margin: 0 auto; padding: 24px; }',
        '    h1 { font-size: 28px; margin-bottom: 12px; }',
        '    ul { list-style: none; padding: 0; }',
        '    li { margin-bottom: 10px; }',
        '    a { color: #007aff; text-decoration: none; font-size: 18px; }',
        '    a:hover { text-decoration: underline; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <h1>iMessage Conversations</h1>',
        '    <p><a href="__search.html" style="color: #007aff; text-decoration: none;">Search conversations →</a></p>',
        '    <ul>',
        *items,
        '    </ul>',
        '  </div>',
        '</body>',
        '</html>'
    ]

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return index_path


def build_search_index(conversations, output_dir):
    search_path = os.path.join(output_dir, '__search.html')
    conv_list = sorted(conversations, key=lambda k: k.lower())

    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <title>Search iMessage Conversations</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; padding: 0; }',
        '    .wrapper { max-width: 780px; margin: 0 auto; padding: 24px; }',
        '    h1 { font-size: 28px; margin-bottom: 12px; }',
        '    .search-box { margin-bottom: 24px; }',
        '    input { width: 100%; padding: 12px; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; }',
        '    .results-count { font-size: 14px; color: #666; margin-bottom: 12px; }',
        '    ul { list-style: none; padding: 0; }',
        '    li { margin-bottom: 10px; }',
        '    a { color: #007aff; text-decoration: none; font-size: 18px; }',
        '    a:hover { text-decoration: underline; }',
        '    .hidden { display: none; }',
        '    .index-link { display: inline-block; margin-bottom: 16px; color: #007aff; text-decoration: none; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <a class="index-link" href="index.html">← Back to all conversations</a>',
        '    <h1>Search Conversations</h1>',
        '    <div class="search-box">',
        '      <input type="text" id="searchInput" placeholder="Search for a person or name...">',
        '    </div>',
        '    <div class="results-count"><span id="resultCount">Showing all</span> conversations</div>',
        '    <ul id="conversationList">',
    ]

    for conv in conv_list:
        safe_name = sanitize_filename(conv)
        content.append(f'      <li class="conv-item" data-name="{html.escape(conv.lower())}"><a href="{safe_name}.html">{html.escape(conv)}</a></li>')

    content.extend([
        '    </ul>',
        '    <script>',
        '      const searchInput = document.getElementById("searchInput");',
        '      const conversationList = document.getElementById("conversationList");',
        '      const conversationItems = conversationList.querySelectorAll(".conv-item");',
        '      const resultCount = document.getElementById("resultCount");',
        '      const totalConversations = conversationItems.length;',
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

    #C:\Users\PC\Files\___Phil_iphone_convo\test2026\MediaDomain\Library\SMS\Attachments\e1\01\91891B4B-499B-4F0D-8335-B1944D308405
    #C:\Users\PC\Files\___Phil_iphone_convo\test2026\MediaDomain\Library\SMS\Attachments\e1\01\91891B4B-499B-4F0D-8335-B1944D308405\IMG_0838.PNG

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Cache path for fetched messages to speed up repeated runs during testing
    cache_path = os.path.join(output_dir, 'sms_messages.pkl')
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
    conversations, id_to_sender = group_messages_by_conversation(messages, chat_names)

    if not conversations:
        raise ValueError('No conversations were found in the provided database files.')

    total_convs = len(conversations)
    print(f'\nExporting {total_convs} conversations...\n')
    print(f'Conversation ID to Sender Mapping:\n{id_to_sender}\n')

    conversion_failures = {}
    for idx, (conv_key, conv_data) in enumerate(conversations.items(), 1):
        conv_name = conv_data['name'] or str(conv_key)
        num_msgs = len(conv_data['messages'])
        sender_phone = id_to_sender.get(conv_key, 'Unknown')
        html_file = build_html(
            conv_name,
            conv_data['messages'],
            output_dir,
            args.attachment_folder,
            conversion_failures,
        )
        print(f'[{idx}/{total_convs}] Created: {conv_name} ({num_msgs} messages) - Sender: {sender_phone}')

    build_index([conv_data['name'] or str(key) for key, conv_data in conversations.items()], output_dir)
    build_search_index([conv_data['name'] or str(key) for key, conv_data in conversations.items()], output_dir)

    if conversion_failures:
        print(f'\nAttachment conversion failures: {len(conversion_failures)}')

    print(f'\nExport complete: {output_dir}')


if __name__ == '__main__':
    main()


# C:\Users\PC\Files\___Phil_iphone_convo\test2026\HomeDomain\Library\SMS\sms.db
# C:\Users\PC\Files\___Phil_iphone_convo\test2026\MediaDomain\Library\SMS\Attachments\attachment.db