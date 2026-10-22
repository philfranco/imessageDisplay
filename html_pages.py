"""Render conversation, index, and search HTML pages."""

import hashlib
import html
import json
import os
from collections import Counter
from collections import defaultdict
from datetime import date, timedelta

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
        '    <nav class="site-nav"><a id="backToSearch" href="search.html">← Back to search</a><a href="index.html">Index</a><a href="calls.html">Call history</a></nav>',
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


def build_index(conversations, output_dir, overall_stats, time_zone=DEFAULT_TIME_ZONE):
    index_path = os.path.join(output_dir, 'index.html')
    daily_counts = overall_stats.get('daily_counts', {})
    years = sorted({day[:4] for day in daily_counts if len(day) >= 4})
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
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="calls.html">Call history</a></nav>',
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
        '    <a class="search-link" href="search.html">Search conversations <span aria-hidden="true">→</span></a>',
        '    <script>',
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


def build_search_index(conversations, output_dir, time_zone=DEFAULT_TIME_ZONE):
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
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="calls.html">Call history</a></nav>',
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

    search_data = []
    for display_name, filename, messages in conv_list:
        stats = summarize_messages(messages, time_zone)
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
        content.append(
            f'      <tr class="conv-item" data-name="{html.escape(searchable_name, quote=True)}" '
            f'data-search-index="{search_index}" '
            f'data-sort-name="{html.escape(display_name.lower())}" '
            f'data-sort-participants="{html.escape(participants_text.lower(), quote=True)}" '
            f'data-sort-messages="{stats["messages"]}" data-sort-attachments="{stats["attachments"]}" '
            f'data-sort-first-date="{html.escape(stats["first_date"])}" '
            f'data-sort-last-date="{html.escape(stats["last_date"])}">'
            f'<td><a data-conversation-file="{html.escape(filename, quote=True)}.html" '
            f'href="{html.escape(filename, quote=True)}.html">{html.escape(display_name)}</a></td>'
            f'<td class="participants">{html.escape(participants_text) if participants_text else "—"}</td>'
            f'<td><span class="filtered-message-count">{stats["messages"]:,}</span></td>'
            f'<td><span class="filtered-attachment-count">{stats["attachments"]:,}</span></td>'
            f'<td><span class="filtered-first-date">{html.escape(stats["first_date"])}</span></td>'
            f'<td><span class="filtered-last-date">{html.escape(stats["last_date"])}</span></td></tr>'
        )

    serialized_search_data = '[' + ','.join(search_data) + ']'
    content.extend([
        '    </tbody></table></div>',
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
        '      const conversationList = document.getElementById("conversationList");',
        '      const conversationItems = conversationList.querySelectorAll(".conv-item");',
        '      const searchMessages = JSON.parse(document.getElementById("searchMessageData").textContent);',
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
        '    <nav class="site-nav"><a href="index.html">Index</a><a href="search.html">Search conversations</a><a href="calls.html">Call history</a></nav>',
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
