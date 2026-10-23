"""Render conversation, index, and search HTML pages."""

import calendar
import hashlib
import html
import json
import mimetypes
import os
import re
import statistics
from collections import Counter
from collections import defaultdict
from datetime import date, datetime, timedelta

from export_media import format_attachment_html
from sms_database import sanitize_filename
from time_zone_utils import DEFAULT_TIME_ZONE, localize_message_datetime



def build_html(
    conversation_name,
    messages,
    output_dir,
    attachment_folder=None,
    conversion_failures=None,
    output_filename=None,
    time_zone=DEFAULT_TIME_ZONE,
    fallback_attachment_folders=(),
):
    if conversion_failures is None:
        conversion_failures = {}

    safe_name = output_filename or sanitize_filename(conversation_name)
    filename = os.path.join(output_dir, f'{safe_name}.html')
    stats = summarize_messages(messages, time_zone)

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
        '    .conversation-summary strong { color: #fff; }',
        '    .activity-card { margin-bottom: 20px; padding: 18px; border: 1px solid #e2e8f0; border-radius: 16px; background: #fff; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .activity-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }',
        '    .activity-heading h2 { margin: 0; font-size: 18px; }',
        '    .year-controls { display: flex; align-items: center; gap: 10px; }',
        '    .year-controls button { padding: 7px 11px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; cursor: pointer; }',
        '    .activity-year[hidden] { display: none; }',
        '    .activity-scroll { overflow-x: auto; padding: 12px 0 4px; }',
        '    .month-labels, .activity-grid { display: grid; grid-template-columns: repeat(53, 12px); gap: 3px; width: max-content; }',
        '    .month-labels { grid-template-rows: 18px; margin-bottom: 4px; color: #64748b; font-size: 11px; }',
        '    .activity-grid { grid-template-rows: repeat(7, 12px); grid-auto-flow: column; }',
        '    .activity-day { display: block; width: 12px; height: 12px; padding: 0; border: 0; border-radius: 3px; background: #fff; box-shadow: inset 0 0 0 1px #e2e8f0; }',
        '    button.activity-day { cursor: pointer; }',
        '    button.activity-day:focus-visible { outline: 2px solid #111827; outline-offset: 2px; }',
        '    .activity-day.level-1 { background: #dbeafe; box-shadow: none; }',
        '    .activity-day.level-2 { background: #93c5fd; box-shadow: none; }',
        '    .activity-day.level-3 { background: #3b82f6; box-shadow: none; }',
        '    .activity-day.level-4 { background: #1e3a8a; box-shadow: none; }',
        '    .activity-legend { margin: 10px 0 0; color: #64748b; font-size: 12px; }',
        '    .message-list { padding: 20px; border: 1px solid #e2e8f0; border-radius: 18px; background: #ffffffb8; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .message-filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 16px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; }',
        '    .message-filters label, .search-filters label { display: grid; gap: 5px; color: #475569; font-size: 12px; font-weight: 600; }',
        '    .message-filters input, .search-filters input { width: 100%; box-sizing: border-box; padding: 9px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }',
        '    .message-result-count { color: #64748b; font-size: 13px; }',
        '    .message { display: flex; margin-bottom: 14px; }',
        '    .message.filtered-out { display: none; }',
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
        '    <nav class="site-nav"><a id="backToSearch" href="search.html">← Back to search</a><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="birthdays.html">Birthdays</a><a href="birthday_wishes.html">Birthday wishes</a><a href="calls.html">Call history</a></nav>',
        '    <header class="page-header">',
        f'      <p class="eyebrow">iMessage conversation • {html.escape(time_zone)}</p>',
        f'      <h1>{html.escape(conversation_name)}</h1>',
        '      <div class="conversation-summary">',
        f'        <span><strong id="messageCount">{stats["messages"]:,}</strong> messages</span>',
        f'        <span><strong id="attachmentCount">{stats["attachments"]:,}</strong> attachments</span>',
        f'        <span>{html.escape(stats["first_date"])} – {html.escape(stats["last_date"])}</span>',
        '      </div>',
        '    </header>',
        '    <section class="message-filters" aria-label="Filter messages in this conversation">',
        '      <label>Search message text<input id="messageTextSearch" type="search" placeholder="Words or phrase"></label>',
        '      <label>From date<input id="messageDateFrom" type="date"></label>',
        '      <label>To date<input id="messageDateTo" type="date"></label>',
        '      <label>From time<input id="messageTimeFrom" type="time"></label>',
        '      <label>To time<input id="messageTimeTo" type="time"></label>',
        '      <div id="messageResultCount" class="message-result-count" aria-live="polite"></div>',
        '    </section>',
    ]

    daily_counts = stats['daily_counts']
    years = sorted({day[:4] for day in daily_counts if len(day) >= 4})
    if years:
        html_content.extend([
            '    <section class="activity-card" aria-label="Conversation daily message activity">',
            '      <div class="activity-heading"><h2>Messages per day in this conversation</h2>',
            '        <div class="year-controls">',
            '          <button type="button" id="conversationPreviousYear" aria-label="Previous year">←</button>',
            '          <strong id="conversationActivityYear"></strong>',
            '          <button type="button" id="conversationNextYear" aria-label="Next year">→</button>',
            '        </div>',
            '      </div>',
        ])
        for year in years:
            year_number = int(year)
            first_day = date(year_number, 1, 1)
            last_day = date(year_number, 12, 31)
            grid_start = first_day - timedelta(days=first_day.weekday())
            grid_end = last_day + timedelta(days=6 - last_day.weekday())
            max_count = max(
                (count for day, count in daily_counts.items() if day.startswith(year)),
                default=0,
            )
            hidden = '' if year == years[-1] else ' hidden'
            html_content.append(
                f'      <section class="activity-year" data-year="{year}"{hidden}>'
                f'<div class="activity-scroll"><div class="month-labels">'
            )
            for month in range(1, 13):
                month_start = date(year_number, month, 1)
                week_column = (month_start - grid_start).days // 7 + 1
                html_content.append(
                    f'<span style="grid-column: {week_column}">{month_start.strftime("%b")}</span>'
                )
            html_content.append(
                '</div><div class="activity-grid" role="group" '
                f'aria-label="Daily message counts for {year}">'
            )
            current_day = grid_start
            while current_day <= grid_end:
                day_key = current_day.isoformat()
                count = daily_counts.get(day_key, 0) if current_day.year == year_number else 0
                level = (
                    0 if not count or not max_count
                    else min(4, (count * 4 + max_count - 1) // max_count)
                )
                if current_day.year == year_number:
                    html_content.append(
                        f'<button type="button" class="activity-day level-{level}" '
                        f'data-calendar-date="{day_key}" title="{day_key}: {count:,} messages" '
                        f'aria-label="Filter this conversation to {day_key}: {count:,} messages">'
                        '</button>'
                    )
                else:
                    html_content.append(
                        '<span class="activity-day level-0" aria-hidden="true"></span>'
                    )
                current_day += timedelta(days=1)
            html_content.append('</div></div></section>')
        html_content.extend([
            '      <p class="activity-legend">Darker squares indicate more messages that day; select a day to filter this conversation.</p>',
            '    </section>',
        ])
    html_content.append('    <main class="message-list" id="messages">')

    for msg in messages:
        bubble_class = 'me' if msg['is_from_me'] else 'other'
        text = html.escape(msg['text'] or '')
        if not text and not msg['attachments']:
            text = '[No text]'
        attachments_html = ''.join(
            format_attachment_html(
                att,
                output_dir,
                attachment_folder,
                conversion_failures,
                fallback_attachment_folders=fallback_attachment_folders,
            )
            for att in msg['attachments']
        )
        sender = 'Me' if msg['is_from_me'] else html.escape(str(msg['sender']))

        display_date = localize_message_datetime(msg.get('date'), time_zone)
        message_date, message_time = _split_message_datetime(display_date)
        searchable_text = ' '.join(
            (str(msg.get('text') or ''), str(msg.get('sender') or ''), display_date)
        ).casefold()
        html_content.append(
            f'    <div class="message {bubble_class}" '
            f'data-date="{html.escape(message_date, quote=True)}" '
            f'data-time="{html.escape(message_time, quote=True)}" '
            f'data-attachment-count="{len(msg["attachments"])}" '
            f'data-search-text="{html.escape(searchable_text, quote=True)}">'
        )
        html_content.append(f'      <div class="bubble {bubble_class}">')
        html_content.append(f'        <div>{text}</div>')
        if attachments_html:
            html_content.append(f'        {attachments_html}')
        html_content.append(f'        <div class="meta">{sender} • {html.escape(display_date)}</div>')
        html_content.append('      </div>')
        html_content.append('    </div>')

    html_content.extend([
        '    </main>',
        '    <script>',
        '      const messageFilters = ["messageTextSearch", "messageDateFrom", "messageDateTo", "messageTimeFrom", "messageTimeTo"];',
        '      const messageItems = Array.from(document.querySelectorAll(".message"));',
        '      const messageResultCount = document.getElementById("messageResultCount");',
        '      const messageCount = document.getElementById("messageCount");',
        '      const attachmentCount = document.getElementById("attachmentCount");',
        '      const messageQuery = new URLSearchParams(window.location.search);',
        '      const messageQueryFields = {',
        '        text: "messageTextSearch", dateFrom: "messageDateFrom", dateTo: "messageDateTo",',
        '        timeFrom: "messageTimeFrom", timeTo: "messageTimeTo"',
        '      };',
        '      Object.keys(messageQueryFields).forEach(function(key) {',
        '        if (messageQuery.has(key)) document.getElementById(messageQueryFields[key]).value = messageQuery.get(key);',
        '      });',
        '      const backToSearch = document.getElementById("backToSearch");',
        '      const searchQuery = new URLSearchParams();',
        '      ["text", "dateFrom", "dateTo", "timeFrom", "timeTo", "name"].forEach(function(key) {',
        '        if (messageQuery.has(key)) searchQuery.set(key, messageQuery.get(key));',
        '      });',
        '      if (searchQuery.toString()) backToSearch.href = "search.html?" + searchQuery.toString();',
        '      function filterMessages() {',
        '        const text = document.getElementById("messageTextSearch").value.trim().toLocaleLowerCase();',
        '        const dateFrom = document.getElementById("messageDateFrom").value;',
        '        const dateTo = document.getElementById("messageDateTo").value;',
        '        const timeFrom = document.getElementById("messageTimeFrom").value;',
        '        const timeTo = document.getElementById("messageTimeTo").value;',
        '        let visible = 0;',
        '        let visibleAttachments = 0;',
        '        messageItems.forEach(function(item) {',
        '          const matches = (!text || item.dataset.searchText.includes(text)) &&',
        '            (!dateFrom || item.dataset.date >= dateFrom) && (!dateTo || item.dataset.date <= dateTo) &&',
        '            (!timeFrom || item.dataset.time >= timeFrom) && (!timeTo || item.dataset.time <= timeTo);',
        '          item.classList.toggle("filtered-out", !matches);',
        '          if (matches) {',
        '            visible++;',
        '            visibleAttachments += Number(item.dataset.attachmentCount || 0);',
        '          }',
        '        });',
        '        messageCount.textContent = visible.toLocaleString();',
        '        attachmentCount.textContent = visibleAttachments.toLocaleString();',
        '        messageResultCount.textContent = "Showing " + visible + " of " + messageItems.length + " messages";',
        '      }',
        '      messageFilters.forEach(function(id) {',
        '        document.getElementById(id).addEventListener("input", filterMessages);',
        '        document.getElementById(id).addEventListener("change", filterMessages);',
        '      });',
        '      const activityYears = Array.from(document.querySelectorAll(".activity-year"));',
        '      if (activityYears.length) {',
        '        let activeYearIndex = activityYears.length - 1;',
        '        function showConversationActivityYear() {',
        '          activityYears.forEach(function(section, index) { section.hidden = index !== activeYearIndex; });',
        '          document.getElementById("conversationActivityYear").textContent = activityYears[activeYearIndex].dataset.year;',
        '          document.getElementById("conversationPreviousYear").disabled = activeYearIndex <= 0;',
        '          document.getElementById("conversationNextYear").disabled = activeYearIndex >= activityYears.length - 1;',
        '        }',
        '        document.getElementById("conversationPreviousYear").addEventListener("click", function() { if (activeYearIndex > 0) { activeYearIndex--; showConversationActivityYear(); } });',
        '        document.getElementById("conversationNextYear").addEventListener("click", function() { if (activeYearIndex < activityYears.length - 1) { activeYearIndex++; showConversationActivityYear(); } });',
        '        showConversationActivityYear();',
        '      }',
        '      document.querySelectorAll("[data-calendar-date]").forEach(function(day) {',
        '        day.addEventListener("click", function() {',
        '          document.getElementById("messageDateFrom").value = day.dataset.calendarDate;',
        '          document.getElementById("messageDateTo").value = day.dataset.calendarDate;',
        '          filterMessages();',
        '          document.getElementById("messages").scrollIntoView({ behavior: "smooth" });',
        '        });',
        '      });',
        '      filterMessages();',
        '    </script>',
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


def summarize_messages(messages, time_zone=DEFAULT_TIME_ZONE):
    dates = [
        localize_message_datetime(message.get('date'), time_zone)
        for message in messages
        if message.get('date') and message.get('date') != 'Unknown'
    ]
    daily_counts = Counter()
    for message in messages:
        message_date, _ = _split_message_datetime(
            localize_message_datetime(message.get('date'), time_zone)
        )
        if message_date:
            daily_counts[message_date] += 1
    busiest_date, busiest_count = max(
        daily_counts.items(),
        key=lambda item: (item[1], item[0]),
        default=('—', 0),
    )
    return {
        'messages': len(messages),
        'attachments': sum(len(message.get('attachments', [])) for message in messages),
        'first_date': min(dates) if dates else '—',
        'last_date': max(dates) if dates else '—',
        'sent': sum(bool(message.get('is_from_me')) for message in messages),
        'received': sum(not bool(message.get('is_from_me')) for message in messages),
        'busiest_date': busiest_date,
        'busiest_count': busiest_count,
        'daily_counts': dict(daily_counts),
    }


def _split_message_datetime(value):
    text = str(value or '')
    if len(text) >= 19 and text[10] == ' ':
        return text[:10], text[11:16]
    if len(text) >= 16 and text[10] == 'T':
        return text[:10], text[11:16]
    return '', ''


def _format_elapsed(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f'{days}d {hours}h'
    if hours:
        return f'{hours}h {minutes}m'
    if minutes:
        return f'{minutes}m'
    return f'{seconds}s'


def _conversation_activity_metrics(messages, time_zone):
    dated_messages = []
    participants = Counter()
    attachment_types = Counter()
    for message in messages:
        local_datetime = localize_message_datetime(message.get('date'), time_zone)
        try:
            timestamp = datetime.strptime(local_datetime, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            timestamp = None
        if timestamp:
            dated_messages.append((timestamp, bool(message.get('is_from_me'))))

        chat_id = message.get('chat_id')
        if isinstance(chat_id, (tuple, list)) and chat_id and chat_id[0] == 'group':
            sender = str(message.get('sender') or 'Unknown')
            if sender.casefold() != 'me':
                participants[sender] += 1

        for attachment in message.get('attachments') or []:
            mime_type = str(attachment.get('mime_type') or '').casefold()
            filename = str(attachment.get('filename') or '')
            if not mime_type:
                mime_type = mimetypes.guess_type(filename)[0] or ''
            if mime_type.startswith('image/'):
                attachment_types['Photos and images'] += 1
            elif mime_type.startswith('video/'):
                attachment_types['Videos'] += 1
            elif mime_type.startswith('audio/'):
                attachment_types['Audio'] += 1
            else:
                attachment_types['Other or unknown'] += 1

    dated_messages.sort(key=lambda item: item[0])
    if not dated_messages:
        return {
            'first_date': None,
            'last_date': None,
            'span_days': None,
            'busiest_day': ('—', 0),
            'busiest_week': ('—', 0),
            'busiest_month': ('—', 0),
            'longest_gap': None,
            'active_streak': 0,
            'reply_sent_minutes': None,
            'reply_received_minutes': None,
            'participants': participants,
            'attachment_types': attachment_types,
        }

    daily_counts = Counter(timestamp.date() for timestamp, _ in dated_messages)
    weekly_counts = Counter(
        f'{timestamp.isocalendar()[0]}-W{timestamp.isocalendar()[1]:02d}'
        for timestamp, _ in dated_messages
    )
    monthly_counts = Counter(timestamp.strftime('%Y-%m') for timestamp, _ in dated_messages)
    busiest_day = max(daily_counts.items(), key=lambda item: (item[1], item[0]))
    busiest_week = max(weekly_counts.items(), key=lambda item: (item[1], item[0]))
    busiest_month = max(monthly_counts.items(), key=lambda item: (item[1], item[0]))
    active_dates = sorted(daily_counts)
    active_streak = 0
    current_streak = 0
    previous_date = None
    for active_date in active_dates:
        current_streak = (
            current_streak + 1
            if previous_date and active_date == previous_date + timedelta(days=1)
            else 1
        )
        active_streak = max(active_streak, current_streak)
        previous_date = active_date

    longest_gap = max(
        (
            (current[0] - previous[0]).total_seconds()
            for previous, current in zip(dated_messages, dated_messages[1:])
        ),
        default=None,
    )
    reply_minutes = {'sent': [], 'received': []}
    previous_message = None
    for current_message in dated_messages:
        if previous_message and previous_message[1] != current_message[1]:
            duration = (current_message[0] - previous_message[0]).total_seconds()
            if duration >= 0:
                direction = 'sent' if current_message[1] else 'received'
                reply_minutes[direction].append(duration / 60)
        previous_message = current_message

    return {
        'first_date': active_dates[0],
        'last_date': active_dates[-1],
        'span_days': (active_dates[-1] - active_dates[0]).days + 1,
        'busiest_day': (busiest_day[0].isoformat(), busiest_day[1]),
        'busiest_week': busiest_week,
        'busiest_month': busiest_month,
        'longest_gap': longest_gap,
        'active_streak': active_streak,
        'reply_sent_minutes': statistics.median(reply_minutes['sent']) if reply_minutes['sent'] else None,
        'reply_received_minutes': statistics.median(reply_minutes['received']) if reply_minutes['received'] else None,
        'participants': participants,
        'attachment_types': attachment_types,
    }


def collect_conversation_metrics(conversations, time_zone):
    return [
        (
            conversation_name,
            filename,
            len(messages),
            _conversation_activity_metrics(messages, time_zone),
        )
        for conversation_name, filename, messages in conversations
    ]


def _render_sortable_headers(columns):
    return [
        f'<th scope="col"><button type="button" data-sort-key="{sort_key}" '
        f'aria-sort="none">{label} <span class="sort-indicator"></span></button></th>'
        for sort_key, label in columns
    ]


def build_index(
    conversations,
    output_dir,
    overall_stats,
    time_zone=DEFAULT_TIME_ZONE,
    calls=(),
    conversation_metrics=None,
):
    index_path = os.path.join(output_dir, 'index.html')
    daily_counts = overall_stats.get('daily_counts', {})
    years = sorted({day[:4] for day in daily_counts if len(day) >= 4})
    yearly_counts = Counter()
    monthly_counts = Counter()
    month_of_year_counts = Counter()
    hourly_counts = Counter()
    weekday_counts = Counter()
    attachment_types = Counter()
    if conversation_metrics is None:
        conversation_metrics = collect_conversation_metrics(conversations, time_zone)
    metrics_by_filename = {
        filename: metrics
        for _, filename, _, metrics in conversation_metrics
    }
    parsed_dates = []
    group_participants = Counter()

    for conversation_name, filename, messages in conversations:
        metrics = metrics_by_filename[filename]
        attachment_types.update(metrics['attachment_types'])
        group_participants.update(metrics['participants'])
        for message in messages:
            localized = localize_message_datetime(message.get('date'), time_zone)
            try:
                timestamp = datetime.strptime(localized, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
            parsed_dates.append(timestamp)
            yearly_counts[str(timestamp.year)] += 1
            monthly_counts[timestamp.strftime('%Y-%m')] += 1
            month_of_year_counts[timestamp.month] += 1
            hourly_counts[timestamp.hour] += 1
            weekday_counts[timestamp.weekday()] += 1

    active_days = len(daily_counts)
    average_per_active_day = (
        len(parsed_dates) / active_days if active_days else 0
    )
    span_days = (
        (max(parsed_dates).date() - min(parsed_dates).date()).days + 1
        if parsed_dates else 0
    )
    busiest_month = max(monthly_counts.items(), key=lambda item: (item[1], item[0]), default=('—', 0))
    most_active = max(conversation_metrics, key=lambda item: (item[2], item[0].casefold()), default=None)
    longest_span = max(
        conversation_metrics,
        key=lambda item: (item[3]['span_days'] or 0, item[0].casefold()),
        default=None,
    )

    call_yearly_counts = Counter()
    call_monthly_counts = Counter()
    call_durations = []
    parsed_call_dates = []
    missed_calls = 0
    for call in calls:
        if call.get('direction') == 'Missed':
            missed_calls += 1
        else:
            try:
                duration = max(0, float(call.get('duration') or 0))
            except (TypeError, ValueError, OverflowError):
                duration = 0
            call_durations.append(duration)

        local_call_date = localize_message_datetime(call.get('date'), time_zone)
        try:
            call_date = datetime.strptime(local_call_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        parsed_call_dates.append(call_date)
        call_yearly_counts[str(call_date.year)] += 1
        call_monthly_counts[call_date.strftime('%Y-%m')] += 1

    analytics_content = [
        '<section class="stat-group" aria-label="Archive overview statistics">',
        '<h2>Archive overview</h2>',
        '<section class="stats">',
        f'<div class="stat"><strong>{active_days:,}</strong><span>Active days</span></div>',
        f'<div class="stat"><strong>{average_per_active_day:,.1f}</strong><span>Average messages per active day</span></div>',
        f'<div class="stat"><strong>{html.escape(busiest_month[0])}</strong><span>Busiest month · {busiest_month[1]:,} messages</span></div>',
        f'<div class="stat"><strong>{span_days:,}</strong><span>Calendar days covered</span></div>',
    ]
    if most_active:
        analytics_content.append(
            f'<div class="stat"><strong><a href="{html.escape(most_active[1], quote=True)}.html">'
            f'{html.escape(most_active[0])}</a></strong><span>Most active conversation · '
            f'{most_active[2]:,} messages</span></div>'
        )
    if longest_span:
        analytics_content.append(
            f'<div class="stat"><strong><a href="{html.escape(longest_span[1], quote=True)}.html">'
            f'{html.escape(longest_span[0])}</a></strong><span>Longest conversation span · '
            f'{longest_span[3]["span_days"] or 0:,} days</span></div>'
        )
    analytics_content.extend([
        '</section>',
        '<div class="table-wrap"><table class="stats-table"><thead><tr><th>Attachment type</th><th>Count</th></tr></thead><tbody>',
    ])
    for category in ('Photos and images', 'Videos', 'Audio', 'Other or unknown'):
        analytics_content.append(
            f'<tr><td>{category}</td><td>{attachment_types[category]:,}</td></tr>'
        )
    analytics_content.append('</tbody></table></div>')

    def append_line_chart(title, points, label_formatter, unit):
        if not points:
            analytics_content.append('<p class="stat-note">No data available.</p>')
            return

        chart_width = 960
        chart_height = 300
        left = 64
        right = 24
        top = 24
        bottom = 52
        plot_width = chart_width - left - right
        plot_height = chart_height - top - bottom
        maximum = max((value for _, value in points), default=0)
        scale_maximum = max(4, ((maximum + 3) // 4) * 4)
        x_step = plot_width / max(1, len(points) - 1)

        def y_coordinate(value):
            return top + plot_height * (1 - value / scale_maximum)

        coordinates = [
            (left + index * x_step, y_coordinate(value))
            for index, (_, value) in enumerate(points)
        ]
        line_points = ' '.join(
            f'{x:.1f},{y:.1f}' for x, y in coordinates
        )
        label_step = max(1, (len(points) + 7) // 8)
        label_indices = set(range(0, len(points), label_step))
        label_indices.add(len(points) - 1)
        analytics_content.append(f'<h3>{title}</h3>')
        analytics_content.append(
            f'<figure class="line-chart" aria-label="{html.escape(title, quote=True)}" '
            f'data-unit-singular="{html.escape(unit[:-1], quote=True)}" '
            f'data-unit-plural="{html.escape(unit, quote=True)}">'
            f'<svg viewBox="0 0 {chart_width} {chart_height}" '
            f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
            f'<title>{html.escape(title)}: {maximum:,} {unit} maximum</title>'
        )
        for tick in range(5):
            value = scale_maximum * tick / 4
            y = y_coordinate(value)
            analytics_content.append(
                f'<line class="chart-gridline" x1="{left}" y1="{y:.1f}" '
                f'x2="{chart_width - right}" y2="{y:.1f}"></line>'
                f'<text class="chart-y-label" x="{left - 10}" y="{y + 4:.1f}" '
                f'text-anchor="end">{value:,.0f}</text>'
            )
        analytics_content.append(
            f'<polyline class="chart-line" points="{line_points}"></polyline>'
        )
        for index, ((key, value), (x, y)) in enumerate(zip(points, coordinates)):
            label = label_formatter(key)
            count_label = f'{value:,} {unit if value != 1 else unit[:-1]}'
            analytics_content.append(
                f'<circle class="chart-point" data-label="{html.escape(label, quote=True)}" '
                f'data-value="{value}" data-x="{x:.1f}" data-y="{y:.1f}" '
                f'cx="{x:.1f}" cy="{y:.1f}" r="4">'
                f'<title>{html.escape(label)}: {html.escape(count_label)}</title></circle>'
            )
            if index in label_indices:
                analytics_content.append(
                    f'<text class="chart-x-label" x="{x:.1f}" '
                    f'y="{chart_height - 16}" text-anchor="middle">'
                    f'{html.escape(label_formatter(key))}</text>'
                )
        analytics_content.extend([
            f'<g class="chart-focus" visibility="hidden" pointer-events="none">'
            f'<line class="chart-focus-line" x1="{left}" y1="{top}" '
            f'x2="{left}" y2="{top + plot_height}"></line>'
            f'<circle class="chart-focus-point" cx="{left}" cy="{top}" r="7"></circle>'
            '</g>',
            '<g class="chart-tooltip" visibility="hidden" pointer-events="none">'
            '<rect x="0" y="0" width="220" height="34" rx="8"></rect>'
            '<text x="10" y="22"></text></g>',
            f'<rect class="chart-interaction" x="{left}" y="{top}" '
            f'width="{plot_width}" height="{plot_height}" tabindex="0" role="slider" '
            f'aria-label="Explore {html.escape(title, quote=True)} values" '
            f'aria-valuemin="0" aria-valuemax="{maximum}" aria-valuenow="0" '
            f'data-left="{left}" data-right="{left + plot_width}"></rect>',
        ])
        analytics_content.extend(['</svg>', '</figure>'])

    def months_between(dates):
        months = []
        if dates:
            month_cursor = date(min(dates).year, min(dates).month, 1)
            last_month = date(max(dates).year, max(dates).month, 1)
        else:
            return months
        while month_cursor <= last_month:
            months.append(month_cursor.strftime('%Y-%m'))
            if month_cursor.month == 12:
                month_cursor = date(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)
        return months

    if yearly_counts:
        years_range = range(
            min(map(int, yearly_counts)),
            max(map(int, yearly_counts)) + 1,
        )
        append_line_chart(
            'Messages by year',
            [(str(year), yearly_counts.get(str(year), 0)) for year in years_range],
            str,
            'messages',
        )
    else:
        analytics_content.append('<h3>Messages by year</h3>')
        analytics_content.append('<p class="stat-note">No dated messages are available.</p>')

    append_line_chart(
        'Messages by month',
        [
            (month, month_of_year_counts.get(month, 0))
            for month in range(1, 13)
        ],
        lambda month: calendar.month_name[month],
        'messages',
    )
    append_line_chart(
        'Messages by day of week',
        [(day, weekday_counts.get(day, 0)) for day in range(7)],
        lambda day: calendar.day_name[day],
        'messages',
    )
    append_line_chart(
        'Messages by hour of day',
        [(hour, hourly_counts.get(hour, 0)) for hour in range(24)],
        lambda hour: f'{hour:02d}:00',
        'messages',
    )
    if group_participants:
        analytics_content.append('<h3>Most active group-chat participants</h3><div class="table-wrap">')
        analytics_content.append(
            '<table class="stats-table"><thead><tr><th>Participant</th><th>Messages</th></tr></thead><tbody>'
        )
        for participant, count in group_participants.most_common(10):
            analytics_content.append(
                f'<tr><td>{html.escape(participant)}</td><td>{count:,}</td></tr>'
            )
        analytics_content.append('</tbody></table></div>')
    analytics_content.append('</section>')

    answered_call_average = (
        statistics.mean(call_durations) if call_durations else None
    )
    analytics_content.extend([
        '<section class="stat-group" aria-label="Call statistics">',
        '<h2>Call statistics</h2>',
        '<section class="stats">',
        f'<div class="stat"><strong>{len(calls):,}</strong><span>Total calls</span></div>',
        f'<div class="stat"><strong>{missed_calls:,}</strong><span>Missed calls</span></div>',
        f'<div class="stat"><strong>{_format_elapsed(answered_call_average)}</strong><span>Average duration of non-missed calls</span></div>',
        '</section>',
    ])
    if call_yearly_counts:
        call_years = range(
            min(map(int, call_yearly_counts)),
            max(map(int, call_yearly_counts)) + 1,
        )
        append_line_chart(
            'Calls by year',
            [(str(year), call_yearly_counts.get(str(year), 0)) for year in call_years],
            str,
            'calls',
        )
        append_line_chart(
            'Calls by month',
            [
                (month, call_monthly_counts.get(month, 0))
                for month in months_between(parsed_call_dates)
            ],
            str,
            'calls',
        )
    else:
        analytics_content.append('<h3>Calls by year</h3>')
        analytics_content.append('<p class="stat-note">No call records are available.</p>')
    analytics_content.append('</section>')

    activity_content = []
    for year in years:
        year_number = int(year)
        first_day = date(year_number, 1, 1)
        last_day = date(year_number, 12, 31)
        grid_start = first_day - timedelta(days=first_day.weekday())
        grid_end = last_day + timedelta(days=6 - last_day.weekday())
        max_count = max(
            (count for day, count in daily_counts.items() if day.startswith(year)),
            default=0,
        )
        activity_content.append(
            f'<section class="activity-year" data-year="{year}" '
            f'{" " if year == years[-1] else "hidden"}>'
            f'<h3>{year}</h3><div class="activity-scroll"><div class="month-labels">'
        )
        for month in range(1, 13):
            month_start = date(year_number, month, 1)
            week_column = (month_start - grid_start).days // 7 + 1
            activity_content.append(
                f'<span style="grid-column: {week_column}">{month_start.strftime("%b")}</span>'
            )
        activity_content.append('</div><div class="activity-grid" role="group" '
                                f'aria-label="Daily message counts for {year}">')
        current_day = grid_start
        while current_day <= grid_end:
            day_key = current_day.isoformat()
            count = daily_counts.get(day_key, 0) if current_day.year == year_number else 0
            level = 0 if not count or not max_count else min(4, (count * 4 + max_count - 1) // max_count)
            day_label = f'{day_key}: {count:,} messages'
            if current_day.year == year_number:
                activity_content.append(
                    f'<a class="activity-day level-{level}" href="search.html?date={day_key}" '
                    f'title="{day_label}" aria-label="Search messages from {day_label}"></a>'
                )
            else:
                activity_content.append(
                    '<span class="activity-day level-0" aria-hidden="true"></span>'
                )
            current_day += timedelta(days=1)
        activity_content.append('</div></div></section>')

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
        '    .stat-group { margin: 20px 0; }',
        '    .stat-group h2 { margin: 0 0 12px; font-size: 21px; color: #102a56; }',
        '    .stat-group h3 { margin: 16px 0 8px; font-size: 16px; color: #334155; }',
        '    .stats-table { width: 100%; border-collapse: collapse; background: #fff; }',
        '    .stats-table th, .stats-table td { padding: 9px 12px; border-bottom: 1px solid #e2e8f0; text-align: left; }',
        '    .stats-table th { color: #475569; font-size: 12px; }',
        '    .stats-table td { color: #334155; font-size: 13px; }',
        '    .stats-table a { color: #2563eb; text-decoration: none; font-weight: 600; }',
        '    .stats-table a:hover { text-decoration: underline; }',
        '    .table-wrap { overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 12px; }',
        '    .line-chart { margin: 0; padding: 12px 10px 4px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; box-shadow: 0 2px 8px #0f172a08; }',
        '    .line-chart svg { display: block; width: 100%; height: auto; overflow: visible; }',
        '    .chart-gridline { stroke: #e2e8f0; stroke-width: 1; }',
        '    .chart-y-label, .chart-x-label { fill: #64748b; font-family: inherit; font-size: 12px; }',
        '    .chart-line { fill: none; stroke: #2563eb; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }',
        '    .chart-point { fill: #fff; stroke: #2563eb; stroke-width: 3; vector-effect: non-scaling-stroke; }',
        '    .chart-focus-line { stroke: #0f172a; stroke-width: 1.5; stroke-dasharray: 4 4; vector-effect: non-scaling-stroke; }',
        '    .chart-focus-point { fill: #fff; stroke: #0f172a; stroke-width: 3; vector-effect: non-scaling-stroke; }',
        '    .chart-tooltip rect { fill: #102a56; stroke: #fff; stroke-width: 1; vector-effect: non-scaling-stroke; }',
        '    .chart-tooltip text { fill: #fff; font-family: inherit; font-size: 13px; font-weight: 700; }',
        '    .chart-interaction { fill: transparent; cursor: crosshair; outline: none; }',
        '    .chart-interaction:focus-visible { stroke: #2563eb; stroke-width: 2; stroke-dasharray: 5 4; }',
        '    .stat-note { color: #64748b; font-size: 12px; }',
        '    .activity-card { margin: 20px 0; padding: 20px; border-radius: 14px; background: #fff; box-shadow: 0 1px 4px #0001; }',
        '    .activity-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }',
        '    .activity-heading h2 { margin: 0; font-size: 19px; }',
        '    .year-controls { display: flex; align-items: center; gap: 10px; }',
        '    .year-controls button { padding: 7px 11px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; cursor: pointer; }',
        '    .activity-year[hidden] { display: none; }',
        '    .activity-scroll { overflow-x: auto; padding: 12px 0 4px; }',
        '    .month-labels, .activity-grid { display: grid; grid-template-columns: repeat(53, 12px); gap: 3px; width: max-content; }',
        '    .month-labels { grid-template-rows: 18px; margin-bottom: 4px; color: #64748b; font-size: 11px; }',
        '    .activity-grid { grid-template-rows: repeat(7, 12px); grid-auto-flow: column; }',
        '    .activity-day { display: block; width: 12px; height: 12px; border-radius: 3px; background: #fff; box-shadow: inset 0 0 0 1px #e2e8f0; }',
        '    a.activity-day { cursor: pointer; }',
        '    a.activity-day:focus-visible { outline: 2px solid #111827; outline-offset: 2px; }',
        '    .activity-day.level-1 { background: #dbeafe; box-shadow: none; }',
        '    .activity-day.level-2 { background: #93c5fd; box-shadow: none; }',
        '    .activity-day.level-3 { background: #3b82f6; box-shadow: none; }',
        '    .activity-day.level-4 { background: #1e3a8a; box-shadow: none; }',
        '    .activity-legend { margin: 12px 0 0; color: #64748b; font-size: 12px; }',
        '    .search-link { display: inline-flex; align-items: center; gap: 8px; margin-top: 8px; padding: 12px 18px; border-radius: 12px; color: #fff; background: #2563eb; text-decoration: none; font-size: 15px; font-weight: 600; box-shadow: 0 5px 14px #2563eb33; transition: background .15s, transform .15s; }',
        '    .search-link:hover { background: #1d4ed8; transform: translateY(-1px); }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .page-header { border-radius: 16px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="birthdays.html">Birthdays</a><a href="birthday_wishes.html">Birthday wishes</a><a href="calls.html">Call history</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage archive</p>',
        '      <h1>Your conversations</h1>',
        f'      <p>All message times shown in {html.escape(time_zone)}. Search the archive to find a specific conversation.</p>',
        '    </header>',
        '    <main>',
        '    <section class="stats" aria-label="Database statistics">',
        f'      <div class="stat"><strong>{overall_stats["conversations"]:,}</strong><span>Conversations</span></div>',
        f'      <div class="stat"><strong>{overall_stats["messages"]:,}</strong><span>Messages</span></div>',
        f'      <div class="stat"><strong>{overall_stats["attachments"]:,}</strong><span>Attachments</span></div>',
        f'      <div class="stat"><strong>{overall_stats["sent"]:,}</strong><span>Sent messages</span></div>',
        f'      <div class="stat"><strong>{overall_stats["received"]:,}</strong><span>Received messages</span></div>',
        f'      <div class="stat"><strong>{overall_stats["busiest_count"]:,}</strong><span>Most messages in one day ({html.escape(overall_stats["busiest_date"])})</span></div>',
        f'      <div class="stat"><strong>{html.escape(overall_stats["first_date"])}</strong><span>First message</span></div>',
        f'      <div class="stat"><strong>{html.escape(overall_stats["last_date"])}</strong><span>Last message</span></div>',
        '    </section>',
        '    <section class="activity-card" aria-label="Daily message activity">',
        '      <div class="activity-heading"><h2>Messages per day</h2>',
        '        <div class="year-controls">',
        '          <button type="button" id="previousYear" aria-label="Previous year">←</button>',
        '          <strong id="activityYear"></strong>',
        '          <button type="button" id="nextYear" aria-label="Next year">→</button>',
        '        </div>',
        '      </div>',
    ]
    if activity_content:
        content.extend(activity_content)
    else:
        content.append('<p>No dated messages are available for the activity chart.</p>')
    content.extend([
        '      <p class="activity-legend">Darker squares indicate more messages that day; white means no messages.</p>',
        '    </section>',
    ])
    content.extend(analytics_content)
    content.extend([
        '    <a class="search-link" href="search.html">Search conversations <span aria-hidden="true">→</span></a>',
        '    <script>',
        '      document.querySelectorAll(".line-chart").forEach(function(figure) {',
        '        const svg = figure.querySelector("svg");',
        '        const interaction = figure.querySelector(".chart-interaction");',
        '        const points = Array.from(figure.querySelectorAll(".chart-point"));',
        '        const focus = figure.querySelector(".chart-focus");',
        '        const focusLine = figure.querySelector(".chart-focus-line");',
        '        const focusPoint = figure.querySelector(".chart-focus-point");',
        '        const tooltip = figure.querySelector(".chart-tooltip");',
        '        const tooltipText = tooltip.querySelector("text");',
        '        const plotLeft = Number(interaction.dataset.left);',
        '        const plotRight = Number(interaction.dataset.right);',
        '        let selectedIndex = 0;',
        '        function showPoint(index) {',
        '          selectedIndex = Math.max(0, Math.min(points.length - 1, index));',
        '          const point = points[selectedIndex];',
        '          const x = Number(point.dataset.x);',
        '          const y = Number(point.dataset.y);',
        '          const value = Number(point.dataset.value);',
        '          const label = point.dataset.label;',
        '          const unit = value === 1 ? figure.dataset.unitSingular : figure.dataset.unitPlural;',
        '          focusLine.setAttribute("x1", x);',
        '          focusLine.setAttribute("x2", x);',
        '          focusPoint.setAttribute("cx", x);',
        '          focusPoint.setAttribute("cy", y);',
        '          focus.setAttribute("visibility", "visible");',
        '          tooltipText.textContent = label + ": " + value.toLocaleString() + " " + unit;',
        '          const tooltipX = Math.max(plotLeft, Math.min(plotRight - 220, x - 110));',
        '          const tooltipY = Math.max(28, y - 46);',
        '          tooltip.setAttribute("transform", "translate(" + tooltipX + " " + tooltipY + ")");',
        '          tooltip.setAttribute("visibility", "visible");',
        '          interaction.setAttribute("aria-valuenow", value);',
        '          interaction.setAttribute("aria-valuetext", label + ": " + value.toLocaleString() + " " + unit);',
        '        }',
        '        function hidePoint() {',
        '          focus.setAttribute("visibility", "hidden");',
        '          tooltip.setAttribute("visibility", "hidden");',
        '        }',
        '        interaction.addEventListener("pointermove", function(event) {',
        '          const position = svg.createSVGPoint();',
        '          position.x = event.clientX;',
        '          position.y = event.clientY;',
        '          const localX = position.matrixTransform(svg.getScreenCTM().inverse()).x;',
        '          const fraction = Math.max(0, Math.min(1, (localX - plotLeft) / (plotRight - plotLeft)));',
        '          showPoint(Math.round(fraction * (points.length - 1)));',
        '        });',
        '        interaction.addEventListener("pointerleave", function() {',
        '          if (document.activeElement !== interaction) hidePoint();',
        '        });',
        '        interaction.addEventListener("focus", function() { showPoint(selectedIndex); });',
        '        interaction.addEventListener("blur", hidePoint);',
        '        interaction.addEventListener("keydown", function(event) {',
        '          if (event.key === "ArrowRight" || event.key === "ArrowUp") { event.preventDefault(); showPoint(selectedIndex + 1); }',
        '          else if (event.key === "ArrowLeft" || event.key === "ArrowDown") { event.preventDefault(); showPoint(selectedIndex - 1); }',
        '          else if (event.key === "Home") { event.preventDefault(); showPoint(0); }',
        '          else if (event.key === "End") { event.preventDefault(); showPoint(points.length - 1); }',
        '        });',
        '      });',
        '      const activityYears = Array.from(document.querySelectorAll(".activity-year"));',
        '      let activeYearIndex = Math.max(0, activityYears.length - 1);',
        '      function showActivityYear() {',
        '        activityYears.forEach(function(section, index) { section.hidden = index !== activeYearIndex; });',
        '        document.getElementById("activityYear").textContent = activityYears.length ? activityYears[activeYearIndex].dataset.year : "—";',
        '        document.getElementById("previousYear").disabled = activeYearIndex <= 0;',
        '        document.getElementById("nextYear").disabled = activeYearIndex >= activityYears.length - 1;',
        '      }',
        '      document.getElementById("previousYear").addEventListener("click", function() { if (activeYearIndex > 0) { activeYearIndex--; showActivityYear(); } });',
        '      document.getElementById("nextYear").addEventListener("click", function() { if (activeYearIndex < activityYears.length - 1) { activeYearIndex++; showActivityYear(); } });',
        '      showActivityYear();',
        '    </script>',
        '    </main>',
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return index_path


def build_search_index(
    conversations,
    output_dir,
    time_zone=DEFAULT_TIME_ZONE,
    conversation_metrics=None,
):
    search_path = os.path.join(output_dir, 'search.html')
    conv_list = sorted(conversations, key=lambda entry: entry[0].lower())
    if conversation_metrics is None:
        conversation_metrics = collect_conversation_metrics(conversations, time_zone)

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
        '    .search-filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 18px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; }',
        '    .search-filters label { display: grid; gap: 5px; color: #475569; font-size: 12px; font-weight: 600; }',
        '    .search-filters input { padding: 9px 10px; border-radius: 8px; font: inherit; }',
        '    .random-day-control { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; grid-column: 1 / -1; }',
        '    .random-day-control button { padding: 9px 14px; border: 0; border-radius: 8px; color: #fff; background: #2563eb; font: inherit; font-weight: 600; cursor: pointer; }',
        '    .random-day-control button:hover:not(:disabled) { background: #1d4ed8; }',
        '    .random-day-control button:disabled { opacity: .55; cursor: not-allowed; }',
        '    #randomDayStatus { color: #64748b; font-size: 13px; }',
        '    .results-count { font-size: 14px; color: #64748b; margin-bottom: 12px; }',
        '    .table-wrap { overflow-x: auto; border-radius: 14px; box-shadow: 0 4px 18px #0f172a0d; }',
        '    table { width: 100%; border-collapse: collapse; background: white; }',
        '    th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e5ea; }',
        '    th { background: #f1f5f9; color: #475569; font-size: 13px; white-space: nowrap; }',
        '    th button { border: 0; padding: 0; background: none; color: inherit; font: inherit; font-weight: 600; cursor: pointer; }',
        '    th button:hover { color: #2563eb; }',
        '    .sort-indicator { margin-left: 4px; }',
        '    .conversation-section { margin-top: 24px; }',
        '    .conversation-section h2 { margin: 0 0 10px; color: #102a56; font-size: 21px; }',
        '    .conversation-table { min-width: 900px; }',
        '    .conversation-table th button { font-size: 12px; }',
        '    .conversation-table .sort-indicator { color: #2563eb; }',
        '    .conversation-table td { white-space: nowrap; }',
        '    .conversation-table td.participants { white-space: normal; }',
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
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="birthdays.html">Birthdays</a><a href="birthday_wishes.html">Birthday wishes</a><a href="calls.html">Call history</a></nav>',
        '    <header class="page-header">',
        '      <p class="eyebrow">iMessage archive</p>',
        '      <h1>Find a conversation</h1>',
        f'      <p>Search, sort, and explore your conversations and message history. Times shown in {html.escape(time_zone)}.</p>',
        '    </header>',
        '    <div class="search-box">',
        '      <input type="text" id="searchInput" placeholder="Search for a person or name...">',
        '    </div>',
        '    <section class="search-filters" aria-label="Search messages by text and date or time">',
        '      <label>Message text<input type="search" id="messageSearchInput" placeholder="Search message text"></label>',
        '      <label>From date<input type="date" id="dateFromInput"></label>',
        '      <label>To date<input type="date" id="dateToInput"></label>',
        '      <label>From time<input type="time" id="timeFromInput"></label>',
        '      <label>To time<input type="time" id="timeToInput"></label>',
        '      <div class="random-day-control"><button type="button" id="randomDayButton">Go to a random day</button><span id="randomDayStatus" aria-live="polite"></span></div>',
        '    </section>',
        '    <div class="results-count"><span id="resultCount">Showing all</span> conversations</div>',
    ]

    direct_columns = (
        ('name', 'Conversation'),
        ('messages', 'Messages'),
        ('attachments', 'Attachments'),
        ('first-date', 'First message'),
        ('last-date', 'Last message'),
        ('busiest-day', 'Busiest day'),
        ('busiest-week', 'Busiest week'),
        ('busiest-month', 'Busiest month'),
        ('longest-gap', 'Longest gap'),
        ('active-streak', 'Longest active streak'),
        ('reply-sent', 'Median sent reply'),
        ('reply-received', 'Median received reply'),
    )
    group_columns = (
        ('name', 'Conversation'),
        ('participants', 'People in group'),
        ('messages', 'Messages'),
        ('attachments', 'Attachments'),
        ('first-date', 'First message'),
        ('last-date', 'Last message'),
        ('top-participant', 'Top group participant'),
    )
    content.extend([
        '    <section class="conversation-section" aria-labelledby="directConversationsHeading">',
        '      <h2 id="directConversationsHeading">Conversations</h2>',
        '      <div class="table-wrap"><table class="conversation-table"><thead><tr>',
    ])
    content.extend(_render_sortable_headers(direct_columns))
    content.extend([
        '</tr></thead><tbody id="conversationList">',
    ])

    search_data = []
    direct_rows = []
    group_rows = []
    metrics_by_filename = {
        filename: metrics
        for _, filename, _, metrics in conversation_metrics
    }
    for display_name, filename, messages in conv_list:
        stats = summarize_messages(messages, time_zone)
        is_group = any(
            isinstance(message.get('chat_id'), (tuple, list))
            and message['chat_id']
            and message['chat_id'][0] == 'group'
            for message in messages
        )
        participant_names = sorted({
            name
            for message in messages
            for name in message.get('group_participants', [])
        }, key=str.casefold) if is_group else []
        participants_text = ', '.join(participant_names)
        searchable_name = f'{display_name} {participants_text}'.lower()
        searchable_messages = []
        for message in messages:
            local_date, local_time = _split_message_datetime(
                localize_message_datetime(message.get('date'), time_zone)
            )
            searchable_messages.append([
                str(message.get('text') or '').casefold(),
                local_date,
                local_time,
                len(message.get('attachments') or []),
                bool(message.get('is_from_me')),
                str(message.get('sender') or 'Unknown'),
            ])
        serialized_messages = json.dumps(
            searchable_messages,
            ensure_ascii=False,
            separators=(',', ':'),
        )
        serialized_messages = (
            serialized_messages.replace('&', '\\u0026')
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
        )
        search_index = len(search_data)
        search_data.append(serialized_messages)
        sort_values = {
            'name': display_name.casefold(),
            'participants': participants_text.casefold(),
            'messages': stats['messages'],
            'attachments': stats['attachments'],
            'first-date': stats['first_date'] if stats['first_date'] != '—' else '',
            'last-date': stats['last_date'] if stats['last_date'] != '—' else '',
        }
        metrics = metrics_by_filename[filename]
        top_participant, participant_count = (
            metrics['participants'].most_common(1)[0]
            if metrics['participants'] else ('—', 0)
        )
        if not is_group:
            sort_values.update({
                'busiest-day': metrics['busiest_day'][1],
                'busiest-week': metrics['busiest_week'][1],
                'busiest-month': metrics['busiest_month'][1],
                'longest-gap': metrics['longest_gap'] if metrics['longest_gap'] is not None else -1,
                'active-streak': metrics['active_streak'],
                'reply-sent': metrics['reply_sent_minutes'] if metrics['reply_sent_minutes'] is not None else -1,
                'reply-received': metrics['reply_received_minutes'] if metrics['reply_received_minutes'] is not None else -1,
            })
        else:
            sort_values['top-participant'] = participant_count
        sort_attributes = ' '.join(
            f'data-sort-{key}="{html.escape(str(value), quote=True)}"'
            for key, value in sort_values.items()
        )
        row_markup = [
            f'<tr class="conv-item" data-name="{html.escape(searchable_name, quote=True)}" '
            f'data-search-index="{search_index}" {sort_attributes}>',
            f'<td><a data-conversation-file="{html.escape(filename, quote=True)}.html" '
            f'href="{html.escape(filename, quote=True)}.html">{html.escape(display_name)}</a></td>',
        ]
        if is_group:
            row_markup.extend([
                f'<td class="participants">{html.escape(participants_text) if participants_text else "—"}</td>',
                f'<td><span class="filtered-message-count">{stats["messages"]:,}</span></td>',
                f'<td><span class="filtered-attachment-count">{stats["attachments"]:,}</span></td>',
                f'<td><span class="filtered-first-date">{html.escape(stats["first_date"])}</span></td>',
                f'<td><span class="filtered-last-date">{html.escape(stats["last_date"])}</span></td>',
                f'<td><span class="filtered-top-participant">{html.escape(top_participant)} ({participant_count:,})</span></td>',
            ])
        else:
            sent_reply = (
                f'{metrics["reply_sent_minutes"]:,.1f} min'
                if metrics['reply_sent_minutes'] is not None else '—'
            )
            received_reply = (
                f'{metrics["reply_received_minutes"]:,.1f} min'
                if metrics['reply_received_minutes'] is not None else '—'
            )
            row_markup.extend([
                f'<td><span class="filtered-message-count">{stats["messages"]:,}</span></td>',
                f'<td><span class="filtered-attachment-count">{stats["attachments"]:,}</span></td>',
                f'<td><span class="filtered-first-date">{html.escape(stats["first_date"])}</span></td>',
                f'<td><span class="filtered-last-date">{html.escape(stats["last_date"])}</span></td>',
                f'<td><span class="filtered-busiest-day">{html.escape(metrics["busiest_day"][0])} ({metrics["busiest_day"][1]:,})</span></td>',
                f'<td><span class="filtered-busiest-week">{html.escape(str(metrics["busiest_week"][0]))} ({metrics["busiest_week"][1]:,})</span></td>',
                f'<td><span class="filtered-busiest-month">{html.escape(str(metrics["busiest_month"][0]))} ({metrics["busiest_month"][1]:,})</span></td>',
                f'<td><span class="filtered-longest-gap">{_format_elapsed(metrics["longest_gap"])}</span></td>',
                f'<td><span class="filtered-active-streak">{metrics["active_streak"]:,} days</span></td>',
                f'<td><span class="filtered-reply-sent">{sent_reply}</span>',
                f'<td><span class="filtered-reply-received">{received_reply}</span>',
            ])
        row_markup.append('</tr>')
        if is_group:
            group_rows.append(''.join(row_markup))
        else:
            direct_rows.append(''.join(row_markup))

    serialized_search_data = '[' + ','.join(search_data) + ']'
    content.extend([
        *direct_rows,
        '      </tbody></table></div>',
        '    </section>',
        '    <section class="conversation-section" aria-labelledby="groupConversationsHeading">',
        '      <h2 id="groupConversationsHeading">Group conversations</h2>',
        '      <div class="table-wrap"><table class="conversation-table"><thead><tr>',
    ])
    content.extend(_render_sortable_headers(group_columns))
    content.extend([
        '</tr></thead><tbody id="groupConversationList">',
        *group_rows,
        '      </tbody></table></div>',
        '    </section>',
    ])
    content.extend([
        '    <script id="searchMessageData" type="application/json">',
        serialized_search_data,
        '    </script>',
        '    <script>',
        '      const searchInput = document.getElementById("searchInput");',
        '      const messageSearchInput = document.getElementById("messageSearchInput");',
        '      const dateFromInput = document.getElementById("dateFromInput");',
        '      const dateToInput = document.getElementById("dateToInput");',
        '      const timeFromInput = document.getElementById("timeFromInput");',
        '      const timeToInput = document.getElementById("timeToInput");',
        '      const conversationItems = document.querySelectorAll(".conv-item");',
        '      const searchMessages = JSON.parse(document.getElementById("searchMessageData").textContent);',
        '      function isoWeekKey(dayValue) {',
        '        const parts = dayValue.split("-").map(Number);',
        '        const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));',
        '        const dayNumber = (date.getUTCDay() + 6) % 7;',
        '        date.setUTCDate(date.getUTCDate() - dayNumber + 3);',
        '        const isoYear = date.getUTCFullYear();',
        '        const jan4 = new Date(Date.UTC(isoYear, 0, 4));',
        '        const jan4Day = (jan4.getUTCDay() + 6) % 7;',
        '        const week = Math.ceil(((date - jan4) / 86400000 - 3 + jan4Day) / 7) + 1;',
        '        return isoYear + "-W" + String(week).padStart(2, "0");',
        '      }',
        '      function formatElapsed(seconds) {',
        '        const total = Math.max(0, Math.round(seconds));',
        '        const days = Math.floor(total / 86400);',
        '        const hours = Math.floor((total % 86400) / 3600);',
        '        const minutes = Math.floor((total % 3600) / 60);',
        '        if (days) return days + "d " + hours + "h";',
        '        if (hours) return hours + "h " + minutes + "m";',
        '        if (minutes) return minutes + "m";',
        '        return total + "s";',
        '      }',
        '      function formatReplyMinutes(value) {',
        '        return value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " min";',
        '      }',
        '      function computeFilteredMetrics(messages) {',
        '        const dated = [];',
        '        const dailyCounts = new Map();',
        '        const weeklyCounts = new Map();',
        '        const monthlyCounts = new Map();',
        '        messages.forEach(function(message) {',
        '          const day = message[1];',
        '          if (!day) return;',
        '          const stamp = new Date(day + "T" + (message[2] || "00:00") + ":00");',
        '          dated.push([stamp, message[4], day]);',
        '          dailyCounts.set(day, (dailyCounts.get(day) || 0) + 1);',
        '          const weekKey = isoWeekKey(day);',
        '          weeklyCounts.set(weekKey, (weeklyCounts.get(weekKey) || 0) + 1);',
        '          const monthKey = day.slice(0, 7);',
        '          monthlyCounts.set(monthKey, (monthlyCounts.get(monthKey) || 0) + 1);',
        '        });',
        '        const pickBusiest = function(counts) {',
        '          let busiestKey = "—";',
        '          let busiestCount = 0;',
        '          counts.forEach(function(count, key) {',
        '            if (count > busiestCount || (count === busiestCount && key > busiestKey)) {',
        '              busiestKey = key;',
        '              busiestCount = count;',
        '            }',
        '          });',
        '          return [busiestKey, busiestCount];',
        '        };',
        '        dated.sort(function(a, b) { return a[0] - b[0]; });',
        '        let longestGap = null;',
        '        for (let index = 1; index < dated.length; index++) {',
        '          const gap = (dated[index][0] - dated[index - 1][0]) / 1000;',
        '          if (gap >= 0 && (longestGap === null || gap > longestGap)) longestGap = gap;',
        '        }',
        '        const activeDays = Array.from(new Set(dated.map(function(item) { return item[2]; })));',
        '        activeDays.sort();',
        '        let streak = 0;',
        '        let currentStreak = 0;',
        '        let previousDay = null;',
        '        activeDays.forEach(function(day) {',
        '          const dayDate = new Date(day + "T12:00:00");',
        '          currentStreak = previousDay && Math.round((dayDate - previousDay) / 86400000) === 1',
        '            ? currentStreak + 1',
        '            : 1;',
        '          streak = Math.max(streak, currentStreak);',
        '          previousDay = dayDate;',
        '        });',
        '        const sentMinutes = [];',
        '        const receivedMinutes = [];',
        '        for (let index = 1; index < dated.length; index++) {',
        '          if (dated[index][1] !== dated[index - 1][1]) {',
        '            const minutes = (dated[index][0] - dated[index - 1][0]) / 60000;',
        '            if (minutes >= 0) {',
        '              (dated[index][1] ? sentMinutes : receivedMinutes).push(minutes);',
        '            }',
        '          }',
        '        }',
        '        const median = function(values) {',
        '          if (!values.length) return null;',
        '          const sortedValues = values.slice().sort(function(a, b) { return a - b; });',
        '          const middle = Math.floor(sortedValues.length / 2);',
        '          return sortedValues.length % 2',
        '            ? sortedValues[middle]',
        '            : (sortedValues[middle - 1] + sortedValues[middle]) / 2;',
        '        };',
        '        return {',
        '          busiestDay: pickBusiest(dailyCounts),',
        '          busiestWeek: pickBusiest(weeklyCounts),',
        '          busiestMonth: pickBusiest(monthlyCounts),',
        '          longestGap: longestGap,',
        '          activeStreak: streak,',
        '          sentMedian: median(sentMinutes),',
        '          receivedMedian: median(receivedMinutes)',
        '        };',
        '      }',
        '      const randomDayButton = document.getElementById("randomDayButton");',
        '      const randomDayStatus = document.getElementById("randomDayStatus");',
        '      const availableDates = new Set();',
        '      searchMessages.forEach(function(messages) {',
        '        messages.forEach(function(message) { if (message[1]) availableDates.add(message[1]); });',
        '      });',
        '      randomDayButton.disabled = availableDates.size === 0;',
        '      const resultCount = document.getElementById("resultCount");',
        '      const totalConversations = conversationItems.length;',
        '      const pageQuery = new URLSearchParams(window.location.search);',
        '      const searchFields = {',
        '        name: searchInput, text: messageSearchInput, dateFrom: dateFromInput, dateTo: dateToInput,',
        '        timeFrom: timeFromInput, timeTo: timeToInput',
        '      };',
        '      if (pageQuery.has("date")) {',
        '        dateFromInput.value = pageQuery.get("date");',
        '        dateToInput.value = pageQuery.get("date");',
        '      }',
        '      Object.keys(searchFields).forEach(function(key) {',
        '        if (pageQuery.has(key)) searchFields[key].value = pageQuery.get(key);',
        '      });',
        '      document.querySelectorAll(".conversation-table").forEach(function(table) {',
        '        let activeSortKey = "";',
        '        let sortAscending = true;',
        '        const sortButtons = table.querySelectorAll("th button[data-sort-key]");',
        '        sortButtons.forEach(function(button) {',
        '          button.addEventListener("click", function() {',
        '            const sortKey = button.dataset.sortKey;',
        '            if (activeSortKey === sortKey) sortAscending = !sortAscending;',
        '            else { activeSortKey = sortKey; sortAscending = true; }',
        '            sortButtons.forEach(function(sortButton) {',
        '              const isActive = sortButton.dataset.sortKey === activeSortKey;',
        '              sortButton.setAttribute("aria-sort", isActive ? (sortAscending ? "ascending" : "descending") : "none");',
        '              sortButton.querySelector(".sort-indicator").textContent = isActive ? (sortAscending ? "▲" : "▼") : "";',
        '            });',
        '            const dataKey = "sort" + sortKey.split("-").map(function(part) { return part.charAt(0).toUpperCase() + part.slice(1); }).join("");',
        '            const rows = Array.from(table.tBodies[0].rows);',
        '            rows.sort(function(left, right) {',
        '              const leftValue = left.dataset[dataKey] || "";',
        '              const rightValue = right.dataset[dataKey] || "";',
        '              const leftNumber = Number(leftValue);',
        '              const rightNumber = Number(rightValue);',
        '              const bothNumeric = leftValue !== "" && rightValue !== "" && Number.isFinite(leftNumber) && Number.isFinite(rightNumber);',
        '              const comparison = bothNumeric ? leftNumber - rightNumber : leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });',
        '              return (sortAscending ? comparison : -comparison) || left.dataset.sortName.localeCompare(right.dataset.sortName);',
        '            });',
        '            rows.forEach(function(row) { table.tBodies[0].appendChild(row); });',
        '          });',
        '        });',
        '      });',
        '      ',
        '      function filterConversations() {',
        '        const searchTerm = searchInput.value.toLocaleLowerCase().trim();',
        '        const messageTerm = messageSearchInput.value.toLocaleLowerCase().trim();',
        '        const dateFrom = dateFromInput.value;',
        '        const dateTo = dateToInput.value;',
        '        const timeFrom = timeFromInput.value;',
        '        const timeTo = timeToInput.value;',
        '        const messageFiltersActive = Boolean(messageTerm || dateFrom || dateTo || timeFrom || timeTo);',
        '        let visibleCount = 0;',
        '        ',
        '        conversationItems.forEach(function(item) {',
        '          const nameMatches = !searchTerm || item.getAttribute("data-name").includes(searchTerm);',
        '          const messages = searchMessages[Number(item.getAttribute("data-search-index"))] || [];',
        '          const matchingMessages = messages.filter(function(message) {',
        '            return (!messageTerm || message[0].includes(messageTerm)) &&',
        '              (!dateFrom || message[1] >= dateFrom) && (!dateTo || message[1] <= dateTo) &&',
        '              (!timeFrom || message[2] >= timeFrom) && (!timeTo || message[2] <= timeTo);',
        '          });',
        '          const messageMatches = !messageFiltersActive || matchingMessages.length > 0;',
        '          const filteredAttachments = matchingMessages.reduce(function(total, message) {',
        '            return total + Number(message[3] || 0);',
        '          }, 0);',
        '          const matchingDates = matchingMessages.map(function(message) {',
        '            return message[1];',
        '          }).filter(Boolean).sort();',
        '          item.querySelector(".filtered-message-count").textContent = matchingMessages.length.toLocaleString();',
        '          item.querySelector(".filtered-attachment-count").textContent = filteredAttachments.toLocaleString();',
        '          item.querySelector(".filtered-first-date").textContent = matchingDates.length ? matchingDates[0] : "—";',
        '          item.querySelector(".filtered-last-date").textContent = matchingDates.length ? matchingDates[matchingDates.length - 1] : "—";',
        '          item.setAttribute("data-sort-messages", matchingMessages.length);',
        '          item.setAttribute("data-sort-attachments", filteredAttachments);',
        '          item.setAttribute("data-sort-first-date", matchingDates.length ? matchingDates[0] : "");',
        '          item.setAttribute("data-sort-last-date", matchingDates.length ? matchingDates[matchingDates.length - 1] : "");',
        '          if (item.querySelector(".filtered-busiest-day")) {',
        '            const rowMetrics = computeFilteredMetrics(matchingMessages);',
        '            item.querySelector(".filtered-busiest-day").textContent = rowMetrics.busiestDay[0] + " (" + rowMetrics.busiestDay[1].toLocaleString() + ")";',
        '            item.querySelector(".filtered-busiest-week").textContent = rowMetrics.busiestWeek[0] + " (" + rowMetrics.busiestWeek[1].toLocaleString() + ")";',
        '            item.querySelector(".filtered-busiest-month").textContent = rowMetrics.busiestMonth[0] + " (" + rowMetrics.busiestMonth[1].toLocaleString() + ")";',
        '            item.querySelector(".filtered-longest-gap").textContent = rowMetrics.longestGap === null ? "—" : formatElapsed(rowMetrics.longestGap);',
        '            item.querySelector(".filtered-active-streak").textContent = rowMetrics.activeStreak.toLocaleString() + " days";',
        '            item.querySelector(".filtered-reply-sent").textContent = rowMetrics.sentMedian === null ? "—" : formatReplyMinutes(rowMetrics.sentMedian);',
        '            item.querySelector(".filtered-reply-received").textContent = rowMetrics.receivedMedian === null ? "—" : formatReplyMinutes(rowMetrics.receivedMedian);',
        '            item.setAttribute("data-sort-busiest-day", rowMetrics.busiestDay[1]);',
        '            item.setAttribute("data-sort-busiest-week", rowMetrics.busiestWeek[1]);',
        '            item.setAttribute("data-sort-busiest-month", rowMetrics.busiestMonth[1]);',
        '            item.setAttribute("data-sort-longest-gap", rowMetrics.longestGap === null ? -1 : rowMetrics.longestGap);',
        '            item.setAttribute("data-sort-active-streak", rowMetrics.activeStreak);',
        '            item.setAttribute("data-sort-reply-sent", rowMetrics.sentMedian === null ? -1 : rowMetrics.sentMedian);',
        '            item.setAttribute("data-sort-reply-received", rowMetrics.receivedMedian === null ? -1 : rowMetrics.receivedMedian);',
        '          }',
        '          const topParticipantCell = item.querySelector(".filtered-top-participant");',
        '          if (topParticipantCell) {',
        '            const senderCounts = new Map();',
        '            matchingMessages.forEach(function(message) {',
        '              const sender = message[5];',
        '              if (sender.toLowerCase() === "me") return;',
        '              senderCounts.set(sender, (senderCounts.get(sender) || 0) + 1);',
        '            });',
        '            let topSender = "—";',
        '            let topSenderCount = 0;',
        '            senderCounts.forEach(function(count, sender) {',
        '              if (count > topSenderCount) {',
        '                topSender = sender;',
        '                topSenderCount = count;',
        '              }',
        '            });',
        '            topParticipantCell.textContent = topSender + " (" + topSenderCount.toLocaleString() + ")";',
        '            item.setAttribute("data-sort-top-participant", topSenderCount);',
        '          }',
        '          if (nameMatches && messageMatches) {',
        '            item.classList.remove("hidden");',
        '            visibleCount++;',
        '          } else {',
        '            item.classList.add("hidden");',
        '          }',
        '        });',
        '        ',
        '        if (!searchTerm && !messageFiltersActive) {',
        '          resultCount.textContent = "Showing all";',
        '        } else {',
        '          resultCount.textContent = "Showing " + visibleCount + " of " + totalConversations;',
        '        }',
        '        const activeFilters = new URLSearchParams();',
        '        Object.keys(searchFields).forEach(function(key) {',
        '          const value = searchFields[key].value.trim();',
        '          if (value) activeFilters.set(key, value);',
        '        });',
        '        conversationItems.forEach(function(item) {',
        '          const link = item.querySelector("a[data-conversation-file]");',
        '          const query = activeFilters.toString();',
        '          link.href = link.dataset.conversationFile + (query ? "?" + query : "");',
        '        });',
        '      }',
        '      randomDayButton.addEventListener("click", function() {',
        '        const dates = Array.from(availableDates);',
        '        if (!dates.length) return;',
        '        const randomDate = dates[Math.floor(Math.random() * dates.length)];',
        '        searchInput.value = "";',
        '        messageSearchInput.value = "";',
        '        dateFromInput.value = randomDate;',
        '        dateToInput.value = randomDate;',
        '        timeFromInput.value = "";',
        '        timeToInput.value = "";',
        '        filterConversations();',
        '        randomDayStatus.textContent = "Showing conversations from " + randomDate;',
        '      });',
        '      [searchInput, messageSearchInput, dateFromInput, dateToInput, timeFromInput, timeToInput].forEach(function(input) {',
        '        function handleFilterChange() {',
        '          randomDayStatus.textContent = "";',
        '          filterConversations();',
        '        }',
        '        input.addEventListener("input", handleFilterChange);',
        '        input.addEventListener("change", handleFilterChange);',
        '      });',
        '      window.addEventListener("pageshow", function() { filterConversations(); });',
        '      filterConversations();',
        '    </script>',
        '  </div>',
        '</body>',
        '</html>'
    ])

    with open(search_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    return search_path


def build_birthdays(conversations, output_dir, time_zone=DEFAULT_TIME_ZONE):
    """Create a calendar of birthday dates inferred from outgoing direct messages."""
    page_path = os.path.join(output_dir, 'birthdays.html')
    birthday_evidence = defaultdict(dict)
    birthday_phrase = re.compile(r'.*\bhappy\s+birthday\b.*', re.IGNORECASE | re.DOTALL)
    quoted_text = re.compile(r'"(?:\\.|[^"\\])*"|“[^”]*”')

    for display_name, filename, messages in conversations:
        for message in messages:
            chat_id = message.get('chat_id')
            if (
                not message.get('is_from_me')
                or not isinstance(chat_id, (tuple, list))
                or not chat_id
                or chat_id[0] not in ('phone', 'address')
                or not birthday_phrase.search(
                    quoted_text.sub('', str(message.get('text') or ''))
                )
            ):
                continue

            local_date, _ = _split_message_datetime(
                localize_message_datetime(message.get('date'), time_zone)
            )
            try:
                message_day = date.fromisoformat(local_date)
            except ValueError:
                continue

            birthday_key = (message_day.month, message_day.day)
            contact = birthday_evidence[birthday_key].setdefault(
                (display_name, filename),
                {'count': 0, 'years': set()},
            )
            contact['count'] += 1
            contact['years'].add(message_day.year)

    birthdays_by_day = defaultdict(list)
    for (month, day), contacts in birthday_evidence.items():
        birthdays_by_day[(month, day)] = sorted(
            (
                {
                    'name': name,
                    'filename': filename,
                    'count': evidence['count'],
                    'years': sorted(evidence['years']),
                }
                for (name, filename), evidence in contacts.items()
            ),
            key=lambda contact: contact['name'].casefold(),
        )

    total_candidates = sum(len(contacts) for contacts in birthdays_by_day.values())
    unique_contacts = {
        (contact['name'], contact['filename'])
        for contacts in birthdays_by_day.values()
        for contact in contacts
    }
    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        '  <title>Inferred birthdays</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; color: #172033; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1500px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #fff; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 42px); margin-bottom: 20px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .page-header p { margin: 10px 0 0; color: #e0f2fe; line-height: 1.5; }',
        '    h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); }',
        '    .calendar { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }',
        '    .month { padding: 16px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .month h2 { margin: 0 0 12px; color: #102a56; font-size: 18px; }',
        '    .month-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }',
        '    .weekday { padding: 4px 0; color: #64748b; font-size: 11px; font-weight: 700; text-align: center; }',
        '    .day { min-height: 64px; padding: 5px; border-radius: 8px; background: #f8fafc; font-size: 12px; }',
        '    .day.empty { background: transparent; }',
        '    .day.has-birthday { background: #eff6ff; box-shadow: inset 0 0 0 1px #bfdbfe; }',
        '    .day-number { color: #475569; font-weight: 700; }',
        '    .birthday-list { display: grid; gap: 3px; margin-top: 4px; }',
        '    .birthday-list a { color: #1d4ed8; font-weight: 600; overflow-wrap: anywhere; text-decoration: none; }',
        '    .birthday-list a:hover { text-decoration: underline; }',
        '    .evidence { color: #64748b; font-size: 10px; line-height: 1.3; }',
        '    .empty-state { padding: 22px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; color: #64748b; }',
        '    @media (max-width: 1000px) { .calendar { grid-template-columns: repeat(2, minmax(0, 1fr)); } }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } .calendar { grid-template-columns: 1fr; } .month { padding: 10px; } .day { min-height: 58px; padding: 3px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="birthdays.html">Birthdays</a><a href="birthday_wishes.html">Birthday wishes</a><a href="calls.html">Call history</a></nav>',
        '    <header class="page-header">',
        '      <h1>Birthday calendar</h1>',
        f'      <p>{total_candidates:,} inferred date(s) for {len(unique_contacts):,} contact(s). Dates are inferred from outgoing “Happy Birthday” messages and may not be the actual birthday. Conflicting dates are shown separately; the number indicates supporting messages. Times and dates use {html.escape(time_zone)}.</p>',
        '    </header>',
    ]

    if not total_candidates:
        content.append(
            '    <p class="empty-state">No outgoing “Happy Birthday” messages in one-to-one conversations were found.</p>'
        )
    else:
        content.append('    <main class="calendar" aria-label="Birthday calendar">')
        weekdays = ('Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat')
        for month in range(1, 13):
            content.append(
                f'      <section class="month"><h2>{calendar.month_name[month]}</h2>'
                '<div class="month-grid">'
            )
            content.extend(
                f'<span class="weekday" aria-hidden="true">{weekday}</span>'
                for weekday in weekdays
            )
            for week in calendar.Calendar(firstweekday=6).monthdayscalendar(2000, month):
                for day in week:
                    if not day:
                        content.append('<span class="day empty" aria-hidden="true"></span>')
                        continue
                    contacts = birthdays_by_day.get((month, day), [])
                    classes = 'day has-birthday' if contacts else 'day'
                    content.append(f'<div class="{classes}"><span class="day-number">{day}</span>')
                    if contacts:
                        content.append('<div class="birthday-list">')
                        for contact in contacts:
                            years = ', '.join(str(year) for year in contact['years'])
                            observed_date = date(contact['years'][-1], month, day).isoformat()
                            message_word = 'message' if contact['count'] == 1 else 'messages'
                            title = (
                                f'{contact["count"]} supporting {message_word}; '
                                f'observed in {years}; open {observed_date}'
                            )
                            content.append(
                                f'<a href="{html.escape(contact["filename"], quote=True)}.html?'
                                f'dateFrom={observed_date}&amp;dateTo={observed_date}" '
                                f'title="{html.escape(title, quote=True)}">'
                                f'{html.escape(contact["name"])}'
                                f' <span aria-label="{contact["count"]} supporting messages">'
                                f'({contact["count"]})</span></a>'
                            )
                            content.append(
                                f'<span class="evidence">{html.escape(years)}</span>'
                            )
                        content.append('</div>')
                    content.append('</div>')
            content.append('</div></section>')
        content.append('    </main>')

    content.extend(['  </div>', '</body>', '</html>'])
    with open(page_path, 'w', encoding='utf-8') as page:
        page.write('\n'.join(content))
    return page_path


def build_birthday_wishes(conversations, output_dir, time_zone=DEFAULT_TIME_ZONE):
    """Create a page for finding incoming birthday wishes by month and day."""
    page_path = os.path.join(output_dir, 'birthday_wishes.html')
    birthday_phrase = re.compile(r'.*\bhappy\s+birthday\b.*', re.IGNORECASE | re.DOTALL)
    quoted_text = re.compile(r'"(?:\\.|[^"\\])*"|“[^”]*”')
    wishes = []

    for conversation_name, filename, messages in conversations:
        for message in messages:
            chat_id = message.get('chat_id')
            text = str(message.get('text') or '')
            if (
                message.get('is_from_me')
                or not isinstance(chat_id, (tuple, list))
                or not chat_id
                or chat_id[0] not in ('phone', 'address', 'group')
                or not birthday_phrase.search(quoted_text.sub('', text))
            ):
                continue

            local_date, _ = _split_message_datetime(
                localize_message_datetime(message.get('date'), time_zone)
            )
            try:
                date.fromisoformat(local_date)
            except ValueError:
                continue

            wishes.append([
                str(message.get('sender') or 'Unknown'),
                filename,
                local_date,
                text,
                conversation_name,
            ])

    wishes.sort(key=lambda wish: (wish[2], wish[0].casefold(), wish[1]))
    serialized_wishes = json.dumps(wishes, ensure_ascii=False, separators=(',', ':'))
    serialized_wishes = (
        serialized_wishes.replace('&', '\\u0026')
        .replace('<', '\\u003c')
        .replace('>', '\\u003e')
    )
    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        '  <title>Birthday wishes</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; color: #172033; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1100px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #fff; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 42px); margin-bottom: 20px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .page-header p { margin: 10px 0 0; color: #e0f2fe; line-height: 1.5; }',
        '    h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); }',
        '    .birthday-search { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; margin-bottom: 14px; padding: 16px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; }',
        '    .birthday-search label { display: grid; gap: 5px; color: #475569; font-size: 12px; font-weight: 600; }',
        '    .birthday-search input, .birthday-search button { padding: 9px 11px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }',
        '    .birthday-search button { border: 0; color: #fff; background: #2563eb; font-weight: 600; cursor: pointer; }',
        '    .results-count { margin: 10px 2px; color: #64748b; font-size: 14px; }',
        '    .wish-list { display: grid; gap: 12px; }',
        '    .wish-card { padding: 16px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .wish-card summary { color: #102a56; font-size: 18px; font-weight: 700; cursor: pointer; }',
        '    .wish-card[open] summary { margin-bottom: 8px; }',
        '    .wish-card p { margin: 7px 0; line-height: 1.5; overflow-wrap: anywhere; }',
        '    .wish-meta { color: #64748b; font-size: 13px; }',
        '    .wish-card a { color: #2563eb; font-weight: 600; text-decoration: none; }',
        '    .wish-card a:hover { text-decoration: underline; }',
        '    .empty-state { padding: 22px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; color: #64748b; }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="birthdays.html">Birthdays</a><a href="birthday_wishes.html">Birthday wishes</a><a href="calls.html">Call history</a></nav>',
        '    <header class="page-header">',
        '      <h1>Who wished you a happy birthday?</h1>',
        f'      <p>Enter your birthday to find incoming “Happy Birthday” messages on that month and day across all years. Searches all direct and group conversations; group wishes are attributed to the sender shown in the message. Dates use {html.escape(time_zone)}.</p>',
        '    </header>',
        '    <form id="birthdaySearch" class="birthday-search">',
        '      <label>Your birthday<input id="birthdayDate" type="date" required></label>',
        '      <button type="submit">Find birthday wishes</button>',
        '    </form>',
        '    <div id="resultsCount" class="results-count" aria-live="polite">Choose your birthday to search the archive.</div>',
        '    <main id="wishList" class="wish-list"></main>',
        '    <p id="emptyState" class="empty-state" hidden>No matching incoming birthday wishes were found for that month and day.</p>',
        '    <script id="birthdayWishData" type="application/json">',
        serialized_wishes,
        '    </script>',
        '    <script>',
        '      const birthdayWishes = JSON.parse(document.getElementById("birthdayWishData").textContent);',
        '      const birthdayForm = document.getElementById("birthdaySearch");',
        '      const birthdayDateInput = document.getElementById("birthdayDate");',
        '      const wishList = document.getElementById("wishList");',
        '      const resultsCount = document.getElementById("resultsCount");',
        '      const emptyState = document.getElementById("emptyState");',
        '      function showBirthdayWishes(value) {',
        '        if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(value)) return;',
        '        const monthDay = value.slice(5);',
        '        const matches = birthdayWishes.filter(function(wish) { return wish[2].slice(5) === monthDay; });',
        '        wishList.replaceChildren();',
        '        const bySender = new Map();',
        '        matches.forEach(function(wish) {',
        '          if (!bySender.has(wish[0])) bySender.set(wish[0], []);',
        '          bySender.get(wish[0]).push(wish);',
        '        });',
        '        bySender.forEach(function(senderWishes, sender) {',
        '          const card = document.createElement("details");',
        '          card.className = "wish-card";',
        '          const heading = document.createElement("summary");',
        '          heading.textContent = sender + " (" + senderWishes.length + " wishes)";',
        '          card.appendChild(heading);',
        '          senderWishes.forEach(function(wish) {',
        '            const detail = document.createElement("p");',
        '            detail.className = "wish-meta";',
        '            detail.textContent = wish[2] + " · " + wish[4];',
        '            card.appendChild(detail);',
        '            const quote = document.createElement("p");',
        '            quote.textContent = wish[3];',
        '            card.appendChild(quote);',
        '            const link = document.createElement("a");',
        '            const query = new URLSearchParams({ dateFrom: wish[2], dateTo: wish[2] });',
        '            link.href = encodeURIComponent(wish[1]) + ".html?" + query.toString();',
        '            link.textContent = "Open conversation";',
        '            card.appendChild(link);',
        '          });',
        '          wishList.appendChild(card);',
        '        });',
        '        resultsCount.textContent = "Found " + matches.length + " message(s) from " + bySender.size + " sender(s) across " + (new Set(matches.map(function(wish) { return wish[2].slice(0, 4); }))).size + " year(s).";',
        '        emptyState.hidden = matches.length > 0;',
        '      }',
        '      birthdayForm.addEventListener("submit", function(event) {',
        '        event.preventDefault();',
        '        showBirthdayWishes(birthdayDateInput.value);',
        '      });',
        '    </script>',
        '  </div>',
        '</body>',
        '</html>',
    ]
    with open(page_path, 'w', encoding='utf-8') as page:
        page.write('\n'.join(content))
    return page_path


def build_call_history(calls, output_dir, time_zone=DEFAULT_TIME_ZONE):
    """Render the combined call history from all extracted backups."""
    page_path = os.path.join(output_dir, 'calls.html')
    contact_totals = {}
    incoming_calls = 0
    outgoing_calls = 0
    for call in calls:
        key = call.get('phone_number') or str(call.get('address') or '').casefold()
        if not key:
            continue
        contact_total = contact_totals.setdefault(
            key,
            {
                'name': str(call.get('contact') or call.get('address') or 'Unknown'),
                'calls': 0,
                'duration': 0,
            },
        )
        contact_total['calls'] += 1
        try:
            contact_total['duration'] += max(0, int(float(call.get('duration') or 0)))
        except (TypeError, ValueError, OverflowError):
            pass
        if call.get('direction') == 'Outgoing':
            outgoing_calls += 1
        elif call.get('direction') in ('Incoming', 'Missed'):
            incoming_calls += 1

    def format_duration(duration):
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'

    top_call_contacts = sorted(
        contact_totals.values(),
        key=lambda contact: (-contact['calls'], contact['name'].casefold()),
    )[:5]
    top_duration_contacts = sorted(
        contact_totals.values(),
        key=lambda contact: (-contact['duration'], contact['name'].casefold()),
    )[:5]
    content = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        '  <title>Call history</title>',
        '  <style>',
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f2f7; margin: 0; color: #172033; }',
        '    .wrapper { width: calc(100% - 48px); max-width: 1200px; margin: 0 auto; padding: 28px 0 48px; }',
        '    .site-nav { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }',
        '    .site-nav a { color: #334155; text-decoration: none; font-size: 14px; font-weight: 600; padding: 9px 14px; border: 1px solid #dbe3ef; border-radius: 999px; background: #fff; }',
        '    .site-nav a:hover { color: #fff; background: #2563eb; border-color: #2563eb; }',
        '    .page-header { padding: clamp(24px, 4vw, 42px); margin-bottom: 20px; border-radius: 22px; color: #fff; background: linear-gradient(120deg, #102a56, #2563eb 68%, #38bdf8); box-shadow: 0 14px 32px #1e3a8a24; }',
        '    .page-header p { margin: 10px 0 0; color: #e0f2fe; }',
        '    h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); }',
        '    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-bottom: 20px; }',
        '    .stat-card { padding: 18px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; box-shadow: 0 4px 18px #0f172a0d; }',
        '    .stat-card h2 { margin: 0 0 12px; color: #475569; font-size: 14px; }',
        '    .stat-value { margin: 0; color: #102a56; font-size: 30px; font-weight: 700; }',
        '    .stat-note { margin: 5px 0 0; color: #64748b; font-size: 12px; }',
        '    .top-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }',
        '    .top-list li { display: flex; justify-content: space-between; gap: 10px; color: #334155; font-size: 13px; }',
        '    .top-list strong { white-space: nowrap; }',
        '    .filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; }',
        '    .filters label { display: grid; gap: 5px; color: #475569; font-size: 12px; font-weight: 600; }',
        '    .filters input { box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }',
        '    .call-count { color: #64748b; font-size: 13px; margin: 8px 2px; }',
        '    .table-wrap { overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; box-shadow: 0 4px 18px #0f172a0d; }',
        '    table { width: 100%; border-collapse: collapse; }',
        '    th, td { padding: 12px 14px; text-align: left; border-bottom: 1px solid #e2e8f0; }',
        '    th { background: #f1f5f9; color: #475569; font-size: 13px; white-space: nowrap; }',
        '    td { color: #334155; font-size: 14px; }',
        '    tr:last-child td { border-bottom: 0; }',
        '    tr.filtered-out { display: none; }',
        '    .empty-state { padding: 22px; color: #64748b; }',
        '    @media (max-width: 640px) { .wrapper { width: calc(100% - 24px); padding-top: 16px; } th, td { padding: 9px 7px; font-size: 12px; } }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="wrapper">',
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="birthdays.html">Birthdays</a><a href="birthday_wishes.html">Birthday wishes</a><a href="calls.html">Call history</a></nav>',
        '    <header class="page-header">',
        '      <h1>Call history</h1>',
        f'      <p>{len(calls):,} calls • Times shown in {html.escape(time_zone)}. Call data is included only when present in an extracted backup.</p>',
        '    </header>',
        '    <section class="stats" aria-label="Call statistics">',
        '      <article class="stat-card"><h2>Incoming calls</h2>',
        f'        <p class="stat-value">{incoming_calls:,}</p>',
        '        <p class="stat-note">Includes missed incoming calls</p></article>',
        '      <article class="stat-card"><h2>Outgoing calls</h2>',
        f'        <p class="stat-value">{outgoing_calls:,}</p></article>',
        '      <article class="stat-card"><h2>Top 5 by number of calls</h2>',
    ]
    if top_call_contacts:
        content.append('        <ol class="top-list">')
        for contact in top_call_contacts:
            call_label = 'call' if contact['calls'] == 1 else 'calls'
            content.append(
                f'<li><span>{html.escape(contact["name"])}</span>'
                f'<strong>{contact["calls"]:,} {call_label}</strong></li>'
            )
        content.append('        </ol>')
    else:
        content.append('        <p class="stat-note">No call records available.</p>')
    content.append('      </article><article class="stat-card"><h2>Top 5 by call duration</h2>')
    if top_duration_contacts:
        content.append('        <ol class="top-list">')
        for contact in top_duration_contacts:
            content.append(
                f'<li><span>{html.escape(contact["name"])}</span>'
                f'<strong>{format_duration(contact["duration"])}</strong></li>'
            )
        content.append('        </ol>')
    else:
        content.append('        <p class="stat-note">No call records available.</p>')
    content.extend([
        '      </article>',
        '    </section>',
        '    <section class="filters" aria-label="Filter call history">',
        '      <label>Search contact or number<input id="callSearch" type="search" placeholder="Name or number"></label>',
        '      <label>From date<input id="callDateFrom" type="date"></label>',
        '      <label>To date<input id="callDateTo" type="date"></label>',
        '      <label>From time<input id="callTimeFrom" type="time"></label>',
        '      <label>To time<input id="callTimeTo" type="time"></label>',
        '    </section>',
        f'    <div id="callCount" class="call-count" aria-live="polite">Showing {len(calls):,} calls</div>',
    ])

    if calls:
        content.extend([
            '    <div class="table-wrap"><table>',
            '      <thead><tr><th>Date and time</th><th>Contact</th><th>Number</th><th>Direction</th><th>Duration</th></tr></thead>',
            '      <tbody id="callList">',
        ])
        for call in calls:
            local_date_time = localize_message_datetime(call['date'], time_zone)
            date_text = local_date_time[:10]
            time_text = local_date_time[11:16]
            try:
                duration_seconds = max(0, int(float(call.get('duration') or 0)))
            except (TypeError, ValueError, OverflowError):
                duration_seconds = 0
            hours, remainder = divmod(duration_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            duration_text = f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'
            searchable = f"{call['contact']} {call['address']}".casefold()
            content.append(
                f'        <tr class="call-row" data-search="{html.escape(searchable, quote=True)}" '
                f'data-date="{html.escape(date_text, quote=True)}" data-time="{html.escape(time_text, quote=True)}">'
                f'<td>{html.escape(date_text)} {html.escape(time_text)}</td>'
                f'<td>{html.escape(str(call["contact"]))}</td>'
                f'<td>{html.escape(str(call["address"]))}</td>'
                f'<td>{html.escape(str(call["direction"]))}</td>'
                f'<td>{html.escape(duration_text)}</td></tr>'
            )
        content.extend([
            '      </tbody></table></div>',
            '    <script>',
            '      const callRows = Array.from(document.querySelectorAll(".call-row"));',
            '      const callSearch = document.getElementById("callSearch");',
            '      const callFilters = ["callDateFrom", "callDateTo", "callTimeFrom", "callTimeTo"].map(function(id) { return document.getElementById(id); });',
            '      const callCount = document.getElementById("callCount");',
            '      function filterCalls() {',
            '        const query = callSearch.value.trim().toLocaleLowerCase();',
            '        let visible = 0;',
            '        callRows.forEach(function(row) {',
            '          const date = row.dataset.date;',
            '          const time = row.dataset.time;',
            '          const matches = row.dataset.search.includes(query)',
            '            && (!callFilters[0].value || date >= callFilters[0].value)',
            '            && (!callFilters[1].value || date <= callFilters[1].value)',
            '            && (!callFilters[2].value || time >= callFilters[2].value)',
            '            && (!callFilters[3].value || time <= callFilters[3].value);',
            '          row.classList.toggle("filtered-out", !matches);',
            '          if (matches) visible += 1;',
            '        });',
            '        callCount.textContent = "Showing " + visible.toLocaleString() + " of " + callRows.length.toLocaleString() + " calls";',
            '      }',
            '      [callSearch].concat(callFilters).forEach(function(input) { input.addEventListener("input", filterCalls); input.addEventListener("change", filterCalls); });',
            '    </script>',
        ])
    else:
        content.append(
            '    <div class="table-wrap empty-state">No call history was found in the extracted backups.</div>'
        )

    content.extend(['  </div>', '</body>', '</html>'])
    with open(page_path, 'w', encoding='utf-8') as page:
        page.write('\n'.join(content))
    return page_path
