# iMessage Display

A Python tool for extracting iPhone backup data and turning SMS/iMessage conversations into a searchable, browser-friendly HTML archive.

## Features

- Extracts messages, attachments, contacts, and call history from an iTunes/Finder iPhone backup, including password-protected backups.
- Creates an HTML page for each conversation, along with an index, search page, and call-history page.
- Supports searching and filtering conversations by message text, date, and time.
- Merges messages from successive backups into a persistent SQLite archive instead of replacing earlier imports.
- Converts HEIC/HEIF images to JPEG and MOV videos to MP4 for browser previews.
- Reuses matching extracted attachments and media conversions across backup extractions when possible.
- Offers both a desktop GUI and a command-line interface.

## Requirements

- Python 3.9 or later.
- FFmpeg on `PATH` to convert MOV videos.
- The Python packages listed in [`requirements.txt`](requirements.txt).
- A Windows installation with time-zone data may also need the `tzdata` package, which is included in the requirements.

HEIC/HEIF conversion requires Pillow and `pillow-heif`. If these optional packages are not installed, the exporter reports conversion failures and cannot create those image previews.

## Install

Clone the repository, then from its directory create and activate a virtual environment and install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install FFmpeg separately and make sure `ffmpeg` is available on `PATH` if you want MOV-to-MP4 conversion.

## Use the GUI

Run the exporter without command-line database arguments:

```powershell
python iphone_imessage_exporter.py
```

Select the iPhone backup, enter its password if it is encrypted, and choose an output folder. The exporter extracts the backup and writes the HTML archive there.

## Use the command line

To read databases and attachments that have already been extracted:

```powershell
python iphone_imessage_exporter.py `
  --sms-db "C:\path\to\sms.db" `
  --address-book-db "C:\path\to\AddressBook.sqlitedb" `
  --attachment-db "C:\path\to\attachment.db" `
  --attachment-folder "C:\path\to\Attachments" `
  --output-dir "C:\path\to\imessage_html" `
  --time-zone "America/New_York"
```

`--attachment-db` and `--attachment-folder` are optional when the attachment records are in `sms.db` or there are no files to resolve. To rebuild the HTML pages from an existing archive without extracting a backup again:

```powershell
python iphone_imessage_exporter.py `
  --rebuild-html `
  --output-dir "C:\path\to\imessage_html" `
  --time-zone "America/New_York"
```

Run `python iphone_imessage_exporter.py --help` for all command-line options.

## Incremental backups and media reuse

Use the **same output folder** when importing later backups. Each backup is extracted into its own `extracted_backup_*` directory. Messages are merged into `messages_archive.sqlite3`, which keeps earlier messages and updates matching message records when they are seen again.

When extracting a later backup, the exporter checks attachment contents against earlier extractions. If identical media already exists, it reuses the earlier attachment rather than writing another copy. During HTML generation, converted HEIC/HEIF and MOV files are named using a content hash. If a matching conversion exists in an earlier extraction, the exporter creates a hard link in the current extraction instead of converting the file again. A hard link is another path to the same file data, so it does not duplicate the media contents.

The original attachments and converted previews live in the extraction directories; the SQLite archive stores message data and attachment references. Keep the output folder and its extraction directories together so existing HTML pages can continue to load their media. If a hard link cannot be created, the exporter reports the error and attempts conversion again.

## Tests

Run the test suite from the repository root:

```powershell
python -m unittest discover -s tests
```

## Privacy

This project processes personal messages, contacts, and attachments. Keep backups and generated output private; do not publish them to a public repository or share them unless you intend to disclose their contents.
