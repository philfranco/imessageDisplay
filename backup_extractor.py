"""Extract iMessage databases and media from an iTunes iPhone backup."""

import os
import hashlib
import plistlib
import shutil
import sqlite3
import tempfile

from sms_database import sanitize_backup_relative_path
from attachment_dedup import index_existing_attachments, register_media_hash


SMS_DB_PATH = 'Library/SMS/sms.db'
ADDRESS_BOOK_DB_PATH = 'Library/AddressBook/AddressBook.sqlitedb'
CALL_HISTORY_DB_PATH = 'Library/CallHistoryDB/CallHistory.storedata'
ATTACHMENT_PATH = 'Library/SMS/Attachments/'
STICKER_CACHE_PATH = 'Library/SMS/StickerCache/'
STICKER_DATABASE_PATH = 'Library/Stickers/stickers.stickerdb'


def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as error:
        raise RuntimeError(
            'Encrypted backup extraction requires cryptography. '
            'Install project dependencies with: python -m pip install -r requirements.txt'
        ) from error
    return hashes, padding, Cipher, algorithms, modes, aes_key_unwrap, PBKDF2HMAC, InvalidUnwrap


def _parse_keybag(data):
    offset = 0
    attributes = {}
    class_records = []
    current_class = None

    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError('The encrypted backup keybag is truncated.')
        tag = data[offset:offset + 4].decode('ascii', errors='strict')
        length = int.from_bytes(data[offset + 4:offset + 8], 'big')
        offset += 8
        value = data[offset:offset + length]
        if len(value) != length:
            raise ValueError('The encrypted backup keybag is truncated.')
        offset += length

        if tag == 'UUID':
            if current_class is None and 'UUID' not in attributes:
                attributes['UUID'] = value
            else:
                if current_class is not None:
                    class_records.append(current_class)
                current_class = {}
        elif tag in ('TYPE',):
            attributes[tag] = value
        elif current_class is not None and tag in ('CLAS', 'WRAP', 'WPKY', 'KTYP', 'PBKY'):
            current_class[tag] = value
        else:
            attributes[tag] = value

    if not all(key in attributes for key in ('DPSL', 'DPIC', 'SALT', 'ITER')):
        raise ValueError('The encrypted backup is missing keybag password parameters.')
    if current_class is not None:
        class_records.append(current_class)
    class_keys = {
        record['CLAS']: record
        for record in class_records
        if len(record.get('CLAS', b'')) == 4
    }
    return attributes, class_keys


def _unlock_keybag(keybag_data, password):
    hashes, _, _, _, _, aes_key_unwrap, PBKDF2HMAC, InvalidUnwrap = _crypto()
    attributes, class_keys = _parse_keybag(keybag_data)
    first_key = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=attributes['DPSL'],
        iterations=int.from_bytes(attributes['DPIC'], 'big'),
    ).derive(password.encode('utf-8'))
    wrapping_key = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=32,
        salt=attributes['SALT'],
        iterations=int.from_bytes(attributes['ITER'], 'big'),
    ).derive(first_key)

    unlocked = {}
    for protection_class, records in class_keys.items():
        wrap_flags = int.from_bytes(records.get('WRAP', b'\0\0\0\0'), 'big')
        if wrap_flags & 2 and 'WPKY' in records:
            try:
                unlocked[protection_class] = aes_key_unwrap(wrapping_key, records['WPKY'])
            except InvalidUnwrap as error:
                raise ValueError('The backup password is incorrect or its keybag is invalid.') from error
    if not unlocked:
        raise ValueError('The backup keybag contains no password-protected file keys.')
    return unlocked


def _decrypt(data, key):
    _, _, Cipher, algorithms, modes, _, _, _ = _crypto()
    decryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def _resolve_archive_value(value, objects):
    while isinstance(value, plistlib.UID):
        try:
            value = objects[value.data]
        except IndexError as error:
            raise ValueError('The backup manifest contains an invalid file record.') from error
    return value


def _file_properties(serialized):
    archive = plistlib.loads(serialized)
    objects = archive.get('$objects')
    root = _resolve_archive_value(archive.get('$top', {}).get('root'), objects)
    if not isinstance(root, dict):
        raise ValueError('The backup manifest contains an unsupported file record.')

    properties = {
        name: _resolve_archive_value(value, objects)
        for name, value in root.items()
        if name != '$class'
    }
    encryption_key = properties.get('EncryptionKey')
    if isinstance(encryption_key, dict):
        encryption_key = _resolve_archive_value(encryption_key.get('NS.data'), objects)
    properties['EncryptionKey'] = encryption_key
    return properties


def _record_files(database_path):
    connection = sqlite3.connect(database_path)
    try:
        return list(connection.execute(
            'SELECT fileID, domain, relativePath, flags, file FROM Files '
            'WHERE flags = 1 AND ((domain = ? AND relativePath IN (?, ?)) '
            'OR (domain = ? AND relativePath = ?) '
            'OR (domain = ? AND relativePath LIKE ?) '
            'OR (domain = ? AND relativePath LIKE ?) '
            'OR (domain = ? AND relativePath = ?))',
            (
                'HomeDomain',
                SMS_DB_PATH,
                ADDRESS_BOOK_DB_PATH,
                'HomeDomain',
                CALL_HISTORY_DB_PATH,
                'MediaDomain',
                ATTACHMENT_PATH + '%',
                'HomeDomain',
                STICKER_CACHE_PATH + '%',
                'HomeDomain',
                STICKER_DATABASE_PATH,
            ),
        ))
    finally:
        connection.close()


def _report(progress, message):
    if progress:
        progress(message)
    else:
        print(message)


def _backup_file_path(backup_dir, file_id):
    if not file_id or len(file_id) < 2 or any(character not in '0123456789abcdefABCDEF' for character in file_id):
        raise ValueError(f'Invalid iTunes backup file ID: {file_id!r}')
    return os.path.join(backup_dir, file_id[:2], file_id)


def _write_backup_content(backup_dir, row, keybag_keys, destination, progress=None):
    file_id, _, _, flags, serialized = row
    if flags != 1:
        raise ValueError('The backup manifest marked a required file as non-regular.')
    properties = _file_properties(serialized)
    size = properties.get('Size')
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError('The backup file record has an invalid size.')
    source_path = _backup_file_path(backup_dir, file_id)
    wrapped_key = properties.get('EncryptionKey')
    if wrapped_key is None:
        if os.path.getsize(source_path) != size:
            raise ValueError(f'Backup file size mismatch for {file_id}.')
        shutil.copyfile(source_path, destination)
        return
    if not isinstance(wrapped_key, bytes):
        raise ValueError('The backup contains an unsupported file encryption key.')
    if len(wrapped_key) == 44:
        wrapped_key = wrapped_key[4:]
    elif len(wrapped_key) != 40:
        raise ValueError(
            f'The backup file encryption key for {file_id} has an unsupported length '
            f'({len(wrapped_key)} bytes).'
        )

    protection_class = properties.get('ProtectionClass')
    if isinstance(protection_class, bool) or not isinstance(protection_class, int):
        raise ValueError('The encrypted backup file is missing its protection class.')
    class_key = keybag_keys.get(protection_class.to_bytes(4, 'big'))
    if class_key is None:
        raise ValueError(f'No decrypted backup key exists for protection class {protection_class}.')

    _, _, _, _, _, aes_key_unwrap, _, InvalidUnwrap = _crypto()
    try:
        content_key = aes_key_unwrap(class_key, wrapped_key)
    except InvalidUnwrap as error:
        raise ValueError(f'Could not unlock backup file {file_id}.') from error

    _, padding, Cipher, algorithms, modes, _, _, _ = _crypto()

    def decrypt_to_file(strip_padding):
        decryptor = Cipher(algorithms.AES(content_key), modes.CBC(bytes(16))).decryptor()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder() if strip_padding else None
        bytes_written = 0
        with open(source_path, 'rb') as source, open(destination, 'wb') as output:
            while True:
                encrypted_chunk = source.read(1024 * 1024)
                if not encrypted_chunk:
                    break
                plaintext_chunk = decryptor.update(encrypted_chunk)
                if unpadder:
                    plaintext_chunk = unpadder.update(plaintext_chunk)
                output.write(plaintext_chunk)
                bytes_written += len(plaintext_chunk)
            plaintext_chunk = decryptor.finalize()
            if unpadder:
                plaintext_chunk = unpadder.update(plaintext_chunk) + unpadder.finalize()
            output.write(plaintext_chunk)
            bytes_written += len(plaintext_chunk)
        return bytes_written

    try:
        actual_size = decrypt_to_file(strip_padding=True)
    except ValueError:
        actual_size = decrypt_to_file(strip_padding=False)
    if actual_size != size:
        _report(
            progress,
            f'Warning: Backup size metadata differs for {file_id}: '
            f'expected {size} bytes, decrypted {actual_size} bytes.'
        )


def _hash_backup_content(backup_dir, row, keybag_keys, progress=None):
    """Hash the extracted plaintext without writing a temporary media file."""
    file_id, _, _, flags, serialized = row
    if flags != 1:
        raise ValueError('The backup manifest marked a required file as non-regular.')
    properties = _file_properties(serialized)
    size = properties.get('Size')
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError('The backup file record has an invalid size.')
    source_path = _backup_file_path(backup_dir, file_id)
    wrapped_key = properties.get('EncryptionKey')
    if wrapped_key is None:
        if os.path.getsize(source_path) != size:
            raise ValueError(f'Backup file size mismatch for {file_id}.')
        digest = hashlib.sha256()
        with open(source_path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    if not isinstance(wrapped_key, bytes):
        raise ValueError('The backup contains an unsupported file encryption key.')
    if len(wrapped_key) == 44:
        wrapped_key = wrapped_key[4:]
    elif len(wrapped_key) != 40:
        raise ValueError(
            f'The backup file encryption key for {file_id} has an unsupported length '
            f'({len(wrapped_key)} bytes).'
        )
    protection_class = properties.get('ProtectionClass')
    if isinstance(protection_class, bool) or not isinstance(protection_class, int):
        raise ValueError('The encrypted backup file is missing its protection class.')
    class_key = keybag_keys.get(protection_class.to_bytes(4, 'big'))
    if class_key is None:
        raise ValueError(f'No decrypted backup key exists for protection class {protection_class}.')

    _, padding, Cipher, algorithms, modes, aes_key_unwrap, _, InvalidUnwrap = _crypto()
    try:
        content_key = aes_key_unwrap(class_key, wrapped_key)
    except InvalidUnwrap as error:
        raise ValueError(f'Could not unlock backup file {file_id}.') from error

    def hash_decrypted_content(strip_padding):
        decryptor = Cipher(algorithms.AES(content_key), modes.CBC(bytes(16))).decryptor()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder() if strip_padding else None
        digest = hashlib.sha256()
        bytes_hashed = 0
        with open(source_path, 'rb') as source:
            while True:
                encrypted_chunk = source.read(1024 * 1024)
                if not encrypted_chunk:
                    break
                plaintext_chunk = decryptor.update(encrypted_chunk)
                if unpadder:
                    plaintext_chunk = unpadder.update(plaintext_chunk)
                digest.update(plaintext_chunk)
                bytes_hashed += len(plaintext_chunk)
            plaintext_chunk = decryptor.finalize()
            if unpadder:
                plaintext_chunk = unpadder.update(plaintext_chunk) + unpadder.finalize()
            digest.update(plaintext_chunk)
            bytes_hashed += len(plaintext_chunk)
        return digest.hexdigest(), bytes_hashed

    try:
        hexdigest, actual_size = hash_decrypted_content(strip_padding=True)
    except ValueError:
        hexdigest, actual_size = hash_decrypted_content(strip_padding=False)
    if actual_size != size:
        _report(
            progress,
            f'Warning: Backup size metadata differs for {file_id}: '
            f'expected {size} bytes, decrypted {actual_size} bytes.'
        )
    return hexdigest


def _write_extracted_file(output_root, backup_dir, row, keybag_keys, progress=None):
    relative_path = row[2]
    parts = relative_path.replace('\\', '/').split('/')
    if not relative_path or any(part in ('', '.', '..') for part in parts):
        raise ValueError(f'Unsafe path in backup manifest: {relative_path!r}')
    relative_path = sanitize_backup_relative_path(relative_path, output_root)
    destination = os.path.join(output_root, relative_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(dir=os.path.dirname(destination))
    try:
        os.close(descriptor)
        _write_backup_content(backup_dir, row, keybag_keys, temporary_path, progress)
        os.replace(temporary_path, destination)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    return destination


def extract_iphone_backup(
    backup_dir,
    output_dir,
    password=None,
    progress=None,
    existing_media_dirs=(),
):
    """Extract required iMessage files from an iTunes backup into output_dir."""
    backup_dir = os.path.abspath(backup_dir)
    output_dir = os.path.abspath(output_dir)
    _report(progress, f'Checking backup folder: {backup_dir}')
    info_path = os.path.join(backup_dir, 'Manifest.plist')
    manifest_path = os.path.join(backup_dir, 'Manifest.db')
    if not os.path.isfile(info_path) or not os.path.isfile(manifest_path):
        raise FileNotFoundError('Select an iTunes backup folder containing Manifest.plist and Manifest.db.')

    with open(info_path, 'rb') as info_file:
        info = plistlib.load(info_file)
    encrypted = bool(info.get('IsEncrypted'))
    _report(progress, f'Backup encryption: {"enabled" if encrypted else "disabled"}.')
    keybag_keys = {}
    if encrypted:
        if not password:
            raise ValueError('This backup is encrypted. Enter its backup password to continue.')
        _report(progress, 'Unlocking backup keybag...')
        keybag_data = info.get('BackupKeyBag')
        if not isinstance(keybag_data, bytes):
            raise ValueError('The encrypted backup is missing its keybag.')
        keybag_keys = _unlock_keybag(keybag_data, password)
        _report(progress, 'Backup password accepted; decrypting manifest...')
        manifest_key = info.get('ManifestKey')
        if not isinstance(manifest_key, bytes) or len(manifest_key) <= 4:
            raise ValueError('The encrypted backup is missing a valid manifest key.')
        protection_class = int.from_bytes(manifest_key[:4], 'little').to_bytes(4, 'big')
        class_key = keybag_keys.get(protection_class)
        if class_key is None:
            raise ValueError('The backup manifest protection key is not available.')
        _, _, _, _, _, aes_key_unwrap, _, InvalidUnwrap = _crypto()
        try:
            manifest_content_key = aes_key_unwrap(class_key, manifest_key[4:])
        except InvalidUnwrap as error:
            raise ValueError('Could not decrypt the backup manifest.') from error
        with open(manifest_path, 'rb') as manifest_file:
            decrypted_manifest = _decrypt(manifest_file.read(), manifest_content_key)
        descriptor, decrypted_manifest_path = tempfile.mkstemp(suffix='.db')
        try:
            with os.fdopen(descriptor, 'wb') as temporary_file:
                temporary_file.write(decrypted_manifest)
            source_manifest = decrypted_manifest_path
            extracted_rows = None
            try:
                extracted_rows = _record_files(source_manifest)
            finally:
                os.remove(decrypted_manifest_path)
        finally:
            if os.path.exists(decrypted_manifest_path):
                os.remove(decrypted_manifest_path)
    else:
        _report(progress, 'Reading backup manifest...')
        extracted_rows = _record_files(manifest_path)

    total_files = len(extracted_rows)
    _report(progress, f'Found {total_files} database and attachment files to extract.')
    canonical_media_by_digest = (
        index_existing_attachments(
            os.path.dirname(output_dir),
            existing_media_dirs,
            progress,
        )
        if existing_media_dirs
        else {}
    )
    found = {}
    written_paths = {}
    attachment_path_map = {}
    duplicate_attachments_skipped = 0
    report_interval = max(1, total_files // 50)
    for index, row in enumerate(extracted_rows, 1):
        domain, relative_path = row[1], row[2]
        if domain == 'HomeDomain' and relative_path in (
            SMS_DB_PATH,
            ADDRESS_BOOK_DB_PATH,
            CALL_HISTORY_DB_PATH,
        ):
            found[relative_path] = _write_extracted_file(
                os.path.join(output_dir, domain), backup_dir, row, keybag_keys, progress
            )
        elif domain == 'HomeDomain' and relative_path == STICKER_DATABASE_PATH:
            found[relative_path] = _write_extracted_file(
                os.path.join(output_dir, domain),
                backup_dir,
                row,
                keybag_keys,
                progress,
            )
        elif domain == 'MediaDomain' and relative_path.startswith(ATTACHMENT_PATH):
            attachment_root = os.path.join(output_dir, domain)
            safe_relative_path = sanitize_backup_relative_path(relative_path, attachment_root)
            path_key = os.path.normcase(safe_relative_path)
            previous_path = written_paths.get(path_key)
            if previous_path is not None and previous_path != relative_path:
                raise ValueError(
                    'Two attachment paths become identical after Windows filename '
                    f'sanitization: {previous_path!r} and {relative_path!r}.'
                )
            written_paths[path_key] = relative_path
            if existing_media_dirs:
                digest = _hash_backup_content(backup_dir, row, keybag_keys, progress)
                canonical_path = canonical_media_by_digest.get(digest)
                if canonical_path is not None:
                    requested_path = os.path.abspath(os.path.join(attachment_root, safe_relative_path))
                    attachment_path_map[os.path.normcase(requested_path)] = canonical_path
                    duplicate_attachments_skipped += 1
                    continue

                extracted_path = _write_extracted_file(
                    attachment_root, backup_dir, row, keybag_keys, progress
                )
                canonical_media_by_digest[digest] = extracted_path
                register_media_hash(extracted_path, digest, os.path.dirname(output_dir))
            else:
                _write_extracted_file(
                    attachment_root, backup_dir, row, keybag_keys, progress
                )
        elif domain == 'HomeDomain' and relative_path.startswith(STICKER_CACHE_PATH):
            _write_extracted_file(
                os.path.join(output_dir, domain),
                backup_dir,
                row,
                keybag_keys,
                progress,
            )
        if index == 1 or index % report_interval == 0 or index == total_files:
            name = relative_path.rsplit('/', 1)[-1]
            _report(progress, f'Extracted files: {index}/{total_files} ({name})')

    missing = [
        path for path in (SMS_DB_PATH, ADDRESS_BOOK_DB_PATH)
        if path not in found
    ]
    if missing:
        raise FileNotFoundError(
            'The backup is missing required file(s): ' + ', '.join(missing)
        )

    if duplicate_attachments_skipped:
        _report(
            progress,
            f'Skipped {duplicate_attachments_skipped:,} duplicate attachment(s); '
            'using the oldest copies.',
        )
    _report(progress, 'Database and attachment extraction complete.')
    return {
        'sms_db': found[SMS_DB_PATH],
        'address_book_db': found[ADDRESS_BOOK_DB_PATH],
        'call_history_db': found.get(CALL_HISTORY_DB_PATH),
        'attachment_folder': os.path.join(output_dir, 'MediaDomain'),
        'sticker_cache_folder': os.path.join(
            output_dir,
            'HomeDomain',
            *STICKER_CACHE_PATH.rstrip('/').split('/'),
        ),
        'sticker_database': found.get(STICKER_DATABASE_PATH),
        'attachment_path_map': attachment_path_map,
        'attachment_db': None,
    }
