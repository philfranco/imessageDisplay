"""GUI and command-line entry points for the iMessage HTML exporter."""

import argparse
import datetime
import glob
import hashlib
import os
import pickle
import queue
import threading
import tkinter as tk
from tkinter import ttk

from backup_extractor import CALL_HISTORY_DB_PATH, extract_iphone_backup
from call_history import fetch_call_history
from export_media import discover_attachment_folders
from html_pages import (
    build_attachments_page,
    build_birthdays,
    build_birthday_wishes,
    build_call_history,
    build_conversation_entries,
    build_html,
    build_index,
    build_search_index,
    collect_conversation_metrics,
    summarize_messages,
)
from gui_preferences import load_preferences, save_preferences
from message_archive import archive_is_empty, merge_messages
from sms_database import (
    apply_contact_names,
    attach_to_messages,
    fetch_attachments,
    fetch_contacts,
    fetch_group_participants,
    fetch_sms_messages,
    group_messages_by_conversation,
    normalize_attachment_paths,
)
from sticker_database import extract_sticker_previews, resolve_missing_sticker_previews
from time_zone_utils import DEFAULT_TIME_ZONE, available_time_zones, get_time_zone


def export_messages(
    sms_db,
    attachment_db,
    attachment_folder,
    address_book_db,
    output_dir,
    backup_dir=None,
    backup_password=None,
    progress=None,
    time_zone=DEFAULT_TIME_ZONE,
):
    get_time_zone(time_zone)

    def report(message):
        if progress:
            progress(message)
        else:
            print(message)

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    extraction_id = datetime.datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')
    conversion_output_dir = output_dir

    if backup_dir:
        existing_extractions = sorted(
            path for path in glob.glob(os.path.join(output_dir, 'extracted_backup_*'))
            if os.path.isdir(path)
        )
        report('Starting backup extraction...')
        extraction_dir = os.path.join(output_dir, f'extracted_backup_{extraction_id}')
        conversion_output_dir = extraction_dir
        extracted = extract_iphone_backup(
            backup_dir,
            extraction_dir,
            backup_password,
            progress,
            existing_media_dirs=[
                os.path.join(
                    existing_dir,
                    'MediaDomain',
                    'Library',
                    'SMS',
                    'Attachments',
                )
                for existing_dir in existing_extractions
            ],
        )
        sms_db = extracted['sms_db']
        attachment_db = extracted['attachment_db']
        attachment_folder = extracted['attachment_folder']
        address_book_db = extracted['address_book_db']

    report('Reading contacts...')
    contacts = fetch_contacts(address_book_db)

    source_stat = os.stat(sms_db)
    cache_key = hashlib.sha256(
        f'{os.path.normcase(os.path.abspath(sms_db))}:{source_stat.st_mtime_ns}:{source_stat.st_size}'.encode('utf-8')
    ).hexdigest()[:12]
    cache_path = os.path.join(output_dir, f'sms_messages_v4_{extraction_id}_{cache_key}.pkl')
    write_cache = True
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as cache_file:
                messages, chat_names = pickle.load(cache_file)
            report(f'Loaded cached messages from: {cache_path}')
            write_cache = False
        except Exception as error:
            report(f'Failed to load cache ({cache_path}), refetching: {error}')
            report('Reading messages from SMS database...')
            messages, chat_names = fetch_sms_messages(sms_db)
    else:
        report('Reading messages from SMS database...')
        messages, chat_names = fetch_sms_messages(sms_db)

    if write_cache:
        try:
            with open(cache_path, 'wb') as cache_file:
                pickle.dump((messages, chat_names), cache_file)
        except Exception as error:
            report(f'Could not write cache ({cache_path}): {error}')

    report('Reading attachments and grouping conversations...')
    attachments = fetch_attachments(attachment_db or sms_db)
    attachments = normalize_attachment_paths(
        attachments,
        attachment_folder,
        extracted.get('sticker_cache_folder') if backup_dir else None,
    )
    sticker_database_candidates = (
        [extracted.get('sticker_database')]
        + [
            os.path.join(
                existing_dir,
                'HomeDomain',
                'Library',
                'Stickers',
                'stickers.stickerdb',
            )
            for existing_dir in existing_extractions
        ]
        if backup_dir
        else []
    )
    sticker_database = next(
        (
            path for path in sticker_database_candidates
            if path and os.path.isfile(path)
        ),
        None,
    )
    if sticker_database:
        sticker_previews = extract_sticker_previews(
            sticker_database,
            os.path.join(
                conversion_output_dir,
                'HomeDomain',
                'Library',
                'Stickers',
                'extracted_previews',
            ),
        )
        resolve_missing_sticker_previews(attachments, sticker_previews)
    attachment_path_map = extracted.get('attachment_path_map', {}) if backup_dir else {}
    for attachment_list in attachments.values():
        for attachment in attachment_list:
            file_path = attachment.get('file_path')
            if file_path:
                canonical_path = attachment_path_map.get(
                    os.path.normcase(os.path.abspath(file_path))
                )
                if canonical_path:
                    attachment['file_path'] = canonical_path
    if backup_dir:
        for attachment_list in attachments.values():
            for attachment in attachment_list:
                attachment['conversion_dir'] = conversion_output_dir
    messages = attach_to_messages(messages, attachments)
    apply_contact_names(messages, contacts)
    group_participants = fetch_group_participants(sms_db, contacts)
    for message in messages:
        message['group_participants'] = group_participants.get(message['chat_id'], [])
    for phone_number, contact_name in contacts.items():
        chat_names.setdefault(('phone', phone_number), contact_name)

    legacy_message_batches = []
    legacy_chat_names = {}
    if archive_is_empty(output_dir):
        legacy_cache_paths = sorted(
            glob.glob(os.path.join(output_dir, 'sms_messages_v3_*.pkl'))
        )
        for legacy_cache_path in legacy_cache_paths:
            try:
                with open(legacy_cache_path, 'rb') as cache_file:
                    cached_messages, cached_chat_names = pickle.load(cache_file)
                if not isinstance(cached_messages, list) or not isinstance(cached_chat_names, dict):
                    raise ValueError('The legacy message cache has an unexpected format.')
                legacy_message_batches.append(cached_messages)
                for key, name in cached_chat_names.items():
                    legacy_chat_names.setdefault(key, name)
                report(f'Migrated messages from legacy cache: {legacy_cache_path}')
            except Exception as error:
                report(f'Could not migrate legacy cache ({legacy_cache_path}): {error}')

    legacy_chat_names.update(chat_names)
    messages, chat_names, imported_count, archived_count = merge_messages(
        output_dir, messages, legacy_chat_names, legacy_message_batches
    )
    report(
        f'Merged {imported_count} messages from this backup; '
        f'{archived_count} messages retained in the archive.'
    )
    result = _render_html(
        messages,
        chat_names,
        output_dir,
        attachment_folder,
        progress,
        time_zone,
    )
    return result


def regenerate_html(output_dir, progress=None, time_zone=DEFAULT_TIME_ZONE):
    """Rebuild HTML from the existing archive without opening or extracting a backup."""
    get_time_zone(time_zone)
    output_dir = os.path.abspath(output_dir)
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f'Archive output folder not found: {output_dir}')
    if archive_is_empty(output_dir):
        raise ValueError(f'No messages found in the archive at: {output_dir}')

    messages, chat_names, _, _ = merge_messages(output_dir, [], {})
    return _render_html(messages, chat_names, output_dir, None, progress, time_zone)


def _render_html(
    messages,
    chat_names,
    output_dir,
    attachment_folder,
    progress=None,
    time_zone=DEFAULT_TIME_ZONE,
):
    def report(message):
        if progress:
            progress(message)
        else:
            print(message)

    get_time_zone(time_zone)
    conversations, id_to_sender = group_messages_by_conversation(messages, chat_names)

    if not conversations:
        raise ValueError('No conversations were found in the provided database files.')

    total_convs = len(conversations)
    report(f'Exporting {total_convs} conversations...')
    print(f'Conversation ID to Sender Mapping:\n{id_to_sender}\n')

    conversion_failures = {}
    fallback_attachment_folders = discover_attachment_folders(output_dir)
    if fallback_attachment_folders:
        report(
            f'Found {len(fallback_attachment_folders)} previous attachment extraction '
            'folder(s) for missing media paths.'
        )
    conversation_entries = build_conversation_entries(conversations)
    index_entries = []
    report_interval = max(1, total_convs // 50)
    for idx, (conv_key, conv_name, output_filename) in enumerate(conversation_entries, 1):
        conv_data = conversations[conv_key]
        build_html(
            conv_name,
            conv_data['messages'],
            output_dir,
            attachment_folder,
            conversion_failures,
            output_filename,
            time_zone,
            fallback_attachment_folders,
        )
        index_entries.append((conv_name, output_filename, conv_data['messages']))
        if idx == 1 or idx % report_interval == 0 or idx == total_convs:
            report(f'Exported conversations: {idx}/{total_convs} ({conv_name})')

    report('Building the attachments page...')
    build_attachments_page(
        index_entries,
        output_dir,
        attachment_folder,
        conversion_failures,
        time_zone,
        fallback_attachment_folders,
    )

    overall_stats = summarize_messages(messages, time_zone)
    overall_stats['conversations'] = total_convs
    call_history_sources = []
    for extraction_dir in sorted(glob.glob(os.path.join(output_dir, 'extracted_backup_*'))):
        if not os.path.isdir(extraction_dir):
            continue
        call_history_db = os.path.join(
            extraction_dir,
            'HomeDomain',
            *CALL_HISTORY_DB_PATH.split('/'),
        )
        if not os.path.isfile(call_history_db):
            continue
        address_book_db = os.path.join(
            extraction_dir,
            'HomeDomain',
            'Library',
            'AddressBook',
            'AddressBook.sqlitedb',
        )
        contacts = fetch_contacts(address_book_db) if os.path.isfile(address_book_db) else {}
        call_history_sources.append((call_history_db, contacts))
    calls = fetch_call_history(call_history_sources, time_zone)

    report('Building conversation index, search index, and birthday pages...')
    conversation_metrics = collect_conversation_metrics(index_entries, time_zone)
    build_index(
        index_entries,
        output_dir,
        overall_stats,
        time_zone,
        calls=calls,
        conversation_metrics=conversation_metrics,
    )
    build_search_index(
        index_entries,
        output_dir,
        time_zone,
        conversation_metrics=conversation_metrics,
    )
    build_birthdays(index_entries, output_dir, time_zone)
    build_birthday_wishes(index_entries, output_dir, time_zone)
    build_call_history(calls, output_dir, time_zone)

    if conversion_failures:
        report(f'Attachment conversion failures: {len(conversion_failures)}')

    report(f'Export complete: {output_dir}')
    return output_dir, total_convs


def launch_gui():
    root = tk.Tk()
    root.title('iMessage HTML Exporter')
    root.resizable(False, False)
    preferences_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.imessage_exporter')
    preference_error = None
    try:
        saved_preferences = load_preferences(preferences_path)
    except (OSError, ValueError) as error:
        saved_preferences = {}
        preference_error = f'Could not load saved settings: {error}'

    fields = (
        ('iTunes Backup Folder', 'backup_dir'),
        ('Backup Password (encrypted backups)', 'backup_password'),
        ('SMS Database  (optional)', 'sms_db'),
        ('Attachment Database (optional)', 'attachment_db'),
        ('Attachment Folder (optional)', 'attachment_folder'),
        ('Address Book Database  (optional)', 'address_book_db'),
        ('Output Folder', 'output_dir'),
    )
    entries = {}

    for row, (label, key) in enumerate(fields):
        tk.Label(root, text=label).grid(row=row, column=0, padx=12, pady=6, sticky='w')
        entry = tk.Entry(root, width=64, show='*' if key == 'backup_password' else '')
        entry.grid(row=row, column=1, padx=12, pady=6)
        default_value = 'imessage_html' if key == 'output_dir' else ''
        entry.insert(0, saved_preferences.get(key, default_value))
        entries[key] = entry

        if key in ('backup_dir', 'output_dir'):
            def browse_path(field_key=key):
                selected = root.tk.call('tk_chooseDirectory', '-mustexist', True)
                if selected:
                    entries[field_key].delete(0, tk.END)
                    entries[field_key].insert(0, selected)

            tk.Button(root, text='Browse...', command=browse_path).grid(
                row=row, column=2, padx=(0, 12), pady=6
            )

    time_zone_row = len(fields)
    tk.Label(root, text='Time Zone (IANA; daylight-saving aware)').grid(
        row=time_zone_row, column=0, padx=12, pady=6, sticky='w'
    )
    time_zone_options = available_time_zones()
    saved_time_zone = saved_preferences.get('time_zone', DEFAULT_TIME_ZONE)
    if saved_time_zone not in time_zone_options:
        preference_error = (
            f'Saved time zone "{saved_time_zone}" is unavailable; using {DEFAULT_TIME_ZONE}.'
        )
        saved_time_zone = DEFAULT_TIME_ZONE
    time_zone_selector = ttk.Combobox(
        root,
        width=61,
        values=time_zone_options,
        state='readonly',
    )
    time_zone_selector.set(saved_time_zone)
    time_zone_selector.grid(row=time_zone_row, column=1, padx=12, pady=6, sticky='w')

    status = tk.Label(
        root,
        text=preference_error or (
            'Each backup is extracted separately; reuse this output folder to merge HTML.'
        ),
        fg='red' if preference_error else 'black',
        anchor='w',
    )
    status.grid(row=time_zone_row + 1, column=0, columnspan=2, padx=12, pady=8, sticky='w')

    log_output = tk.Text(root, width=104, height=12, state='disabled', wrap='word')
    log_scrollbar = tk.Scrollbar(root, command=log_output.yview)
    log_output.config(yscrollcommand=log_scrollbar.set)
    log_output.grid(row=time_zone_row + 2, column=0, columnspan=2, padx=(12, 0), pady=6, sticky='nsew')
    log_scrollbar.grid(row=time_zone_row + 2, column=2, padx=(0, 12), pady=6, sticky='ns')

    messages = queue.Queue()
    export_button = tk.Button(root, text='Export')
    export_button.grid(row=time_zone_row + 3, column=1, padx=12, pady=12, sticky='e')
    rebuild_button = tk.Button(root, text='Rebuild HTML from archive')
    rebuild_button.grid(row=time_zone_row + 3, column=0, padx=12, pady=12, sticky='w')

    def append_log(lines):
        if not lines:
            return
        log_output.config(state='normal')
        log_output.insert('end', '\n'.join(lines) + '\n')
        line_count = int(log_output.index('end-1c').split('.')[0])
        if line_count > 1000:
            log_output.delete('1.0', f'{line_count - 1000}.0')
        log_output.see('end')
        log_output.config(state='disabled')

    def save_form_preferences():
        paths = {key: entry.get().strip() for key, entry in entries.items()}
        paths['time_zone'] = time_zone_selector.get()
        try:
            save_preferences(preferences_path, paths)
        except OSError as error:
            status.config(text=f'Could not save GUI settings: {error}', fg='red')
            append_log([f'Could not save GUI settings: {error}'])
            return False
        return True

    def close_window():
        if save_form_preferences():
            root.destroy()

    def run_export():
        paths = {key: entry.get().strip() for key, entry in entries.items()}
        time_zone = time_zone_selector.get()
        if not paths['backup_dir'] and (not paths['sms_db'] or not paths['address_book_db']):
            status.config(text='SMS Database and Address Book Database paths are required.', fg='red')
            return

        while not messages.empty():
            messages.get_nowait()
        append_log(['Starting export...'])
        save_form_preferences()
        status.config(text='Exporting... Please wait.', fg='black')
        export_button.config(state='disabled')
        rebuild_button.config(state='disabled')

        def worker():
            try:
                result = export_messages(
                    paths['sms_db'],
                    paths['attachment_db'],
                    paths['attachment_folder'] or None,
                    paths['address_book_db'] or None,
                    paths['output_dir'] or 'imessage_html',
                    paths['backup_dir'] or None,
                    paths['backup_password'] or None,
                    messages.put,
                    time_zone,
                )
            except Exception as error:
                print(f'Export failed: {error}')
                messages.put(('error', str(error)))
            else:
                messages.put(('complete', result))

        threading.Thread(target=worker, daemon=True).start()
        poll_messages()

    def poll_messages():
        log_lines = []
        result = None
        while True:
            try:
                message = messages.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, tuple):
                result = message
            else:
                log_lines.append(message)

        append_log(log_lines)
        if result:
            export_button.config(state='normal')
            rebuild_button.config(state='normal')
            if result[0] == 'error':
                status.config(text=f'Export failed: {result[1]}', fg='red')
            else:
                output_path, conversation_count = result[1]
                status.config(
                    text=f'Exported {conversation_count} conversations to {output_path}',
                    fg='green',
                )
            return

        root.after(150, poll_messages)

    def run_rebuild():
        output_dir = entries['output_dir'].get().strip() or 'imessage_html'
        time_zone = time_zone_selector.get()
        save_form_preferences()
        while not messages.empty():
            messages.get_nowait()
        append_log(['Rebuilding HTML from the existing archive...'])
        status.config(text='Rebuilding HTML... Please wait.', fg='black')
        export_button.config(state='disabled')
        rebuild_button.config(state='disabled')

        def worker():
            try:
                result = regenerate_html(output_dir, messages.put, time_zone)
            except Exception as error:
                print(f'HTML rebuild failed: {error}')
                messages.put(('error', str(error)))
            else:
                messages.put(('complete', result))

        threading.Thread(target=worker, daemon=True).start()
        poll_messages()

    export_button.config(command=run_export)
    rebuild_button.config(command=run_rebuild)
    root.protocol('WM_DELETE_WINDOW', close_window)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Export iPhone SMS/attachment databases as styled iMessage HTML conversations. '
            'Each backup is extracted separately; reuse an output folder to merge its HTML archive.'
        )
    )
    parser.add_argument('--sms-db', help='Path to the SMS SQLite database (sms.db)')
    parser.add_argument('--attachment-db', help='Path to the attachment SQLite database (if separate)')
    parser.add_argument('--attachment-folder', help='Base folder path where attachment files are located')
    parser.add_argument('--address-book-db', help='Path to the Address Book SQLite database')
    parser.add_argument(
        '--output-dir',
        default='imessage_html',
        help='HTML output and persistent archive directory; reuse it to merge backups',
    )
    parser.add_argument(
        '--rebuild-html',
        action='store_true',
        help='Rebuild index and conversation HTML from the existing archive without re-extracting a backup',
    )
    parser.add_argument(
        '--time-zone',
        default=DEFAULT_TIME_ZONE,
        help='IANA time zone for displayed message timestamps (default: America/New_York)',
    )
    args = parser.parse_args()

    if args.rebuild_html:
        regenerate_html(args.output_dir, time_zone=args.time_zone)
        return

    if not args.sms_db:
        launch_gui()
        return
    if not args.address_book_db:
        parser.error('--address-book-db is required when using command-line mode')

    export_messages(
        args.sms_db,
        args.attachment_db,
        args.attachment_folder,
        args.address_book_db,
        args.output_dir,
        time_zone=args.time_zone,
    )


if __name__ == '__main__':
    main()
