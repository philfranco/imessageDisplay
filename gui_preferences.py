"""Load and save non-sensitive GUI path preferences."""

import json
import os
import tempfile


PREFERENCE_KEYS = (
    'backup_dir',
    'sms_db',
    'attachment_db',
    'attachment_folder',
    'address_book_db',
    'output_dir',
)


def load_preferences(path):
    try:
        with open(path, 'r', encoding='utf-8') as preferences_file:
            preferences = json.load(preferences_file)
    except FileNotFoundError:
        return {}

    if not isinstance(preferences, dict):
        raise ValueError('Saved exporter preferences must be a JSON object.')

    return {
        key: value
        for key, value in preferences.items()
        if key in PREFERENCE_KEYS and isinstance(value, str)
    }


def save_preferences(path, values):
    preferences = {
        key: values[key]
        for key in PREFERENCE_KEYS
        if key in values and isinstance(values[key], str)
    }
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary_path = tempfile.mkstemp(dir=directory, prefix='.imessage_exporter_')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as preferences_file:
            json.dump(preferences, preferences_file, indent=2)
            preferences_file.write('\n')
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
