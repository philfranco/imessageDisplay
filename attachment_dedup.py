"""Content hashing and hard-link deduplication for extracted media files."""

import hashlib
import os
import sqlite3


HASH_INDEX_FILENAME = 'attachment_hashes.sqlite3'


def _hash_index_path(output_dir):
    if os.path.basename(output_dir).startswith('extracted_backup_'):
        output_dir = os.path.dirname(output_dir)
    return os.path.join(output_dir, HASH_INDEX_FILENAME)


def _hash_file(path, connection):
    absolute_path = os.path.abspath(path)
    stat = os.stat(absolute_path)
    path_key = os.path.normcase(absolute_path)
    cached = connection.execute(
        'SELECT size, mtime_ns, digest FROM file_hashes WHERE path = ?',
        (path_key,),
    ).fetchone()
    if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
        return cached[2]

    digest = hashlib.sha256()
    with open(absolute_path, 'rb') as media_file:
        for chunk in iter(lambda: media_file.read(1024 * 1024), b''):
            digest.update(chunk)
    hexdigest = digest.hexdigest()
    connection.execute(
        'INSERT INTO file_hashes (path, size, mtime_ns, digest) VALUES (?, ?, ?, ?) '
        'ON CONFLICT(path) DO UPDATE SET '
        'size = excluded.size, mtime_ns = excluded.mtime_ns, digest = excluded.digest',
        (path_key, stat.st_size, stat.st_mtime_ns, hexdigest),
    )
    return hexdigest


def hash_media_file(path, output_dir):
    """Return a cached SHA-256 digest, reading file contents if it has changed."""
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    connection = sqlite3.connect(_hash_index_path(output_dir))
    try:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS file_hashes ('
            'path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, '
            'digest TEXT NOT NULL)'
        )
        digest = _hash_file(path, connection)
        connection.commit()
        return digest
    finally:
        connection.close()


def index_existing_attachments(output_dir, attachment_dirs, progress=None):
    """Hash old extraction media in path order so the oldest copy stays canonical."""
    canonical_by_digest = {}
    files_checked = 0
    candidates_by_extraction = []
    for attachment_dir in attachment_dirs:
        if not os.path.isdir(attachment_dir):
            continue
        candidates = []
        for current_dir, _, filenames in os.walk(attachment_dir):
            candidates.extend(os.path.join(current_dir, name) for name in filenames)
        candidates_by_extraction.append(sorted(candidates, key=os.path.normcase))

    total_candidates = sum(len(files) for files in candidates_by_extraction)
    for candidates in candidates_by_extraction:
        for path in candidates:
            digest = hash_media_file(path, output_dir)
            canonical_by_digest.setdefault(digest, path)
            files_checked += 1
            if progress and files_checked % 500 == 0:
                progress(
                    f'Hashed existing attachment files: '
                    f'{files_checked}/{total_candidates}'
                )
    if progress:
        progress(f'Indexed {files_checked} existing attachment files.')
    return canonical_by_digest


def register_media_hash(path, digest, output_dir):
    """Persist a digest for a newly extracted file without rereading its contents."""
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    absolute_path = os.path.abspath(path)
    stat = os.stat(absolute_path)
    connection = sqlite3.connect(_hash_index_path(output_dir))
    try:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS file_hashes ('
            'path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, '
            'digest TEXT NOT NULL)'
        )
        connection.execute(
            'INSERT INTO file_hashes (path, size, mtime_ns, digest) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(path) DO UPDATE SET '
            'size = excluded.size, mtime_ns = excluded.mtime_ns, digest = excluded.digest',
            (os.path.normcase(absolute_path), stat.st_size, stat.st_mtime_ns, digest),
        )
        connection.commit()
    finally:
        connection.close()
