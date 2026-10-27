import glob
import os
import re
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from iphone_imessage_exporter import export_messages, regenerate_html
from message_archive import ARCHIVE_FILENAME, merge_messages
from sms_database import detect_owner_phone, fetch_sms_messages


def message(guid, text, date, chat_id=('phone', '15551234567'), **extra):
    result = {
        'id': extra.pop('id', 1),
        'guid': guid,
        'text': text,
        'date': date,
        'is_from_me': False,
        'sender': 'Alex',
        'handle_address': '+15551234567',
        'handle_id': 1,
        'chat_id': chat_id,
        'attachments': [],
    }
    result.update(extra)
    return result


class MessageArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temporary_dir.name

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_reimported_guid_updates_without_duplicate(self):
        first = message('GUID-1', 'hello', '2025-01-01 10:00:00', id=13)
        second = message('GUID-1', 'hello edited', '2025-01-01 10:00:00', id=87)

        messages, _, imported, total = merge_messages(self.output_dir, [first], {})
        messages, _, imported_again, total_again = merge_messages(self.output_dir, [second], {})

        self.assertEqual((imported, total), (1, 1))
        self.assertEqual((imported_again, total_again), (1, 1))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['text'], 'hello edited')
        self.assertEqual(messages[0]['chat_id'], ('phone', '15551234567'))

    def test_disappeared_messages_and_old_attachments_are_retained(self):
        old = message(
            'GUID-1',
            'older',
            '2025-01-01 10:00:00',
            attachments=[{'id': 9, 'filename': 'photo.jpg'}],
        )
        newer = message('GUID-2', 'newer', '2025-01-02 10:00:00')

        merge_messages(self.output_dir, [old, newer], {})
        messages, _, _, total = merge_messages(
            self.output_dir,
            [message('GUID-2', 'newer', '2025-01-02 10:00:00')],
            {},
        )

        by_guid = {item['guid']: item for item in messages}
        self.assertEqual(total, 2)
        self.assertEqual(set(by_guid), {'GUID-1', 'GUID-2'})
        self.assertEqual(by_guid['GUID-1']['attachments'], [{'id': 9, 'filename': 'photo.jpg'}])
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, ARCHIVE_FILENAME)))

    def test_fallback_key_preserves_identical_messages_and_deduplicates_reimports(self):
        duplicate_1 = message(None, 'same', '2025-01-01 10:00:00', id=1)
        duplicate_2 = message(None, 'same', '2025-01-01 10:00:00', id=2)
        merge_messages(self.output_dir, [duplicate_1, duplicate_2], {})

        messages, _, _, total = merge_messages(
            self.output_dir,
            [
                message(None, 'same', '2025-01-01 10:00:00', id=44),
                message(None, 'same', '2025-01-01 10:00:00', id=45),
            ],
            {},
        )

        self.assertEqual(total, 2)
        self.assertEqual(len(messages), 2)

    def test_conversation_names_survive_imports_that_omit_them(self):
        key = ('group', 'chat123')
        merge_messages(self.output_dir, [message('GUID-1', 'hello', '2025-01-01 10:00:00', key)], {key: 'Family'})

        _, names, _, _ = merge_messages(
            self.output_dir,
            [message('GUID-2', 'later', '2025-01-02 10:00:00', key)],
            {},
        )

        self.assertEqual(names[key], 'Family')

    def test_archive_messages_are_returned_in_chronological_order(self):
        merge_messages(
            self.output_dir,
            [
                message('GUID-2', 'later', '2025-01-02 10:00:00'),
                message('GUID-1', 'earlier', '2025-01-01 10:00:00'),
            ],
            {},
        )

        messages, _, _, _ = merge_messages(self.output_dir, [], {})

        self.assertEqual([item['guid'] for item in messages], ['GUID-1', 'GUID-2'])

    def test_detect_owner_phone_from_self_only_chat(self):
        messages = [
            message('GUID-1', 'note to self', '2025-01-01 10:00:00', ('phone', '15551234567'),
                    is_from_me=True, sender='Me'),
            message('GUID-2', 'from alex', '2025-01-02 10:00:00', ('phone', '15559876543')),
        ]
        self.assertEqual(detect_owner_phone(messages), '5551234567')

    def test_detect_owner_phone_ignores_mixed_chats(self):
        messages = [
            message('GUID-1', 'from alex', '2025-01-01 10:00:00', ('phone', '15551234567')),
            message('GUID-2', 'my reply', '2025-01-02 10:00:00', ('phone', '15551234567'),
                    is_from_me=True, sender='Me'),
        ]
        self.assertIsNone(detect_owner_phone(messages))

    def test_detect_owner_phone_falls_back_to_shared_outgoing_handle(self):
        messages = [
            message('GUID-1', 'hi alex', '2025-01-01 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-2', 'from alex', '2025-01-02 10:00:00', ('phone', '15559876543'),
                    handle_address='+15559876543'),
            message('GUID-3', 'hi sam', '2025-01-03 10:00:00', ('phone', '15558675309'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-4', 'from sam', '2025-01-04 10:00:00', ('phone', '15558675309'),
                    handle_address='+15558675309'),
        ]
        self.assertEqual(detect_owner_phone(messages), '5551234567')

    def test_detect_owner_phone_fallback_needs_several_conversations(self):
        messages = [
            message('GUID-1', 'hi alex', '2025-01-01 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-2', 'hi alex again', '2025-01-02 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
        ]
        self.assertIsNone(detect_owner_phone(messages))

    def test_detect_owner_phone_fallback_stays_silent_on_ties(self):
        messages = [
            message('GUID-1', 'hi alex', '2025-01-01 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-2', 'hi sam', '2025-01-02 10:00:00', ('phone', '15558675309'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-3', 'hi alex again', '2025-01-03 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15552223333'),
            message('GUID-4', 'hi sam again', '2025-01-04 10:00:00', ('phone', '15558675309'),
                    is_from_me=True, sender='Me', handle_address='+15552223333'),
        ]
        self.assertIsNone(detect_owner_phone(messages))

    def test_self_chat_wins_over_outgoing_handle_fallback(self):
        messages = [
            message('GUID-1', 'note to self', '2025-01-01 10:00:00', ('phone', '15551111111'),
                    is_from_me=True, sender='Me', handle_address='+15551111111'),
            message('GUID-2', 'hi alex', '2025-01-02 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-3', 'hi sam', '2025-01-03 10:00:00', ('phone', '15558675309'),
                    is_from_me=True, sender='Me', handle_address='+15551234567'),
            message('GUID-4', 'from alex', '2025-01-04 10:00:00', ('phone', '15559876543'),
                    handle_address='+15559876543'),
        ]
        self.assertEqual(detect_owner_phone(messages), '5551111111')

    def test_export_labels_self_chat_with_detected_number(self):
        database = os.path.join(self.output_dir, 'self_sms.db')
        with open(database, 'wb') as database_file:
            database_file.write(b'test database')
        messages = [
            message('GUID-1', 'note to self', '2025-01-01 10:00:00', ('phone', '15551234567'),
                    is_from_me=True, sender='Me', id=1),
            message('GUID-2', 'reminder', '2025-01-02 10:00:00', ('phone', '15551234567'),
                    is_from_me=True, sender='Me', id=2),
            message('GUID-3', 'from alex', '2025-01-03 10:00:00', ('phone', '15559876543'),
                    sender='Alex', id=3),
        ]

        with ExitStack() as patches:
            patches.enter_context(patch('iphone_imessage_exporter.fetch_contacts', return_value={}))
            patches.enter_context(
                patch('iphone_imessage_exporter.fetch_sms_messages', return_value=(messages, {}))
            )
            patches.enter_context(patch('iphone_imessage_exporter.fetch_attachments', return_value={}))
            patches.enter_context(patch('iphone_imessage_exporter.fetch_group_participants', return_value={}))
            export_messages(database, None, None, None, self.output_dir)

        self_chat_path = os.path.join(self.output_dir, 'You_(+1_(555)_123-4567).html')
        self.assertTrue(
            os.path.isfile(self_chat_path),
            f'output files: {sorted(os.listdir(self.output_dir))}',
        )
        with open(self_chat_path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn('You (+1 (555) 123-4567)', content)
        self.assertIn('<span>Your number · +1 (555) 123-4567</span>', content)

        with open(os.path.join(self.output_dir, 'index.html'), encoding='utf-8') as page:
            index_content = page.read()
        self.assertIn('You (+1 (555) 123-4567)', index_content)
        self.assertNotIn('<tr><td>Me</td>', index_content)
        # Sender rows in the per-year section carry the share of that year's received texts.
        self.assertIn('<th>% of received</th>', index_content)
        self.assertIn('<tr><td>Alex</td><td>1</td><td>100.0%</td></tr>', index_content)

    def test_export_fallback_uses_shared_outgoing_handles(self):
        database = os.path.join(self.output_dir, 'fallback_sms.db')
        with open(database, 'wb') as database_file:
            database_file.write(b'test database')
        messages = [
            message('GUID-1', 'hi alex', '2025-01-01 10:00:00', ('phone', '15559876543'),
                    is_from_me=True, sender='Me', handle_address='+15551234567', id=1),
            message('GUID-2', 'hi sam', '2025-01-02 10:00:00', ('phone', '15558675309'),
                    is_from_me=True, sender='Me', handle_address='+15551234567', id=2),
            message('GUID-3', 'from alex', '2025-01-03 10:00:00', ('phone', '15559876543'),
                    sender='Alex', handle_address='+15559876543', id=3),
        ]

        with ExitStack() as patches:
            patches.enter_context(patch('iphone_imessage_exporter.fetch_contacts', return_value={}))
            patches.enter_context(
                patch('iphone_imessage_exporter.fetch_sms_messages', return_value=(messages, {}))
            )
            patches.enter_context(patch('iphone_imessage_exporter.fetch_attachments', return_value={}))
            patches.enter_context(patch('iphone_imessage_exporter.fetch_group_participants', return_value={}))
            export_messages(database, None, None, None, self.output_dir)

        with open(os.path.join(self.output_dir, 'index.html'), encoding='utf-8') as page:
            index_content = page.read()

        self.assertNotIn('<tr><td>Me</td>', index_content)
        self.assertIn('<tr><td>Alex</td><td>1</td><td>100.0%</td></tr>', index_content)

    def test_legacy_message_is_upgraded_to_guid_without_duplication(self):
        legacy = message(None, 'hello', '2025-01-01 10:00:00', id=12)
        legacy['attachments'] = [{'filename': 'old.jpg'}]
        current = message('stable-guid', 'hello', '2025-01-01 10:00:00', id=96)
        _, _, _, total = merge_messages(
            self.output_dir,
            [current],
            {},
            legacy_message_batches=([legacy], [legacy]),
        )

        messages, _, _, total_after_reimport = merge_messages(self.output_dir, [current], {})

        self.assertEqual(total, 1)
        self.assertEqual(total_after_reimport, 1)
        self.assertEqual(messages[0]['guid'], 'stable-guid')
        self.assertEqual(messages[0]['attachments'], [{'filename': 'old.jpg'}])

    def test_sms_fetch_includes_the_database_guid(self):
        database_path = os.path.join(self.output_dir, 'sms.db')
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                'CREATE TABLE message ('
                'ROWID INTEGER PRIMARY KEY, text TEXT, date INTEGER, '
                'is_from_me INTEGER, handle_id INTEGER, guid TEXT)'
            )
            connection.execute(
                'INSERT INTO message (text, date, is_from_me, handle_id, guid) '
                'VALUES (?, ?, ?, ?, ?)',
                ('hello', 0, 0, 1, 'stable-guid'),
            )
            connection.commit()
        finally:
            connection.close()

        messages, _ = fetch_sms_messages(database_path)

        self.assertEqual(messages[0]['guid'], 'stable-guid')

    def test_export_rebuilds_conversation_html_from_merged_archive(self):
        first_database = os.path.join(self.output_dir, 'first_sms.db')
        second_database = os.path.join(self.output_dir, 'second_sms.db')
        for path in (first_database, second_database):
            with open(path, 'wb') as database_file:
                database_file.write(b'test database')

        first_import = message('GUID-1', 'older text', '2025-01-01 10:00:00')
        overlapping_import = message('GUID-1', 'older text', '2025-01-01 10:00:00', id=44)
        new_import = message('GUID-2', 'newer text', '2025-01-02 10:00:00', id=45)
        imports = {
            first_database: ([first_import], {}),
            second_database: ([overlapping_import, new_import], {}),
        }

        with ExitStack() as patches:
            patches.enter_context(patch('iphone_imessage_exporter.fetch_contacts', return_value={}))
            patches.enter_context(
                patch('iphone_imessage_exporter.fetch_sms_messages', side_effect=lambda path: imports[path])
            )
            patches.enter_context(patch('iphone_imessage_exporter.fetch_attachments', return_value={}))
            patches.enter_context(patch('iphone_imessage_exporter.fetch_group_participants', return_value={}))
            export_messages(first_database, None, None, None, self.output_dir)
            export_messages(second_database, None, None, None, self.output_dir)

        with open(os.path.join(self.output_dir, 'Alex.html'), encoding='utf-8') as conversation:
            html = conversation.read()

        self.assertEqual(html.count('>older text</div>'), 1)
        self.assertEqual(html.count('>newer text</div>'), 1)

    def test_regenerate_html_reuses_archive_without_extracting_backup(self):
        merge_messages(
            self.output_dir,
            [message('GUID-1', 'archived text', '2025-01-01 10:00:00')],
            {},
        )

        with patch('iphone_imessage_exporter.extract_iphone_backup') as extract:
            output_dir, count = regenerate_html(self.output_dir)

        extract.assert_not_called()
        self.assertEqual(output_dir, self.output_dir)
        self.assertEqual(count, 1)
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, 'Alex.html')))
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, 'birthdays.html')))
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, 'birthday_wishes.html')))
        with open(os.path.join(self.output_dir, 'Alex.html'), encoding='utf-8') as conversation:
            self.assertIn('2025-01-01 05:00:00', conversation.read())

    def test_backup_imports_get_separate_dated_extractions_caches_and_conversions(self):
        extracted_roots = []
        extracted_media = []
        imports = [
            message('GUID-1', 'first backup', '2025-01-01 10:00:00', id=1),
            message('GUID-2', 'second backup', '2025-01-02 10:00:00', id=2),
        ]

        def extract_backup(
            backup_dir,
            extraction_dir,
            password,
            progress,
            existing_media_dirs=(),
        ):
            self.assertIn(backup_dir, ('backup-one', 'backup-two'))
            self.assertIsNone(password)
            self.assertIsNone(progress)
            extracted_roots.append(extraction_dir)
            media_folder = os.path.join(extraction_dir, 'MediaDomain')
            attachment_path = os.path.join(
                media_folder, 'Library', 'SMS', 'Attachments', 'sample.heic'
            )
            os.makedirs(os.path.dirname(attachment_path), exist_ok=True)
            with open(attachment_path, 'wb') as attachment:
                attachment.write(b'heic placeholder')
            extracted_media.append(attachment_path)
            attachment_path_map = {}
            if existing_media_dirs:
                attachment_path_map[os.path.normcase(attachment_path)] = extracted_media[0]
            sms_path = os.path.join(extraction_dir, 'sms.db')
            with open(sms_path, 'wb') as database:
                database.write(b'sms placeholder')
            return {
                'sms_db': sms_path,
                'attachment_db': None,
                'attachment_folder': media_folder,
                'address_book_db': None,
                'attachment_path_map': attachment_path_map,
            }

        imported = iter(imports)

        def fetch_messages(sms_path):
            self.assertTrue(os.path.isfile(sms_path))
            return [next(imported)], {}

        def fetch_attachments(sms_path):
            self.assertTrue(os.path.isfile(sms_path))
            return {1: [dict(attachment)], 2: [dict(attachment)]}

        def convert_heic(source_path, conversion_dir):
            self.assertTrue(os.path.isfile(source_path))
            conversion_folder = os.path.join(conversion_dir, 'converted_heic')
            os.makedirs(conversion_folder, exist_ok=True)
            return os.path.join(conversion_folder, 'preview.jpg')

        attachment = {
            'id': 5,
            'filename': 'sample.heic',
            'mime_type': 'image/heic',
            'file_path': 'Library/SMS/Attachments/sample.heic',
        }
        with ExitStack() as patches:
            patches.enter_context(patch('iphone_imessage_exporter.fetch_contacts', return_value={}))
            patches.enter_context(
                patch('iphone_imessage_exporter.extract_iphone_backup', side_effect=extract_backup)
            )
            patches.enter_context(
                patch('iphone_imessage_exporter.fetch_sms_messages', side_effect=fetch_messages)
            )
            patches.enter_context(
                patch('iphone_imessage_exporter.fetch_attachments', side_effect=fetch_attachments)
            )
            patches.enter_context(patch('iphone_imessage_exporter.fetch_group_participants', return_value={}))
            convert = patches.enter_context(patch('export_media.convert_heic_to_jpeg', side_effect=convert_heic))
            export_messages(None, None, None, None, self.output_dir, backup_dir='backup-one')
            export_messages(None, None, None, None, self.output_dir, backup_dir='backup-two')

        self.assertEqual(len(extracted_media), 2)
        self.assertEqual(convert.call_args_list[1].args[0], extracted_media[0])
        self.assertEqual(len(set(extracted_roots)), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, 'calls.html')))
        self.assertTrue(all(
            re.fullmatch(r'extracted_backup_\d{8}_\d{6}_\d{6}', os.path.basename(root))
            for root in extracted_roots
        ))
        cache_paths = glob.glob(os.path.join(self.output_dir, 'sms_messages_v4_*.pkl'))
        self.assertEqual(len(cache_paths), 2)
        self.assertTrue(all(
            any(
                os.path.basename(root).split('extracted_backup_', 1)[1] in os.path.basename(cache_path)
                for cache_path in cache_paths
            )
            for root in extracted_roots
        ))
        conversion_dirs = {call.args[1] for call in convert.call_args_list}
        self.assertEqual(conversion_dirs, set(extracted_roots))
        self.assertTrue(all(
            os.path.isdir(os.path.join(root, 'converted_heic'))
            for root in extracted_roots
        ))


if __name__ == '__main__':
    unittest.main()
