import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from attachment_dedup import hash_media_file, index_existing_attachments
from export_media import convert_heic_to_jpeg, convert_mov_to_mp4


class AttachmentDedupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temporary_dir.name

    def tearDown(self):
        self.temporary_dir.cleanup()

    def _write(self, path, contents):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as media_file:
            media_file.write(contents)
        return path

    def _attachment(self, extraction_dir, name):
        return os.path.join(
            extraction_dir,
            'MediaDomain',
            'Library',
            'SMS',
            'Attachments',
            name,
        )

    def test_existing_attachment_index_keeps_the_oldest_path_for_identical_files(self):
        old_extraction = os.path.join(self.output_dir, 'extracted_backup_old')
        new_extraction = os.path.join(self.output_dir, 'extracted_backup_new')
        old_photo = self._write(self._attachment(old_extraction, 'old-name.jpg'), b'same bytes')
        new_photo = self._write(self._attachment(new_extraction, 'new-name.jpg'), b'same bytes')
        new_photo_duplicate = self._write(
            self._attachment(new_extraction, 'different-name.jpg'),
            b'same bytes',
        )

        indexed = index_existing_attachments(
            self.output_dir,
            [
                os.path.join(old_extraction, 'MediaDomain', 'Library', 'SMS', 'Attachments'),
                os.path.join(new_extraction, 'MediaDomain', 'Library', 'SMS', 'Attachments'),
            ],
        )

        digest = hash_media_file(old_photo, self.output_dir)
        self.assertEqual(indexed[digest], old_photo)
        self.assertFalse(os.path.samefile(old_photo, new_photo))
        self.assertTrue(os.path.isfile(new_photo_duplicate))

    def test_hash_cache_refreshes_when_file_metadata_changes(self):
        source = self._write(self._attachment(
            os.path.join(self.output_dir, 'extracted_backup_old'),
            'photo.jpg',
        ), b'first')
        first_digest = hash_media_file(source, self.output_dir)
        with open(source, 'wb') as media_file:
            media_file.write(b'second')

        second_digest = hash_media_file(source, self.output_dir)

        self.assertNotEqual(first_digest, second_digest)

    def test_conversions_are_reused_across_extractions(self):
        digest = 'a' * 64
        old_extraction = os.path.join(self.output_dir, 'extracted_backup_old')
        new_extraction = os.path.join(self.output_dir, 'extracted_backup_new')
        source = self._write(self._attachment(new_extraction, 'photo.heic'), b'photo')
        old_jpeg = self._write(
            os.path.join(old_extraction, 'converted_heic', f'{digest}.jpg'),
            b'converted photo',
        )
        old_mp4 = self._write(
            os.path.join(old_extraction, 'converted_mov', f'{digest}.mp4'),
            b'converted video',
        )
        with patch('export_media.hash_media_file', return_value=digest):
            jpeg = convert_heic_to_jpeg(source, new_extraction)
            mp4 = convert_mov_to_mp4(source, new_extraction)

        self.assertTrue(os.path.samefile(old_jpeg, jpeg))
        self.assertTrue(os.path.samefile(old_mp4, mp4))

    def test_mov_conversion_maps_only_first_audio_track(self):
        source = self._write(
            self._attachment(os.path.join(self.output_dir, 'extracted_backup_new'), 'clip.mov'),
            b'movie',
        )
        digest = 'b' * 64

        def run_ffmpeg(command, **_kwargs):
            with open(command[-1], 'wb') as output:
                output.write(b'mp4')
            return SimpleNamespace(returncode=0, stderr='')

        with patch('export_media.hash_media_file', return_value=digest):
            with patch('export_media.shutil.which', return_value='ffmpeg'):
                with patch('export_media.subprocess.run', side_effect=run_ffmpeg) as run:
                    converted_path = convert_mov_to_mp4(source, self.output_dir)

        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-map') + 1], '0:v:0')
        audio_map_index = command.index('-map', command.index('-map') + 1)
        self.assertEqual(command[audio_map_index + 1], '0:a:0?')
        self.assertTrue(os.path.isfile(converted_path))


if __name__ == '__main__':
    unittest.main()
