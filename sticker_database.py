"""Extract static sticker previews embedded in Apple's sticker library database."""

import os
import re
import sqlite3
import uuid


_STICKER_TABLE = 'ZMANAGEDSTICKER'
_REPRESENTATION_TABLE = 'ZMANAGEDREPRESENTATION'
_UUID_PATTERN = re.compile(
    r'(?i)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})'
)


def sticker_identifier_key(value):
    if not value:
        return None
    match = _UUID_PATTERN.search(str(value))
    if not match:
        return None
    try:
        return uuid.UUID(match.group(1)).hex
    except ValueError:
        return None


def extract_sticker_previews(database_path, output_dir):
    """Write each sticker's preferred PNG preview, or still HEIC fallback, to disk."""
    if not os.path.isfile(database_path):
        raise FileNotFoundError(f'Sticker library database not found: {database_path}')

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0].casefold()
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {
            _STICKER_TABLE.casefold(),
            _REPRESENTATION_TABLE.casefold(),
        }.issubset(tables):
            raise ValueError(
                f'Sticker library database has an unsupported schema: {database_path}'
            )

        sticker_columns = {
            row[1].casefold()
            for row in connection.execute(f'PRAGMA table_info("{_STICKER_TABLE}")')
        }
        representation_columns = {
            row[1].casefold()
            for row in connection.execute(
                f'PRAGMA table_info("{_REPRESENTATION_TABLE}")'
            )
        }
        if not {'z_pk', 'zidentifier'}.issubset(sticker_columns) or not {
            'zsticker',
            'zindex',
            'zrole',
            'zuti',
            'zdata',
        }.issubset(representation_columns):
            raise ValueError(
                f'Sticker library database has an unsupported schema: {database_path}'
            )

        rows = connection.execute(
            'SELECT sticker.ZIDENTIFIER, representation.ZUTI, representation.ZDATA '
            f'FROM "{_STICKER_TABLE}" AS sticker '
            f'JOIN "{_REPRESENTATION_TABLE}" AS representation '
            'ON representation.ZSTICKER = sticker.Z_PK '
            "WHERE (representation.ZROLE = 'com.apple.stickers.role.keyboard' "
            "AND representation.ZUTI = 'public.png') "
            "OR (representation.ZROLE = 'com.apple.stickers.role.still' "
            "AND representation.ZUTI = 'public.heic') "
            'ORDER BY sticker.Z_PK, '
            "CASE WHEN representation.ZUTI = 'public.png' THEN 0 ELSE 1 END, "
            'representation.ZINDEX'
        )

        previews = {}
        os.makedirs(output_dir, exist_ok=True)
        for identifier, uti, data in rows:
            if not isinstance(identifier, bytes) or len(identifier) != 16 or not data:
                continue
            key = identifier.hex()
            if key in previews:
                continue

            extension = '.png' if uti == 'public.png' else '.heic'
            if extension == '.png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError(
                    f'Sticker {key} has invalid PNG preview data in {database_path}'
                )
            if extension == '.heic' and b'ftyp' not in data[:16]:
                raise ValueError(
                    f'Sticker {key} has invalid HEIC preview data in {database_path}'
                )

            preview_path = os.path.join(output_dir, f'{key}{extension}')
            with open(preview_path, 'wb') as preview_file:
                preview_file.write(data)
            previews[key] = preview_path

        return previews
    finally:
        connection.close()


def resolve_missing_sticker_previews(attachments, previews):
    """Replace missing sticker-cache paths with matching library previews."""
    if not previews:
        return attachments

    for attachment_list in attachments.values():
        for attachment in attachment_list:
            sticker_info = attachment.get('sticker_user_info')
            if not isinstance(sticker_info, dict):
                continue
            preview_key = sticker_identifier_key(sticker_info.get('sid'))
            preview_path = previews.get(preview_key)
            if not preview_path or os.path.isfile(attachment.get('file_path') or ''):
                continue

            attachment['file_path'] = preview_path
            attachment['filename'] = os.path.basename(preview_path)
            attachment['mime_type'] = (
                'image/heic' if preview_path.lower().endswith('.heic') else 'image/png'
            )

    return attachments
