"""Render conversation, index, and search HTML pages."""

import hashlib
import html
import os
from collections import defaultdict

from export_media import format_attachment_html
from sms_database import sanitize_filename



def build_html(
    conversation_name,
    messages,
    output_dir,
    attachment_folder=None,
    conversion_failures=None,
    output_filename=None,
):
    if conversion_failures is None:
        conversion_failures = {}

    safe_name = output_filename or sanitize_filename(conversation_name)
    filename = os.path.join(output_dir, f'{safe_name}.html')
    stats = summarize_messages(messages)

    html_content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        f'  <title>{html.escape(conversation_name)}</title>',
        '  <style>',
        '    body { min-height: 100vh; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; background: #f2f2f7; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1100px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #ffffff; transition: background .15s, color .15s, border-color .15s; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 42px); margin-bottom: 26px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .eyebrow { margin: 0 0 10px; color: #bfdbfe; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }',
        '    h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); letter-spacing: -.03em; overflow-wrap: anywhere; }',
        '    .conversation-summary { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }',
        '    .conversation-summary span { padding: 7px 11px; border: 1px solid #ffffff4d; border-radius: 999px; background: #ffffff1c; color: #eff6ff; font-size: 13px; }',
        '    .message-list { padding: 20px; border: 1px solid #e2e8f0; border-radius: 18px; background: #ffffffb8; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .message { display: flex; margin-bottom: 14px; }',
        '    .message.me { justify-content: flex-end; }',
        '    .bubble { max-width: min(78%, 760px); padding: 12px 15px; border-radius: 20px; line-height: 1.5; position: relative; overflow-wrap: anywhere; box-shadow: 0 1px 3px #0f172a12; }',
        '    .bubble.me { background: #2563eb; color: white; border-bottom-right-radius: 6px; border-bottom-left-radius: 20px; }',
        '    .bubble.other { background: #e2e8f0; color: #172033; border-bottom-left-radius: 6px; border-bottom-right-radius: 20px; }',
        '    .meta { font-size: 12px; color: #64748b; margin-top: 6px; }',
        '    .bubble.me .meta { color: #dbeafe; }',
        '    .attachment { margin-top: 8px; font-size: 13px; color: #334155; }',
        '    .attachment img { max-width: 100%; border-radius: 12px; margin-top: 4px; }',
        '    .attachment video { max-width: 100%; max-height: 480px; border-radius: 12px; margin-top: 4px; }',
        '    .attachment-meta { font-size: 11px; color: #666; margin-top: 4px; }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } .message-list { padding: 12px 8px; border-radius: 14px; } .bubble { max-width: 88%; padding: 10px 12px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="search.html">← Back to search</a><a href="index.html">Index</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage conversation</p>',
        f'      <h1>{html.escape(conversation_name)}</h1>',
        '      <div class="conversation-summary">',
        f'        <span>{stats["messages"]:,} messages</span>',
        f'        <span>{stats["attachments"]:,} attachments</span>',
        f'        <span>{html.escape(stats["first_date"])} – {html.escape(stats["last_date"])}</span>',
        '      </div>',
        '    </header>',
        '    <main class="message-list">',
    ]

    for msg in messages:
        bubble_class = 'me' if msg['is_from_me'] else 'other'
        text = html.escape(msg['text'] or '')
        if not text and not msg['attachments']:
            text = '[No text]'
        attachments_html = ''.join(
            format_attachment_html(att, output_dir, attachment_folder, conversion_failures)
            for att in msg['attachments']
        )
        sender = 'Me' if msg['is_from_me'] else html.escape(str(msg['sender']))

        html_content.append(f'    <div class="message {bubble_class}">')
        html_content.append(f'      <div class="bubble {bubble_class}">')
        html_content.append(f'        <div>{text}</div>')
        if attachments_html:
            html_content.append(f'        {attachments_html}')
        html_content.append(f'        <div class="meta">{sender} • {html.escape(msg["date"])}</div>')
        html_content.append('      </div>')
        html_content.append('    </div>')

    html_content.extend([
        '    </main>',
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_content))

    return filename


def build_conversation_entries(conversations):
    titles = {
        key: conv_data['name'] or str(key)
        for key, conv_data in conversations.items()
    }
    base_names = {key: sanitize_filename(title) for key, title in titles.items()}
    base_name_counts = defaultdict(int)
    for base_name in base_names.values():
        base_name_counts[base_name.casefold()] += 1

    entries = []
    used_filenames = set()
    for key, title in titles.items():
        filename = base_names[key]
        display_name = title
        if base_name_counts[filename.casefold()] > 1:
            key_type, key_value = key
            if key_type == 'phone' and len(str(key_value)) == 10:
                phone = str(key_value)
                display_name = f'{title} (+1 ({phone[:3]}) {phone[3:6]}-{phone[6:]})'
            else:
                display_name = f'{title} ({key_type})'
            suffix = hashlib.sha256(repr(key).encode('utf-8')).hexdigest()[:8]
            filename = f'{filename[:100]}_{suffix}'

        if filename.casefold() in used_filenames:
            suffix = hashlib.sha256(repr(key).encode('utf-8')).hexdigest()[:12]
            filename = f'{filename[:95]}_{suffix}'
        used_filenames.add(filename.casefold())
        entries.append((key, display_name, filename))

    return entries


def summarize_messages(messages):
    dates = [
        str(message.get('date'))
        for message in messages
        if message.get('date') and message.get('date') != 'Unknown'
    ]
    return {
        'messages': len(messages),
        'attachments': sum(len(message.get('attachments', [])) for message in messages),
        'first_date': min(dates) if dates else '—',
        'last_date': max(dates) if dates else '—',
    }


def build_index(conversations, output_dir, overall_stats):
    index_path = os.path.join(output_dir, 'index.html')
    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <title>iMessage Conversations</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; padding: 0; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1400px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #ffffff; transition: background .15s, color .15s, border-color .15s; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 48px); margin-bottom: 26px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .eyebrow { margin: 0 0 10px; color: #bfdbfe; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }',
        '    h1 { margin: 0; font-size: clamp(30px, 4vw, 42px); letter-spacing: -.03em; }',
        '    .page-header p:last-child { max-width: 680px; margin: 10px 0 0; color: #e0f2fe; font-size: 16px; line-height: 1.55; }',
        '    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }',
        '    .stat { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px #0001; }',
        '    .stat strong { display: block; font-size: 22px; color: #111; }',
        '    .stat span { color: #666; font-size: 13px; }',
        '    .search-link { display: inline-flex; align-items: center; gap: 8px; margin-top: 8px; padding: 12px 18px; border-radius: 12px; color: #fff; background: #2563eb; text-decoration: none; font-size: 15px; font-weight: 600; box-shadow: 0 5px 14px #2563eb33; transition: background .15s, transform .15s; }',
        '    .search-link:hover { background: #1d4ed8; transform: translateY(-1px); }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage archive</p>',
        '      <h1>Your conversations</h1>',
        '      <p>A snapshot of your message history. Search the archive to find a specific conversation.</p>',
        '    </header>',
        '    <main>',
        '    <section class="stats" aria-label="Database statistics">',
        f'      <div class="stat"><strong>{overall_stats["conversations"]:,}</strong><span>Conversations</span></div>',
        f'      <div class="stat"><strong>{overall_stats["messages"]:,}</strong><span>Messages</span></div>',
        f'      <div class="stat"><strong>{overall_stats["attachments"]:,}</strong><span>Attachments</span></div>',
        f'      <div class="stat"><strong>{html.escape(overall_stats["first_date"])}</strong><span>First message</span></div>',
        f'      <div class="stat"><strong>{html.escape(overall_stats["last_date"])}</strong><span>Last message</span></div>',
        '    </section>',
        '    <a class="search-link" href="search.html">Search conversations <span aria-hidden="true">→</span></a>',
        '    </main>',
        '  </div>',
        '</body>',
        '</html>'
    ]

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return index_path


def build_search_index(conversations, output_dir):
    search_path = os.path.join(output_dir, 'search.html')
    conv_list = sorted(conversations, key=lambda entry: entry[0].lower())

    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <title>Search iMessage Conversations</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; padding: 0; }',
        '    body { min-height: 100vh; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1800px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #ffffff; transition: background .15s, color .15s, border-color .15s; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 48px); margin-bottom: 26px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .eyebrow { margin: 0 0 10px; color: #bfdbfe; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }',
        '    h1 { margin: 0; font-size: clamp(30px, 4vw, 42px); letter-spacing: -.03em; }',
        '    .page-header p:last-child { max-width: 680px; margin: 10px 0 0; color: #e0f2fe; font-size: 16px; line-height: 1.55; }',
        '    .search-box { margin-bottom: 18px; }',
        '    input { width: 100%; padding: 14px 16px; font-size: 16px; border: 1px solid #cbd5e1; border-radius: 12px; box-sizing: border-box; box-shadow: 0 2px 8px #0f172a0a; }',
        '    input:focus { outline: 3px solid #93c5fd; border-color: #2563eb; }',
        '    .results-count { font-size: 14px; color: #64748b; margin-bottom: 12px; }',
        '    .table-wrap { overflow-x: auto; border-radius: 14px; box-shadow: 0 4px 18px #0f172a0d; }',
        '    table { width: 100%; border-collapse: collapse; background: white; }',
        '    th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e5ea; }',
        '    th { background: #f1f5f9; color: #475569; font-size: 13px; white-space: nowrap; }',
        '    th button { border: 0; padding: 0; background: none; color: inherit; font: inherit; font-weight: 600; cursor: pointer; }',
        '    th button:hover { color: #2563eb; }',
        '    .sort-indicator { margin-left: 4px; }',
        '    td { font-size: 14px; color: #334155; vertical-align: top; }',
        '    td a { color: #2563eb; text-decoration: none; font-size: 16px; font-weight: 600; }',
        '    td a:hover { text-decoration: underline; }',
        '    td.participants { min-width: 220px; color: #64748b; line-height: 1.5; }',
        '    tbody tr:hover { background: #f8fafc; }',
        '    tr:last-child td { border-bottom: 0; }',
        '    .hidden { display: none; }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } th, td { padding: 9px 7px; font-size: 12px; } td a { font-size: 13px; } td.participants { min-width: 160px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage archive</p>',
        '      <h1>Find a conversation</h1>',
        '      <p>Search, sort, and explore your conversations and message history.</p>',
        '    </header>',
        '    <div class="search-box">',
        '      <input type="text" id="searchInput" placeholder="Search for a person or name...">',
        '    </div>',
        '    <div class="results-count"><span id="resultCount">Showing all</span> conversations</div>',
        '    <div class="table-wrap"><table><thead><tr>',
        '      <th scope="col"><button type="button" data-sort-key="name" aria-sort="none">Conversation <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="participants" aria-sort="none">People in group <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="messages" aria-sort="none">Messages <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="attachments" aria-sort="none">Attachments <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="first-date" aria-sort="none">First message <span class="sort-indicator"></span></button></th>',
        '      <th scope="col"><button type="button" data-sort-key="last-date" aria-sort="none">Last message <span class="sort-indicator"></span></button></th>',
        '    </tr></thead>',
        '    <tbody id="conversationList">',
    ]

    for display_name, filename, messages in conv_list:
        stats = summarize_messages(messages)
        is_group = any(
            isinstance(message.get('chat_id'), tuple) and message['chat_id'][0] == 'group'
            for message in messages
        )
        participant_names = sorted({
            name
            for message in messages
            for name in message.get('group_participants', [])
        }, key=str.casefold) if is_group else []
        participants_text = ', '.join(participant_names)
        searchable_name = f'{display_name} {participants_text}'.lower()
        content.append(
            f'      <tr class="conv-item" data-name="{html.escape(searchable_name, quote=True)}" '
            f'data-sort-name="{html.escape(display_name.lower())}" '
            f'data-sort-participants="{html.escape(participants_text.lower(), quote=True)}" '
            f'data-sort-messages="{stats["messages"]}" data-sort-attachments="{stats["attachments"]}" '
            f'data-sort-first-date="{html.escape(stats["first_date"])}" '
            f'data-sort-last-date="{html.escape(stats["last_date"])}">'
            f'<td><a href="{filename}.html">{html.escape(display_name)}</a></td>'
            f'<td class="participants">{html.escape(participants_text) if participants_text else "—"}</td>'
            f'<td>{stats["messages"]:,}</td><td>{stats["attachments"]:,}</td>'
            f'<td>{html.escape(stats["first_date"])}</td><td>{html.escape(stats["last_date"])}</td></tr>'
        )

    content.extend([
        '    </tbody></table></div>',
        '    <script>',
        '      const searchInput = document.getElementById("searchInput");',
        '      const conversationList = document.getElementById("conversationList");',
        '      const conversationItems = conversationList.querySelectorAll(".conv-item");',
        '      const resultCount = document.getElementById("resultCount");',
        '      const totalConversations = conversationItems.length;',
        '      const sortButtons = document.querySelectorAll("th button[data-sort-key]");',
        '      let activeSortKey = "";',
        '      let sortAscending = true;',
        '      ',
        '      sortButtons.forEach(function(button) {',
        '        button.addEventListener("click", function() {',
        '          const sortKey = this.getAttribute("data-sort-key");',
        '          if (activeSortKey === sortKey) {',
        '            sortAscending = !sortAscending;',
        '          } else {',
        '            activeSortKey = sortKey;',
        '            sortAscending = true;',
        '          }',
        '          sortButtons.forEach(function(sortButton) {',
        '            const isActive = sortButton === button;',
        '            sortButton.setAttribute("aria-sort", isActive ? (sortAscending ? "ascending" : "descending") : "none");',
        '            sortButton.querySelector(".sort-indicator").textContent = isActive ? (sortAscending ? "▲" : "▼") : "";',
        '          });',
        '          const sortAttribute = "data-sort-" + sortKey;',
        '          const sortedItems = Array.from(conversationItems).sort(function(left, right) {',
        '            const leftValue = left.getAttribute(sortAttribute) || "";',
        '            const rightValue = right.getAttribute(sortAttribute) || "";',
        '            let comparison;',
        '            if (sortKey === "messages" || sortKey === "attachments") {',
        '              comparison = Number(leftValue) - Number(rightValue);',
        '            } else {',
        '              comparison = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });',
        '            }',
        '            return (sortAscending ? comparison : -comparison) ||',
        '              left.getAttribute("data-sort-name").localeCompare(right.getAttribute("data-sort-name"));',
        '          });',
        '          sortedItems.forEach(function(item) { conversationList.appendChild(item); });',
        '        });',
        '      });',
        '      ',
        '      searchInput.addEventListener("input", function() {',
        '        const searchTerm = this.value.toLowerCase().trim();',
        '        let visibleCount = 0;',
        '        ',
        '        conversationItems.forEach(function(item) {',
        '          const name = item.getAttribute("data-name");',
        '          if (searchTerm === "" || name.includes(searchTerm)) {',
        '            item.classList.remove("hidden");',
        '            visibleCount++;',
        '          } else {',
        '            item.classList.add("hidden");',
        '          }',
        '        });',
        '        ',
        '        if (searchTerm === "") {',
        '          resultCount.textContent = "Showing all";',
        '        } else {',
        '          resultCount.textContent = "Showing " + visibleCount + " of " + totalConversations;',
        '        }',
        '      });',
        '    </script>',
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(search_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return search_path
