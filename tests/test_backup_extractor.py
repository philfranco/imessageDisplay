import hashlib
import os
import plistlib
import sqlite3
import tempfile
import unittest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import aes_key_wrap

from backup_extractor import extract_iphone_backup
from sms_database import normalize_attachment_paths, sanitize_backup_relative_path


SMS_PATH = 'Library/SMS/sms.db'
CONTACTS_PATH = 'Library/AddressBook/AddressBook.sqlitedb'
CALL_HISTORY_PATH = 'Library/CallHistoryDB/CallHistory.storedata'
MEDIA_PATH = (
    'Library/SMS/Attachments/51/01/15FEA88B-D0FB-49ED-95B8-4A611168CC8A/'
    'Paula Paula its Paula @XfinityLive! You have been selected for VIP Party '
    'for your group this Friday with 12 drinks & free entry.jpeg'
)


def read_bytes(path):
    with open(path, 'rb') as file:
        return file.read()


def archive_file(data, protection_class=None, wrapped_key=None, metadata_size=None):
    objects = ['$null', {}]
    properties = objects[1]
    properties['Size'] = plistlib.UID(2)
    objects.append(len(data) if metadata_size is None else metadata_size)
    if wrapped_key is not None:
        properties['ProtectionClass'] = plistlib.UID(3)
        properties['EncryptionKey'] = plistlib.UID(4)
        objects.append(protection_class)
        objects.append({'NS.data': wrapped_key})
    objects.append({'$classname': 'FileInfo'})
    properties['$class'] = plistlib.UID(len(objects) - 1)
    return plistlib.dumps(
        {'$archiver': 'NSKeyedArchiver', '$version': 100000, '$objects': objects, '$top': {'root': plistlib.UID(1)}},
        fmt=plistlib.FMT_BINARY,
    )


def encrypt_cbc(data, key):
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def make_backup(
    backup_dir,
    encrypted,
    sms_metadata_size_offset=0,
    include_call_history=True,
    media_path=MEDIA_PATH,
    media_contents=b'attachment bytes',
):
    os.makedirs(backup_dir, exist_ok=True)
    files = [
        ('HomeDomain', SMS_PATH, b'sms database'),
        ('HomeDomain', CONTACTS_PATH, b'address book database'),
        ('MediaDomain', media_path, media_contents),
    ]
    if include_call_history:
        files.insert(
            2,
            ('HomeDomain', CALL_HISTORY_PATH, b'call history database'),
        )
    keybag_data = b''
    manifest_key_data = None
    keybag_class_key = None
    password = 'correct horse battery staple'

    if encrypted:
        dpsl, salt = b'password-salt-01', b'backup-salt-001'
        iterations1, iterations2 = 10, 10
        first_key = hashlib.pbkdf2_hmac('sha256', password.encode(), dpsl, iterations1, 32)
        wrapping_key = hashlib.pbkdf2_hmac('sha1', first_key, salt, iterations2, 32)
        keybag_class_key = bytes(range(32))
        class_id = (1).to_bytes(4, 'big')
        wrapped_class_key = aes_key_wrap(wrapping_key, keybag_class_key)

        def record(tag, value):
            return tag.encode() + len(value).to_bytes(4, 'big') + value

        keybag_data = b''.join((
            record('TYPE', (1).to_bytes(4, 'big')),
            record('UUID', b'global-keybag-id'),
            record('DPSL', dpsl),
            record('DPIC', iterations1.to_bytes(4, 'big')),
            record('SALT', salt),
            record('ITER', iterations2.to_bytes(4, 'big')),
            record('UUID', b'file-class-uuid!'),
            record('CLAS', class_id),
            record('WRAP', (2).to_bytes(4, 'big')),
            record('WPKY', wrapped_class_key),
        ))
        manifest_content_key = b'manifest-content-key-00000000000'
        manifest_key_data = (1).to_bytes(4, 'little') + aes_key_wrap(
            keybag_class_key, manifest_content_key
        )

    manifest_path = os.path.join(backup_dir, 'Manifest.db')
    connection = sqlite3.connect(manifest_path)
    connection.execute(
        'CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)'
    )
    for index, (domain, relative_path, plaintext) in enumerate(files, 1):
        file_id = f'{index:040x}'
        file_key = bytes([index]) * 32
        wrapped_file_key = aes_key_wrap(keybag_class_key, file_key) if encrypted else None
        connection.execute(
            'INSERT INTO Files VALUES (?, ?, ?, ?, ?)',
            (
                file_id,
                domain,
                relative_path,
                1,
                archive_file(
                    plaintext,
                    1,
                    (1).to_bytes(4, 'big') + wrapped_file_key if encrypted else None,
                    len(plaintext) + sms_metadata_size_offset if index == 1 else None,
                ),
            ),
        )
        file_dir = os.path.join(backup_dir, file_id[:2])
        os.makedirs(file_dir, exist_ok=True)
        payload = encrypt_cbc(plaintext, file_key) if encrypted else plaintext
        with open(os.path.join(file_dir, file_id), 'wb') as backup_file:
            backup_file.write(payload)
    connection.execute(
        'INSERT INTO Files VALUES (?, ?, ?, ?, ?)',
        ('f' * 40, 'MediaDomain', 'Library/SMS/Attachments/1', 2, b''),
    )
    connection.commit()
    connection.close()

    if encrypted:
        with open(manifest_path, 'rb') as manifest_file:
            encrypted_manifest = encrypt_cbc(manifest_file.read(), manifest_content_key)
        with open(manifest_path, 'wb') as manifest_file:
            manifest_file.write(encrypted_manifest)

    manifest_info = {'IsEncrypted': encrypted}
    if encrypted:
        manifest_info.update({'BackupKeyBag': keybag_data, 'ManifestKey': manifest_key_data})
    with open(os.path.join(backup_dir, 'Manifest.plist'), 'wb') as info_file:
        plistlib.dump(manifest_info, info_file)
    return password


class BackupExtractorTests(unittest.TestCase):
    def test_duplicate_attachment_is_not_written_and_maps_to_oldest_copy(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted), tempfile.TemporaryDirectory() as temporary_dir:
                new_backup = os.path.join(temporary_dir, 'new-backup')
                old_extraction = os.path.join(temporary_dir, 'extracted_backup_old')
                new_extraction = os.path.join(temporary_dir, 'extracted_backup_new')
                new_media_path = (
                    'Library/SMS/Attachments/00/00/unique-new-folder/'
                    'same-picture.jpg'
                )
                old_attachment_root = os.path.join(
                    old_extraction,
                    'MediaDomain',
                    'Library',
                    'SMS',
                    'Attachments',
                )
                old_attachment = os.path.join(
                    old_attachment_root,
                    sanitize_backup_relative_path(MEDIA_PATH, old_attachment_root),
                )
                os.makedirs(os.path.dirname(old_attachment), exist_ok=True)
                with open(old_attachment, 'wb') as media_file:
                    media_file.write(b'identical image bytes')

                password = make_backup(
                    new_backup,
                    encrypted=encrypted,
                    media_path=new_media_path,
                    media_contents=b'identical image bytes',
                )
                progress = []

                extracted = extract_iphone_backup(
                    new_backup,
                    new_extraction,
                    password if encrypted else None,
                    progress=progress.append,
                    existing_media_dirs=[old_attachment_root],
                )
                requested_path = os.path.join(
                    new_extraction,
                    'MediaDomain',
                    sanitize_backup_relative_path(
                        new_media_path,
                        os.path.join(new_extraction, 'MediaDomain'),
                    ),
                )

                self.assertFalse(os.path.exists(requested_path))
                self.assertEqual(
                    extracted['attachment_path_map'][os.path.normcase(requested_path)],
                    old_attachment,
                )
                self.assertEqual(read_bytes(old_attachment), b'identical image bytes')
                self.assertEqual(
                    sum('Skipped 1 duplicate attachment' in message for message in progress),
                    1,
                )
                self.assertFalse(any(
                    'Skipped duplicate attachment;' in message for message in progress
                ))

    def test_extracts_required_files_and_attachments_from_unencrypted_backup(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            output_dir = os.path.join(temporary_dir, 'output')
            make_backup(backup_dir, encrypted=False)

            extracted = extract_iphone_backup(backup_dir, output_dir)

            self.assertEqual(read_bytes(extracted['sms_db']), b'sms database')
            self.assertEqual(
                read_bytes(extracted['address_book_db']),
                b'address book database',
            )
            self.assertEqual(
                read_bytes(extracted['call_history_db']),
                b'call history database',
            )
            attachment = os.path.join(
                extracted['attachment_folder'],
                sanitize_backup_relative_path(MEDIA_PATH, extracted['attachment_folder']),
            )
            self.assertLessEqual(len(attachment), 240)
            self.assertEqual(read_bytes(attachment), b'attachment bytes')
            mapped = normalize_attachment_paths(
                {1: [{'file_path': MEDIA_PATH}]},
                extracted['attachment_folder'],
            )
            self.assertEqual(mapped[1][0]['file_path'], attachment)
            self.assertTrue(os.path.isfile(mapped[1][0]['file_path']))

    def test_call_history_database_is_optional(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            output_dir = os.path.join(temporary_dir, 'output')
            make_backup(backup_dir, encrypted=False, include_call_history=False)

            extracted = extract_iphone_backup(backup_dir, output_dir)

            self.assertIsNone(extracted['call_history_db'])

    def test_reports_extraction_stages_and_file_progress(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            output_dir = os.path.join(temporary_dir, 'output')
            make_backup(backup_dir, encrypted=False)
            progress = []

            extract_iphone_backup(backup_dir, output_dir, progress=progress.append)

            self.assertTrue(any('Checking backup folder' in line for line in progress))
            self.assertTrue(any('Reading backup manifest' in line for line in progress))
            self.assertTrue(any('Found 4' in line for line in progress))
            self.assertTrue(any('extraction complete' in line.lower() for line in progress))

    def test_extracts_encrypted_backup_with_password(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            output_dir = os.path.join(temporary_dir, 'output')
            password = make_backup(backup_dir, encrypted=True)

            extracted = extract_iphone_backup(backup_dir, output_dir, password)

            self.assertEqual(read_bytes(extracted['sms_db']), b'sms database')
            self.assertEqual(
                read_bytes(extracted['address_book_db']),
                b'address book database',
            )

    def test_encrypted_file_size_metadata_mismatch_does_not_abort_extraction(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            output_dir = os.path.join(temporary_dir, 'output')
            password = make_backup(
                backup_dir,
                encrypted=True,
                sms_metadata_size_offset=16,
            )

            extracted = extract_iphone_backup(backup_dir, output_dir, password)

            self.assertEqual(read_bytes(extracted['sms_db']), b'sms database')

    def test_rejects_incorrect_backup_password(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            make_backup(backup_dir, encrypted=True)

            with self.assertRaisesRegex(ValueError, 'password is incorrect'):
                extract_iphone_backup(
                    backup_dir,
                    os.path.join(temporary_dir, 'output'),
                    'incorrect password',
                )

    def test_encrypted_backup_requires_password(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            backup_dir = os.path.join(temporary_dir, 'backup')
            make_backup(backup_dir, encrypted=True)

            with self.assertRaisesRegex(ValueError, 'Enter its backup password'):
                extract_iphone_backup(backup_dir, os.path.join(temporary_dir, 'output'))


if __name__ == '__main__':
    unittest.main()
