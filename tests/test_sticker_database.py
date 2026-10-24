import os
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from export_media import format_attachment_html
from sticker_database import (
    extract_sticker_previews,
    resolve_missing_sticker_previews,
    sticker_identifier_key,
)
from sms_database import fetch_attachments


class StickerDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = self.temporary_dir.name
        self.database_path = os.path.join(self.root, 'stickers.stickerdb')
        self.preview_dir = os.path.join(self.root, 'previews')
        self.identifier = bytes.fromhex('64f5222f73da4311a525bc497cf7bf78')
        self.png_data = b'\x89PNG\r\n\x1a\n' + b'test image data'
        self.heic_identifier = bytes.fromhex('6d4ff3c5c20a478c99862fb6399b7230')
        self.heic_data = b'\x00\x00\x00\x18ftypheic' + b'test image data'

        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                'CREATE TABLE ZMANAGEDSTICKER ('
                'Z_PK INTEGER PRIMARY KEY, ZIDENTIFIER BLOB)'
            )
            connection.execute(
                'CREATE TABLE ZMANAGEDREPRESENTATION ('
                'Z_PK INTEGER PRIMARY KEY, ZSTICKER INTEGER, ZINDEX INTEGER, '
                'ZROLE TEXT, ZUTI TEXT, ZDATA BLOB)'
            )
            connection.execute(
                'INSERT INTO ZMANAGEDSTICKER (Z_PK, ZIDENTIFIER) VALUES (?, ?)',
                (1, self.identifier),
            )
            connection.execute(
                'INSERT INTO ZMANAGEDSTICKER (Z_PK, ZIDENTIFIER) VALUES (?, ?)',
                (2, self.heic_identifier),
            )
            connection.execute(
                'INSERT INTO ZMANAGEDREPRESENTATION '
                '(Z_PK, ZSTICKER, ZINDEX, ZROLE, ZUTI, ZDATA) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (
                    1,
                    1,
                    0,
                    'com.apple.stickers.role.keyboard',
                    'public.png',
                    self.png_data,
                ),
            )
            connection.execute(
                'INSERT INTO ZMANAGEDREPRESENTATION '
                '(Z_PK, ZSTICKER, ZINDEX, ZROLE, ZUTI, ZDATA) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (
                    2,
                    2,
                    0,
                    'com.apple.stickers.role.still',
                    'public.heic',
                    self.heic_data,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_extracts_embedded_png_and_indexes_by_sticker_uuid(self):
        previews = extract_sticker_previews(self.database_path, self.preview_dir)

        key = self.identifier.hex()
        heic_key = self.heic_identifier.hex()
        self.assertEqual(set(previews), {key, heic_key})
        with open(previews[key], 'rb') as preview:
            self.assertEqual(preview.read(), self.png_data)
        self.assertTrue(previews[heic_key].endswith(f'{heic_key}.heic'))
        with open(previews[heic_key], 'rb') as preview:
            self.assertEqual(preview.read(), self.heic_data)
        self.assertEqual(
            sticker_identifier_key('64F5222F-73DA-4311-A525-BC497CF7BF78.png'),
            key,
        )

    def test_uses_library_preview_only_when_message_cache_is_missing(self):
        previews = extract_sticker_previews(self.database_path, self.preview_dir)
        key = self.identifier.hex()
        cache_path = os.path.join(self.root, 'sticker-cache.png')
        attachments = {
            1: [{
                'filename': '~/Library/SMS/StickerCache/missing.png',
                'file_path': os.path.join(self.root, 'missing-cache.png'),
                'mime_type': 'image/png',
                'is_sticker': True,
                'sticker_user_info': {
                    'sid': '64F5222F-73DA-4311-A525-BC497CF7BF78'
                },
            }],
            2: [{
                'filename': 'present.png',
                'file_path': cache_path,
                'mime_type': 'image/png',
                'is_sticker': True,
                'sticker_user_info': {
                    'sid': '64F5222F-73DA-4311-A525-BC497CF7BF78'
                },
            }],
        }
        with open(cache_path, 'wb') as cache:
            cache.write(b'cached image')

        resolve_missing_sticker_previews(attachments, previews)

        self.assertEqual(attachments[1][0]['file_path'], previews[key])
        self.assertEqual(attachments[1][0]['filename'], f'{key}.png')
        self.assertEqual(attachments[1][0]['mime_type'], 'image/png')
        self.assertEqual(attachments[2][0]['file_path'], cache_path)
        markup = format_attachment_html(attachments[1][0], self.root)
        self.assertIn(f'<img loading="lazy" src="{Path(previews[key]).as_uri()}"', markup)

    def test_fetch_attachments_decodes_sticker_metadata_for_html_fallback(self):
        sms_path = os.path.join(self.root, 'sms.db')
        connection = sqlite3.connect(sms_path)
        try:
            connection.execute(
                'CREATE TABLE attachment ('
                'ROWID INTEGER PRIMARY KEY, filename TEXT, mime_type TEXT, '
                'is_sticker INTEGER, sticker_user_info BLOB)'
            )
            connection.execute(
                'CREATE TABLE message_attachment_join ('
                'message_id INTEGER, attachment_id INTEGER)'
            )
            connection.execute(
                'INSERT INTO attachment VALUES (?, ?, ?, ?, ?)',
                (
                    9,
                    '~/Library/SMS/StickerCache/missing.png',
                    'image/png',
                    1,
                    plistlib.dumps({
                        'sid': '64F5222F-73DA-4311-A525-BC497CF7BF78'
                    }),
                ),
            )
            connection.execute(
                'INSERT INTO message_attachment_join VALUES (?, ?)',
                (12, 9),
            )
            connection.commit()
        finally:
            connection.close()

        attachments = fetch_attachments(sms_path)

        self.assertEqual(attachments[12][0]['is_sticker'], True)
        self.assertEqual(
            attachments[12][0]['sticker_user_info'],
            {'sid': '64F5222F-73DA-4311-A525-BC497CF7BF78'},
        )


if __name__ == '__main__':
    unittest.main()
