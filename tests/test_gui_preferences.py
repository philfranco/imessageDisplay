import json
import os
import tempfile
import unittest

from gui_preferences import load_preferences, save_preferences


class GuiPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.preferences_path = os.path.join(self.temporary_dir.name, '.imessage_exporter')

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_loads_saved_paths_and_ignores_unrecognized_values(self):
        with open(self.preferences_path, 'w', encoding='utf-8') as preferences_file:
            json.dump(
                {
                    'backup_dir': 'C:\\backups\\phone',
                    'output_dir': 'C:\\exports',
                    'time_zone': 'America/New_York',
                    'backup_password': 'must not restore',
                    'unexpected': 'ignored',
                },
                preferences_file,
            )

        self.assertEqual(
            load_preferences(self.preferences_path),
            {
                'backup_dir': 'C:\\backups\\phone',
                'output_dir': 'C:\\exports',
                'time_zone': 'America/New_York',
            },
        )

    def test_saves_paths_but_never_saves_backup_password(self):
        save_preferences(
            self.preferences_path,
            {
                'backup_dir': 'C:\\backups\\phone',
                'output_dir': 'C:\\exports',
                'time_zone': 'America/New_York',
                'backup_password': 'secret password',
            },
        )

        with open(self.preferences_path, 'r', encoding='utf-8') as preferences_file:
            saved_text = preferences_file.read()

        self.assertNotIn('backup_password', saved_text)
        self.assertNotIn('secret password', saved_text)
        self.assertEqual(
            load_preferences(self.preferences_path),
            {
                'backup_dir': 'C:\\backups\\phone',
                'output_dir': 'C:\\exports',
                'time_zone': 'America/New_York',
            },
        )

    def test_missing_preferences_file_returns_empty_settings(self):
        self.assertEqual(load_preferences(self.preferences_path), {})

    def test_rejects_non_object_preferences(self):
        with open(self.preferences_path, 'w', encoding='utf-8') as preferences_file:
            json.dump(['not', 'an', 'object'], preferences_file)

        with self.assertRaises(ValueError):
            load_preferences(self.preferences_path)


if __name__ == '__main__':
    unittest.main()
