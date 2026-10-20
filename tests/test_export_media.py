import os
import tempfile
import unittest
from pathlib import Path

from export_media import discover_attachment_folders, format_attachment_html


class ExportMediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = self.temporary_dir.name
        self.output_dir = os.path.join(self.root, 'HTML output')
        os.makedirs(self.output_dir)

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_external_image_uses_file_uri(self):
        source = os.path.join(self.root, 'Phone backup', 'photo #1.jpg')
        os.makedirs(os.path.dirname(source))
        with open(source, 'wb') as image:
            image.write(b'image')

        markup = format_attachment_html(
            {
                'filename': 'photo #1.jpg',
                'mime_type': 'image/jpeg',
                'file_path': source,
            },
            self.output_dir,
        )

        self.assertIn(f'src="{Path(source).as_uri()}"', markup)
        self.assertNotIn('src="C:\\', markup)

    def test_assets_in_separate_extractions_use_independent_file_uris(self):
        media_paths = []
        for extraction_name in ('extracted_backup_old', 'extracted_backup_new'):
            media_dir = os.path.join(self.output_dir, extraction_name, 'Media Files')
            os.makedirs(media_dir)
            source = os.path.join(media_dir, 'photo #1.jpg')
            with open(source, 'wb') as image:
                image.write(b'image')
            media_paths.append(source)

        for source in media_paths:
            with self.subTest(source=source):
                markup = format_attachment_html(
                    {
                        'filename': 'photo #1.jpg',
                        'mime_type': 'image/jpeg',
                        'file_path': source,
                    },
                    self.output_dir,
                )
                self.assertIn(f'src="{Path(source).as_uri()}"', markup)

    def test_external_video_uses_file_uri(self):
        source = os.path.join(self.root, 'Phone backup', 'clip #1.mp4')
        os.makedirs(os.path.dirname(source))
        with open(source, 'wb') as video:
            video.write(b'video')

        markup = format_attachment_html(
            {
                'filename': 'clip #1.mp4',
                'mime_type': 'video/mp4',
                'file_path': source,
            },
            self.output_dir,
        )

        self.assertIn(f'<source src="{Path(source).as_uri()}"', markup)

    def test_missing_attachment_resolves_from_another_extraction(self):
        old_attachment_folder = os.path.join(
            self.root,
            'old extraction',
            'MediaDomain',
            'Library',
            'SMS',
            'Attachments',
        )
        old_source = os.path.join(
            old_attachment_folder,
            '14',
            '04',
            'IMG_9443.PNG',
        )
        os.makedirs(os.path.dirname(old_source))
        with open(old_source, 'wb') as image:
            image.write(b'image')

        newer_media_path = os.path.join(
            self.output_dir,
            'extracted_backup_new',
            'MediaDomain',
            'Library',
            'SMS',
            'Attachments',
            '14',
            '04',
            'IMG_9443.PNG',
        )
        previous_page_path = os.path.join(self.output_dir, 'Previous.html')
        with open(previous_page_path, 'w', encoding='utf-8') as previous_page:
            previous_page.write(f'<img src="{old_source}">')

        discovered_folders = discover_attachment_folders(self.output_dir)
        self.assertIn(old_attachment_folder, discovered_folders)
        markup = format_attachment_html(
            {
                'filename': '~/Library/SMS/Attachments/14/04/IMG_9443.PNG',
                'mime_type': 'image/png',
                'file_path': newer_media_path,
            },
            self.output_dir,
            fallback_attachment_folders=discovered_folders,
        )

        self.assertIn(f'src="{Path(old_source).as_uri()}"', markup)


if __name__ == '__main__':
    unittest.main()
