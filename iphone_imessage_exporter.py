"""GUI and command-line entry points for the iMessage HTML exporter."""

import argparse
import hashlib
import os
import pickle
import queue
import threading
import tkinter as tk

from backup_extractor import extract_iphone_backup
from html_pages import (
    build_conversation_entries,
    build_html,
    build_index,
    build_search_index,
    summarize_messages,
)
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


def export_messages(
    sms_db,
    attachment_db,
    attachment_folder,
    address_book_db,
    output_dir,
    backup_dir=None,
    backup_password=None,
    progress=None,
):
    def report(message):
        if progress:
            progress(message)
        else:
            print(message)

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if backup_dir:
        report('Starting backup extraction...')
        extracted = extract_iphone_backup(
            backup_dir,
            os.path.join(output_dir, 'extracted_backup'),
            backup_password,
            progress,
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
    cache_path = os.path.join(output_dir, f'sms_messages_v3_{cache_key}.pkl')
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
    attachments = normalize_attachment_paths(attachments, attachment_folder)
    messages = attach_to_messages(messages, attachments)
    apply_contact_names(messages, contacts)
    group_participants = fetch_group_participants(sms_db, contacts)
    for message in messages:
        message['group_participants'] = group_participants.get(message['chat_id'], [])
    for phone_number, contact_name in contacts.items():
        chat_names.setdefault(('phone', phone_number), contact_name)
    conversations, id_to_sender = group_messages_by_conversation(messages, chat_names)

    if not conversations:
        raise ValueError('No conversations were found in the provided database files.')

    total_convs = len(conversations)
    report(f'Exporting {total_convs} conversations...')
    print(f'Conversation ID to Sender Mapping:\n{id_to_sender}\n')

    conversion_failures = {}
    conversation_entries = build_conversation_entries(conversations)
    index_entries = []
    report_interval = max(1, total_convs // 50)
    for idx, (conv_key, conv_name, output_filename) in enumerate(conversation_entries, 1):
        conv_data = conversations[conv_key]
        num_msgs = len(conv_data['messages'])
        sender_phone = id_to_sender.get(conv_key, 'Unknown')
        build_html(
            conv_name,
            conv_data['messages'],
            output_dir,
            attachment_folder,
            conversion_failures,
            output_filename,
        )
        index_entries.append((conv_name, output_filename, conv_data['messages']))
        if idx == 1 or idx % report_interval == 0 or idx == total_convs:
            report(f'Exported conversations: {idx}/{total_convs} ({conv_name})')

    overall_stats = summarize_messages(messages)
    overall_stats['conversations'] = total_convs
    report('Building conversation index and search index...')
    build_index(index_entries, output_dir, overall_stats)
    build_search_index(index_entries, output_dir)

    if conversion_failures:
        report(f'Attachment conversion failures: {len(conversion_failures)}')

    report(f'Export complete: {output_dir}')
    return output_dir, total_convs


def launch_gui():
    root = tk.Tk()
    root.title('iMessage HTML Exporter')
    root.resizable(False, False)

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
        if key == 'output_dir':
            entry.insert(0, 'imessage_html')
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

    status = tk.Label(root, text='Enter paths, then select Export.', anchor='w')
    status.grid(row=len(fields), column=0, columnspan=2, padx=12, pady=8, sticky='w')

    log_output = tk.Text(root, width=104, height=12, state='disabled', wrap='word')
    log_scrollbar = tk.Scrollbar(root, command=log_output.yview)
    log_output.config(yscrollcommand=log_scrollbar.set)
    log_output.grid(row=len(fields) + 1, column=0, columnspan=2, padx=(12, 0), pady=6, sticky='nsew')
    log_scrollbar.grid(row=len(fields) + 1, column=2, padx=(0, 12), pady=6, sticky='ns')

    messages = queue.Queue()
    export_button = tk.Button(root, text='Export')
    export_button.grid(row=len(fields) + 2, column=1, padx=12, pady=12, sticky='e')

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

    def run_export():
        paths = {key: entry.get().strip() for key, entry in entries.items()}
        if not paths['backup_dir'] and (not paths['sms_db'] or not paths['address_book_db']):
            status.config(text='SMS Database and Address Book Database paths are required.', fg='red')
            return

        while not messages.empty():
            messages.get_nowait()
        append_log(['Starting export...'])
        status.config(text='Exporting... Please wait.', fg='black')
        export_button.config(state='disabled')

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

    export_button.config(command=run_export)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description='Export iPhone SMS/attachment databases as styled iMessage HTML conversations.'
    )
    parser.add_argument('--sms-db', help='Path to the SMS SQLite database (sms.db)')
    parser.add_argument('--attachment-db', help='Path to the attachment SQLite database (if separate)')
    parser.add_argument('--attachment-folder', help='Base folder path where attachment files are located')
    parser.add_argument('--address-book-db', help='Path to the Address Book SQLite database')
    parser.add_argument('--output-dir', default='imessage_html', help='Directory where HTML output will be written')
    args = parser.parse_args()

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
    )


if __name__ == '__main__':
    main()
